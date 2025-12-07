#!/usr/bin/env python3
"""
generate_capture_jobs.py
Generate vendor-specific job files for network capture automation
"""

import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path


def get_configured_username() -> str:
    """
    Get username from VelocityCMDB config file.
    Falls back to environment variable or 'admin' if not configured.
    """
    config_path = Path.home() / '.velocitycmdb' / 'config.yaml'

    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}

            # Check common config locations for username
            # credentials.username or collection.username or default_username
            creds = config.get('credentials', {})
            if creds.get('username'):
                return creds['username']

            collection = config.get('collection', {})
            if collection.get('username'):
                return collection['username']

            if config.get('default_username'):
                return config['default_username']

        except Exception as e:
            print(f"Warning: Could not read config file: {e}", file=sys.stderr)

    # Fallback to environment variable
    return os.environ.get('VELOCITYCMDB_USERNAME', 'admin')


# Vendor-specific paging disable commands
PAGING_DISABLE = {
    'cisco_ios': 'terminal length 0',
    'cisco_nxos': 'terminal length 0',
    'arista': 'terminal length 0',
    'aruba': 'no page'
}

# Import the command mappings
CAPTURE_COMMANDS = {
    'arp': {
        'cisco_ios': 'show ip arp',
        'cisco_nxos': 'show ip arp',
        'arista': 'show ip arp',
        'aruba': 'show arp'
    },
    'authentication': {
        'cisco_ios': 'show run | section aaa authentication',
        'cisco_nxos': 'show run | section aaa',
        'arista': 'show run section aaa authentication',
        'aruba': 'show authentication'
    },
    'authorization': {
        'cisco_ios': 'show run | section aaa authorization',
        'cisco_nxos': 'show run | section aaa',
        'arista': 'show run section aaa authorization',
        'aruba': 'show aaa authorization'
    },
    'bgp-neighbor': {
        'cisco_ios': 'show ip bgp neighbors',
        'cisco_nxos': 'show ip bgp neighbors',
        'arista': 'show ip bgp neighbors',
        'aruba': None
    },
    'bgp-summary': {
        'cisco_ios': 'show ip bgp summary',
        'cisco_nxos': 'show ip bgp summary',
        'arista': 'show ip bgp summary',
        'aruba': None
    },
    'bgp-table': {
        'cisco_ios': 'show ip bgp',
        'cisco_nxos': 'show ip bgp',
        'arista': 'show ip bgp',
        'aruba': None
    },
    'bgp-table-detail': {
        'cisco_ios': 'show ip bgp | begin Network',
        'cisco_nxos': 'show ip bgp',
        'arista': 'show ip bgp detail',
        'aruba': None
    },
    'cdp': {
        'cisco_ios': 'show cdp neighbors',
        'cisco_nxos': 'show cdp neighbors',
        'arista': None,
        'aruba': 'show cdp neighbors'
    },
    'cdp-detail': {
        'cisco_ios': 'show cdp neighbors detail',
        'cisco_nxos': 'show cdp neighbors detail',
        'arista': None,
        'aruba': 'show cdp neighbors detail'
    },
    'config': {
        'cisco_ios': 'show running-config',
        'cisco_nxos': 'show running-config',
        'arista': 'show running-config',
        'aruba': 'show running-config'
    },
    'configs': {
        'cisco_ios': 'show running-config',
        'cisco_nxos': 'show running-config',
        'arista': 'show running-config',
        'aruba': 'show running-config'
    },
    'console': {
        'cisco_ios': 'show run | section line con',
        'cisco_nxos': 'show run | section console',
        'arista': 'show run section line con',
        'aruba': 'show console'
    },
    'eigrp-neighbor': {
        'cisco_ios': 'show ip eigrp neighbors',
        'cisco_nxos': 'show ip eigrp neighbors',
        'arista': None,
        'aruba': None
    },
    'int-status': {
        'cisco_ios': 'show interfaces status',
        'cisco_nxos': 'show interface status',
        'arista': 'show interfaces status',
        'aruba': 'show interfaces brief'
    },
    'interface-status': {
        'cisco_ios': 'show ip interface brief',
        'cisco_nxos': 'show ip interface brief',
        'arista': 'show ip interface brief',
        'aruba': 'show ip brief'
    },
    'inventory': {
        'cisco_ios': 'show inventory',
        'cisco_nxos': 'show inventory',
        'arista': 'show inventory',
        'aruba': 'show system information'
    },
    'ip_ssh': {
        'cisco_ios': 'show ip ssh',
        'cisco_nxos': 'show ssh server',
        'arista': 'show management ssh',
        'aruba': 'show ip ssh'
    },
    'lldp': {
        'cisco_ios': 'show lldp neighbors',
        'cisco_nxos': 'show lldp neighbors',
        'arista': 'show lldp neighbors',
        'aruba': 'show lldp info remote-device'
    },
    'lldp-detail': {
        'cisco_ios': 'show lldp neighbors detail',
        'cisco_nxos': 'show lldp neighbors detail',
        'arista': 'show lldp neighbors detail',
        'aruba': 'show lldp info remote-device detail'
    },
    'mac': {
        'cisco_ios': 'show mac address-table',
        'cisco_nxos': 'show mac address-table',
        'arista': 'show mac address-table',
        'aruba': 'show mac-address'
    },
    'ntp_status': {
        'cisco_ios': 'show ntp status',
        'cisco_nxos': 'show ntp peer-status',
        'arista': 'show ntp status',
        'aruba': 'show ntp status'
    },
    'ospf-neighbor': {
        'cisco_ios': 'show ip ospf neighbor',
        'cisco_nxos': 'show ip ospf neighbors',
        'arista': 'show ip ospf neighbor',
        'aruba': 'show ip ospf neighbor'
    },
    'port-channel': {
        'cisco_ios': 'show etherchannel summary',
        'cisco_nxos': 'show port-channel summary',
        'arista': 'show port-channel',
        'aruba': 'show trunk'
    },
    'radius': {
        'cisco_ios': 'show run | section radius',
        'cisco_nxos': 'show run | section radius',
        'arista': 'show run section radius',
        'aruba': 'show radius'
    },
    'routes': {
        'cisco_ios': 'show ip route',
        'cisco_nxos': 'show ip route',
        'arista': 'show ip route',
        'aruba': 'show ip route'
    },
    'snmp_server': {
        'cisco_ios': 'show snmp',
        'cisco_nxos': 'show snmp',
        'arista': 'show snmp',
        'aruba': 'show snmp-server'
    },
    'syslog': {
        'cisco_ios': 'show logging',
        'cisco_nxos': 'show logging',
        'arista': 'show logging',
        'aruba': 'show logging'
    },
    'tacacs': {
        'cisco_ios': 'show tacacs',
        'cisco_nxos': 'show tacacs-server',
        'arista': 'show tacacs',
        'aruba': 'show tacacs'
    },
    'version': {
        'cisco_ios': 'show version',
        'cisco_nxos': 'show version',
        'arista': 'show version',
        'aruba': 'show version'
    }
}

