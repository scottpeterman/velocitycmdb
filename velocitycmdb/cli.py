#!/usr/bin/env python3
"""
VelocityCMDB CLI - Command Line Interface
"""
import argparse
import getpass
import json
import os
import secrets
from pathlib import Path

DEFAULT_CONFIG = """# VelocityCMDB Configuration File
# Generated automatically - customize as needed
#
# Authentication Methods:
#   - database: Local SQLite database (recommended for small teams)
#   - local: OS-level authentication (Windows/Linux)
#   - ldap: LDAP/Active Directory (enterprise)
#
# Multiple methods can be enabled simultaneously

authentication:
  default_method: database
  use_ssh_fallback: true
  ssh_host: localhost

  # Database Authentication (Default)
  database:
    enabled: true
    path: ~/.velocitycmdb/data/users.db

  # Local OS Authentication
  local:
    enabled: false
    domain_required: false
    use_computer_name_as_domain: true

  # LDAP/Active Directory Authentication
  ldap:
    enabled: false
    server: null
    port: 389
    use_ssl: false
    base_dn: null
    user_dn_template: null
    search_groups: false
    group_base_dn: null
    group_filter: "(&(objectClass=group)(member={{{{user_dn}}}}))"
    timeout: 10
    max_retries: 3

# Default Credentials for Network Device Access
# Used by collection jobs and automation scripts
credentials:
  username: {default_username}
  # Password is never stored here - retrieved at runtime from credential system

# Flask Settings
flask:
  secret_key: {secret_key}
  session_timeout_minutes: 120

# Server Settings
server:
  host: 0.0.0.0
  port: 8086
  debug: false

# Logging Configuration
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: null

# SecureCartography Maps Directory
scmaps:
  data_dir: ~/.velocitycmdb/discovery/maps

# Getting Started:
# 1. Run: python -m velocitycmdb.cli init
# 2. Run: python -m velocitycmdb.app.run
# 3. Login with your configured admin credentials
"""


def setup_data_dir():
    """Set data directory environment variable if not already set."""
    if 'VELOCITYCMDB_DATA_DIR' not in os.environ:
        data_dir = Path.home() / '.velocitycmdb' / 'data'
        os.environ['VELOCITYCMDB_DATA_DIR'] = str(data_dir)
        print(f"Set VELOCITYCMDB_DATA_DIR to: {data_dir}")
    return Path(os.environ['VELOCITYCMDB_DATA_DIR'])


def prompt_credentials(args) -> tuple[str, str, str]:
    """
    Prompt for credentials interactively or use CLI arguments.

    Returns:
        tuple: (default_username, admin_username, admin_password)
    """
    print("\n" + "-" * 60)
    print("Credential Configuration")
    print("-" * 60)

    # Default username for network device access
    if args.default_username:
        default_username = args.default_username
        print(f"• Default network username: {default_username} (from --default-username)")
    else:
        current_user = getpass.getuser()
        default_username = input(f"Default network device username [{current_user}]: ").strip()
        if not default_username:
            default_username = current_user

    # Admin username for web UI
    if args.admin_username:
        admin_username = args.admin_username
        print(f"• Admin username: {admin_username} (from --admin-username)")
    else:
        admin_username = input("Admin username for web UI [admin]: ").strip()
        if not admin_username:
            admin_username = 'admin'

    # Admin password
    if args.admin_password:
        admin_password = args.admin_password
        print("• Admin password: (from --admin-password)")
    else:
        while True:
            admin_password = getpass.getpass(f"Admin password for '{admin_username}': ")
            if not admin_password:
                print("  Password cannot be empty.")
                continue
            confirm_password = getpass.getpass("Confirm admin password: ")
            if admin_password != confirm_password:
                print("  Passwords do not match. Try again.")
                continue
            break

    print("-" * 60 + "\n")
    return default_username, admin_username, admin_password


