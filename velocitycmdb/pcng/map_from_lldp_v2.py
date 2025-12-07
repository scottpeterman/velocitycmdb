#!/usr/bin/env python3
"""
LLDP Topology Mapper - Root Node BFS Traversal

Builds network topology starting from a root device using BFS with hop limit.
Perfect for multi-site databases - only maps the connected segment.

Features:
- Start from specified root device
- BFS traversal with configurable max hop count
- Only includes devices reachable from root
- Hop distance tracking for each device
- Supports partial network mapping
"""
import json
import sys
import re
import csv
import sqlite3
from pathlib import Path
from typing import Dict, Optional, List, Set, Tuple
from collections import deque
import unicodedata
import argparse

# Import your tfsm_fire library
try:
    from tfsm_fire import TextFSMAutoEngine
except ImportError:
    print("Error: tfsm_fire module not found. Ensure it's in your Python path.")
    sys.exit(1)


def sanitize_string(s: str) -> str:
    """Remove problematic characters"""
    if not s:
        return ""

    s = str(s)
    s = ''.join(char for char in s if ord(char) >= 32 or char in '\n\r\t')
    s = ''.join(char for char in s if unicodedata.category(char)[0] != 'C')

    replacements = {'&': 'and', '<': '', '>': '', '"': "'", '\x00': ''}
    for old, new in replacements.items():
        s = s.replace(old, new)

    return s.strip()


def extract_hostname(system_name: str, domain_suffix: str = 'home.com') -> str:
    """Extract hostname from FQDN"""
    if not system_name:
        return ""

    system_name = sanitize_string(system_name)

    if domain_suffix and system_name.lower().endswith(domain_suffix.lower()):
        hostname = system_name[:-len(domain_suffix)]
    else:
        hostname = system_name

    hostname = re.sub(r'[^\w\-\.]', '', hostname)
    return hostname.strip()


class InterfaceNormalizer:
    """Normalize interface names to short form"""

    @staticmethod
    def normalize(interface: str) -> str:
        if not interface:
            return "unknown"

        interface = str(interface).strip()

        # Juniper - keep as-is (matches xe-0/0/1, ge-1/0/47, ae5, me0, fxp0)
        if re.match(r'^(xe|et|ge|ae|fxp|me)-?[\d/]', interface, re.I):
            return interface

        # Cisco/Arista - normalize to short form
        replacements = [
            (r'TenGigabitEthernet', 'Te'),
            (r'GigabitEthernet', 'Gi'),
            (r'FastEthernet', 'Fa'),
            (r'TenGigE', 'Te'),
            (r'FortyGigE', 'Fo'),
            (r'HundredGigE', 'Hu'),
            (r'Ethernet', 'Eth'),
            (r'Port-channel', 'Po'),
            (r'Management', 'Ma'),
        ]

        result = interface
        for pattern, replacement in replacements:
            result = re.sub(f'^{pattern}', replacement, result, flags=re.I)

        return result


