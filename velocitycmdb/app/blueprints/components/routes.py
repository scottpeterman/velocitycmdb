# app/blueprints/components/routes.py
from flask import render_template, request, jsonify
from . import components_bp
from velocitycmdb.app.utils.database import get_db_connection
import math
from collections import defaultdict


@components_bp.route('/')
def index():
    """Component inventory overview with filtering and statistics"""
    # Get query parameters
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

            # Base query with device information
            base_query = """
                SELECT 
                    c.id, c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_confidence,
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

            # Get total count
            cursor.execute(count_query, params)
            total_components = cursor.fetchone()[0]

            # Calculate pagination
            total_pages = math.ceil(total_components / per_page)
            offset = (page - 1) * per_page

            # Get components
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

            # Get vendor statistics
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

            # Get filter options
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

            # Calculate overall stats
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
    """API endpoint for component statistics"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Type distribution
            cursor.execute("""
                SELECT 
                    type,
                    COUNT(*) as count,
                    COUNT(CASE WHEN have_sn = 1 THEN 1 END) as with_serials
                FROM components
                GROUP BY type
                ORDER BY count DESC
            """)
            type_distribution = [dict(row) for row in cursor.fetchall()]

            # Top devices by component count
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

            # Serial coverage by vendor
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


# Add this route to app/blueprints/components/routes.py

@components_bp.route('/export')
def export_csv():
    """Export filtered components to CSV"""
    from flask import make_response
    import csv
    from io import StringIO

    # Get filter parameters (same as index route)
    search = request.args.get('search', '').strip()
    type_filter = request.args.get('type', '')
    vendor_filter = request.args.get('vendor', '')
    has_serial = request.args.get('has_serial', '')

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Same query as index but without pagination
            base_query = """
                SELECT 
                    c.name, c.description, c.serial, c.position,
                    c.type, c.subtype, c.have_sn, c.extraction_confidence,
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

            # Create CSV
            si = StringIO()
            writer = csv.writer(si)

            # Write header
            writer.writerow([
                'Component Name', 'Description', 'Serial Number', 'Position',
                'Type', 'Subtype', 'Has Serial', 'Extraction Confidence',
                'Device Name', 'Device Model', 'Site', 'Vendor'
            ])

            # Write data
            for comp in components:
                writer.writerow([
                    comp[0] or '',  # name
                    comp[1] or '',  # description
                    comp[2] or '',  # serial
                    comp[3] or '',  # position
                    comp[4] or '',  # type
                    comp[5] or '',  # subtype
                    'Yes' if comp[6] else 'No',  # have_sn
                    f"{comp[7] * 100:.1f}%" if comp[7] else '',  # confidence
                    comp[8] or '',  # device_name
                    comp[9] or '',  # device_model
                    comp[10] or '',  # site_code
                    comp[11] or ''  # vendor_name
                ])

            # Create response
            output = si.getvalue()
            si.close()

            response = make_response(output)
            response.headers['Content-Type'] = 'text/csv'
            response.headers['Content-Disposition'] = 'attachment; filename=components_export.csv'

            return response

    except Exception as e:
        from flask import flash, redirect, url_for
        flash(f'Export failed: {str(e)}', 'error')
        return redirect(url_for('components.index'))

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