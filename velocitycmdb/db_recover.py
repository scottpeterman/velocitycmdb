#!/usr/bin/env python3
"""
Force rebuild of corrupted FTS tables
Drops and recreates capture_fts and note_fts tables with their triggers
"""

import sqlite3
import sys


def force_rebuild_fts(db_path='assets.db'):
    """Forcibly rebuild all FTS tables"""

    print(f"Connecting to: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # ============================================================
        # REBUILD note_fts (notes table)
        # ============================================================
        print("\n" + "=" * 50)
        print("=== Rebuilding note_fts ===")
        print("=" * 50)

        cursor.execute("SELECT COUNT(*) FROM notes")
        note_count = cursor.fetchone()[0]
        print(f"\nFound {note_count} notes to index")

        if note_count > 0:
            # Drop triggers first
            print("\nDropping FTS triggers...")
            cursor.execute("DROP TRIGGER IF EXISTS notes_fts_insert")
            cursor.execute("DROP TRIGGER IF EXISTS notes_fts_update")
            cursor.execute("DROP TRIGGER IF EXISTS notes_fts_delete")
            print("✓ Triggers dropped")

            # Drop FTS table
            print("Dropping FTS table...")
            cursor.execute("DROP TABLE IF EXISTS note_fts")
            print("✓ FTS table dropped")

            print("\nRecreating FTS table...")
            cursor.execute("""
                CREATE VIRTUAL TABLE note_fts USING fts5(
                    title,
                    content,
                    tags,
                    content=notes,
                    content_rowid=id
                )
            """)
            print("✓ FTS table created")

            print("\nRecreating FTS triggers...")
            cursor.execute("""
                CREATE TRIGGER notes_fts_insert AFTER INSERT ON notes BEGIN
                    INSERT INTO note_fts(rowid, title, content, tags)
                    VALUES (new.id, new.title, new.content, new.tags);
                END
            """)
            print("✓ Insert trigger created")

            cursor.execute("""
                CREATE TRIGGER notes_fts_update AFTER UPDATE ON notes BEGIN
                    UPDATE note_fts SET 
                        title = new.title,
                        content = new.content,
                        tags = new.tags
                    WHERE rowid = new.id;
                END
            """)
            print("✓ Update trigger created")

            cursor.execute("""
                CREATE TRIGGER notes_fts_delete AFTER DELETE ON notes BEGIN
                    DELETE FROM note_fts WHERE rowid = old.id;
                END
            """)
            print("✓ Delete trigger created")

            print("\nPopulating FTS index...")
            cursor.execute("""
                INSERT INTO note_fts(rowid, title, content, tags)
                SELECT id, title, content, tags FROM notes
            """)
            print(f"✓ Indexed {note_count} notes")

            # Verify
            cursor.execute("SELECT COUNT(*) FROM note_fts")
            fts_count = cursor.fetchone()[0]
            if note_count == fts_count:
                print(f"✅ note_fts rebuilt successfully")
            else:
                print(f"⚠️  Count mismatch: {note_count} vs {fts_count}")
        else:
            print("No notes to index - skipping")

        # ============================================================
        # REBUILD capture_fts (capture_snapshots table)
        # ============================================================
        print("\n" + "=" * 50)
        print("=== Rebuilding capture_fts ===")
        print("=" * 50)

        cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
        snapshot_count = cursor.fetchone()[0]
        print(f"\nFound {snapshot_count} snapshots to index")

        if snapshot_count > 0:
            # Drop triggers first
            print("\nDropping FTS triggers...")
            cursor.execute("DROP TRIGGER IF EXISTS capture_fts_insert")
            cursor.execute("DROP TRIGGER IF EXISTS capture_fts_update")
            cursor.execute("DROP TRIGGER IF EXISTS capture_fts_delete")
            print("✓ Triggers dropped")

            # Drop FTS table
            print("Dropping FTS table...")
            cursor.execute("DROP TABLE IF EXISTS capture_fts")
            print("✓ FTS table dropped")

            print("\nRecreating FTS table...")
            cursor.execute("""
                CREATE VIRTUAL TABLE capture_fts USING fts5(
                    content,
                    content=capture_snapshots,
                    content_rowid=id
                )
            """)
            print("✓ FTS table created")

            print("\nRecreating FTS triggers...")
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

            print("\nPopulating FTS index...")
            cursor.execute("""
                INSERT INTO capture_fts(rowid, content)
                SELECT id, content FROM capture_snapshots
            """)
            print(f"✓ Indexed {snapshot_count} snapshots")

            # Verify
            cursor.execute("SELECT COUNT(*) FROM capture_fts")
            fts_count = cursor.fetchone()[0]
            if snapshot_count == fts_count:
                print(f"✅ capture_fts rebuilt successfully")
            else:
                print(f"⚠️  Count mismatch: {snapshot_count} vs {fts_count}")
        else:
            print("No snapshots to index - skipping")

        # ============================================================
        # COMMIT AND VERIFY
        # ============================================================
        conn.commit()

        print("\n" + "=" * 50)
        print("=== Final Verification ===")
        print("=" * 50)

        # Integrity check
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        if integrity == "ok":
            print("✓ Database integrity check passed")
        else:
            print(f"⚠️  Integrity issue: {integrity}")

        # Test note search
        if note_count > 0:
            try:
                cursor.execute("SELECT COUNT(*) FROM note_fts WHERE note_fts MATCH 'test OR the OR a'")
                print(f"✓ note_fts search working")
            except Exception as e:
                print(f"✗ note_fts search failed: {e}")

        # Test capture search
        if snapshot_count > 0:
            test_queries = ['interface', 'vlan', 'ip', 'config', 'cisco']
            for query in test_queries:
                try:
                    cursor.execute("SELECT COUNT(*) FROM capture_fts WHERE content MATCH ?", (query,))
                    count = cursor.fetchone()[0]
                    if count > 0:
                        print(f"✓ capture_fts search for '{query}': {count} results")
                        break
                except Exception as e:
                    print(f"✗ capture_fts search failed: {e}")

        conn.close()
        print("\n" + "=" * 50)
        print("✅ FTS rebuild complete!")
        print("=" * 50)
        print("\nYou can now restart your Flask application.")

    except Exception as e:
        print(f"\n❌ Error during rebuild: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        sys.exit(1)


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'assets.db'
    force_rebuild_fts(db_path)