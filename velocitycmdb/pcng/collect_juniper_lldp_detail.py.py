#!/usr/bin/env python3
"""
Juniper LLDP Detail Collector - Multi-Stage Collection

Collects detailed LLDP neighbor information from Juniper devices by:
1. Getting interface list via 'show interfaces terse'
2. Parsing active interfaces with LLDP neighbors
3. Running 'show lldp neighbors interface <X>' for each interface
4. Aggregating results into single output file

This is a specialized collector that doesn't fit the standard batch pipeline
because it requires dynamic command generation based on parsed output.
"""

import os
import sys
import json
import argparse
import yaml
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Import your existing SSH infrastructure
from ssh_client import SSHClient, SSHClientOptions


class InterfaceParser:
    """Parse Juniper 'show interfaces terse' to extract interface names"""

    @staticmethod
    def parse_interfaces_terse(output: str) -> List[str]:
        """
        Extract interface names from 'show interfaces terse' output

        Expected format:
        Interface               Admin Link Proto    Local                 Remote
        ge-0/0/0                up    up
        ge-0/0/0.0              up    up   inet     192.168.1.1/24
        """
        interfaces = []

        for line in output.split('\n'):
            line = line.strip()

            # Skip headers and empty lines
            if not line or line.startswith('Interface') or line.startswith('---'):
                continue

            # Extract interface name (first field)
            parts = line.split()
            if len(parts) >= 2:
                interface = parts[0]

                # Skip sub-interfaces (with dots) and logical interfaces
                if '.' not in interface:
                    interfaces.append(interface)

        return sorted(set(interfaces))  # Remove duplicates and sort

    @staticmethod
    def filter_lldp_capable(interfaces: List[str]) -> List[str]:
        """
        Filter to interfaces that typically have LLDP
        Exclude management, loopback, etc.
        """
        filtered = []

        # Common physical interface prefixes on Juniper
        physical_prefixes = [
            'ge-',  # Gigabit Ethernet
            'xe-',  # 10G Ethernet
            'et-',  # 40G/100G Ethernet
            'ae',  # Aggregated Ethernet (LAG)
        ]

        for intf in interfaces:
            # Check if interface matches physical patterns
            if any(intf.startswith(prefix) for prefix in physical_prefixes):
                filtered.append(intf)

        return filtered


