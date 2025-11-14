# app/blueprints/admin/routes.py
"""
Admin interface for user management, system configuration, and operations
"""
from flask import render_template, redirect, url_for, request, session, flash, jsonify, current_app
from functools import wraps
import logging
import yaml
import json
from datetime import datetime
from pathlib import Path
from . import admin_bp

logger = logging.getLogger(__name__)

# This will be set from app initialization
auth_manager = None


def init_admin(auth_mgr):
    """Initialize admin blueprint with auth manager"""
    global auth_manager
    auth_manager = auth_mgr

    # DEBUG: Log initialization
    logger.info("=" * 80)
    logger.info("ADMIN MODULE INITIALIZATION")
    logger.info("=" * 80)
    logger.info(f"auth_manager provided: {auth_mgr is not None}")
    if auth_mgr:
        logger.info(f"auth_manager type: {type(auth_mgr)}")
        logger.info(f"Has _db_auth_available: {hasattr(auth_mgr, '_db_auth_available')}")
        if hasattr(auth_mgr, '_db_auth_available'):
            logger.info(f"_db_auth_available: {auth_mgr._db_auth_available}")
        if hasattr(auth_mgr, '_db_path'):
            logger.info(f"DB path: {auth_mgr._db_path}")
            db_path = Path(auth_mgr._db_path)
            logger.info(f"DB exists: {db_path.exists()}")
        if hasattr(auth_mgr, 'config'):
            logger.info(
                f"Config keys: {list(auth_mgr.config.keys()) if isinstance(auth_mgr.config, dict) else 'Not a dict'}")
    logger.info("=" * 80)


