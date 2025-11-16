"""
Command-line interface for VelocityCMDB
"""
import click
import os
import sys
from pathlib import Path
import shutil
import webbrowser

# ============================================================================
# SMART PATH DETECTION
# ============================================================================

def get_default_data_dir():
    """
    Determine default data directory with smart detection

    Priority:
    1. VELOCITYCMDB_DATA_DIR environment variable
    2. ~/.velocitycmdb (standard install)
    3. Current directory if it looks like dev environment

    Returns:
        Path: Base directory (not the data/ subdirectory)
    """
    # Check environment variable first
    env_dir = os.environ.get('VELOCITYCMDB_DATA_DIR')
    if env_dir:
        path = Path(env_dir)
        if path.exists():
            return path

    # Check for standard install location
    if os.name == 'nt':  # Windows
        standard_dir = Path(os.environ.get('USERPROFILE', '~')) / '.velocitycmdb'
    else:  # Linux/macOS
        standard_dir = Path.home() / '.velocitycmdb'

    standard_dir = standard_dir.expanduser()

    if standard_dir.exists():
        return standard_dir

    # Development mode - check if current directory looks like velocitycmdb project
    cwd = Path.cwd()
    if (cwd / 'velocitycmdb').exists():
        # This looks like the project root
        if (cwd / 'assets.db').exists() or (cwd / 'config.yaml').exists():
            click.echo(f"🔧 Development mode detected: {cwd}", err=True)
            return cwd

    # Default to standard location (will be created by init)
    return standard_dir


def find_data_path(base_dir: Path) -> Path:
    """
    Find actual data directory from base directory

    Standard structure (production):
      ~/.velocitycmdb/
      ├── data/          <- databases and captures here
      └── discovery/     <- discovery output here (parallel to data/)

    Dev structure (fallback):
      /project_root/
      ├── assets.db      <- databases at root
      └── data/          <- captures here

    Args:
        base_dir: Base directory to search from

    Returns:
        Path: Actual data directory containing databases
    """
    # Check standard structure: ~/.velocitycmdb/data/
    if (base_dir / 'data' / 'assets.db').exists():
        return base_dir / 'data'

    # Check dev structure: /project_root/assets.db
    if (base_dir / 'assets.db').exists():
        return base_dir

    # Default to data/ subdirectory (standard structure)
    return base_dir / 'data'


DEFAULT_DATA_DIR = get_default_data_dir()


# ============================================================================
# MAIN GROUP
# ============================================================================

@click.group()
@click.version_option(version='0.9.0', prog_name='VelocityCMDB')
def main():
    """VelocityCMDB - Fast operational CMDB for network teams"""
    pass


# ============================================================================
# COMMANDS
# ============================================================================

@main.command()
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
@click.option('--admin-password', default='admin',
              help='Initial admin password')
def init(data_dir, admin_password):
    """Initialize VelocityCMDB databases"""
    from velocitycmdb.db import DatabaseInitializer, DatabaseChecker

    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    click.echo(f"Initializing VelocityCMDB...")
    click.echo(f"Base directory: {base_path}")
    click.echo(f"Data directory: {data_path}\n")

    # Check if already initialized
    checker = DatabaseChecker(data_dir=str(data_path))
    if not checker.needs_initialization():
        click.echo("⚠️  Databases already exist!")
        if not click.confirm('Reinitialize (will preserve existing data)?', default=False):
            click.echo("Initialization cancelled")
            click.echo("\nTip: Use 'velocitycmdb reset' to start completely fresh")
            return

    # Initialize
    initializer = DatabaseInitializer(data_dir=str(data_path))
    success, message = initializer.initialize_all(admin_password=admin_password)

    if success:
        click.echo("\n" + "=" * 60)
        click.echo("✓ VelocityCMDB initialized successfully!")
        click.echo("=" * 60)
        click.echo(f"\nData directory: {data_path}")
        click.echo("\nDefault credentials:")
        click.echo("  Username: admin")
        click.echo(f"  Password: {admin_password}")
        if admin_password == 'admin':
            click.echo("\n⚠️  CHANGE THE DEFAULT PASSWORD!")
        click.echo("\nNext steps:")
        click.echo("  velocitycmdb start")
    else:
        click.echo(f"\n✗ Initialization failed: {message}", err=True)
        sys.exit(1)


