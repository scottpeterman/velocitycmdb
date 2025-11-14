# app/blueprints/capture/routes.py
from flask import render_template, request, jsonify, current_app
from . import capture_bp
from velocitycmdb.app.utils.database import get_db_connection
import re
import os


@capture_bp.route('/')
@capture_bp.route('/search')
def search():
    """Capture search interface"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            SELECT capture_type, device_count, success_rate, latest_capture
            FROM v_capture_coverage 
            ORDER BY device_count DESC
        """)
        capture_types = [dict(row) for row in cursor.fetchall()]

        cursor = conn.execute("SELECT COUNT(*) as total_devices FROM devices")
        total_devices = cursor.fetchone()['total_devices']

        cursor = conn.execute("SELECT COUNT(DISTINCT capture_type) as total_types FROM device_captures_current")
        total_types = cursor.fetchone()['total_types']

    return render_template('capture/search.html',
                           capture_types=capture_types,
                           total_devices=total_devices,
                           total_types=total_types)


@capture_bp.route('/api/search', methods=['POST'])
def api_search():
    """Simple exact string search in CLI captures - no normalization"""
    data = request.get_json()
    query = data.get('query', '')  # Don't strip - user might want leading/trailing spaces
    capture_types = data.get('capture_types', [])
    devices = data.get('devices', [])
    limit = data.get('limit', 100)

    # Only reject completely empty queries
    if query is None or query == '':
        return jsonify({'error': 'Search query is required'}), 400

    results = []

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Build filter conditions
        conditions = ['cs.content LIKE ?']
        params = [f'%{query}%']  # Exact string search - what you type is what we search

        if capture_types:
            placeholders = ','.join('?' * len(capture_types))
            conditions.append(f"cs.capture_type IN ({placeholders})")
            params.extend(capture_types)

        if devices:
            placeholders = ','.join('?' * len(devices))
            conditions.append(f"cs.device_id IN ({placeholders})")
            params.extend(devices)

        where_clause = " AND ".join(conditions)
        params.append(limit)

        try:
            # Simple LIKE search - exact string matching
            cursor.execute(f"""
                SELECT 
                    cs.id as snapshot_id,
                    cs.device_id,
                    cs.capture_type,
                    cs.captured_at,
                    cs.file_path,
                    cs.content,
                    d.name as device_name,
                    d.management_ip,
                    s.name as site_name
                FROM capture_snapshots cs
                JOIN devices d ON cs.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE {where_clause}
                ORDER BY cs.captured_at DESC
                LIMIT ?
            """, params)

            # Process results - find matching lines with context
            for row in cursor.fetchall():
                content = row['content']
                lines = content.split('\n')
                matching_lines = []

                # Find lines that contain the exact search string
                for i, line in enumerate(lines, 1):
                    if query in line:  # Simple string contains check - case sensitive
                        # Get context: 2 lines before, 2 lines after
                        start = max(0, i - 3)
                        end = min(len(lines), i + 3)
                        context = lines[start:end]

                        matching_lines.append({
                            'line_number': i,
                            'line': line.strip(),
                            'context': context
                        })

                        # Limit to 15 matches per file
                        if len(matching_lines) >= 15:
                            break

                # Only include if we found matches
                if matching_lines:
                    results.append({
                        'device_id': row['device_id'],
                        'device_name': row['device_name'],
                        'management_ip': row['management_ip'],
                        'site_name': row['site_name'],
                        'capture_type': row['capture_type'],
                        'file_path': row['file_path'],
                        'captured_at': row['captured_at'],
                        'matches': matching_lines
                    })

        except Exception as e:
            current_app.logger.error(f"Search error: {e}")
            return jsonify({
                'error': f'Search error: {str(e)}',
                'query': query
            }), 500

    return jsonify({
        'results': results,
        'total_matches': len(results),
        'query': query
    })


@capture_bp.route('/api/types')
def api_capture_types():
    """Get available capture types"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            SELECT capture_type, device_count, success_rate, latest_capture
            FROM v_capture_coverage 
            ORDER BY capture_type
        """)
        types = [dict(row) for row in cursor.fetchall()]

    return jsonify(types)


@capture_bp.route('/api/view', methods=['POST'])
def api_view_capture():
    """API endpoint to view full capture content"""
    data = request.get_json()
    snapshot_id = data.get('snapshot_id')
    device_id = data.get('device_id')
    capture_type = data.get('capture_type')
    line_number = data.get('line_number')
    search_query = data.get('search_query')

    with get_db_connection() as conn:
        cursor = conn.cursor()

        if snapshot_id:
            cursor.execute("""
                SELECT cs.content, cs.file_path, cs.file_size, cs.captured_at,
                       d.name as device_name, d.management_ip, s.name as site_name
                FROM capture_snapshots cs
                JOIN devices d ON cs.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE cs.id = ?
            """, (snapshot_id,))

            capture = cursor.fetchone()

            if capture:
                response = {
                    'content': capture['content'],
                    'file_path': capture['file_path'],
                    'file_size': capture['file_size'],
                    'capture_timestamp': capture['captured_at'],
                    'device_name': capture['device_name'],
                    'management_ip': capture['management_ip'],
                    'site_name': capture['site_name']
                }

                if line_number:
                    response['line_number'] = line_number
                if search_query:
                    response['search_query'] = search_query

                return jsonify(response)

        elif device_id and capture_type:
            cursor.execute("""
                SELECT cs.content, cs.file_path, cs.file_size, cs.captured_at,
                       d.name as device_name, d.management_ip, s.name as site_name
                FROM capture_snapshots cs
                JOIN devices d ON cs.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE cs.device_id = ? AND cs.capture_type = ?
                ORDER BY cs.captured_at DESC
                LIMIT 1
            """, (device_id, capture_type))

            capture = cursor.fetchone()

            if capture:
                response = {
                    'content': capture['content'],
                    'file_path': capture['file_path'],
                    'file_size': capture['file_size'],
                    'capture_timestamp': capture['captured_at'],
                    'device_name': capture['device_name'],
                    'management_ip': capture['management_ip'],
                    'site_name': capture['site_name']
                }

                if line_number:
                    response['line_number'] = line_number
                if search_query:
                    response['search_query'] = search_query

                return jsonify(response)

        return jsonify({'error': 'Provide snapshot_id OR device_id+capture_type'}), 400


@capture_bp.route('/api/devices')
def api_devices():
    """Get devices for filtering"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            SELECT DISTINCT d.id, d.name, d.management_ip, s.name as site_name
            FROM devices d
            LEFT JOIN sites s ON d.site_code = s.code
            WHERE d.id IN (SELECT DISTINCT device_id FROM device_captures_current)
            ORDER BY d.name
        """)
        devices = [dict(row) for row in cursor.fetchall()]

    return jsonify(devices)