#!/usr/bin/env python3
"""
Convert inventory spreadsheet to Anguis format
Creates both sessions.yaml and pre-populated fingerprint files
"""

import csv
import json
import yaml
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict
import argparse
from datetime import datetime

# Vendor detection mapping
VENDOR_MAPPING = {
    'IOS': 'Cisco',
    'NX-OS': 'Cisco',
    'IOS-XE': 'Cisco',
    'IOS-XR': 'Cisco',
    'EOS': 'Arista',
    'AOS': 'Aruba',
    'ArubaOS': 'Aruba',
    'JunOS': 'Juniper',
    'JUNOS': 'Juniper',
    'Comware': 'HPE',
    'ProVision': 'HPE',
}

# Platform detection for sessions.yaml
PLATFORM_MAPPING = {
    'IOS': 'cisco_ios',
    'NX-OS': 'cisco_nxos',
    'IOS-XE': 'cisco_xe',
    'IOS-XR': 'cisco_xr',
    'EOS': 'arista_eos',
    'AOS': 'aruba_aos',
    'ArubaOS': 'aruba_arubaos',
    'JunOS': 'juniper_junos',
    'JUNOS': 'juniper_junos',
    'Comware': 'hp_comware',
    'ProVision': 'hp_procurve',
}


def detect_vendor(os_type: str, model: str = '') -> str:
    """Detect vendor from OS type or model"""
    # Check OS mapping first
    for os_key, vendor in VENDOR_MAPPING.items():
        if os_key.lower() in os_type.lower():
            return vendor

    # Fallback to model detection
    if model:
        model_lower = model.lower()
        if 'ws-' in model_lower or 'cat' in model_lower or 'nexus' in model_lower:
            return 'Cisco'
        elif 'dcs-' in model_lower:
            return 'Arista'
        elif 'aruba' in model_lower or 'hp' in model_lower:
            return 'Aruba'
        elif 'ex' in model_lower or 'mx' in model_lower or 'srx' in model_lower:
            return 'Juniper'

    return 'Unknown'


def detect_platform(os_type: str) -> str:
    """Detect NAPALM platform from OS type"""
    for os_key, platform in PLATFORM_MAPPING.items():
        if os_key.lower() in os_type.lower():
            return platform
    return 'cisco_ios'  # Safe default


def extract_site_from_hostname(hostname: str) -> str:
    """
    Extract site identifier from hostname
    Examples:
        agg5-01.iad1 -> iad1
        c103a.iad2 -> iad2
        sw-core.nyc3 -> nyc3
    """
    # Try extracting after last dot
    if '.' in hostname:
        site = hostname.split('.')[-1]
        # Check if it looks like a site code (2-4 chars/digits)
        if len(site) >= 2 and len(site) <= 6:
            return site.upper()

    # Fallback: try extracting from hostname pattern
    parts = hostname.replace('.', '-').split('-')
    for part in reversed(parts):
        if len(part) >= 2 and len(part) <= 6:
            return part.upper()

    return 'UNKNOWN'


def parse_csv_inventory(csv_file: Path) -> List[Dict]:
    """Parse CSV inventory file"""
    devices = []

    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)

        for row in reader:
            device = {
                'hostname': row.get('Hostname', '').strip(),
                'ip': row.get('IP', '').strip(),
                'model': row.get('Model', '').strip(),
                'os': row.get('OS', '').strip(),
                'version': row.get('Version', '').strip(),
                'serial': row.get('Serial', '').strip(),
                'status': row.get('Status', '').strip(),
                'last_update': row.get('Last Update', '').strip(),
            }

            # Skip empty rows
            if not device['hostname'] or not device['ip']:
                continue

            # Add derived fields
            device['vendor'] = detect_vendor(device['os'], device['model'])
            device['platform'] = detect_platform(device['os'])
            device['site'] = extract_site_from_hostname(device['hostname'])

            devices.append(device)

    print(f"Loaded {len(devices)} devices from {csv_file}")
    return devices


