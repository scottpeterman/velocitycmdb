import traceback

from flask import render_template, jsonify, request, current_app
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import os

from velocitycmdb.app.blueprints.changes import changes_bp
from velocitycmdb.app.utils.database import get_db_connection


def get_data_dir():
    """Get configured data directory from app config"""
    return Path(current_app.config.get('VELOCITYCMDB_DATA_DIR', '.')).expanduser()


@changes_bp.route('/')
def index():
    """Recent changes dashboard"""
    hours = request.args.get('hours', 24, type=int)
    severity = request.args.get('severity', '')
    capture_type = request.args.get('capture_type', '')

    # Initialize variables with defaults
    changes = []
    stats = {
        'total_changes': 0,
        'devices_affected': 0,
        'critical_count': 0,
        'moderate_count': 0,
        'minor_count': 0
    }
    capture_types = []

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT 
                    cc.id,
                    cc.device_id,
                    cc.detected_at,
                    d.name as device_name,
                    s.name as site_name,
                    cc.capture_type,
                    cc.lines_added,
                    cc.lines_removed,
                    cc.severity,
                    cc.diff_path
                FROM capture_changes cc
                JOIN devices d ON cc.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE cc.detected_at > ?
            """

            params = [(datetime.now() - timedelta(hours=hours)).isoformat()]

            if severity:
                query += " AND cc.severity = ?"
                params.append(severity)

            if capture_type:
                query += " AND cc.capture_type = ?"
                params.append(capture_type)

            query += " ORDER BY cc.detected_at DESC LIMIT 100"

            cursor.execute(query, params)
            changes = [dict(row) for row in cursor.fetchall()]

            # Get summary stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_changes,
                    COUNT(DISTINCT device_id) as devices_affected,
                    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical_count,
                    SUM(CASE WHEN severity = 'moderate' THEN 1 ELSE 0 END) as moderate_count,
                    SUM(CASE WHEN severity = 'minor' THEN 1 ELSE 0 END) as minor_count
                FROM capture_changes
                WHERE detected_at > ?
            """, [(datetime.now() - timedelta(hours=hours)).isoformat()])

            stats = dict(cursor.fetchone())

            # Get available capture types for the filter dropdown
            cursor.execute("""
                SELECT DISTINCT capture_type 
                FROM capture_changes 
                WHERE detected_at > ?
                ORDER BY capture_type
            """, [(datetime.now() - timedelta(hours=hours)).isoformat()])

            capture_types = [row['capture_type'] for row in cursor.fetchall()]

    except Exception as e:
        traceback.print_exc()

    return render_template('changes/index.html',
                           changes=changes,
                           stats=stats,
                           hours=hours,
                           severity_filter=severity,
                           capture_type_filter=capture_type,
                           available_capture_types=capture_types)


@changes_bp.route('/device/<int:device_id>')
def device_history(device_id):
    """Change history for a specific device"""
    # Initialize variables with defaults
    device = {}
    changes = []

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get device info
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            device_row = cursor.fetchone()
            if device_row:
                device = dict(device_row)

            # Get changes
            cursor.execute("""
                SELECT 
                    cc.*,
                    s.name as site_name
                FROM capture_changes cc
                LEFT JOIN devices d ON cc.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE cc.device_id = ?
                ORDER BY cc.detected_at DESC
            """, (device_id,))

            changes = [dict(row) for row in cursor.fetchall()]

    except Exception as e:
        traceback.print_exc()

    return render_template('changes/device_history.html',
                           device=device,
                           changes=changes)


