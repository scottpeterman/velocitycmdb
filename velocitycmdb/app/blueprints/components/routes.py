# app/blueprints/components/routes.py
from flask import render_template, request, jsonify, redirect, url_for, flash, make_response
from . import components_bp
from velocitycmdb.app.utils.database import get_db_connection
import math
from collections import defaultdict
import csv
from io import StringIO
from datetime import datetime


# ========== READ OPERATIONS ==========

@components_bp.route('/')
def index():
    """Component inventory overview with filtering and statistics"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search = request.args.get('search', '').strip()
    type_filter = request.args.get('type', '')
    vendor_filter = request.args.get('vendor', '')
    has_serial = request.args.get('has_serial', '')

    per_page = min(max(per_page, 10), 200)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            base_query = """
                SELECT 
                    c.id, c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_confidence,
                    c.extraction_source,
                    d.id as device_id, d.name as device_name,
                    v.name as vendor_name, d.model as device_model
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE 1=1
            """

            count_query = """
                SELECT COUNT(*) FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE 1=1
            """

            conditions = []
            params = []

            if search:
                conditions.append("""
                    (c.name LIKE ? OR c.description LIKE ? OR 
                     c.serial LIKE ? OR d.name LIKE ?)
                """)
                search_param = f"%{search}%"
                params.extend([search_param] * 4)

            if type_filter:
                conditions.append("c.type = ?")
                params.append(type_filter)

            if vendor_filter:
                conditions.append("v.name = ?")
                params.append(vendor_filter)

            if has_serial == 'yes':
                conditions.append("c.have_sn = 1")
            elif has_serial == 'no':
                conditions.append("c.have_sn = 0")

            if conditions:
                where_clause = " AND " + " AND ".join(conditions)
                base_query += where_clause
                count_query += where_clause

            cursor.execute(count_query, params)
            total_components = cursor.fetchone()[0]

            total_pages = math.ceil(total_components / per_page)
            offset = (page - 1) * per_page

            base_query += " ORDER BY d.name, c.type, c.position, c.name LIMIT ? OFFSET ?"
            params.extend([per_page, offset])

            cursor.execute(base_query, params)
            components = [dict(row) for row in cursor.fetchall()]

            # Get statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN have_sn = 1 THEN 1 END) as with_serials,
                    COUNT(DISTINCT device_id) as unique_devices,
                    type
                FROM components
                GROUP BY type
                ORDER BY total DESC
            """)
            type_stats = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT 
                    v.name as vendor,
                    COUNT(c.id) as count
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE v.name IS NOT NULL
                GROUP BY v.name
                ORDER BY count DESC
            """)
            vendor_stats = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT DISTINCT type FROM components 
                WHERE type IS NOT NULL 
                ORDER BY type
            """)
            types = [row[0] for row in cursor.fetchall()]

            cursor.execute("""
                SELECT DISTINCT v.name 
                FROM vendors v
                JOIN devices d ON d.vendor_id = v.id
                JOIN components c ON c.device_id = d.id
                ORDER BY v.name
            """)
            vendors = [row[0] for row in cursor.fetchall()]

            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN have_sn = 1 THEN 1 END) as with_serials,
                    COUNT(DISTINCT device_id) as unique_devices
                FROM components
            """)
            overall_stats = dict(cursor.fetchone())

            pagination = {
                'page': page,
                'per_page': per_page,
                'total': total_components,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'prev_num': page - 1 if page > 1 else None,
                'next_num': page + 1 if page < total_pages else None
            }

            return render_template('components/index.html',
                                   components=components,
                                   pagination=pagination,
                                   type_stats=type_stats,
                                   vendor_stats=vendor_stats,
                                   overall_stats=overall_stats,
                                   types=types,
                                   vendors=vendors,
                                   filters={
                                       'search': search,
                                       'type': type_filter,
                                       'vendor': vendor_filter,
                                       'has_serial': has_serial
                                   })

    except Exception as e:
        return render_template('components/index.html',
                               components=[],
                               pagination={'page': 1, 'total': 0, 'total_pages': 0},
                               type_stats=[],
                               vendor_stats=[],
                               overall_stats={'total': 0, 'with_serials': 0, 'unique_devices': 0},
                               types=[],
                               vendors=[],
                               filters={},
                               error=str(e))


@components_bp.route('/<int:component_id>')
def detail(component_id):
    """Component detail view"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.id, c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_confidence,
                    c.extraction_source,
                    d.id as device_id, d.name as device_name,
                    d.management_ip, d.site_code, d.model as device_model,
                    v.name as vendor_name
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE c.id = ?
            """, (component_id,))

            component = cursor.fetchone()

            if not component:
                flash('Component not found', 'error')
                return redirect(url_for('components.index'))

            component = dict(component)

            # Get sibling components (same device)
            cursor.execute("""
                SELECT id, name, type, serial
                FROM components
                WHERE device_id = ? AND id != ?
                ORDER BY type, position, name
                LIMIT 10
            """, (component['device_id'], component_id))
            siblings = [dict(row) for row in cursor.fetchall()]

            return render_template('components/detail.html',
                                   component=component,
                                   siblings=siblings)

    except Exception as e:
        flash(f'Error loading component: {str(e)}', 'error')
        return redirect(url_for('components.index'))


@components_bp.route('/search')
def search():
    """Component search API endpoint"""
    query = request.args.get('q', '').strip()

    if not query or len(query) < 2:
        return jsonify({'results': [], 'status': 'error', 'message': 'Query too short'})

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            search_param = f"%{query}%"
            cursor.execute("""
                SELECT 
                    c.id, c.name, c.description, c.serial, c.type,
                    d.id as device_id, d.name as device_name,
                    v.name as vendor_name
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE 
                    c.name LIKE ? OR 
                    c.description LIKE ? OR 
                    c.serial LIKE ?
                ORDER BY d.name, c.name
                LIMIT 50
            """, (search_param, search_param, search_param))

            results = [dict(row) for row in cursor.fetchall()]

            return jsonify({'results': results, 'status': 'success', 'count': len(results)})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@components_bp.route('/api/stats')
def api_stats():
    """Component statistics API"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    type,
                    COUNT(*) as total,
                    COUNT(CASE WHEN have_sn = 1 THEN 1 END) as with_serials
                FROM components
                WHERE type IS NOT NULL
                GROUP BY type
                ORDER BY total DESC
            """)
            type_distribution = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT 
                    d.name,
                    d.model,
                    v.name as vendor,
                    COUNT(c.id) as component_count
                FROM devices d
                JOIN components c ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                GROUP BY d.id
                ORDER BY component_count DESC
                LIMIT 10
            """)
            top_devices = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT 
                    v.name as vendor,
                    COUNT(c.id) as total,
                    COUNT(CASE WHEN c.have_sn = 1 THEN 1 END) as with_serials,
                    ROUND(COUNT(CASE WHEN c.have_sn = 1 THEN 1 END) * 100.0 / COUNT(c.id), 1) as coverage_pct
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE v.name IS NOT NULL
                GROUP BY v.name
                ORDER BY total DESC
            """)
            vendor_coverage = [dict(row) for row in cursor.fetchall()]

            return jsonify({
                'type_distribution': type_distribution,
                'top_devices': top_devices,
                'vendor_coverage': vendor_coverage,
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@components_bp.route('/api/by-type/<component_type>')
def api_by_type(component_type):
    """Get all components of a specific type"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.id, c.name, c.description, c.serial, c.position,
                    c.have_sn, c.extraction_confidence,
                    d.id as device_id, d.name as device_name,
                    v.name as vendor_name, d.model as device_model
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE c.type = ?
                ORDER BY d.name, c.position, c.name
            """, (component_type,))

            components = [dict(row) for row in cursor.fetchall()]

            return jsonify({
                'type': component_type,
                'count': len(components),
                'components': components,
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@components_bp.route('/api/serial/<serial_number>')
def api_by_serial(serial_number):
    """Find component by serial number"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.id, c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_confidence,
                    d.id as device_id, d.name as device_name,
                    d.management_ip, d.site_code,
                    v.name as vendor_name, d.model as device_model
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE c.serial = ?
            """, (serial_number,))

            component = cursor.fetchone()

            if component:
                return jsonify({
                    'component': dict(component),
                    'status': 'success'
                })
            else:
                return jsonify({
                    'status': 'not_found',
                    'message': f'No component found with serial {serial_number}'
                }), 404

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@components_bp.route('/export')
def export_csv():
    """Export filtered components to CSV"""
    search = request.args.get('search', '').strip()
    type_filter = request.args.get('type', '')
    vendor_filter = request.args.get('vendor', '')
    has_serial = request.args.get('has_serial', '')

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            base_query = """
                SELECT 
                    c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_confidence,
                    c.extraction_source,
                    d.name as device_name, d.model as device_model,
                    d.site_code, v.name as vendor_name
                FROM components c
                JOIN devices d ON c.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE 1=1
            """

            conditions = []
            params = []

            if search:
                conditions.append("""
                    (c.name LIKE ? OR c.description LIKE ? OR 
                     c.serial LIKE ? OR d.name LIKE ?)
                """)
                search_param = f"%{search}%"
                params.extend([search_param] * 4)

            if type_filter:
                conditions.append("c.type = ?")
                params.append(type_filter)

            if vendor_filter:
                conditions.append("v.name = ?")
                params.append(vendor_filter)

            if has_serial == 'yes':
                conditions.append("c.have_sn = 1")
            elif has_serial == 'no':
                conditions.append("c.have_sn = 0")

            if conditions:
                where_clause = " AND " + " AND ".join(conditions)
                base_query += where_clause

            base_query += " ORDER BY d.name, c.type, c.position, c.name"

            cursor.execute(base_query, params)
            components = cursor.fetchall()

            si = StringIO()
            writer = csv.writer(si)

            writer.writerow([
                'Component Name', 'Description', 'Serial Number', 'Position',
                'Type', 'Subtype', 'Has Serial', 'Extraction Confidence',
                'Extraction Source', 'Device Name', 'Device Model', 'Site', 'Vendor'
            ])

            for comp in components:
                writer.writerow([
                    comp[0] or '',
                    comp[1] or '',
                    comp[2] or '',
                    comp[3] or '',
                    comp[4] or '',
                    comp[5] or '',
                    'Yes' if comp[6] else 'No',
                    f"{comp[7] * 100:.1f}%" if comp[7] else '',
                    comp[8] or '',
                    comp[9] or '',
                    comp[10] or '',
                    comp[11] or '',
                    comp[12] or ''
                ])

            output = si.getvalue()
            si.close()

            response = make_response(output)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename=components_export.csv'

            return response

    except Exception as e:
        flash(f'Export failed: {str(e)}', 'error')
        return redirect(url_for('components.index'))


# ========== CREATE OPERATIONS ==========

@components_bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new component"""
    if request.method == 'POST':
        device_id = request.form.get('device_id', type=int)
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        serial = request.form.get('serial', '').strip()
        position = request.form.get('position', '').strip()
        comp_type = request.form.get('type', '').strip()
        subtype = request.form.get('subtype', '').strip()

        # Validation
        if not device_id:
            flash('Device is required', 'error')
            return redirect(url_for('components.add'))

        if not name:
            flash('Component name is required', 'error')
            return redirect(url_for('components.add', device_id=device_id))

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Verify device exists
                cursor.execute("SELECT id, name FROM devices WHERE id = ?", (device_id,))
                device = cursor.fetchone()
                if not device:
                    flash('Selected device not found', 'error')
                    return redirect(url_for('components.add'))

                # Check for duplicate (same name, serial, device)
                if serial:
                    cursor.execute("""
                        SELECT id FROM components 
                        WHERE device_id = ? AND serial = ?
                    """, (device_id, serial))
                    if cursor.fetchone():
                        flash(f'Component with serial {serial} already exists on this device', 'error')
                        return redirect(url_for('components.add', device_id=device_id))

                # Insert component
                have_sn = 1 if serial else 0
                cursor.execute("""
                    INSERT INTO components 
                    (device_id, name, description, serial, position, type, subtype, 
                     have_sn, extraction_source, extraction_confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', 1.0)
                """, (device_id, name, description or None, serial or None,
                      position or None, comp_type or None, subtype or None, have_sn))

                conn.commit()
                component_id = cursor.lastrowid

                flash(f'Component "{name}" added successfully', 'success')

                # Redirect based on referrer
                next_url = request.form.get('next')
                if next_url and 'device_detail' in next_url:
                    return redirect(url_for('assets.device_detail', device_id=device_id) + '#components-tab')
                return redirect(url_for('components.detail', component_id=component_id))

        except Exception as e:
            flash(f'Error adding component: {str(e)}', 'error')
            return redirect(url_for('components.add', device_id=device_id))

    # GET request - show form
    device_id = request.args.get('device_id', type=int)
    selected_device = None

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get all devices for dropdown
            cursor.execute("""
                SELECT d.id, d.name, d.model, v.name as vendor_name, d.site_code
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                ORDER BY d.name
            """)
            devices = [dict(row) for row in cursor.fetchall()]

            # Get selected device if specified
            if device_id:
                cursor.execute("""
                    SELECT d.id, d.name, d.model, v.name as vendor_name
                    FROM devices d
                    LEFT JOIN vendors v ON d.vendor_id = v.id
                    WHERE d.id = ?
                """, (device_id,))
                selected_device = cursor.fetchone()
                if selected_device:
                    selected_device = dict(selected_device)

            # Get existing component types for suggestions
            cursor.execute("""
                SELECT DISTINCT type FROM components 
                WHERE type IS NOT NULL 
                ORDER BY type
            """)
            existing_types = [row[0] for row in cursor.fetchall()]

            return render_template('components/form.html',
                                   mode='add',
                                   component=None,
                                   devices=devices,
                                   selected_device=selected_device,
                                   existing_types=existing_types,
                                   next=request.args.get('next', ''))

    except Exception as e:
        flash(f'Error loading form: {str(e)}', 'error')
        return redirect(url_for('components.index'))


