#!/usr/bin/env python3
"""
ARP Cat Loader

Loads ARP capture files from assets.db using the v_capture_details view
and processes them through TextFSM parsing into the arp_cat.db database.
"""

import os
import sys
import sqlite3
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import ipaddress

# Import our ARP Cat utility
from arp_cat_util import ArpCatUtil, get_parser

# Import TextFSM engine if available
try:
    from tfsm_fire import TextFSMAutoEngine

    TEXTFSM_AVAILABLE = True
except ImportError:
    try:
        sys.path.append('./VCMDB')
        from tfsm_fire import TextFSMAutoEngine

        TEXTFSM_AVAILABLE = True
    except ImportError:
        TEXTFSM_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ArpCaptureLoader:
    """Loads ARP captures from assets.db and processes them into arp_cat.db"""

    def __init__(self, assets_db_path: str = "assets.db",
                 arp_cat_db_path: str = "arp_cat.db",
                 textfsm_db_path: str = "Anguis/tfsm_templates.db"):
        """
        Initialize the ARP capture loader.

        Args:
            assets_db_path: Path to assets database
            arp_cat_db_path: Path to ARP cat database
            textfsm_db_path: Path to TextFSM templates database
        """
        self.assets_db_path = assets_db_path
        self.arp_cat_db_path = arp_cat_db_path
        self.textfsm_db_path = textfsm_db_path
        self.textfsm_engine = None

        # Initialize TextFSM engine
        self._initialize_textfsm()

    def _initialize_textfsm(self):
        """Initialize TextFSM engine with fallback paths"""
        if not TEXTFSM_AVAILABLE:
            logger.warning("TextFSM not available - will use fallback parsing")
            return

        # Try multiple paths for the TextFSM database
        potential_paths = [
            self.textfsm_db_path,
            "tfsm_templates.db",
            "Anguis/tfsm_templates.db",
            "./tfsm_templates.db"
        ]

        for db_path in potential_paths:
            if os.path.exists(db_path):
                try:
                    self.textfsm_engine = TextFSMAutoEngine(db_path, verbose=False)
                    logger.info(f"TextFSM engine initialized with: {db_path}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to initialize TextFSM with {db_path}: {e}")

        logger.warning("No TextFSM templates found - will use fallback parsing")

    def _create_vendor_filter(self, vendor_name: str, device_type: str = None) -> List[str]:
        """
        Create TextFSM filter based on vendor and device type.
        Based on the fingerprint logic in device_fingerprint.py
        """
        if not vendor_name:
            return ['arp', 'show_arp']

        vendor_lower = vendor_name.lower()
        filters = []

        # Vendor-specific ARP command filters
        vendor_filters = {
            'cisco': ['cisco_ios_show_arp', 'cisco_nxos_show_arp', 'cisco_asa_show_arp'],
            'arista': ['arista_eos_show_arp'],
            'juniper': ['juniper_junos_show_arp'],
            'hp': ['hp_procurve_show_arp', 'hp_comware_show_arp'],
            'aruba': ['aruba_os_show_arp'],
            'fortinet': ['fortinet_show_arp'],
            'paloalto': ['paloalto_panos_show_arp'],
            'dell': ['dell_force10_show_arp'],
            'brocade': ['brocade_fastiron_show_arp'],
            'extreme': ['extreme_exos_show_arp'],
            'mikrotik': ['mikrotik_routeros_show_arp']
        }

        # Find matching vendor filters
        for vendor_key, vendor_filter_list in vendor_filters.items():
            if vendor_key in vendor_lower:
                filters.extend(vendor_filter_list)
                break

        # Add generic filters as fallback
        filters.extend(['show_arp', 'arp'])

        return filters

    def _parse_arp_with_textfsm(self, content: str, vendor: str, device_type: str = None) -> Optional[Dict]:
        """Parse ARP content using TextFSM with vendor-specific filters"""
        if not self.textfsm_engine:
            return None

        try:
            filter_attempts = self._create_vendor_filter(vendor, device_type)
            logger.debug(f"Trying TextFSM filters for {vendor}: {filter_attempts}")

            best_result = None
            best_score = 0

            for filter_string in filter_attempts:
                try:
                    template, parsed_data, score, template_content = self.textfsm_engine.find_best_template(
                        content, filter_string
                    )

                    if score > best_score and parsed_data:
                        best_score = score
                        best_result = {
                            'template_name': template,
                            'score': score,
                            'parsed_data': parsed_data,
                            'filter_used': filter_string
                        }

                        logger.debug(f"Found better match: {template} (score: {score})")

                        # High confidence match - stop searching
                        if score > 70:
                            break

                except Exception as e:
                    logger.debug(f"Filter '{filter_string}' failed: {e}")
                    continue

            if best_result and best_result['score'] > 30:
                logger.info(
                    f"TextFSM parsed with template: {best_result['template_name']} (score: {best_result['score']})")
                return best_result

        except Exception as e:
            logger.warning(f"TextFSM parsing failed: {e}")

        return None

    def _normalize_mac_address(self, mac: str) -> str:
        """Normalize MAC address to standard format"""
        if not mac:
            return ""

        # Remove all non-alphanumeric characters
        clean_mac = re.sub(r'[^a-fA-F0-9]', '', mac.strip())

        # Validate length
        if len(clean_mac) != 12:
            return ""

        # Convert to lowercase and add colons
        return ':'.join([clean_mac[i:i + 2] for i in range(0, 12, 2)]).lower()

    def _validate_ip_address(self, ip: str) -> bool:
        """Validate IP address"""
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def _parse_arp_fallback(self, content: str, vendor: str) -> List[Dict]:
        """Fallback ARP parsing when TextFSM fails"""
        logger.info("Using fallback ARP parsing")
        entries = []

        # Common ARP table patterns
        patterns = {
            'cisco_ios': r'Internet\s+(\S+)\s+(\S+)\s+([a-fA-F0-9.]+)\s+(\S+)\s+(\S+)',
            'cisco_nxos': r'(\S+)\s+(\S+)\s+([a-fA-F0-9.:]+)\s+(\S+)\s+(\S+)',
            'arista': r'(\S+)\s+([a-fA-F0-9.:]+)\s+(\S+)\s+(\S+)',
            'juniper': r'(\S+)\s+([a-fA-F0-9:]+)\s+(\S+)\s+(\S+)',
            'hp': r'(\S+)\s+([a-fA-F0-9-]+)\s+(\S+)\s+(\S+)',
        }

        vendor_lower = vendor.lower() if vendor else 'generic'

        # Try vendor-specific pattern first
        pattern = None
        for vendor_key, vendor_pattern in patterns.items():
            if vendor_key in vendor_lower:
                pattern = vendor_pattern
                break

        if not pattern:
            # Generic pattern - try to match IP and MAC
            pattern = r'(\d+\.\d+\.\d+\.\d+)\s+.*?([a-fA-F0-9][a-fA-F0-9.:-]+[a-fA-F0-9])'

        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or 'Protocol' in line:
                continue

            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                groups = match.groups()

                # Extract IP and MAC based on pattern
                ip_addr = None
                mac_addr = None
                interface = None
                entry_type = 'dynamic'
                age = None

                if 'cisco_ios' in vendor_lower and len(groups) >= 5:
                    ip_addr = groups[0]
                    age = groups[1]
                    mac_addr = groups[2]
                    entry_type = groups[3]
                    interface = groups[4]
                elif len(groups) >= 2:
                    # Generic extraction
                    for group in groups:
                        if self._validate_ip_address(group):
                            ip_addr = group
                        elif self._normalize_mac_address(group):
                            mac_addr = group
                        elif not ip_addr and not mac_addr:
                            # Could be interface
                            interface = group

                if ip_addr and mac_addr:
                    normalized_mac = self._normalize_mac_address(mac_addr)
                    if normalized_mac:
                        entries.append({
                            'ip_address': ip_addr,
                            'mac_address': normalized_mac,
                            'mac_address_raw': mac_addr,
                            'interface_name': interface,
                            'entry_type': entry_type,
                            'age': age
                        })

        logger.info(f"Fallback parsing extracted {len(entries)} ARP entries")
        return entries

    def _extract_arp_entries_from_textfsm(self, textfsm_result: Dict) -> List[Dict]:
        """Extract ARP entries from TextFSM results"""
        entries = []
        parsed_data = textfsm_result.get('parsed_data', [])

        if not parsed_data:
            return entries

        # Handle both list of dicts and list of lists
        for row in parsed_data:
            if isinstance(row, dict):
                # Direct dictionary format
                entry = self._extract_arp_entry_from_dict(row)
            elif isinstance(row, list):
                # List format - need to map to common fields
                entry = self._extract_arp_entry_from_list(row, textfsm_result.get('template_name', ''))
            else:
                continue

            if entry:
                entries.append(entry)

        return entries

    def _extract_arp_entry_from_dict(self, row: Dict) -> Optional[Dict]:
        """Extract ARP entry from dictionary row"""
        # Common field mappings
        ip_fields = ['ADDRESS', 'IP_ADDRESS', 'IP', 'PROTOCOL_ADDRESS', 'DESTINATION']
        mac_fields = ['MAC', 'MAC_ADDRESS', 'HARDWARE_ADDRESS', 'HW_ADDRESS', 'HWADDR']
        interface_fields = ['INTERFACE', 'PORT', 'VIA']
        type_fields = ['TYPE', 'ENTRY_TYPE', 'FLAGS']
        age_fields = ['AGE', 'TIME', 'EXPIRES']

        entry = {}

        # Find IP address
        for field in ip_fields:
            if field in row and row[field]:
                ip_addr = str(row[field]).strip()
                if self._validate_ip_address(ip_addr):
                    entry['ip_address'] = ip_addr
                    break

        # Find MAC address
        for field in mac_fields:
            if field in row and row[field]:
                mac_addr = str(row[field]).strip()
                normalized_mac = self._normalize_mac_address(mac_addr)
                if normalized_mac:
                    entry['mac_address'] = normalized_mac
                    entry['mac_address_raw'] = mac_addr
                    break

        # Find interface
        for field in interface_fields:
            if field in row and row[field]:
                entry['interface_name'] = str(row[field]).strip()
                break

        # Find entry type
        for field in type_fields:
            if field in row and row[field]:
                entry['entry_type'] = str(row[field]).strip().lower()
                break

        # Find age
        for field in age_fields:
            if field in row and row[field]:
                entry['age'] = str(row[field]).strip()
                break

        # Must have at least IP and MAC
        if 'ip_address' in entry and 'mac_address' in entry:
            return entry

        return None

    def _extract_arp_entry_from_list(self, row: List, template_name: str) -> Optional[Dict]:
        """Extract ARP entry from list row based on template"""
        # This would need template-specific logic
        # For now, use a generic approach
        if len(row) < 2:
            return None

        entry = {}

        # Try to find IP and MAC in the row
        for item in row:
            if not item:
                continue

            item_str = str(item).strip()

            if not entry.get('ip_address') and self._validate_ip_address(item_str):
                entry['ip_address'] = item_str
            elif not entry.get('mac_address'):
                normalized_mac = self._normalize_mac_address(item_str)
                if normalized_mac:
                    entry['mac_address'] = normalized_mac
                    entry['mac_address_raw'] = item_str

        if 'ip_address' in entry and 'mac_address' in entry:
            return entry

        return None

    def get_arp_captures(self, processed_only: bool = False) -> List[Dict]:
        """Get ARP captures from assets database"""
        try:
            conn = sqlite3.connect(self.assets_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Query the v_capture_details view for ARP captures
            query = """
                SELECT * FROM v_capture_details 
                WHERE capture_type = 'arp'
                AND extraction_success = 1
                AND file_path IS NOT NULL
            """

            if processed_only:
                # Only get files that haven't been processed yet
                # This would require tracking in arp_cat.db
                pass

            query += " ORDER BY capture_timestamp DESC"

            cursor.execute(query)
            captures = [dict(row) for row in cursor.fetchall()]

            conn.close()
            logger.info(f"Found {len(captures)} ARP captures to process")
            return captures

        except sqlite3.Error as e:
            logger.error(f"Error querying assets database: {e}")
            return []

    def load_arp_capture(self, capture: Dict) -> int:
        """Load a single ARP capture into arp_cat.db"""
        file_path = capture.get('file_path')
        if not file_path or not os.path.exists(file_path):
            logger.warning(f"ARP file not found: {file_path}")
            return 0

        logger.info(f"Processing ARP capture: {file_path}")

        # Read the file content
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return 0

        if not content.strip():
            logger.warning(f"Empty ARP file: {file_path}")
            return 0

        # Extract device and context information
        device_info = {
            'hostname': capture.get('device_name', capture.get('device_normalized_name', 'unknown')),
            'device_type': capture.get('device_type_name'),
            'vendor': capture.get('vendor_name'),
            'model': capture.get('device_model'),
            'site_code': capture.get('site_code'),
            'management_ip': capture.get('management_ip')
        }

        # Determine context - default to VRF for now
        context_info = {
            'context_name': 'default',
            'context_type': 'vrf',
            'description': f"ARP table from {capture.get('capture_timestamp')}"
        }

        # Parse ARP entries
        arp_entries = []

        # Try TextFSM first
        if self.textfsm_engine:
            textfsm_result = self._parse_arp_with_textfsm(
                content,
                capture.get('vendor_name', ''),
                capture.get('device_type_name', '')
            )

            if textfsm_result:
                arp_entries = self._extract_arp_entries_from_textfsm(textfsm_result)

        # Fallback to regex parsing
        if not arp_entries:
            arp_entries = self._parse_arp_fallback(content, capture.get('vendor_name', ''))

        if not arp_entries:
            logger.warning(f"No ARP entries found in {file_path}")
            return 0

        # Store in arp_cat.db
        entries_loaded = 0
        try:
            with ArpCatUtil(self.arp_cat_db_path) as arp_util:
                # Create device and context
                device_id = arp_util.get_or_create_device(**device_info)
                context_id = arp_util.get_or_create_context(device_id, **context_info)

                # Create snapshot
                capture_timestamp = capture.get('capture_timestamp')
                if capture_timestamp:
                    # Convert to ISO format if needed
                    try:
                        dt = datetime.fromisoformat(capture_timestamp.replace('Z', '+00:00'))
                        capture_timestamp = dt.isoformat()
                    except:
                        capture_timestamp = datetime.now().isoformat()
                else:
                    capture_timestamp = datetime.now().isoformat()

                snapshot_id = arp_util.create_snapshot(
                    device_id, context_id, capture_timestamp,
                    source_file=file_path,
                    source_command='show arp',
                    processing_status='processed'
                )

                # Add ARP entries
                for entry in arp_entries:
                    try:
                        arp_util.add_arp_entry(
                            device_id, context_id,
                            entry['ip_address'],
                            entry['mac_address'],
                            interface_name=entry.get('interface_name'),
                            entry_type=entry.get('entry_type', 'dynamic'),
                            age=entry.get('age'),
                            capture_timestamp=capture_timestamp,
                            source_file=file_path,
                            source_command='show arp'
                        )
                        entries_loaded += 1
                    except Exception as e:
                        logger.warning(f"Error adding ARP entry {entry}: {e}")

        except Exception as e:
            logger.error(f"Error storing ARP data for {file_path}: {e}")
            return 0

        logger.info(f"Loaded {entries_loaded} ARP entries from {file_path}")
        return entries_loaded

    def load_all_captures(self, max_files: int = None) -> Dict[str, int]:
        """Load all ARP captures from assets database"""
        captures = self.get_arp_captures()

        if max_files:
            captures = captures[:max_files]

        stats = {
            'files_processed': 0,
            'files_skipped': 0,
            'total_entries': 0,
            'errors': 0
        }

        for capture in captures:
            try:
                entries_count = self.load_arp_capture(capture)
                if entries_count > 0:
                    stats['files_processed'] += 1
                    stats['total_entries'] += entries_count
                else:
                    stats['files_skipped'] += 1
            except Exception as e:
                logger.error(f"Error processing capture {capture.get('file_path')}: {e}")
                stats['errors'] += 1

        logger.info(f"Processing complete: {stats}")
        return stats


def main():
    """Main CLI interface"""
    import argparse

    parser = argparse.ArgumentParser(description="Load ARP captures into arp_cat.db")
    parser.add_argument("--assets-db", default="assets.db", help="Path to assets database")
    parser.add_argument("--arp-db", default="arp_cat.db", help="Path to ARP cat database")
    parser.add_argument("--textfsm-db", default="Anguis/tfsm_templates.db", help="Path to TextFSM templates")
    parser.add_argument("--max-files", type=int, help="Maximum files to process")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize loader
    loader = ArpCaptureLoader(
        assets_db_path=args.assets_db,
        arp_cat_db_path=args.arp_db,
        textfsm_db_path=args.textfsm_db
    )

    # Load captures
    stats = loader.load_all_captures(max_files=args.max_files)

    print(f"\nARP Capture Loading Complete:")
    print(f"  Files processed: {stats['files_processed']}")
    print(f"  Files skipped: {stats['files_skipped']}")
    print(f"  Total entries: {stats['total_entries']}")
    print(f"  Errors: {stats['errors']}")


if __name__ == "__main__":
    main()