def admin_required(f):
    """Decorator requiring admin privileges"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Please log in to access admin panel', 'error')
            return redirect(url_for('auth.login'))

        # Check if user is admin - fixed to check session is_admin directly
        is_admin = session.get('is_admin', False) or 'admin' in session.get('groups', [])

        if not is_admin:
            flash('Admin privileges required', 'error')
            return redirect(url_for('dashboard.index'))

        return f(*args, **kwargs)

    return decorated_function


def _get_config_path():
    """
    Get the path to config.yaml based on persistence strategy.

    This aligns with how config_loader.py finds the config file.

    Priority order:
    1. Environment variable: VELOCITYCMDB_CONFIG_PATH
    2. Next to app root: ../config.yaml (relative to app directory)
    3. Home directory: ~/.velocitycmdb/config.yaml
    4. Data directory: {DATA_DIR}/../config.yaml
    5. Data directory: {DATA_DIR}/config.yaml
    6. Current working directory: ./config.yaml

    Returns Path object for config file
    """
    import os

    # Check environment variable first
    env_config = os.environ.get('VELOCITYCMDB_CONFIG_PATH')
    if env_config:
        config_path = Path(env_config)
        if config_path.exists():
            logger.info(f"Using config from environment: {config_path}")
            return config_path
        logger.debug(f"Environment config path not found: {config_path}")

    # Try relative to app root (this is what __init__.py uses)
    try:
        app_root = Path(current_app.root_path)  # This is the 'app' directory
        project_root = app_root.parent.parent  # Go up to velocitycmdb project root
        relative_config = project_root / 'config.yaml'
        if relative_config.exists():
            logger.info(f"Using config relative to app root: {relative_config}")
            return relative_config
    except Exception as e:
        logger.debug(f"Could not check relative path: {e}")

    # Try standard home directory location
    home_config = Path.home() / '.velocitycmdb' / 'config.yaml'
    if home_config.exists():
        logger.info(f"Using config from home directory: {home_config}")
        return home_config

    # Try data directory from Flask config (if available)
    try:
        data_dir = current_app.config.get('VELOCITYCMDB_DATA_DIR')
        if data_dir:
            # Try parent (base) directory
            config_path = Path(data_dir).parent / 'config.yaml'
            if config_path.exists():
                logger.info(f"Using config from base directory: {config_path}")
                return config_path

            # Try in data directory itself
            config_path = Path(data_dir) / 'config.yaml'
            if config_path.exists():
                logger.info(f"Using config from data directory: {config_path}")
                return config_path
    except Exception as e:
        logger.debug(f"Could not check DATA_DIR paths: {e}")

    # Fall back to current working directory
    cwd_config = Path('config.yaml')
    if cwd_config.exists():
        logger.info(f"Using config from current directory: {cwd_config}")
        return cwd_config

    # Last resort: return standard home location (even if doesn't exist)
    # This matches the standard persistence location
    logger.warning(f"Config file not found in any location, defaulting to: {home_config}")
    return home_config


# ============================================================================
# MAIN ADMIN DASHBOARD
# ============================================================================

@admin_bp.route('/')
@admin_required
def index():
    """Admin dashboard home"""

    # DEBUG: Log admin module state
    logger.info("=" * 80)
    logger.info("ADMIN DASHBOARD ACCESS")
    logger.info("=" * 80)
    logger.info(f"auth_manager exists: {auth_manager is not None}")

    if auth_manager:
        logger.info(f"auth_manager type: {type(auth_manager)}")
        logger.info(f"Has _db_auth_available: {hasattr(auth_manager, '_db_auth_available')}")

        if hasattr(auth_manager, '_db_auth_available'):
            logger.info(f"_db_auth_available value: {auth_manager._db_auth_available}")

        if hasattr(auth_manager, '_db_path'):
            logger.info(f"Database path: {auth_manager._db_path}")
            db_path = Path(auth_manager._db_path)
            logger.info(f"Database exists: {db_path.exists()}")
            if db_path.exists():
                logger.info(f"Database size: {db_path.stat().st_size} bytes")
                logger.info(f"Database absolute path: {db_path.absolute()}")

        if hasattr(auth_manager, 'config'):
            logger.info(f"Auth config: {auth_manager.config}")

        # Check for list_users method
        if hasattr(auth_manager, 'list_users'):
            logger.info("list_users method exists")
        else:
            logger.error("list_users method NOT FOUND!")
    else:
        logger.error("auth_manager is None!")
        logger.error("init_admin() may not have been called properly")

    # Get system statistics
    stats = {
        'total_users': 0,
        'active_users': 0,
        'admin_users': 0,
        'external_users': 0,
        'recent_logins': [],
        'debug_info': {
            'auth_manager_present': auth_manager is not None,
            'db_auth_available': False,
            'db_path': None,
            'db_exists': False,
            'error': None
        }
    }

    if auth_manager:
        if hasattr(auth_manager, '_db_path'):
            stats['debug_info']['db_path'] = str(auth_manager._db_path)
            db_path = Path(auth_manager._db_path)
            stats['debug_info']['db_exists'] = db_path.exists()

        if hasattr(auth_manager, '_db_auth_available'):
            stats['debug_info']['db_auth_available'] = auth_manager._db_auth_available

            if auth_manager._db_auth_available:
                try:
                    logger.info("Attempting to list users...")
                    users = auth_manager.list_users()
                    logger.info(f"Successfully retrieved {len(users)} users")

                    stats['total_users'] = len(users)
                    stats['active_users'] = len([u for u in users if u['is_active']])
                    stats['admin_users'] = len([u for u in users if u['is_admin']])
                    stats['external_users'] = len([u for u in users if u['auth_backend'] != 'database'])

                    # Get recent logins (last 10)
                    stats['recent_logins'] = sorted(
                        [u for u in users if u['last_login']],
                        key=lambda x: x['last_login'] or '',
                        reverse=True
                    )[:10]

                    logger.info(
                        f"Stats: {stats['total_users']} total, {stats['active_users']} active, {stats['admin_users']} admin")
                except Exception as e:
                    logger.error(f"Error retrieving users: {str(e)}")
                    logger.exception("Full traceback:")
                    stats['debug_info']['error'] = str(e)
            else:
                logger.warning("Database authentication not available (_db_auth_available is False)")
                stats['debug_info']['error'] = "Database authentication not enabled in config"
        else:
            logger.error("auth_manager missing _db_auth_available attribute")
            stats['debug_info']['error'] = "auth_manager missing _db_auth_available attribute"
    else:
        logger.error("auth_manager is None - init_admin() not called")
        stats['debug_info']['error'] = "Auth manager not initialized (init_admin not called)"

    logger.info("=" * 80)

    return render_template('admin/index.html', stats=stats)


# ============================================================================
# DEBUG ENDPOINT
# ============================================================================

@admin_bp.route('/debug')
@admin_required
def debug_info():
    """Debug information endpoint"""

    debug_data = {
        'auth_manager': {
            'exists': auth_manager is not None,
            'type': str(type(auth_manager)) if auth_manager else None,
            'attributes': dir(auth_manager) if auth_manager else [],
        },
        'config': {},
        'database': {},
        'session': dict(session),
        'environment': {},
        'paths': {
            'config_file': str(_get_config_path()),
            'data_dir': current_app.config.get('VELOCITYCMDB_DATA_DIR'),
            'database': current_app.config.get('DATABASE'),
            'capture_dir': current_app.config.get('CAPTURE_DIR'),
            'discovery_dir': current_app.config.get('DISCOVERY_DIR'),
            'app_root': current_app.root_path,
        }
    }

    if auth_manager:
        # Config info
        if hasattr(auth_manager, 'config'):
            debug_data['config'] = auth_manager.config

        # Database info
        if hasattr(auth_manager, '_db_path'):
            db_path = Path(auth_manager._db_path)
            debug_data['database']['path'] = str(auth_manager._db_path)
            debug_data['database']['absolute_path'] = str(db_path.absolute())
            debug_data['database']['exists'] = db_path.exists()
            if db_path.exists():
                debug_data['database']['size'] = db_path.stat().st_size
                debug_data['database']['readable'] = db_path.is_file()

        if hasattr(auth_manager, '_db_auth_available'):
            debug_data['database']['auth_available'] = auth_manager._db_auth_available

        # Try to get user count
        if hasattr(auth_manager, 'list_users'):
            try:
                users = auth_manager.list_users()
                debug_data['database']['user_count'] = len(users)
                debug_data['database']['users'] = [
                    {
                        'username': u['username'],
                        'is_admin': u['is_admin'],
                        'is_active': u['is_active'],
                        'auth_backend': u['auth_backend']
                    }
                    for u in users
                ]
            except Exception as e:
                debug_data['database']['error'] = str(e)

    # Environment info
    import os
    debug_data['environment']['cwd'] = os.getcwd()
    debug_data['environment']['VELOCITYCMDB_DATA_DIR'] = os.environ.get('VELOCITYCMDB_DATA_DIR')
    debug_data['environment']['VELOCITYCMDB_CONFIG_PATH'] = os.environ.get('VELOCITYCMDB_CONFIG_PATH')

    return jsonify(debug_data)


# ============================================================================
# USER MANAGEMENT
# ============================================================================

@admin_bp.route('/users')
@admin_required
def users_list():
    """List all users"""

    users = []
    if auth_manager and hasattr(auth_manager, '_db_auth_available'):
        if auth_manager._db_auth_available:
            users = auth_manager.list_users()
        else:
            flash('Database authentication is not enabled', 'warning')
    else:
        flash('User management not available', 'error')

    return render_template('admin/users_list.html', users=users)


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def users_create():
    """Create new user"""

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        groups = request.form.get('groups', '').strip()
        is_admin = request.form.get('is_admin') == 'on'

        # Validation
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('admin/users_form.html', action='create')

        if len(password) < 8:
            flash('Password must be at least 8 characters', 'error')
            return render_template('admin/users_form.html', action='create')

        if password != password_confirm:
            flash('Passwords do not match', 'error')
            return render_template('admin/users_form.html', action='create')

        # Create user - try with all parameters, fallback to basic if needed
        try:
            success, message = auth_manager.create_user(
                username=username,
                password=password,
                email=email,
                display_name=display_name or username,
                groups=groups,
                is_admin=is_admin
            )
        except TypeError as e:
            # Method doesn't accept all parameters, try with just basic ones
            logger.warning(f"create_user doesn't support all parameters: {e}")
            try:
                success, message = auth_manager.create_user(
                    username=username,
                    password=password,
                    display_name=display_name or username,
                    is_admin=is_admin
                )
                if success:
                    flash(f'{message} (Note: email and groups not supported by current auth backend)', 'warning')
            except Exception as e2:
                logger.error(f"Error creating user with basic parameters: {e2}")
                success = False
                message = str(e2)

        if success:
            flash(message, 'success')
            logger.info(f"Admin {session.get('username')} created user: {username}")
            return redirect(url_for('admin.users_list'))
        else:
            flash(f'Error creating user: {message}', 'error')

    return render_template('admin/users_form.html', action='create')


@admin_bp.route('/users/<username>', methods=['GET', 'POST'])
@admin_required
def users_edit(username):
    """Edit user"""

    # Get user data - handle different auth manager implementations
    user = None
    if hasattr(auth_manager, 'get_user'):
        user = auth_manager.get_user(username)
    elif hasattr(auth_manager, 'list_users'):
        # Fallback: find user in list
        try:
            users = auth_manager.list_users()
            user = next((u for u in users if u['username'] == username), None)
        except Exception as e:
            logger.error(f"Error listing users: {e}")

    if not user:
        flash('User not found', 'error')
        return redirect(url_for('admin.users_list'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        display_name = request.form.get('display_name', '').strip()
        groups = request.form.get('groups', '').strip()
        is_admin = request.form.get('is_admin') == 'on'
        is_active = request.form.get('is_active') == 'on'

        # Try to update user - handle different method signatures
        success = False
        message = ""

        if hasattr(auth_manager, 'update_user'):
            try:
                # Try with all parameters (new signature)
                success, message = auth_manager.update_user(
                    username=username,
                    email=email,
                    display_name=display_name,
                    groups=groups,
                    is_admin=is_admin,
                    is_active=is_active
                )
            except TypeError as e:
                # Method doesn't accept all parameters, try basic ones
                logger.warning(f"update_user doesn't support all parameters: {e}")
                try:
                    success, message = auth_manager.update_user(
                        username=username,
                        display_name=display_name,
                        is_admin=is_admin,
                        is_active=is_active
                    )
                    if success:
                        flash(f'{message} (Note: email and groups not supported by current auth backend)', 'warning')
                except Exception as e2:
                    logger.error(f"Error updating user with basic parameters: {e2}")
                    success = False
                    message = str(e2)
        else:
            success = False
            message = "Update user method not available in auth manager"

        if success:
            flash(message, 'success')
            logger.info(f"Admin {session.get('username')} updated user: {username}")
            # Refresh user data
            if hasattr(auth_manager, 'get_user'):
                user = auth_manager.get_user(username)
            elif hasattr(auth_manager, 'list_users'):
                users = auth_manager.list_users()
                user = next((u for u in users if u['username'] == username), None)
        else:
            flash(f'Error updating user: {message}', 'error')

    # Add groups_str for display in form
    if user:
        # Handle groups field
        if 'groups' in user:
            groups_list = user.get('groups', [])
            if isinstance(groups_list, list):
                user['groups_str'] = ', '.join(groups_list)
            else:
                user['groups_str'] = groups_list or ''
        else:
            user['groups_str'] = ''

        # Ensure email field exists
        if 'email' not in user:
            user['email'] = ''

    return render_template('admin/users_form.html', user=user, action='edit')


@admin_bp.route('/users/<username>/password', methods=['POST'])
@admin_required
def users_change_password(username):
    """Change user password"""

    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not new_password:
        flash('New password is required', 'error')
        return redirect(url_for('admin.users_edit', username=username))

    if new_password != confirm_password:
        flash('Passwords do not match', 'error')
        return redirect(url_for('admin.users_edit', username=username))

    if len(new_password) < 8:
        flash('Password must be at least 8 characters', 'error')
        return redirect(url_for('admin.users_edit', username=username))

    success, message = auth_manager.update_user_password(username, new_password)

    if success:
        flash(message, 'success')
        logger.info(f"Admin {session.get('username')} changed password for user: {username}")
    else:
        flash(f'Error changing password: {message}', 'error')

    return redirect(url_for('admin.users_edit', username=username))


@admin_bp.route('/users/<username>/delete', methods=['POST'])
@admin_required
def users_delete(username):
    """Delete (deactivate) user"""

    # Prevent self-deletion
    if username == session.get('username'):
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('admin.users_list'))

    success, message = auth_manager.delete_user(username)

    if success:
        flash(message, 'success')
        logger.info(f"Admin {session.get('username')} deleted user: {username}")
    else:
        flash(f'Error deleting user: {message}', 'error')

    return redirect(url_for('admin.users_list'))


# ============================================================================
# SYSTEM CONFIGURATION
# ============================================================================

@admin_bp.route('/config')
@admin_required
def config_view():
    """View system configuration"""

    config_path = _get_config_path()

    if not config_path.exists():
        flash(f'Configuration file not found at: {config_path}', 'error')
        logger.warning(f"Config file not found at: {config_path}")

        # Show where we looked
        data_dir = current_app.config.get('DATA_DIR')
        flash(f'Searched in: {data_dir}/, {Path(data_dir).parent}/, ~/.velocitycmdb/, ./', 'info')

        return redirect(url_for('admin.index'))

    try:
        with open(config_path, 'r') as f:
            config_data = f.read()
    except Exception as e:
        flash(f'Error reading configuration file: {str(e)}', 'error')
        logger.error(f"Error reading config: {str(e)}")
        return redirect(url_for('admin.index'))

    # Parse YAML for structured view
    try:
        config_dict = yaml.safe_load(config_data)
    except yaml.YAMLError as e:
        config_dict = None
        flash(f'Error parsing YAML: {e}', 'warning')

    return render_template('admin/config_view.html',
                           config_text=config_data,
                           config_dict=config_dict,
                           config_path=str(config_path))


@admin_bp.route('/config/edit', methods=['GET', 'POST'])
@admin_required
def config_edit():
    """Edit system configuration"""

    config_path = _get_config_path()

    if request.method == 'POST':
        new_config = request.form.get('config_text', '')

        # Validate YAML
        try:
            yaml.safe_load(new_config)
        except yaml.YAMLError as e:
            flash(f'Invalid YAML syntax: {e}', 'error')
            return render_template('admin/config_edit.html',
                                   config_text=new_config,
                                   config_path=str(config_path))

        # Backup current config
        if config_path.exists():
            backup_path = config_path.with_suffix('.yaml.backup')
            try:
                import shutil
                shutil.copy(config_path, backup_path)
                logger.info(f"Backed up config to: {backup_path}")
            except Exception as e:
                flash(f'Warning: Could not create backup: {str(e)}', 'warning')
                logger.warning(f"Backup failed: {str(e)}")

        # Write new config
        try:
            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(config_path, 'w') as f:
                f.write(new_config)

            flash('Configuration updated successfully. Restart application for changes to take effect.', 'success')
            logger.info(f"Admin {session.get('username')} updated system configuration at: {config_path}")
            return redirect(url_for('admin.config_view'))
        except Exception as e:
            flash(f'Error writing configuration: {str(e)}', 'error')
            logger.error(f"Error writing config: {str(e)}")

    # GET request
    if not config_path.exists():
        # Try to create a default config
        flash(f'Configuration file not found at: {config_path}', 'warning')
        config_text = """# VelocityCMDB Configuration