VENDOR_FILTERS = {
    'cisco_ios': '*cisco*',
    'cisco_nxos': '*cisco*',
    'arista': '*arista*',
    'aruba': '*aruba*|*hp*|*procurve*'
}

VENDOR_NAMES = {
    'cisco_ios': 'Cisco IOS',
    'cisco_nxos': 'Cisco NX-OS',
    'arista': 'Arista',
    'aruba': 'Aruba/HP'
}

ENABLE_REQUIRED = {
    'cisco_ios': ['configs', 'config', 'inventory'],
    'cisco_nxos': [],
    'arista': [],
    'aruba': ['configs', 'config']
}


def build_command_string(vendor, capture_type):
    """Build complete command string with paging disable and enable if needed"""

    base_command = CAPTURE_COMMANDS.get(capture_type, {}).get(vendor)
    if base_command is None:
        return None

    # Start with paging disable
    paging_cmd = PAGING_DISABLE.get(vendor, '')

    # Add enable if required
    needs_enable = capture_type in ENABLE_REQUIRED.get(vendor, [])

    # Build command chain
    commands = []

    if needs_enable and vendor in ['cisco_ios', 'aruba']:
        commands.append('enable')

    if paging_cmd:
        commands.append(paging_cmd)

    commands.append(base_command)

    return ','.join(commands)


