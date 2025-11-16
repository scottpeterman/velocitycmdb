# app/blueprints/assets/routes.py - Extended with CRUD Operations
import json
import os

from flask import render_template, request, jsonify, redirect, url_for, flash
from . import assets_bp
from velocitycmdb.app.utils.database import get_db_connection
import sqlite3
import math
import re
from datetime import datetime

from ..notes.models import NoteAssociation


# ========== EXISTING READ OPERATIONS ==========

@assets_bp.route('/devices')
def devices():
    """Device inventory listing with pagination and filtering"""
    # Get query parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '').strip()
    vendor_filter = request.args.get('vendor', '')
    site_filter = request.args.get('site', '')
    role_filter = request.args.get('role', '')
    stack_filter = request.args.get('stack', '')

    # Ensure reasonable pagination limits
    per_page = min(max(per_page, 10), 100)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Base query using the v_device_status view
            base_query = """
                SELECT 
                    id, name, normalized_name, site_name, site_code,
                    vendor_name, device_type_name, model, os_version,
                    management_ip, is_stack, stack_count, have_sn,
                    current_captures, capture_types,
                    last_fingerprint, last_fingerprint_success,
                    last_updated, role_name, is_infrastructure
                FROM v_device_status
                WHERE 1=1
            """

            # Count query for pagination
            count_query = """
                SELECT COUNT(*) FROM v_device_status WHERE 1=1
            """

            # Build WHERE conditions
            conditions = []
            params = []

            if search:
                conditions.append("(name LIKE ? OR normalized_name LIKE ? OR management_ip LIKE ? OR model LIKE ?)")
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param, search_param])

            if vendor_filter:
                conditions.append("vendor_name = ?")
                params.append(vendor_filter)

            if site_filter:
                conditions.append("site_code = ?")
                params.append(site_filter)

            if role_filter:
                conditions.append("role_name = ?")
                params.append(role_filter)

            if stack_filter == 'yes':
                conditions.append("is_stack = 1")
            elif stack_filter == 'no':
                conditions.append("is_stack = 0")

            # Apply conditions
            if conditions:
                where_clause = " AND " + " AND ".join(conditions)
                base_query += where_clause
                count_query += where_clause

            # Get total count
            cursor.execute(count_query, params)
            total_devices = cursor.fetchone()[0]

            # Calculate pagination
            total_pages = math.ceil(total_devices / per_page)
            offset = (page - 1) * per_page

            # Add ordering and pagination
            base_query += " ORDER BY last_updated DESC, name LIMIT ? OFFSET ?"
            params.extend([per_page, offset])

            # Execute main query
            cursor.execute(base_query, params)
            devices = [dict(row) for row in cursor.fetchall()]

            # Get filter options
            cursor.execute(
                "SELECT DISTINCT vendor_name FROM v_device_status WHERE vendor_name IS NOT NULL ORDER BY vendor_name")
            vendors = [row[0] for row in cursor.fetchall()]

            cursor.execute(
                "SELECT DISTINCT site_code FROM v_device_status WHERE site_code IS NOT NULL ORDER BY site_code")
            sites = [row[0] for row in cursor.fetchall()]

            cursor.execute(
                "SELECT DISTINCT role_name FROM v_device_status WHERE role_name IS NOT NULL ORDER BY role_name")
            roles = [row[0] for row in cursor.fetchall()]

            # Pagination info
            pagination = {
                'page': page,
                'per_page': per_page,
                'total': total_devices,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'prev_num': page - 1 if page > 1 else None,
                'next_num': page + 1 if page < total_pages else None
            }

            return render_template('assets/devices.html',
                                   devices=devices,
                                   pagination=pagination,
                                   vendors=vendors,
                                   sites=sites,
                                   roles=roles,
                                   filters={
                                       'search': search,
                                       'vendor': vendor_filter,
                                       'site': site_filter,
                                       'role': role_filter,
                                       'stack': stack_filter
                                   })

    except Exception as e:
        flash(f'Database error: {str(e)}', 'error')
        return render_template('assets/devices.html',
                               devices=[],
                               pagination={'page': 1, 'total': 0, 'total_pages': 0},
                               vendors=[], sites=[], roles=[],
                               filters={})