@changes_bp.route('/diff/<int:change_id>')
def view_diff(change_id):
    """View diff for a specific change"""
    # Initialize variables with defaults
    change = {}
    diff_content = ""
    debug_info = []

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    cc.*,
                    d.name as device_name,
                    s.name as site_name
                FROM capture_changes cc
                JOIN devices d ON cc.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE cc.id = ?
            """, (change_id,))

            change_row = cursor.fetchone()
            if change_row:
                change = dict(change_row)

    except Exception as e:
        traceback.print_exc()

    # Read diff file
    if change and change.get('diff_path'):
        try:
            diff_path = Path(change['diff_path'])
            data_dir = get_data_dir()
            debug_info.append(f"Original path: {change['diff_path']}")
            debug_info.append(f"Data dir: {data_dir}")

            # Try multiple path resolution strategies
            paths_to_try = []

            # Strategy 1: If absolute path, use as-is
            if diff_path.is_absolute():
                paths_to_try.append(diff_path)

            # Strategy 2: Relative to configured data_dir (PRIMARY)
            paths_to_try.append(data_dir / diff_path)

            # Strategy 3: Check if path starts with 'diffs/' and resolve from data_dir
            if str(diff_path).startswith('diffs/'):
                paths_to_try.append(data_dir / diff_path)
            else:
                paths_to_try.append(data_dir / 'diffs' / diff_path)

            # Strategy 4: Relative to current working directory (fallback)
            paths_to_try.append(diff_path)

            # Try each path
            file_found = False
            for try_path in paths_to_try:
                debug_info.append(f"Trying: {try_path.absolute()}")
                if try_path.exists():
                    debug_info.append(f"Found at: {try_path.absolute()}")
                    diff_content = try_path.read_text(encoding='utf-8', errors='ignore')
                    file_found = True
                    break

            if not file_found:
                diff_content = f"# Diff file not found\n\nTried the following paths:\n"
                diff_content += "\n".join(f"  - {info}" for info in debug_info)
            else:
                # Sanitize the diff content
                original_length = len(diff_content)
                diff_content = sanitize_diff_content(diff_content)
                debug_info.append(f"Original length: {original_length}, After sanitize: {len(diff_content)}")

                # If sanitization removed everything, show raw content
                if not diff_content.strip():
                    debug_info.append("Warning: Sanitization removed all content, showing raw diff")
                    diff_content = try_path.read_text(encoding='utf-8', errors='ignore')

        except Exception as e:
            traceback.print_exc()
            diff_content = f"Error reading diff: {e}\n\nDebug info:\n"
            diff_content += "\n".join(f"  - {info}" for info in debug_info)
    else:
        diff_content = "No diff path recorded for this change"

    return render_template('changes/view_diff.html',
                           change=change,
                           diff_content=diff_content)


def sanitize_diff_content(diff_content: str) -> str:
    """Remove error tracebacks and command metadata from diff output"""
    lines = []
    skip_block = False
    in_traceback = False

    for line in diff_content.splitlines():
        # Detect start of Python traceback
        if 'Traceback (most recent call last)' in line:
            in_traceback = True
            continue

        # Skip traceback lines
        if in_traceback:
            if line.startswith(('  File ', 'Exception:', 'Error:', '    ')):
                continue
            else:
                in_traceback = False

        # Skip command metadata but be more conservative
        if line.startswith(('-Command:', '+Command:',
                            '-Device:', '+Device:',
                            '-Return code:', '+Return code:',
                            '-STDERR:', '+STDERR:')):
            skip_block = True
            continue

        # Skip import statements that leak into diff
        if line.strip().startswith(('import ', 'from ')) and ' import ' in line:
            continue

        # Check if we should stop skipping
        if skip_block:
            # If line looks like actual config content
            if (line.startswith(('+', '-', ' ')) and
                    not any(x in line for x in ['File', 'import', 'Traceback', '.py'])):
                skip_block = False
            else:
                continue

        lines.append(line)

    return '\n'.join(lines)


@changes_bp.route('/api/recent')
def api_recent_changes():
    """API endpoint for recent changes"""
    hours = request.args.get('hours', 24, type=int)
    changes = []

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    cc.detected_at,
                    d.name as device_name,
                    cc.capture_type,
                    cc.severity,
                    cc.lines_added,
                    cc.lines_removed
                FROM capture_changes cc
                JOIN devices d ON cc.device_id = d.id
                WHERE cc.detected_at > ?
                ORDER BY cc.detected_at DESC
            """, [(datetime.now() - timedelta(hours=hours)).isoformat()])

            changes = [dict(row) for row in cursor.fetchall()]

    except Exception as e:
        traceback.print_exc()

    return jsonify(changes)