def cmd_init(args):
    """Initialize the VelocityCMDB data directory, config, databases, and admin user."""
    data_dir = setup_data_dir()
    config_dir = Path.home() / '.velocitycmdb'

    print("\n" + "=" * 60)
    print("python -m velocitycmdb.cli initialization")
    print("=" * 60)

    # Check if config exists and we're not forcing
    config_path = config_dir / 'config.yaml'
    if config_path.exists() and not args.force:
        print(f"\n• Config file already exists: {config_path}")
        print("  (Use --force to overwrite)")

        # Still prompt for admin credentials if database doesn't exist
        users_db = data_dir / 'users.db'
        if not users_db.exists():
            print("\n  Database not found - will create with new credentials.")
            default_username, admin_username, admin_password = prompt_credentials(args)
        else:
            print("  Skipping credential setup (use --force to reconfigure)")
            return
    else:
        # Get credentials (interactive or from args)
        default_username, admin_username, admin_password = prompt_credentials(args)

        # Ensure config directory exists
        config_dir.mkdir(parents=True, exist_ok=True)

        # Generate config with credentials
        secret_key = secrets.token_hex(32)
        config_content = DEFAULT_CONFIG.format(
            secret_key=secret_key,
            default_username=default_username
        )

        with open(config_path, 'w') as f:
            f.write(config_content)
        print(f"✓ Created config file: {config_path}")

    # Use the DatabaseInitializer to create everything
    from velocitycmdb.db.initializer import DatabaseInitializer

    print(f"\nInitializing databases in: {data_dir}")
    initializer = DatabaseInitializer(str(data_dir))

    success, message = initializer.initialize_all(
        admin_username=admin_username,
        admin_password=admin_password
    )

    if success:
        # Verify files were created
        print("\n" + "-" * 60)
        print("Verification:")
        print("-" * 60)

        files_to_check = [
            (config_path, "Config file"),
            (data_dir / 'users.db', "Users database"),
            (data_dir / 'assets.db', "Assets database"),
            (data_dir / 'arp_cat.db', "ARP database"),
        ]

        all_good = True
        for file_path, label in files_to_check:
            if file_path.exists():
                size = file_path.stat().st_size
                print(f"  ✓ {label}: {file_path} ({size} bytes)")
            else:
                print(f"  ✗ {label}: {file_path} MISSING")
                all_good = False

        if all_good:
            print("\n" + "=" * 60)
            print("Initialization complete!")
            print("=" * 60)
            print(f"\nAdmin credentials:")
            print(f"  Username: {admin_username}")
            print(f"  Password: {'*' * len(admin_password)}")
            print(f"\nDefault network username: {default_username}")
            print("  (Used by collection jobs - stored in config.yaml)")
            print("\nNext step:")
            print("  python -m velocitycmdb.app.run")
            print("\nConfig file: ~/.velocitycmdb/config.yaml")
            print("=" * 60 + "\n")
        else:
            print("\n✗ Some files were not created. Check errors above.")
    else:
        print(f"\n✗ Initialization failed: {message}")


def cmd_run(args):
    """Run the VelocityCMDB development server."""
    setup_data_dir()

    # Check if initialized
    config_path = Path.home() / '.velocitycmdb' / 'config.yaml'
    if not config_path.exists():
        print("\nError: VelocityCMDB has not been initialized.")
        print("Please run: python -m velocitycmdb.cli init\n")
        return

    from velocitycmdb.app import create_app

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

    # Apply login_required to dashboard routes
    from velocitycmdb.app.blueprints.auth.routes import login_required
    from velocitycmdb.app.blueprints.dashboard import dashboard_bp

    # Protect dashboard routes
    for endpoint, view_func in dashboard_bp.view_functions.items():
        dashboard_bp.view_functions[endpoint] = login_required(view_func)

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


def main():
    parser = argparse.ArgumentParser(
        prog='velocitycmdb',
        description='VelocityCMDB - Network Configuration Management Database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # init subcommand
    init_parser = subparsers.add_parser(
        'init',
        help='Initialize config, databases, and admin user',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m velocitycmdb.cli init                                    # Interactive prompts
  python -m velocitycmdb.cli init --default-username speterman      # Set network username
  python -m velocitycmdb.cli init --admin-password secret123        # Non-interactive admin setup
  python -m velocitycmdb.cli init -u netadmin -p secret --force     # Full non-interactive
        """
    )
    init_parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Overwrite existing config file'
    )
    init_parser.add_argument(
        '--default-username', '-u',
        type=str,
        help='Default username for network device access (used by collection jobs)'
    )
    init_parser.add_argument(
        '--admin-username',
        type=str,
        help='Admin username for web UI (default: admin)'
    )
    init_parser.add_argument(
        '--admin-password', '-p',
        type=str,
        help='Admin password for web UI (prompts if not provided)'
    )

    # run subcommand
    run_parser = subparsers.add_parser(
        'run',
        help='Run the development server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m velocitycmdb.app.run                      # Default: port 8086, no SSL
  python -m velocitycmdb.app.run -p 8443 --ssl        # Port 8443 with self-signed SSL
  python -m velocitycmdb.app.run --port 5000          # Port 5000, no SSL
  python -m velocitycmdb.app.run --ssl                # Default port with SSL
        """
    )
    run_parser.add_argument(
        '-p', '--port',
        type=int,
        default=8086,
        help='Port to listen on (default: 8086)'
    )
    run_parser.add_argument(
        '--ssl',
        action='store_true',
        help='Enable HTTPS with Flask\'s adhoc self-signed certificate'
    )
    run_parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    run_parser.add_argument(
        '--no-debug',
        action='store_true',
        help='Disable debug mode'
    )

    args = parser.parse_args()

    if args.command == 'init':
        cmd_init(args)
    elif args.command == 'run':
        cmd_run(args)
    else:
        print("VelocityCMDB - Network Configuration Management Database\n")
        print("Quick start:")
        print("  python -m velocitycmdb.cli init    # Initialize (first time setup)")
        print("  python -m velocitycmdb.app.run     # Start the server\n")
        parser.print_help()


if __name__ == '__main__':
    main()