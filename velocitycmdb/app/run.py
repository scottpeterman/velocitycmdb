import argparse
import json
import os
from pathlib import Path

from velocitycmdb.app import create_app

# CRITICAL: Set data directory BEFORE importing app
# This ensures all components use the correct path
if 'VELOCITYCMDB_DATA_DIR' not in os.environ:
    data_dir = Path.home() / '.velocitycmdb' / 'data'
    os.environ['VELOCITYCMDB_DATA_DIR'] = str(data_dir)
    print(f"Set VELOCITYCMDB_DATA_DIR to: {data_dir}")



def parse_args():
    parser = argparse.ArgumentParser(
        description='VelocityCMDB Development Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                      # Default: port 8086, no SSL
  python run.py -p 8443 --ssl        # Port 8443 with self-signed SSL
  python run.py --port 5000          # Port 5000, no SSL
  python run.py --ssl                # Default port with SSL
        """
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=8086,
        help='Port to listen on (default: 8086)'
    )
    parser.add_argument(
        '--ssl',
        action='store_true',
        help='Enable HTTPS with Flask\'s adhoc self-signed certificate'
    )
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--no-debug',
        action='store_true',
        help='Disable debug mode'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    print("""
================================================================================
VelocityCMDB is currently in Proof of Concept (POC) stage and is under active
development. While functional, it is not yet recommended for production
environments. The codebase and features are subject to significant changes.
Feel free to test, contribute, and provide feedback, but please exercise
caution in production or security-critical environments.
================================================================================
""")

    config_name = os.environ.get('FLASK_ENV', 'development')
    app, socketio = create_app(config_name)

    # Verify database paths
    print(f"Database paths configured:")
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

    # NOTE: Route protection is now handled globally via before_request in create_app()
    # All routes except auth.* and static are automatically protected

    # Build SSL context if requested
    ssl_context = None
    if args.ssl:
        ssl_context = 'adhoc'
        protocol = 'https'
        print("SSL enabled using Flask's adhoc self-signed certificate")
        print("  Note: Browser will show security warning - this is expected")
    else:
        protocol = 'http'

    debug_mode = not args.no_debug
    print(f"Starting server: {protocol}://{args.host}:{args.port}")
    print(f"Debug mode: {debug_mode}")
    print("")

    socketio.run(
        app,
        debug=debug_mode,
        host=args.host,
        port=args.port,
        allow_unsafe_werkzeug=True,
        ssl_context=ssl_context
    )