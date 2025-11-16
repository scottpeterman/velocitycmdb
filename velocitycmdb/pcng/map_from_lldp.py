#!/usr/bin/env python3
"""
Convert LLDP Data from assets.db to Topology Format

Reads parsed LLDP neighbor data from assets.db (via tfsm_fire parsing)
and generates topology files similar to snmp_to_topology.py

Features:
- Location-aware component detection
- Per-location topology generation
- Proper interface normalization for Cisco/Juniper/Arista
- Bidirectional connection validation
"""
import json
import sys
import re
import csv
import sqlite3
from pathlib import Path
from typing import Dict, Optional, List, Set
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


class LLDPTopologyBuilder:
    """Builds topology from LLDP data in assets.db"""

    def __init__(self, assets_db_path: str, tfsm_db_path: str, domain_suffix: str = 'home.com',
                 verbose: bool = False, filter_platform: List[str] = None, filter_device: List[str] = None):
        self.assets_db_path = assets_db_path
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

        # Statistics
        self.stats = {
            'devices_processed': 0,
            'snapshots_processed': 0,
            'parse_failures': 0,
            'error_content': 0,
            'total_neighbors': 0,
            'connections_created': 0,
            'filtered_devices': 0,
            'filtered_peers': 0
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
                v.name as vendor_name,
                v.short_name as vendor_short
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
        """

        cursor = self.conn.cursor()
        cursor.execute(query)

        for row in cursor.fetchall():
            device_name = sanitize_string(row['name'])
            # Prefer management_ip, fallback to ipv4_address
            ip = row['management_ip'] or row['ipv4_address'] or ''

            self.device_info[row['id']] = {
                'name': device_name,
                'ip': sanitize_string(ip),
                'vendor': sanitize_string(row['vendor_name'] or 'Unknown')
            }

        self._log(f"Loaded metadata for {len(self.device_info)} devices")

    def get_lldp_snapshots(self) -> List[sqlite3.Row]:
        """Retrieve all LLDP detail snapshots"""
        query = """
            SELECT 
                cs.id as snapshot_id,
                cs.device_id,
                cs.content,
                d.name as device_name,
                v.name as vendor_name
            FROM capture_snapshots cs
            JOIN devices d ON cs.device_id = d.id
            LEFT JOIN vendors v ON d.vendor_id = v.id
            WHERE cs.capture_type = 'lldp-detail'
            ORDER BY d.name
        """

        cursor = self.conn.cursor()
        cursor.execute(query)
        return cursor.fetchall()

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
                return None

        try:
            # find_best_template can return different tuple sizes
            result = self.engine.find_best_template(content, 'lldp')

            if result is None:
                self._log(f"  find_best_template returned None")
                return None

            # Handle variable tuple sizes
            if len(result) == 3:
                template, parsed_data, score = result
            elif len(result) == 4:
                template, parsed_data, score, template_content = result
            elif len(result) == 2:
                template, parsed_data = result
                score = 0
            else:
                self._log(f"  Unexpected result format: {len(result)} elements")
                return None

            self._log(
                f"  Template: {template}, Score: {score}, Data: {len(parsed_data) if parsed_data else 0} neighbors")

            # If we got parsed data, return it even if template had minor errors
            # TextFSM may complain about lines like "Pagination disabled" but still parse neighbors
            if parsed_data and len(parsed_data) > 0:
                return parsed_data

            self._log(f"  No valid parsed data (parsed_data={parsed_data})")
            return None

        except Exception as e:
            self._log(f"  Parse exception: {type(e).__name__}: {e}")
            import traceback
            self._log(f"  Traceback: {traceback.format_exc()}")
            return None

    def map_parsed_fields(self, neighbor: Dict) -> Dict:
        """
        Map parsed LLDP fields to standardized format

        Vendor-specific field mappings:
        - Juniper: DEVICE_ID (neighbor), LOCAL_INTERFACE, PORT_ID (remote port), PLATFORM, MGMT_IP
        - Cisco IOS: NEIGHBOR_NAME, LOCAL_INTERFACE, NEIGHBOR_INTERFACE, NEIGHBOR_DESCRIPTION, MGMT_ADDRESS
        - Arista: NEIGHBOR_NAME, LOCAL_INTERFACE, NEIGHBOR_INTERFACE, NEIGHBOR_DESCRIPTION, MGMT_ADDRESS

        Returns standardized dict with: neighbor_name, local_port, remote_port, platform, ip
        """

        # Extract neighbor name/hostname
        # Priority: DEVICE_ID (Juniper) > NEIGHBOR_NAME (Cisco/Arista) > NEIGHBOR
        neighbor_name = (
                neighbor.get('DEVICE_ID') or  # Juniper
                neighbor.get('NEIGHBOR_NAME') or  # Cisco IOS / Arista
                neighbor.get('NEIGHBOR') or
                neighbor.get('SYSTEM_NAME') or
                neighbor.get('CHASSIS_ID') or  # Arista fallback
                ''
        )

        # Extract local interface
        # All vendors use LOCAL_INTERFACE
        local_port = (
                neighbor.get('LOCAL_INTERFACE') or
                neighbor.get('LOCAL_PORT') or
                neighbor.get('LOCAL_INTF') or
                ''
        )

        # Extract remote interface (neighbor's port)
        # Priority: PORT_ID (Juniper) > NEIGHBOR_INTERFACE (Cisco/Arista)
        remote_port = (
                neighbor.get('PORT_ID') or  # Juniper
                neighbor.get('NEIGHBOR_INTERFACE') or  # Cisco IOS / Arista
                neighbor.get('REMOTE_INTERFACE') or
                neighbor.get('NEIGHBOR_PORT_ID') or
                neighbor.get('REMOTE_PORT') or
                ''
        )

        # Extract platform/system description
        # Juniper has dedicated PLATFORM field
        # Cisco/Arista use NEIGHBOR_DESCRIPTION
        platform = (
                neighbor.get('PLATFORM') or  # Juniper (e.g., "Juniper...")
                neighbor.get('NEIGHBOR_DESCRIPTION') or  # Cisco/Arista (full system desc)
                neighbor.get('SYSTEM_DESCRIPTION') or
                neighbor.get('SYSTEM_DESC') or
                ''
        )

        # Extract management IP
        # Priority: MGMT_IP (Juniper) > MGMT_ADDRESS (Cisco/Arista)
        ip = (
                neighbor.get('MGMT_IP') or  # Juniper
                neighbor.get('MGMT_ADDRESS') or  # Cisco IOS / Arista
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

    def build_topology(self):
        """Build topology from LLDP snapshots in database"""
        self._log("\nBuilding topology from LLDP data...")
        self._log("=" * 70)

        # Load device metadata
        self.load_device_metadata()

        # Get all LLDP snapshots
        snapshots = self.get_lldp_snapshots()
        self.stats['snapshots_processed'] = len(snapshots)

        self._log(f"Processing {len(snapshots)} LLDP snapshots...\n")

        for snapshot in snapshots:
            device_id = snapshot['device_id']
            device_name = sanitize_string(snapshot['device_name'])

            if not device_name:
                continue

            # Filter by device name
            if self._should_filter_device(device_name):
                self.stats['filtered_devices'] += 1
                continue

            # Parse LLDP content
            parsed_neighbors = self.parse_lldp_content(snapshot['content'])

            if not parsed_neighbors:
                # Check if it was error content vs parse failure
                content_lower = snapshot['content'].lower() if snapshot['content'] else ''
                if 'error' in content_lower or 'invalid' in content_lower:
                    self.stats['error_content'] += 1
                    self._log(f"  ⚠ {device_name}: Error content (check LLDP capture command)")
                else:
                    self.stats['parse_failures'] += 1
                    self._log(f"  ✗ {device_name}: Failed to parse")
                continue

            self.stats['devices_processed'] += 1
            self.stats['total_neighbors'] += len(parsed_neighbors)

            # Initialize device in topology
            if device_name not in self.topology:
                device_meta = self.device_info.get(device_id, {})
                vendor = device_meta.get('vendor', 'Unknown')
                ip = device_meta.get('ip', '')

                # Filter by platform
                if self._should_filter_platform(vendor):
                    self._log(f"  Filtering device: {device_name} (platform '{vendor}' matches filter)")
                    self.stats['filtered_devices'] += 1
                    continue

                self.topology[device_name] = {
                    'node_details': {
                        'ip': ip,
                        'platform': vendor
                    },
                    'peers': {}
                }

            self._log(f"  ✓ {device_name}: {len(parsed_neighbors)} neighbors")

            # Process each neighbor
            for neighbor in parsed_neighbors:
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

                # Extract peer platform
                peer_platform = extract_platform(mapped['platform'])
                if not peer_platform:
                    peer_platform = "Unknown"

                # Filter peer by platform
                if self._should_filter_platform(peer_platform):
                    self.stats['filtered_peers'] += 1
                    continue

                peer_ip = mapped['ip']

                # Add peer
                if peer_name not in self.topology[device_name]['peers']:
                    self.topology[device_name]['peers'][peer_name] = {
                        'ip': peer_ip,
                        'platform': peer_platform,
                        'connections': []
                    }

                # Add connection if not duplicate
                connection = [local_port, remote_port]
                if not connection_exists(self.topology[device_name]['peers'][peer_name]['connections'],
                                         local_port, remote_port):
                    self.topology[device_name]['peers'][peer_name]['connections'].append(connection)
                    self.stats['connections_created'] += 1

        return self.topology

    def ensure_bidirectional(self):
        """Ensure all peer relationships are bidirectional"""
        self._log("\nEnsuring bidirectional connections...")

        all_devices = set(self.topology.keys())
        referenced_peers = set()

        # Collect all referenced peers
        for device, data in self.topology.items():
            for peer in data['peers'].keys():
                referenced_peers.add(peer)

        missing_devices = referenced_peers - all_devices

        # Add missing devices as endpoints
        if missing_devices:
            self._log(f"Adding {len(missing_devices)} referenced devices not in topology")
            for peer in missing_devices:
                # Try to find platform/IP from existing peer references
                peer_platform = 'endpoint'
                peer_ip = ''

                for dev_data in self.topology.values():
                    if peer in dev_data['peers']:
                        peer_platform = dev_data['peers'][peer].get('platform', 'endpoint')
                        peer_ip = dev_data['peers'][peer].get('ip', '')
                        break

                self.topology[peer] = {
                    'node_details': {'ip': peer_ip, 'platform': peer_platform},
                    'peers': {}
                }

        # Ensure bidirectional connections
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
                            'platform': peer_platform
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

    def annotate_with_locations(self, locations: Dict[str, str]):
        """Add location metadata to topology"""
        if not locations:
            return

        self._log("\nAnnotating with locations...")
        for device, data in self.topology.items():
            location = locations.get(device, 'unknown')
            data['node_details']['location'] = location

    def print_summary(self):
        """Print topology summary"""
        print(f"\n{'=' * 70}")
        print("TOPOLOGY SUMMARY")
        print(f"{'=' * 70}")
        print(f"Snapshots processed: {self.stats['snapshots_processed']}")
        print(f"Devices parsed: {self.stats['devices_processed']}")
        print(f"Parse failures: {self.stats['parse_failures']}")
        if self.stats['error_content'] > 0:
            print(f"Error content (bad LLDP capture): {self.stats['error_content']}")
        if self.stats['filtered_devices'] > 0:
            print(f"Filtered devices: {self.stats['filtered_devices']}")
        if self.stats['filtered_peers'] > 0:
            print(f"Filtered peers: {self.stats['filtered_peers']}")
        print(f"Total LLDP neighbors: {self.stats['total_neighbors']}")
        print(f"Connections created: {self.stats['connections_created']}")
        print(f"Final device count: {len(self.topology)}")

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


def load_device_locations(csv_file: Path) -> Dict[str, str]:
    """Load hostname -> location mapping from CSV"""
    locations = {}

    if not csv_file or not csv_file.exists():
        return locations

    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                hostname = row.get('Hostname', '').strip().strip('"')
                location = row.get('Site', '').strip().strip('"')

                if hostname and location:
                    clean_hostname = extract_hostname(hostname, '')
                    if clean_hostname:
                        locations[clean_hostname] = location

        print(f"Loaded locations for {len(locations)} devices")
    except Exception as e:
        print(f"Warning: Could not load locations: {e}")

    return locations


def find_connected_components(topology: Dict) -> List[Set[str]]:
    """Find all connected components using DFS"""
    visited = set()
    components = []

    def dfs(node: str, component: Set[str]):
        if node in visited or node not in topology:
            return
        visited.add(node)
        component.add(node)
        for peer in topology[node]['peers'].keys():
            dfs(peer, component)

    for device in topology.keys():
        if device not in visited:
            component = set()
            dfs(device, component)
            if component:
                components.append(component)

    return components


def analyze_components_by_location(topology: Dict, components: List[Set[str]]) -> Dict:
    """Group components by primary location"""
    location_components = {}

    for comp_id, component in enumerate(components, 1):
        location_counts = {}
        for device in component:
            location = topology[device]['node_details'].get('location', 'unknown')
            location_counts[location] = location_counts.get(location, 0) + 1

        if location_counts:
            primary_location = max(location_counts.items(), key=lambda x: x[1])[0]
            location_components[primary_location] = {
                'component_id': comp_id,
                'devices': sorted(list(component)),
                'device_count': len(component),
                'location_breakdown': location_counts
            }

    return location_components


def save_location_topologies(topology: Dict, location_components: Dict, output_dir: Path):
    """Save per-location topology files"""
    saved = []
    for location, info in location_components.items():
        location_safe = re.sub(r'[^\w\-]', '_', location)
        location_file = output_dir / f'topology_{location_safe}.json'

        location_topology = {
            device: topology[device]
            for device in info['devices']
            if device in topology
        }

        with open(location_file, 'w') as f:
            json.dump(location_topology, f, indent=2)
        saved.append(location_file)
    return saved


def main():
    parser = argparse.ArgumentParser(
        description='Build topology from LLDP data in assets.db',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build topology from assets.db
  python lldp_to_topology.py assets.db

  # Specify output file and domain suffix
  python lldp_to_topology.py assets.db -o topology.json -d home.com

  # Filter out devices with "sep" or "tv" in their platform
  python lldp_to_topology.py assets.db --fp "sep,tv"

  # Filter out devices with "rft" or "sw" in their name
  python lldp_to_topology.py assets.db --fd "rft,sw"

  # Combine filters
  python lldp_to_topology.py assets.db --fp "sep,tv" --fd "rft,sw"

  # Include device locations from CSV
  python lldp_to_topology.py assets.db --locations devices.csv

  # Verbose output
  python lldp_to_topology.py assets.db -v

  # Custom TFSM database path
  python lldp_to_topology.py assets.db --tfsm-db /path/to/tfsm_templates.db
        """
    )

    parser.add_argument('assets_db',
                        help='Path to assets.db containing LLDP snapshots')

    parser.add_argument('--tfsm-db',
                        default='tfsm_templates.db',
                        help='Path to TFSM templates database (default: tfsm_templates.db)')

    parser.add_argument('-o', '--output',
                        default='topology.json',
                        help='Output topology file (default: topology.json)')

    parser.add_argument('-d', '--domain',
                        default='home.com',
                        help='Domain suffix to strip from hostnames (default: home.com)')

    parser.add_argument('--locations',
                        help='CSV file with device locations (Hostname,Site columns)')

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

    print(f"LLDP to Topology Converter")
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

    print()

    # Load device locations if provided
    device_locations = {}
    if args.locations:
        device_locations = load_device_locations(Path(args.locations))
        print()

    # Build topology
    builder = LLDPTopologyBuilder(
        assets_db_path=str(assets_db),
        tfsm_db_path=str(tfsm_db),
        domain_suffix=args.domain,
        verbose=args.verbose,
        filter_platform=filter_platform,
        filter_device=filter_device
    )

    try:
        # Build topology from LLDP
        topology = builder.build_topology()

        # Ensure bidirectional
        builder.ensure_bidirectional()

        # Annotate with locations
        if device_locations:
            builder.annotate_with_locations(device_locations)

        # Analyze components
        print("\nAnalyzing network components...")
        components = find_connected_components(topology)
        location_components = analyze_components_by_location(topology, components)

        # Print summary
        builder.print_summary()

        if len(components) > 1:
            print(f"⚠️  WARNING: {len(components)} disconnected network segments")
        else:
            print(f"✓ All devices in single connected component")

        if location_components:
            print(f"\nBy Location:")
            for location, info in sorted(location_components.items(),
                                         key=lambda x: x[1]['device_count'], reverse=True):
                print(f"  {location}: {info['device_count']} devices")

        # Save main topology
        with open(output_file, 'w') as f:
            json.dump(topology, f, indent=2)
        print(f"\nSaved: {output_file}")

        # Save per-location topologies
        if location_components and len(location_components) > 1:
            output_dir = output_file.parent if output_file.parent != Path('.') else Path('.')
            saved_files = save_location_topologies(topology, location_components, output_dir)
            for file in saved_files:
                print(f"Saved: {file}")

        print(f"\n{'=' * 70}")
        print("COMPLETE")
        print(f"{'=' * 70}\n")

    finally:
        builder.close()


if __name__ == "__main__":
    main()