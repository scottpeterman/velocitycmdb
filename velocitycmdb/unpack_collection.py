#!/usr/bin/env python3
"""
Unpack device collection outputs into organized capture directory structure.
Copies text files from device_collection_* directories into pcng/capture subdirectories.
"""

import os
import sys
import shutil
from pathlib import Path
import json

# Mapping of collection output files to capture subdirectories
FILE_MAPPING = {
    'version.txt': 'version',
    'config.txt': 'configs',
    'lldp.txt': 'lldp',
    'lldp_detail.txt': 'lldp-detail'
}


def find_collection_dir(search_path='.'):
    """Find the most recent device_collection_* directory."""
    collection_dirs = []
    for item in Path(search_path).iterdir():
        if item.is_dir() and item.name.startswith('device_collection_'):
            collection_dirs.append(item)

    if not collection_dirs:
        return None

    # Sort by name (timestamp in name) and return most recent
    collection_dirs.sort(reverse=True)
    return collection_dirs[0]


def create_capture_structure(base_path):
    """Create the capture directory structure if it doesn't exist."""
    capture_dirs = [
        'version', 'configs', 'lldp', 'lldp-detail',
        'bgp-neighbor', 'bgp-summary', 'bgp-table', 'bgp-table-detail',
        'int-status', 'interface-status', 'inventory',
        'arp', 'mac', 'routes', 'ospf-neighbor', 'port-channel',
        'vrf', 'ntp_status', 'authentication', 'authorization',
        'ip_ssh', 'snmp_server', 'syslog', 'radius', 'tacacs',
        'console', 'configs_old', 'test_capture', 'test_password_auth'
    ]

    base = Path(base_path)
    base.mkdir(parents=True, exist_ok=True)

    for dir_name in capture_dirs:
        (base / dir_name).mkdir(exist_ok=True)

    return base


def strip_kentik_domain(hostname):
    """Remove home.com from hostname if present."""
    if hostname.endswith('home.com'):
        return hostname[:-11]  # Remove 'home.com'
    return hostname


def unpack_collection(collection_dir, capture_base, verbose=False):
    """Unpack collection outputs into capture directory structure."""
    collection_path = Path(collection_dir)

    if not collection_path.exists():
        print(f"Error: Collection directory not found: {collection_dir}")
        return False

    # Read summary to get device list
    summary_file = collection_path / 'collection_summary.json'
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        device_count = summary.get('total_devices', 0)
        print(f"Found collection with {device_count} devices")

    # Process each device directory
    copied_files = 0
    failed_files = 0

    for device_dir in collection_path.iterdir():
        if not device_dir.is_dir():
            continue

        hostname = device_dir.name
        clean_hostname = strip_kentik_domain(hostname)

        if verbose:
            print(f"\nProcessing {hostname} -> {clean_hostname}")

        # Copy each output file to appropriate capture directory
        for source_file, dest_subdir in FILE_MAPPING.items():
            source_path = device_dir / source_file

            if not source_path.exists():
                if verbose:
                    print(f"  [SKIP] {source_file} not found")
                continue

            # Check if file has actual content (not just errors)
            content = source_path.read_text()
            if content.startswith('ERROR:'):
                if verbose:
                    print(f"  [SKIP] {source_file} contains error")
                failed_files += 1
                continue

            # Create destination path
            dest_dir = Path(capture_base) / dest_subdir
            dest_file = dest_dir / f"{clean_hostname}.txt"

            # Copy file
            try:
                shutil.copy2(source_path, dest_file)
                if verbose:
                    print(f"  [COPY] {source_file} -> {dest_subdir}/{clean_hostname}.txt")
                copied_files += 1
            except Exception as e:
                print(f"  [ERROR] Failed to copy {source_file}: {e}")
                failed_files += 1

    return copied_files, failed_files


def main():
    """Main execution function."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Unpack device collection outputs into capture directory structure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Auto-find latest collection, use default pcng/capture
  python unpack_collection.py

  # Specify collection directory
  python unpack_collection.py -c device_collection_20241104_153045

  # Specify capture base directory
  python unpack_collection.py -o /path/to/pcng/capture

  # Verbose mode
  python unpack_collection.py -v

  # All options
  python unpack_collection.py -c device_collection_20241104_153045 -o pcng/capture -v
        '''
    )

    parser.add_argument('-c', '--collection',
                        help='Collection directory (default: auto-find latest device_collection_*)')
    parser.add_argument('-o', '--output', default='pcng/capture',
                        help='Base capture directory (default: pcng/capture)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')

    args = parser.parse_args()

    # Find collection directory
    if args.collection:
        collection_dir = args.collection
    else:
        print("Searching for collection directory...")
        collection_dir = find_collection_dir()
        if not collection_dir:
            print("Error: No device_collection_* directory found in current directory")
            print("Use -c to specify collection directory")
            sys.exit(1)
        print(f"Found: {collection_dir}")

    # Create capture structure
    print(f"\nCreating capture directory structure: {args.output}")
    capture_base = create_capture_structure(args.output)

    # Unpack collection
    print(f"\nUnpacking collection from: {collection_dir}")
    print(f"Output destination: {capture_base}\n")

    copied, failed = unpack_collection(collection_dir, capture_base, args.verbose)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Unpacking complete!")
    print(f"Files copied: {copied}")
    print(f"Files failed/skipped: {failed}")
    print(f"Output location: {capture_base.absolute()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()