@main.command()
@click.option('--host', default='0.0.0.0', help='Host to bind to')
@click.option('--port', default=8086, help='Port to bind to')
@click.option('--debug', is_flag=True, help='Run in debug mode')
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
@click.option('--no-browser', is_flag=True, help="Don't open browser automatically")
def start(host, port, debug, data_dir, no_browser):
    """Start VelocityCMDB web interface"""
    from velocitycmdb.db import DatabaseChecker

    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    # Check if initialized
    checker = DatabaseChecker(data_dir=str(data_path))
    if checker.needs_initialization():
        click.echo("✗ VelocityCMDB not initialized!")
        click.echo(f"\nData directory checked: {data_path}")
        click.echo("\nRun: velocitycmdb init")
        sys.exit(1)

    click.echo(f"Starting VelocityCMDB on {host}:{port}")
    click.echo(f"Data directory: {data_path}")
    click.echo(f"Access at: http://localhost:{port}")
    click.echo("\nPress Ctrl+C to stop\n")

    # Set environment
    os.environ['VELOCITYCMDB_DATA_DIR'] = str(data_path)

    # Import and run Flask app
    from velocitycmdb.app import create_app

    app, socketio = create_app()

    # Open browser automatically (unless disabled)
    if not debug and not no_browser:
        import threading
        def open_browser():
            import time
            time.sleep(1.5)  # Give server time to start
            webbrowser.open(f'http://localhost:{port}')

        threading.Thread(target=open_browser, daemon=True).start()

    socketio.run(app, host=host, port=port, debug=debug)


@main.command()
@click.option('--seed-ip', prompt='Seed IP address', help='Starting IP for discovery')
@click.option('--username', prompt='Username', help='Device username')
@click.option('--password', prompt='Password', hide_input=True, help='Device password')
@click.option('--site-name', default='network', help='Site name for this discovery')
@click.option('--alternate-username', default='', help='Alternate username (optional)')
@click.option('--alternate-password', default='', help='Alternate password (optional)')
@click.option('--max-devices', default=100, help='Maximum devices to discover')
@click.option('--timeout', default=30, help='Connection timeout in seconds')
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR), help='Data directory path')
def discover(seed_ip, username, password, site_name, alternate_username, alternate_password,
             max_devices, timeout, data_dir):
    """
    Run network discovery from command line

    Discovers network topology using CDP/LLDP from a seed device.
    """
    from velocitycmdb.services.discovery import DiscoveryOrchestrator

    base_path = Path(data_dir)

    # Discovery output goes to base_path/discovery (parallel to data/)
    output_dir = base_path / 'discovery'
    output_dir.mkdir(parents=True, exist_ok=True)

    click.echo("\n" + "=" * 60)
    click.echo("Network Discovery")
    click.echo("=" * 60)
    click.echo(f"Seed IP:     {seed_ip}")
    click.echo(f"Site:        {site_name}")
    click.echo(f"Max devices: {max_devices}")
    click.echo(f"Output:      {output_dir}")
    click.echo("=" * 60 + "\n")

    # Progress callback
    last_progress = [0]
    def progress_callback(data):
        progress = data.get('progress', 0)
        message = data.get('message', '')

        if progress > last_progress[0]:
            click.echo(f"[{progress}%] {message}")
            last_progress[0] = progress
        elif message and 'discovered' in message.lower():
            click.echo(f"  • {message}")

    # Run discovery
    orchestrator = DiscoveryOrchestrator(output_dir=output_dir)

    try:
        result = orchestrator.run_full_discovery(
            seed_ip=seed_ip,
            username=username,
            password=password,
            alternate_username=alternate_username if alternate_username else None,
            alternate_password=alternate_password if alternate_password else None,
            site_name=site_name,
            max_devices=max_devices,
            timeout=timeout,
            progress_callback=progress_callback
        )

        if result['success']:
            click.echo("\n" + "=" * 60)
            click.echo("✓ Discovery Complete!")
            click.echo("=" * 60)
            click.echo(f"Devices discovered: {result['device_count']}")
            click.echo(f"Sites identified:   {result['site_count']}")
            click.echo(f"\nFiles created:")
            click.echo(f"  • Topology:  {result['topology_file']}")
            click.echo(f"  • Inventory: {result['inventory_file']}")
            if result.get('map_file'):
                click.echo(f"  • Map:       {result['map_file']}")
        else:
            click.echo(f"\n✗ Discovery failed: {result.get('error')}", err=True)
            sys.exit(1)

    except KeyboardInterrupt:
        click.echo("\n\n✗ Discovery cancelled by user")
        sys.exit(130)
    except Exception as e:
        click.echo(f"\n✗ Discovery error: {str(e)}", err=True)
        sys.exit(1)