class LLDPDetailCollector:
    """Collects detailed LLDP information from Juniper devices"""

    def __init__(self, username: str, password: str = '', ssh_key_path: str = None,
                 output_base_dir: str = 'capture/lldp-detail', debug: bool = False,
                 verbose: bool = False, max_workers: int = 10):
        self.username = username
        self.password = password
        self.ssh_key_path = ssh_key_path
        self.output_base_dir = Path(output_base_dir)
        self.debug = debug
        self.verbose = verbose
        self.max_workers = max_workers

        # Thread-safe output lock
        self.output_lock = Lock()

        # Create output directory
        self.output_base_dir.mkdir(parents=True, exist_ok=True)

    def _log(self, message: str, always: bool = False):
        """Thread-safe logging"""
        if self.verbose or always:
            with self.output_lock:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

    def _create_ssh_client(self, host: str, port: int = 22,
                           display_name: str = None) -> SSHClient:
        """Create SSH client with your existing infrastructure"""

        options = SSHClientOptions(
            host=host,
            port=port,
            username=self.username,
            password=self.password,
            ssh_key_path=self.ssh_key_path,
            display_name=display_name,
            invoke_shell=False,  # Use direct command mode
            timeout=120,
            debug=self.debug
        )

        # Suppress output callback for cleaner logs
        if not self.debug:
            options.output_callback = lambda x: None

        return SSHClient(options)

    def collect_device_lldp_detail(self, device: Dict) -> Dict[str, any]:
        """
        Collect detailed LLDP information from a single device

        Returns:
            {
                'device': device_name,
                'host': ip_address,
                'success': bool,
                'interface_count': int,
                'lldp_neighbors': int,
                'output_file': path,
                'error': str (if failed)
            }
        """
        device_name = device.get('display_name', device.get('host'))
        host = device['host']
        port = device.get('port', 22)

        self._log(f"Starting collection for {device_name} ({host})")

        result = {
            'device': device_name,
            'host': host,
            'success': False,
            'interface_count': 0,
            'lldp_neighbors': 0
        }

        try:
            # Stage 1: Get interface list
            self._log(f"  [{device_name}] Stage 1: Getting interface list...")
            ssh_client = self._create_ssh_client(host, port, device_name)
            ssh_client.connect()

            intf_output = ssh_client.execute_command('show interfaces terse')
            ssh_client.disconnect()

            # Parse interfaces
            all_interfaces = InterfaceParser.parse_interfaces_terse(intf_output)
            lldp_interfaces = InterfaceParser.filter_lldp_capable(all_interfaces)

            result['interface_count'] = len(lldp_interfaces)
            self._log(f"  [{device_name}] Found {len(lldp_interfaces)} LLDP-capable interfaces")

            if not lldp_interfaces:
                result['success'] = True
                result['error'] = 'No LLDP-capable interfaces found'
                return result

            # Stage 2: Collect LLDP detail for each interface
            self._log(f"  [{device_name}] Stage 2: Collecting LLDP details from {len(lldp_interfaces)} interfaces...")

            aggregated_output = []
            neighbor_count = 0

            # Use thread pool for parallel interface queries
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(lldp_interfaces))) as executor:
                # Submit all interface queries
                future_to_intf = {
                    executor.submit(self._collect_interface_lldp, host, port, device_name, intf): intf
                    for intf in lldp_interfaces
                }

                # Collect results as they complete
                for future in as_completed(future_to_intf):
                    intf = future_to_intf[future]
                    try:
                        intf_output = future.result()
                        if intf_output and 'LLDP Neighbor Information:' in intf_output:
                            # Append raw output with explicit record separator for TextFSM
                            aggregated_output.append(intf_output)
                            # Add separator that matches your template's Record trigger
                            aggregated_output.append("{master:0}")
                            neighbor_count += 1
                    except Exception as e:
                        self._log(f"    [{device_name}] Error on {intf}: {e}")

            result['lldp_neighbors'] = neighbor_count
            self._log(f"  [{device_name}] Found LLDP neighbors on {neighbor_count}/{len(lldp_interfaces)} interfaces")

            # Stage 3: Save aggregated output
            output_file = self.output_base_dir / f"{device_name}.txt"
            with open(output_file, 'w') as f:
                f.write('\n'.join(aggregated_output))

            result['output_file'] = str(output_file)
            result['success'] = True

            self._log(f"✓ [{device_name}] Complete - {neighbor_count} neighbors saved to {output_file}", always=True)

        except Exception as e:
            result['error'] = str(e)
            self._log(f"✗ [{device_name}] Failed: {e}", always=True)

        return result

    def _collect_interface_lldp(self, host: str, port: int, device_name: str,
                                interface: str) -> Optional[str]:
        """
        Collect LLDP detail for a single interface
        Returns the output if successful, None if no neighbor
        """
        try:
            ssh_client = self._create_ssh_client(host, port, device_name)
            ssh_client.connect()

            output = ssh_client.execute_command(f'show lldp neighbors interface {interface}')

            ssh_client.disconnect()

            # Check if there's actually a neighbor
            if 'LLDP Neighbor Information:' in output:
                self._log(f"    [{device_name}] {interface}: Found neighbor")
                return output
            else:
                # No neighbor on this interface
                return None

        except Exception as e:
            self._log(f"    [{device_name}] {interface}: Error - {e}")
            return None

    def collect_from_devices(self, devices: List[Dict]) -> Dict[str, any]:
        """
        Collect LLDP detail from multiple devices in parallel

        Args:
            devices: List of device dicts with 'host', 'display_name', etc.

        Returns:
            Summary statistics
        """
        self._log(f"Starting LLDP detail collection for {len(devices)} devices", always=True)

        results = []

        # Collect from devices in parallel
        with ThreadPoolExecutor(max_workers=min(5, len(devices))) as executor:
            future_to_device = {
                executor.submit(self.collect_device_lldp_detail, device): device
                for device in devices
            }

            for future in as_completed(future_to_device):
                device = future_to_device[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self._log(f"✗ Exception for {device.get('display_name', device.get('host'))}: {e}", always=True)

        # Generate summary
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]

        total_interfaces = sum(r.get('interface_count', 0) for r in results)
        total_neighbors = sum(r.get('lldp_neighbors', 0) for r in results)

        summary = {
            'total_devices': len(devices),
            'successful': len(successful),
            'failed': len(failed),
            'total_interfaces': total_interfaces,
            'total_neighbors': total_neighbors,
            'results': results
        }

        self._log("=" * 70, always=True)
        self._log(f"SUMMARY:", always=True)
        self._log(f"  Devices processed: {len(devices)}", always=True)
        self._log(f"  Successful: {len(successful)}", always=True)
        self._log(f"  Failed: {len(failed)}", always=True)
        self._log(f"  Total interfaces checked: {total_interfaces}", always=True)
        self._log(f"  Total LLDP neighbors found: {total_neighbors}", always=True)
        self._log("=" * 70, always=True)

        if failed:
            self._log("\nFailed devices:", always=True)
            for r in failed:
                self._log(f"  - {r['device']}: {r.get('error', 'Unknown error')}", always=True)

        return summary


