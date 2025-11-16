# app/blueprints/bulk/routes.py
import traceback

from flask import render_template, request, jsonify, flash, redirect, url_for
from . import bulk_bp
from velocitycmdb.app.utils.database import get_db_connection
from .operations import (
    SetRoleOperation, SetSiteOperation,
    DeleteDevicesOperation, SetVendorOperation
)


@bulk_bp.route('/')
def index():
    """Bulk operations dashboard"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get available roles
            cursor.execute("SELECT id, name FROM device_roles ORDER BY name")
            roles = [dict(row) for row in cursor.fetchall()]

            # Get available sites
            cursor.execute("SELECT code, name FROM sites ORDER BY name")
            sites = [dict(row) for row in cursor.fetchall()]

            # Get available vendors
            cursor.execute("SELECT id, name FROM vendors ORDER BY name")
            vendors = [dict(row) for row in cursor.fetchall()]

            # Get recent operations
            cursor.execute("""
                SELECT 
                    operation_type, affected_count, executed_at
                FROM bulk_operations
                ORDER BY executed_at DESC
                LIMIT 10
            """)
            recent_ops = [dict(row) for row in cursor.fetchall()]

            return render_template('bulk/index.html',
                                   roles=roles,
                                   sites=sites,
                                   vendors=vendors,
                                   recent_operations=recent_ops)

    except Exception as e:
        flash(f'Error loading bulk operations: {str(e)}', 'error')
        return redirect(url_for('dashboard.index'))


@bulk_bp.route('/api/preview', methods=['POST'])
def preview():
    """Preview bulk operation (dry run)"""
    data = request.json
    operation_type = data.get('operation')
    filters = data.get('filters', {})
    values = data.get('values', {})

    operation_map = {
        'set_role': SetRoleOperation,
        'set_site': SetSiteOperation,
        'set_vendor': SetVendorOperation,
        'delete_devices': DeleteDevicesOperation
    }

    if operation_type not in operation_map:
        return jsonify({'error': 'Invalid operation type'}), 400

    try:
        with get_db_connection() as conn:
            operation = operation_map[operation_type](filters, values)
            result = operation.execute(conn, dry_run=True)

            return jsonify(result.to_dict())

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bulk_bp.route('/api/execute', methods=['POST'])
def execute():
    """Execute bulk operation after preview confirmation"""
    data = request.json
    operation_type = data.get('operation')
    filters = data.get('filters', {})
    values = data.get('values', {})
    preview_token = data.get('preview_token')
    confirmation_count = data.get('confirmation_count')

    if not preview_token:
        return jsonify({'error': 'Preview token required'}), 400

    operation_map = {
        'set_role': SetRoleOperation,
        'set_site': SetSiteOperation,
        'set_vendor': SetVendorOperation,
        'delete_devices': DeleteDevicesOperation
    }

    if operation_type not in operation_map:
        return jsonify({'error': 'Invalid operation type'}), 400

    try:
        with get_db_connection() as conn:
            operation = operation_map[operation_type](filters, values)

            # Verify preview token matches
            dry_result = operation.execute(conn, dry_run=True)
            if dry_result.preview_token != preview_token:
                return jsonify({
                    'error': 'Preview token mismatch - devices may have changed'
                }), 400

            # Verify confirmation count matches
            if confirmation_count != len(dry_result.affected_devices):
                return jsonify({
                    'error': f'Confirmation mismatch: expected {len(dry_result.affected_devices)}, got {confirmation_count}'
                }), 400

            # Execute for real
            result = operation.execute(conn, dry_run=False)

            return jsonify(result.to_dict())

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500