# ========== UPDATE OPERATIONS ==========

@components_bp.route('/<int:component_id>/edit', methods=['GET', 'POST'])
def edit(component_id):
    """Edit an existing component"""
    if request.method == 'POST':
        device_id = request.form.get('device_id', type=int)
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        serial = request.form.get('serial', '').strip()
        position = request.form.get('position', '').strip()
        comp_type = request.form.get('type', '').strip()
        subtype = request.form.get('subtype', '').strip()

        if not device_id:
            flash('Device is required', 'error')
            return redirect(url_for('components.edit', component_id=component_id))

        if not name:
            flash('Component name is required', 'error')
            return redirect(url_for('components.edit', component_id=component_id))

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Verify component exists
                cursor.execute("SELECT id, device_id FROM components WHERE id = ?", (component_id,))
                existing = cursor.fetchone()
                if not existing:
                    flash('Component not found', 'error')
                    return redirect(url_for('components.index'))

                # Check for duplicate serial on same device (excluding current)
                if serial:
                    cursor.execute("""
                        SELECT id FROM components 
                        WHERE device_id = ? AND serial = ? AND id != ?
                    """, (device_id, serial, component_id))
                    if cursor.fetchone():
                        flash(f'Another component with serial {serial} already exists on this device', 'error')
                        return redirect(url_for('components.edit', component_id=component_id))

                # Update component
                have_sn = 1 if serial else 0
                cursor.execute("""
                    UPDATE components SET
                        device_id = ?,
                        name = ?,
                        description = ?,
                        serial = ?,
                        position = ?,
                        type = ?,
                        subtype = ?,
                        have_sn = ?
                    WHERE id = ?
                """, (device_id, name, description or None, serial or None,
                      position or None, comp_type or None, subtype or None,
                      have_sn, component_id))

                conn.commit()

                flash(f'Component "{name}" updated successfully', 'success')

                next_url = request.form.get('next')
                if next_url and 'device_detail' in next_url:
                    return redirect(url_for('assets.device_detail', device_id=device_id) + '#components-tab')
                return redirect(url_for('components.detail', component_id=component_id))

        except Exception as e:
            flash(f'Error updating component: {str(e)}', 'error')
            return redirect(url_for('components.edit', component_id=component_id))

    # GET request - show form
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.id, c.device_id, c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.extraction_source, c.extraction_confidence
                FROM components c
                WHERE c.id = ?
            """, (component_id,))

            component = cursor.fetchone()
            if not component:
                flash('Component not found', 'error')
                return redirect(url_for('components.index'))

            component = dict(component)

            # Get all devices for dropdown
            cursor.execute("""
                SELECT d.id, d.name, d.model, v.name as vendor_name, d.site_code
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                ORDER BY d.name
            """)
            devices = [dict(row) for row in cursor.fetchall()]

            # Get selected device
            cursor.execute("""
                SELECT d.id, d.name, d.model, v.name as vendor_name
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE d.id = ?
            """, (component['device_id'],))
            selected_device = cursor.fetchone()
            if selected_device:
                selected_device = dict(selected_device)

            # Get existing component types
            cursor.execute("""
                SELECT DISTINCT type FROM components 
                WHERE type IS NOT NULL 
                ORDER BY type
            """)
            existing_types = [row[0] for row in cursor.fetchall()]

            return render_template('components/form.html',
                                   mode='edit',
                                   component=component,
                                   devices=devices,
                                   selected_device=selected_device,
                                   existing_types=existing_types,
                                   next=request.args.get('next', ''))

    except Exception as e:
        flash(f'Error loading component: {str(e)}', 'error')
        return redirect(url_for('components.index'))


# ========== DELETE OPERATIONS ==========

@components_bp.route('/<int:component_id>/delete', methods=['POST'])
def delete(component_id):
    """Delete a component"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get component info for flash message
            cursor.execute("""
                SELECT c.name, c.device_id, d.name as device_name
                FROM components c
                JOIN devices d ON c.device_id = d.id
                WHERE c.id = ?
            """, (component_id,))

            component = cursor.fetchone()
            if not component:
                flash('Component not found', 'error')
                return redirect(url_for('components.index'))

            component = dict(component)

            # Delete the component
            cursor.execute("DELETE FROM components WHERE id = ?", (component_id,))
            conn.commit()

            flash(f'Component "{component["name"]}" deleted from {component["device_name"]}', 'success')

            # Redirect based on referrer
            next_url = request.form.get('next', '')
            if 'device_detail' in next_url:
                return redirect(url_for('assets.device_detail', device_id=component['device_id']) + '#components-tab')
            return redirect(url_for('components.index'))

    except Exception as e:
        flash(f'Error deleting component: {str(e)}', 'error')
        return redirect(url_for('components.index'))


