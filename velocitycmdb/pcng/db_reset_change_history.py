#!/usr/bin/env python3
"""
Reset change tracking tables and diff files for testing
"""

import sqlite3
import shutil
from pathlib import Path
import click


@click.command()
@click.option('--db-path', default='assets.db', help='Path to SQLite database')
@click.option('--diff-dir', default='diffs', help='Diffs directory to clean')
@click.option('--confirm', is_flag=True, help='Confirm deletion without prompting')
def reset_changes(db_path, diff_dir, confirm):
    """Delete all change tracking data and diff files to re-test"""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get counts before deletion
    cursor.execute("SELECT COUNT(*) FROM capture_changes")
    changes_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
    snapshots_count = cursor.fetchone()[0]

    # Check diff directory
    diff_path = Path(diff_dir)
    diff_exists = diff_path.exists()
    diff_files = []
    if diff_exists:
        diff_files = list(diff_path.rglob("*.diff"))

    print(f"Database: {db_path}")
    print(f"Current records:")
    print(f"  - Capture changes: {changes_count}")
    print(f"  - Snapshots: {snapshots_count}")
    print(f"\nDiff directory: {diff_dir}")
    print(f"  - Exists: {diff_exists}")
    print(f"  - Diff files: {len(diff_files)}")

    if changes_count == 0 and snapshots_count == 0 and not diff_files:
        print("\nNothing to delete!")
        return

    if not confirm:
        print("\nThis will delete:")
        print(f"  - {changes_count} change records")
        print(f"  - {snapshots_count} snapshots")
        print(f"  - {len(diff_files)} diff files")
        print(f"  - Entire {diff_dir}/ directory")
        response = input("\nProceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return

    # Delete database records
    print("\nDeleting database records...")
    cursor.execute("DELETE FROM capture_changes")
    cursor.execute("DELETE FROM capture_snapshots")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('capture_changes', 'capture_snapshots')")
    conn.commit()

    # Delete diff directory
    if diff_exists:
        print(f"Deleting {diff_dir}/ directory...")
        shutil.rmtree(diff_path)

    # Verify
    cursor.execute("SELECT COUNT(*) FROM capture_changes")
    changes_after = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
    snapshots_after = cursor.fetchone()[0]

    print(f"\nCompleted:")
    print(f"  ✓ Deleted {changes_count} change records")
    print(f"  ✓ Deleted {snapshots_count} snapshots")
    print(f"  ✓ Deleted {len(diff_files)} diff files")
    print(f"  ✓ Removed {diff_dir}/ directory")
    print(f"\nVerification: {changes_after} changes, {snapshots_after} snapshots in DB")
    print("\nReady for fresh run:")
    print("  python db_load_captures.py --captures-dir Anguis/capture --show-changes")

    conn.close()


if __name__ == '__main__':
    reset_changes()