@main.command()
@click.option('--port', default=8086, help='Port number')
def open(port):
    """Open VelocityCMDB dashboard in browser"""
    url = f'http://localhost:{port}'
    click.echo(f"Opening {url}...")
    webbrowser.open(url)


@main.command()
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
def status(data_dir):
    """Check VelocityCMDB status"""
    from velocitycmdb.db import DatabaseChecker

    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    click.echo("VelocityCMDB Status")
    click.echo("=" * 60)
    click.echo(f"Base directory: {base_path}")
    click.echo(f"Data directory: {data_path}")

    # Check installation
    if not data_path.exists():
        click.echo(f"\n✗ Data directory not found: {data_path}")
        click.echo("\nRun: velocitycmdb init")
        return

    # Get detailed status
    checker = DatabaseChecker(data_dir=str(data_path))

    if checker.needs_initialization():
        click.echo("\n⚠️  Databases need initialization")
        click.echo("\nRun: velocitycmdb init")
        return

    status_info = checker.get_status()

    click.echo("\nDatabases:")

    # Assets database
    if status_info['assets_db']['exists']:
        size_mb = status_info['assets_db']['size'] / 1024 / 1024
        click.echo(f"  ✓ assets.db: {status_info['assets_db']['device_count']} devices, "
                   f"{status_info['assets_db']['site_count']} sites ({size_mb:.1f} MB)")
    else:
        click.echo("  ✗ assets.db: Missing")

    # ARP database
    if status_info['arp_db']['exists']:
        size_mb = status_info['arp_db']['size'] / 1024 / 1024
        click.echo(f"  ✓ arp_cat.db: {status_info['arp_db']['entry_count']} entries ({size_mb:.1f} MB)")
    else:
        click.echo("  ✗ arp_cat.db: Missing")

    # Users database
    if status_info['users_db']['exists']:
        size_kb = status_info['users_db']['size'] / 1024
        click.echo(f"  ✓ users.db: {status_info['users_db']['user_count']} users ({size_kb:.1f} KB)")
    else:
        click.echo("  ✗ users.db: Missing")

    # Show project structure type
    if (base_path / 'velocitycmdb').exists():
        click.echo("\n📁 Project structure: Development mode")
    else:
        click.echo("\n📁 Project structure: Standard install")


@main.command()
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
@click.option('--yes', '-y', is_flag=True,
              help='Skip confirmation prompt')
