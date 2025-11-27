#!/usr/bin/env python3
"""
Re-baseline script for network device configurations.
Clears change history and resets baseline captures.
"""

import sqlite3
import argparse
import shutil
from pathlib import Path
from datetime import datetime

DB_PATH = 'assets.db'
DIFF_BASE_DIR = Path('pcng')  # Adjust this to match your setup


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def delete_diff_files(diff_paths):
    """Delete diff files and clean up empty directories"""
    deleted_files = 0
    deleted_dirs = 0

    for diff_path_str in diff_paths:
        if not diff_path_str:
            continue

        # Construct full path
        diff_path = Path(diff_path_str)
        if not diff_path.is_absolute():
            diff_path = DIFF_BASE_DIR / diff_path

        try:
            if diff_path.exists():
                diff_path.unlink()
                deleted_files += 1

                # Try to clean up empty parent directories
                parent = diff_path.parent
                while parent != DIFF_BASE_DIR and parent.exists():
                    try:
                        if not any(parent.iterdir()):  # Directory is empty
                            parent.rmdir()
                            deleted_dirs += 1
                            parent = parent.parent
                        else:
                            break
                    except OSError:
                        break
        except Exception as e:
            print(f"  Warning: Could not delete {diff_path}: {e}")

    return deleted_files, deleted_dirs


def rebaseline_device(device_id, cleanup_files=True):
    """Re-baseline a specific device"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Get device info
        cursor.execute("SELECT name FROM devices WHERE id = ?", (device_id,))
        device = cursor.fetchone()

        if not device:
            print(f"Error: Device ID {device_id} not found")
            return False

        print(f"Re-baselining device: {device['name']} (ID: {device_id})")

        # Get diff paths before deleting records
        if cleanup_files:
            cursor.execute("""
                SELECT diff_path 
                FROM capture_changes 
                WHERE device_id = ? AND diff_path IS NOT NULL
            """, (device_id,))
            diff_paths = [row['diff_path'] for row in cursor.fetchall()]

        # Delete change records for this device
        cursor.execute("DELETE FROM capture_changes WHERE device_id = ?", (device_id,))
        deleted_changes = cursor.rowcount

        conn.commit()

        print(f"  - Deleted {deleted_changes} change records")

        # Delete diff files
        if cleanup_files and diff_paths:
            deleted_files, deleted_dirs = delete_diff_files(diff_paths)
            print(f"  - Deleted {deleted_files} diff files")
            if deleted_dirs > 0:
                print(f"  - Cleaned up {deleted_dirs} empty directories")

        print(f"  - Device will be re-baselined on next capture")

        return True


def rebaseline_all(cleanup_files=True):
    """Re-baseline all devices"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Get count of changes
        cursor.execute("SELECT COUNT(*) as count FROM capture_changes")
        total_changes = cursor.fetchone()['count']

        # Get count of devices affected
        cursor.execute("SELECT COUNT(DISTINCT device_id) as count FROM capture_changes")
        affected_devices = cursor.fetchone()['count']

        print(f"Re-baselining all devices...")
        print(f"  - Total change records: {total_changes}")
        print(f"  - Devices affected: {affected_devices}")

        # Get all diff paths before deleting records
        if cleanup_files:
            cursor.execute("""
                SELECT diff_path 
                FROM capture_changes 
                WHERE diff_path IS NOT NULL
            """)
            diff_paths = [row['diff_path'] for row in cursor.fetchall()]

        # Delete all change records
        cursor.execute("DELETE FROM capture_changes")

        conn.commit()

        print(f"✓ All change history cleared")

        # Delete diff files
        if cleanup_files and diff_paths:
            deleted_files, deleted_dirs = delete_diff_files(diff_paths)
            print(f"✓ Deleted {deleted_files} diff files")
            if deleted_dirs > 0:
                print(f"✓ Cleaned up {deleted_dirs} empty directories")

        print(f"✓ All devices will be re-baselined on next capture")

        return True


def list_devices_with_changes():
    """List all devices that have change records"""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                d.id,
                d.name,
                d.site_code,
                COUNT(cc.id) as change_count,
                MAX(cc.detected_at) as last_change
            FROM devices d
            LEFT JOIN capture_changes cc ON d.id = cc.device_id
            GROUP BY d.id, d.name, d.site_code
            HAVING change_count > 0
            ORDER BY change_count DESC
        """)

        devices = cursor.fetchall()

        if not devices:
            print("No devices with change history found")
            return

        print(f"\nDevices with change history:")
        print(f"{'ID':<6} {'Device Name':<30} {'Site':<10} {'Changes':<10} {'Last Change'}")
        print("-" * 80)

        for device in devices:
            print(f"{device['id']:<6} {device['name']:<30} {device['site_code'] or 'N/A':<10} "
                  f"{device['change_count']:<10} {device['last_change']}")


def main():
    parser = argparse.ArgumentParser(
        description='Re-baseline network device configurations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all devices with changes
  python rebaseline.py --list

  # Re-baseline a specific device
  python rebaseline.py --device 66

  # Re-baseline all devices
  python rebaseline.py --all

  # Re-baseline without deleting diff files
  python rebaseline.py --all --no-cleanup
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--device', '-d', type=int, metavar='DEVICE_ID',
                       help='Re-baseline a specific device by ID')
    group.add_argument('--all', '-a', action='store_true',
                       help='Re-baseline all devices')
    group.add_argument('--list', '-l', action='store_true',
                       help='List all devices with change history')

    parser.add_argument('--confirm', '-y', action='store_true',
                        help='Skip confirmation prompt')
    parser.add_argument('--no-cleanup', action='store_true',
                        help='Do not delete diff files from filesystem (only clear database)')

    args = parser.parse_args()

    # Handle list command
    if args.list:
        list_devices_with_changes()
        return

    # Confirmation prompt
    if not args.confirm:
        cleanup_msg = " and diff files" if not args.no_cleanup else ""
        if args.all:
            response = input(f"WARNING: This will delete ALL change history{cleanup_msg}. Continue? (yes/no): ")
        else:
            response = input(
                f"This will delete change history{cleanup_msg} for device {args.device}. Continue? (yes/no): ")

        if response.lower() not in ['yes', 'y']:
            print("Aborted.")
            return

    # Execute re-baseline
    cleanup_files = not args.no_cleanup

    if args.device:
        success = rebaseline_device(args.device, cleanup_files)
    elif args.all:
        success = rebaseline_all(cleanup_files)

    if success:
        print("\n✓ Re-baseline complete!")
    else:
        print("\n✗ Re-baseline failed")


if __name__ == '__main__':
    main()