def load_devices_from_yaml(yaml_file: str, vendor_filter: str = 'juniper') -> List[Dict]:
    """Load devices from sessions.yaml with vendor filtering"""
    with open(yaml_file, 'r') as f:
        sessions = yaml.safe_load(f)

    devices = []
    for folder_group in sessions:
        for device in folder_group.get('sessions', []):
            vendor = device.get('Vendor', '').lower()
            if vendor_filter.lower() in vendor or 'junos' in vendor:
                devices.append(device)

    return devices


def main():
    parser = argparse.ArgumentParser(
        description='Collect detailed LLDP information from Juniper devices',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect from all Juniper devices in sessions.yaml
  python collect_juniper_lldp_detail.py sessions.yaml -u speterman --use-keys

  # Collect from specific device
  python collect_juniper_lldp_detail.py sessions.yaml -u speterman --use-keys --name "qfx.iad1"

  # Debug mode with verbose output
  python collect_juniper_lldp_detail.py sessions.yaml -u speterman --use-keys -v -d

  # Custom output directory
  python collect_juniper_lldp_detail.py sessions.yaml -u speterman --use-keys -o /data/lldp

Output Format:
  Creates one file per device with aggregated LLDP detail from all interfaces.
  Format mimics multiple 'show lldp neighbors interface <X>' outputs concatenated.
        """
    )

    # Input
    parser.add_argument('yaml_file', help='Path to sessions.yaml device inventory')

    # Authentication
    parser.add_argument('-u', '--user', required=True,
                        help='SSH username')
    parser.add_argument('-p', '--password', default='',
                        help='SSH password (optional with --use-keys)')
    parser.add_argument('--use-keys', action='store_true',
                        help='Use SSH key authentication')
    parser.add_argument('--ssh-key',
                        help='Path to SSH private key (default: ~/.ssh/<user>/id_rsa)')

    # Device filtering
    parser.add_argument('--name',
                        help='Filter by device name (substring match)')
    parser.add_argument('--folder',
                        help='Filter by folder name')
    parser.add_argument('--vendor', default='juniper',
                        help='Vendor filter (default: juniper)')

    # Execution
    parser.add_argument('-o', '--output-dir', default='capture/lldp-detail',
                        help='Output directory (default: capture/lldp-detail)')
    parser.add_argument('--max-workers', type=int, default=10,
                        help='Max parallel interface queries per device (default: 10)')
    parser.add_argument('--max-devices', type=int, default=5,
                        help='Max parallel device collections (default: 5)')

    # Output control
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('--save-summary',
                        help='Save execution summary to JSON file')

    args = parser.parse_args()

    # Resolve SSH key path
    ssh_key_path = None
    if args.use_keys:
        if args.ssh_key:
            ssh_key_path = args.ssh_key
        else:
            # Try multiple common key locations
            possible_keys = [
                os.path.expanduser(f'~/.ssh/{args.user}/id_rsa'),
                os.path.expanduser('~/.ssh/id_rsa'),
                os.path.expanduser('~/.ssh/id_ed25519'),
                os.path.expanduser(f'~/.ssh/{args.user}/id_ed25519'),
            ]

            for key_path in possible_keys:
                if Path(key_path).exists():
                    ssh_key_path = key_path
                    print(f"Using SSH key: {ssh_key_path}")
                    break

            if not ssh_key_path:
                print(f"Error: No SSH key found. Tried:")
                for kp in possible_keys:
                    print(f"  - {kp}")
                print(f"\nSpecify key explicitly with --ssh-key")
                sys.exit(1)

        if not Path(ssh_key_path).exists():
            print(f"Error: SSH key not found: {ssh_key_path}")
            sys.exit(1)

    # Load devices
    print(f"Loading devices from {args.yaml_file}...")
    all_devices = load_devices_from_yaml(args.yaml_file, args.vendor)

    # Apply filters
    filtered_devices = all_devices

    if args.name:
        filtered_devices = [
            d for d in filtered_devices
            if args.name.lower() in d.get('display_name', '').lower()
        ]

    if args.folder:
        filtered_devices = [
            d for d in filtered_devices
            if args.folder.lower() in d.get('folder_name', '').lower()
        ]

    if not filtered_devices:
        print("No devices matched the filters.")
        sys.exit(1)

    print(f"Found {len(filtered_devices)} Juniper devices:")
    for device in filtered_devices:
        print(f"  - {device.get('display_name')} ({device['host']})")

    # Create collector
    collector = LLDPDetailCollector(
        username=args.user,
        password=args.password,
        ssh_key_path=ssh_key_path,
        output_base_dir=args.output_dir,
        debug=args.debug,
        verbose=args.verbose,
        max_workers=args.max_workers
    )

    # Execute collection
    summary = collector.collect_from_devices(filtered_devices)

    # Save summary if requested
    if args.save_summary:
        with open(args.save_summary, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\nSummary saved to {args.save_summary}")


if __name__ == '__main__':
    main()