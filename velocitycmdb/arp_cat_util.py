#!/usr/bin/env python3
"""
ARP Cat Utility Module

This module provides functionality for tracking ARP information over time
in a SQLite database with support for various network contexts (VRF, VDOM, etc.).
"""

import sqlite3
import re
import logging
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Union
from pathlib import Path
import ipaddress

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ArpCatUtil:
    """Main utility class for ARP Cat operations."""

    def __init__(self, db_path: str = "arp_cat.db"):
        """
        Initialize ARP Cat utility.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database connection and create schema if needed."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute("PRAGMA foreign_keys = ON")

            # Check if tables exist, create if not
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='devices'
            """)

            if not cursor.fetchone():
                self._create_schema()

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def _create_schema(self):
        """Create database schema from SQL file or embedded schema."""
        # Note: In production, you'd load this from the schema file
        # For now, this is a placeholder - you would execute the schema SQL here
        logger.info("Creating database schema...")
        # Execute the schema SQL from the previous artifact
        pass

    def normalize_mac_address(self, mac: str) -> str:
        """
        Normalize MAC address to standard format (lowercase, colon-separated).
        Handles vendor-specific formats:
        - Cisco: aabb.ccdd.eeff
        - Standard: aa:bb:cc:dd:ee:ff
        - HP: aabbcc-ddeeff
        - Other formats

        Args:
            mac: MAC address in any common format

        Returns:
            Normalized MAC address (e.g., 'aa:bb:cc:dd:ee:ff')
        """
        if not mac:
            return ""

        # Remove all non-alphanumeric characters first
        clean_mac = re.sub(r'[^a-fA-F0-9]', '', mac.strip())

        # Validate length
        if len(clean_mac) != 12:
            raise ValueError(f"Invalid MAC address length: {mac} (cleaned: {clean_mac})")

        # Validate hex characters
        try:
            int(clean_mac, 16)
        except ValueError:
            raise ValueError(f"Invalid MAC address format: {mac}")

        # Convert to lowercase and add colons
        normalized = ':'.join([clean_mac[i:i + 2] for i in range(0, 12, 2)]).lower()

        return normalized

    def validate_ip_address(self, ip: str) -> bool:
        """
        Validate IP address format.

        Args:
            ip: IP address string

        Returns:
            True if valid IP address
        """
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def get_or_create_device(self, hostname: str, **kwargs) -> int:
        """
        Get existing device ID or create new device.

        Args:
            hostname: Device hostname
            **kwargs: Additional device attributes

        Returns:
            Device ID
        """
        cursor = self.conn.cursor()
        normalized_hostname = hostname.lower().strip()

        # Try to find existing device
        cursor.execute("""
            SELECT id FROM devices WHERE normalized_hostname = ?
        """, (normalized_hostname,))

        result = cursor.fetchone()
        if result:
            # Update last_seen_timestamp
            cursor.execute("""
                UPDATE devices 
                SET last_seen_timestamp = datetime('now')
                WHERE id = ?
            """, (result[0],))
            self.conn.commit()
            return result[0]

        # Create new device
        cursor.execute("""
            INSERT INTO devices (
                hostname, normalized_hostname, device_type, vendor, 
                model, site_code, management_ip
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            hostname,
            normalized_hostname,
            kwargs.get('device_type'),
            kwargs.get('vendor'),
            kwargs.get('model'),
            kwargs.get('site_code'),
            kwargs.get('management_ip')
        ))

        self.conn.commit()
        return cursor.lastrowid

    def get_or_create_context(self, device_id: int, context_name: str = 'default',
                              context_type: str = 'vrf', description: str = None) -> int:
        """
        Get existing context ID or create new context.

        Args:
            device_id: Device ID
            context_name: Context name (default: 'default')
            context_type: Context type (default: 'vrf')
            description: Optional description

        Returns:
            Context ID
        """
        cursor = self.conn.cursor()

        # Try to find existing context
        cursor.execute("""
            SELECT id FROM contexts 
            WHERE device_id = ? AND context_name = ? AND context_type = ?
        """, (device_id, context_name, context_type))

        result = cursor.fetchone()
        if result:
            # Update last_seen_timestamp
            cursor.execute("""
                UPDATE contexts 
                SET last_seen_timestamp = datetime('now')
                WHERE id = ?
            """, (result[0],))
            self.conn.commit()
            return result[0]

        # Create new context
        cursor.execute("""
            INSERT INTO contexts (
                device_id, context_name, context_type, description
            ) VALUES (?, ?, ?, ?)
        """, (device_id, context_name, context_type, description))

        self.conn.commit()
        return cursor.lastrowid

    def add_arp_entry(self, device_id: int, context_id: int, ip_address: str,
                      mac_address: str, **kwargs) -> int:
        """
        Add ARP entry to database.

        Args:
            device_id: Device ID
            context_id: Context ID
            ip_address: IP address
            mac_address: MAC address (will be normalized)
            **kwargs: Additional ARP entry attributes

        Returns:
            ARP entry ID
        """
        # Validate IP address
        if not self.validate_ip_address(ip_address):
            raise ValueError(f"Invalid IP address: {ip_address}")

        # Normalize MAC address
        mac_normalized = self.normalize_mac_address(mac_address)

        cursor = self.conn.cursor()

        # Mark previous entries as not current for this IP/MAC combo
        cursor.execute("""
            UPDATE arp_entries 
            SET is_current = 0 
            WHERE device_id = ? AND context_id = ? AND ip_address = ?
        """, (device_id, context_id, ip_address))

        # Insert new entry
        cursor.execute("""
            INSERT INTO arp_entries (
                device_id, context_id, ip_address, mac_address, mac_address_raw,
                interface_name, entry_type, age, protocol, capture_timestamp,
                source_file, source_command, is_current
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            device_id,
            context_id,
            ip_address,
            mac_normalized,
            mac_address,  # Keep original format
            kwargs.get('interface_name'),
            kwargs.get('entry_type', 'dynamic'),
            kwargs.get('age'),
            kwargs.get('protocol', 'IPv4'),
            kwargs.get('capture_timestamp', datetime.now().isoformat()),
            kwargs.get('source_file'),
            kwargs.get('source_command')
        ))

        self.conn.commit()
        return cursor.lastrowid

    def create_snapshot(self, device_id: int, context_id: int,
                        capture_timestamp: str = None, **kwargs) -> int:
        """
        Create ARP snapshot record.

        Args:
            device_id: Device ID
            context_id: Context ID
            capture_timestamp: When snapshot was taken
            **kwargs: Additional snapshot attributes

        Returns:
            Snapshot ID
        """
        if not capture_timestamp:
            capture_timestamp = datetime.now().isoformat()

        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO arp_snapshots (
                device_id, context_id, capture_timestamp, source_file,
                source_command, processing_status
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            device_id,
            context_id,
            capture_timestamp,
            kwargs.get('source_file'),
            kwargs.get('source_command'),
            kwargs.get('processing_status', 'pending')
        ))

        self.conn.commit()
        return cursor.lastrowid

    def search_mac(self, mac_address: str, history: bool = False) -> List[Dict]:
        """Search for MAC address across all entries."""
        try:
            normalized_mac = self.normalize_mac_address(mac_address)
        except ValueError as e:
            logger.error(f"Invalid MAC address for search: {e}")
            return []

        cursor = self.conn.cursor()

        if history:
            cursor.execute("""
                SELECT * FROM v_mac_history 
                WHERE mac_address = ?
                ORDER BY capture_timestamp DESC
            """, (normalized_mac,))
        else:
            cursor.execute("""
                SELECT * FROM v_current_arp 
                WHERE mac_address = ?
                ORDER BY capture_timestamp DESC
            """, (normalized_mac,))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def search_ip(self, ip_address: str, history: bool = False) -> List[Dict]:
        """Search for IP address across all entries."""
        if not self.validate_ip_address(ip_address):
            logger.error(f"Invalid IP address for search: {ip_address}")
            return []

        cursor = self.conn.cursor()

        if history:
            cursor.execute("""
                SELECT * FROM v_mac_history 
                WHERE ip_address = ?
                ORDER BY capture_timestamp DESC
            """, (ip_address,))
        else:
            cursor.execute("""
                SELECT * FROM v_current_arp 
                WHERE ip_address = ?
                ORDER BY capture_timestamp DESC
            """, (ip_address,))

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_device_summary(self, hostname: str = None) -> List[Dict]:
        """
        Get device summary information.

        Args:
            hostname: Optional hostname filter

        Returns:
            List of device summaries
        """
        cursor = self.conn.cursor()

        if hostname:
            cursor.execute("""
                SELECT * FROM v_device_summary 
                WHERE hostname = ?
            """, (hostname,))
        else:
            cursor.execute("SELECT * FROM v_device_summary")

        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_statistics(self) -> Dict:
        """
        Get overall database statistics.

        Returns:
            Dictionary with various statistics
        """
        cursor = self.conn.cursor()

        stats = {}

        # Device count
        cursor.execute("SELECT COUNT(*) FROM devices")
        stats['total_devices'] = cursor.fetchone()[0]

        # Total ARP entries
        cursor.execute("SELECT COUNT(*) FROM arp_entries")
        stats['total_arp_entries'] = cursor.fetchone()[0]

        # Current entries
        cursor.execute("SELECT COUNT(*) FROM arp_entries WHERE is_current = 1")
        stats['current_entries'] = cursor.fetchone()[0]

        # Unique MACs
        cursor.execute("SELECT COUNT(DISTINCT mac_address) FROM arp_entries")
        stats['unique_macs'] = cursor.fetchone()[0]

        # Context count
        cursor.execute("SELECT COUNT(*) FROM contexts")
        stats['total_contexts'] = cursor.fetchone()[0]

        # Snapshot count
        cursor.execute("SELECT COUNT(*) FROM arp_snapshots")
        stats['total_snapshots'] = cursor.fetchone()[0]

        # Latest capture timestamp
        cursor.execute("SELECT MAX(capture_timestamp) FROM arp_entries")
        stats['latest_capture'] = cursor.fetchone()[0]

        return stats

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class ArpParser:
    """Base class for parsing ARP output from different vendors."""

    def __init__(self, arp_util: ArpCatUtil):
        """
        Initialize parser.

        Args:
            arp_util: ArpCatUtil instance
        """
        self.arp_util = arp_util

    def parse_file(self, file_path: str, device_info: Dict,
                   context_info: Dict = None) -> int:
        """
        Parse ARP file and add entries to database.

        Args:
            file_path: Path to ARP output file
            device_info: Device information dict
            context_info: Context information dict

        Returns:
            Number of entries processed
        """
        raise NotImplementedError("Subclasses must implement parse_file")


