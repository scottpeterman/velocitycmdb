import json
import os
from datetime import datetime
from pathlib import Path

# Module-level constants
JOB_VERSION = "1.0"
DEFAULT_SESSION_FILE = "sessions.yaml"
DEFAULT_MAX_WORKERS = 12
DEFAULT_USERNAME = os.getenv("NETWORK_USERNAME", "admin")
BATCH_SCRIPT = "batch_spn.py (Multi-process)"
FINGERPRINT_BASE = "./output/fingerprints"
DEFAULT_FINGERPRINT_ONLY = False
DEFAULT_USE_KEYS = True  # or False for password-based
DEFAULT_SSH_KEY_PATH = "~/.ssh/admin/id_rsa"

# Vendor configuration
VENDOR_CONFIG = {
    'cisco_ios': {
        'name': 'Cisco IOS',
        'filter': '*cisco*',
        'vendor_name': 'cisco',  # NEW: Simple vendor name for filtering
        'paging_disable': 'terminal length 0',
        'enable_command': 'enable',
        'enable_required_for': ['configs', 'inventory']
    },
    'cisco_nxos': {
        'name': 'Cisco NX-OS',
        'filter': '*cisco*',
        'vendor_name': 'cisco',  # NEW: Simple vendor name for filtering
        'paging_disable': 'terminal length 0',
        'enable_command': None,
        'enable_required_for': []
    },
    'arista': {
        'name': 'Arista',
        'filter': '*arista*',
        'vendor_name': 'arista',  # NEW: Simple vendor name for filtering
        'paging_disable': 'terminal length 0',
        'enable_command': None,
        'enable_required_for': []
    },
    'juniper': {
        'name': 'Juniper',
        'filter': '*juniper*|*junos*',
        'vendor_name': 'juniper',  # NEW: Simple vendor name for filtering
        'paging_disable': 'set cli screen-length 0',
        'enable_command': None,
        'enable_required_for': []
    }
}