def create_sessions_yaml(devices: List[Dict], output_file: Path,
                         credential_id: int = 1, use_fqdn: bool = True) -> None:
    """Create sessions.yaml file for Anguis with full device metadata"""

    # Group devices by site
    sites = defaultdict(list)
    for device in devices:
        sites[device['site']].append(device)

    # Build sessions structure
    sessions_data = []
    for site, site_devices in sorted(sites.items()):
        folder = {
            'folder_name': site,
            'sessions': []
        }

        for device in sorted(site_devices, key=lambda x: x['hostname']):
            # Build rich session entry
            session = {
                'display_name': device['hostname'],
                'host': device['hostname'] if use_fqdn else device['ip'],
                'port': '22',
                'DeviceType': device['platform'].replace('_ssh', ''),  # e.g., arista_eos, cisco_ios
                'Vendor': device['vendor'],
                'Model': device['model'],
                'SerialNumber': device['serial'],
                'SoftwareVersion': device['version'],
                'credsid': str(credential_id)
            }

            folder['sessions'].append(session)

        sessions_data.append(folder)

    # Write YAML file
    with open(output_file, 'w') as f:
        yaml.dump(sessions_data, f, default_flow_style=False, sort_keys=False)

    total_devices = sum(len(f['sessions']) for f in sessions_data)
    print(f"\n✓ Created {output_file}")
    print(f"  {total_devices} devices across {len(sessions_data)} sites")

    # Print site summary
    print(f"\n  Site Distribution:")
    for folder in sessions_data:
        site = folder['folder_name']
        count = len(folder['sessions'])
        print(f"    {site:20s} {count:3d} devices")


def create_fingerprint_files(devices: List[Dict], output_dir: Path) -> None:
    """Create fingerprint JSON files for each device"""

    output_dir.mkdir(parents=True, exist_ok=True)

    successful = 0
    failed = 0

    for device in devices:
        # Skip devices that failed discovery
        if device['status'].lower() != 'success':
            failed += 1
            continue

        # Create fingerprint data matching db_load_fingerprints.py expected format
        # The loader looks for additional_info.vendor and additional_info.netmiko_driver
        fingerprint = {
            'success': True,  # Critical: marks fingerprint as valid
            'hostname': device['hostname'],
            'detected_prompt': f"{device['hostname']}#",  # Include prompt for fallback parsing
            'host': device['ip'],
            'model': device['model'],
            'version': device['version'],
            'serial_number': device['serial'],
            'fingerprint_time': device['last_update'],
            'command_outputs': {},  # Empty dict for compatibility
            'additional_info': {
                'vendor': device['vendor'].lower(),  # Loader uses this for vendor mapping
                'netmiko_driver': device['platform']  # Loader uses this for device_type mapping
            }
        }

        # Write fingerprint file
        output_file = output_dir / f"{device['hostname']}.json"
        try:
            with open(output_file, 'w') as f:
                json.dump(fingerprint, f, indent=2)
            successful += 1
        except Exception as e:
            print(f"  ✗ Failed to create {output_file}: {e}")
            failed += 1

    print(f"\n✓ Created fingerprint files in {output_dir}")
    print(f"  Successful: {successful}")
    if failed > 0:
        print(f"  Failed/Skipped: {failed}")


