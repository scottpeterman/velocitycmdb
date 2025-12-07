# app/blueprints/environment/__init__.py
"""
Environment diagnostics blueprint for VelocityCMDB.
Provides validated checks of all resource locations and configuration.
"""

import os
import platform
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Blueprint, jsonify, current_app

environment_bp = Blueprint('environment', __name__, url_prefix='/environment')


def check_path(path_str, check_type='exists'):
    """
    Check a path and return validation info.
    """
    if not path_str:
        return {
            'path': None,
            'exists': False,
            'status': 'error',
            'message': 'Path not configured'
        }

    path = Path(path_str)
    result = {
        'path': str(path),
        'exists': path.exists(),
        'is_file': path.is_file() if path.exists() else None,
        'is_dir': path.is_dir() if path.exists() else None,
        'readable': os.access(path, os.R_OK) if path.exists() else False,
        'writable': os.access(path, os.W_OK) if path.exists() else False,
    }

    if result['is_file']:
        try:
            stat = path.stat()
            result['size'] = stat.st_size
            result['size_human'] = format_size(stat.st_size)
            result['modified'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except Exception as e:
            result['size'] = None
            result['error'] = str(e)

    if not result['exists']:
        result['status'] = 'missing'
        result['message'] = 'Path does not exist'
    elif check_type == 'file' and not result['is_file']:
        result['status'] = 'error'
        result['message'] = 'Expected file, found directory'
    elif check_type == 'directory' and not result['is_dir']:
        result['status'] = 'error'
        result['message'] = 'Expected directory, found file'
    elif check_type == 'writable' and not result['writable']:
        result['status'] = 'warning'
        result['message'] = 'Path exists but is not writable'
    elif not result['readable']:
        result['status'] = 'warning'
        result['message'] = 'Path exists but is not readable'
    else:
        result['status'] = 'ok'
        result['message'] = 'OK'

    return result


def check_database(db_path):
    """Check if a SQLite database is valid and accessible."""
    path_check = check_path(db_path, 'file')

    if path_check['status'] != 'ok':
        return path_check

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        cursor.execute("PRAGMA page_count")
        page_count = cursor.fetchone()[0]
        cursor.execute("PRAGMA page_size")
        page_size = cursor.fetchone()[0]

        conn.close()

        path_check['db_valid'] = True
        path_check['tables'] = tables
        path_check['table_count'] = len(tables)
        path_check['db_size'] = page_count * page_size
        path_check['message'] = f'OK - {len(tables)} tables'

    except sqlite3.Error as e:
        path_check['db_valid'] = False
        path_check['status'] = 'error'
        path_check['message'] = f'Database error: {str(e)}'
    except Exception as e:
        path_check['db_valid'] = False
        path_check['status'] = 'error'
        path_check['message'] = f'Error: {str(e)}'

    return path_check


def format_size(size_bytes):
    """Format bytes to human readable string."""
    if size_bytes is None:
        return 'N/A'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def count_files_in_dir(dir_path, pattern='*'):
    """Count files matching pattern in directory."""
    if not dir_path or not Path(dir_path).exists():
        return 0
    try:
        return len(list(Path(dir_path).glob(pattern)))
    except Exception:
        return 0


@environment_bp.route('/check')
def check_environment():
    """
    Return comprehensive environment diagnostics.
    Validates all configured paths and resources.
    """
    config = current_app.config

    # System info
    system_info = {
        'platform': platform.system(),
        'platform_release': platform.release(),
        'python_version': platform.python_version(),
        'hostname': platform.node(),
        'flask_env': os.environ.get('FLASK_ENV', 'not set'),
        'debug_mode': config.get('DEBUG', False),
        'timestamp': datetime.now().isoformat()
    }

    # Core directories - using ACTUAL config keys from __init__.py
    directories = {
        'data_dir': {
            'label': 'Data Directory',
            'description': 'Main data storage location',
            **check_path(config.get('VELOCITYCMDB_DATA_DIR'), 'directory')
        },
        'capture_dir': {
            'label': 'Capture Directory',
            'description': 'Command capture storage',
            **check_path(config.get('CAPTURE_DIR'), 'directory')
        },
        'jobs_dir': {
            'label': 'Jobs Directory',
            'description': 'Collection job storage',
            **check_path(config.get('JOBS_DIR'), 'directory')
        },
        'fingerprints_dir': {
            'label': 'Fingerprints Directory',
            'description': 'Device fingerprint storage',
            **check_path(config.get('FINGERPRINTS_DIR'), 'directory')
        },
        'discovery_dir': {
            'label': 'Discovery Directory',
            'description': 'Discovery data storage',
            **check_path(config.get('DISCOVERY_DIR'), 'directory')
        },
        'scmaps_dir': {
            'label': 'Secure Cartography Maps',
            'description': 'Discovery map storage (SVG/JSON)',
            **check_path(config.get('SCMAPS_DIR'), 'directory')
        },
        'maps_dir': {
            'label': 'Maps Directory',
            'description': 'Topology map storage',
            **check_path(config.get('MAPS_BASE'), 'directory')
        },
    }

    # Add file counts for directories that exist
    for key, dir_info in directories.items():
        if dir_info.get('exists') and dir_info.get('is_dir'):
            dir_path = dir_info['path']
            if 'maps' in key.lower() or 'scmaps' in key.lower():
                svg_count = count_files_in_dir(dir_path, '*.svg')
                json_count = count_files_in_dir(dir_path, '*.json')
                dir_info['file_count'] = svg_count + json_count
                dir_info['file_note'] = f'{svg_count} SVG, {json_count} JSON'
            elif 'capture' in key.lower():
                dir_info['file_count'] = count_files_in_dir(dir_path, '**/*')
                dir_info['file_note'] = 'Total files'
            else:
                dir_info['file_count'] = count_files_in_dir(dir_path, '*')
                dir_info['file_note'] = 'Total files'

    # Databases
    databases = {
        'assets_db': {
            'label': 'Assets Database',
            'description': 'Main device/asset storage',
            **check_database(config.get('DATABASE'))
        },
        'arp_db': {
            'label': 'ARP Database',
            'description': 'ARP/MAC address catalog',
            **check_database(config.get('ARP_DATABASE'))
        },
        'users_db': {
            'label': 'Users Database',
            'description': 'User authentication data',
            **check_database(config.get('USERS_DATABASE'))
        },
    }

    # Configuration files
    config_files = {
        'main_config': {
            'label': 'Main Configuration',
            'description': 'config.yaml',
            **check_path(config.get('CONFIG_FILE'), 'file')
        },
    }

    # If CONFIG_FILE not set, check default location
    if not config.get('CONFIG_FILE'):
        default_config = Path.home() / '.velocitycmdb' / 'config.yaml'
        config_files['main_config'] = {
            'label': 'Main Configuration',
            'description': '~/.velocitycmdb/config.yaml',
            **check_path(str(default_config), 'file')
        }

    # Environment variables
    env_vars = {
        'VELOCITYCMDB_DATA_DIR': os.environ.get('VELOCITYCMDB_DATA_DIR', 'not set'),
        'FLASK_ENV': os.environ.get('FLASK_ENV', 'not set'),
        'FLASK_DEBUG': os.environ.get('FLASK_DEBUG', 'not set'),
        'SECRET_KEY': '(set)' if os.environ.get('SECRET_KEY') else 'not set',
    }

    # Summary stats
    all_checks = list(directories.values()) + list(databases.values()) + list(config_files.values())
    summary = {
        'total_checks': len(all_checks),
        'ok_count': sum(1 for c in all_checks if c.get('status') == 'ok'),
        'warning_count': sum(1 for c in all_checks if c.get('status') == 'warning'),
        'error_count': sum(1 for c in all_checks if c.get('status') in ('error', 'missing')),
    }
    summary['overall_status'] = 'ok' if summary['error_count'] == 0 else 'error'

    return jsonify({
        'system': system_info,
        'directories': directories,
        'databases': databases,
        'config_files': config_files,
        'environment_variables': env_vars,
        'summary': summary
    })