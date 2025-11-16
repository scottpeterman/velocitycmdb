#!/usr/bin/env python3
"""
Assets DB to sessions.yaml Exporter
Exports device inventory from assets.db to sessions.yaml format
Compatible with batch_spn.py and collection pipeline
"""

import sqlite3
import yaml
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict


class DBToSessionsExporter:
    """Export assets.db to sessions.yaml format"""

    def __init__(self, db_path: str):
        self.db_path = db_path

        # Vendor to credential ID mapping
        self.vendor_cred_map = {
            'Cisco': '1',
            'Arista': '2',
            'Juniper': '3',
            'Palo Alto Networks': '4',
            'Fortinet': '5',
            'Aruba': '6',
            'HP': '6'
        }

    def get_credential_id(self, vendor_name: str) -> str:
        """Map vendor name to credential ID"""
        # Try exact match first
        if vendor_name in self.vendor_cred_map:
            return self.vendor_cred_map[vendor_name]

        # Try partial matches
        vendor_lower = vendor_name.lower()
        for key, cred_id in self.vendor_cred_map.items():
            if key.lower() in vendor_lower:
                return cred_id

        # Default to credential ID 1
        return '1'

    def load_devices_from_db(self,
                             vendor_filter: Optional[str] = None,
                             site_filter: Optional[str] = None,
                             has_ip_only: bool = True) -> List[Dict]:
        """
        Load devices from assets.db

        Returns devices in sessions.yaml-compatible format
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build query with all relevant joins
        query = """
        SELECT 
            d.id,
            d.name as display_name,
            COALESCE(d.management_ip, d.ipv4_address) as host,
            v.name as vendor,
            v.short_name as vendor_short,
            d.model,
            d.os_version as software_version,
            dt.name as device_type,
            dr.name as role,
            s.code as site_code,
            s.name as site_name,
            ds.serial
        FROM devices d
        LEFT JOIN vendors v ON d.vendor_id = v.id
        LEFT JOIN device_types dt ON d.device_type_id = dt.id
        LEFT JOIN device_roles dr ON d.role_id = dr.id
        LEFT JOIN sites s ON d.site_code = s.code
        LEFT JOIN (
            SELECT device_id, serial 
            FROM device_serials 
            WHERE is_primary = 1
        ) ds ON d.id = ds.device_id
        WHERE 1=1
        """

        params = []

        # Filter by vendor
        if vendor_filter:
            query += " AND (LOWER(v.name) LIKE ? OR LOWER(v.short_name) LIKE ?)"
            vendor_pattern = f"%{vendor_filter.lower()}%"
            params.extend([vendor_pattern, vendor_pattern])

        # Filter by site
        if site_filter:
            query += " AND (LOWER(s.code) LIKE ? OR LOWER(s.name) LIKE ?)"
            site_pattern = f"%{site_filter.lower()}%"
            params.extend([site_pattern, site_pattern])

        # Only devices with IPs
        if has_ip_only:
            query += " AND (d.management_ip IS NOT NULL OR d.ipv4_address IS NOT NULL)"

        query += " ORDER BY s.name, d.name"

        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()

            devices = []
            for row in rows:
                # Skip devices without IP
                if not row['host']:
                    continue

                # Use vendor name or fallback
                vendor = row['vendor'] or 'Unknown'

                device = {
                    'DeviceType': row['device_type'] or row['role'] or 'Network',
                    'Model': row['model'] or '',
                    'SerialNumber': row['serial'] or '',
                    'SoftwareVersion': row['software_version'] or '',
                    'Vendor': vendor,
                    'credsid': self.get_credential_id(vendor),
                    'display_name': row['display_name'],
                    'host': row['host'],
                    'port': '22'
                }

                # Add site information for grouping
                device['_site_code'] = row['site_code'] or 'UNKNOWN'
                device['_site_name'] = row['site_name'] or 'Unknown Site'

                devices.append(device)

            conn.close()
            return devices

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            conn.close()
            return []

    def group_devices_by_site(self, devices: List[Dict]) -> List[Dict]:
        """
        Group devices by site into sessions.yaml folder structure
        """
        # Group by site
        sites = defaultdict(list)

        for device in devices:
            site_code = device.pop('_site_code')
            site_name = device.pop('_site_name')

            # Use site name as folder name
            folder_key = f"{site_name}"
            sites[folder_key].append(device)

        # Convert to sessions.yaml format
        sessions = []
        for folder_name, folder_devices in sorted(sites.items()):
            # Sort devices within folder
            folder_devices.sort(key=lambda x: x['display_name'])

            sessions.append({
                'folder_name': folder_name,
                'sessions': folder_devices
            })

        return sessions

    def export_to_yaml(self,
                       output_file: str,
                       vendor_filter: Optional[str] = None,
                       site_filter: Optional[str] = None,
                       has_ip_only: bool = True):
        """
        Export database to sessions.yaml format
        """
        print(f"Loading devices from {self.db_path}...")

        devices = self.load_devices_from_db(
            vendor_filter=vendor_filter,
            site_filter=site_filter,
            has_ip_only=has_ip_only
        )

        if not devices:
            print("No devices found matching criteria")
            return False

        print(f"Found {len(devices)} devices")

        # Group by site
        sessions_data = self.group_devices_by_site(devices)

        # Write to YAML
        print(f"Writing to {output_file}...")
        with open(output_file, 'w') as f:
            yaml.dump(sessions_data, f,
                      default_flow_style=False,
                      allow_unicode=True,
                      sort_keys=False,
                      width=120)

        print(f"✓ Export complete!")
        self.print_summary(sessions_data)

        return True

    def print_summary(self, sessions_data: List[Dict]):
        """Print export summary"""
        total_devices = sum(len(folder['sessions']) for folder in sessions_data)

        # Count by vendor
        vendor_counts = defaultdict(int)
        for folder in sessions_data:
            for device in folder['sessions']:
                vendor = device.get('Vendor', 'Unknown')
                vendor_counts[vendor] += 1

        print(f"\n{'=' * 60}")
        print("Export Summary")
        print(f"{'=' * 60}")
        print(f"Total sites/folders: {len(sessions_data)}")
        print(f"Total devices: {total_devices}")

        print(f"\nVendor breakdown:")
        for vendor, count in sorted(vendor_counts.items()):
            print(f"  {vendor}: {count} devices")

        print(f"\nSite breakdown:")
        for folder in sessions_data:
            count = len(folder['sessions'])
            print(f"  {folder['folder_name']}: {count} devices")

        print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Export assets.db to sessions.yaml format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export all devices
  python db_to_sessions.py assets.db -o sessions.yaml

  # Export only Juniper devices
  python db_to_sessions.py assets.db -o sessions_juniper.yaml --vendor juniper

  # Export only IAD site
  python db_to_sessions.py assets.db -o sessions_iad.yaml --site iad

  # Export Cisco devices from IAD site
  python db_to_sessions.py assets.db -o sessions_cisco_iad.yaml --vendor cisco --site iad

  # Include devices without IPs (not recommended for automation)
  python db_to_sessions.py assets.db -o sessions_all.yaml --include-no-ip

Output Format:
  Generates YAML file compatible with batch_spn.py and collection scripts:

  - folder_name: IAD1 Site
    sessions:
    - DeviceType: Switch
      Model: DCS-7280SRA-48C6
      SerialNumber: JPE12345678
      SoftwareVersion: 4.23.3M
      Vendor: Arista
      credsid: '2'
      display_name: tor2-101.iad1
      host: 10.3.210.5
      port: '22'
        """
    )

    # Input/Output
    parser.add_argument('db_file',
                        help='Path to assets.db database file')
    parser.add_argument('-o', '--output',
                        default='sessions.yaml',
                        help='Output YAML file (default: sessions.yaml)')

    # Filters
    parser.add_argument('--vendor',
                        help='Filter by vendor (substring match, e.g., "cisco", "juniper")')
    parser.add_argument('--site',
                        help='Filter by site code or name (substring match, e.g., "iad", "fra")')
    parser.add_argument('--include-no-ip', action='store_true',
                        help='Include devices without management IP (default: exclude)')

    # Output control
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be exported without writing file')

    args = parser.parse_args()

    # Validate database exists
    if not Path(args.db_file).exists():
        print(f"Error: Database file not found: {args.db_file}")
        return 1

    try:
        exporter = DBToSessionsExporter(args.db_file)

        if args.dry_run:
            print("DRY RUN MODE - No file will be written")
            print(f"Would export to: {args.output}")
            if args.vendor:
                print(f"Vendor filter: {args.vendor}")
            if args.site:
                print(f"Site filter: {args.site}")
            print()

        success = exporter.export_to_yaml(
            output_file=args.output if not args.dry_run else '/dev/null',
            vendor_filter=args.vendor,
            site_filter=args.site,
            has_ip_only=not args.include_no_ip
        )

        if success and not args.dry_run:
            print(f"\nNext steps:")
            print(f"1. Review {args.output}")
            print(f"2. Update credential environment variables (CRED_X_USER/CRED_X_PASS)")
            print(f"3. Use with batch_spn.py for device collection")
            print(f"\nExample usage:")
            print(f"  python batch_spn.py {args.output} --vendor juniper -c 'show version' -o version")

        return 0 if success else 1

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())