def reset(data_dir, yes):
    """
    Reset VelocityCMDB to fresh state

    ⚠️  WARNING: This will DELETE all databases and data!
    Use this to test the setup wizard from scratch.
    """
    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    # Check both data/ and discovery/ directories
    data_exists = data_path.exists() and any(data_path.iterdir())
    discovery_path = base_path / 'discovery'
    discovery_exists = discovery_path.exists() and any(discovery_path.iterdir())

    if not data_exists and not discovery_exists:
        click.echo("✓ Directories don't exist or are empty - already clean")
        click.echo(f"\nReady for fresh initialization:")
        click.echo("  velocitycmdb init")
        return

    # Show what will be deleted
    click.echo("⚠️  WARNING: This will DELETE ALL DATA!")
    click.echo(f"\nBase location: {base_path}")
    click.echo(f"Data location: {data_path}\n")
    click.echo("Files to be deleted:")

    items_to_delete = []

    # Check databases in data/
    for db_file in ['assets.db', 'arp_cat.db', 'users.db']:
        db_path = data_path / db_file
        if db_path.exists():
            size_mb = db_path.stat().st_size / 1024 / 1024
            click.echo(f"  • data/{db_file} ({size_mb:.1f} MB)")
            items_to_delete.append(db_path)

    # Check data directories in data/
    for data_subdir in ['fingerprints', 'capture', 'jobs', 'logs']:
        subdir_path = data_path / data_subdir
        if subdir_path.exists():
            file_count = sum(1 for _ in subdir_path.rglob('*') if _.is_file())
            if file_count > 0:
                click.echo(f"  • data/{data_subdir}/ ({file_count} files)")
                items_to_delete.append(subdir_path)

    # Check discovery directory (at base level, parallel to data/)
    if discovery_exists:
        file_count = sum(1 for _ in discovery_path.rglob('*') if _.is_file())
        if file_count > 0:
            click.echo(f"  • discovery/ ({file_count} files)")
            items_to_delete.append(discovery_path)

    if not items_to_delete:
        click.echo("  (no data found)")
        click.echo("\n✓ Already clean")
        return

    # Confirm (unless --yes flag)
    click.echo("")
    if not yes:
        click.echo("This action cannot be undone!")
        if not click.confirm('Are you SURE you want to delete all data?', default=False):
            click.echo("\n✓ Reset cancelled - data preserved")
            return

    # Delete everything
    click.echo("\nDeleting...")

    for item in items_to_delete:
        try:
            if item.is_file():
                item.unlink()
                click.echo(f"  ✓ Deleted {item.name}")
            elif item.is_dir():
                shutil.rmtree(item)
                click.echo(f"  ✓ Deleted {item.name}/")
        except Exception as e:
            click.echo(f"  ✗ Failed to delete {item.name}: {e}", err=True)

    click.echo("\n" + "=" * 60)
    click.echo("✓ Reset complete - ready for fresh initialization")
    click.echo("=" * 60)
    click.echo("\nNext steps:")
    click.echo("  velocitycmdb init       # Initialize databases")
    click.echo("  velocitycmdb start      # Start web interface")


@main.command()
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
def clean(data_dir):
    """
    Clean up temporary files (keeps databases)

    Removes fingerprints, captures, and discovery logs but preserves databases.
    Useful for recapturing without losing device/site data.
    """
    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    if not data_path.exists():
        click.echo("✓ No data directory found")
        return

    click.echo("Cleaning temporary files...")
    click.echo(f"Base location: {base_path}")
    click.echo(f"Data location: {data_path}\n")

    cleaned = []

    # Clean data directories (but not databases)
    for data_subdir in ['fingerprints', 'capture', 'jobs', 'logs']:
        subdir_path = data_path / data_subdir
        if subdir_path.exists():
            file_count = sum(1 for _ in subdir_path.rglob('*') if _.is_file())
            if file_count > 0:
                shutil.rmtree(subdir_path)
                click.echo(f"  ✓ Cleaned data/{data_subdir}/ ({file_count} files)")
                cleaned.append(f'data/{data_subdir}')

    # Clean discovery directory (at base level, parallel to data/)
    discovery_path = base_path / 'discovery'
    if discovery_path.exists():
        file_count = sum(1 for _ in discovery_path.rglob('*') if _.is_file())
        if file_count > 0:
            shutil.rmtree(discovery_path)
            click.echo(f"  ✓ Cleaned discovery/ ({file_count} files)")
            cleaned.append('discovery')

    if cleaned:
        click.echo(f"\n✓ Cleaned {len(cleaned)} directories")
        click.echo("\nDatabases preserved:")
        click.echo("  • data/assets.db")
        click.echo("  • data/arp_cat.db")
        click.echo("  • data/users.db")
    else:
        click.echo("✓ No temporary files to clean")


