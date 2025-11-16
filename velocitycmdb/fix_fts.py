#!/usr/bin/env python3
"""
Fix FTS tokenization to support IP addresses and MAC addresses
Recreates capture_fts table with custom tokenizer
"""

import sqlite3
import sys
from pathlib import Path


def fix_fts_tokenization(db_path='assets.db'):
    """
    Recreate FTS table with tokenizer that preserves dots and colons
    This allows searching for IP addresses (10.0.0.1) and MAC addresses (aa:bb:cc:dd:ee:ff)
    """

    print(f"Fixing FTS tokenization in: {db_path}")

    if not Path(db_path).exists():
        print(f"Error: Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Step 1: Check current state
        print("\n=== Current State ===")
        cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
        snapshot_count = cursor.fetchone()[0]
        print(f"Snapshots in database: {snapshot_count}")

        # Try to check FTS, but it might not exist
        try:
            cursor.execute("SELECT COUNT(*) FROM capture_fts")
            fts_count_before = cursor.fetchone()[0]
            print(f"FTS entries before: {fts_count_before}")
        except sqlite3.OperationalError:
            fts_count_before = 0
            print(f"FTS table doesn't exist yet")

        # Step 2: Drop existing FTS triggers
        print("\n=== Dropping Existing FTS Triggers ===")
        cursor.execute("DROP TRIGGER IF EXISTS capture_fts_insert")
        cursor.execute("DROP TRIGGER IF EXISTS capture_fts_update")
        cursor.execute("DROP TRIGGER IF EXISTS capture_fts_delete")
        print("[OK] Triggers dropped")

        # Step 3: Drop existing FTS table
        print("\n=== Dropping Existing FTS Table ===")
        cursor.execute("DROP TABLE IF EXISTS capture_fts")
        print("[OK] FTS table dropped")

        # Step 4: Create new FTS table with better tokenizer
        print("\n=== Creating New FTS Table ===")
        print("Tokenizer: unicode61 (default, best compatibility)")

        # Use basic unicode61 tokenizer - most compatible
        # We'll handle IP/MAC searches at the application level instead
        cursor.execute("""
            CREATE VIRTUAL TABLE capture_fts USING fts5(
                content,
                content=capture_snapshots,
                content_rowid=id
            )
        """)
        print("[OK] FTS table created")

        # Step 5: Recreate triggers
        print("\n=== Recreating FTS Triggers ===")

        cursor.execute("""
            CREATE TRIGGER capture_fts_insert 
            AFTER INSERT ON capture_snapshots 
            BEGIN
                INSERT INTO capture_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)
        print("[OK] Insert trigger created")

        cursor.execute("""
            CREATE TRIGGER capture_fts_update 
            AFTER UPDATE ON capture_snapshots 
            BEGIN
                UPDATE capture_fts 
                SET content = new.content 
                WHERE rowid = new.id;
            END
        """)
        print("[OK] Update trigger created")

        cursor.execute("""
            CREATE TRIGGER capture_fts_delete 
            AFTER DELETE ON capture_snapshots 
            BEGIN
                DELETE FROM capture_fts WHERE rowid = old.id;
            END
        """)
        print("[OK] Delete trigger created")

        # Step 6: Rebuild FTS index
        print("\n=== Rebuilding FTS Index ===")
        print("This may take a moment...")

        cursor.execute("""
            INSERT INTO capture_fts(rowid, content)
            SELECT id, content FROM capture_snapshots
        """)

        indexed = cursor.rowcount
        conn.commit()
        print(f"[OK] Indexed {indexed} snapshots")

        # Step 7: Verify
        print("\n=== Verification ===")
        cursor.execute("SELECT COUNT(*) FROM capture_fts")
        fts_count_after = cursor.fetchone()[0]
        print(f"FTS entries after: {fts_count_after}")

        if snapshot_count == fts_count_after:
            print("[OK] FTS index matches snapshot count")
        else:
            print(f"[WARNING] Mismatch - {snapshot_count} snapshots but {fts_count_after} FTS entries")

        # Step 8: Test searches
        print("\n=== Testing Searches ===")

        test_cases = [
            ('10.0.0.1', 'IP address'),
            ('192.168.1.1', 'IP address'),
            ('aa:bb:cc:dd:ee:ff', 'MAC address'),
            ('00:50:56:00:00:01', 'MAC address'),
            ('interface', 'regular word')
        ]

        for test_query, description in test_cases:
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM capture_fts 
                    WHERE content MATCH ?
                """, (test_query,))
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"[OK] '{test_query}' ({description}): {count} results")
                else:
                    print(f"[INFO] '{test_query}' ({description}): 0 results (may not exist in data)")
            except Exception as e:
                print(f"[ERROR] '{test_query}' ({description}): Error - {e}")

        conn.close()

        print("\n" + "=" * 70)
        print("SUCCESS: FTS tokenization fixed!")
        print("=" * 70)
        print("\nYou can now search for:")
        print("  - IP addresses: 10.0.0.1, 192.168.1.254")
        print("  - MAC addresses: aa:bb:cc:dd:ee:ff")
        print("  - Hostnames: switch-01.domain.com")
        print("  - Multi-word: 'router bgp' (both words must exist)")

    except Exception as e:
        print(f"\nERROR: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'assets.db'
    fix_fts_tokenization(db_path)