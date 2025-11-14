#!/usr/bin/env python3
"""
Juniper LLDP Detail Collector - anguisnms Integration

Modified version that pulls inventory from assets.db instead of sessions.yaml.
Designed for anguisnms integration with automatic key-based authentication.

FIXED VERSION with:
- Exact name matching option (--exact-name)
- Device deduplication to prevent processing same device multiple times

Collects detailed LLDP neighbor information from Juniper devices by:
1. Loading device inventory from assets.db
2. Getting interface list via 'show interfaces terse'
3. Parsing active interfaces with LLDP neighbors
4. Running 'show lldp neighbors interface <X>' for each interface
5. Aggregating results into single output file per device
"""

import os
import sys
import json
import argparse
import sqlite3
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Import your existing SSH infrastructure
from ssh_client import SSHClient, SSHClientOptions


class AssetsDBLoader:
    """Load device inventory from anguisnms assets.db"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def load_juniper_devices(self, name_filter: Optional[str] = None,
                             exact_name: Optional[str] = None,
                             site_filter: Optional[str] = None,
                             debug: bool = False) -> List[Dict]:
        """
        Load Juniper devices from assets.db

        Args:
            name_filter: Substring match on device name
            exact_name: Exact match on device name (takes precedence)
            site_filter: Filter by site code or name
            debug: Enable debug output

        Returns list of device dicts compatible with the collector:
        [
            {
                'host': '10.1.1.1',
                'port': 22,
                'display_name': 'qfx.iad1',
                'vendor': 'Juniper',
                'site': 'IAD',
                'device_type': 'qfx5100'
            },
            ...
        ]
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # First, let's see what columns are available
        if debug:
            try:
                cursor.execute("SELECT * FROM devices LIMIT 1")
                if cursor.description:
                    cols = [desc[0] for desc in cursor.description]
                    print(f"Debug: Available columns in devices table: {cols}")
            except Exception as e:
                print(f"Debug: Error checking columns: {e}")

        # Query for Juniper devices using proper schema
        # Join with vendors table to get vendor name
        query = """
        SELECT 
            d.name as display_name,
            COALESCE(d.management_ip, d.ipv4_address) as host,
            v.name as vendor,
            d.model as device_type,
            COALESCE(s.code, d.site_code) as site,
            22 as port
        FROM devices d
        LEFT JOIN vendors v ON d.vendor_id = v.id
        LEFT JOIN sites s ON d.site_code = s.code
        WHERE (LOWER(v.name) LIKE '%juniper%' 
           OR LOWER(v.name) LIKE '%junos%')
        """

        params = []

        # Exact name takes precedence over substring match
        if exact_name:
            query += " AND LOWER(d.name) = ?"
            params.append(exact_name.lower())
            if debug:
                print(f"Debug: Using exact name filter: {exact_name}")
        elif name_filter:
            query += " AND LOWER(d.name) LIKE ?"
            params.append(f"%{name_filter.lower()}%")
            if debug:
                print(f"Debug: Using substring name filter: {name_filter}")

        if site_filter:
            query += " AND (LOWER(d.site_code) LIKE ? OR LOWER(s.name) LIKE ?)"
            params.append(f"%{site_filter.lower()}%")
            params.append(f"%{site_filter.lower()}%")

        try:
            if debug:
                print(f"Debug: Executing query: {query}")
                print(f"Debug: With params: {params}")

            cursor.execute(query, params)
            rows = cursor.fetchall()

            if debug:
                print(f"Debug: Found {len(rows)} rows from database")
                if rows and len(rows) > 0:
                    print(f"Debug: First row: {dict(rows[0])}")

            devices = []
            seen = set()  # Track unique devices to prevent duplicates

            for row in rows:
                # Skip devices without an IP address
                if not row['host']:
                    if debug:
                        print(f"Debug: Skipping {row['display_name']} - no IP address")
                    continue

                # Create unique key from host and display name
                device_key = (row['host'], row['display_name'])

                # Skip if we've already seen this device
                if device_key in seen:
                    if debug:
                        print(f"Debug: Skipping duplicate device: {row['display_name']} ({row['host']})")
                    continue

                seen.add(device_key)

                device = {
                    'host': row['host'],
                    'port': row['port'],
                    'display_name': row['display_name'],
                    'vendor': row['vendor'] or 'Unknown',
                    'device_type': row['device_type'] or 'Unknown',
                    'site': row['site'] or 'unknown'
                }
                devices.append(device)

            conn.close()

            if debug:
                print(f"Debug: Returning {len(devices)} unique devices after deduplication")

            return devices

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            print(f"Note: Check your database structure")

            # Try to show available vendors to help debug
            try:
                cursor.execute("SELECT DISTINCT name FROM vendors ORDER BY name")
                vendors = cursor.fetchall()
                print(f"\nAvailable vendors in database:")
                for v in vendors:
                    print(f"  - {v['name']}")
            except Exception as ve:
                print(f"Could not list vendors: {ve}")

            conn.close()
            return []


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
                 output_base_dir: str = './capture/lldp-detail', debug: bool = False,
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
            # Stage 1: Get interface list (single connection)
            self._log(f"  [{device_name}] Stage 1: Getting interface list...")
            ssh_client = self._create_ssh_client(host, port, device_name)
            ssh_client.connect()

            intf_output = ssh_client.execute_command('show interfaces terse')

            # Parse interfaces
            all_interfaces = InterfaceParser.parse_interfaces_terse(intf_output)
            lldp_interfaces = InterfaceParser.filter_lldp_capable(all_interfaces)

            result['interface_count'] = len(lldp_interfaces)
            self._log(f"  [{device_name}] Found {len(lldp_interfaces)} LLDP-capable interfaces")

            if not lldp_interfaces:
                ssh_client.disconnect()
                result['success'] = True
                result['error'] = 'No LLDP-capable interfaces found'
                return result

            # Stage 2: Collect LLDP detail for each interface (SAME connection)
            self._log(f"  [{device_name}] Stage 2: Collecting LLDP details from {len(lldp_interfaces)} interfaces...")

            aggregated_output = []
            neighbor_count = 0

            # Execute all commands in the same SSH session
            for i, intf in enumerate(lldp_interfaces):
                if self.verbose and i % 10 == 0:
                    self._log(f"    [{device_name}] Progress: {i}/{len(lldp_interfaces)} interfaces checked")

                try:
                    # Execute command in existing session
                    intf_output = ssh_client.execute_command(f'show lldp neighbors interface {intf}')

                    # Check if there's actually a neighbor
                    if intf_output and 'LLDP Neighbor Information:' in intf_output:
                        aggregated_output.append(intf_output)
                        aggregated_output.append("{master:0}")
                        neighbor_count += 1

                except Exception as e:
                    self._log(f"    [{device_name}] Error on {intf}: {e}")

            # Disconnect after all commands
            ssh_client.disconnect()

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