# Vendor-specific command mappings
CAPTURE_COMMANDS = {
    'arp': {
        'cisco_ios': 'show ip arp',
        'cisco_nxos': 'show ip arp',
        'arista': 'show ip arp',
        'juniper': 'show arp no-resolve'
    },
    'authentication': {
        'cisco_ios': 'show run | section aaa authentication',
        'cisco_nxos': 'show run | section aaa',
        'arista': 'show run section aaa authentication',
        'juniper': 'show configuration system authentication-order'
    },
    'authorization': {
        'cisco_ios': 'show run | section aaa authorization',
        'cisco_nxos': 'show run | section aaa',
        'arista': 'show run section aaa authorization',
        'juniper': 'show configuration system login'
    },
    'bgp-neighbor': {
        'cisco_ios': 'show ip bgp neighbors',
        'cisco_nxos': 'show ip bgp neighbors',
        'arista': 'show ip bgp neighbors',
        'juniper': 'show bgp neighbor'
    },
    'bgp-summary': {
        'cisco_ios': 'show ip bgp summary',
        'cisco_nxos': 'show ip bgp summary',
        'arista': 'show ip bgp summary',
        'juniper': 'show bgp summary'
    },
    'bgp-table': {
        'cisco_ios': 'show ip bgp',
        'cisco_nxos': 'show ip bgp',
        'arista': 'show ip bgp',
        'juniper': 'show route protocol bgp'
    },
    'bgp-table-detail': {
        'cisco_ios': 'show ip bgp | begin Network',
        'cisco_nxos': 'show ip bgp',
        'arista': 'show ip bgp detail',
        'juniper': 'show route protocol bgp detail'
    },
    'configs': {
        'cisco_ios': 'show running-config',
        'cisco_nxos': 'show running-config',
        'arista': 'show running-config',
        'juniper': 'show configuration'
    },
    'console': {
        'cisco_ios': 'show run | section line con',
        'cisco_nxos': 'show run | section console',
        'arista': 'show run section line con',
        'juniper': 'show configuration system ports console'
    },
    'int-status': {
        'cisco_ios': 'show interfaces status',
        'cisco_nxos': 'show interface status',
        'arista': 'show interfaces status',
        'juniper': 'show interfaces terse'
    },
    'interface-status': {
        'cisco_ios': 'show ip interface brief',
        'cisco_nxos': 'show ip interface brief',
        'arista': 'show ip interface brief',
        'juniper': 'show interfaces terse'
    },
    'inventory': {
        'cisco_ios': 'show inventory',
        'cisco_nxos': 'show inventory',
        'arista': 'show inventory',
        'juniper': 'show chassis hardware'
    },
    'ip_ssh': {
        'cisco_ios': 'show ip ssh',
        'cisco_nxos': 'show ssh server',
        'arista': 'show management ssh',
        'juniper': 'show configuration system services ssh'
    },
    'lldp': {
        'cisco_ios': 'show lldp neighbors',
        'cisco_nxos': 'show lldp neighbors',
        'arista': 'show lldp neighbors',
        'juniper': 'show lldp neighbors'
    },
    'lldp-detail': {
        'cisco_ios': 'show lldp neighbors detail',
        'cisco_nxos': 'show lldp neighbors detail',
        'arista': 'show lldp neighbors detail',
        'juniper': 'show lldp neighbors detail'
    },
    'mac': {
        'cisco_ios': 'show mac address-table',
        'cisco_nxos': 'show mac address-table',
        'arista': 'show mac address-table',
        'juniper': 'show ethernet-switching table'
    },
    'ntp_status': {
        'cisco_ios': 'show ntp status',
        'cisco_nxos': 'show ntp peer-status',
        'arista': 'show ntp status',
        'juniper': 'show ntp status'
    },
    'ospf-neighbor': {
        'cisco_ios': 'show ip ospf neighbor',
        'cisco_nxos': 'show ip ospf neighbors',
        'arista': 'show ip ospf neighbor',
        'juniper': 'show ospf neighbor'
    },
    'port-channel': {
        'cisco_ios': 'show etherchannel summary',
        'cisco_nxos': 'show port-channel summary',
        'arista': 'show port-channel',
        'juniper': 'show lacp interfaces'
    },
    'radius': {
        'cisco_ios': 'show run | section radius',
        'cisco_nxos': 'show run | section radius',
        'arista': 'show run section radius',
        'juniper': 'show configuration system radius-server'
    },
    'routes': {
        'cisco_ios': 'show ip route',
        'cisco_nxos': 'show ip route',
        'arista': 'show ip route',
        'juniper': 'show route'
    },
    'snmp_server': {
        'cisco_ios': 'show snmp',
        'cisco_nxos': 'show snmp',
        'arista': 'show snmp',
        'juniper': 'show configuration snmp'
    },
    'syslog': {
        'cisco_ios': 'show logging',
        'cisco_nxos': 'show logging',
        'arista': 'show logging',
        'juniper': 'show log messages'
    },
    'tacacs': {
        'cisco_ios': 'show tacacs',
        'cisco_nxos': 'show tacacs-server',
        'arista': 'show tacacs',
        'juniper': 'show configuration system tacplus-server'
    },
    'version': {
        'cisco_ios': 'show version',
        'cisco_nxos': 'show version',
        'arista': 'show version',
        'juniper': 'show version'
    }
}


def build_command_string(vendor, capture_type):
    """
    Build complete command string with paging disable and enable if needed.

    Args:
        vendor: Vendor identifier (e.g., 'cisco_ios', 'juniper')
        capture_type: Type of capture (e.g., 'configs', 'version')

    Returns:
        str: Comma-separated command chain, or None if unsupported
    """
    base_command = CAPTURE_COMMANDS.get(capture_type, {}).get(vendor)
    if base_command is None:
        return None

    vendor_cfg = VENDOR_CONFIG.get(vendor, {})
    paging_cmd = vendor_cfg.get('paging_disable', '')
    enable_cmd = vendor_cfg.get('enable_command')
    enable_required = capture_type in vendor_cfg.get('enable_required_for', [])

    commands = []

    # Add enable command if needed
    if enable_required and enable_cmd:
        commands.append(enable_cmd)

    # Add paging disable
    if paging_cmd:
        commands.append(paging_cmd)

    # Add the actual command
    commands.append(base_command)

    return ','.join(commands)


