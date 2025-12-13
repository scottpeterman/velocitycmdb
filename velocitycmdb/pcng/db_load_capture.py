#!/usr/bin/env python3
"""
Capture Files Database Loader
Loads network device capture files into the asset management database
Stores ALL captures as snapshots for search/viewing
Only tracks CHANGES for critical types (configs, version, inventory)
"""

import os
import sqlite3
import re
import hashlib
import difflib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging
import click

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CaptureLoader:
    """Main loader class for processing network capture files"""

    # Expected capture types based on your directory structure
    CAPTURE_TYPES = [
        'arp',
        'configs',
        'etherchannel',
        'interface-status',
        'inventory',
        'lldp',
        'lldp-detail',
        'mac',
        'routes',
        'version',
    ]

    # Capture types that get change tracking (all get stored as snapshots)
    CHANGE_TRACKED_TYPES = {'configs', 'version', 'inventory'}

    def __init__(self, db_path: str, data_dir: Path, diff_subdir: str = 'diffs'):
        """
        Initialize capture loader

        Args:
            db_path: Path to SQLite database
            data_dir: Base data directory (VELOCITYCMDB_DATA_DIR)
            diff_subdir: Subdirectory name for diffs within data_dir
        """
        self.db_path = db_path
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.diff_output_dir = self.data_dir / diff_subdir
        self.diff_output_dir.mkdir(parents=True, exist_ok=True)
        self.device_cache = {}  # Cache device IDs by normalized name

        logger.info(f"Data directory: {self.data_dir}")
        logger.info(f"Diff output directory: {self.diff_output_dir}")

    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection with foreign keys enabled"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _update_current_capture(self, conn, device_id: int, capture_type: str,
                                file_path: Path, file_size: int, capture_timestamp: datetime):
        """
        Update device_captures_current table for dashboard visibility
        This method now takes a connection object instead of cursor for better transaction control
        """
        cursor = conn.cursor()
        extraction_success = self.determine_extraction_success(file_path, capture_type)
        command_used = self.determine_command_used(capture_type)

        try:
            # Check if this capture already exists
            cursor.execute("""
                SELECT id FROM device_captures_current 
                WHERE device_id = ? AND capture_type = ?
            """, (device_id, capture_type))

            existing = cursor.fetchone()

            if existing:
                # Update current capture
                cursor.execute("""
                    UPDATE device_captures_current SET
                        file_path = ?, 
                        file_size = ?, 
                        capture_timestamp = ?,
                        extraction_success = ?, 
                        command_used = ?
                    WHERE id = ?
                """, (str(file_path), file_size, capture_timestamp.isoformat(),
                      extraction_success, command_used, existing['id']))
                logger.debug(f"  ✓ Updated device_captures_current: device_id={device_id}, type={capture_type}")
            else:
                # Insert new current capture
                cursor.execute("""
                    INSERT INTO device_captures_current (
                        device_id, capture_type, file_path, file_size,
                        capture_timestamp, extraction_success, command_used
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (device_id, capture_type, str(file_path), file_size,
                      capture_timestamp.isoformat(), extraction_success, command_used))
                logger.debug(f"  ✓ Inserted into device_captures_current: device_id={device_id}, type={capture_type}")

            # Commit immediately to ensure it's persisted
            conn.commit()

        except Exception as e:
            logger.error(f"  ✗ Failed to update device_captures_current: {e}")
            conn.rollback()
            raise

    def load_capture_snapshot(self, file_path: Path, device_id: int, site_code: str,
                              device_name: str, capture_type: str) -> bool:
        """
        Load capture as snapshot (always stores in DB)
        Only creates change records for CHANGE_TRACKED_TYPES
        """
        conn = None
        try:
            # Read file content
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            file_size, capture_timestamp = self.get_file_stats(file_path)

            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Get previous snapshot
            cursor.execute("""
                SELECT id, content, content_hash, file_path
                FROM capture_snapshots 
                WHERE device_id = ? AND capture_type = ?
                ORDER BY captured_at DESC LIMIT 1
            """, (device_id, capture_type))

            previous = cursor.fetchone()
            if previous:
                logger.debug(f"  Found previous snapshot: {previous['file_path']}")

            # ALWAYS update device_captures_current first (for dashboard)
            self._update_current_capture(conn, device_id, capture_type,
                                         file_path, file_size, capture_timestamp)

            # Skip snapshot creation if unchanged
            if previous and previous['content_hash'] == content_hash:
                logger.debug(f"  No change detected: {device_name} {capture_type} (current capture updated)")
                return True

            # Insert new snapshot (ALL types get stored)
            cursor.execute("""
                INSERT INTO capture_snapshots 
                (device_id, capture_type, captured_at, file_path, file_size, content, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (device_id, capture_type, capture_timestamp.isoformat(),
                  str(file_path), file_size, content, content_hash))

            new_snapshot_id = cursor.lastrowid
            logger.debug(f"  Created snapshot ID {new_snapshot_id}")

            # Only create change records for tracked types
            if capture_type in self.CHANGE_TRACKED_TYPES and previous:
                diff_content = self.generate_diff(previous['content'], content, capture_type)

                # Only create change record if diff is non-empty
                if diff_content.strip():
                    diff_path = self.save_diff_file(device_id, capture_type, capture_timestamp, diff_content)

                    lines_added = diff_content.count('\n+')
                    lines_removed = diff_content.count('\n-')
                    severity = self.classify_severity(capture_type, diff_content)

                    cursor.execute("""
                        INSERT INTO capture_changes
                        (device_id, capture_type, detected_at, previous_snapshot_id, 
                         current_snapshot_id, lines_added, lines_removed, diff_path, severity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (device_id, capture_type, datetime.now().isoformat(), previous['id'],
                          new_snapshot_id, lines_added, lines_removed, diff_path, severity))

                    logger.info(f"  CHANGE DETECTED: {device_name} {capture_type} "
                                f"(+{lines_added}/-{lines_removed} lines, {severity})")
                else:
                    logger.debug(f"  No meaningful changes after normalization: {device_name} {capture_type}")
            else:
                if capture_type in self.CHANGE_TRACKED_TYPES:
                    logger.info(f"  Initial snapshot: {device_name} {capture_type}")
                else:
                    logger.debug(f"  Stored snapshot (no change tracking): {device_name} {capture_type}")

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"  Error loading snapshot {file_path}: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()

    def extract_device_info_from_filename(self, file_path: Path) -> Optional[Tuple[str, str, str]]:
        """
        Extract device info from capture filename
        Expected formats:
        - device-name.site-code.txt (e.g., tor412.iad2.txt)
          → device: tor412.iad2 (full name)
          → site: IAD2 (extracted from suffix)

        Returns: (site_code, device_name, capture_type) or None
        """
        filename = file_path.name
        parent_dir = file_path.parent.name

        # Remove common extensions
        name_without_ext = re.sub(r'\.(txt|log|cfg|conf)$', '', filename, flags=re.IGNORECASE)

        # Pattern 1: parent directory is capture type
        if parent_dir in self.CAPTURE_TYPES:
            capture_type = parent_dir
            device_part = name_without_ext
        else:
            # Pattern 2: capture type in filename
            capture_type = None
            for ct in self.CAPTURE_TYPES:
                patterns = [
                    f'_{ct}$',
                    f'_{ct}_',
                    f'\\.{ct}$',
                    f'_{ct.replace("-", "_")}$',
                    f'_{ct.replace("-", "-")}$'
                ]

                for pattern in patterns:
                    if re.search(pattern, name_without_ext, re.IGNORECASE):
                        capture_type = ct
                        device_part = re.sub(pattern, '', name_without_ext, flags=re.IGNORECASE)
                        break

                if capture_type:
                    break

            if not capture_type:
                logger.warning(f"Could not determine capture type for: {filename}")
                return None

        # Extract site code from device name (device.siteXX pattern)
        # Keep full device name INCLUDING site suffix
        site_match = re.search(r'\.([a-z]{3,4}\d+)$', device_part, re.IGNORECASE)
        if site_match:
            site_code = site_match.group(1).upper()  # e.g., IAD2
            device_name = device_part.lower()  # e.g., tor412.iad2 (keep full name)
        else:
            # No site suffix found - use UNKNOWN
            site_code = "UNKNOWN"
            device_name = device_part.lower()

        return site_code, device_name, capture_type

    def get_device_id_by_name(self, conn: sqlite3.Connection, device_name: str, site_code: str = None) -> Optional[int]:
        """Get device ID by normalized name (site_code parameter kept for compatibility but ignored)"""
        if device_name in self.device_cache:
            return self.device_cache[device_name]

        cursor = conn.cursor()

        # Match only by device name - devices are unique
        cursor.execute("SELECT id FROM devices WHERE normalized_name = ?", (device_name,))

        row = cursor.fetchone()
        if row:
            device_id = row['id']
            self.device_cache[device_name] = device_id
            return device_id

        # No match found
        return None

    def get_file_stats(self, file_path: Path) -> Tuple[int, datetime]:
        """Get file size and modification time"""
        stat = file_path.stat()
        return stat.st_size, datetime.fromtimestamp(stat.st_mtime)

    def determine_extraction_success(self, file_path: Path, capture_type: str) -> bool:
        """Determine if capture was successful based on file size"""
        try:
            file_size = file_path.stat().st_size

            if file_size < 50:
                return False

            if capture_type in ['configs', 'config']:
                return file_size > 1000

            return file_size > 100

        except Exception:
            return False

    def determine_command_used(self, capture_type: str) -> str:
        """Map capture type to likely command used"""
        command_mapping = {
            'arp': 'show arp',
            'configs': 'show running-config',
            'etherchannel': 'show etherchannel summary',
            'interface-status': 'show interface status',
            'inventory': 'show inventory',
            'lldp': 'show lldp neighbors',
            'lldp-detail': 'show lldp neighbors detail',
            'mac': 'show mac address-table',
            'routes': 'show ip route',
            'version': 'show version',
        }
        return command_mapping.get(capture_type, f'show {capture_type}')

    def normalize_config_for_diff(self, content: str, capture_type: str) -> str:
        """Remove noise/dynamic content before generating diffs"""
        if capture_type not in self.CHANGE_TRACKED_TYPES:
            return content

        # Generic noise patterns - timestamps and dynamic banners
        noise_patterns = [
            r'^Last login:.*$',
            r'^! Last configuration change at.*$',
            r'^Building configuration.*$',
            r'^Current configuration : \d+ bytes$',
            r'^! NVRAM config last updated.*$',
            r'^\s*!\s*Time:.*$',
            r'^.*ntp clock-period.*$',  # NTP drift compensation
            r'^.*Your previous successful login.*$',
            r'^.*was on \d{4}-\d{2}-\d{2}.*$',
            r'^.*from \d+\.\d+\.\d+\.\d+.*$',
        ]

        lines = []
        for line in content.splitlines():
            # Skip lines matching noise patterns
            if any(re.match(pattern, line.strip()) for pattern in noise_patterns):
                continue
            lines.append(line)

        # Clean excessive whitespace
        result = '\n'.join(lines)
        result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
        return result.strip()

    def generate_diff(self, old_content: str, new_content: str, capture_type: str = 'configs') -> str:
        """Generate unified diff between two text contents, filtering noise"""
        # Normalize before diffing
        old_normalized = self.normalize_config_for_diff(old_content, capture_type)
        new_normalized = self.normalize_config_for_diff(new_content, capture_type)

        old_lines = old_normalized.splitlines(keepends=True)
        new_lines = new_normalized.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile='previous',
            tofile='current',
            lineterm=''
        )

        return ''.join(diff)

    def save_diff_file(self, device_id: int, capture_type: str, timestamp: datetime, diff_content: str) -> str:
        """
        Save diff to file and return RELATIVE path (relative to data_dir)

        This ensures the path stored in DB can be resolved by the web UI
        using: data_dir / diff_path
        """
        # Create directory structure: {data_dir}/diffs/device_id/capture_type/
        device_dir = self.diff_output_dir / str(device_id) / capture_type
        device_dir.mkdir(parents=True, exist_ok=True)

        # Filename with timestamp
        filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}.diff"
        diff_path = device_dir / filename

        diff_path.write_text(diff_content)

        # Return path RELATIVE to data_dir for DB storage
        # This allows the web UI to resolve: data_dir / relative_path
        try:
            relative_path = diff_path.relative_to(self.data_dir)
            logger.debug(f"  Diff saved: {diff_path} (stored as: {relative_path})")
            return str(relative_path)
        except ValueError:
            # Fallback if somehow not relative to data_dir
            logger.warning(f"  Diff path {diff_path} not relative to {self.data_dir}, storing absolute")
            return str(diff_path)

    def classify_severity(self, capture_type: str, diff_content: str) -> str:
        """Classify change severity based on capture type and diff size"""
        lines_added = diff_content.count('\n+')
        lines_removed = diff_content.count('\n-')
        total_changes = lines_added + lines_removed

        # Critical: large config changes
        if capture_type == 'configs' and total_changes > 50:
            return 'critical'

        # Version changes: check if it's just uptime/memory stats
        if capture_type == 'version':
            if self._is_uptime_only_change(diff_content):
                return 'minor'
            # Actual version/firmware changes are still critical
            return 'critical'

        # Moderate: any config change
        if capture_type == 'configs' and total_changes > 0:
            return 'moderate'

        # Moderate: inventory changes (hardware swap)
        if capture_type == 'inventory' and total_changes > 5:
            return 'moderate'

        return 'minor'

    def _is_uptime_only_change(self, diff_content: str) -> bool:
        """Check if version diff only contains uptime/memory/timestamp changes"""
        significant_changes = []

        for line in diff_content.splitlines():
            # Skip diff metadata
            if line.startswith(('---', '+++', '@@', ' ')):
                continue

            # Check for actual change lines
            if line.startswith(('+', '-')):
                # Ignore lines that are just dynamic stats
                lower_line = line.lower()
                if any(keyword in lower_line for keyword in
                       ['uptime:', 'uptime ', 'free memory:', 'total memory:',
                        'last reboot', 'system time:', 'current time:', 'processor load']):
                    continue

                # This is a significant change
                significant_changes.append(line)

        # If no significant changes found, it's uptime-only
        return len(significant_changes) == 0

    def load_capture_file(self, file_path: Path) -> bool:
        """Load a single capture file into the database"""
        try:
            # Extract device and capture info from filename
            device_info = self.extract_device_info_from_filename(file_path)
            if not device_info:
                logger.warning(f"Could not parse filename: {file_path}")
                return False

            site_code, device_name, capture_type = device_info

            # Find device ID
            conn = self.get_db_connection()
            device_id = self.get_device_id_by_name(conn, device_name, site_code)
            conn.close()

            if not device_id:
                logger.warning(f"Device not found for file: {file_path} "
                               f"(device: {device_name}, site: {site_code})")
                return False

            logger.debug(f"Processing: {device_name} ({capture_type})")

            # ALL captures go through snapshot storage
            return self.load_capture_snapshot(file_path, device_id, site_code,
                                              device_name, capture_type)

        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def load_captures_directory(self, captures_dir: Path, capture_types: List[str] = None) -> Dict[str, int]:
        """Load capture files from directory structure"""
        results = {
            'success': 0,
            'failed': 0,
            'total': 0,
            'by_type': {},
            'changes_detected': 0,
            'snapshots_created': 0
        }

        if not captures_dir.exists():
            logger.error(f"Captures directory not found: {captures_dir}")
            return results

        types_to_process = capture_types or self.CAPTURE_TYPES

        # Collect all files to process
        files_to_process = []

        for capture_type in types_to_process:
            type_dir = captures_dir / capture_type
            if type_dir.exists() and type_dir.is_dir():
                patterns = ['*.txt']
                for pattern in patterns:
                    files_to_process.extend(type_dir.glob(pattern))

                results['by_type'][capture_type] = 0
            else:
                logger.warning(f"Capture type directory not found: {type_dir}")

        results['total'] = len(files_to_process)
        logger.info(f"Found {results['total']} capture files to process")

        # Track changes before processing
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM capture_changes")
        changes_before = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
        snapshots_before = cursor.fetchone()[0]
        conn.close()

        # Process files
        for i, file_path in enumerate(files_to_process, 1):
            if self.load_capture_file(file_path):
                results['success'] += 1
                device_info = self.extract_device_info_from_filename(file_path)
                if device_info:
                    capture_type = device_info[2]
                    if capture_type in results['by_type']:
                        results['by_type'][capture_type] += 1
            else:
                results['failed'] += 1

            if i % 100 == 0 or i == results['total']:
                logger.info(f"Processed {i}/{results['total']} files "
                            f"({results['success']} success, {results['failed']} failed)")

        # Count changes and snapshots
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM capture_changes")
        changes_after = cursor.fetchone()[0]
        results['changes_detected'] = changes_after - changes_before

        cursor.execute("SELECT COUNT(*) FROM capture_snapshots")
        snapshots_after = cursor.fetchone()[0]
        results['snapshots_created'] = snapshots_after - snapshots_before
        conn.close()

        return results

    def get_recent_changes_summary(self, hours: int = 24) -> List[Dict]:
        """Get summary of recent changes"""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    cc.detected_at,
                    d.name as device_name,
                    s.name as site_name,
                    cc.capture_type,
                    cc.lines_added,
                    cc.lines_removed,
                    cc.severity
                FROM capture_changes cc
                JOIN devices d ON cc.device_id = d.id
                LEFT JOIN sites s ON d.site_code = s.code
                WHERE cc.detected_at > ?
                ORDER BY cc.detected_at DESC
            """, (cutoff,))

            return [dict(row) for row in cursor.fetchall()]


@click.command()
@click.option('--data-dir', envvar='VELOCITYCMDB_DATA_DIR',
              default='~/.velocitycmdb/data',
              help='Base data directory (default: ~/.velocitycmdb/data or VELOCITYCMDB_DATA_DIR env)')
@click.option('--db-path', default=None,
              help='Path to SQLite database (default: {data-dir}/assets.db)')
@click.option('--captures-dir', default=None,
              help='Directory containing capture subdirectories (default: {data-dir}/capture)')
@click.option('--diff-subdir', default='diffs',
              help='Subdirectory name for diffs within data-dir (default: diffs)')
@click.option('--capture-types', help='Comma-separated list of capture types to process')
@click.option('--single-file', help='Process a single capture file')
@click.option('--show-changes', is_flag=True, help='Show recent changes after loading')
@click.option('--changes-hours', default=24, help='Hours of change history to show (default: 24)')
@click.option('--verbose', '-v', is_flag=True, help='Verbose logging')
def main(data_dir, db_path, captures_dir, diff_subdir, capture_types, single_file,
         show_changes, changes_hours, verbose):
    """Load network capture files into the asset management database with change tracking"""

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve data_dir
    data_dir = Path(data_dir).expanduser().resolve()
    logger.info(f"Using data directory: {data_dir}")

    # Default paths relative to data_dir
    if db_path is None:
        db_path = str(data_dir / 'assets.db')

    if captures_dir is None:
        captures_dir = str(data_dir / 'capture')

    logger.info(f"Database: {db_path}")
    logger.info(f"Captures directory: {captures_dir}")
    logger.info(f"Diffs will be stored in: {data_dir / diff_subdir}")

    loader = CaptureLoader(db_path, data_dir, diff_subdir)

    if single_file:
        file_path = Path(single_file)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return

        logger.info(f"Processing single file: {file_path}")
        success = loader.load_capture_file(file_path)
        if success:
            logger.info("File processed successfully")
        else:
            logger.error("Failed to process file")
    else:
        captures_path = Path(captures_dir)
        logger.info(f"Loading captures from: {captures_path}")
        logger.info(f"All captures stored as snapshots")
        logger.info(f"Change tracking enabled for: {', '.join(loader.CHANGE_TRACKED_TYPES)}")

        types_list = None
        if capture_types:
            types_list = [ct.strip() for ct in capture_types.split(',')]
            logger.info(f"Processing capture types: {types_list}")

        results = loader.load_captures_directory(captures_path, types_list)

        # Print summary to stdout (captured by subprocess)
        print("=" * 70)
        print("CAPTURE LOADING RESULTS")
        print("=" * 70)
        print(f"Total files: {results['total']}")
        print(f"Successfully loaded: {results['success']}")
        print(f"Failed: {results['failed']}")
        print(f"Snapshots created/updated: {results['snapshots_created']}")
        print(f"Changes detected: {results['changes_detected']}")
        if results['total'] > 0:
            print(f"Success rate: {results['success'] / results['total'] * 100:.1f}%")

        # Also log for file logs
        logger.info("=" * 70)
        logger.info("CAPTURE LOADING RESULTS")
        logger.info("=" * 70)
        logger.info(f"Total files: {results['total']}")
        logger.info(f"Successfully loaded: {results['success']}")
        logger.info(f"Failed: {results['failed']}")
        logger.info(f"Snapshots created/updated: {results['snapshots_created']}")
        logger.info(f"Changes detected: {results['changes_detected']}")
        if results['total'] > 0:
            logger.info(f"Success rate: {results['success'] / results['total'] * 100:.1f}%")

        logger.info("\nBy capture type:")
        for capture_type, count in sorted(results['by_type'].items()):
            tracked = " [CHANGE TRACKING]" if capture_type in loader.CHANGE_TRACKED_TYPES else " [STORED]"
            logger.info(f"  {capture_type}: {count}{tracked}")

    if show_changes:
        logger.info("\n" + "=" * 70)
        logger.info(f"RECENT CHANGES (Last {changes_hours} hours)")
        logger.info("=" * 70)

        changes = loader.get_recent_changes_summary(changes_hours)
        if changes:
            for change in changes:
                logger.info(f"{change['detected_at']} | {change['device_name']} ({change['site_name']}) | "
                            f"{change['capture_type']} | +{change['lines_added']}/-{change['lines_removed']} | "
                            f"{change['severity'].upper()}")
        else:
            logger.info("No changes detected in this period")


if __name__ == '__main__':
    main()