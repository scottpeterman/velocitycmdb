from flask import render_template, request, redirect, url_for, flash
from velocitycmdb.app.blueprints.auth.routes import login_required
from velocitycmdb.app.utils.database import get_db_connection
import sqlite3
import json
from . import roles_bp

@roles_bp.route('/')
@login_required
def index():
    """List all device roles with device counts"""
    with get_db_connection() as conn:
        roles = conn.execute('''
            SELECT 
                dr.id,
                dr.name,
                dr.description,
                dr.is_infrastructure,
                dr.port_count_min,
                dr.port_count_max,
                COUNT(d.id) as device_count
            FROM device_roles dr
            LEFT JOIN devices d ON dr.id = d.role_id
            GROUP BY dr.id
            ORDER BY device_count DESC, dr.name
        ''').fetchall()

        # Fixed stats query
        stats = conn.execute('''
            SELECT 
                COUNT(DISTINCT dr.id) as total_roles,
                COUNT(DISTINCT CASE WHEN d.id IS NOT NULL THEN dr.id END) as roles_in_use
            FROM device_roles dr
            LEFT JOIN devices d ON dr.id = d.role_id
        ''').fetchone()

    return render_template('roles/index.html', roles=roles, stats=stats)

@roles_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create new device role"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        is_infrastructure = 1 if request.form.get('is_infrastructure') else 0
        port_count_min = request.form.get('port_count_min', '').strip()
        port_count_max = request.form.get('port_count_max', '').strip()

        # Validation
        if not name:
            flash('Role name is required', 'error')
            return render_template('roles/form.html', role=None, form_data=request.form)

        # Convert port counts to integers or None
        try:
            port_count_min = int(port_count_min) if port_count_min else None
            port_count_max = int(port_count_max) if port_count_max else None
        except ValueError:
            flash('Port counts must be valid numbers', 'error')
            return render_template('roles/form.html', role=None, form_data=request.form)

        with get_db_connection() as conn:
            try:
                conn.execute('''
                    INSERT INTO device_roles 
                    (name, description, is_infrastructure, port_count_min, port_count_max)
                    VALUES (?, ?, ?, ?, ?)
                ''', (name, description, is_infrastructure, port_count_min, port_count_max))
                conn.commit()
                flash(f'Role "{name}" created successfully', 'success')
                return redirect(url_for('roles.index'))
            except sqlite3.IntegrityError:
                flash(f'Role name "{name}" already exists', 'error')
                return render_template('roles/form.html', role=None, form_data=request.form)

    return render_template('roles/form.html', role=None, form_data=None)


@roles_bp.route('/<int:role_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(role_id):
    """Edit existing device role"""
    with get_db_connection() as conn:
        role = conn.execute('SELECT * FROM device_roles WHERE id = ?', (role_id,)).fetchone()

        if not role:
            flash('Role not found', 'error')
            return redirect(url_for('roles.index'))

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            is_infrastructure = 1 if request.form.get('is_infrastructure') else 0
            port_count_min = request.form.get('port_count_min', '').strip()
            port_count_max = request.form.get('port_count_max', '').strip()

            if not name:
                flash('Role name is required', 'error')
                return render_template('roles/form.html', role=role, form_data=request.form)

            try:
                port_count_min = int(port_count_min) if port_count_min else None
                port_count_max = int(port_count_max) if port_count_max else None
            except ValueError:
                flash('Port counts must be valid numbers', 'error')
                return render_template('roles/form.html', role=role, form_data=request.form)

            try:
                conn.execute('''
                    UPDATE device_roles 
                    SET name = ?, description = ?, is_infrastructure = ?,
                        port_count_min = ?, port_count_max = ?
                    WHERE id = ?
                ''', (name, description, is_infrastructure, port_count_min, port_count_max, role_id))
                conn.commit()
                flash(f'Role "{name}" updated successfully', 'success')
                return redirect(url_for('roles.index'))
            except sqlite3.IntegrityError:
                flash(f'Role name "{name}" already exists', 'error')
                return render_template('roles/form.html', role=role, form_data=request.form)

    return render_template('roles/form.html', role=role, form_data=None)


@roles_bp.route('/<int:role_id>/delete', methods=['POST'])
@login_required
def delete(role_id):
    """Delete device role (only if no devices)"""
    with get_db_connection() as conn:
        device_count = conn.execute(
            'SELECT COUNT(*) as count FROM devices WHERE role_id = ?',
            (role_id,)
        ).fetchone()['count']

        if device_count > 0:
            flash(f'Cannot delete role: {device_count} devices are still assigned to this role', 'error')
            return redirect(url_for('roles.index'))

        role = conn.execute('SELECT * FROM device_roles WHERE id = ?', (role_id,)).fetchone()
        if not role:
            flash('Role not found', 'error')
            return redirect(url_for('roles.index'))

        conn.execute('DELETE FROM device_roles WHERE id = ?', (role_id,))
        conn.commit()
        flash(f'Role "{role["name"]}" deleted successfully', 'success')

    return redirect(url_for('roles.index'))


@roles_bp.route('/<int:role_id>/detail')
@login_required
def detail(role_id):
    """View role details with device list"""
    with get_db_connection() as conn:
        # Get role info
        role = conn.execute('''
            SELECT * FROM device_roles WHERE id = ?
        ''', (role_id,)).fetchone()

        if not role:
            flash('Role not found', 'error')
            return redirect(url_for('roles.index'))

        # Get device count
        device_count = conn.execute('''
            SELECT COUNT(*) as count FROM devices WHERE role_id = ?
        ''', (role_id,)).fetchone()['count']

        # Get devices - query devices table directly with joins
        devices = conn.execute('''
            SELECT 
                d.id,
                d.name,
                d.normalized_name,
                s.name as site_name,
                s.code as site_code,
                v.name as vendor_name,
                d.model,
                d.os_version,
                d.management_ip,
                d.is_stack,
                d.stack_count,
                COUNT(dcc.id) as current_captures,
                COUNT(DISTINCT dcc.capture_type) as capture_types,
                MAX(fe.extraction_timestamp) as last_fingerprint,
                MAX(fe.extraction_success) as last_fingerprint_success
            FROM devices d
            LEFT JOIN sites s ON d.site_code = s.code
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN device_captures_current dcc ON d.id = dcc.device_id
            LEFT JOIN fingerprint_extractions fe ON d.id = fe.device_id
            WHERE d.role_id = ?
            GROUP BY d.id
            ORDER BY d.name
        ''', (role_id,)).fetchall()

    # Add device_count to role dict for template
    role = dict(role)
    role['device_count'] = device_count

    return render_template('roles/detail.html', role=role, devices=devices)