def build_job_config(vendor, capture_type, command, timestamp):
    """
    Build the job configuration dictionary.

    Args:
        vendor: Vendor identifier
        capture_type: Type of capture
        command: Command string to execute
        timestamp: ISO format timestamp

    Returns:
        dict: Complete job configuration
    """
    vendor_cfg = VENDOR_CONFIG[vendor]

    return {
        "version": JOB_VERSION,
        "timestamp": timestamp,
        "session_file": DEFAULT_SESSION_FILE,
        "vendor": {
            "selected": vendor_cfg['name'],
            "auto_paging": True
        },
        "credentials": {
            "username": DEFAULT_USERNAME,
            "credential_system": "Auto-detect from script",
            "password_provided": False,
            "enable_password_provided": False
        },
        "authentication": {
            "use_keys": DEFAULT_USE_KEYS,
            "ssh_key_path": DEFAULT_SSH_KEY_PATH
        },
        "filters": {
            "folder": "",
            "name": "",
            "vendor": vendor_cfg['vendor_name'],  # FIXED: Use simple vendor name
            "device_type": ""
        },
        "commands": {
            "template": f"{vendor_cfg['name']} Command Template",
            "command_text": command,
            "output_directory": capture_type
        },
        "execution": {
            "batch_script": BATCH_SCRIPT,
            "max_workers": DEFAULT_MAX_WORKERS,
            "verbose": False,
            "dry_run": False
        },
        "fingerprint_options": {
            # "fingerprinted_only": True,
            # "fingerprint_only": False,
            # "fingerprint": False,
            "fingerprint_base": FINGERPRINT_BASE
        },
        "ui_state": {
            "current_tab": 0
        },
        "legacy_info": {
            "generated_by": "generate_capture_jobs.py",
            "generation_timestamp": timestamp
        }
    }


def generate_job_file(vendor, capture_type, job_id, output_dir="pcng/gnet_jobs"):
    """
    Generate a single vendor-specific job configuration file.

    Args:
        vendor: Vendor identifier (e.g., 'cisco_ios')
        capture_type: Type of data to capture (e.g., 'configs')
        job_id: Unique numeric identifier for this job
        output_dir: Directory to write job file to

    Returns:
        tuple: (filename, success_bool) or (None, False) if unsupported
    """
    command = build_command_string(vendor, capture_type)

    if command is None:
        return None, False

    timestamp = datetime.now().isoformat()
    job_config = build_job_config(vendor, capture_type, command, timestamp)

    vendor_short = vendor.replace('_', '-')
    filename = f"job_{job_id:03d}_{vendor_short}_{capture_type}.json"
    filepath = Path(output_dir) / filename

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(job_config, f, indent=2)
        return filename, True
    except (IOError, OSError, json.JSONEncodeError) as e:
        print(f"ERROR: Failed to write {filepath}: {e}")
        return None, False