@assets_bp.route('/devices/<int:device_id>')
def device_detail(device_id):
    """Device detail page with full information"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get device details from view
            cursor.execute("SELECT * FROM v_device_status WHERE id = ?", (device_id,))
            device = cursor.fetchone()

            if not device:
                flash('Device not found', 'error')
                return redirect(url_for('assets.devices'))

            device = dict(device)

            # Get device serials
            cursor.execute("""
                SELECT serial, is_primary 
                FROM device_serials 
                WHERE device_id = ? 
                ORDER BY is_primary DESC, serial
            """, (device_id,))
            serials = [dict(row) for row in cursor.fetchall()]

            # Get stack members if it's a stack
            stack_members = []
            if device['is_stack']:
                cursor.execute("""
                    SELECT serial, position, model, is_master 
                    FROM stack_members 
                    WHERE device_id = ? 
                    ORDER BY position, serial
                """, (device_id,))
                stack_members = [dict(row) for row in cursor.fetchall()]

            # Get components
            cursor.execute("""
                SELECT name, description, serial, position, type, subtype,
                       extraction_source, extraction_confidence
                FROM components 
                WHERE device_id = ? 
                ORDER BY position, name
            """, (device_id,))
            components = [dict(row) for row in cursor.fetchall()]

            # Get current captures
            cursor.execute("""
                SELECT capture_type, file_path, file_size, capture_timestamp,
                       extraction_success, command_used
                FROM device_captures_current 
                WHERE device_id = ? 
                ORDER BY capture_type
            """, (device_id,))
            captures = [dict(row) for row in cursor.fetchall()]

            # Get recent fingerprint extractions
            cursor.execute("""
                SELECT extraction_timestamp, template_used, template_score,
                       extraction_success, fields_extracted, total_fields_available,
                       command_count, extraction_duration_ms
                FROM fingerprint_extractions 
                WHERE device_id = ? 
                ORDER BY extraction_timestamp DESC 
                LIMIT 5
            """, (device_id,))
            fingerprints = [dict(row) for row in cursor.fetchall()]

            device_notes = NoteAssociation.get_for_entity('device', str(device_id))

            return render_template('assets/device_detail.html',
                                   device=device,
                                   serials=serials,
                                   stack_members=stack_members,
                                   components=components,
                                   captures=captures,
                                   fingerprints=fingerprints,
                                   device_notes=device_notes)

    except Exception as e:
        flash(f'Database error: {str(e)}', 'error')
        return redirect(url_for('assets.devices'))


# ========== NEW CREATE/UPDATE/DELETE OPERATIONS ==========

@assets_bp.route('/devices/create', methods=['GET', 'POST'])
def device_create():
    """Create a new device"""
    if request.method == 'POST':
        try:
            # Extract form data
            name = request.form.get('name', '').strip()
            site_code = request.form.get('site_code', '').strip() or None
            vendor_id = request.form.get('vendor_id', type=int) or None
            device_type_id = request.form.get('device_type_id', type=int) or None
            role_id = request.form.get('role_id', type=int) or None
            model = request.form.get('model', '').strip() or None
            os_version = request.form.get('os_version', '').strip() or None
            management_ip = request.form.get('management_ip', '').strip() or None
            processor_id = request.form.get('processor_id', '').strip() or None

            # Validation
            if not name:
                flash('Device name is required', 'error')
                return redirect(url_for('assets.device_create'))

            # Validate IP address format if provided
            if management_ip and not is_valid_ip(management_ip):
                flash('Invalid IP address format', 'error')
                return redirect(url_for('assets.device_create'))

            # Generate normalized name
            normalized_name = normalize_device_name(name)

            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Check for duplicate normalized name
                cursor.execute("SELECT id FROM devices WHERE normalized_name = ?", (normalized_name,))
                if cursor.fetchone():
                    flash(f'Device with normalized name "{normalized_name}" already exists', 'error')
                    return redirect(url_for('assets.device_create'))

                # Insert device
                cursor.execute("""
                    INSERT INTO devices (
                        name, normalized_name, site_code, vendor_id, device_type_id,
                        role_id, model, os_version, management_ip, processor_id,
                        timestamp, source_system
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name, normalized_name, site_code, vendor_id, device_type_id,
                    role_id, model, os_version, management_ip, processor_id,
                    datetime.now().isoformat(), 'manual_entry'
                ))

                device_id = cursor.lastrowid
                conn.commit()

                flash(f'Device "{name}" created successfully', 'success')
                return redirect(url_for('assets.device_detail', device_id=device_id))

        except sqlite3.IntegrityError as e:
            flash(f'Database constraint error: {str(e)}', 'error')
            return redirect(url_for('assets.device_create'))
        except Exception as e:
            flash(f'Error creating device: {str(e)}', 'error')
            return redirect(url_for('assets.device_create'))

    # GET request - show form
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get reference data for dropdowns
            cursor.execute("SELECT code, name FROM sites ORDER BY name")
            sites = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT id, name FROM vendors ORDER BY name")
            vendors = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT id, name FROM device_types ORDER BY name")
            device_types = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT id, name FROM device_roles ORDER BY name")
            roles = [dict(row) for row in cursor.fetchall()]

            return render_template('assets/device_form.html',
                                   device=None,
                                   sites=sites,
                                   vendors=vendors,
                                   device_types=device_types,
                                   roles=roles,
                                   form_title='Create Device')
    except Exception as e:
        flash(f'Error loading form data: {str(e)}', 'error')
        return redirect(url_for('assets.devices'))


