#!/usr/bin/env python3
"""
Simple script to rebuild the capture_fts index
Run this after adding the FTS triggers to populate the index with existing data
"""

import sqlite3
import sys


def rebuild_fts(db_path='assets.db'):
    """Rebuild the capture_fts index from existing capture_snapshots"""

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current state
    print("\n=== Before Rebuild ===")
    cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
    snapshot_count = cursor.fetchone()[0]
    print(f"Snapshots in database: {snapshot_count}")

    cursor.execute("SELECT COUNT(*) FROM capture_fts")
    fts_count_before = cursor.fetchone()[0]
    print(f"FTS entries before: {fts_count_before}")

    if snapshot_count == 0:
        print("\nNo snapshots to index. Load some captures first!")
        conn.close()
        return

    # Rebuild
    print("\n=== Rebuilding FTS Index ===")
    print("Clearing existing FTS data...")
    cursor.execute("DELETE FROM capture_fts")

    print("Indexing snapshots...")
    cursor.execute("""
        INSERT INTO capture_fts(rowid, content)
        SELECT id, content FROM capture_snapshots
    """)

    indexed = cursor.rowcount
    conn.commit()

    # Verify
    print("\n=== After Rebuild ===")
    cursor.execute("SELECT COUNT(*) FROM capture_fts")
    fts_count_after = cursor.fetchone()[0]
    print(f"FTS entries after: {fts_count_after}")
    print(f"Indexed: {indexed} snapshots")

    if fts_count_after == snapshot_count:
        print("\n✅ SUCCESS! FTS index is now in sync with snapshots")
    else:
        print(f"\n⚠️  WARNING: Mismatch - {snapshot_count} snapshots but {fts_count_after} FTS entries")

    # Test search
    print("\n=== Testing FTS Search ===")
    test_terms = ['interface', 'vlan', 'cisco', 'router']

    for term in test_terms:
        cursor.execute("SELECT COUNT(*) FROM capture_fts WHERE content MATCH ?", (term,))
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"✓ '{term}': {count} results")
            break
    else:
        print("No test results found - try searching for content you know exists")

    conn.close()
    print("\n✅ FTS rebuild complete!")


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'assets.db'
    rebuild_fts(db_path)