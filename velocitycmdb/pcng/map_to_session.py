#!/usr/bin/env python3
"""
Converter from Secure Cartography JSON topology to sessions.yaml inventory format
Transforms network topology discovery data into collection pipeline inventory
"""

import json
import yaml
import re
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


class TopologyToInventoryConverter:
    """Converts Secure Cartography JSON topology to sessions.yaml format"""

    def __init__(self):
        # Platform to vendor mapping
        self.platform_vendor_map = {
            # Cisco patterns
            r'C9\d+': 'Cisco',
            r'WS-C\d+': 'Cisco',
            r'CISCO\d+': 'Cisco',
            r'ASR\d+': 'Cisco',
            r'ISR\d+': 'Cisco',
            r'C\d+[A-Z]': 'Cisco',

            # Arista patterns
            r'DCS-\d+': 'Arista',
            r'vEOS': 'Arista',

            # Juniper patterns
            r'EX\d+': 'Juniper',
            r'QFX\d+': 'Juniper',
            r'SRX\d+': 'Juniper',
            r'MX\d+': 'Juniper',

            # HP/Aruba patterns
            r'JL\d+A': 'Aruba',
            r'J\d+A': 'HP',
            r'ProCurve': 'HP',

            # Palo Alto patterns
            r'PA-\d+': 'Palo Alto Networks',
            r'VM-\d+': 'Palo Alto Networks',

            # Fortinet patterns
            r'FortiGate': 'Fortinet',
            r'FG-\d+': 'Fortinet',
        }

        # Platform to device type mapping
        self.platform_device_type_map = {
            # Switches
            r'C9\d+[L]?-\d+[TGX]': 'Switch',
            r'WS-C\d+': 'Switch',
            r'DCS-\d+': 'Switch',
            r'EX\d+': 'Switch',
            r'QFX\d+': 'Switch',
            r'JL\d+A': 'Switch',

            # Routers
            r'CISCO\d+': 'Router',
            r'ASR\d+': 'Router',
            r'ISR\d+': 'Router',
            r'MX\d+': 'Router',

            # Firewalls
            r'PA-\d+': 'Firewall',
            r'SRX\d+': 'Firewall',
            r'FortiGate': 'Firewall',
            r'FG-\d+': 'Firewall',
        }

    def detect_vendor_from_platform(self, platform: str) -> str:
        """Detect vendor from platform string"""
        if not platform:
            return ''

        for pattern, vendor in self.platform_vendor_map.items():
            if re.search(pattern, platform, re.IGNORECASE):
                return vendor

        # Default vendor detection from hostname patterns
        platform_lower = platform.lower()
        if 'cisco' in platform_lower or 'cat' in platform_lower:
            return 'Cisco'
        elif 'arista' in platform_lower or 'eos' in platform_lower:
            return 'Arista'
        elif 'juniper' in platform_lower or 'junos' in platform_lower:
            return 'Juniper'
        elif 'palo' in platform_lower or 'pan-os' in platform_lower:
            return 'Palo Alto Networks'
        elif 'fortinet' in platform_lower or 'fortigate' in platform_lower:
            return 'Fortinet'
        elif 'aruba' in platform_lower or 'procurve' in platform_lower:
            return 'Aruba'

        return ''

    def detect_device_type_from_platform(self, platform: str) -> str:
        """Detect device type from platform string"""
        if not platform:
            return 'Network'

        for pattern, device_type in self.platform_device_type_map.items():
            if re.search(pattern, platform, re.IGNORECASE):
                return device_type

        # Default detection based on common patterns
        platform_lower = platform.lower()
        if any(word in platform_lower for word in ['switch', 'sw', 'catalyst']):
            return 'Switch'
        elif any(word in platform_lower for word in ['router', 'rtr', 'gateway']):
            return 'Router'
        elif any(word in platform_lower for word in ['firewall', 'fw', 'asa', 'palo', 'fortinet']):
            return 'Firewall'
        elif any(word in platform_lower for word in ['wlc', 'wireless', 'ap']):
            return 'Wireless Controller'

        return 'Network'

    def extract_site_from_hostname(self, hostname: str) -> str:
        """Extract site/folder name from hostname"""
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
            'Palo Alto Networks': '4',
            'Fortinet': '5',
            'Aruba': '6',
            'HP': '6'
        }

        return cred_map.get(vendor, '1')  # Default to credential ID 1

    def convert_topology_to_inventory(self, topology_data: Dict,
                                      site_mapping: Optional[Dict[str, str]] = None) -> List[Dict]:
        """Convert topology JSON to inventory YAML format"""

        # Group devices by site
        sites = defaultdict(list)

        for device_name, device_data in topology_data.items():
            node_details = device_data.get('node_details', {})
            ip_address = node_details.get('ip', '')
            platform = node_details.get('platform', '')

            # Skip devices without IP addresses
            if not ip_address:
                print(f"Warning: Skipping {device_name} - no IP address")
                continue

            # Extract site information
            if site_mapping and device_name in site_mapping:
                site_name = site_mapping[device_name]
            else:
                site_code = self.extract_site_from_hostname(device_name)
                site_name = f"{site_code} Site"  # Can be customized

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

        # Convert to final inventory format
        inventory = []
        for site_name, devices in sorted(sites.items()):
            # Sort devices within each site
            devices.sort(key=lambda x: x['display_name'])

            site_entry = {
                'folder_name': site_name,
                'sessions': devices
            }
            inventory.append(site_entry)

        return inventory

    def load_topology_json(self, json_file: str) -> Dict:
        """Load topology JSON file"""
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise Exception(f"Failed to load topology JSON: {e}")

    def save_inventory_yaml(self, inventory_data: List[Dict], yaml_file: str):
        """Save inventory to YAML file"""
        try:
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(inventory_data, f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)
        except Exception as e:
            raise Exception(f"Failed to save inventory YAML: {e}")

    def load_site_mapping(self, mapping_file: str) -> Optional[Dict[str, str]]:
        """Load optional site mapping file (JSON)"""
        try:
            if Path(mapping_file).exists():
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load site mapping: {e}")
        return None

    def generate_site_mapping_template(self, topology_data: Dict, output_file: str):
        """Generate a site mapping template for customization"""
        site_mapping = {}

        for device_name in topology_data.keys():
            site_code = self.extract_site_from_hostname(device_name)
            site_mapping[device_name] = f"{site_code} - Custom Site Name"

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(site_mapping, f, indent=2, sort_keys=True)
            print(f"Site mapping template saved to: {output_file}")
        except Exception as e:
            print(f"Warning: Could not save site mapping template: {e}")

    def print_conversion_summary(self, inventory_data: List[Dict]):
        """Print summary of the conversion"""
        total_devices = sum(len(site['sessions']) for site in inventory_data)

        print(f"\n=== CONVERSION SUMMARY ===")
        print(f"Total sites: {len(inventory_data)}")
        print(f"Total devices: {total_devices}")

        # Vendor breakdown
        vendor_counts = defaultdict(int)
        device_type_counts = defaultdict(int)

        for site in inventory_data:
            for device in site['sessions']:
                vendor = device.get('Vendor', 'Unknown')
                device_type = device.get('DeviceType', 'Unknown')
                vendor_counts[vendor] += 1
                device_type_counts[device_type] += 1

        print(f"\n=== VENDOR BREAKDOWN ===")
        for vendor, count in sorted(vendor_counts.items()):
            print(f"  {vendor}: {count} devices")

        print(f"\n=== DEVICE TYPE BREAKDOWN ===")
        for device_type, count in sorted(device_type_counts.items()):
            print(f"  {device_type}: {count} devices")

        print(f"\n=== SITE BREAKDOWN ===")
        for site in inventory_data:
            site_name = site['folder_name']
            device_count = len(site['sessions'])
            print(f"  {site_name}: {device_count} devices")


