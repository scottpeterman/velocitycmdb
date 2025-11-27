#!/usr/bin/env python3
"""
ARP Cat - Reset and Test Script

Complete reset and validation of the ARP Cat database and loading pipeline.
"""

import os
import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def reset_arp_cat_db(db_path: str = "arp_cat.db"):
    """Complete database reset with schema creation"""

    db_file = Path(db_path)

    # Backup existing database if it exists
    if db_file.exists():
        backup_path = f"{db_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Backing up existing database to: {backup_path}")
        import shutil
        shutil.copy2(db_path, backup_path)

        logger.info(f"Removing existing {db_path}...")
        db_file.unlink()

    logger.info(f"Creating fresh {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    logger.info("Creating schema...")

    # Tables
    cursor.execute("""
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT UNIQUE NOT NULL,
            normalized_hostname TEXT UNIQUE NOT NULL,
            device_type TEXT,
            vendor TEXT,
            model TEXT,
            site_code TEXT,
            management_ip TEXT,
            created_timestamp TEXT DEFAULT (datetime('now')),
            last_seen_timestamp TEXT DEFAULT (datetime('now'))
        )
    """)

    cursor.execute("""
        CREATE TABLE contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            context_name TEXT NOT NULL DEFAULT 'default',
            context_type TEXT NOT NULL DEFAULT 'vrf',
            description TEXT,
            created_timestamp TEXT DEFAULT (datetime('now')),
            last_seen_timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            UNIQUE(device_id, context_name, context_type)
        )
    """)

    cursor.execute("""
        CREATE TABLE arp_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            context_id INTEGER NOT NULL,
            capture_timestamp TEXT NOT NULL,
            source_file TEXT,
            source_command TEXT,
            total_entries INTEGER DEFAULT 0,
            processing_status TEXT DEFAULT 'pending',
            processing_error TEXT,
            processing_timestamp TEXT,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            FOREIGN KEY (context_id) REFERENCES contexts(id) ON DELETE CASCADE,
            UNIQUE(device_id, context_id, capture_timestamp)
        )
    """)

    cursor.execute("""
        CREATE TABLE arp_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            context_id INTEGER NOT NULL,
            ip_address TEXT NOT NULL,
            mac_address TEXT NOT NULL,
            mac_address_raw TEXT NOT NULL,
            interface_name TEXT,
            entry_type TEXT,
            age TEXT,
            protocol TEXT DEFAULT 'IPv4',
            capture_timestamp TEXT NOT NULL,
            source_file TEXT,
            source_command TEXT,
            is_current BOOLEAN DEFAULT 1,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            FOREIGN KEY (context_id) REFERENCES contexts(id) ON DELETE CASCADE
        )
    """)

    # Indexes
    indexes = [
        "CREATE INDEX idx_contexts_device ON contexts(device_id)",
        "CREATE INDEX idx_contexts_name_type ON contexts(context_name, context_type)",
        "CREATE INDEX idx_snapshots_device_context ON arp_snapshots(device_id, context_id)",
        "CREATE INDEX idx_snapshots_timestamp ON arp_snapshots(capture_timestamp)",
        "CREATE INDEX idx_arp_entries_device_context ON arp_entries(device_id, context_id)",
        "CREATE INDEX idx_arp_entries_mac ON arp_entries(mac_address)",
        "CREATE INDEX idx_arp_entries_ip ON arp_entries(ip_address)",
        "CREATE INDEX idx_arp_entries_mac_ip ON arp_entries(mac_address, ip_address)",
        "CREATE INDEX idx_arp_entries_timestamp ON arp_entries(capture_timestamp)",
        "CREATE INDEX idx_arp_entries_current ON arp_entries(is_current)"
    ]

    for idx_sql in indexes:
        cursor.execute(idx_sql)

    # Triggers
    cursor.execute("""
        CREATE TRIGGER tr_update_device_last_seen
        AFTER INSERT ON arp_entries
        FOR EACH ROW
        BEGIN
            UPDATE devices
            SET last_seen_timestamp = datetime('now')
            WHERE id = NEW.device_id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER tr_update_context_last_seen
        AFTER INSERT ON arp_entries
        FOR EACH ROW
        BEGIN
            UPDATE contexts
            SET last_seen_timestamp = datetime('now')
            WHERE id = NEW.context_id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER tr_update_snapshot_count
        AFTER INSERT ON arp_entries
        FOR EACH ROW
        BEGIN
            UPDATE arp_snapshots
            SET total_entries = (
                SELECT COUNT(*)
                FROM arp_entries
                WHERE device_id = NEW.device_id
                AND context_id = NEW.context_id
                AND capture_timestamp = NEW.capture_timestamp
            )
            WHERE device_id = NEW.device_id
            AND context_id = NEW.context_id
            AND capture_timestamp = NEW.capture_timestamp;
        END
    """)

    # Views
    cursor.execute("""
        CREATE VIEW v_current_arp AS
        SELECT
            ae.id,
            d.hostname,
            d.device_type,
            d.vendor,
            c.context_name,
            c.context_type,
            ae.ip_address,
            ae.mac_address,
            ae.mac_address_raw,
            ae.interface_name,
            ae.entry_type,
            ae.age,
            ae.protocol,
            ae.capture_timestamp,
            ae.source_file
        FROM arp_entries ae
        JOIN devices d ON ae.device_id = d.id
        JOIN contexts c ON ae.context_id = c.id
        WHERE ae.is_current = 1
        ORDER BY ae.capture_timestamp DESC
    """)

    cursor.execute("""
        CREATE VIEW v_device_summary AS
        SELECT
            d.hostname,
            d.device_type,
            d.vendor,
            d.site_code,
            COUNT(DISTINCT c.id) as context_count,
            COUNT(DISTINCT ae.mac_address) as unique_macs,
            COUNT(ae.id) as total_arp_entries,
            MAX(ae.capture_timestamp) as last_arp_capture,
            MAX(s.capture_timestamp) as last_snapshot
        FROM devices d
        LEFT JOIN contexts c ON d.id = c.device_id
        LEFT JOIN arp_entries ae ON d.id = ae.device_id
        LEFT JOIN arp_snapshots s ON d.id = s.device_id
        GROUP BY d.id, d.hostname, d.device_type, d.vendor, d.site_code
        ORDER BY last_arp_capture DESC
    """)

    cursor.execute("""
        CREATE VIEW v_mac_history AS
        SELECT
            ae.mac_address,
            ae.ip_address,
            d.hostname,
            c.context_name,
            c.context_type,
            ae.interface_name,
            ae.capture_timestamp,
            ae.entry_type,
            COUNT(*) OVER (PARTITION BY ae.mac_address) as total_occurrences
        FROM arp_entries ae
        JOIN devices d ON ae.device_id = d.id
        JOIN contexts c ON ae.context_id = c.id
        ORDER BY ae.mac_address, ae.capture_timestamp DESC
    """)

    conn.commit()
    conn.close()

    logger.info("✓ Database schema created successfully")
    return True


def verify_schema(db_path: str = "arp_cat.db"):
    """Verify database schema is correct"""

    logger.info("Verifying database schema...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    expected_tables = ['arp_entries', 'arp_snapshots', 'contexts', 'devices']
    missing_tables = set(expected_tables) - set(tables)

    if missing_tables:
        logger.error(f"✗ Missing tables: {missing_tables}")
        return False

    logger.info(f"✓ All tables present: {tables}")

    # Check indexes
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
    indexes = [row[0] for row in cursor.fetchall()]
    logger.info(f"✓ Found {len(indexes)} indexes")

    # Check triggers
    cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
    triggers = [row[0] for row in cursor.fetchall()]

    expected_triggers = ['tr_update_context_last_seen', 'tr_update_device_last_seen', 'tr_update_snapshot_count']
    missing_triggers = set(expected_triggers) - set(triggers)

    if missing_triggers:
        logger.error(f"✗ Missing triggers: {missing_triggers}")
        return False

    logger.info(f"✓ All triggers present: {triggers}")

    # Check views
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    views = [row[0] for row in cursor.fetchall()]

    expected_views = ['v_current_arp', 'v_device_summary', 'v_mac_history']
    missing_views = set(expected_views) - set(views)

    if missing_views:
        logger.error(f"✗ Missing views: {missing_views}")
        return False

    logger.info(f"✓ All views present: {views}")

    conn.close()
    return True


def check_assets_db(assets_db_path: str = "assets.db"):
    """Check assets.db for ARP captures"""

    logger.info("Checking assets.db for ARP captures...")

    if not os.path.exists(assets_db_path):
        logger.error(f"✗ assets.db not found at: {assets_db_path}")
        return False

    conn = sqlite3.connect(assets_db_path)
    cursor = conn.cursor()

    # Check for v_capture_details view
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='v_capture_details'")
    if not cursor.fetchone():
        logger.error("✗ v_capture_details view not found in assets.db")
        conn.close()
        return False

    logger.info("✓ v_capture_details view found")

    # Count ARP captures
    cursor.execute("""
        SELECT COUNT(*) FROM v_capture_details 
        WHERE capture_type = 'arp' 
        AND extraction_success = 1
        AND file_path IS NOT NULL
    """)

    arp_count = cursor.fetchone()[0]
    logger.info(f"✓ Found {arp_count} ARP captures ready to process")

    if arp_count == 0:
        logger.warning("⚠ No ARP captures found - run capture jobs first")

    # Show sample devices
    cursor.execute("""
        SELECT DISTINCT device_name, vendor_name 
        FROM v_capture_details 
        WHERE capture_type = 'arp'
        LIMIT 5
    """)

    devices = cursor.fetchall()
    if devices:
        logger.info("Sample devices with ARP captures:")
        for device, vendor in devices:
            logger.info(f"  - {device} ({vendor})")

    conn.close()
    return arp_count > 0


def test_load_sample_with_paths(assets_db: str, arp_db: str, max_files: int = 3):
    """Test loading a few ARP captures with custom paths"""

    logger.info(f"\nTesting ARP loading with {max_files} sample files...")

    # Check for TextFSM templates
    tfsm_paths = ["tfsm_templates.db", "pcng/tfsm_templates.db", "../pcng/tfsm_templates.db",
                  "Anguis/tfsm_templates.db"]
    tfsm_db = None

    for path in tfsm_paths:
        if os.path.exists(path):
            tfsm_db = path
            logger.info(f"✓ Found TextFSM templates at: {path}")
            break

    if not tfsm_db:
        logger.error("✗ TextFSM templates not found in any expected location")
        logger.error(f"  Searched: {tfsm_paths}")
        return False

    try:
        from arp_cat_loader import ArpCaptureLoader

        loader = ArpCaptureLoader(
            assets_db_path=assets_db,
            arp_cat_db_path=arp_db,
            textfsm_db_path=tfsm_db
        )

        stats = loader.load_all_captures(max_files=max_files)

        logger.info("\nLoad test results:")
        logger.info(f"  Files processed: {stats['files_processed']}")
        logger.info(f"  Files skipped: {stats['files_skipped']}")
        logger.info(f"  Total entries: {stats['total_entries']}")
        logger.info(f"  Errors: {stats['errors']}")

        if stats['total_entries'] > 0:
            logger.info("✓ Loading test successful")
            return True
        else:
            logger.warning("⚠ No entries loaded - check TextFSM templates")
            return False

    except Exception as e:
        logger.error(f"✗ Load test failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


def show_stats(db_path: str = "arp_cat.db"):
    """Show database statistics"""

    logger.info("\n" + "=" * 60)
    logger.info("ARP Cat Database Statistics")
    logger.info("=" * 60)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Device count
    cursor.execute("SELECT COUNT(*) FROM devices")
    device_count = cursor.fetchone()[0]
    logger.info(f"Devices: {device_count}")

    # Context count
    cursor.execute("SELECT COUNT(*) FROM contexts")
    context_count = cursor.fetchone()[0]
    logger.info(f"Contexts: {context_count}")

    # Snapshot count
    cursor.execute("SELECT COUNT(*) FROM arp_snapshots")
    snapshot_count = cursor.fetchone()[0]
    logger.info(f"Snapshots: {snapshot_count}")

    # Total entries
    cursor.execute("SELECT COUNT(*) FROM arp_entries")
    total_entries = cursor.fetchone()[0]
    logger.info(f"Total ARP entries: {total_entries}")

    # Current entries
    cursor.execute("SELECT COUNT(*) FROM arp_entries WHERE is_current = 1")
    current_entries = cursor.fetchone()[0]
    logger.info(f"Current entries: {current_entries}")

    # Unique MACs
    cursor.execute("SELECT COUNT(DISTINCT mac_address) FROM arp_entries")
    unique_macs = cursor.fetchone()[0]
    logger.info(f"Unique MAC addresses: {unique_macs}")

    # Latest capture
    cursor.execute("SELECT MAX(capture_timestamp) FROM arp_entries")
    latest = cursor.fetchone()[0]
    if latest:
        logger.info(f"Latest capture: {latest}")

    logger.info("=" * 60 + "\n")

    conn.close()


def main():
    """Main reset and test workflow"""

    import argparse
    parser = argparse.ArgumentParser(description="Reset and test ARP Cat database")
    parser.add_argument("--assets-db", default="assets.db", help="Path to assets.db")
    parser.add_argument("--arp-db", default="arp_cat.db", help="Path to arp_cat.db")
    parser.add_argument("--skip-reset", action="store_true", help="Skip database reset")
    parser.add_argument("--skip-load", action="store_true", help="Skip load test")
    parser.add_argument("--max-test-files", type=int, default=100, help="Max files for load test")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("ARP Cat - Reset  and Test")
    logger.info("=" * 60 + "\n")

    # Step 1: Reset database
    if not args.skip_reset:
        if not reset_arp_cat_db(args.arp_db):
            logger.error("Database reset failed")
            return 1
    else:
        logger.info("Skipping database reset")

    # Step 2: Verify schema
    if not verify_schema(args.arp_db):
        logger.error("Schema verification failed")
        return 1

    # Step 3: Check assets.db
    has_captures = check_assets_db(args.assets_db)

    # Step 4: Test loading
    if not args.skip_load and has_captures:
        if not test_load_sample_with_paths(args.assets_db, args.arp_db, max_files=args.max_test_files):
            logger.warning("Load test had issues - check logs")
    else:
        if args.skip_load:
            logger.info("Skipping load test")
        else:
            logger.warning("Skipping load test - no captures available")

    # Step 5: Show stats
    show_stats(args.arp_db)

    logger.info("\n✓ Reset and test complete!")
    logger.info("\nNext steps:")
    logger.info("  1. Review the statistics above")
    logger.info("  2. If needed, run full load: python arp_cat_loader.py")
    logger.info("  3. Test queries with arp_cat_util.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())