#!/usr/bin/env python3
"""
Topology to Sessions Merger
Processes a folder of topology JSON files and generates consolidated sessions.yaml
"""

import os
import json
import yaml
import argparse
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional


class TopologySessionsProcessor:
    """Processes topology files and generates consolidated sessions.yaml"""

    def __init__(self):
        # Platform to vendor mapping
        self.platform_vendor_map = {
            # Cisco patterns
            r'[Cc]isco.*': 'Cisco',
            r'IOS.*': 'Cisco',
            r'IOSv': 'Cisco',
            r'C9\d+': 'Cisco',
            r'WS-C\d+': 'Cisco',
            r'ASR\d+': 'Cisco',
            r'ISR\d+': 'Cisco',

            # Arista patterns
            r'[Aa]rista.*': 'Arista',
            r'vEOS.*': 'Arista',
            r'EOS.*': 'Arista',
            r'DCS-.*': 'Arista',

            # Juniper patterns
            r'[Jj]uniper.*': 'Juniper',
            r'JunOS.*': 'Juniper',
            r'EX\d+': 'Juniper',
            r'QFX\d+': 'Juniper',
            r'SRX\d+': 'Juniper',
            r'MX\d+': 'Juniper',

            # HP/Aruba patterns
            r'[Aa]ruba.*': 'Aruba',
            r'[Pp]ro[Cc]urve.*': 'HP',
            r'JL\d+A': 'Aruba',
            r'J\d+A': 'HP',

            # Palo Alto patterns
            r'[Pp]alo.*[Aa]lto.*': 'Palo Alto',
            r'PA-\d+': 'Palo Alto',
            r'VM-\d+': 'Palo Alto',

            # Fortinet patterns
            r'[Ff]ortinet.*': 'Fortinet',
            r'[Ff]orti[Gg]ate.*': 'Fortinet',
            r'FG-\d+': 'Fortinet',
        }

        # Platform to device type mapping
        self.platform_device_type_map = {
            # Switches
            r'.*[Ss]witch.*': 'Switch',
            r'C9\d+.*': 'Switch',
            r'WS-C\d+.*': 'Switch',
            r'DCS-.*': 'Switch',
            r'EX\d+.*': 'Switch',
            r'QFX\d+.*': 'Switch',
            r'JL\d+A.*': 'Switch',

            # Routers
            r'.*[Rr]outer.*': 'Router',
            r'ASR\d+.*': 'Router',
            r'ISR\d+.*': 'Router',
            r'MX\d+.*': 'Router',

            # Firewalls
            r'.*[Ff]irewall.*': 'Firewall',
            r'PA-\d+.*': 'Firewall',
            r'SRX\d+.*': 'Firewall',
            r'[Ff]orti[Gg]ate.*': 'Firewall',
            r'FG-\d+.*': 'Firewall',

            # Default fallback
            r'.*': 'Network',
        }

    def detect_vendor_from_platform(self, platform: str) -> str:
        """Detect vendor from platform string"""
        if not platform:
            return 'Unknown'

        for pattern, vendor in self.platform_vendor_map.items():
            if re.search(pattern, platform, re.IGNORECASE):
                return vendor

        return 'Unknown'

    def detect_device_type_from_platform(self, platform: str) -> str:
        """Detect device type from platform string"""
        if not platform:
            return 'Network'

        for pattern, device_type in self.platform_device_type_map.items():
            if re.search(pattern, platform, re.IGNORECASE):
                return device_type

        return 'Network'

    def extract_site_from_hostname(self, hostname: str) -> str:
        """Extract site/folder name from hostname"""
        if not hostname:
            return "UNKNOWN"

        # Common hostname patterns: site-function-device-01
        # Examples: frs-core-01, frs-ar1-lan-sw-01, nyc-dc1-fw-01
        parts = hostname.split('-')
        if len(parts) >= 2:
            # First part is usually site identifier
            site_code = parts[0].upper()

            # Check for multi-part site codes (like frs-ar1)
            if len(parts) >= 3 and len(parts[1]) <= 3:
                # If second part is short, it might be part of site (like ar1, dc1)
                site_code = f"{parts[0]}-{parts[1]}".upper()

            return site_code

        # Fallback: use first 3-4 characters if no hyphens
        if len(hostname) >= 3:
            return hostname[:4].upper()

        return "UNKNOWN"

    def generate_credential_id(self, vendor: str, device_type: str) -> str:
        """Generate credential ID based on vendor and device type"""
        # Simple credential ID mapping - can be customized
        cred_map = {
            'Cisco': '1',
            'Arista': '2',
            'Juniper': '3',
            'Palo Alto': '4',
            'Fortinet': '5',
            'Aruba': '6',
            'HP': '6'
        }

        return cred_map.get(vendor, '1')  # Default to credential ID 1

    def merge_topology_files(self, topology_files: List[Path]) -> Dict[str, Any]:
        """Merge multiple topology JSON files"""
        if not topology_files:
            return {}

        print(f"Merging {len(topology_files)} topology files...")

        # Start with first file
        with open(topology_files[0], 'r') as f:
            merged_topology = json.load(f)

        print(f"Base topology: {topology_files[0].name} ({len(merged_topology)} devices)")

        # Merge remaining files
        for topo_file in topology_files[1:]:
            print(f"Merging: {topo_file.name}")

            with open(topo_file, 'r') as f:
                current_topology = json.load(f)

            # Merge devices
            devices_added = 0
            connections_added = 0

            for device_name, device_data in current_topology.items():
                if device_name in merged_topology:
                    # Merge peers and connections for existing device
                    existing_peers = merged_topology[device_name].get('peers', {})
                    new_peers = device_data.get('peers', {})

                    for peer_name, peer_data in new_peers.items():
                        if peer_name in existing_peers:
                            # Merge connections for existing peer
                            existing_connections = existing_peers[peer_name].get('connections', [])
                            new_connections = peer_data.get('connections', [])

                            for conn in new_connections:
                                if conn not in existing_connections:
                                    existing_connections.append(conn)
                                    connections_added += 1
                        else:
                            # Add new peer
                            existing_peers[peer_name] = peer_data
                            connections_added += len(peer_data.get('connections', []))
                else:
                    # Add new device
                    merged_topology[device_name] = device_data
                    devices_added += 1

            print(f"  Added {devices_added} new devices, {connections_added} new connections")

        print(f"Final merged topology: {len(merged_topology)} devices")
        return merged_topology

    def topology_to_sessions(self, merged_topology: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert merged topology to sessions.yaml format"""
        print("Converting topology to sessions format...")

        # Group devices by site
        sites = defaultdict(list)

        for device_name, device_data in merged_topology.items():
            node_details = device_data.get('node_details', {})
            ip_address = node_details.get('ip', '')
            platform = node_details.get('platform', '')

            # Skip devices without IP addresses
            if not ip_address:
                print(f"Warning: Skipping {device_name} - no IP address")
                continue

            # Extract site information
            site_code = self.extract_site_from_hostname(device_name)
            site_name = f"{site_code} Site"

            # Detect vendor and device type
            vendor = self.detect_vendor_from_platform(platform)
            device_type = self.detect_device_type_from_platform(platform)
            credential_id = self.generate_credential_id(vendor, device_type)

            # Create device entry
            device_entry = {
                'DeviceType': device_type,
                'Model': platform,
                'SerialNumber': '',  # Not available in topology data
                'SoftwareVersion': '',  # Not available in topology data
                'Vendor': vendor,
                'credsid': credential_id,
                'display_name': device_name,
                'host': ip_address,
                'port': '22'
            }

            sites[site_name].append(device_entry)

        # Convert to final sessions format
        sessions = []
        for site_name, devices in sorted(sites.items()):
            # Sort devices within each site
            devices.sort(key=lambda x: x['display_name'])

            site_entry = {
                'folder_name': site_name,
                'sessions': devices
            }
            sessions.append(site_entry)

        return sessions

    def process_folder(self, input_folder: Path, output_file: Path = None) -> Dict[str, Any]:
        """Process all topology files in a folder"""
        if not input_folder.exists():
            raise FileNotFoundError(f"Input folder not found: {input_folder}")

        # Find all JSON files
        topology_files = list(input_folder.glob("*.json"))
        if not topology_files:
            raise ValueError(f"No JSON files found in {input_folder}")

        print(f"Found {len(topology_files)} topology files:")
        for f in topology_files:
            print(f"  - {f.name}")

        # Merge topology files
        merged_topology = self.merge_topology_files(topology_files)

        # Convert to sessions format
        sessions_data = self.topology_to_sessions(merged_topology)

        # Generate statistics
        total_devices = sum(len(site['sessions']) for site in sessions_data)
        total_sites = len(sessions_data)

        # Vendor breakdown
        vendor_counts = defaultdict(int)
        device_type_counts = defaultdict(int)

        for site in sessions_data:
            for device in site['sessions']:
                vendor = device.get('Vendor', 'Unknown')
                device_type = device.get('DeviceType', 'Unknown')
                vendor_counts[vendor] += 1
                device_type_counts[device_type] += 1

        # Save sessions file
        if output_file is None:
            output_file = input_folder / "merged_sessions.yaml"

        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(sessions_data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)

        print(f"\nSessions file saved: {output_file}")
        print(f"Total sites: {total_sites}")
        print(f"Total devices: {total_devices}")

        print(f"\nVendor breakdown:")
        for vendor, count in sorted(vendor_counts.items()):
            print(f"  {vendor}: {count} devices")

        print(f"\nDevice type breakdown:")
        for device_type, count in sorted(device_type_counts.items()):
            print(f"  {device_type}: {count} devices")

        print(f"\nSite breakdown:")
        for site in sessions_data:
            site_name = site['folder_name']
            device_count = len(site['sessions'])
            print(f"  {site_name}: {device_count} devices")

        return {
            'sessions_file': str(output_file),
            'total_sites': total_sites,
            'total_devices': total_devices,
            'vendor_counts': dict(vendor_counts),
            'device_type_counts': dict(device_type_counts),
            'sessions_data': sessions_data
        }


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(
        description="Process topology files and generate consolidated sessions.yaml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s sessions_input/
  %(prog)s sessions_input/ -o master_sessions.yaml
  %(prog)s /path/to/topologies/ --output-dir ./output/
        """.strip()
    )

    parser.add_argument(
        'input_folder',
        type=Path,
        help='Folder containing topology JSON files'
    )

    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Output sessions.yaml file (default: input_folder/merged_sessions.yaml)'
    )

    parser.add_argument(
        '--output-dir',
        type=Path,
        help='Output directory (default: same as input folder)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without creating output'
    )

    args = parser.parse_args()

    try:
        # Determine output file
        output_file = args.output
        if not output_file:
            if args.output_dir:
                output_file = args.output_dir / "merged_sessions.yaml"
                args.output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_file = args.input_folder / "merged_sessions.yaml"

        # Process files
        processor = TopologySessionsProcessor()

        if args.dry_run:
            print("DRY RUN - No files will be created")
            topology_files = list(args.input_folder.glob("*.json"))
            print(f"Would process {len(topology_files)} files:")
            for f in topology_files:
                print(f"  - {f.name}")
            print(f"Would create: {output_file}")
            return 0

        result = processor.process_folder(args.input_folder, output_file)
        print(f"\nProcessing completed successfully!")
        print(f"Sessions file: {result['sessions_file']}")

        return 0

    except Exception as e:
        print(f"Error: {str(e)}")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())