def extract_platform(platform_str: str) -> str:
    """Extract simplified platform from system description (max 20 chars)"""
    if not platform_str:
        return ""

    platform_str = sanitize_string(platform_str)
    platform_str = platform_str.lower()

    # Juniper
    if 'qfx5100' in platform_str:
        return "Juniper QFX5100"
    if 'qfx5120' in platform_str:
        return "Juniper QFX5120"
    if 'qfx5200' in platform_str:
        return "Juniper QFX5200"
    if 'mx10003' in platform_str:
        return "Juniper MX10003"
    if 'mx' in platform_str and 'juniper' in platform_str:
        return "Juniper MX"
    if 'ex' in platform_str and 'juniper' in platform_str:
        return "Juniper EX"
    if 'juniper' in platform_str or 'qfx' in platform_str:
        return "Juniper"

    # Cisco
    if 'catalyst 4500' in platform_str or 'cat4500' in platform_str or 'ws-c45' in platform_str:
        return "Cisco Catalyst 4500"
    if 'catalyst 3850' in platform_str or 'ws-c3850' in platform_str:
        return "Cisco Catalyst 3850"
    if 'catalyst' in platform_str:
        return "Cisco Catalyst"
    if 'nexus' in platform_str or 'n9k' in platform_str or 'n7k' in platform_str:
        return "Cisco Nexus"
    if 'cisco' in platform_str:
        return "Cisco"

    # Arista
    if 'arista' in platform_str or 'dcs-' in platform_str:
        if '7280' in platform_str:
            return "Arista DCS-7280"
        if '7050' in platform_str:
            return "Arista DCS-7050"
        return "Arista"

    # Linux/Unix servers
    if 'debian' in platform_str:
        version_match = re.search(r'debian[^\d]*(\d+)', platform_str)
        if version_match:
            return f"Debian {version_match.group(1)}"
        return "Debian Linux"

    if 'ubuntu' in platform_str:
        version_match = re.search(r'ubuntu[^\d]*([\d.]+)', platform_str)
        if version_match:
            ver = version_match.group(1).split('.')[0]
            return f"Ubuntu {ver}"
        return "Ubuntu Linux"

    if 'red hat' in platform_str or 'rhel' in platform_str:
        version_match = re.search(r'(?:red hat|rhel)[^\d]*([\d.]+)', platform_str)
        if version_match:
            ver = version_match.group(1).split('.')[0]
            return f"RHEL {ver}"
        return "Red Hat Linux"

    if 'centos' in platform_str:
        version_match = re.search(r'centos[^\d]*([\d.]+)', platform_str)
        if version_match:
            ver = version_match.group(1).split('.')[0]
            return f"CentOS {ver}"
        return "CentOS Linux"

    # Generic Linux
    if 'linux' in platform_str:
        kernel_match = re.search(r'linux[^\d]*([\d.]+)', platform_str)
        if kernel_match:
            kernel = kernel_match.group(1).split('.')
            if len(kernel) >= 2:
                return f"Linux {kernel[0]}.{kernel[1]}"
            elif len(kernel) >= 1:
                return f"Linux {kernel[0]}"
        return "Linux"

    # FreeBSD/Unix
    if 'freebsd' in platform_str:
        return "FreeBSD"
    if 'openbsd' in platform_str:
        return "OpenBSD"

    return ""


def normalize_connection(local_port: str, remote_port: str) -> tuple:
    """Create a normalized connection tuple for comparison"""
    return (
        InterfaceNormalizer.normalize(local_port),
        InterfaceNormalizer.normalize(remote_port)
    )


def connection_exists(connections: List, local_port: str, remote_port: str) -> bool:
    """Check if a connection already exists (handles list format)"""
    target = normalize_connection(local_port, remote_port)

    for conn in connections:
        if len(conn) >= 2:
            existing = normalize_connection(conn[0], conn[1])
            if existing == target:
                return True
    return False


