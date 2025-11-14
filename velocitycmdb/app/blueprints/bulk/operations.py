# app/blueprints/bulk/operations.py
from velocitycmdb.app.utils.database import get_db_connection
from typing import List, Dict, Any, Optional
import json
import hashlib
from datetime import datetime


class BulkOperationResult:
    def __init__(self, operation_type: str, dry_run: bool = True):
        self.operation_type = operation_type
        self.dry_run = dry_run
        self.affected_devices = []
        self.changes = []
        self.preview_token = None
        self.error = None

    def to_dict(self):
        return {
            'operation': self.operation_type,
            'dry_run': self.dry_run,
            'affected_count': len(self.affected_devices),
            'affected_devices': self.affected_devices,
            'changes': self.changes,
            'preview_token': self.preview_token,
            'error': self.error
        }


class BulkOperation:
    """Base class for bulk operations with dry-run support"""

    def __init__(self, filters: Dict[str, Any], values: Dict[str, Any]):
        self.filters = filters
        self.values = values
        self.operation_type = self.__class__.__name__

    def build_where_clause(self) -> tuple[str, list]:
        """Build WHERE clause from filters"""
        conditions = []
        params = []

        if 'name_pattern' in self.filters and self.filters['name_pattern']:
            pattern = self.filters['name_pattern']

            # Convert glob-style wildcards to SQL LIKE patterns
            # * becomes %
            # ? becomes _
            like_pattern = pattern.replace('*', '%').replace('?', '_')

            # Remove regex anchors if present
            like_pattern = like_pattern.lstrip('^').rstrip('$')

            conditions.append("d.name LIKE ?")
            params.append(like_pattern)

        if 'site_code' in self.filters and self.filters['site_code']:
            conditions.append("d.site_code = ?")
            params.append(self.filters['site_code'])

        if 'vendor_id' in self.filters and self.filters['vendor_id']:
            conditions.append("d.vendor_id = ?")
            params.append(self.filters['vendor_id'])

        if 'role_id' in self.filters and self.filters['role_id']:
            conditions.append("d.role_id = ?")
            params.append(self.filters['role_id'])

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params

    def get_affected_devices(self, conn) -> List[Dict]:
        """Get list of devices that would be affected"""
        where_clause, params = self.build_where_clause()

        query = f"""
            SELECT 
                d.id, d.name, d.site_code, d.model, 
                d.role_id, dr.name as role_name,
                d.vendor_id, v.name as vendor_name
            FROM devices d
            LEFT JOIN device_roles dr ON d.role_id = dr.id
            LEFT JOIN vendors v ON d.vendor_id = v.id
            WHERE {where_clause}
        """

        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def generate_preview_token(self, affected_devices: List[Dict]) -> str:
        """Generate token for preview-commit validation"""
        data = json.dumps({
            'operation': self.operation_type,
            'filters': self.filters,
            'values': self.values,
            'device_ids': sorted([d['id'] for d in affected_devices])
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def validate(self, conn) -> Optional[str]:
        """Validate operation before execution - return error message or None"""
        raise NotImplementedError

    def execute(self, conn, dry_run: bool = True) -> BulkOperationResult:
        """Execute the operation"""
        raise NotImplementedError

    def _log_operation(self, conn, result: BulkOperationResult):
        """Log bulk operation to audit table - standardized for all operations"""
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bulk_operations 
            (operation_type, filters, operation_values, affected_count, executed_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            self.operation_type,
            json.dumps(self.filters),
            json.dumps(self.values),
            len(result.affected_devices),
            datetime.now().isoformat()
        ))
        conn.commit()


class SetRoleOperation(BulkOperation):
    """Bulk set device role"""

    def validate(self, conn) -> Optional[str]:
        if 'role_id' not in self.values:
            return "role_id is required"

        # Verify role exists
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM device_roles WHERE id = ?",
                       (self.values['role_id'],))
        if not cursor.fetchone():
            return f"Role ID {self.values['role_id']} does not exist"

        # Require at least one filter
        if not any(self.filters.values()):
            return "At least one filter is required"

        return None

    def execute(self, conn, dry_run: bool = True) -> BulkOperationResult:
        result = BulkOperationResult('set_role', dry_run)

        # Validate first
        error = self.validate(conn)
        if error:
            result.error = error
            return result

        # Get affected devices
        affected = self.get_affected_devices(conn)
        result.affected_devices = affected

        if not affected:
            result.error = "No devices match the specified filters"
            return result

        # Build change preview
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM device_roles WHERE id = ?",
                       (self.values['role_id'],))
        new_role_name = cursor.fetchone()['name']

        for device in affected:
            result.changes.append({
                'device_id': device['id'],
                'device_name': device['name'],
                'field': 'role',
                'old_value': device['role_name'],
                'new_value': new_role_name
            })

        if dry_run:
            result.preview_token = self.generate_preview_token(affected)
            return result

        # Execute actual update
        device_ids = [d['id'] for d in affected]
        placeholders = ','.join('?' * len(device_ids))

        cursor.execute(f"""
            UPDATE devices 
            SET role_id = ? 
            WHERE id IN ({placeholders})
        """, [self.values['role_id']] + device_ids)

        conn.commit()

        # Log the operation
        self._log_operation(conn, result)

        return result


