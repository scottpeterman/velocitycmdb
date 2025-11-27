#!/usr/bin/env python3
"""
CLI tool for fingerprinting devices from sessions.yaml inventory
Can be used standalone without running discovery first

Supports:
  - Batch mode: fingerprint all devices from sessions.yaml
  - Single device mode: fingerprint one device by IP/hostname
"""

import argparse
import sys
import logging
import os
import json
from pathlib import Path
from datetime import datetime
import yaml


def setup_logging(verbose=False, debug=False):
    """Configure logging"""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


def validate_sessions_file(sessions_file):
    """Validate sessions.yaml file exists and has valid structure"""
    if not sessions_file.exists():
        raise FileNotFoundError(f"Sessions file not found: {sessions_file}")

    try:
        with open(sessions_file, 'r') as f:
            data = yaml.safe_load(f)

        site_count = 0
        device_count = 0

        # Handle two formats:
        # Format 1 (dict): {site_name: {sessions: [...]}, ...}
        # Format 2 (list): [{folder_name: site_name, sessions: [...]}, ...]

        if isinstance(data, dict):
            # Dictionary format
            for site_name, site_data in data.items():
                if isinstance(site_data, dict) and 'sessions' in site_data:
                    site_count += 1
                    device_count += len(site_data['sessions'])

        elif isinstance(data, list):
            # List format with folder_name
            for item in data:
                if isinstance(item, dict) and 'folder_name' in item and 'sessions' in item:
                    site_count += 1
                    device_count += len(item['sessions'])
        else:
            raise ValueError("Sessions file must contain a dictionary or list")

        if device_count == 0:
            raise ValueError("No devices found in sessions file")

        return site_count, device_count

    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in sessions file: {e}")


def normalize_sessions_file(sessions_file, output_file):
    """
    Normalize sessions file to dictionary format if needed
    Returns path to normalized file (or original if already in correct format)
    """
    with open(sessions_file, 'r') as f:
        data = yaml.safe_load(f)

    # If already a dict, just return original file
    if isinstance(data, dict):
        return sessions_file

    # Convert list format to dict format
    if isinstance(data, list):
        normalized = {}
        for item in data:
            if isinstance(item, dict) and 'folder_name' in item and 'sessions' in item:
                site_name = item['folder_name']
                normalized[site_name] = {
                    'sessions': item['sessions']
                }

        # Write normalized version
        with open(output_file, 'w') as f:
            yaml.dump(normalized, f, default_flow_style=False, sort_keys=False)

        return output_file

    return sessions_file


def progress_callback(data):
    """Simple console progress callback"""
    stage = data.get('stage', 'unknown')
    message = data.get('message', '')

    if stage == 'device':
        device = data.get('device', 'unknown')
        current = data.get('current', 0)
        total = data.get('total', 0)
        print(f"[{current}/{total}] Fingerprinting: {device}")
    elif stage == 'complete':
        print(f"\n✓ {message}")
    elif stage == 'error':
        print(f"\n✗ Error: {message}")
    else:
        print(f"  {message}")


