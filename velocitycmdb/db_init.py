#!/usr/bin/env python3
"""
Anguis Network Management System - Database Initialization
Creates fresh assets.db with complete schema
"""

import sqlite3
import sys
from pathlib import Path


def init_assets_db(db_path: str = "assets.db"):
    """Initialize assets.db with complete schema"""

    # Set UTF-8 encoding for Windows console
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

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

    # Sites table
    cursor.execute("""
        CREATE TABLE sites (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT
        )
    """)

    # Vendors table
    cursor.execute("""
        CREATE TABLE vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            short_name TEXT,
            description TEXT
        )
    """)

    # Device types table
    cursor.execute("""
        CREATE TABLE device_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            netmiko_driver TEXT,
            napalm_driver TEXT,
            transport TEXT,
            default_port INTEGER,
            requires_enable BOOLEAN DEFAULT 0,
            supports_config_session BOOLEAN DEFAULT 0
        )
    """)

    # Device roles table
    cursor.execute("""
        CREATE TABLE device_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            expected_model_patterns TEXT,
            port_count_min INTEGER,
            port_count_max INTEGER,
            is_infrastructure BOOLEAN DEFAULT 0
        )
    """)

    # Devices table
    cursor.execute("""
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            normalized_name TEXT UNIQUE NOT NULL,
            site_code TEXT,
            vendor_id INTEGER,
            device_type_id INTEGER,
            model TEXT,
            os_version TEXT,
            uptime TEXT,
            have_sn BOOLEAN DEFAULT 0,
            processor_id TEXT,
            ipv4_address TEXT,
            management_ip TEXT,
            role_id INTEGER,
            is_stack BOOLEAN DEFAULT 0,
            stack_count INTEGER DEFAULT 0,
            timestamp TEXT,
            source_file TEXT,
            source_system TEXT,
            FOREIGN KEY (site_code) REFERENCES sites(code),
            FOREIGN KEY (vendor_id) REFERENCES vendors(id),
            FOREIGN KEY (device_type_id) REFERENCES device_types(id),
            FOREIGN KEY (role_id) REFERENCES device_roles(id)
        )
    """)

    # Device serials table
    cursor.execute("""
        CREATE TABLE device_serials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            serial TEXT NOT NULL,
            is_primary BOOLEAN DEFAULT 0,
            FOREIGN KEY (device_id) REFERENCES devices(id),
            UNIQUE(device_id, serial)
        )
    """)

    # Stack members table
    cursor.execute("""
        CREATE TABLE stack_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            serial TEXT NOT NULL,
            position INTEGER,
            model TEXT,
            is_master BOOLEAN DEFAULT 0,
            FOREIGN KEY (device_id) REFERENCES devices(id),
            UNIQUE(device_id, serial)
        )
    """)

    # Components table
    cursor.execute("""
        CREATE TABLE components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            serial TEXT,
            position TEXT,
            have_sn BOOLEAN DEFAULT 0,
            type TEXT,
            subtype TEXT,
            extraction_source TEXT,
            extraction_confidence REAL,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
    """)

    # Fingerprint extractions table
    cursor.execute("""
        CREATE TABLE fingerprint_extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            extraction_timestamp TEXT NOT NULL,
            fingerprint_file_path TEXT,
            template_used TEXT,
            template_score REAL,
            extraction_success BOOLEAN DEFAULT 1,
            fields_extracted INTEGER,
            total_fields_available INTEGER,
            command_count INTEGER,
            extraction_duration_ms INTEGER,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
    """)

    # Device captures current table
    cursor.execute("""
        CREATE TABLE device_captures_current (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            capture_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            capture_timestamp TEXT NOT NULL,
            extraction_success BOOLEAN DEFAULT 1,
            command_used TEXT,
            FOREIGN KEY (device_id) REFERENCES devices(id),
            UNIQUE(device_id, capture_type)
        )
    """)

    # Capture snapshots table
    cursor.execute("""
        CREATE TABLE capture_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            capture_type TEXT NOT NULL,
            captured_at TIMESTAMP NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
    """)

    # Capture changes table
    cursor.execute("""
        CREATE TABLE capture_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            capture_type TEXT NOT NULL,
            detected_at TIMESTAMP NOT NULL,
            previous_snapshot_id INTEGER,
            current_snapshot_id INTEGER NOT NULL,
            lines_added INTEGER,
            lines_removed INTEGER,
            diff_path TEXT,
            severity TEXT CHECK(severity IN ('minor', 'moderate', 'critical')),
            FOREIGN KEY (device_id) REFERENCES devices(id),
            FOREIGN KEY (previous_snapshot_id) REFERENCES capture_snapshots(id),
            FOREIGN KEY (current_snapshot_id) REFERENCES capture_snapshots(id)
        )
    """)

    # Notes table
    cursor.execute("""
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            note_type TEXT CHECK(note_type IN ('site', 'device', 'general', 'kb')) DEFAULT 'general',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            tags TEXT
        )
    """)

    # Note associations table
    cursor.execute("""
        CREATE TABLE note_associations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('site', 'device', 'note')),
            entity_id TEXT NOT NULL,
            FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
        )
    """)

    # Note attachments table
    cursor.execute("""
        CREATE TABLE note_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            data BLOB,
            file_size INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
        )
    """)

    # Bulk operations table
    cursor.execute("""
        CREATE TABLE bulk_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type TEXT NOT NULL,
            filters TEXT NOT NULL,
            operation_values TEXT NOT NULL,
            affected_count INTEGER NOT NULL,
            executed_by TEXT,
            executed_at TIMESTAMP NOT NULL,
            can_rollback BOOLEAN DEFAULT 0
        )
    """)

    print("Creating indexes...")

    # Device indexes
    cursor.execute("CREATE INDEX idx_devices_vendor ON devices(vendor_id)")
    cursor.execute("CREATE INDEX idx_devices_device_type ON devices(device_type_id)")
    cursor.execute("CREATE INDEX idx_devices_role ON devices(role_id)")

    # Serial indexes
    cursor.execute("CREATE INDEX idx_device_serials_serial ON device_serials(serial)")
    cursor.execute("CREATE INDEX idx_stack_members_serial ON stack_members(serial)")

    # Component indexes
    cursor.execute("CREATE INDEX idx_components_device ON components(device_id)")

    # Fingerprint indexes
    cursor.execute(
        "CREATE INDEX idx_extractions_device_timestamp ON fingerprint_extractions(device_id, extraction_timestamp)")
    cursor.execute("CREATE INDEX idx_extractions_success ON fingerprint_extractions(extraction_success)")

    # Capture indexes
    cursor.execute("CREATE INDEX idx_current_timestamp ON device_captures_current(capture_timestamp)")
    cursor.execute(
        "CREATE INDEX idx_snapshots_device_type_time ON capture_snapshots(device_id, capture_type, captured_at)")
    cursor.execute("CREATE INDEX idx_snapshots_hash ON capture_snapshots(content_hash)")
    cursor.execute("CREATE INDEX idx_changes_device_time ON capture_changes(device_id, detected_at)")

    # Note indexes
    cursor.execute("CREATE INDEX idx_notes_type ON notes(note_type)")
    cursor.execute("CREATE INDEX idx_notes_created ON notes(created_at DESC)")
    cursor.execute("CREATE INDEX idx_notes_updated ON notes(updated_at DESC)")
    cursor.execute("CREATE INDEX idx_assoc_note ON note_associations(note_id)")
    cursor.execute("CREATE INDEX idx_assoc_entity ON note_associations(entity_type, entity_id)")
    cursor.execute("CREATE UNIQUE INDEX idx_assoc_unique ON note_associations(note_id, entity_type, entity_id)")
    cursor.execute("CREATE INDEX idx_attach_note ON note_attachments(note_id)")

    # Bulk operations indexes
    cursor.execute("CREATE INDEX idx_bulk_ops_timestamp ON bulk_operations(executed_at)")

    print("Creating FTS5 tables...")

    # Capture FTS
    cursor.execute("""
        CREATE VIRTUAL TABLE capture_fts USING fts5(
            content,
            content=capture_snapshots,
            content_rowid=id
        )
    """)

    # Note FTS
    cursor.execute("""
        CREATE VIRTUAL TABLE note_fts USING fts5(
            title,
            content,
            tags,
            content=notes,
            content_rowid=id
        )
    """)

    print("Creating triggers...")

    # Device timestamp trigger
    cursor.execute("""
        CREATE TRIGGER tr_devices_update_timestamp 
        AFTER UPDATE ON devices
        FOR EACH ROW
        BEGIN
            UPDATE devices 
            SET timestamp = datetime('now') 
            WHERE id = NEW.id;
        END
    """)

    # Serial triggers
    cursor.execute("""
        CREATE TRIGGER tr_device_serials_update_have_sn_insert
        AFTER INSERT ON device_serials
        FOR EACH ROW
        BEGIN
            UPDATE devices 
            SET have_sn = 1 
            WHERE id = NEW.device_id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER tr_device_serials_update_have_sn_delete
        AFTER DELETE ON device_serials
        FOR EACH ROW
        BEGIN
            UPDATE devices 
            SET have_sn = CASE 
                WHEN (SELECT COUNT(*) FROM device_serials WHERE device_id = OLD.device_id) > 0 
                THEN 1 ELSE 0 
            END
            WHERE id = OLD.device_id;
        END
    """)

    # Stack triggers
    cursor.execute("""
        CREATE TRIGGER tr_stack_members_update_count_insert
        AFTER INSERT ON stack_members
        FOR EACH ROW
        BEGIN
            UPDATE devices 
            SET 
                stack_count = (SELECT COUNT(*) FROM stack_members WHERE device_id = NEW.device_id),
                is_stack = 1
            WHERE id = NEW.device_id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER tr_stack_members_update_count_delete
        AFTER DELETE ON stack_members
        FOR EACH ROW
        BEGIN
            UPDATE devices 
            SET 
                stack_count = (SELECT COUNT(*) FROM stack_members WHERE device_id = OLD.device_id),
                is_stack = CASE 
                    WHEN (SELECT COUNT(*) FROM stack_members WHERE device_id = OLD.device_id) > 1 
                    THEN 1 ELSE 0 
                END
            WHERE id = OLD.device_id;
        END
    """)

    # Note FTS triggers
    cursor.execute("""
        CREATE TRIGGER notes_fts_insert AFTER INSERT ON notes BEGIN
            INSERT INTO note_fts(rowid, title, content, tags)
            VALUES (new.id, new.title, new.content, new.tags);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER notes_fts_update AFTER UPDATE ON notes BEGIN
            UPDATE note_fts SET 
                title = new.title,
                content = new.content,
                tags = new.tags
            WHERE rowid = new.id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER notes_fts_delete AFTER DELETE ON notes BEGIN
            DELETE FROM note_fts WHERE rowid = old.id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER notes_update_timestamp 
        AFTER UPDATE ON notes
        FOR EACH ROW
        BEGIN
            UPDATE notes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END
    """)

    print("Creating views...")

    # Site inventory view
    cursor.execute("""
        CREATE VIEW v_site_inventory AS
        SELECT 
            s.code,
            s.name as site_name,
            s.description,
            COUNT(d.id) as total_devices,
            COUNT(CASE WHEN dr.is_infrastructure = 1 THEN 1 END) as infrastructure_devices,
            COUNT(CASE WHEN d.is_stack = 1 THEN 1 END) as stacked_devices,
            COUNT(DISTINCT v.name) as vendor_count,
            GROUP_CONCAT(DISTINCT v.name) as vendors,
            COUNT(CASE WHEN d.have_sn = 1 THEN 1 END) as devices_with_serials,
            MAX(d.timestamp) as last_device_update
        FROM sites s
        LEFT JOIN devices d ON s.code = d.site_code
        LEFT JOIN vendors v ON d.vendor_id = v.id
        LEFT JOIN device_roles dr ON d.role_id = dr.id
        GROUP BY s.code, s.name, s.description
        ORDER BY total_devices DESC
    """)

    # Device status view
    cursor.execute("""
        CREATE VIEW v_device_status AS
        SELECT 
            d.id,
            d.name,
            d.normalized_name,
            s.name as site_name,
            s.code as site_code,
            v.name as vendor_name,
            dt.name as device_type_name,
            dt.netmiko_driver,
            dt.napalm_driver,
            dt.transport,
            dr.name as role_name,
            dr.is_infrastructure,
            d.model,
            d.os_version,
            d.management_ip,
            d.is_stack,
            d.stack_count,
            d.have_sn,
            COUNT(dcc.id) as current_captures,
            COUNT(DISTINCT dcc.capture_type) as capture_types,
            MAX(fe.extraction_timestamp) as last_fingerprint,
            MAX(fe.extraction_success) as last_fingerprint_success,
            d.timestamp as last_updated
        FROM devices d
        LEFT JOIN sites s ON d.site_code = s.code
        LEFT JOIN vendors v ON d.vendor_id = v.id
        LEFT JOIN device_types dt ON d.device_type_id = dt.id
        LEFT JOIN device_roles dr ON d.role_id = dr.id
        LEFT JOIN device_captures_current dcc ON d.id = dcc.device_id
        LEFT JOIN fingerprint_extractions fe ON d.id = fe.device_id
        GROUP BY d.id
    """)

    # Capture coverage view
    cursor.execute("""
        CREATE VIEW v_capture_coverage AS
        SELECT 
            capture_type,
            COUNT(*) as device_count,
            COUNT(DISTINCT device_id) as unique_devices,
            AVG(file_size) as avg_file_size,
            MAX(capture_timestamp) as latest_capture,
            COUNT(CASE WHEN extraction_success = 0 THEN 1 END) as failed_count,
            ROUND(
                (COUNT(CASE WHEN extraction_success = 1 THEN 1 END) * 100.0) / COUNT(*), 2
            ) as success_rate
        FROM device_captures_current
        GROUP BY capture_type
        ORDER BY device_count DESC
    """)

    # Capture details view
    cursor.execute("""
        CREATE VIEW v_capture_details AS
        SELECT 
            dcc.id as capture_id,
            dcc.capture_type,
            dcc.file_path,
            dcc.file_size,
            dcc.capture_timestamp,
            dcc.extraction_success,
            dcc.command_used,
            d.id as device_id,
            d.name as device_name,
            d.normalized_name as device_normalized_name,
            d.model as device_model,
            d.os_version,
            d.uptime,
            d.processor_id,
            d.ipv4_address,
            d.management_ip,
            d.is_stack,
            d.stack_count,
            d.have_sn as device_has_serial,
            d.timestamp as device_last_updated,
            d.source_file as device_source_file,
            d.source_system as device_source_system,
            s.code as site_code,
            s.name as site_name,
            s.description as site_description,
            v.id as vendor_id,
            v.name as vendor_name,
            v.short_name as vendor_short_name,
            dt.id as device_type_id,
            dt.name as device_type_name,
            dt.netmiko_driver,
            dt.napalm_driver,
            dt.transport,
            dt.default_port,
            dt.requires_enable,
            dt.supports_config_session,
            dr.id as role_id,
            dr.name as role_name,
            dr.description as role_description,
            dr.is_infrastructure,
            CASE 
                WHEN dcc.extraction_success = 1 THEN 'Success'
                ELSE 'Failed'
            END as extraction_status,
            ROUND(dcc.file_size / 1024.0, 2) as file_size_kb,
            CASE 
                WHEN dcc.capture_timestamp IS NOT NULL 
                THEN julianday('now') - julianday(dcc.capture_timestamp)
                ELSE NULL 
            END as days_since_capture
        FROM device_captures_current dcc
        LEFT JOIN devices d ON dcc.device_id = d.id
        LEFT JOIN sites s ON d.site_code = s.code
        LEFT JOIN vendors v ON d.vendor_id = v.id
        LEFT JOIN device_types dt ON d.device_type_id = dt.id
        LEFT JOIN device_roles dr ON d.role_id = dr.id
        ORDER BY dcc.capture_timestamp DESC
    """)

    conn.commit()
    conn.close()

    print(f"✓ Database {db_path} initialized successfully!")
    print("\nSchema created:")
    print("  - 17 tables")
    print("  - 20 indexes")
    print("  - 9 triggers")
    print("  - 4 views")
    print("  - 2 FTS5 virtual tables")


if __name__ == '__main__':
    init_assets_db()