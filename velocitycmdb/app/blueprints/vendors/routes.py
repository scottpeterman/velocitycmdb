from flask import render_template, request, redirect, url_for, flash
from velocitycmdb.app.blueprints.auth.routes import login_required
from velocitycmdb.app.utils.database import get_db_connection
import sqlite3
from . import vendors_bp

@vendors_bp.route('/')
@login_required
def index():
    """List all vendors with device counts"""
    with get_db_connection() as conn:
        vendors = conn.execute('''
            SELECT 
                v.id,
                v.name,
                v.short_name,
                v.description,
                COUNT(d.id) as device_count
            FROM vendors v
            LEFT JOIN devices d ON v.id = d.vendor_id
            GROUP BY v.id
            ORDER BY device_count DESC, v.name
        ''').fetchall()

        stats = conn.execute('''
            SELECT 
                COUNT(*) as total_vendors,
                SUM(CASE WHEN device_count > 0 THEN 1 ELSE 0 END) as vendors_in_use
            FROM (
                SELECT v.id, COUNT(d.id) as device_count
                FROM vendors v
                LEFT JOIN devices d ON v.id = d.vendor_id
                GROUP BY v.id
            )
        ''').fetchone()

    return render_template('vendors/index.html', vendors=vendors, stats=stats)


@vendors_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create new vendor"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        short_name = request.form.get('short_name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Vendor name is required', 'error')
            return render_template('vendors/form.html', vendor=None, form_data=request.form)

        with get_db_connection() as conn:
            try:
                conn.execute(
                    'INSERT INTO vendors (name, short_name, description) VALUES (?, ?, ?)',
                    (name, short_name if short_name else None, description)
                )
                conn.commit()
                flash(f'Vendor "{name}" created successfully', 'success')
                return redirect(url_for('vendors.index'))
            except sqlite3.IntegrityError:
                flash(f'Vendor name "{name}" already exists', 'error')
                return render_template('vendors/form.html', vendor=None, form_data=request.form)

    return render_template('vendors/form.html', vendor=None, form_data=None)


@vendors_bp.route('/<int:vendor_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(vendor_id):
    """Edit existing vendor"""
    with get_db_connection() as conn:
        vendor = conn.execute('SELECT * FROM vendors WHERE id = ?', (vendor_id,)).fetchone()

        if not vendor:
            flash('Vendor not found', 'error')
            return redirect(url_for('vendors.index'))

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            short_name = request.form.get('short_name', '').strip()
            description = request.form.get('description', '').strip()

            if not name:
                flash('Vendor name is required', 'error')
                return render_template('vendors/form.html', vendor=vendor, form_data=request.form)

            try:
                conn.execute(
                    'UPDATE vendors SET name = ?, short_name = ?, description = ? WHERE id = ?',
                    (name, short_name if short_name else None, description, vendor_id)
                )
                conn.commit()
                flash(f'Vendor "{name}" updated successfully', 'success')
                return redirect(url_for('vendors.index'))
            except sqlite3.IntegrityError:
                flash(f'Vendor name "{name}" already exists', 'error')
                return render_template('vendors/form.html', vendor=vendor, form_data=request.form)

    return render_template('vendors/form.html', vendor=vendor, form_data=None)


@vendors_bp.route('/<int:vendor_id>/delete', methods=['POST'])
@login_required
def delete(vendor_id):
    """Delete vendor (only if no devices)"""
    with get_db_connection() as conn:
        device_count = conn.execute(
            'SELECT COUNT(*) as count FROM devices WHERE vendor_id = ?',
            (vendor_id,)
        ).fetchone()['count']

        if device_count > 0:
            flash(f'Cannot delete vendor: {device_count} devices are still assigned to this vendor', 'error')
            return redirect(url_for('vendors.index'))

        vendor = conn.execute('SELECT * FROM vendors WHERE id = ?', (vendor_id,)).fetchone()
        if not vendor:
            flash('Vendor not found', 'error')
            return redirect(url_for('vendors.index'))

        conn.execute('DELETE FROM vendors WHERE id = ?', (vendor_id,))
        conn.commit()
        flash(f'Vendor "{vendor["name"]}" deleted successfully', 'success')

    return redirect(url_for('vendors.index'))


@vendors_bp.route('/<int:vendor_id>/detail')
@login_required
def detail(vendor_id):
    """View vendor details with device list"""
    with get_db_connection() as conn:
        vendor = conn.execute('SELECT * FROM vendors WHERE id = ?', (vendor_id,)).fetchone()

        if not vendor:
            flash('Vendor not found', 'error')
            return redirect(url_for('vendors.index'))

        # Get device count
        device_count = conn.execute(
            'SELECT COUNT(*) as count FROM devices WHERE vendor_id = ?',
            (vendor_id,)
        ).fetchone()['count']

        # Get devices from this vendor
        devices = conn.execute('''
            SELECT 
                d.id,
                d.name,
                d.normalized_name,
                s.name as site_name,
                s.code as site_code,
                dr.name as role_name,
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
            LEFT JOIN device_roles dr ON d.role_id = dr.id
            LEFT JOIN device_captures_current dcc ON d.id = dcc.device_id
            LEFT JOIN fingerprint_extractions fe ON d.id = fe.device_id
            WHERE d.vendor_id = ?
            GROUP BY d.id
            ORDER BY d.name
        ''', (vendor_id,)).fetchall()

    vendor = dict(vendor)
    vendor['device_count'] = device_count

    return render_template('vendors/detail.html', vendor=vendor, devices=devices)