def generate_job_file(vendor, capture_type, job_id, output_dir="Anguis/gnet_jobs"):
    """Generate a single vendor-specific job configuration file"""

    command = build_command_string(vendor, capture_type)

    if command is None:
        return None, False

    job_config = {
        "version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "session_file": "sessions.yaml",
        "vendor": {
            "selected": VENDOR_NAMES[vendor],
            "auto_paging": True
        },
        "credentials": {
            "username": get_configured_username(),
            "credential_system": "Auto-detect from script",
            "password_provided": False,
            "enable_password_provided": False
        },
        "filters": {
            "folder": "",
            "name": "",
            "vendor": VENDOR_FILTERS[vendor],
            "device_type": ""
        },
        "commands": {
            "template": f"{VENDOR_NAMES[vendor]} Command Template",
            "command_text": command,
            "output_directory": capture_type
        },
        "execution": {
            "batch_script": "batch_spn_concurrent.py (Multi-process)",
            "max_workers": 12,
            "verbose": False,
            "dry_run": False
        },
        "fingerprint_options": {
            "fingerprinted_only": True,
            "fingerprint_only": False,
            "fingerprint": False,
            "fingerprint_base": "./fingerprints"
        },
        "ui_state": {
            "current_tab": 0
        },
        "legacy_info": {
            "generated_by": "generate_capture_jobs.py",
            "generation_timestamp": datetime.now().isoformat()
        }
    }

    vendor_short = vendor.replace('_', '-')
    filename = f"job_{job_id:03d}_{vendor_short}_{capture_type}.json"
    filepath = Path(output_dir) / filename

    os.makedirs(output_dir, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(job_config, f, indent=2)

    return filename, True


def generate_all_jobs(output_dir="Anguis/gnet_jobs", start_job_id=200):
    """Generate all vendor/capture type combinations"""

    print("=" * 70)
    print("NETWORK CAPTURE JOB GENERATOR")
    print("=" * 70)

    vendors = ['cisco_ios', 'cisco_nxos', 'arista', 'aruba']
    capture_types = sorted(CAPTURE_COMMANDS.keys())

    job_id = start_job_id
    generated_jobs = []
    skipped_combinations = []

    print(f"\nGenerating jobs for {len(vendors)} vendors × {len(capture_types)} capture types")
    print(f"Output directory: {output_dir}")
    print(f"Starting job ID: {start_job_id}\n")

    for capture_type in capture_types:
        print(f"\n[{capture_type}]")

        for vendor in vendors:
            filename, success = generate_job_file(vendor, capture_type, job_id, output_dir)

            if success:
                generated_jobs.append(filename)
                # Show the actual command being used
                cmd = build_command_string(vendor, capture_type)
                print(f"  ✓ {job_id:03d} | {VENDOR_NAMES[vendor]:15s} | {cmd[:50]}...")
                job_id += 1
            else:
                skipped_combinations.append((vendor, capture_type))
                print(f"  ✗ SKIP | {VENDOR_NAMES[vendor]:15s} | Not supported")

    # Generate master batch list
    batch_list_path = Path(output_dir) / "job_batch_list_generated.txt"
    with open(batch_list_path, 'w', encoding='utf-8') as f:
        f.write("# Auto-generated Network Capture Job Batch List\n")
        f.write(f"# Generated: {datetime.now().isoformat()}\n")
        f.write(f"# Total jobs: {len(generated_jobs)}\n")
        f.write(f"# Skipped combinations: {len(skipped_combinations)}\n\n")

        for job in sorted(generated_jobs):
            f.write(f"{job}\n")

    # Generate vendor-specific batch lists
    for vendor in vendors:
        vendor_jobs = [j for j in generated_jobs if vendor.replace('_', '-') in j]
        vendor_batch_path = Path(output_dir) / f"job_batch_{vendor}.txt"

        with open(vendor_batch_path, 'w', encoding='utf-8') as f:
            f.write(f"# {VENDOR_NAMES[vendor]} Capture Jobs\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(f"# Jobs: {len(vendor_jobs)}\n\n")

            for job in sorted(vendor_jobs):
                f.write(f"{job}\n")

    # Generate capture-type-specific batch lists
    for capture_type in capture_types:
        capture_jobs = [j for j in generated_jobs if f"_{capture_type}.json" in j]
        capture_batch_path = Path(output_dir) / f"job_batch_{capture_type}.txt"

        with open(capture_batch_path, 'w', encoding='utf-8') as f:
            f.write(f"# {capture_type} Capture Jobs (All Vendors)\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(f"# Jobs: {len(capture_jobs)}\n\n")

            for job in sorted(capture_jobs):
                f.write(f"{job}\n")

    # Summary
    print("\n" + "=" * 70)
    print("GENERATION SUMMARY")
    print("=" * 70)
    print(f"Generated jobs:        {len(generated_jobs)}")
    print(f"Skipped combinations:  {len(skipped_combinations)}")
    print(f"Total possible:        {len(vendors) * len(capture_types)}")
    print(f"\nBatch lists created:")
    print(f"  • Master list:       {batch_list_path}")
    for vendor in vendors:
        print(f"  • {VENDOR_NAMES[vendor]:15s}: job_batch_{vendor}.txt")

    if skipped_combinations:
        print(f"\nSkipped combinations ({len(skipped_combinations)}):")
        for vendor, capture in skipped_combinations:
            print(f"  • {VENDOR_NAMES[vendor]:15s} | {capture}")

    print("\n" + "=" * 70)
    print("USAGE EXAMPLES")
    print("=" * 70)
    print("\n# Run all jobs:")
    print(f"python run_jobs_concurrent_batch.py {batch_list_path} --max-processes 8\n")
    print("# Run vendor-specific:")
    print(f"python run_jobs_concurrent_batch.py {output_dir}/job_batch_cisco_ios.txt --max-processes 8\n")
    print("# Run capture-type specific:")
    print(f"python run_jobs_concurrent_batch.py {output_dir}/job_batch_configs.txt --max-processes 8\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate vendor-specific network capture job files",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--output-dir',
        default='Anguis/gnet_jobs',
        help='Output directory for job files (default: Anguis/gnet_jobs)'
    )

    parser.add_argument(
        '--start-id',
        type=int,
        default=200,
        help='Starting job ID number (default: 200)'
    )

    args = parser.parse_args()

    generate_all_jobs(
        output_dir=args.output_dir,
        start_job_id=args.start_id
    )