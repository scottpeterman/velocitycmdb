# app/blueprints/sites/routes.py
from flask import render_template, request, redirect, url_for, flash, jsonify

from . import sites_bp
from velocitycmdb.app.blueprints.auth.routes import login_required
from velocitycmdb.app.utils.database import get_db_connection  # <-- Change this import
import sqlite3
# Add this import at the top of the file
from velocitycmdb.app.blueprints.notes.models import NoteAssociation


# Update the detail function (around line 88)
@sites_bp.route('/<code>/detail')
@login_required
def detail(code):
    """View site details with device list"""
    with get_db_connection() as conn:
        site = conn.execute('''
            SELECT * FROM v_site_inventory WHERE code = ?
        ''', (code,)).fetchone()

        if not site:
            flash('Site not found', 'error')
            return redirect(url_for('sites.index'))

        devices = conn.execute('''
            SELECT * FROM v_device_status 
            WHERE site_code = ?
            ORDER BY name
        ''', (code,)).fetchall()

    # ADD THIS: Get site notes
    site_notes = NoteAssociation.get_for_entity('site', code)

    return render_template('sites/detail.html',
                           site=site,
                           devices=devices,
                           site_notes=site_notes)  # ADD THIS

@sites_bp.route('/')
@login_required
def index():
    """List all sites with device counts"""
    with get_db_connection() as conn:  # <-- Use get_db_connection()
        sites = conn.execute('''
            SELECT code, site_name, description, total_devices, 
                   infrastructure_devices, stacked_devices, vendor_count,
                   vendors, devices_with_serials, last_device_update
            FROM v_site_inventory
            ORDER BY total_devices DESC, code
        ''').fetchall()

        stats = conn.execute('''
            SELECT 
                COUNT(*) as total_sites,
                SUM(total_devices) as total_devices,
                AVG(total_devices) as avg_devices_per_site
            FROM v_site_inventory
        ''').fetchone()

    return render_template('sites/index.html', sites=sites, stats=stats)


@sites_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create new site"""
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not code:
            flash('Site code is required', 'error')
            return render_template('sites/form.html', site=None, form_data=request.form)

        if not name:
            flash('Site name is required', 'error')
            return render_template('sites/form.html', site=None, form_data=request.form)

        import re
        if not re.match(r'^[A-Z0-9_-]+$', code):
            flash('Site code can only contain uppercase letters, numbers, hyphens, and underscores', 'error')
            return render_template('sites/form.html', site=None, form_data=request.form)

        with get_db_connection() as conn:
            try:
                conn.execute(
                    'INSERT INTO sites (code, name, description) VALUES (?, ?, ?)',
                    (code, name, description)
                )
                conn.commit()
                flash(f'Site {code} created successfully', 'success')
                return redirect(url_for('sites.index'))
            except sqlite3.IntegrityError:
                flash(f'Site code {code} already exists', 'error')
                return render_template('sites/form.html', site=None, form_data=request.form)

    return render_template('sites/form.html', site=None, form_data=None)


@sites_bp.route('/<code>/edit', methods=['GET', 'POST'])
@login_required
def edit(code):
    """Edit existing site"""
    with get_db_connection() as conn:
        site = conn.execute('SELECT * FROM sites WHERE code = ?', (code,)).fetchone()

        if not site:
            flash('Site not found', 'error')
            return redirect(url_for('sites.index'))

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()

            if not name:
                flash('Site name is required', 'error')
                return render_template('sites/form.html', site=site, form_data=request.form)

            conn.execute(
                'UPDATE sites SET name = ?, description = ? WHERE code = ?',
                (name, description, code)
            )
            conn.commit()
            flash(f'Site {code} updated successfully', 'success')
            return redirect(url_for('sites.index'))

    return render_template('sites/form.html', site=site, form_data=None)


@sites_bp.route('/<code>/delete', methods=['POST'])
@login_required
def delete(code):
    """Delete site (only if no devices)"""
    with get_db_connection() as conn:
        device_count = conn.execute(
            'SELECT COUNT(*) as count FROM devices WHERE site_code = ?',
            (code,)
        ).fetchone()['count']

        if device_count > 0:
            flash(f'Cannot delete site {code}: {device_count} devices are still assigned to this site', 'error')
            return redirect(url_for('sites.index'))

        site = conn.execute('SELECT * FROM sites WHERE code = ?', (code,)).fetchone()
        if not site:
            flash('Site not found', 'error')
            return redirect(url_for('sites.index'))

        conn.execute('DELETE FROM sites WHERE code = ?', (code,))
        conn.commit()
        flash(f'Site {code} deleted successfully', 'success')

    return redirect(url_for('sites.index'))