def fingerprint_single_device(args, logger):
    """
    Fingerprint a single device by IP/hostname

    Returns:
        0 on success, 1 on failure
    """
    from velocitycmdb.pcng.device_fingerprint import DeviceFingerprint

    host = args.host
    port = args.port or 22
    display_name = args.display_name or host

    print(f"\n{'=' * 60}")
    print(f"SINGLE DEVICE FINGERPRINT")
    print(f"{'=' * 60}")
    print(f"Host: {host}:{port}")
    print(f"Display Name: {display_name}")
    print(f"Username: {args.username}")
    print(f"Auth: {'SSH Key' if args.ssh_key else 'Password'}")
    print(f"{'=' * 60}\n")

    # Find TextFSM database - user specified or search common paths
    textfsm_db = None

    if args.textfsm_db:
        # User specified path
        if args.textfsm_db.exists():
            textfsm_db = str(args.textfsm_db.expanduser().absolute())
            logger.info(f"Using specified TextFSM database: {textfsm_db}")
        else:
            print(f"Warning: Specified TextFSM database not found: {args.textfsm_db}")

    if not textfsm_db:
        # Search common paths
        possible_paths = [
            Path.cwd() / 'tfsm_templates.db',
            Path.cwd() / 'pcng' / 'tfsm_templates.db',
            Path(__file__).parent / 'pcng' / 'tfsm_templates.db',
            Path(__file__).parent / 'tfsm_templates.db',
        ]
        for path in possible_paths:
            if path.exists():
                textfsm_db = str(path)
                logger.info(f"Found TextFSM database: {textfsm_db}")
                break

    if not textfsm_db:
        print("Warning: No TextFSM database found - parsing will use regex fallback")
        print("  Specify with: --textfsm-db /path/to/tfsm_templates.db")

    try:
        # Create fingerprinter
        fingerprinter = DeviceFingerprint(
            host=host,
            port=port,
            username=args.username,
            password=args.password,
            ssh_key_path=str(args.ssh_key.expanduser()) if args.ssh_key else None,
            debug=args.debug,
            verbose=args.verbose,
            connection_timeout=10000,
            textfsm_db_path=textfsm_db
        )

        # Store yaml_display_name before fingerprinting
        fingerprinter._device_info.additional_info['yaml_display_name'] = display_name

        print(f"Connecting to {host}...")
        start_time = datetime.now()

        # Run fingerprinting
        device_info = fingerprinter.fingerprint()

        elapsed = (datetime.now() - start_time).total_seconds()

        # Build result dict
        result = {
            'host': device_info.host,
            'port': device_info.port,
            'device_type': device_info.device_type.value if hasattr(device_info.device_type,
                                                                    'value') else device_info.device_type,
            'detected_prompt': device_info.detected_prompt,
            'disable_paging_command': device_info.disable_paging_command,
            'hostname': device_info.hostname,
            'model': device_info.model,
            'version': device_info.version,
            'serial_number': device_info.serial_number,
            'is_virtual_device': device_info.is_virtual_device,
            'platform': device_info.platform,
            'uptime': device_info.uptime,
            'additional_info': device_info.additional_info,
            'interfaces': device_info.interfaces,
            'ip_addresses': device_info.ip_addresses,
            'cpu_info': device_info.cpu_info,
            'memory_info': device_info.memory_info,
            'storage_info': device_info.storage_info,
            'command_outputs': device_info.command_outputs,
            'fingerprint_time': datetime.now().isoformat(),
            'success': True
        }

        # ================================================================
        # Save raw command outputs for template debugging
        # ================================================================
        if args.debug_dir:
            debug_dir = args.debug_dir.expanduser().absolute()
            debug_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize display name for filenames
            safe_name = display_name.replace('/', '_').replace('\\', '_').replace(':', '_')

            print(f"\nSaving debug outputs to: {debug_dir}")

            # Save each command output
            for cmd, output in device_info.command_outputs.items():
                # Create safe filename from command
                safe_cmd = cmd.replace(' ', '_').replace('|', '_').replace('/', '_')
                safe_cmd = safe_cmd.replace('>', '_').replace('<', '_')
                filename = f"{safe_name}_{safe_cmd}.txt"
                filepath = debug_dir / filename

                with open(filepath, 'w') as f:
                    f.write(f"# Device: {display_name}\n")
                    f.write(f"# Host: {host}\n")
                    f.write(f"# Command: {cmd}\n")
                    f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
                    f.write(f"# Output length: {len(output)} bytes\n")
                    f.write("#" + "=" * 60 + "\n\n")
                    f.write(output)

                print(f"  Saved: {filename} ({len(output)} bytes)")

            # Also save a summary JSON with all metadata
            summary_file = debug_dir / f"{safe_name}_summary.json"
            summary = {
                'device': display_name,
                'host': host,
                'port': port,
                'vendor': device_info.additional_info.get('vendor', 'Unknown'),
                'model': device_info.model,
                'version': device_info.version,
                'device_type': str(device_info.device_type),
                'detected_prompt': device_info.detected_prompt,
                'commands_captured': list(device_info.command_outputs.keys()),
                'timestamp': datetime.now().isoformat()
            }
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
            print(f"  Saved: {summary_file.name}")
        # ================================================================

        # Print results
        print(f"\n{'=' * 60}")
        print("FINGERPRINT RESULTS")
        print(f"{'=' * 60}")
        print(f"Duration: {elapsed:.1f} seconds")
        print(f"")
        print(f"Hostname (detected):    {device_info.hostname or '(none)'}")
        print(f"Display Name (YAML):    {device_info.additional_info.get('yaml_display_name', '(none)')}")
        print(f"Display Name (final):   {device_info.additional_info.get('display_name', '(none)')}")
        print(f"")
        print(f"Vendor:                 {device_info.additional_info.get('vendor', 'Unknown')}")
        print(f"Model:                  {device_info.model or 'Unknown'}")
        print(f"Version:                {device_info.version or 'Unknown'}")
        print(f"Serial Number:          {device_info.serial_number or 'Unknown'}")
        print(f"")
        print(f"Device Type:            {device_info.device_type}")
        print(f"Netmiko Driver:         {device_info.additional_info.get('netmiko_driver', 'Unknown')}")
        print(f"Detected Prompt:        {device_info.detected_prompt or '(none)'}")
        print(f"{'=' * 60}")

        # Save to file if data directory specified
        if args.data_dir:
            data_dir = args.data_dir
            data_dir.mkdir(parents=True, exist_ok=True)
            fingerprints_dir = data_dir / 'fingerprints'
            fingerprints_dir.mkdir(parents=True, exist_ok=True)

            # Use display_name for filename, sanitize it
            safe_name = display_name.replace('/', '_').replace('\\', '_').replace(':', '_')
            output_file = fingerprints_dir / f'{safe_name}.json'

            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2, default=str)

            print(f"\nFingerprint saved to: {output_file}")

            # Optionally load into database
            if args.load_db:
                try:
                    from db_load_fingerprints import FingerprintLoader
                    db_path = data_dir / 'assets.db'
                    loader = FingerprintLoader(str(db_path))

                    if loader.load_fingerprint_file(output_file):
                        print(f"Loaded into database: {db_path}")
                    else:
                        print(f"Failed to load into database")
                except ImportError:
                    print("Warning: db_load_fingerprints not available, skipping database load")
                except Exception as e:
                    print(f"Database load error: {e}")

        # Print raw JSON if requested
        if args.json:
            print(f"\n{'=' * 60}")
            print("RAW JSON OUTPUT")
            print(f"{'=' * 60}")
            # Remove command_outputs for cleaner display (it's huge)
            display_result = {k: v for k, v in result.items() if k != 'command_outputs'}
            print(json.dumps(display_result, indent=2, default=str))

        return 0

    except Exception as e:
        print(f"\n✗ Fingerprinting failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


def fingerprint_batch(args, logger):
    """
    Fingerprint all devices from sessions.yaml

    Returns:
        0 on success, 1 on failure
    """
    # Validate sessions file
    logger.info(f"Validating sessions file: {args.sessions_file}")
    site_count, device_count = validate_sessions_file(args.sessions_file)
    logger.info(f"Found {device_count} devices across {site_count} sites")

    if args.validate_only:
        print(f"\n✓ Sessions file is valid:")
        print(f"  Sites: {site_count}")
        print(f"  Devices: {device_count}")
        return 0

    # Check authentication
    if not args.username:
        print("Error: --username is required for fingerprinting")
        return 1

    if not args.password and not args.ssh_key:
        print("Error: Either --password or --ssh-key must be provided")
        return 1

    # Set data directory
    data_dir = args.data_dir or Path.cwd() / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Data directory: {data_dir}")

    # Import here to avoid import errors if just validating
    from velocitycmdb.services.fingerprint import FingerprintOrchestrator

    # Set environment variables for SSH client authentication
    if args.ssh_key:
        os.environ['PYSSH_KEY'] = str(args.ssh_key.expanduser().absolute())
        logger.info(f"Set PYSSH_KEY environment variable: {os.environ['PYSSH_KEY']}")
    elif args.password:
        os.environ['PYSSH_PASS'] = args.password
        logger.info("Set PYSSH_PASS environment variable")

    # Create orchestrator
    logger.info("Initializing fingerprint orchestrator")
    orchestrator = FingerprintOrchestrator(data_dir=data_dir)

    # Start fingerprinting
    logger.info(f"Starting fingerprint process...")
    print(f"\nFingerprinting {device_count} devices...\n")

    start_time = datetime.now()

    result = orchestrator.fingerprint_inventory(
        sessions_file=args.sessions_file,
        username=args.username,
        password=args.password,
        ssh_key_path=args.ssh_key,
        progress_callback=progress_callback
    )

    elapsed = (datetime.now() - start_time).total_seconds()

    # Print results
    print("\n" + "=" * 60)
    print("FINGERPRINTING RESULTS")
    print("=" * 60)
    print(f"Duration: {elapsed:.1f} seconds")
    print(f"Fingerprinted: {result['fingerprinted']}")
    print(f"Failed: {result['failed']}")

    if result['failed'] > 0:
        print(f"\nFailed devices:")
        for device in result['failed_devices']:
            print(f"  - {device}")

    print(f"\nDatabase:")
    print(f"  Loaded: {result['loaded_to_db']}")
    print(f"  Failed: {result['db_load_failed']}")
    print(f"  Path: {result['db_path']}")

    print(f"\nFingerprints directory: {result['fingerprints_dir']}")
    print("=" * 60)

    # Return exit code based on success
    if result['success']:
        logger.info("Fingerprinting completed successfully")
        return 0
    else:
        logger.error("Fingerprinting completed with errors")
        return 1


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Fingerprint network devices from sessions.yaml inventory or single device',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Batch fingerprinting from sessions.yaml
  %(prog)s -s sessions.yaml -u admin -p password -d /data/velocitycmdb

  # Using SSH key authentication
  %(prog)s -s sessions.yaml -u admin -k ~/.ssh/id_rsa -d /data/velocitycmdb

  # Single device fingerprinting
  %(prog)s --host 192.168.1.1 --display-name core-rtr-01 -u admin -k ~/.ssh/id_rsa

  # Single device with specific TextFSM database
  %(prog)s --host 192.168.1.1 -u admin -k ~/.ssh/id_rsa --textfsm-db ~/templates/tfsm_templates.db

  # Single device with debug output and JSON
  %(prog)s --host 192.168.1.1 -u admin -p password --debug --json

  # Save raw command outputs for template debugging
  %(prog)s --host 192.168.1.1 -u admin -k ~/.ssh/id_rsa --debug-dir ./debug_outputs

  # Single device, save to file and load into database
  %(prog)s --host 192.168.1.1 --display-name edge1-01.fra1 -u admin -k ~/.ssh/id_rsa -d ~/.velocitycmdb/data --load-db

  # Validate sessions file only
  %(prog)s -s sessions.yaml --validate-only

  # Verbose batch output
  %(prog)s -s sessions.yaml -u admin -p password -d /data -v
        """
    )

    # Mode selection - batch vs single
    mode_group = parser.add_argument_group('mode selection (choose one)')
    mode_group.add_argument('-s', '--sessions-file',
                            type=Path,
                            help='Path to sessions.yaml inventory file (batch mode)')

    mode_group.add_argument('--host',
                            help='Single device IP or hostname (single device mode)')

    # Single device options
    single_group = parser.add_argument_group('single device options')
    single_group.add_argument('--display-name',
                              help='Display name for single device (defaults to host)')

    single_group.add_argument('--port',
                              type=int,
                              default=22,
                              help='SSH port (default: 22)')

    single_group.add_argument('--json',
                              action='store_true',
                              help='Print raw JSON output for single device')

    single_group.add_argument('--load-db',
                              action='store_true',
                              help='Load fingerprint into database (requires -d)')

    single_group.add_argument('--textfsm-db',
                              type=Path,
                              help='Path to TextFSM templates database (tfsm_templates.db)')

    single_group.add_argument('--debug-dir',
                              type=Path,
                              help='Directory to save raw command outputs for template debugging')

    # Common options
    parser.add_argument('-d', '--data-dir',
                        type=Path,
                        help='Data directory for fingerprints and database (default: ./data)')

    # Authentication arguments
    auth_group = parser.add_argument_group('authentication')
    auth_group.add_argument('-u', '--username',
                            help='SSH username')

    auth_group.add_argument('-p', '--password',
                            help='SSH password')

    auth_group.add_argument('-k', '--ssh-key',
                            type=Path,
                            help='Path to SSH private key (alternative to password)')

    # Output options
    output_group = parser.add_argument_group('output options')
    output_group.add_argument('-v', '--verbose',
                              action='store_true',
                              help='Enable verbose logging')

    output_group.add_argument('--debug',
                              action='store_true',
                              help='Enable debug logging (very verbose)')

    output_group.add_argument('--validate-only',
                              action='store_true',
                              help='Only validate sessions file, do not fingerprint')

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.verbose, args.debug)

    try:
        # Determine mode
        if args.host:
            # Single device mode
            if not args.username:
                parser.error("--username is required for fingerprinting")
            if not args.password and not args.ssh_key:
                parser.error("Either --password or --ssh-key must be provided")

            return fingerprint_single_device(args, logger)

        elif args.sessions_file:
            # Batch mode
            return fingerprint_batch(args, logger)

        else:
            parser.error("Either --sessions-file or --host must be provided")
            return 1

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130

    except Exception as e:
        logger.exception("Fingerprinting failed")
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())