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

from velocitycmdb.app.blueprints.admin import admin_bp
from velocitycmdb.app.blueprints.arp import arp_bp
from velocitycmdb.app.blueprints.auth.routes import init_auth_manager
from velocitycmdb.app.blueprints.admin.routes import init_admin
from velocitycmdb.app.blueprints.bulk import bulk_bp
from velocitycmdb.app.blueprints.capture import capture_bp
from velocitycmdb.app.blueprints.changes import changes_bp
from velocitycmdb.app.blueprints.collection.routes import collection_bp
from velocitycmdb.app.blueprints.maps import maps_bp
from velocitycmdb.app.blueprints.notes import notes_bp
from velocitycmdb.app.blueprints.osversions import osversions_bp
from velocitycmdb.app.blueprints.roles import roles_bp
from velocitycmdb.app.blueprints.sites import sites_bp
from velocitycmdb.app.blueprints.vendors import vendors_bp
from velocitycmdb.app.blueprints.search import search_bp
from velocitycmdb.app.blueprints.discovery import discovery_bp
from velocitycmdb.app.blueprints.scmaps import scmaps_bp

socketio = SocketIO()


def load_scmaps_config(app):
    """Load SCMAPS_DIR from config.yaml"""
    import yaml
    config_path = os.path.join(os.path.dirname(os.path.dirname(app.root_path)), 'config.yaml')

    app.logger.info(f"[SCMAPS] Looking for config at: {config_path}")

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        scmaps_dir = config.get('scmaps', {}).get('data_dir', 'scmaps_data')

        if scmaps_dir.startswith('~'):
            scmaps_dir = os.path.expanduser(scmaps_dir)

        if not os.path.isabs(scmaps_dir):
            project_root = os.path.dirname(os.path.dirname(app.root_path))
            scmaps_dir = os.path.join(project_root, scmaps_dir)

        app.config['SCMAPS_DIR'] = scmaps_dir
        app.logger.info(f"[SCMAPS] Configured SCMAPS_DIR: {scmaps_dir}")
        os.makedirs(scmaps_dir, exist_ok=True)

def create_app(config_name='development'):
    """
    Application factory pattern for creating Flask app.

    Args:
        config_name: Configuration name (development, production, testing)

    Returns:
        Tuple of (Flask app, SocketIO instance)
    """
    app = Flask(__name__)

    # Get data directory from environment (set by CLI or run.py)
    data_dir = os.environ.get('VELOCITYCMDB_DATA_DIR',
                              os.path.join(os.path.expanduser('~'), '.velocitycmdb', 'data'))

    # Basic configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['DATABASE'] = os.path.join(data_dir, 'assets.db')
    app.config['ARP_DATABASE'] = os.path.join(data_dir, 'arp_cat.db')
    app.config['USERS_DATABASE'] = os.path.join(data_dir, 'users.db')
    app.config['VELOCITYCMDB_DATA_DIR'] = data_dir

    # NEW: Capture and jobs directories for collection system
    app.config['CAPTURE_DIR'] = os.path.join(data_dir, 'capture')
    app.config['JOBS_DIR'] = os.path.join(data_dir, 'jobs')
    app.config['FINGERPRINTS_DIR'] = os.path.join(data_dir, 'fingerprints')
    app.config['DISCOVERY_DIR'] = os.path.join(os.path.dirname(data_dir), 'discovery')
    app.config['SCMAPS_DIR'] = os.path.join(os.path.dirname(data_dir), 'discovery', 'maps')

    # Ensure data directory exists
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        pass

    # Initialize SocketIO
    socketio.init_app(app, cors_allowed_origins="*")
    load_scmaps_config(app)

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

    from velocitycmdb.app.config_loader import load_config
    config = load_config('./config.yaml')
    auth_config = config.get('authentication', {})
    auth_manager = init_auth_manager(auth_config)
    init_admin(auth_manager)

    # DEPRECATED: Legacy paths - keep for backwards compatibility
    # These are being phased out in favor of the paths above
    app.config['SESSIONS_YAML'] = 'pcng/sessions.yaml'

    # NOTE: Don't use these hardcoded pcng paths - use the config paths above
    # app.config['CAPTURE_DIR'] = 'pcng/capture'  # OLD - don't use
    # app.config['FINGERPRINTS_DIR'] = 'pcng/fingerprints'  # OLD - don't use

    # Root route redirect
    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    return app, socketio
