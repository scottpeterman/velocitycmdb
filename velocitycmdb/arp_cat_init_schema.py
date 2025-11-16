#!/usr/bin/env python3
"""
Anguis Network Management System - ARP Database Initialization
Creates fresh arp_cat.db with complete schema
"""

import sqlite3
from pathlib import Path


def init_arp_cat_db(db_path: str = "arp_cat.db"):
    """Initialize arp_cat.db with complete schema"""

    db_file = Path(db_path)

    # Remove existing database if present
    if db_file.exists():
        print(f"Removing existing {db_path}...")
        db_file.unlink()

    print(f"Creating {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")

    print("Creating tables...")

    # Devices table
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

    # Contexts table
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

    # ARP snapshots table
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

    # ARP entries table
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

    print("Creating indexes...")

    # Context indexes
    cursor.execute("CREATE INDEX idx_contexts_device ON contexts(device_id)")
    cursor.execute("CREATE INDEX idx_contexts_name_type ON contexts(context_name, context_type)")

    # Snapshot indexes
    cursor.execute("CREATE INDEX idx_snapshots_device_context ON arp_snapshots(device_id, context_id)")
    cursor.execute("CREATE INDEX idx_snapshots_timestamp ON arp_snapshots(capture_timestamp)")

    # ARP entry indexes
    cursor.execute("CREATE INDEX idx_arp_entries_device_context ON arp_entries(device_id, context_id)")
    cursor.execute("CREATE INDEX idx_arp_entries_mac ON arp_entries(mac_address)")
    cursor.execute("CREATE INDEX idx_arp_entries_ip ON arp_entries(ip_address)")
    cursor.execute("CREATE INDEX idx_arp_entries_mac_ip ON arp_entries(mac_address, ip_address)")
    cursor.execute("CREATE INDEX idx_arp_entries_timestamp ON arp_entries(capture_timestamp)")
    cursor.execute("CREATE INDEX idx_arp_entries_current ON arp_entries(is_current)")

    print("Creating triggers...")

    # Update device last seen on ARP entry insert
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

    # Update context last seen on ARP entry insert
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

    # Update snapshot count on ARP entry insert
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

    print("Creating views...")

    # Current ARP view
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

    # Device summary view
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

    # MAC history view
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

    print(f"Database {db_path} initialized successfully!")
    print("\nSchema created:")
    print("  - 4 tables")
    print("  - 10 indexes")
    print("  - 3 triggers")
    print("  - 3 views")


if __name__ == '__main__':
    init_arp_cat_db()