# app/blueprints/dashboard/routes.py
from flask import render_template, jsonify
from . import dashboard_bp
from velocitycmdb.app.utils.database import get_db_connection
import sqlite3


@dashboard_bp.route('/')
def index():
    """Main dashboard with network overview"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get basic stats
            stats = {}

            # Site count
            cursor.execute('SELECT COUNT(*) FROM sites')
            stats['site_count'] = cursor.fetchone()[0]

            # Device count
            cursor.execute('SELECT COUNT(*) FROM devices')
            stats['device_count'] = cursor.fetchone()[0]

            # Stack count
            cursor.execute('SELECT COUNT(*) FROM devices WHERE is_stack = 1')
            stats['stack_count'] = cursor.fetchone()[0]

            # Component count (if table exists)
            try:
                cursor.execute('SELECT COUNT(*) FROM components')
                stats['component_count'] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                stats['component_count'] = 0

            # Vendor breakdown
            cursor.execute('''
                SELECT v.name, COUNT(d.id) as count
                FROM vendors v
                LEFT JOIN devices d ON v.id = d.vendor_id
                GROUP BY v.name
                ORDER BY count DESC
                LIMIT 5
            ''')
            stats['top_vendors'] = [{'name': row[0], 'count': row[1]} for row in cursor.fetchall()]

            # Site breakdown
            cursor.execute('''
                SELECT s.code, COUNT(d.id) as count
                FROM sites s
                LEFT JOIN devices d ON s.code = d.site_code
                GROUP BY s.code
                ORDER BY count DESC
                LIMIT 10
            ''')
            stats['top_sites'] = [{'code': row[0], 'count': row[1]} for row in cursor.fetchall()]

            # Recent devices
            cursor.execute('''
                SELECT d.id, d.name, d.site_code, v.name as vendor, d.model, d.timestamp
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                ORDER BY d.timestamp DESC
                LIMIT 10
            ''')
            stats['recent_devices'] = [dict(zip(['id', 'name', 'site_code', 'vendor', 'model', 'timestamp'], row))
                                       for row in cursor.fetchall()]

            # Component statistics (detailed breakdown)
            try:
                # Overall component stats
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN have_sn = 1 THEN 1 END) as with_serials,
                        COUNT(DISTINCT type) as types_count
                    FROM components
                """)
                component_overall = cursor.fetchone()

                # Component breakdown by type
                cursor.execute("""
                    SELECT 
                        type,
                        COUNT(*) as count
                    FROM components
                    WHERE type IS NOT NULL
                    GROUP BY type
                    ORDER BY count DESC
                    LIMIT 5
                """)
                component_by_type = [dict(zip(['type', 'count'], row)) for row in cursor.fetchall()]

                stats['component_stats'] = {
                    'total': component_overall[0] if component_overall else 0,
                    'with_serials': component_overall[1] if component_overall else 0,
                    'types_count': component_overall[2] if component_overall else 0,
                    'by_type': component_by_type
                } if component_overall else None

            except sqlite3.OperationalError:
                stats['component_stats'] = None

            return render_template('dashboard/index.html', **stats)

    except Exception as e:
        print(f"Dashboard error: {e}")
        # Return empty stats on error
        empty_stats = {
            'site_count': 0, 'device_count': 0, 'stack_count': 0, 'component_count': 0,
            'top_vendors': [], 'top_sites': [], 'recent_devices': [], 'component_stats': None
        }
        return render_template('dashboard/index.html', **empty_stats)


@dashboard_bp.route('/api/stats')
def api_stats():
    """API endpoint for dashboard statistics"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Device status by vendor
            cursor.execute('''
                SELECT v.name, COUNT(d.id) as total,
                       SUM(CASE WHEN d.is_stack = 1 THEN 1 ELSE 0 END) as stacks
                FROM vendors v
                LEFT JOIN devices d ON v.id = d.vendor_id
                GROUP BY v.name
                HAVING total > 0
                ORDER BY total DESC
            ''')
            vendor_stats = [dict(zip(['vendor', 'total', 'stacks'], row)) for row in cursor.fetchall()]

            return jsonify({
                'vendor_stats': vendor_stats,
                'status': 'success'
            })

    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'}), 500