@assets_bp.route('/devices/<int:device_id>/edit', methods=['GET', 'POST'])
def device_edit(device_id):
    """Edit an existing device"""
    if request.method == 'POST':
        try:
            # Extract form data
            name = request.form.get('name', '').strip()
            site_code = request.form.get('site_code', '').strip() or None
            vendor_id = request.form.get('vendor_id', type=int) or None
            device_type_id = request.form.get('device_type_id', type=int) or None
            role_id = request.form.get('role_id', type=int) or None
            model = request.form.get('model', '').strip() or None
            os_version = request.form.get('os_version', '').strip() or None
            management_ip = request.form.get('management_ip', '').strip() or None
            processor_id = request.form.get('processor_id', '').strip() or None

            # Validation
            if not name:
                flash('Device name is required', 'error')
                return redirect(url_for('assets.device_edit', device_id=device_id))

            if management_ip and not is_valid_ip(management_ip):
                flash('Invalid IP address format', 'error')
                return redirect(url_for('assets.device_edit', device_id=device_id))

            # Generate normalized name
            normalized_name = normalize_device_name(name)

            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Check if device exists
                cursor.execute("SELECT id, normalized_name FROM devices WHERE id = ?", (device_id,))
                existing = cursor.fetchone()
                if not existing:
                    flash('Device not found', 'error')
                    return redirect(url_for('assets.devices'))

                # Check for duplicate normalized name (excluding current device)
                cursor.execute(
                    "SELECT id FROM devices WHERE normalized_name = ? AND id != ?",
                    (normalized_name, device_id)
                )
                if cursor.fetchone():
                    flash(f'Another device with normalized name "{normalized_name}" already exists', 'error')
                    return redirect(url_for('assets.device_edit', device_id=device_id))

                # Update device
                cursor.execute("""
                    UPDATE devices SET
                        name = ?, normalized_name = ?, site_code = ?, vendor_id = ?,
                        device_type_id = ?, role_id = ?, model = ?, os_version = ?,
                        management_ip = ?, processor_id = ?
                    WHERE id = ?
                """, (
                    name, normalized_name, site_code, vendor_id, device_type_id,
                    role_id, model, os_version, management_ip, processor_id, device_id
                ))

                conn.commit()

                flash(f'Device "{name}" updated successfully', 'success')
                return redirect(url_for('assets.device_detail', device_id=device_id))

        except sqlite3.IntegrityError as e:
            flash(f'Database constraint error: {str(e)}', 'error')
            return redirect(url_for('assets.device_edit', device_id=device_id))
        except Exception as e:
            flash(f'Error updating device: {str(e)}', 'error')
            return redirect(url_for('assets.device_edit', device_id=device_id))

    # GET request - show form with existing data
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get device
            cursor.execute("""
                SELECT id, name, normalized_name, site_code, vendor_id, device_type_id,
                       role_id, model, os_version, management_ip, processor_id
                FROM devices WHERE id = ?
            """, (device_id,))
            device = cursor.fetchone()

            if not device:
                flash('Device not found', 'error')
                return redirect(url_for('assets.devices'))

            device = dict(device)

            # Get reference data for dropdowns
            cursor.execute("SELECT code, name FROM sites ORDER BY name")
            sites = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT id, name FROM vendors ORDER BY name")
            vendors = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT id, name FROM device_types ORDER BY name")
            device_types = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT id, name FROM device_roles ORDER BY name")
            roles = [dict(row) for row in cursor.fetchall()]

            return render_template('assets/device_form.html',
                                   device=device,
                                   sites=sites,
                                   vendors=vendors,
                                   device_types=device_types,
                                   roles=roles,
                                   form_title='Edit Device')
    except Exception as e:
        flash(f'Error loading device: {str(e)}', 'error')
        return redirect(url_for('assets.devices'))


