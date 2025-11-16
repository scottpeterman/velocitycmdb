#!/usr/bin/env python3
"""
Bulk Device Deletion by Site

Safely removes all devices from a specified site in the assets database.
Handles all related records in the correct order to maintain referential integrity.

Usage:
    python delete_site_devices.py <site_code> [--confirm]

Example:
    python delete_site_devices.py NYC --confirm
"""

import sqlite3
import sys
import argparse
from datetime import datetime
from contextlib import contextmanager


@contextmanager
def get_db_connection(db_path='assets.db'):
    """Context manager for database connections"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_site_devices(conn, site_code):
    """
    Get all devices for a given site

    Returns:
        List of device dictionaries with id, name, and related record counts
    """
    cursor = conn.cursor()

    # Get devices with counts of related records
    cursor.execute("""
        SELECT 
            d.id,
            d.name,
            d.normalized_name,
            COUNT(DISTINCT dcc.id) as capture_count,
            COUNT(DISTINCT fe.id) as fingerprint_count,
            COUNT(DISTINCT ds.id) as serial_count,
            COUNT(DISTINCT sm.id) as stack_member_count,
            COUNT(DISTINCT c.id) as component_count
        FROM devices d
        LEFT JOIN device_captures_current dcc ON d.id = dcc.device_id
        LEFT JOIN fingerprint_extractions fe ON d.id = fe.device_id
        LEFT JOIN device_serials ds ON d.id = ds.device_id
        LEFT JOIN stack_members sm ON d.id = sm.device_id
        LEFT JOIN components c ON d.id = c.device_id
        WHERE d.site_code = ?
        GROUP BY d.id, d.name, d.normalized_name
        ORDER BY d.name
    """, (site_code,))

    return [dict(row) for row in cursor.fetchall()]


def delete_device_records(conn, device_id):
    """
    Delete all records related to a device in the correct order

    Returns:
        Dictionary with counts of deleted records
    """
    cursor = conn.cursor()
    counts = {}

    # Delete in correct order to respect foreign key constraints

    # 1. Delete capture snapshots (referenced by capture_changes)
    cursor.execute("DELETE FROM capture_snapshots WHERE device_id = ?", (device_id,))
    counts['capture_snapshots'] = cursor.rowcount

    # 2. Delete capture changes (references capture_snapshots and devices)
    cursor.execute("DELETE FROM capture_changes WHERE device_id = ?", (device_id,))
    counts['capture_changes'] = cursor.rowcount

    # 3. Delete current captures
    cursor.execute("DELETE FROM device_captures_current WHERE device_id = ?", (device_id,))
    counts['device_captures_current'] = cursor.rowcount

    # 4. Delete fingerprint extractions
    cursor.execute("DELETE FROM fingerprint_extractions WHERE device_id = ?", (device_id,))
    counts['fingerprint_extractions'] = cursor.rowcount

    # 5. Delete components
    cursor.execute("DELETE FROM components WHERE device_id = ?", (device_id,))
    counts['components'] = cursor.rowcount

    # 6. Delete stack members
    cursor.execute("DELETE FROM stack_members WHERE device_id = ?", (device_id,))
    counts['stack_members'] = cursor.rowcount

    # 7. Delete device serials
    cursor.execute("DELETE FROM device_serials WHERE device_id = ?", (device_id,))
    counts['device_serials'] = cursor.rowcount

    # 8. Finally delete the device itself
    cursor.execute("DELETE FROM devices WHERE id = ?", (device_id,))
    counts['devices'] = cursor.rowcount

    return counts


def verify_site_exists(conn, site_code):
    """Check if site exists in database"""
    cursor = conn.cursor()
    cursor.execute("SELECT code, name FROM sites WHERE code = ?", (site_code,))
    site = cursor.fetchone()
    return dict(site) if site else None


def main():
    parser = argparse.ArgumentParser(
        description='Bulk delete all devices from a site',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview what would be deleted)
  python delete_site_devices.py NYC

  # Actually delete devices
  python delete_site_devices.py NYC --confirm

  # Use custom database path
  python delete_site_devices.py NYC --confirm --db /path/to/assets.db
        """
    )
    parser.add_argument('site_code', help='Site code to delete devices from')
    parser.add_argument('--confirm', action='store_true',
                        help='Actually perform deletion (without this, script runs in dry-run mode)')
    parser.add_argument('--db', default='assets.db',
                        help='Path to database file (default: assets.db)')

    args = parser.parse_args()

    try:
        with get_db_connection(args.db) as conn:
            # Verify site exists
            site = verify_site_exists(conn, args.site_code)
            if not site:
                print(f"ERROR: Site '{args.site_code}' not found in database")
                return 1

            print(f"Site: {site['name']} ({site['code']})")
            print("=" * 70)

            # Get devices for site
            devices = get_site_devices(conn, args.site_code)

            if not devices:
                print(f"\nNo devices found for site '{args.site_code}'")
                return 0

            print(f"\nFound {len(devices)} device(s) in site '{args.site_code}':")
            print()

            # Display summary
            total_captures = sum(d['capture_count'] for d in devices)
            total_fingerprints = sum(d['fingerprint_count'] for d in devices)
            total_serials = sum(d['serial_count'] for d in devices)
            total_components = sum(d['component_count'] for d in devices)

            for i, device in enumerate(devices, 1):
                print(f"{i}. {device['name']} (ID: {device['id']})")
                print(f"   - Captures: {device['capture_count']}")
                print(f"   - Fingerprints: {device['fingerprint_count']}")
                print(f"   - Serials: {device['serial_count']}")
                print(f"   - Components: {device['component_count']}")
                if device['stack_member_count'] > 0:
                    print(f"   - Stack Members: {device['stack_member_count']}")
                print()

            print("Summary of records to be deleted:")
            print(f"  - Devices: {len(devices)}")
            print(f"  - Captures: {total_captures}")
            print(f"  - Fingerprints: {total_fingerprints}")
            print(f"  - Serials: {total_serials}")
            print(f"  - Components: {total_components}")
            print()

            if not args.confirm:
                print("=" * 70)
                print("DRY RUN MODE - No changes made to database")
                print("Add --confirm flag to actually delete these devices")
                print("=" * 70)
                return 0

            # Confirm deletion
            print("=" * 70)
            print("WARNING: This will permanently delete all listed devices and related data!")
            response = input("Type 'DELETE' to confirm: ")

            if response != 'DELETE':
                print("\nDeletion cancelled")
                return 0

            # Perform deletion
            print("\nDeleting devices...")
            print()

            total_deleted = {
                'devices': 0,
                'capture_snapshots': 0,
                'capture_changes': 0,
                'device_captures_current': 0,
                'fingerprint_extractions': 0,
                'components': 0,
                'stack_members': 0,
                'device_serials': 0
            }

            for i, device in enumerate(devices, 1):
                print(f"[{i}/{len(devices)}] Deleting {device['name']}...", end=' ')

                counts = delete_device_records(conn, device['id'])

                # Accumulate totals
                for key, value in counts.items():
                    total_deleted[key] += value

                print("✓")

            # Commit all changes
            conn.commit()

            print()
            print("=" * 70)
            print("Deletion Complete!")
            print()
            print("Records deleted:")
            for table, count in total_deleted.items():
                if count > 0:
                    print(f"  - {table}: {count}")
            print()
            print(f"Timestamp: {datetime.now().isoformat()}")
            print("=" * 70)

            return 0

    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())