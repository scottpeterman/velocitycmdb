#!/usr/bin/env python3
"""
Fix normalized_name in devices table to match capture file format
Adds dot before site suffix: tor2-103fra1 -> tor2-103
"""

import sqlite3
import sys
import re


def fix_normalized_names(db_path='assets.db', dry_run=True):
    """Fix normalized names to include dot before site suffix"""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all devices
    cursor.execute("""
        SELECT id, name, normalized_name, site_code 
        FROM devices 
        ORDER BY id
    """)

    devices = cursor.fetchall()

    print(f"\n{'=' * 80}")
    print(f"FIXING NORMALIZED NAMES")
    print(f"{'=' * 80}\n")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will update database)'}\n")

    updates = []

    for device in devices:
        old_name = device['normalized_name']
        site_code = device['site_code']

        if not site_code:
            continue

        # Check if normalized_name ends with site code (no dot)
        # Pattern: ends with .siteXX or just siteXX
        site_lower = site_code.lower()

        # If it already has the dot, skip
        if old_name.endswith(f".{site_lower}"):
            continue

        # If it ends with site code (no dot), add the dot
        if old_name.endswith(site_lower):
            # Insert dot before site code
            new_name = old_name[:-len(site_lower)] + f".{site_lower}"
            updates.append((device['id'], old_name, new_name))

    if not updates:
        print("No devices need fixing - all normalized names are correct!")
        conn.close()
        return

    print(f"Found {len(updates)} devices to fix:\n")
    print(f"{'ID':<6} {'Current':<35} {'Fixed':<35}")
    print(f"{'-' * 80}")

    for device_id, old_name, new_name in updates:
        print(f"{device_id:<6} {old_name:<35} {new_name:<35}")

    if dry_run:
        print(f"\n{'=' * 80}")
        print(f"DRY RUN - No changes made")
        print(f"Run with --apply to actually update the database")
        print(f"{'=' * 80}\n")
    else:
        print(f"\nApplying updates...")
        for device_id, old_name, new_name in updates:
            try:
                cursor.execute("""
                    UPDATE devices 
                    SET normalized_name = ? 
                    WHERE id = ?
                """, (new_name, device_id))
                print(f"  ✓ Updated device {device_id}")
            except sqlite3.IntegrityError as e:
                print(f"  ✗ Failed to update device {device_id}: {e}")

        conn.commit()
        print(f"\n{'=' * 80}")
        print(f"✓ Successfully updated {len(updates)} devices")
        print(f"{'=' * 80}\n")

    conn.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix normalized_name format in devices table'
    )
    parser.add_argument('--db-path', default='assets.db',
                        help='Path to database (default: assets.db)')
    parser.add_argument('--apply', action='store_true',
                        help='Actually apply changes (default is dry-run)')

    args = parser.parse_args()

    fix_normalized_names(args.db_path, dry_run=not args.apply)