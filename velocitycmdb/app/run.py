import json
import os
from pathlib import Path

# CRITICAL: Set data directory BEFORE importing app
# This ensures all components use the correct path
if 'VELOCITYCMDB_DATA_DIR' not in os.environ:
    data_dir = Path.home() / '.velocitycmdb' / 'data'
    os.environ['VELOCITYCMDB_DATA_DIR'] = str(data_dir)
    print(f"Set VELOCITYCMDB_DATA_DIR to: {data_dir}")

from velocitycmdb.app import create_app

if __name__ == '__main__':
    print("""VelocityCMDB is currently in Proof of Concept (POC) stage and is under active development. While functional, it is not yet recommended for production environments. The codebase and features are subject to significant changes. Feel free to test, contribute, and provide feedback, but please exercise caution in production or security-critical environments.""")
    config_name = os.environ.get('FLASK_ENV', 'development')
    app, socketio = create_app(config_name)

    # Verify database paths
    print(f"\nDatabase paths configured:")
    print(f"  Assets DB: {app.config['DATABASE']}")
    print(f"  ARP DB: {app.config['ARP_DATABASE']}")
    print(f"  Users DB: {app.config['USERS_DATABASE']}")
    print(f"  Data Dir: {app.config['VELOCITYCMDB_DATA_DIR']}")
    print("")


    @app.template_filter('from_json')
    def from_json_filter(value):
        """Custom Jinja2 filter to parse JSON strings"""
        if value:
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
        return []


    # Apply login_required to dashboard routes
    from velocitycmdb.app.blueprints.auth.routes import login_required
    from velocitycmdb.app.blueprints.dashboard import dashboard_bp

    # Protect dashboard routes
    for endpoint, view_func in dashboard_bp.view_functions.items():
        dashboard_bp.view_functions[endpoint] = login_required(view_func)

    socketio.run(app, debug=True, host='0.0.0.0', port=8086, allow_unsafe_werkzeug=True)