class SetSiteOperation(BulkOperation):
    """Bulk set device site"""

    def validate(self, conn) -> Optional[str]:
        if 'site_code' not in self.values:
            return "site_code is required"

        # Verify site exists
        cursor = conn.cursor()
        cursor.execute("SELECT code FROM sites WHERE code = ?",
                       (self.values['site_code'],))
        if not cursor.fetchone():
            return f"Site code {self.values['site_code']} does not exist"

        if not any(self.filters.values()):
            return "At least one filter is required"

        return None

    def execute(self, conn, dry_run: bool = True) -> BulkOperationResult:
        result = BulkOperationResult('set_site', dry_run)

        error = self.validate(conn)
        if error:
            result.error = error
            return result

        affected = self.get_affected_devices(conn)
        result.affected_devices = affected

        if not affected:
            result.error = "No devices match the specified filters"
            return result

        for device in affected:
            result.changes.append({
                'device_id': device['id'],
                'device_name': device['name'],
                'field': 'site_code',
                'old_value': device['site_code'],
                'new_value': self.values['site_code']
            })

        if dry_run:
            result.preview_token = self.generate_preview_token(affected)
            return result

        # Execute update
        device_ids = [d['id'] for d in affected]
        placeholders = ','.join('?' * len(device_ids))

        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE devices 
            SET site_code = ? 
            WHERE id IN ({placeholders})
        """, [self.values['site_code']] + device_ids)

        conn.commit()
        self._log_operation(conn, result)

        return result


class SetVendorOperation(BulkOperation):
    """Bulk set device vendor"""

    def validate(self, conn) -> Optional[str]:
        if 'vendor_id' not in self.values:
            return "vendor_id is required"

        # Verify vendor exists
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM vendors WHERE id = ?",
                       (self.values['vendor_id'],))
        if not cursor.fetchone():
            return f"Vendor ID {self.values['vendor_id']} does not exist"

        # Require at least one filter
        if not any(self.filters.values()):
            return "At least one filter is required"

        return None

    def execute(self, conn, dry_run: bool = True) -> BulkOperationResult:
        result = BulkOperationResult('set_vendor', dry_run)

        # Validate first
        error = self.validate(conn)
        if error:
            result.error = error
            return result

        # Get affected devices
        affected = self.get_affected_devices(conn)
        result.affected_devices = affected

        if not affected:
            result.error = "No devices match the specified filters"
            return result

        # Build change preview
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM vendors WHERE id = ?",
                       (self.values['vendor_id'],))
        new_vendor_name = cursor.fetchone()['name']

        for device in affected:
            result.changes.append({
                'device_id': device['id'],
                'device_name': device['name'],
                'field': 'vendor',
                'old_value': device['vendor_name'],
                'new_value': new_vendor_name
            })

        if dry_run:
            result.preview_token = self.generate_preview_token(affected)
            return result

        # Execute actual update
        device_ids = [d['id'] for d in affected]
        placeholders = ','.join('?' * len(device_ids))

        cursor.execute(f"""
            UPDATE devices 
            SET vendor_id = ? 
            WHERE id IN ({placeholders})
        """, [self.values['vendor_id']] + device_ids)

        conn.commit()

        # Log the operation
        self._log_operation(conn, result)

        return result


class DeleteDevicesOperation(BulkOperation):
    """Bulk delete devices - DESTRUCTIVE"""

    def validate(self, conn) -> Optional[str]:
        # Require minimum 2 filters for safety
        active_filters = sum(1 for v in self.filters.values() if v)
        if active_filters < 2:
            return "Delete operations require at least 2 filters for safety"

        # Check if any devices have recent captures (within 7 days)
        affected = self.get_affected_devices(conn)
        if not affected:
            return None

        device_ids = [d['id'] for d in affected]
        placeholders = ','.join('?' * len(device_ids))

        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT COUNT(*) as recent_count
            FROM device_captures_current
            WHERE device_id IN ({placeholders})
            AND datetime(capture_timestamp) > datetime('now', '-7 days')
        """, device_ids)

        recent = cursor.fetchone()['recent_count']
        if recent > 0:
            return f"Cannot delete: {recent} devices have captures within the last 7 days"

        return None

    def execute(self, conn, dry_run: bool = True) -> BulkOperationResult:
        result = BulkOperationResult('delete_devices', dry_run)

        error = self.validate(conn)
        if error:
            result.error = error
            return result

        affected = self.get_affected_devices(conn)
        result.affected_devices = affected

        if not affected:
            result.error = "No devices match the specified filters"
            return result

        for device in affected:
            result.changes.append({
                'device_id': device['id'],
                'device_name': device['name'],
                'action': 'DELETE',
                'vendor': device['vendor_name'],
                'site': device['site_code']
            })

        if dry_run:
            result.preview_token = self.generate_preview_token(affected)
            return result

        # Execute deletion (cascades will handle related records)
        device_ids = [d['id'] for d in affected]
        placeholders = ','.join('?' * len(device_ids))

        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM devices WHERE id IN ({placeholders})", device_ids)

        conn.commit()
        self._log_operation(conn, result)

        return result