def write_batch_file(filepath, title, jobs):
    """
    Write a batch list file with header and job list.

    Args:
        filepath: Path object for output file
        title: Title/description for the batch file
        jobs: List of job filenames
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(f"# Jobs: {len(jobs)}\n\n")
            for job in sorted(jobs):
                f.write(f"{job}\n")
    except (IOError, OSError) as e:
        print(f"ERROR: Failed to write batch file {filepath}: {e}")


def generate_all_jobs(output_dir="pcng/gnet_jobs", start_job_id=200):
    """
    Generate all vendor/capture type combinations.

    Args:
        output_dir: Directory for output files
        start_job_id: Starting job ID number
    """
    print("=" * 70)
    print("NETWORK CAPTURE JOB GENERATOR")
    print("=" * 70)

    vendors = sorted(VENDOR_CONFIG.keys())
    capture_types = sorted(CAPTURE_COMMANDS.keys())

    job_id = start_job_id
    generated_jobs = []
    skipped_combinations = []

    print(f"\nGenerating jobs for {len(vendors)} vendors × {len(capture_types)} capture types")
    print(f"Output directory: {output_dir}")
    print(f"Starting job ID: {start_job_id}\n")

    # Generate individual job files
    for capture_type in capture_types:
        print(f"\n[{capture_type}]")

        for vendor in vendors:
            filename, success = generate_job_file(vendor, capture_type, job_id, output_dir)

            if success:
                generated_jobs.append(filename)
                cmd = build_command_string(vendor, capture_type)
                vendor_name = VENDOR_CONFIG[vendor]['name']
                vendor_filter = VENDOR_CONFIG[vendor]['vendor_name']
                print(f"  ✓ {job_id:03d} | {vendor_name:15s} | filter={vendor_filter:8s} | {cmd[:40]}...")
                job_id += 1
            else:
                skipped_combinations.append((vendor, capture_type))
                vendor_name = VENDOR_CONFIG[vendor]['name']
                print(f"  ✗ SKIP | {vendor_name:15s} | Not supported")

    # Generate master batch list
    batch_list_path = Path(output_dir) / "job_batch_list_generated.txt"
    write_batch_file(
        batch_list_path,
        f"Auto-generated Network Capture Job Batch List\n# Total jobs: {len(generated_jobs)}\n# Skipped combinations: {len(skipped_combinations)}",
        generated_jobs
    )

    # Generate vendor-specific batch lists
    for vendor in vendors:
        vendor_short = vendor.replace('_', '-')
        vendor_jobs = [j for j in generated_jobs if vendor_short in j]
        vendor_batch_path = Path(output_dir) / f"job_batch_{vendor}.txt"
        write_batch_file(
            vendor_batch_path,
            f"{VENDOR_CONFIG[vendor]['name']} Capture Jobs",
            vendor_jobs
        )

    # Generate capture-type-specific batch lists
    for capture_type in capture_types:
        capture_jobs = [j for j in generated_jobs if f"_{capture_type}.json" in j]
        capture_batch_path = Path(output_dir) / f"job_batch_{capture_type}.txt"
        write_batch_file(
            capture_batch_path,
            f"{capture_type} Capture Jobs (All Vendors)",
            capture_jobs
        )

    # Print summary
    print("\n" + "=" * 70)
    print("GENERATION SUMMARY")
    print("=" * 70)
    print(f"Generated jobs:        {len(generated_jobs)}")
    print(f"Skipped combinations:  {len(skipped_combinations)}")
    print(f"Total possible:        {len(vendors) * len(capture_types)}")
    print(f"\nBatch lists created:")
    print(f"  • Master list:       {batch_list_path}")
    for vendor in vendors:
        print(f"  • {VENDOR_CONFIG[vendor]['name']:15s}: job_batch_{vendor}.txt")

    if skipped_combinations:
        print(f"\nSkipped combinations ({len(skipped_combinations)}):")
        for vendor, capture in skipped_combinations:
            print(f"  • {VENDOR_CONFIG[vendor]['name']:15s} | {capture}")

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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s --output-dir /tmp/jobs --start-id 100

Supported vendors: Cisco IOS, Cisco NX-OS, Arista, Juniper
        """
    )

    parser.add_argument(
        '--output-dir',
        default='pcng/jobs',
        help='Output directory for job files (default: pcng/jobs)'
    )

    parser.add_argument(
        '--start-id',
        type=int,
        default=300,
        help='Starting job ID number (default: 300)'
    )

    args = parser.parse_args()

    generate_all_jobs(
        output_dir=args.output_dir,
        start_job_id=args.start_id
    )