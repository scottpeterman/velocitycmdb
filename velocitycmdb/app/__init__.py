# velocitycmdb/app/__init__.py
"""
Flask application factory for VelocityCMDB.

Creates and configures the Flask application with all blueprints,
SocketIO support, and proper path configuration.
"""

from flask import Flask
from flask_socketio import SocketIO
import os
from pathlib import Path

from velocitycmdb.app.blueprints.connections import connections_bp
from velocitycmdb.app.config_loader import load_config, get_config_path
from velocitycmdb.app.blueprints.admin import admin_bp
from velocitycmdb.app.blueprints.arp import arp_bp
from velocitycmdb.app.blueprints.auth.routes import init_auth_manager
from velocitycmdb.app.blueprints.admin.routes import init_admin
from velocitycmdb.app.blueprints.bulk import bulk_bp
from velocitycmdb.app.blueprints.capture import capture_bp
from velocitycmdb.app.blueprints.changes import changes_bp
from velocitycmdb.app.blueprints.collection.routes import collection_bp
from velocitycmdb.app.blueprints.environment import environment_bp
from velocitycmdb.app.blueprints.maps import maps_bp
from velocitycmdb.app.blueprints.notes import notes_bp
from velocitycmdb.app.blueprints.osversions import osversions_bp
from velocitycmdb.app.blueprints.roles import roles_bp
from velocitycmdb.app.blueprints.sites import sites_bp
from velocitycmdb.app.blueprints.vendors import vendors_bp
from velocitycmdb.app.blueprints.search import search_bp
from velocitycmdb.app.blueprints.discovery import discovery_bp
from velocitycmdb.app.blueprints.scmaps import scmaps_bp
from velocitycmdb.app.blueprints.ip_locator import ip_locator_bp

socketio = SocketIO()


def expand_path(path_str: str) -> str:
    """Expand ~ and make path absolute"""
    if path_str:
        return os.path.abspath(os.path.expanduser(path_str))
    return path_str