def create_vendor_summary(devices: List[Dict], output_file: Path) -> None:
    """Create vendor distribution summary"""

    vendor_counts = defaultdict(int)
    os_counts = defaultdict(int)
    site_counts = defaultdict(lambda: defaultdict(int))

    for device in devices:
        vendor_counts[device['vendor']] += 1
        os_counts[device['os']] += 1
        site_counts[device['site']][device['vendor']] += 1

    with open(output_file, 'w') as f:
        f.write("Anguis Import Summary\n")
        f.write("=" * 70 + "\n\n")

        # Overall stats
        f.write(f"Total Devices: {len(devices)}\n")
        f.write(f"Total Sites: {len(site_counts)}\n\n")

        # Vendor distribution
        f.write("Vendor Distribution:\n")
        f.write("-" * 70 + "\n")
        for vendor, count in sorted(vendor_counts.items(), key=lambda x: -x[1]):
            pct = count / len(devices) * 100
            f.write(f"  {vendor:20s} {count:4d} devices ({pct:5.1f}%)\n")

        f.write("\n")

        # OS distribution
        f.write("Operating Systems:\n")
        f.write("-" * 70 + "\n")
        for os, count in sorted(os_counts.items(), key=lambda x: -x[1]):
            pct = count / len(devices) * 100
            f.write(f"  {os:20s} {count:4d} devices ({pct:5.1f}%)\n")

        f.write("\n")

        # Site breakdown
        f.write("Site Distribution:\n")
        f.write("-" * 70 + "\n")
        for site in sorted(site_counts.keys()):
            site_total = sum(site_counts[site].values())
            f.write(f"\n{site} ({site_total} devices):\n")
            for vendor, count in sorted(site_counts[site].items(), key=lambda x: -x[1]):
                f.write(f"  {vendor:20s} {count:4d}\n")

    print(f"\n✓ Created summary report: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert inventory spreadsheet to Anguis format"
    )
    parser.add_argument(
        'csv_file',
        help='Input CSV file (Hostname,IP,Model,OS,Version,Serial,Status,Last Update)'
    )
    parser.add_argument(
        '--output-dir',
        default='Anguis',
        help='Output directory for Anguis files (default: Anguis)'
    )
    parser.add_argument(
        '--credential-id',
        type=int,
        default=1,
        help='Credential ID to use in sessions.yaml (default: 1)'
    )
    parser.add_argument(
        '--sessions-file',
        default='sessions.yaml',
        help='Output sessions file name (default: sessions.yaml)'
    )
    parser.add_argument(
        '--use-fqdn',
        action='store_true',
        help='Use FQDN as host instead of IP address'
    )
    parser.add_argument(
        '--domain-suffix',
        default='',
        help='Domain suffix to append to hostnames for FQDN (e.g., company.com)'
    )

    args = parser.parse_args()

    # Validate input
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    # Setup output directories
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fingerprints_dir = output_dir / 'fingerprints'

    print("=" * 70)
    print("Anguis Import Tool - Spreadsheet Converter")
    print("=" * 70)
    print(f"\nInput CSV: {csv_path}")
    print(f"Output Directory: {output_dir}")
    print(f"Fingerprints Directory: {fingerprints_dir}")

    # Parse CSV
    print(f"\n{'=' * 70}")
    print("Step 1: Parsing CSV inventory...")
    print("=" * 70)
    devices = parse_csv_inventory(csv_path)

    if not devices:
        print("Error: No valid devices found in CSV")
        sys.exit(1)

    # Apply domain suffix if provided
    if args.domain_suffix:
        print(f"Applying domain suffix: {args.domain_suffix}")
        for device in devices:
            if not '.' in device['hostname'] or not device['hostname'].endswith(args.domain_suffix):
                device['hostname'] = f"{device['hostname']}.{args.domain_suffix}"

    # Create sessions.yaml
    print(f"\n{'=' * 70}")
    print("Step 2: Creating sessions.yaml...")
    print("=" * 70)
    sessions_file = output_dir / args.sessions_file
    create_sessions_yaml(devices, sessions_file, args.credential_id, args.use_fqdn)

    # Create fingerprint files
    print(f"\n{'=' * 70}")
    print("Step 3: Creating fingerprint files...")
    print("=" * 70)
    create_fingerprint_files(devices, fingerprints_dir)

    # Create summary report
    print(f"\n{'=' * 70}")
    print("Step 4: Generating summary report...")
    print("=" * 70)
    summary_file = output_dir / 'import_summary.txt'
    create_vendor_summary(devices, summary_file)

    # Final instructions
    print(f"\n{'=' * 70}")
    print("Import Complete!")
    print("=" * 70)
    print(f"\nGenerated Files:")
    print(f"  1. {sessions_file} - Device inventory for Anguis")
    print(
        f"  2. {fingerprints_dir}/*.json - Pre-populated fingerprints ({len(list(fingerprints_dir.glob('*.json')))} files)")
    print(f"  3. {summary_file} - Import statistics")

    print(f"\nNext Steps:")
    print(f"  1. Set credentials:")
    print(f"     $env:CRED_{args.credential_id}_USER = \"admin\"")
    print(f"     $env:CRED_{args.credential_id}_PASS = \"your-password\"")
    print(f"")
    print(f"  2. Skip to configuration capture (fingerprinting already done!):")
    print(f"     python Anguis\\generate_capture_jobs.py --output-dir Anguis\\gnet_jobs")
    print(
        f"     python Anguis\\run_jobs_concurrent_batch.py Anguis\\gnet_jobs\\job_batch_configs.txt --max-processes 8")
    print(f"")
    print(f"  3. Load into web dashboard:")
    print(f"     python Anguis\\db_load_fingerprints.py --fingerprints-dir {fingerprints_dir}")
    print(f"     cd app && python run.py")


if __name__ == '__main__':
    main()