@assets_bp.route('/devices/<int:device_id>/delete', methods=['POST'])
def device_delete(device_id):
    """Delete a device"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get device name for confirmation message
            cursor.execute("SELECT name FROM devices WHERE id = ?", (device_id,))
            device = cursor.fetchone()

            if not device:
                flash('Device not found', 'error')
                return redirect(url_for('assets.devices'))

            device_name = device[0]

            # Check for related records
            cursor.execute("SELECT COUNT(*) FROM device_captures_current WHERE device_id = ?", (device_id,))
            capture_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM fingerprint_extractions WHERE device_id = ?", (device_id,))
            fingerprint_count = cursor.fetchone()[0]

            # Require confirmation if device has data
            confirm = request.form.get('confirm', 'no')
            if (capture_count > 0 or fingerprint_count > 0) and confirm != 'yes':
                flash(
                    f'Device "{device_name}" has {capture_count} captures and {fingerprint_count} fingerprints. '
                    'Deleting will remove all related data. Please confirm deletion.',
                    'warning'
                )
                return redirect(url_for('assets.device_detail', device_id=device_id))

            # Delete related records in correct order
            # Delete capture snapshots first (they reference device_captures_current)
            cursor.execute("DELETE FROM capture_snapshots WHERE device_id = ?", (device_id,))

            # Delete capture changes (they reference capture_snapshots and devices)
            cursor.execute("DELETE FROM capture_changes WHERE device_id = ?", (device_id,))

            # Delete current captures
            cursor.execute("DELETE FROM device_captures_current WHERE device_id = ?", (device_id,))

            # Delete fingerprint extractions
            cursor.execute("DELETE FROM fingerprint_extractions WHERE device_id = ?", (device_id,))

            # Delete components
            cursor.execute("DELETE FROM components WHERE device_id = ?", (device_id,))

            # Delete stack members
            cursor.execute("DELETE FROM stack_members WHERE device_id = ?", (device_id,))

            # Delete device serials
            cursor.execute("DELETE FROM device_serials WHERE device_id = ?", (device_id,))

            # Finally delete the device itself
            cursor.execute("DELETE FROM devices WHERE id = ?", (device_id,))

            conn.commit()

            flash(f'Device "{device_name}" deleted successfully', 'success')
            return redirect(url_for('assets.devices'))

    except sqlite3.IntegrityError as e:
        flash(f'Database constraint error: {str(e)}', 'error')
        return redirect(url_for('assets.device_detail', device_id=device_id))
    except Exception as e:
        flash(f'Error deleting device: {str(e)}', 'error')
        return redirect(url_for('assets.device_detail', device_id=device_id))


@assets_bp.route('/devices/export')
def devices_export():
    """Export devices to CSV with current filters"""
    from flask import make_response
    import io
    import csv

    # Get filter parameters (same as main devices route)
    search = request.args.get('search', '').strip()
    vendor_filter = request.args.get('vendor', '')
    site_filter = request.args.get('site', '')
    role_filter = request.args.get('role', '')
    stack_filter = request.args.get('stack', '')

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Use same query logic as devices route
            base_query = """
                SELECT 
                    name, normalized_name, site_code, site_name,
                    vendor_name, device_type_name, model, os_version,
                    management_ip, role_name, is_infrastructure,
                    is_stack, stack_count, have_sn,
                    current_captures, capture_types,
                    last_fingerprint, last_fingerprint_success,
                    last_updated
                FROM v_device_status
                WHERE 1=1
            """

            conditions = []
            params = []

            if search:
                conditions.append("(name LIKE ? OR normalized_name LIKE ? OR management_ip LIKE ? OR model LIKE ?)")
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param, search_param])

            if vendor_filter:
                conditions.append("vendor_name = ?")
                params.append(vendor_filter)

            if site_filter:
                conditions.append("site_code = ?")
                params.append(site_filter)

            if role_filter:
                conditions.append("role_name = ?")
                params.append(role_filter)

            if stack_filter == 'yes':
                conditions.append("is_stack = 1")
            elif stack_filter == 'no':
                conditions.append("is_stack = 0")

            if conditions:
                base_query += " AND " + " AND ".join(conditions)

            base_query += " ORDER BY last_updated DESC, name"

            cursor.execute(base_query, params)
            devices = [dict(row) for row in cursor.fetchall()]

            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow([
                'Name', 'Normalized Name', 'Site Code', 'Site Name',
                'Vendor', 'Device Type', 'Model', 'OS Version',
                'Management IP', 'Role', 'Is Infrastructure',
                'Is Stack', 'Stack Count', 'Has Serials',
                'Current Captures', 'Capture Types',
                'Last Fingerprint', 'Fingerprint Success',
                'Last Updated'
            ])

            # Write device rows
            for device in devices:
                writer.writerow([
                    device['name'],
                    device['normalized_name'],
                    device['site_code'] or '',
                    device['site_name'] or '',
                    device['vendor_name'] or '',
                    device['device_type_name'] or '',
                    device['model'] or '',
                    device['os_version'] or '',
                    device['management_ip'] or '',
                    device['role_name'] or '',
                    'Yes' if device['is_infrastructure'] else 'No',
                    'Yes' if device['is_stack'] else 'No',
                    device['stack_count'] or 0,
                    'Yes' if device['have_sn'] else 'No',
                    device['current_captures'] or 0,
                    device['capture_types'] or 0,
                    device['last_fingerprint'] or '',
                    'Yes' if device['last_fingerprint_success'] else 'No',
                    device['last_updated'] or ''
                ])

            # Create response
            output.seek(0)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # Build filename based on filters
            filename_parts = ['devices']
            if search:
                filename_parts.append(f'search_{search[:20]}')
            if vendor_filter:
                filename_parts.append(vendor_filter)
            if site_filter:
                filename_parts.append(site_filter)
            if role_filter:
                filename_parts.append(role_filter)
            if stack_filter:
                filename_parts.append(f'stack_{stack_filter}')

            filename = f"{'_'.join(filename_parts)}_{timestamp}.csv"

            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'

            return response

    except Exception as e:
        flash(f'Export error: {str(e)}', 'error')
        return redirect(url_for('assets.devices'))


@assets_bp.route('/api/devices/stats')
def api_device_stats():
    """API endpoint for device statistics"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get device counts by vendor
            cursor.execute("""
                SELECT vendor_name, COUNT(*) as count,
                       SUM(CASE WHEN is_stack = 1 THEN 1 ELSE 0 END) as stacks,
                       SUM(CASE WHEN have_sn = 1 THEN 1 ELSE 0 END) as with_serials,
                       SUM(current_captures) as total_captures
                FROM v_device_status 
                WHERE vendor_name IS NOT NULL
                GROUP BY vendor_name 
                ORDER BY count DESC
            """)
            vendor_stats = [dict(row) for row in cursor.fetchall()]

            # Get device counts by site
            cursor.execute("""
                SELECT site_code, site_name, COUNT(*) as count,
                       SUM(CASE WHEN is_stack = 1 THEN 1 ELSE 0 END) as stacks,
                       COUNT(DISTINCT vendor_name) as vendor_count
                FROM v_device_status 
                WHERE site_code IS NOT NULL
                GROUP BY site_code, site_name 
                ORDER BY count DESC
            """)
            site_stats = [dict(row) for row in cursor.fetchall()]

            return jsonify({
                'vendor_stats': vendor_stats,
                'site_stats': site_stats,
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@assets_bp.route('/api/devices/<int:device_id>/captures')
def api_device_captures(device_id):
    """API endpoint for device capture history"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get capture history from archive
            cursor.execute("""
                SELECT capture_type, file_path, file_size, capture_timestamp,
                       extraction_success, archived_timestamp
                FROM device_captures_archive 
                WHERE device_id = ? 
                ORDER BY capture_timestamp DESC 
                LIMIT 50
            """, (device_id,))
            archive = [dict(row) for row in cursor.fetchall()]

            # Get current captures
            cursor.execute("""
                SELECT capture_type, file_path, file_size, capture_timestamp,
                       extraction_success, command_used
                FROM device_captures_current 
                WHERE device_id = ?
            """, (device_id,))
            current = [dict(row) for row in cursor.fetchall()]

            return jsonify({
                'current_captures': current,
                'archive_captures': archive,
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


# ========== UTILITY FUNCTIONS ==========

def normalize_device_name(name):
    """Normalize device name for uniqueness checking"""
    # Remove special characters, convert to lowercase
    normalized = re.sub(r'[^a-z0-9-]', '', name.lower())
    return normalized


def is_valid_ip(ip_address):
    """Validate IPv4 address format"""
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip_address):
        return False

    # Check each octet is 0-255
    octets = ip_address.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


@assets_bp.route('/api/devices/<int:device_id>/capture/<capture_type>')
def api_device_capture_content(device_id, capture_type):
    """API endpoint to get capture file content - reads from snapshots"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Try to get from snapshots first (new method)
            cursor.execute("""
                SELECT cs.content, cs.file_path, cs.file_size, cs.captured_at
                FROM capture_snapshots cs
                WHERE cs.device_id = ? AND cs.capture_type = ?
                ORDER BY cs.captured_at DESC
                LIMIT 1
            """, (device_id, capture_type))

            snapshot = cursor.fetchone()

            if snapshot:
                # Found in snapshots - return directly from database
                content = snapshot[0]
                file_path = snapshot[1]
                file_size = snapshot[2]
                capture_timestamp = snapshot[3]

                return jsonify({
                    'content': content,
                    'size': file_size,
                    'lines': len(content.splitlines()),
                    'capture_type': capture_type,
                    'timestamp': capture_timestamp,
                    'file_path': file_path,
                    'source': 'database_snapshot',
                    'status': 'success'
                })

            # Fallback: try device_captures_current and read from disk
            cursor.execute("""
                SELECT file_path, file_size, capture_timestamp
                FROM device_captures_current 
                WHERE device_id = ? AND capture_type = ?
            """, (device_id, capture_type))

            capture = cursor.fetchone()
            if not capture:
                return jsonify({
                    'error': 'Capture not found in database or snapshots',
                    'status': 'error'
                }), 404

            file_path = capture[0]
            file_size = capture[1]
            capture_timestamp = capture[2]

            # Try to read from disk
            if not os.path.exists(file_path):
                return jsonify({
                    'error': 'Capture file not found on disk and no snapshot available',
                    'status': 'error'
                }), 404

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            return jsonify({
                'content': content,
                'size': file_size,
                'lines': len(content.splitlines()),
                'capture_type': capture_type,
                'timestamp': capture_timestamp,
                'file_path': file_path,
                'source': 'disk_file',
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@assets_bp.route('/api/devices/<int:device_id>/inventory')
def api_device_inventory_content(device_id):
    """API endpoint to get full device inventory as formatted text"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check if device exists
            cursor.execute("SELECT name, normalized_name FROM devices WHERE id = ?", (device_id,))
            device = cursor.fetchone()
            if not device:
                return jsonify({'error': 'Device not found', 'status': 'error'}), 404

            # Get all components
            cursor.execute("""
                SELECT name, description, serial, position, type, subtype,
                       extraction_source, extraction_confidence
                FROM components 
                WHERE device_id = ? 
                ORDER BY position, name
            """, (device_id,))

            components = [dict(row) for row in cursor.fetchall()]

            if not components:
                content = f"No inventory data available for {device[0]}"
            else:
                # Format as text
                lines = [
                    f"Device Inventory Report",
                    f"=" * 80,
                    f"Device: {device[0]} ({device[1]})",
                    f"Total Components: {len(components)}",
                    f"=" * 80,
                    ""
                ]

                for i, comp in enumerate(components, 1):
                    lines.append(f"Component {i}:")
                    lines.append(f"  Name: {comp['name']}")
                    if comp['description']:
                        lines.append(f"  Description: {comp['description']}")
                    if comp['serial']:
                        lines.append(f"  Serial: {comp['serial']}")
                    if comp['position']:
                        lines.append(f"  Position: {comp['position']}")
                    if comp['type']:
                        lines.append(f"  Type: {comp['type']}")
                    if comp['subtype']:
                        lines.append(f"  Subtype: {comp['subtype']}")
                    if comp['extraction_source']:
                        lines.append(f"  Source: {comp['extraction_source']}")
                    if comp['extraction_confidence']:
                        lines.append(f"  Confidence: {comp['extraction_confidence']:.1%}")
                    lines.append("")

                content = "\n".join(lines)

            return jsonify({
                'content': content,
                'component_count': len(components),
                'device_name': device[0],
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


@assets_bp.route('/api/devices/<int:device_id>/fingerprint/<timestamp>')
def api_device_fingerprint_content(device_id, timestamp):
    """API endpoint to get fingerprint JSON data"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Check if device exists
            cursor.execute("SELECT name, normalized_name FROM devices WHERE id = ?", (device_id,))
            device = cursor.fetchone()
            if not device:
                return jsonify({'error': 'Device not found', 'status': 'error'}), 404

            # Fingerprint files are typically stored in pcng/fingerprints/{normalized_name}_{timestamp}.json
            # Adjust the path based on your actual structure
            normalized_name = device[1]

            # Try different possible paths
            possible_paths = [
                f"pcng/fingerprints/{normalized_name}_{timestamp}.json",
                f"pcng/fingerprints/{normalized_name}.json",
                f"fingerprints/{normalized_name}_{timestamp}.json",
                f"fingerprints/{normalized_name}.json",
            ]

            fingerprint_data = None
            found_path = None

            for path in possible_paths:
                if os.path.exists(path):
                    found_path = path
                    with open(path, 'r', encoding='utf-8') as f:
                        fingerprint_data = json.load(f)
                    break

            if not fingerprint_data:
                # Try to get from database if file not found
                cursor.execute("""
                    SELECT template_used, template_score, extraction_success,
                           fields_extracted, total_fields_available
                    FROM fingerprint_extractions 
                    WHERE device_id = ? AND extraction_timestamp = ?
                """, (device_id, timestamp))

                fp_record = cursor.fetchone()
                if fp_record:
                    fingerprint_data = {
                        'device_name': device[0],
                        'extraction_timestamp': timestamp,
                        'template_used': fp_record[0],
                        'template_score': fp_record[1],
                        'extraction_success': fp_record[2],
                        'fields_extracted': fp_record[3],
                        'total_fields_available': fp_record[4],
                        'note': 'Fingerprint file not found on disk. Showing database metadata only.'
                    }
                else:
                    return jsonify({'error': 'Fingerprint not found', 'status': 'error'}), 404

            return jsonify({
                'fingerprint': fingerprint_data,
                'device_name': device[0],
                'timestamp': timestamp,
                'file_path': found_path,
                'status': 'success'
            })

    except json.JSONDecodeError as e:
        return jsonify({'error': f'Invalid JSON in fingerprint file: {str(e)}', 'status': 'error'}), 500
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500


# ========== UTILITY FUNCTION FOR FILE READING ==========

def safe_read_file(file_path, max_size_mb=10):
    """
    Safely read a file with size checking

    Args:
        file_path: Path to file
        max_size_mb: Maximum file size to read in MB

    Returns:
        tuple: (success: bool, content: str or error message)
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return False, "File not found"

        # Check file size
        file_size = os.path.getsize(file_path)
        max_size_bytes = max_size_mb * 1024 * 1024

        if file_size > max_size_bytes:
            return False, f"File too large ({file_size / 1024 / 1024:.1f}MB). Maximum size is {max_size_mb}MB"

        # Read file
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        return True, content

    except Exception as e:
        return False, f"Error reading file: {str(e)}"