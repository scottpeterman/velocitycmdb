#!/usr/bin/env python3
"""Remove all captures of a specific type from the database and filesystem"""

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / '.velocitycmdb/data/assets.db'
CAPTURE_DIR = Path.home() / '.velocitycmdb/data/capture'


def get_capture_types(conn):
    """Get list of existing capture types"""
    cur = conn.execute("""
        SELECT DISTINCT capture_type, COUNT(*) as count 
        FROM device_captures_current 
        GROUP BY capture_type 
        ORDER BY capture_type
    """)
    return cur.fetchall()


def delete_capture_type(conn, capture_type, dry_run=False):
    """Delete all records for a capture type"""

    # Get counts first
    counts = {}

    cur = conn.execute("""
        SELECT COUNT(*) FROM capture_changes 
        WHERE current_snapshot_id IN (
            SELECT id FROM capture_snapshots WHERE capture_type = ?
        ) OR previous_snapshot_id IN (
            SELECT id FROM capture_snapshots WHERE capture_type = ?
        )
    """, (capture_type, capture_type))
    counts['capture_changes'] = cur.fetchone()[0]

    cur = conn.execute(
        "SELECT COUNT(*) FROM capture_snapshots WHERE capture_type = ?",
        (capture_type,)
    )
    counts['capture_snapshots'] = cur.fetchone()[0]

    cur = conn.execute(
        "SELECT COUNT(*) FROM device_captures_current WHERE capture_type = ?",
        (capture_type,)
    )
    counts['device_captures_current'] = cur.fetchone()[0]

    # Check filesystem
    fs_path = CAPTURE_DIR / capture_type
    file_count = len(list(fs_path.glob('*.txt'))) if fs_path.exists() else 0

    print(f"\nCapture type: {capture_type}")
    print(f"  capture_changes:        {counts['capture_changes']} rows")
    print(f"  capture_snapshots:      {counts['capture_snapshots']} rows")
    print(f"  device_captures_current: {counts['device_captures_current']} rows")
    print(f"  files on disk:          {file_count} files")

    if dry_run:
        print("  [DRY RUN - no changes made]")
        return counts

    # Delete in order (respect foreign keys)
    conn.execute("""
        DELETE FROM capture_changes 
        WHERE current_snapshot_id IN (
            SELECT id FROM capture_snapshots WHERE capture_type = ?
        ) OR previous_snapshot_id IN (
            SELECT id FROM capture_snapshots WHERE capture_type = ?
        )
    """, (capture_type, capture_type))

    conn.execute(
        "DELETE FROM capture_snapshots WHERE capture_type = ?",
        (capture_type,)
    )

    conn.execute(
        "DELETE FROM device_captures_current WHERE capture_type = ?",
        (capture_type,)
    )

    conn.commit()

    # Clean up files
    if fs_path.exists():
        for f in fs_path.glob('*.txt'):
            f.unlink()
        print(f"  Deleted {file_count} files from {fs_path}")

    print("  ✓ Deleted")
    return counts


def main():
    parser = argparse.ArgumentParser(description='Delete captures by type')
    parser.add_argument('capture_type', nargs='?', help='Capture type to delete (e.g., configs, arp, lldp-detail)')
    parser.add_argument('--list', '-l', action='store_true', help='List available capture types')
    parser.add_argument('--dry-run', '-n', action='store_true', help='Show what would be deleted')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    if args.list or not args.capture_type:
        print("Available capture types:")
        for ct, count in get_capture_types(conn):
            print(f"  {ct}: {count} devices")
        return 0

    # Verify capture type exists
    existing = [ct for ct, _ in get_capture_types(conn)]
    if args.capture_type not in existing:
        print(f"Error: '{args.capture_type}' not found")
        print(f"Available: {', '.join(existing)}")
        return 1

    if args.dry_run:
        delete_capture_type(conn, args.capture_type, dry_run=True)
        return 0

    if not args.yes:
        resp = input(f"Delete all '{args.capture_type}' captures? [y/N] ")
        if resp.lower() != 'y':
            print("Aborted")
            return 0

    delete_capture_type(conn, args.capture_type)
    conn.close()
    return 0


if __name__ == "__main__":
    exit(main())