def create_app(config_name='development'):
    """
    Application factory pattern for creating Flask app.

    Args:
        config_name: Configuration name (development, production, testing)

    Returns:
        Tuple of (Flask app, SocketIO instance)
    """
    app = Flask(__name__)

    # Load configuration from ~/.velocitycmdb/config.yaml
    config_path = get_config_path()
    config = load_config(config_path)

    # Store config file path for diagnostics
    app.config['CONFIG_FILE'] = config_path

    # Get paths from config (with fallbacks to defaults)
    paths_config = config.get('paths', {})

    # Data directory - can also be set via environment variable
    data_dir = os.environ.get(
        'VELOCITYCMDB_DATA_DIR',
        expand_path(paths_config.get('data_dir', '~/.velocitycmdb/data'))
    )

    # Basic configuration
    flask_config = config.get('flask', {})
    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY',
        flask_config.get('secret_key') or 'dev-secret-key-change-in-production'
    )

    # Database paths (always relative to data_dir)
    app.config['DATABASE'] = os.path.join(data_dir, 'assets.db')
    app.config['ARP_DATABASE'] = os.path.join(data_dir, 'arp_cat.db')
    app.config['USERS_DATABASE'] = os.path.join(data_dir, 'users.db')
    app.config['VELOCITYCMDB_DATA_DIR'] = data_dir

    # Directory paths from config (with defaults)
    app.config['CAPTURE_DIR'] = expand_path(
        paths_config.get('capture_dir', os.path.join(data_dir, 'capture'))
    )
    app.config['JOBS_DIR'] = expand_path(
        paths_config.get('jobs_dir', os.path.join(data_dir, 'jobs'))
    )
    app.config['FINGERPRINTS_DIR'] = expand_path(
        paths_config.get('fingerprints_dir', os.path.join(data_dir, 'fingerprints'))
    )
    app.config['DISCOVERY_DIR'] = expand_path(
        paths_config.get('discovery_dir', os.path.join(os.path.dirname(data_dir), 'discovery'))
    )
    app.config['SCMAPS_DIR'] = expand_path(
        paths_config.get('scmaps_dir') or
        config.get('scmaps', {}).get('data_dir') or
        os.path.join(os.path.dirname(data_dir), 'discovery', 'maps')
    )
    app.config['MAPS_BASE'] = expand_path(
        paths_config.get('maps_dir', os.path.join(data_dir, 'maps'))
    )

    # Ensure critical directories exist
    for dir_key in ['VELOCITYCMDB_DATA_DIR', 'CAPTURE_DIR', 'JOBS_DIR',
                    'FINGERPRINTS_DIR', 'DISCOVERY_DIR', 'SCMAPS_DIR', 'MAPS_BASE']:
        dir_path = app.config.get(dir_key)
        if dir_path:
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                app.logger.warning(f"Could not create directory {dir_path}: {e}")

    # Initialize SocketIO
    socketio.init_app(app, cors_allowed_origins="*")

    @socketio.on('connect')
    def require_login_socketio():
        from flask import session
        if not session.get('logged_in'):
            return False

    # Register SocketIO event handlers
    from velocitycmdb.app.blueprints.admin.maintenance_socktio import register_maintenance_socketio_handlers
    register_maintenance_socketio_handlers(socketio, app)

    # Register blueprints
    from velocitycmdb.app.blueprints.auth import auth_bp
    from velocitycmdb.app.blueprints.dashboard import dashboard_bp
    from velocitycmdb.app.blueprints.assets import assets_bp
    from velocitycmdb.app.blueprints.coverage import coverage_bp
    from velocitycmdb.app.blueprints.components import components_bp
    from velocitycmdb.app.blueprints.terminal import terminal_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(changes_bp, url_prefix='/changes')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(assets_bp, url_prefix='/assets')
    app.register_blueprint(coverage_bp, url_prefix='/coverage')
    app.register_blueprint(maps_bp, url_prefix='/maps')
    app.register_blueprint(arp_bp, url_prefix='/arp')
    app.register_blueprint(components_bp, url_prefix='/components')
    app.register_blueprint(terminal_bp, url_prefix='/terminal')
    app.register_blueprint(capture_bp)
    app.register_blueprint(osversions_bp, url_prefix='/osversions')
    app.register_blueprint(bulk_bp, url_prefix='/bulk')
    app.register_blueprint(sites_bp, url_prefix='/sites')
    app.register_blueprint(roles_bp, url_prefix='/roles')
    app.register_blueprint(vendors_bp, url_prefix='/vendors')
    app.register_blueprint(notes_bp, url_prefix='/notes')
    app.register_blueprint(search_bp, url_prefix='/search')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(discovery_bp, url_prefix='/discovery')
    app.register_blueprint(collection_bp, url_prefix='/collection')
    app.register_blueprint(scmaps_bp, url_prefix='/scmaps')
    app.register_blueprint(environment_bp)
    app.register_blueprint(ip_locator_bp)
    app.register_blueprint(connections_bp, url_prefix='/connections')

    # Initialize authentication
    auth_config = config.get('authentication', {})
    auth_manager = init_auth_manager(auth_config)
    init_admin(auth_manager)

    # =========================================================================
    # GLOBAL AUTHENTICATION - Secure all routes by default
    # =========================================================================
    @app.before_request
    def require_login():
        """
        Require authentication for all routes except auth blueprint and static files.
        This is a 'secure by default' approach - everything is protected unless
        explicitly whitelisted here.
        """
        from flask import request, redirect, url_for, session

        # Endpoints that don't require authentication
        public_endpoints = {
            'auth.login',
            'auth.logout',
            'auth.get_auth_methods',
            'static',
        }

        # Check if current endpoint is public
        if request.endpoint:
            # Direct match
            if request.endpoint in public_endpoints:
                return None
            # Prefix match for static files
            if request.endpoint.startswith('static'):
                return None

        # Check if user is authenticated
        if not session.get('logged_in'):
            # For API endpoints, return 401 instead of redirect
            if request.path.startswith('/api/') or request.is_json:
                from flask import jsonify
                return jsonify({'error': 'Authentication required'}), 401
            # For regular requests, redirect to login
            return redirect(url_for('auth.login', next=request.url))

        return None

    # DEPRECATED: Legacy paths - keep for backwards compatibility
    app.config['SESSIONS_YAML'] = 'pcng/sessions.yaml'

    # Root route redirect
    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    return app, socketio