class LLDPTopologyMapper:
    """Builds topology from LLDP data starting from a root node"""

    def __init__(self, assets_db_path: str, tfsm_db_path: str, root_device: str,
                 max_hops: int = 4, domain_suffix: str = 'home.com',
                 verbose: bool = False, filter_platform: List[str] = None,
                 filter_device: List[str] = None):
        self.assets_db_path = assets_db_path
        self.root_device = root_device.lower()  # Normalize for comparison
        self.max_hops = max_hops
        self.domain_suffix = domain_suffix
        self.verbose = verbose
        self.filter_platform = [f.lower().strip() for f in (filter_platform or [])]
        self.filter_device = [f.lower().strip() for f in (filter_device or [])]

        # Connect to database
        self.conn = sqlite3.connect(assets_db_path)
        self.conn.row_factory = sqlite3.Row

        # Initialize TFSM engine
        self.engine = TextFSMAutoEngine(tfsm_db_path, verbose=False)

        # Topology storage
        self.topology = {}
        self.device_info = {}  # Cache device info
        self.device_hops = {}  # Track hop distance from root
        self.lldp_cache = {}  # Cache parsed LLDP data

        # Statistics
        self.stats = {
            'devices_processed': 0,
            'snapshots_processed': 0,
            'parse_failures': 0,
            'error_content': 0,
            'total_neighbors': 0,
            'connections_created': 0,
            'filtered_devices': 0,
            'filtered_peers': 0,
            'max_hop_reached': 0
        }

    def _log(self, message: str):
        """Log message if verbose"""
        if self.verbose:
            print(message)

    def _should_filter_device(self, device_name: str) -> bool:
        """Check if device should be filtered by name"""
        if not self.filter_device:
            return False
        device_lower = device_name.lower()
        for filter_term in self.filter_device:
            if filter_term in device_lower:
                self._log(f"  Filtering device: {device_name} (matches '{filter_term}')")
                return True
        return False

    def _should_filter_platform(self, platform: str) -> bool:
        """Check if device should be filtered by platform"""
        if not self.filter_platform:
            return False
        platform_lower = platform.lower()
        for filter_term in self.filter_platform:
            if filter_term in platform_lower:
                return True
        return False

    def load_device_metadata(self):
        """Load device information from database"""
        query = """
            SELECT 
                d.id,
                d.name,
                d.normalized_name,
                d.management_ip,
                d.ipv4_address,
                d.model,
                v.name as vendor_name,
                v.short_name as vendor_short
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
        """

        cursor = self.conn.cursor()
        cursor.execute(query)

        for row in cursor.fetchall():
            device_name = sanitize_string(row['name'])
            normalized_name = sanitize_string(row['normalized_name'])
            # Prefer management_ip, fallback to ipv4_address
            ip = row['management_ip'] or row['ipv4_address'] or ''

            # Store by both name and normalized_name for flexible lookup
            device_data = {
                'id': row['id'],
                'name': device_name,
                'normalized_name': normalized_name,
                'ip': sanitize_string(ip),
                'model': sanitize_string(row['model'] or ''),
                'vendor': sanitize_string(row['vendor_name'] or 'Unknown')
            }

            self.device_info[device_name.lower()] = device_data
            self.device_info[normalized_name.lower()] = device_data

        self._log(f"Loaded metadata for {len(self.device_info)} devices")

    def find_device_id(self, device_name: str) -> Optional[int]:
        """Find device ID by name (case insensitive)"""
        device_lower = device_name.lower()
        if device_lower in self.device_info:
            return self.device_info[device_lower]['id']
        return None

    def get_device_lldp(self, device_id: int) -> Optional[List[Dict]]:
        """Get parsed LLDP neighbors for a device (with caching)"""
        if device_id in self.lldp_cache:
            return self.lldp_cache[device_id]

        query = """
            SELECT content
            FROM capture_snapshots
            WHERE device_id = ? AND capture_type = 'lldp-detail'
            ORDER BY captured_at DESC
            LIMIT 1
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (device_id,))
        row = cursor.fetchone()

        if not row or not row['content']:
            self.lldp_cache[device_id] = None
            return None

        # Parse LLDP content
        parsed = self.parse_lldp_content(row['content'])
        self.lldp_cache[device_id] = parsed
        return parsed

    def parse_lldp_content(self, content: str) -> Optional[List[Dict]]:
        """Parse LLDP content using tfsm_fire"""
        if not content or not content.strip():
            return None

        # Check for error patterns in content
        content_lower = content.lower()
        error_patterns = [
            'error: syntax error',
            'invalid command',
            'invalid input',
            '% invalid',
            'command not found'
        ]

        for pattern in error_patterns:
            if pattern in content_lower:
                self._log(f"  Skipping - content contains error: '{pattern}'")
                self.stats['error_content'] += 1
                return None

        try:
            best_template, result, best_score = self.engine.find_best_template(content, 'show_lldp')

            if result and len(result) > 0:
                return result

            return None

        except Exception as e:
            self._log(f"  Parse exception: {type(e).__name__}: {e}")
            self.stats['parse_failures'] += 1
            return None

    def map_parsed_fields(self, neighbor: Dict) -> Dict:
        """Map parsed LLDP fields to standardized format"""
        neighbor_name = (
                neighbor.get('DEVICE_ID') or
                neighbor.get('NEIGHBOR_NAME') or
                neighbor.get('NEIGHBOR') or
                neighbor.get('SYSTEM_NAME') or
                neighbor.get('CHASSIS_ID') or
                ''
        )

        local_port = (
                neighbor.get('LOCAL_INTERFACE') or
                neighbor.get('LOCAL_PORT') or
                neighbor.get('LOCAL_INTF') or
                ''
        )

        remote_port = (
                neighbor.get('PORT_ID') or
                neighbor.get('NEIGHBOR_INTERFACE') or
                neighbor.get('REMOTE_INTERFACE') or
                neighbor.get('NEIGHBOR_PORT_ID') or
                neighbor.get('REMOTE_PORT') or
                ''
        )

        platform = (
                neighbor.get('PLATFORM') or
                neighbor.get('NEIGHBOR_DESCRIPTION') or
                neighbor.get('SYSTEM_DESCRIPTION') or
                neighbor.get('SYSTEM_DESC') or
                ''
        )

        ip = (
                neighbor.get('MGMT_IP') or
                neighbor.get('MGMT_ADDRESS') or
                neighbor.get('MANAGEMENT_IP') or
                neighbor.get('MANAGEMENT_ADDRESS') or
                neighbor.get('IP') or
                ''
        )

        return {
            'neighbor_name': sanitize_string(neighbor_name),
            'local_port': sanitize_string(local_port),
            'remote_port': sanitize_string(remote_port),
            'platform': sanitize_string(platform),
            'ip': sanitize_string(ip)
        }

    def build_topology_bfs(self):
        """Build topology using BFS from root device with hop limit"""
        self._log("\nBuilding topology from root device using BFS...")
        self._log("=" * 70)

        # Load device metadata
        self.load_device_metadata()

        # Find root device
        root_id = self.find_device_id(self.root_device)
        if not root_id:
            print(f"ERROR: Root device '{self.root_device}' not found in database")
            print(f"Available devices starting with '{self.root_device[:3]}':")
            for name in sorted(self.device_info.keys())[:10]:
                print(f"  - {name}")
            sys.exit(1)

        root_info = self.device_info[self.root_device.lower()]
        root_name = root_info['name']

        # Use model if available, otherwise fall back to vendor
        root_platform = root_info['model'] if root_info['model'] else root_info['vendor']

        print(f"\nRoot Device: {root_name}")
        print(f"Max Hops: {self.max_hops}")
        print(f"Starting BFS traversal...\n")

        # BFS queue: (device_name, device_id, hop_count)
        queue = deque([(root_name, root_id, 0)])
        visited = {root_name.lower()}
        self.device_hops[root_name] = 0

        # Initialize root in topology
        self.topology[root_name] = {
            'node_details': {
                'ip': root_info['ip'],
                'platform': root_platform,
                'hop_distance': 0
            },
            'peers': {}
        }

        while queue:
            current_name, current_id, current_hop = queue.popleft()

            self._log(f"\n[Hop {current_hop}] Processing: {current_name}")

            # Check hop limit
            if current_hop >= self.max_hops:
                self._log(f"  Max hop limit reached, not exploring neighbors")
                self.stats['max_hop_reached'] += 1
                continue

            # Get LLDP neighbors
            neighbors = self.get_device_lldp(current_id)

            if not neighbors:
                self._log(f"  No LLDP data available")
                continue

            self.stats['devices_processed'] += 1
            self.stats['total_neighbors'] += len(neighbors)
            self._log(f"  Found {len(neighbors)} LLDP neighbors")

            # Process each neighbor
            for neighbor in neighbors:
                mapped = self.map_parsed_fields(neighbor)

                peer_name = extract_hostname(mapped['neighbor_name'], self.domain_suffix)
                local_port = mapped['local_port']
                remote_port = mapped['remote_port']

                if not peer_name or not local_port or not remote_port:
                    continue

                # Filter peer by name
                if self._should_filter_device(peer_name):
                    self.stats['filtered_peers'] += 1
                    continue

                # Normalize interfaces
                local_port = InterfaceNormalizer.normalize(local_port)
                remote_port = InterfaceNormalizer.normalize(remote_port)

                # Extract peer platform from LLDP data
                peer_platform_from_lldp = extract_platform(mapped['platform'])

                # Try to get peer info from database
                peer_lower = peer_name.lower()
                peer_platform = None
                peer_ip = mapped['ip']

                # Check if peer exists in our device_info (from DB)
                if peer_lower in self.device_info:
                    peer_info = self.device_info[peer_lower]
                    # Use model if available, otherwise use vendor
                    peer_platform = peer_info['model'] if peer_info['model'] else peer_info['vendor']
                    # Use IP from DB if LLDP didn't provide one
                    if not peer_ip:
                        peer_ip = peer_info['ip']
                else:
                    # Peer not in DB, use platform from LLDP data
                    peer_platform = peer_platform_from_lldp if peer_platform_from_lldp else "Unknown"

                # Filter peer by platform
                if self._should_filter_platform(peer_platform):
                    self.stats['filtered_peers'] += 1
                    continue

                # Add peer to current device's peers
                if peer_name not in self.topology[current_name]['peers']:
                    self.topology[current_name]['peers'][peer_name] = {
                        'ip': peer_ip,
                        'platform': peer_platform,
                        'connections': []
                    }

                # Add connection if not duplicate
                connection = [local_port, remote_port]
                if not connection_exists(self.topology[current_name]['peers'][peer_name]['connections'],
                                         local_port, remote_port):
                    self.topology[current_name]['peers'][peer_name]['connections'].append(connection)
                    self.stats['connections_created'] += 1

                # Queue peer for exploration if not visited and within hop limit
                if peer_lower not in visited:
                    visited.add(peer_lower)
                    peer_id = self.find_device_id(peer_name)

                    if peer_id:
                        next_hop = current_hop + 1
                        self.device_hops[peer_name] = next_hop

                        # Initialize peer in topology
                        if peer_name not in self.topology:
                            peer_info = self.device_info.get(peer_lower, {})
                            # Use model if available, otherwise vendor, otherwise platform from LLDP
                            if peer_info:
                                peer_platform_final = peer_info.get('model') or peer_info.get('vendor', peer_platform)
                            else:
                                peer_platform_final = peer_platform

                            self.topology[peer_name] = {
                                'node_details': {
                                    'ip': peer_info.get('ip', peer_ip),
                                    'platform': peer_platform_final,
                                    'hop_distance': next_hop
                                },
                                'peers': {}
                            }

                        if next_hop < self.max_hops:
                            queue.append((peer_name, peer_id, next_hop))
                            self._log(f"    Queued: {peer_name} (hop {next_hop})")
                        else:
                            self._log(f"    Found: {peer_name} (at max hop limit, won't explore)")
                    else:
                        # Peer not in database, add as endpoint
                        if peer_name not in self.topology:
                            self.topology[peer_name] = {
                                'node_details': {
                                    'ip': peer_ip,
                                    'platform': peer_platform,
                                    'hop_distance': current_hop + 1
                                },
                                'peers': {}
                            }
                        self._log(f"    Endpoint: {peer_name} (not in database)")

        return self.topology

    def ensure_bidirectional(self):
        """Ensure all peer relationships are bidirectional"""
        self._log("\nEnsuring bidirectional connections...")

        devices_to_process = list(self.topology.keys())

        for device in devices_to_process:
            device_data = self.topology[device]

            for peer, peer_data in list(device_data['peers'].items()):
                # Ensure peer exists in topology
                if peer not in self.topology:
                    peer_platform = peer_data.get('platform', 'endpoint')
                    self.topology[peer] = {
                        'node_details': {
                            'ip': peer_data.get('ip', ''),
                            'platform': peer_platform,
                            'hop_distance': device_data['node_details'].get('hop_distance', 0) + 1
                        },
                        'peers': {}
                    }

                # Check if reverse peer relationship exists
                if device not in self.topology[peer]['peers']:
                    self.topology[peer]['peers'][device] = {
                        'ip': device_data['node_details'].get('ip', ''),
                        'platform': device_data['node_details'].get('platform', ''),
                        'connections': []
                    }

                # Add reverse connections
                existing_reverse = self.topology[peer]['peers'][device].get('connections', [])

                for connection in peer_data.get('connections', []):
                    if len(connection) >= 2:
                        local_port = connection[0]
                        remote_port = connection[1]

                        if not connection_exists(existing_reverse, remote_port, local_port):
                            reverse_connection = [remote_port, local_port]
                            self.topology[peer]['peers'][device]['connections'].append(reverse_connection)

        self._log(f"Topology now has {len(self.topology)} total devices")

    def print_summary(self):
        """Print topology summary"""
        print(f"\n{'=' * 70}")
        print("TOPOLOGY SUMMARY")
        print(f"{'=' * 70}")
        print(f"Root Device: {self.root_device}")
        print(f"Max Hops: {self.max_hops}")
        print(f"Devices processed: {self.stats['devices_processed']}")
        print(f"Parse failures: {self.stats['parse_failures']}")
        if self.stats['error_content'] > 0:
            print(f"Error content (bad LLDP capture): {self.stats['error_content']}")
        if self.stats['filtered_devices'] > 0:
            print(f"Filtered devices: {self.stats['filtered_devices']}")
        if self.stats['filtered_peers'] > 0:
            print(f"Filtered peers: {self.stats['filtered_peers']}")
        if self.stats['max_hop_reached'] > 0:
            print(f"Devices at max hop limit: {self.stats['max_hop_reached']}")
        print(f"Total LLDP neighbors: {self.stats['total_neighbors']}")
        print(f"Connections created: {self.stats['connections_created']}")
        print(f"Final device count: {len(self.topology)}")

        # Hop distribution
        hop_counts = {}
        for device, data in self.topology.items():
            hop = data['node_details'].get('hop_distance', -1)
            hop_counts[hop] = hop_counts.get(hop, 0) + 1

        if hop_counts:
            print(f"\nHop Distribution:")
            for hop in sorted(hop_counts.keys()):
                print(f"  Hop {hop}: {hop_counts[hop]} devices")

        # Vendor distribution
        vendor_counts = {}
        for device_data in self.topology.values():
            vendor = device_data['node_details'].get('platform', 'Unknown')
            vendor_counts[vendor] = vendor_counts.get(vendor, 0) + 1

        if vendor_counts:
            print(f"\nVendor Distribution:")
            for vendor, count in sorted(vendor_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {vendor}: {count} devices")

        print(f"{'=' * 70}\n")

    def close(self):
        """Clean up database connection"""
        if self.conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Build topology from LLDP data starting from a root device',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Map from core router with default 4 hop limit
  python lldp_map_from_root.py assets.db core-rtr-01

  # Map with 2 hop limit (just immediate neighbors and their neighbors)
  python lldp_map_from_root.py assets.db core-rtr-01 --max-hops 2

  # Specify output file
  python lldp_map_from_root.py assets.db tor412.iad2 -o iad2_topology.json

  # Filter out endpoints (phones, cameras, etc)
  python lldp_map_from_root.py assets.db core-rtr-01 --fp "sep,debian"

  # Verbose output to see BFS traversal
  python lldp_map_from_root.py assets.db core-rtr-01 -v

  # Custom domain suffix
  python lldp_map_from_root.py assets.db core-rtr-01 -d .mycompany.com
        """
    )

    parser.add_argument('assets_db',
                        help='Path to assets.db containing LLDP snapshots')

    parser.add_argument('root_device',
                        help='Root device name to start mapping from')

    parser.add_argument('--tfsm-db',
                        default='tfsm_templates.db',
                        help='Path to TFSM templates database (default: tfsm_templates.db)')

    parser.add_argument('--max-hops',
                        type=int,
                        default=6,
                        help='Maximum hop count from root device (default: 4)')

    parser.add_argument('-o', '--output',
                        default='topology.json',
                        help='Output topology file (default: topology.json)')

    parser.add_argument('-d', '--domain',
                        default='home.com',
                        help='Domain suffix to strip from hostnames (default: home.com)')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Enable verbose output')

    parser.add_argument('--fp', '--filter-platform',
                        dest='filter_platform',
                        help='Filter out devices by platform (comma-separated keywords, e.g., "sep,tv")')

    parser.add_argument('--fd', '--filter-device',
                        dest='filter_device',
                        help='Filter out devices by name (comma-separated keywords, e.g., "rft,sw")')

    args = parser.parse_args()

    # Validate inputs
    assets_db = Path(args.assets_db)
    if not assets_db.exists():
        print(f"Error: Assets database not found: {assets_db}")
        sys.exit(1)

    tfsm_db = Path(args.tfsm_db)
    if not tfsm_db.exists():
        print(f"Error: TFSM database not found: {tfsm_db}")
        print(f"Please provide correct path with --tfsm-db")
        sys.exit(1)

    output_file = Path(args.output)

    print(f"LLDP Topology Mapper - Root Device BFS")
    print(f"{'=' * 70}")
    print(f"Assets DB: {assets_db}")
    print(f"TFSM DB:   {tfsm_db}")
    print(f"Output:    {output_file}")
    print(f"Domain:    {args.domain}")

    # Parse filter arguments
    filter_platform = []
    filter_device = []

    if args.filter_platform:
        filter_platform = [f.strip() for f in args.filter_platform.split(',') if f.strip()]
        print(f"Filter Platform: {', '.join(filter_platform)}")

    if args.filter_device:
        filter_device = [f.strip() for f in args.filter_device.split(',') if f.strip()]
        print(f"Filter Device: {', '.join(filter_device)}")

    # Build topology
    mapper = LLDPTopologyMapper(
        assets_db_path=str(assets_db),
        tfsm_db_path=str(tfsm_db),
        root_device=args.root_device,
        max_hops=args.max_hops,
        domain_suffix=args.domain,
        verbose=args.verbose,
        filter_platform=filter_platform,
        filter_device=filter_device
    )

    try:
        # Build topology from root using BFS
        topology = mapper.build_topology_bfs()

        if not topology:
            print("\nERROR: No topology built. Check that root device has LLDP data.")
            sys.exit(1)

        # Ensure bidirectional
        mapper.ensure_bidirectional()

        # Print summary
        mapper.print_summary()

        # Save topology
        with open(output_file, 'w') as f:
            json.dump(topology, f, indent=2)
        print(f"Saved: {output_file}")

        print(f"\n{'=' * 70}")
        print("COMPLETE")
        print(f"{'=' * 70}\n")

    finally:
        mapper.close()


if __name__ == "__main__":
    main()