@main.command()
@click.option('--output', '-o', default='velocitycmdb-backup.tar.gz',
              help='Backup file path')
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
def backup(output, data_dir):
    """
    Create backup of all VelocityCMDB data

    Backs up databases, configurations, and captured data.
    """
    import tarfile
    from datetime import datetime

    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    if not data_path.exists():
        click.echo("✗ Data directory not found")
        click.echo("\nRun: velocitycmdb init")
        sys.exit(1)

    # Add timestamp to filename if not specified
    if output == 'velocitycmdb-backup.tar.gz':
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output = f'velocitycmdb-backup-{timestamp}.tar.gz'

    output_path = Path(output)

    click.echo(f"Creating backup: {output_path}")
    click.echo(f"Source: {base_path}\n")

    try:
        with tarfile.open(output_path, 'w:gz') as tar:
            # Add data directory
            tar.add(data_path, arcname='data')

            # Add discovery directory if it exists
            discovery_path = base_path / 'discovery'
            if discovery_path.exists():
                tar.add(discovery_path, arcname='discovery')

        size_mb = output_path.stat().st_size / 1024 / 1024
        click.echo(f"\n✓ Backup created: {output_path} ({size_mb:.1f} MB)")

    except Exception as e:
        click.echo(f"\n✗ Backup failed: {str(e)}", err=True)
        sys.exit(1)


@main.command()
@click.argument('backup_file', type=click.Path(exists=True))
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
@click.option('--yes', '-y', is_flag=True,
              help='Skip confirmation prompt')
def restore(backup_file, data_dir, yes):
    """
    Restore VelocityCMDB from backup

    ⚠️  WARNING: This will overwrite existing data!
    """
    import tarfile

    base_path = Path(data_dir)
    data_path = find_data_path(base_path)
    backup_path = Path(backup_file)

    click.echo(f"Restore from: {backup_path}")
    click.echo(f"Target: {base_path}\n")

    if data_path.exists():
        click.echo("⚠️  WARNING: This will OVERWRITE existing data!")
        if not yes:
            if not click.confirm('Continue with restore?', default=False):
                click.echo("\n✓ Restore cancelled")
                return

    click.echo("\nRestoring...")

    try:
        # Extract backup
        with tarfile.open(backup_path, 'r:gz') as tar:
            # Extract to base directory (tar contains 'data/' and 'discovery/' prefixes)
            tar.extractall(path=base_path)

        click.echo("\n✓ Restore complete!")
        click.echo(f"\nData restored to: {base_path}")

    except Exception as e:
        click.echo(f"\n✗ Restore failed: {str(e)}", err=True)
        sys.exit(1)


@main.command()
def version():
    """Show VelocityCMDB version"""
    click.echo("VelocityCMDB version 0.9.0")
    click.echo("https://github.com/scottpeterman/velocitycmdb")


@main.command()
@click.option('--data-dir', default=str(DEFAULT_DATA_DIR),
              help='Data directory path')
@click.option('--lines', '-n', default=50, help='Number of lines to show')
def logs(data_dir, lines):
    """Show recent log entries"""
    base_path = Path(data_dir)
    data_path = find_data_path(base_path)

    # Check multiple possible log locations
    log_paths = [
        data_path / 'logs' / 'velocitycmdb.log',
        base_path / 'logs' / 'velocitycmdb.log',
        base_path / 'log' / 'velocitycmdb.log',
    ]

    log_file = None
    for path in log_paths:
        if path.exists():
            log_file = path
            break

    if not log_file:
        click.echo("No log file found")
        click.echo("\nSearched locations:")
        for path in log_paths:
            click.echo(f"  • {path}")
        return

    click.echo(f"Recent logs from: {log_file}")
    click.echo(f"(last {lines} lines)\n")
    click.echo("=" * 60)

    # Show last N lines
    try:
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            for line in all_lines[-lines:]:
                click.echo(line.rstrip())
    except Exception as e:
        click.echo(f"Error reading logs: {e}", err=True)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()