def find_ssh_key(username: str) -> Optional[str]:
    """Find SSH key automatically, trying common locations"""
    possible_keys = [
        os.path.expanduser(f'~/.ssh/{username}/id_rsa'),
        os.path.expanduser(f'~/.ssh/{username}/id_ed25519'),
        os.path.expanduser('~/.ssh/id_rsa'),
        os.path.expanduser('~/.ssh/id_ed25519'),
        os.path.expanduser(f'~/.ssh/{username}/id_ecdsa'),
        os.path.expanduser('~/.ssh/id_ecdsa'),
    ]

    for key_path in possible_keys:
        if Path(key_path).exists():
            return key_path

    return None


def main():
    parser = argparse.ArgumentParser(
        description='Collect detailed LLDP information from Juniper devices (anguisnms version)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect from all Juniper devices in assets.db
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin

  # Collect from specific device (exact match)
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin --exact-name tor1.fra1

  # Collect from specific device (substring match)
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin --name qfx.iad1

  # Filter by site
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin --site IAD

  # Debug mode with verbose output
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin -v -d

  # Custom output directory
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin -o /data/lldp

  # Specify SSH key explicitly
  python collect_juniper_lldp_detail_anguisnms.py --db assets.db -u admin --ssh-key ~/.ssh/id_rsa

Output Format:
  Creates one file per device in ./capture/lldp-detail/ with aggregated LLDP detail 
  from all interfaces. Format mimics multiple 'show lldp neighbors interface <X>' 
  outputs concatenated.
        """
    )

    # Input
    parser.add_argument('--db', '--database', dest='db_path',
                        default='assets.db',
                        help='Path to assets.db database (default: assets.db)')

    # Authentication
    parser.add_argument('-u', '--user', required=True,
                        help='SSH username')
    parser.add_argument('-p', '--password', default='',
                        help='SSH password (optional if using keys)')
    parser.add_argument('--ssh-key',
                        help='Path to SSH private key (auto-detected if not specified)')
    parser.add_argument('--no-keys', action='store_true',
                        help='Disable SSH key authentication (use password only)')

    # Device filtering
    parser.add_argument('--name',
                        help='Filter by device hostname (substring match)')
    parser.add_argument('--exact-name',
                        help='Filter by exact device hostname (exact match - recommended for single device testing)')
    parser.add_argument('--site',
                        help='Filter by site name')

    # Execution
    parser.add_argument('-o', '--output-dir', default='./capture/lldp-detail',
                        help='Output directory (default: ./capture/lldp-detail)')
    parser.add_argument('--max-workers', type=int, default=10,
                        help='Max parallel interface queries per device (default: 10)')

    # Output control
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug output')
    parser.add_argument('--save-summary',
                        help='Save execution summary to JSON file')

    args = parser.parse_args()

    # Check if both --name and --exact-name are provided
    if args.name and args.exact_name:
        print("Error: Cannot use both --name and --exact-name. Please use only one.")
        sys.exit(1)

    # Check if database exists
    if not Path(args.db_path).exists():
        print(f"Error: Database not found: {args.db_path}")
        print(f"\nPlease specify the correct path to assets.db using --db")
        sys.exit(1)

    # Resolve SSH key path
    ssh_key_path = None
    if not args.no_keys:
        if args.ssh_key:
            ssh_key_path = args.ssh_key
            if not Path(ssh_key_path).exists():
                print(f"Error: SSH key not found: {ssh_key_path}")
                sys.exit(1)
        else:
            # Auto-detect SSH key
            ssh_key_path = find_ssh_key(args.user)
            if ssh_key_path:
                print(f"Using SSH key: {ssh_key_path}")
            else:
                print(f"Warning: No SSH key found. Will attempt password authentication.")
                if not args.password:
                    print(f"Error: No SSH key found and no password provided.")
                    print(f"Either provide --ssh-key or -p/--password")
                    sys.exit(1)

    # Load devices from database
    print(f"Loading devices from {args.db_path}...")
    db_loader = AssetsDBLoader(args.db_path)
    devices = db_loader.load_juniper_devices(
        name_filter=args.name,
        exact_name=args.exact_name,
        site_filter=args.site,
        debug=args.debug
    )

    if not devices:
        print("No Juniper devices found in database.")
        print("\nTroubleshooting:")
        print("1. Check that assets.db contains devices with vendor 'Juniper Networks'")
        print("2. Verify devices have management_ip or ipv4_address set")
        print("3. Check database with: sqlite3 assets.db 'SELECT * FROM vendors'")
        if args.exact_name:
            print(f"4. Verify exact device name '{args.exact_name}' exists in database")
        if args.debug:
            print("\nRe-run with -d flag for detailed debug output")
        sys.exit(1)

    print(f"Found {len(devices)} Juniper device(s):")
    for device in devices:
        site_info = f" [{device.get('site', 'unknown')}]" if device.get('site') else ""
        print(f"  - {device.get('display_name')} ({device['host']}){site_info}")

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
    print(f"\nOutput directory: {args.output_dir}")
    summary = collector.collect_from_devices(devices)

    # Save summary if requested
    if args.save_summary:
        with open(args.save_summary, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\nSummary saved to {args.save_summary}")


if __name__ == '__main__':
    main()