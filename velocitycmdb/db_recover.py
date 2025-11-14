#!/usr/bin/env python3
"""
Force rebuild of corrupted FTS table
Drops and recreates the capture_fts table and triggers
"""

import sqlite3
import sys


def force_rebuild_fts(db_path='assets.db'):
    """Forcibly rebuild the FTS table"""

    print(f"Connecting to: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get snapshot count before we start
        cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
        snapshot_count = cursor.fetchone()[0]
        print(f"\nFound {snapshot_count} snapshots to index")

        if snapshot_count == 0:
            print("No snapshots to index!")
            conn.close()
            return

        print("\n=== Dropping corrupted FTS table ===")
        # Drop triggers first
        print("Dropping FTS triggers...")
        cursor.execute("DROP TRIGGER IF EXISTS capture_fts_insert")
        cursor.execute("DROP TRIGGER IF EXISTS capture_fts_update")
        cursor.execute("DROP TRIGGER IF EXISTS capture_fts_delete")
        print("✓ Triggers dropped")

        # Drop FTS table
        print("Dropping FTS table...")
        cursor.execute("DROP TABLE IF EXISTS capture_fts")
        print("✓ FTS table dropped")

        print("\n=== Recreating FTS table ===")
        cursor.execute("""
            CREATE VIRTUAL TABLE capture_fts USING fts5(
                content,
                content=capture_snapshots,
                content_rowid=id
            )
        """)
        print("✓ FTS table created")

        print("\n=== Recreating FTS triggers ===")
        cursor.execute("""
            CREATE TRIGGER capture_fts_insert 
            AFTER INSERT ON capture_snapshots 
            BEGIN
                INSERT INTO capture_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)
        print("✓ Insert trigger created")

        cursor.execute("""
            CREATE TRIGGER capture_fts_update 
            AFTER UPDATE ON capture_snapshots 
            BEGIN
                UPDATE capture_fts 
                SET content = new.content 
                WHERE rowid = new.id;
            END
        """)
        print("✓ Update trigger created")

        cursor.execute("""
            CREATE TRIGGER capture_fts_delete 
            AFTER DELETE ON capture_snapshots 
            BEGIN
                DELETE FROM capture_fts WHERE rowid = old.id;
            END
        """)
        print("✓ Delete trigger created")

        print("\n=== Populating FTS index ===")
        print("This may take a moment...")
        cursor.execute("""
            INSERT INTO capture_fts(rowid, content)
            SELECT id, content FROM capture_snapshots
        """)
        indexed_count = cursor.rowcount
        print(f"✓ Indexed {indexed_count} snapshots")

        conn.commit()

        # Verify
        print("\n=== Verification ===")
        cursor.execute("SELECT COUNT(*) FROM capture_fts")
        fts_count = cursor.fetchone()[0]

        print(f"Snapshots: {snapshot_count}")
        print(f"FTS entries: {fts_count}")

        if snapshot_count == fts_count:
            print("\n✅ SUCCESS! FTS table rebuilt and populated correctly")
        else:
            print(f"\n⚠️  WARNING: Count mismatch!")

        # Test search
        print("\n=== Testing FTS search ===")
        test_queries = ['interface', 'vlan', 'ip', 'config', 'cisco']

        for query in test_queries:
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM capture_fts 
                    WHERE content MATCH ?
                """, (query,))
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"✓ Search for '{query}': {count} results")
                    break
            except Exception as e:
                print(f"✗ Search for '{query}' failed: {e}")
        else:
            print("No test results found")

        conn.close()
        print("\n✅ FTS rebuild complete!")
        print("\nYou can now use the Flask capture search feature.")

    except Exception as e:
        print(f"\n❌ Error during rebuild: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'assets.db'
    force_rebuild_fts(db_path)