class CiscoArpParser(ArpParser):
    """Parser for Cisco ARP output."""

    def parse_file(self, file_path: str, device_info: Dict,
                   context_info: Dict = None) -> int:
        """Parse Cisco ARP file."""
        if not context_info:
            context_info = {'context_name': 'default', 'context_type': 'vrf'}

        # Get or create device and context
        device_id = self.arp_util.get_or_create_device(**device_info)
        context_id = self.arp_util.get_or_create_context(device_id, **context_info)

        # Create snapshot
        file_stat = os.stat(file_path)
        capture_timestamp = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

        snapshot_id = self.arp_util.create_snapshot(
            device_id, context_id, capture_timestamp,
            source_file=str(file_path),
            source_command='show ip arp'
        )

        entries_count = 0

        with open(file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('Protocol'):
                    continue

                # Parse Cisco ARP line format:
                # Internet  192.168.1.1      0   aabb.ccdd.eeff  ARPA   GigabitEthernet0/1
                match = re.match(
                    r'Internet\s+(\S+)\s+(\S+)\s+([a-fA-F0-9.]+)\s+(\S+)\s+(\S+)',
                    line
                )

                if match:
                    ip_addr, age, mac_addr, entry_type, interface = match.groups()

                    try:
                        self.arp_util.add_arp_entry(
                            device_id, context_id, ip_addr, mac_addr,
                            interface_name=interface,
                            entry_type=entry_type,
                            age=age,
                            capture_timestamp=capture_timestamp,
                            source_file=str(file_path),
                            source_command='show ip arp'
                        )
                        entries_count += 1
                    except Exception as e:
                        logger.warning(f"Error processing line {line_num} in {file_path}: {e}")

        logger.info(f"Processed {entries_count} ARP entries from {file_path}")
        return entries_count


# Factory function for getting the right parser
def get_parser(vendor: str, arp_util: ArpCatUtil) -> ArpParser:
    """
    Get appropriate parser for vendor.

    Args:
        vendor: Vendor name
        arp_util: ArpCatUtil instance

    Returns:
        Parser instance
    """
    vendor_lower = vendor.lower()

    if vendor_lower in ['cisco', 'ios', 'nxos']:
        return CiscoArpParser(arp_util)
    else:
        raise ValueError(f"No parser available for vendor: {vendor}")


if __name__ == "__main__":
    # Example usage
    with ArpCatUtil() as util:
        # Example device
        device_info = {
            'hostname': 'router01.example.com',
            'device_type': 'router',
            'vendor': 'cisco',
            'site_code': 'NYC01'
        }

        # Search examples
        results = util.search_mac('aa:bb:cc:dd:ee:ff')
        print(f"MAC search results: {len(results)} entries")

        summary = util.get_device_summary()
        print(f"Device summary: {len(summary)} devices")