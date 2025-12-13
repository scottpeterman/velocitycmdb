"""
Database initialization for VelocityCMDB
Matches schema documentation exactly
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """Initialize all VelocityCMDB databases"""

    def __init__(self, data_dir='~/.velocitycmdb/data'):
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.assets_db = self.data_dir / 'assets.db'
        self.arp_db = self.data_dir / 'arp_cat.db'
        self.users_db = self.data_dir / 'users.db'

    def _create_directory_structure(self):
        """
        Create complete directory structure for VelocityCMDB.

        Creates:
        - Core directories: fingerprints, logs, jobs
        - 25+ capture subdirectories for network data
        - Discovery output directory
        """
        logger.info("Creating directory structure...")

        # Core directories
        directories = [
            self.data_dir / 'fingerprints',
            self.data_dir / 'logs',
            self.data_dir / 'jobs',
            self.data_dir / 'maps',

            # Capture directories - organized by data type
            self.data_dir / 'capture' / 'arp',
            self.data_dir / 'capture' / 'authentication',
            self.data_dir / 'capture' / 'authorization',
            self.data_dir / 'capture' / 'bgp-neighbor',
            self.data_dir / 'capture' / 'bgp-summary',
            self.data_dir / 'capture' / 'cdp',
            self.data_dir / 'capture' / 'configs',
            self.data_dir / 'capture' / 'cpu',
            self.data_dir / 'capture' / 'environment',
            self.data_dir / 'capture' / 'etherchannel',
            self.data_dir / 'capture' / 'interfaces',
            self.data_dir / 'capture' / 'inventory',
            self.data_dir / 'capture' / 'lldp',
            self.data_dir / 'capture' / 'mac',
            self.data_dir / 'capture' / 'memory',
            self.data_dir / 'capture' / 'ospf',
            self.data_dir / 'capture' / 'power',
            self.data_dir / 'capture' / 'routing',
            self.data_dir / 'capture' / 'spanning-tree',
            self.data_dir / 'capture' / 'transceivers',
            self.data_dir / 'capture' / 'version',
            self.data_dir / 'capture' / 'vlan',
            self.data_dir / 'capture' / 'vpc',
            self.data_dir / 'capture' / 'vrf',
            self.data_dir / 'capture' / 'vrrp',

            # Discovery output directory (sibling to data/)
            self.data_dir.parent / 'discovery',
        ]

        created_count = 0
        for directory in directories:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created_count += 1
                logger.debug(f"Created directory: {directory}")

        logger.info(f"✓ Directory structure complete ({created_count} new directories)")
        return True

    def initialize_all(self, admin_username='admin', admin_password='admin'):
        """
        Initialize all three databases

        Args:
            admin_username: Username for admin account (default: 'admin')
            admin_password: Password for admin account (default: 'admin')

        Returns: (success: bool, message: str)
        """
        try:
            logger.info("Starting database initialization...")

            # 0. Create directory structure FIRST
            self._create_directory_structure()

            # 1. Assets database
            logger.info("Initializing assets database...")
            self._init_assets_db()
            logger.info("✓ Assets database initialized")

            # 2. ARP database
            logger.info("Initializing ARP database...")
            self._init_arp_db()
            logger.info("✓ ARP database initialized")

            # 3. Users database
            logger.info("Initializing users database...")
            self._init_users_db(admin_username, admin_password)
            logger.info("✓ Users database initialized")

            logger.info("All databases initialized successfully")
            return True, "All databases initialized successfully"

        except Exception as e:
            logger.exception("Database initialization failed")
            return False, f"Initialization failed: {str(e)}"

    def _init_assets_db(self):
        """Initialize assets.db with complete schema from documentation"""
        conn = sqlite3.connect(str(self.assets_db))
        cursor = conn.cursor()

        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        # ================================================================
        # CORE REFERENCE TABLES (no foreign keys)
        # ================================================================

        # Vendors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                short_name TEXT,
                description TEXT
            )
        """)

        # Sites table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT
            )
        """)

        # Device types table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_types (
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
            CREATE TABLE IF NOT EXISTS device_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                expected_model_patterns TEXT,
                port_count_min INTEGER,
                port_count_max INTEGER,
                is_infrastructure BOOLEAN DEFAULT 0
            )
        """)

        # ================================================================
        # DEVICES TABLE (references: sites, vendors, device_types, device_roles)
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
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

        # ================================================================
        # DEVICE-RELATED TABLES
        # ================================================================

        # Device serials
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_serials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                serial TEXT NOT NULL,
                is_primary BOOLEAN DEFAULT 0,
                FOREIGN KEY (device_id) REFERENCES devices(id),
                UNIQUE(device_id, serial)
            )
        """)

        # Stack members
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stack_members (
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

        # ================================================================
        # COMPONENTS TABLE (hardware inventory)
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS components (
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

        # ================================================================
        # CAPTURE SYSTEM TABLES
        # ================================================================

        # Current captures (one per device per capture type)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_captures_current (
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

        # Capture snapshots (historical captures with content)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capture_snapshots (
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

        # Capture changes (diff tracking between snapshots)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capture_changes (
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

        # ================================================================
        # FINGERPRINT EXTRACTIONS
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fingerprint_extractions (
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

        # ================================================================
        # BULK OPERATIONS TRACKING
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bulk_operations (
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

        # ================================================================
        # NOTES SYSTEM (Knowledge Management)
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
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

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS note_associations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('site', 'device', 'note')),
                entity_id TEXT NOT NULL,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS note_attachments (
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

        # ================================================================
        # FULL TEXT SEARCH - Notes
        # ================================================================

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
                title,
                content,
                tags,
                content=notes,
                content_rowid=id
            )
        """)

        # ================================================================
        # FULL TEXT SEARCH - Capture Content
        # ================================================================

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS capture_fts USING fts5(
                content,
                content=capture_snapshots,
                content_rowid=id
            )
        """)

        # ================================================================
        # INDEXES
        # ================================================================

        indexes = [
            # Devices indexes
            "CREATE INDEX IF NOT EXISTS idx_devices_vendor ON devices(vendor_id)",
            "CREATE INDEX IF NOT EXISTS idx_devices_device_type ON devices(device_type_id)",
            "CREATE INDEX IF NOT EXISTS idx_devices_role ON devices(role_id)",

            # Device serials index
            "CREATE INDEX IF NOT EXISTS idx_device_serials_serial ON device_serials(serial)",

            # Stack members index
            "CREATE INDEX IF NOT EXISTS idx_stack_members_serial ON stack_members(serial)",

            # Components index
            "CREATE INDEX IF NOT EXISTS idx_components_device ON components(device_id)",

            # Device captures current index
            "CREATE INDEX IF NOT EXISTS idx_current_timestamp ON device_captures_current(capture_timestamp)",

            # Capture snapshots indexes
            "CREATE INDEX IF NOT EXISTS idx_snapshots_device_type_time ON capture_snapshots(device_id, capture_type, captured_at)",
            "CREATE INDEX IF NOT EXISTS idx_snapshots_hash ON capture_snapshots(content_hash)",

            # Capture changes index
            "CREATE INDEX IF NOT EXISTS idx_changes_device_time ON capture_changes(device_id, detected_at)",

            # Fingerprint extractions indexes
            "CREATE INDEX IF NOT EXISTS idx_extractions_device_timestamp ON fingerprint_extractions(device_id, extraction_timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_extractions_success ON fingerprint_extractions(extraction_success)",

            # Bulk operations index
            "CREATE INDEX IF NOT EXISTS idx_bulk_ops_timestamp ON bulk_operations(executed_at)",

            # Notes indexes
            "CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type)",
            "CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC)",

            # Note associations indexes
            "CREATE INDEX IF NOT EXISTS idx_assoc_note ON note_associations(note_id)",
            "CREATE INDEX IF NOT EXISTS idx_assoc_entity ON note_associations(entity_type, entity_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_assoc_unique ON note_associations(note_id, entity_type, entity_id)",

            # Note attachments index
            "CREATE INDEX IF NOT EXISTS idx_attach_note ON note_attachments(note_id)",
        ]

        for idx_sql in indexes:
            try:
                cursor.execute(idx_sql)
            except sqlite3.OperationalError as e:
                logger.debug(f"Index creation note: {e}")

        # ================================================================
        # TRIGGERS - Device timestamp update
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_devices_update_timestamp 
            AFTER UPDATE ON devices
            FOR EACH ROW
            BEGIN
                UPDATE devices 
                SET timestamp = datetime('now') 
                WHERE id = NEW.id;
            END
        """)

        # ================================================================
        # TRIGGERS - Device serials -> have_sn flag
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_device_serials_update_have_sn_insert
            AFTER INSERT ON device_serials
            FOR EACH ROW
            BEGIN
                UPDATE devices 
                SET have_sn = 1 
                WHERE id = NEW.device_id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_device_serials_update_have_sn_delete
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

        # ================================================================
        # TRIGGERS - Stack members -> is_stack and stack_count
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_stack_members_update_count_insert
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
            CREATE TRIGGER IF NOT EXISTS tr_stack_members_update_count_delete
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

        # ================================================================
        # TRIGGERS - Notes FTS sync
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_fts_insert 
            AFTER INSERT ON notes 
            BEGIN
                INSERT INTO note_fts(rowid, title, content, tags)
                VALUES (new.id, new.title, new.content, new.tags);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_fts_delete 
            AFTER DELETE ON notes 
            BEGIN
                DELETE FROM note_fts WHERE rowid = old.id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_fts_update 
            AFTER UPDATE ON notes 
            BEGIN
                UPDATE note_fts SET 
                    title = new.title,
                    content = new.content,
                    tags = new.tags
                WHERE rowid = new.id;
            END
        """)

        # ================================================================
        # TRIGGERS - Notes updated_at timestamp
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_update_timestamp 
            AFTER UPDATE ON notes
            FOR EACH ROW
            BEGIN
                UPDATE notes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)

        # ================================================================
        # TRIGGERS - Capture snapshots FTS sync
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS capture_fts_insert 
            AFTER INSERT ON capture_snapshots 
            BEGIN
                INSERT INTO capture_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS capture_fts_delete 
            AFTER DELETE ON capture_snapshots 
            BEGIN
                DELETE FROM capture_fts WHERE rowid = old.id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS capture_fts_update 
            AFTER UPDATE ON capture_snapshots 
            BEGIN
                UPDATE capture_fts 
                SET content = new.content 
                WHERE rowid = new.id;
            END
        """)

        # ================================================================
        # VIEWS
        # ================================================================

        cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_device_status AS
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

        cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_site_inventory AS
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

        cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_capture_coverage AS
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

        cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_capture_details AS
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
        logger.info(f"✓ Assets database schema complete: {self.assets_db}")

    def _init_arp_db(self):
        """
        Initialize arp_cat.db with complete schema.

        Schema matches arp_cat_util.py expectations exactly.
        """
        conn = sqlite3.connect(str(self.arp_db))
        cursor = conn.cursor()

        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        # ================================================================
        # DEVICES TABLE
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
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

        # ================================================================
        # CONTEXTS TABLE (VRF, VDOM, routing-instance, etc.)
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
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

        # ================================================================
        # ARP ENTRIES TABLE
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS arp_entries (
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

        # ================================================================
        # ARP SNAPSHOTS TABLE
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS arp_snapshots (
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

        # ================================================================
        # MAC VENDOR LOOKUP TABLE (OUI database)
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mac_vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oui TEXT UNIQUE NOT NULL,
                vendor_name TEXT NOT NULL,
                vendor_short TEXT,
                last_updated TEXT DEFAULT (datetime('now'))
            )
        """)

        # ================================================================
        # MAC HISTORY TABLE (tracking MAC/IP bindings over time)
        # ================================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mac_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mac_address TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                device_id INTEGER NOT NULL,
                context_id INTEGER NOT NULL,
                interface_name TEXT,
                first_seen TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen TEXT NOT NULL DEFAULT (datetime('now')),
                occurrence_count INTEGER DEFAULT 1,
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
                FOREIGN KEY (context_id) REFERENCES contexts(id) ON DELETE CASCADE,
                UNIQUE(mac_address, ip_address, device_id, context_id)
            )
        """)

        # ================================================================
        # INDEXES
        # ================================================================

        indexes = [
            # ARP entries indexes
            "CREATE INDEX IF NOT EXISTS idx_arp_entries_device_context ON arp_entries(device_id, context_id)",
            "CREATE INDEX IF NOT EXISTS idx_arp_entries_ip ON arp_entries(ip_address)",
            "CREATE INDEX IF NOT EXISTS idx_arp_entries_mac ON arp_entries(mac_address)",
            "CREATE INDEX IF NOT EXISTS idx_arp_entries_mac_ip ON arp_entries(mac_address, ip_address)",
            "CREATE INDEX IF NOT EXISTS idx_arp_entries_timestamp ON arp_entries(capture_timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_arp_entries_current ON arp_entries(is_current)",

            # Snapshots indexes
            "CREATE INDEX IF NOT EXISTS idx_snapshots_device_context ON arp_snapshots(device_id, context_id)",
            "CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON arp_snapshots(capture_timestamp)",

            # Contexts indexes
            "CREATE INDEX IF NOT EXISTS idx_contexts_device ON contexts(device_id)",
            "CREATE INDEX IF NOT EXISTS idx_contexts_name_type ON contexts(context_name, context_type)",

            # MAC tracking indexes
            "CREATE INDEX IF NOT EXISTS idx_mac_history_mac ON mac_history(mac_address)",
            "CREATE INDEX IF NOT EXISTS idx_mac_history_ip ON mac_history(ip_address)",
            "CREATE INDEX IF NOT EXISTS idx_mac_vendors_oui ON mac_vendors(oui)",
        ]

        for idx_sql in indexes:
            try:
                cursor.execute(idx_sql)
            except sqlite3.OperationalError as e:
                logger.debug(f"Index creation note: {e}")

        # ================================================================
        # TRIGGERS
        # ================================================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_update_device_last_seen
            AFTER INSERT ON arp_entries
            FOR EACH ROW
            BEGIN
                UPDATE devices
                SET last_seen_timestamp = datetime('now')
                WHERE id = NEW.device_id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_update_context_last_seen
            AFTER INSERT ON arp_entries
            FOR EACH ROW
            BEGIN
                UPDATE contexts
                SET last_seen_timestamp = datetime('now')
                WHERE id = NEW.context_id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS tr_update_snapshot_count
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

        # ================================================================
        # VIEWS
        # ================================================================

        cursor.execute("""
            CREATE VIEW IF NOT EXISTS v_current_arp AS
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
            CREATE VIEW IF NOT EXISTS v_device_summary AS
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
            CREATE VIEW IF NOT EXISTS v_mac_history AS
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
        logger.info(f"✓ ARP database schema complete: {self.arp_db}")

    def _init_users_db(self, admin_username='admin', admin_password='admin'):
        """
        Initialize users.db with complete schema from documentation

        Args:
            admin_username: Username for the admin account
            admin_password: Password for the admin account
        """
        conn = sqlite3.connect(str(self.users_db))
        cursor = conn.cursor()

        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        # ================================================================
        # USERS TABLE
        # ================================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                is_admin INTEGER DEFAULT 0,
                display_name TEXT,
                groups_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                last_login TEXT,
                auth_backend TEXT DEFAULT 'database'
            )
        """)

        # ================================================================
        # CREDENTIAL VAULT TABLES
        # ================================================================

        # User vault keys - per-user encryption key material
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_vault_keys (
                user_id INTEGER PRIMARY KEY,
                key_salt TEXT NOT NULL,
                key_check TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # User credentials - encrypted credentials per user
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                credential_name TEXT NOT NULL,
                username TEXT NOT NULL,
                password_encrypted TEXT,
                ssh_key_encrypted TEXT,
                ssh_key_passphrase_encrypted TEXT,
                is_default INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # ================================================================
        # SAVED CONNECTIONS TABLE
        # ================================================================

        # Saved connections - SSH connection profiles
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                connection_name TEXT NOT NULL,
                device_id INTEGER,
                host TEXT NOT NULL,
                port INTEGER DEFAULT 22,
                credential_id INTEGER,
                device_type TEXT,
                notes TEXT,
                last_used TEXT,
                use_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                color_tag TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (credential_id) REFERENCES user_credentials(id) ON DELETE SET NULL
            )
        """)

        # Check if admin user exists (by username)
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (admin_username,))
        admin_exists = cursor.fetchone()[0] > 0

        if not admin_exists:
            # Create admin user
            import bcrypt

            password_hash = bcrypt.hashpw(
                admin_password.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            now = datetime.now().isoformat()

            # Generate email from username
            admin_email = f"{admin_username}@localhost"

            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, is_active, is_admin,
                    display_name, groups_json, auth_backend,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                admin_username,
                admin_email,
                password_hash,
                1,  # is_active
                1,  # is_admin
                'Administrator',
                '["admin"]',
                'database',
                now,
                now
            ))

            logger.info(f"✓ Admin user created ({admin_username})")
        else:
            logger.info(f"✓ Admin user '{admin_username}' already exists")

        conn.commit()
        conn.close()
        logger.info(f"✓ Users database schema complete: {self.users_db}")


# ================================================================
# CONVENIENCE FUNCTIONS
# ================================================================

def initialize_databases(data_dir='~/.velocitycmdb/data', admin_username='admin', admin_password='admin'):
    """
    Convenience function to initialize all databases

    Args:
        data_dir: Directory where databases will be created
        admin_username: Username for admin account (default: 'admin')
        admin_password: Password for default admin user

    Returns:
        (success: bool, message: str)
    """
    initializer = DatabaseInitializer(data_dir)
    return initializer.initialize_all(admin_username, admin_password)


def reset_databases(data_dir='~/.velocitycmdb/data'):
    """
    Delete all databases (use with caution!)

    Args:
        data_dir: Directory where databases are located

    Returns:
        (success: bool, message: str)
    """
    data_path = Path(data_dir).expanduser()

    if not data_path.exists():
        return True, "Data directory does not exist"

    try:
        for db_file in ['assets.db', 'arp_cat.db', 'users.db']:
            db_path = data_path / db_file
            if db_path.exists():
                db_path.unlink()
                logger.info(f"✓ Deleted {db_file}")

        return True, "All databases deleted successfully"

    except Exception as e:
        logger.exception("Failed to delete databases")
        return False, f"Reset failed: {str(e)}"


if __name__ == '__main__':
    # For testing
    logging.basicConfig(level=logging.INFO)
    success, message = initialize_databases()
    print(f"{'✓' if success else '✗'} {message}")