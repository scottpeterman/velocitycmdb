#!/usr/bin/env python3
"""
VelocityCMDB Importer
Imports VelocityMaps discovery results into VelocityCMDB assets database

Usage:
    velocitycmdb_import.py --results-dir /path/to/velocitymaps/tests
    velocitycmdb_import.py --results-dir /path/to/velocitymaps/tests --db-path /custom/path/assets.db
    velocitycmdb_import.py --results-dir /path/to/velocitymaps/tests --dry-run

Author: Scott Peterman
License: GPLv3
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import re


class VendorParser:
    """Parse vendor-specific sysDescr to extract model and OS version"""

    @staticmethod
    def parse_cisco(sysdescr: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse Cisco sysDescr
        Example: "Cisco IOS Software, IOSv Software (VIOS-ADVENTERPRISEK9-M), Version 15.6(2)T"
        """
        model = None
        os_version = None

        # Try to extract version first (works for most formats)
        version_match = re.search(r'Version\s+([\d.()A-Za-z]+)', sysdescr)
        if version_match:
            os_version = version_match.group(1)

        # Try to extract model from parentheses (IOS software string)
        model_match = re.search(r'\(([^)]+)\)', sysdescr)
        if model_match:
            # Make sure it's not a version string
            candidate = model_match.group(1)
            if not re.match(r'^\d', candidate):  # Don't match if starts with digit
                model = candidate

        # Fallback: try to get platform from beginning (physical devices)
        if not model:
            # Look for platform codes like "7206VXR", "2960", "ASR1000", etc.
            platform_match = re.search(r'Cisco\s+([A-Z0-9][\w\-]+)', sysdescr)
            if platform_match:
                candidate = platform_match.group(1)
                # Exclude OS names
                if candidate not in ['IOS', 'NX-OS', 'IOS-XE', 'IOS-XR', 'NXOS']:
                    model = candidate

        return model, os_version

    @staticmethod
    def parse_arista(sysdescr: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse Arista sysDescr
        Example: "Arista Networks EOS version 4.33.1F running on an Arista vEOS-lab"
        """
        model = None
        os_version = None

        # Extract EOS version
        version_match = re.search(r'EOS version\s+([\d.]+\w*)', sysdescr)
        if version_match:
            os_version = version_match.group(1)

        # Extract model/platform
        model_match = re.search(r'running on an Arista\s+([^\s]+)', sysdescr)
        if model_match:
            model = model_match.group(1)
        else:
            # Fallback: look for DCS- prefix (physical switches)
            dcs_match = re.search(r'(DCS-[^\s]+)', sysdescr)
            if dcs_match:
                model = dcs_match.group(1)

        return model, os_version

    @staticmethod
    def parse_juniper(sysdescr: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse Juniper sysDescr
        Example: "Juniper Networks, Inc. srx300 internet router, kernel JUNOS 15.1X49-D170.4"
        """
        model = None
        os_version = None

        # Extract model (usually lowercase platform name)
        model_match = re.search(r'Juniper Networks[^,]*,\s+Inc\.\s+(\S+)', sysdescr)
        if model_match:
            model = model_match.group(1).upper()

        # Extract JUNOS version
        version_match = re.search(r'JUNOS\s+([\d.X\-A-Za-z]+)', sysdescr)
        if version_match:
            os_version = version_match.group(1)

        return model, os_version

    @staticmethod
    def parse_unknown(sysdescr: str) -> Tuple[Optional[str], Optional[str]]:
        """Fallback parser for unknown vendors"""
        # Just return the first 50 chars as model, no OS version
        model = sysdescr[:50] if sysdescr else None
        return model, None

    @classmethod
    def parse(cls, vendor: str, sysdescr: str) -> Tuple[Optional[str], Optional[str]]:
        """Main parsing dispatcher"""
        vendor_lower = vendor.lower()

        if vendor_lower == 'cisco':
            return cls.parse_cisco(sysdescr)
        elif vendor_lower == 'arista':
            return cls.parse_arista(sysdescr)
        elif vendor_lower == 'juniper':
            return cls.parse_juniper(sysdescr)
        else:
            return cls.parse_unknown(sysdescr)


class VelocityCMDBImporter:
    """Import VelocityMaps discovery results into VelocityCMDB"""

    # Vendor name mapping: VelocityMaps → VelocityCMDB
    VENDOR_MAP = {
        'cisco': 'Cisco Systems',
        'arista': 'Arista Networks',
        'juniper': 'Juniper Networks',
    }

    def __init__(self, db_path: str, dry_run: bool = False, remove_domains: List[str] = None):
        self.db_path = db_path
        self.dry_run = dry_run
        self.remove_domains = remove_domains or []
        self.conn = None
        self.stats = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0
        }

    def connect(self):
        """Connect to SQLite database"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            print(f"✓ Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            print(f"✗ Database connection failed: {e}")
            sys.exit(1)

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def clean_hostname(self, hostname: str) -> str:
        """Remove specified domain suffixes from hostname"""
        if not hostname or not self.remove_domains:
            return hostname

        cleaned = hostname
        for domain in self.remove_domains:
            # Remove .domain suffix (case-insensitive)
            suffix = f".{domain.lower()}"
            if cleaned.lower().endswith(suffix):
                cleaned = cleaned[:-len(suffix)]
                break  # Only remove first matching domain

        return cleaned

    def ensure_vendors_exist(self) -> bool:
        """Ensure all required vendors exist in the vendors table"""
        cursor = self.conn.cursor()

        # Define required vendors (VelocityCMDB format)
        required_vendors = [
            ('Arista Networks', 'ARISTA'),
            ('Juniper Networks', 'JUNIPER'),
            ('Cisco Systems', 'Cisco'),
            ('Unknown', 'UNKNOWN')
        ]

        created = []
        for vendor_name, short_name in required_vendors:
            cursor.execute("SELECT id FROM vendors WHERE name = ?", (vendor_name,))
            if cursor.fetchone():
                continue  # Vendor exists

            # Create missing vendor
            if self.dry_run:
                print(f"[DRY RUN] Would create vendor: {vendor_name}")
                created.append(vendor_name)
                continue

            try:
                cursor.execute("""
                    INSERT INTO vendors (name, short_name, description)
                    VALUES (?, ?, ?)
                """, (vendor_name, short_name, f"Auto-created by VelocityMaps import"))
                self.conn.commit()
                created.append(vendor_name)
            except sqlite3.Error as e:
                print(f"✗ Failed to create vendor {vendor_name}: {e}")
                return False

        if created:
            for vendor in created:
                print(f"✓ Created vendor: {vendor}")

        return True

    def ensure_site_exists(self, site_code: str = "IMPORTED") -> bool:
        """Ensure the IMPORTED site exists in the sites table"""
        cursor = self.conn.cursor()

        # Check if site exists
        cursor.execute("SELECT code FROM sites WHERE code = ?", (site_code,))
        if cursor.fetchone():
            return True

        # Create IMPORTED site
        if self.dry_run:
            print(f"[DRY RUN] Would create site: {site_code}")
            return True

        try:
            cursor.execute("""
                INSERT INTO sites (code, name, description)
                VALUES (?, ?, ?)
            """, (site_code, "Imported Devices", "Devices imported from VelocityMaps discovery"))
            self.conn.commit()
            print(f"✓ Created site: {site_code}")
            return True
        except sqlite3.Error as e:
            print(f"✗ Failed to create site {site_code}: {e}")
            return False

    def get_vendor_id(self, vendor_name: str) -> Optional[int]:
        """Get vendor ID from vendors table"""
        cursor = self.conn.cursor()

        # Map VelocityMaps vendor name to VelocityCMDB vendor name
        cmdb_vendor_name = self.VENDOR_MAP.get(vendor_name.lower(), 'Unknown')

        cursor.execute("SELECT id FROM vendors WHERE name = ?", (cmdb_vendor_name,))
        row = cursor.fetchone()

        if row:
            return row['id']

        # In dry-run mode, vendors won't exist yet, return dummy ID
        if self.dry_run:
            return -1

        # Should never happen after ensure_vendors_exist, but handle gracefully
        print(f"⚠️  Warning: Vendor '{cmdb_vendor_name}' not found in database")
        return None

    def find_device(self, hostname: str, management_ip: str) -> Optional[int]:
        """Find existing device by normalized_name or management IP"""
        cursor = self.conn.cursor()

        # Normalize the hostname (lowercase)
        normalized_name = hostname.lower()

        # Try normalized_name first (unique key)
        cursor.execute("SELECT id FROM devices WHERE normalized_name = ?", (normalized_name,))
        row = cursor.fetchone()
        if row:
            return row['id']

        # Try management IP as fallback
        if management_ip:
            cursor.execute("SELECT id FROM devices WHERE management_ip = ?", (management_ip,))
            row = cursor.fetchone()
            if row:
                return row['id']

        # Try ipv4_address as additional fallback
        if management_ip:
            cursor.execute("SELECT id FROM devices WHERE ipv4_address = ?", (management_ip,))
            row = cursor.fetchone()
            if row:
                return row['id']

        return None

    def import_device(self, device_data: Dict) -> bool:
        """Import or update a single device"""
        raw_hostname = device_data.get('hostname')
        if not raw_hostname:
            print("✗ Skipping device: no hostname")
            self.stats['skipped'] += 1
            return False

        # Clean hostname by removing domain suffixes
        hostname = self.clean_hostname(raw_hostname)
        if hostname != raw_hostname:
            print(f"  Cleaned hostname: {raw_hostname} → {hostname}")

        # Extract basic info
        fqdn = device_data.get('fqdn', '')
        management_ip = device_data.get('ip', '')
        vendor_name = device_data.get('vendor', 'unknown')
        sysdescr = device_data.get('sysDescr', '')
        timestamp = device_data.get('timestamp', datetime.now().isoformat())

        # Parse model and OS version from sysDescr
        model, os_version = VendorParser.parse(vendor_name, sysdescr)

        # Get vendor ID
        vendor_id = self.get_vendor_id(vendor_name)
        if vendor_id is None:
            print(f"✗ Skipping {hostname}: couldn't resolve vendor {vendor_name}")
            self.stats['errors'] += 1
            return False

        # Check if device exists
        device_id = self.find_device(hostname, management_ip)

        cursor = self.conn.cursor()

        if device_id:
            # Update existing device
            if self.dry_run:
                print(f"[DRY RUN] Would update device: {hostname} (ID: {device_id})")
                self.stats['updated'] += 1
                return True

            try:
                cursor.execute("""
                    UPDATE devices SET
                        name = ?,
                        ipv4_address = ?,
                        management_ip = ?,
                        vendor_id = ?,
                        model = ?,
                        os_version = ?,
                        timestamp = ?,
                        source_system = 'VelocityMaps'
                    WHERE id = ?
                """, (hostname, management_ip, management_ip, vendor_id, model, os_version, timestamp, device_id))
                self.conn.commit()
                print(f"✓ Updated device: {hostname}")
                self.stats['updated'] += 1
                return True
            except sqlite3.Error as e:
                print(f"✗ Failed to update {hostname}: {e}")
                self.stats['errors'] += 1
                return False
        else:
            # Insert new device
            if self.dry_run:
                print(f"[DRY RUN] Would create device: {hostname}")
                self.stats['created'] += 1
                return True

            try:
                cursor.execute("""
                    INSERT INTO devices (
                        name, normalized_name, ipv4_address, management_ip, vendor_id, model, os_version,
                        site_code, timestamp, source_system
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'IMPORTED', ?, 'VelocityMaps')
                """, (hostname, hostname.lower(), management_ip, management_ip, vendor_id, model, os_version,
                      timestamp))
                self.conn.commit()
                print(f"✓ Created device: {hostname}")
                self.stats['created'] += 1
                return True
            except sqlite3.Error as e:
                print(f"✗ Failed to create {hostname}: {e}")
                self.stats['errors'] += 1
                return False

    def import_from_directory(self, results_dir: str):
        """Import all devices from a VelocityMaps results directory"""
        results_path = Path(results_dir)

        if not results_path.exists():
            print(f"✗ Results directory not found: {results_dir}")
            sys.exit(1)

        print(f"\n{'=' * 80}")
        print(f"VelocityCMDB Importer")
        print(f"{'=' * 80}")
        print(f"Results Directory: {results_dir}")
        print(f"Database: {self.db_path}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        if self.remove_domains:
            print(f"Remove Domains: {', '.join(self.remove_domains)}")
        print(f"{'=' * 80}\n")

        # Ensure required vendors exist
        if not self.ensure_vendors_exist():
            print("✗ Failed to ensure vendors exist")
            sys.exit(1)

        # Ensure IMPORTED site exists
        self.ensure_site_exists()

        # Find all device directories (they contain device.json)
        device_dirs = []
        for item in results_path.iterdir():
            if item.is_dir():
                device_json = item / "device.json"
                if device_json.exists():
                    device_dirs.append(item)

        if not device_dirs:
            print("✗ No device directories found (looking for */device.json)")
            sys.exit(1)

        print(f"Found {len(device_dirs)} devices to import\n")

        # Import each device
        for device_dir in sorted(device_dirs):
            device_json = device_dir / "device.json"

            try:
                with open(device_json, 'r') as f:
                    device_data = json.load(f)
                self.import_device(device_data)
            except json.JSONDecodeError as e:
                print(f"✗ Invalid JSON in {device_json}: {e}")
                self.stats['errors'] += 1
            except Exception as e:
                print(f"✗ Error processing {device_json}: {e}")
                self.stats['errors'] += 1

        # Print summary
        self.print_summary()

    def print_summary(self):
        """Print import summary statistics"""
        print(f"\n{'=' * 80}")
        print("Import Summary")
        print(f"{'=' * 80}")
        print(f"Created:  {self.stats['created']}")
        print(f"Updated:  {self.stats['updated']}")
        print(f"Skipped:  {self.stats['skipped']}")
        print(f"Errors:   {self.stats['errors']}")
        print(f"{'=' * 80}\n")

        if self.dry_run:
            print("NOTE: This was a dry run. No changes were made to the database.")


def get_default_db_path() -> str:
    """Get default VelocityCMDB database path"""
    home = Path.home()
    return str(home / ".velocitycmdb" / "data" / "assets.db")


def main():
    parser = argparse.ArgumentParser(
        description="Import VelocityMaps discovery results into VelocityCMDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import from default VelocityMaps output directory
  %(prog)s --results-dir ~/PycharmProjects/velocitymaps/tests

  # Dry run to preview changes
  %(prog)s --results-dir ~/PycharmProjects/velocitymaps/tests --dry-run

  # Remove domain suffixes from hostnames
  %(prog)s --results-dir ~/PycharmProjects/velocitymaps/tests --remove-domains "kentik.com,kentik.eu"

  # Specify custom database path
  %(prog)s --results-dir /path/to/results --db-path /custom/assets.db
        """
    )

    parser.add_argument(
        '--results-dir',
        required=True,
        help='Path to VelocityMaps results directory (contains device folders with device.json)'
    )

    parser.add_argument(
        '--db-path',
        default=get_default_db_path(),
        help=f'Path to VelocityCMDB assets.db (default: {get_default_db_path()})'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying the database'
    )

    parser.add_argument(
        '--remove-domains',
        help='Comma-separated list of domain suffixes to remove from hostnames (e.g., "kentik.com,kentik.eu")'
    )

    args = parser.parse_args()

    # Parse remove-domains argument
    remove_domains = []
    if args.remove_domains:
        remove_domains = [d.strip() for d in args.remove_domains.split(',') if d.strip()]

    # Verify database exists (unless dry run)
    db_path = Path(args.db_path)
    if not args.dry_run and not db_path.exists():
        print(f"✗ Database not found: {args.db_path}")
        print("  Create the database first or use --dry-run to test")
        sys.exit(1)

    # Run import
    importer = VelocityCMDBImporter(args.db_path, dry_run=args.dry_run, remove_domains=remove_domains)
    try:
        importer.connect()
        importer.import_from_directory(args.results_dir)
    finally:
        importer.close()


if __name__ == "__main__":
    main()