# Generated by admin interface

# Flask settings
flask:
  debug: false
  secret_key: change-me-in-production

# Authentication
auth:
  database:
    enabled: true
  ldap:
    enabled: false

# Network settings
network:
  ssh:
    timeout: 30
    port: 22
"""
        return render_template('admin/config_edit.html',
                               config_text=config_text,
                               config_path=str(config_path),
                               is_new=True)

    try:
        with open(config_path, 'r') as f:
            config_text = f.read()
    except Exception as e:
        flash(f'Error reading configuration: {str(e)}', 'error')
        logger.error(f"Error reading config: {str(e)}")
        return redirect(url_for('admin.index'))

    return render_template('admin/config_edit.html',
                           config_text=config_text,
                           config_path=str(config_path))


# ============================================================================
# AUTHENTICATION SETTINGS
# ============================================================================

@admin_bp.route('/auth-settings')
@admin_required
def auth_settings():
    """View authentication settings and methods"""

    auth_info = auth_manager.get_available_methods() if auth_manager else {}

    return render_template('admin/auth_settings.html', auth_info=auth_info)


# ============================================================================
# SYSTEM STATUS
# ============================================================================

@admin_bp.route('/system')
@admin_required
def system_status():
    """System status and statistics"""

    import sqlite3
    from pathlib import Path

    # Database statistics
    db_stats = {}

    # Use configured database path from Flask config with fallback
    assets_db_path = current_app.config.get('DATABASE')
    if assets_db_path:
        assets_db = Path(assets_db_path)
    else:
        # Fallback to legacy location
        assets_db = Path('app/assets.db')

    if assets_db.exists():
        try:
            conn = sqlite3.connect(str(assets_db))
            cursor = conn.cursor()

            # Get table sizes
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = cursor.fetchall()

            for table in tables:
                table_name = table[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                db_stats[table_name] = count

            conn.close()
        except Exception as e:
            logger.error(f"Error reading database stats: {str(e)}")
    else:
        logger.warning(f"Assets database not found at: {assets_db}")

    # Capture directory statistics
    capture_stats = {}
    capture_dir_path = current_app.config.get('CAPTURE_DIR')
    if capture_dir_path:
        capture_dir = Path(capture_dir_path)
        if capture_dir.exists():
            try:
                for subdir in capture_dir.iterdir():
                    if subdir.is_dir():
                        file_count = len(list(subdir.glob('*')))
                        capture_stats[subdir.name] = file_count
            except Exception as e:
                logger.error(f"Error reading capture stats: {str(e)}")
        else:
            logger.debug(f"Capture directory not found: {capture_dir}")

    # File system statistics
    data_dir_path = current_app.config.get('VELOCITYCMDB_DATA_DIR')
    if data_dir_path:
        data_dir = Path(data_dir_path)
    else:
        data_dir = Path.cwd()

    try:
        import shutil
        total, used, free = shutil.disk_usage(data_dir)

        fs_stats = {
            'total_gb': total / (1024 ** 3),
            'used_gb': used / (1024 ** 3),
            'free_gb': free / (1024 ** 3),
            'used_percent': (used / total) * 100,
            'data_dir': str(data_dir)
        }
    except Exception as e:
        logger.error(f"Error getting filesystem stats: {str(e)}")
        fs_stats = {
            'total_gb': 0,
            'used_gb': 0,
            'free_gb': 0,
            'used_percent': 0,
            'data_dir': str(data_dir),
            'error': str(e)
        }

    return render_template('admin/system_status.html',
                           db_stats=db_stats,
                           capture_stats=capture_stats,
                           fs_stats=fs_stats)


# ============================================================================
# API ENDPOINTS
# ============================================================================

@admin_bp.route('/api/users', methods=['GET'])
@admin_required
def api_users_list():
    """API endpoint to get user list"""

    users = []
    if auth_manager and hasattr(auth_manager, '_db_auth_available'):
        if auth_manager._db_auth_available:
            users = auth_manager.list_users()

    return jsonify(users)


@admin_bp.route('/api/system/health', methods=['GET'])
@admin_required
def api_system_health():
    """API endpoint for system health check"""

    health = {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'auth_methods': auth_manager.get_available_methods() if auth_manager else {},
        'session_active': 'logged_in' in session,
        'admin_user': session.get('username'),
        'config_path': str(_get_config_path()),
        'data_dir': current_app.config.get('DATA_DIR')
    }

    return jsonify(health)