# ========== API CRUD OPERATIONS (for AJAX) ==========

@components_bp.route('/api/add', methods=['POST'])
def api_add():
    """API endpoint to add a component (for AJAX from device detail)"""
    data = request.get_json()

    device_id = data.get('device_id')
    name = data.get('name', '').strip()

    if not device_id or not name:
        return jsonify({'status': 'error', 'message': 'Device ID and name are required'}), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Verify device exists
            cursor.execute("SELECT id FROM devices WHERE id = ?", (device_id,))
            if not cursor.fetchone():
                return jsonify({'status': 'error', 'message': 'Device not found'}), 404

            serial = data.get('serial', '').strip() or None
            have_sn = 1 if serial else 0

            cursor.execute("""
                INSERT INTO components 
                (device_id, name, description, serial, position, type, subtype, 
                 have_sn, extraction_source, extraction_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', 1.0)
            """, (
                device_id,
                name,
                data.get('description', '').strip() or None,
                serial,
                data.get('position', '').strip() or None,
                data.get('type', '').strip() or None,
                data.get('subtype', '').strip() or None,
                have_sn
            ))

            conn.commit()
            component_id = cursor.lastrowid

            return jsonify({
                'status': 'success',
                'message': f'Component "{name}" added',
                'component_id': component_id
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@components_bp.route('/api/<int:component_id>', methods=['GET'])
def api_get(component_id):
    """API endpoint to get component details"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.id, c.device_id, c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_source, 
                    c.extraction_confidence,
                    d.name as device_name
                FROM components c
                JOIN devices d ON c.device_id = d.id
                WHERE c.id = ?
            """, (component_id,))

            component = cursor.fetchone()
            if not component:
                return jsonify({'status': 'error', 'message': 'Component not found'}), 404

            return jsonify({
                'status': 'success',
                'component': dict(component)
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@components_bp.route('/api/<int:component_id>', methods=['PUT'])
def api_update(component_id):
    """API endpoint to update a component"""
    data = request.get_json()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM components WHERE id = ?", (component_id,))
            if not cursor.fetchone():
                return jsonify({'status': 'error', 'message': 'Component not found'}), 404

            serial = data.get('serial', '').strip() or None
            have_sn = 1 if serial else 0

            cursor.execute("""
                UPDATE components SET
                    name = COALESCE(?, name),
                    description = ?,
                    serial = ?,
                    position = ?,
                    type = ?,
                    subtype = ?,
                    have_sn = ?
                WHERE id = ?
            """, (
                data.get('name', '').strip() or None,
                data.get('description', '').strip() or None,
                serial,
                data.get('position', '').strip() or None,
                data.get('type', '').strip() or None,
                data.get('subtype', '').strip() or None,
                have_sn,
                component_id
            ))

            conn.commit()

            return jsonify({
                'status': 'success',
                'message': 'Component updated'
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@components_bp.route('/api/<int:component_id>', methods=['DELETE'])
def api_delete(component_id):
    """API endpoint to delete a component"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM components WHERE id = ?", (component_id,))
            component = cursor.fetchone()
            if not component:
                return jsonify({'status': 'error', 'message': 'Component not found'}), 404

            cursor.execute("DELETE FROM components WHERE id = ?", (component_id,))
            conn.commit()

            return jsonify({
                'status': 'success',
                'message': f'Component "{component[0]}" deleted'
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500