def main():
    """Main conversion function"""
    parser = argparse.ArgumentParser(
        description="Convert Secure Cartography topology JSON to sessions.yaml inventory"
    )
    parser.add_argument(
        "input_json",
        help="Input topology JSON file from Secure Cartography"
    )
    parser.add_argument(
        "-o", "--output",
        default="sessions.yaml",
        help="Output inventory YAML file (default: sessions.yaml)"
    )
    parser.add_argument(
        "--site-mapping",
        help="Optional JSON file mapping device names to custom site names"
    )
    parser.add_argument(
        "--generate-site-template",
        help="Generate site mapping template file and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show conversion results without saving output file"
    )

    args = parser.parse_args()

    # Validate input file
    if not Path(args.input_json).exists():
        print(f"Error: Input file not found: {args.input_json}")
        return 1

    try:
        # Initialize converter
        converter = TopologyToInventoryConverter()

        # Load topology data
        print(f"Loading topology data from: {args.input_json}")
        topology_data = converter.load_topology_json(args.input_json)

        if not topology_data:
            print("Error: No topology data found in input file")
            return 1

        print(f"Found {len(topology_data)} devices in topology")

        # Generate site mapping template if requested
        if args.generate_site_template:
            converter.generate_site_mapping_template(topology_data, args.generate_site_template)
            print(f"Edit the site mapping file and re-run with --site-mapping {args.generate_site_template}")
            return 0

        # Load site mapping if provided
        site_mapping = None
        if args.site_mapping:
            print(f"Loading site mapping from: {args.site_mapping}")
            site_mapping = converter.load_site_mapping(args.site_mapping)

        # Convert topology to inventory
        print("Converting topology to inventory format...")
        inventory_data = converter.convert_topology_to_inventory(topology_data, site_mapping)

        if not inventory_data:
            print("Error: No valid devices found for inventory")
            return 1

        # Print conversion summary
        converter.print_conversion_summary(inventory_data)

        # Save or display results
        if args.dry_run:
            print(f"\n=== DRY RUN - YAML OUTPUT ===")
            print(yaml.dump(inventory_data, default_flow_style=False,
                            allow_unicode=True, sort_keys=False))
        else:
            print(f"\nSaving inventory to: {args.output}")
            converter.save_inventory_yaml(inventory_data, args.output)
            print("Conversion completed successfully!")

            # Provide usage hints
            print(f"\nNext steps:")
            print(f"1. Review and edit {args.output} as needed")
            print(f"2. Verify credential IDs match your authentication system")
            print(f"3. Test with your collection pipeline")
            print(f"4. Use gap analysis to identify needed collection jobs")

        return 0

    except Exception as e:
        print(f"Error during conversion: {e}")
        return 1


if __name__ == "__main__":
    exit(main())