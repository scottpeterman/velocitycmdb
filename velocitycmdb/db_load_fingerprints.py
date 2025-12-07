#!/usr/bin/env python3
"""
Fingerprint Database Loader
Loads device fingerprint JSON files into the network asset management database
Handles new devices, updates, and complex stack configurations

FIXED: Properly handles yaml_display_name fallback for devices that don't report hostname
"""

import json
import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
import logging
import click

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.setLevel("DEBUG")


@dataclass
class DeviceInfo:
    """Parsed device information from fingerprint JSON"""
    hostname: str
    normalized_name: str
    site_code: str
    vendor_name: str
    device_type_name: str
    model: str
    os_version: str
    uptime: Optional[str]
    management_ip: str
    serial_numbers: List[str]
    is_stack: bool
    stack_members: List[Dict[str, Any]]
    fingerprint_data: Dict[str, Any]


class FingerprintLoader:
    """Main loader class for processing fingerprint JSON files"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.vendor_cache = {}
        self.device_type_cache = {}
        self.site_cache = {}

    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection with foreign keys enabled"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def extract_site_code(self, hostname: str) -> str:
        """Extract site code from hostname using common patterns"""
        if not hostname:
            return "UNKNOWN"

        hostname_lower = hostname.lower()

        # Pattern 1: Extract from FQDN - take the part immediately after the first dot
        # Examples: device.iad1, oob5-6937.iad1.domain.com
        if '.' in hostname_lower:
            parts = hostname_lower.split('.')
            if len(parts) >= 2:
                # Second part (index 1) is the site
                potential_site = parts[1]
                # Validate it looks like a site code (2-6 alphanumeric chars)
                if (2 <= len(potential_site) <= 6 and
                        potential_site.isalnum() and
                        potential_site not in ['com', 'net', 'org', 'local', 'lan', 'internal']):
                    return potential_site.upper()

            # Fallback: if only 2 parts (device.site), use second part
            if len(parts) == 2:
                return parts[1].upper()

        # Pattern 2: Dash-separated prefix (site-device-01 format) - legacy fallback
        patterns = [
            r'^([a-zA-Z]+)-',  # Everything before first dash
            r'^([a-zA-Z]{2,4})\d',  # 2-4 letters followed by number
        ]

        for pattern in patterns:
            match = re.match(pattern, hostname_lower)
            if match:
                return match.group(1).upper()

        return "UNKNOWN"

    def normalize_hostname(self, hostname: str) -> str:
        """Normalize hostname for database storage"""
        if not hostname:
            return "unknown-device"
        return hostname.lower().strip()

    def map_vendor_from_fingerprint(self, fingerprint: Dict) -> str:
        """Map vendor from fingerprint data"""
        additional_info = fingerprint.get('additional_info', {})
        vendor = additional_info.get('vendor', '')

        # Normalize vendor names
        vendor_mapping = {
            'cisco': 'Cisco Systems',
            'hp/aruba': 'Hewlett Packard Enterprise',
            'arista': 'Arista Networks',
            'juniper': 'Juniper Networks',
            'fortinet': 'Fortinet',
            'palo alto': 'Palo Alto Networks',
        }

        vendor_lower = vendor.lower()
        return vendor_mapping.get(vendor_lower, vendor or 'Unknown')

    def map_device_type_from_fingerprint(self, fingerprint: Dict) -> str:
        """Map device type from fingerprint data"""
        additional_info = fingerprint.get('additional_info', {})
        netmiko_driver = additional_info.get('netmiko_driver', '')

        # Map netmiko drivers to our device types
        driver_mapping = {
            'cisco_ios': 'cisco_ios_ssh',
            'cisco_xe': 'cisco_ios_xe_ssh',
            'cisco_nxos': 'cisco_nxos_ssh',
            'arista_eos': 'arista_eos_ssh',
            'hp_procurve': 'hp_procurve_ssh',
            'juniper_junos': 'juniper_junos_ssh',
        }

        return driver_mapping.get(netmiko_driver, netmiko_driver or 'generic_ssh')

    def extract_hostname_from_prompt(self, detected_prompt: str) -> Optional[str]:
        """
        Extract hostname from detected prompt with better parsing.

        Handles formats like:
        - "hostname#" or "hostname>"
        - "username@hostname#" or "username@hostname>"
        - "hostname(config)#"
        - "admin@edge1-01>"
        """
        if not detected_prompt:
            return None

        prompt = detected_prompt.strip()

        # Remove trailing prompt characters (#, >, $, %, ), etc.)
        prompt = re.sub(r'[\#\>\$\%\)\]]+\s*$', '', prompt)

        # Remove config mode indicators like (config), (config-if), etc.
        prompt = re.sub(r'\([^)]+\)\s*$', '', prompt)

        # Handle username@hostname format (common in Juniper, Linux)
        if '@' in prompt:
            # Take everything after the @ as hostname
            parts = prompt.split('@')
            if len(parts) >= 2:
                hostname = parts[-1].strip()
                if hostname:
                    logger.debug(f"Extracted hostname from user@host prompt: '{hostname}'")
                    return hostname

        # If no @, the remaining string is the hostname
        hostname = prompt.strip()
        if hostname:
            logger.debug(f"Extracted hostname from prompt: '{hostname}'")
            return hostname

        return None

    def parse_stack_members_from_textfsm(self, textfsm_data: Dict) -> List[Dict[str, Any]]:
        """Parse stack member information from TextFSM data"""
        stack_members = []

        # Look for stack members in TextFSM records
        records = textfsm_data.get('records', [])
        if not records:
            logger.debug("No TextFSM records found")
            return stack_members

        logger.debug(f"Processing {len(records)} TextFSM records for stack members")

        # Check if STACK_MEMBERS field exists
        for record in records:
            logger.debug(f"Checking record keys: {list(record.keys())}")

            if 'STACK_MEMBERS' in record and record['STACK_MEMBERS']:
                logger.debug(f"Found STACK_MEMBERS field: {record['STACK_MEMBERS']}")

                # Handle both list and single dict formats
                members_data = record['STACK_MEMBERS']
                if isinstance(members_data, list):
                    logger.debug(f"STACK_MEMBERS is a list with {len(members_data)} items")
                    for i, member in enumerate(members_data):
                        logger.debug(f"Processing member {i}: {member}")

                        # Get model and serial strings
                        model_str = str(member.get('model', ''))
                        serial_str = str(member.get('serial', ''))

                        logger.debug(f"Model string: '{model_str}'")
                        logger.debug(f"Serial string: '{serial_str}'")

                        # Check for comma-separated values and split
                        if ',' in model_str or ',' in serial_str:
                            logger.debug("Found comma-separated values, splitting...")
                            models = [m.strip() for m in model_str.split(',') if m.strip()]
                            serials = [s.strip() for s in serial_str.split(',') if s.strip()]

                            logger.debug(f"Split models: {models}")
                            logger.debug(f"Split serials: {serials}")

                            # Create individual stack members by matching serials to models
                            for j, serial in enumerate(serials):
                                if serial:
                                    # Use corresponding model or first model if fewer models than serials
                                    model = models[j] if j < len(models) else (models[0] if models else '')
                                    new_member = {
                                        'index': j + 1,
                                        'model': model,
                                        'serial': serial
                                    }
                                    stack_members.append(new_member)
                                    logger.debug(f"Added stack member: {new_member}")
                        else:
                            logger.debug("No comma-separated values found")
                            # Single device, not a stack
                            if serial_str:
                                new_member = {
                                    'index': 1,
                                    'model': model_str,
                                    'serial': serial_str
                                }
                                stack_members.append(new_member)
                                logger.debug(f"Added single stack member: {new_member}")
                elif isinstance(members_data, dict):
                    logger.debug(f"STACK_MEMBERS is a dict: {members_data}")
                    # Single member case - handle same way
                    model_str = str(members_data.get('model', ''))
                    serial_str = str(members_data.get('serial', ''))

                    if ',' in model_str or ',' in serial_str:
                        models = [m.strip() for m in model_str.split(',') if m.strip()]
                        serials = [s.strip() for s in serial_str.split(',') if s.strip()]

                        for j, serial in enumerate(serials):
                            if serial:
                                model = models[j] if j < len(models) else (models[0] if models else '')
                                new_member = {
                                    'index': j + 1,
                                    'model': model,
                                    'serial': serial
                                }
                                stack_members.append(new_member)
                                logger.debug(f"Added stack member: {new_member}")
                    else:
                        if serial_str:
                            new_member = {
                                'index': 1,
                                'model': model_str,
                                'serial': serial_str
                            }
                            stack_members.append(new_member)
                            logger.debug(f"Added single stack member: {new_member}")
            else:
                logger.debug("No STACK_MEMBERS field found in this record")

            # Fallback: parse from HARDWARE and SERIAL fields for stacks
            if not stack_members and ',' in record.get('SERIAL', ''):
                logger.debug("Using fallback: parsing from HARDWARE and SERIAL fields")
                serials = [s.strip() for s in record['SERIAL'].split(',') if s.strip()]
                hardware_str = record.get('HARDWARE', '')

                # Handle HARDWARE field - could be list or string
                if isinstance(hardware_str, list):
                    models = [m.strip() for m in hardware_str[0].split(',') if m.strip()] if hardware_str else []
                else:
                    models = [m.strip() for m in str(hardware_str).split(',') if m.strip()]

                logger.debug(f"Fallback - Models: {models}, Serials: {serials}")

                for j, serial in enumerate(serials):
                    if serial:
                        model = models[j] if j < len(models) else (models[0] if models else '')
                        new_member = {
                            'index': j + 1,
                            'model': model,
                            'serial': serial
                        }
                        stack_members.append(new_member)
                        logger.debug(f"Added fallback stack member: {new_member}")

        logger.debug(f"Final stack_members count: {len(stack_members)}")
        return stack_members

    def parse_uptime_from_textfsm(self, textfsm_data: Dict) -> Optional[str]:
        """Extract uptime from TextFSM data"""
        records = textfsm_data.get('records', [])
        if records:
            return records[0].get('UPTIME', '')
        return None

    def parse_fingerprint_json(self, fingerprint_path: Path) -> Optional[DeviceInfo]:
        """
        Parse a fingerprint JSON file into DeviceInfo object.

        FIXED: Proper hostname extraction with yaml_display_name fallback.

        Hostname priority order:
        1. hostname field (from device detection)
        2. yaml_display_name (from sessions.yaml inventory)
        3. display_name (computed during fingerprinting)
        4. Parsed from detected_prompt (with proper username handling)
        5. IP address (last resort)
        """
        try:
            with open(fingerprint_path, 'r') as f:
                data = json.load(f)

            if not data.get('success', False):
                logger.warning(f"Fingerprint marked as failed: {fingerprint_path}")
                return None

            additional_info = data.get('additional_info', {})

            # ================================================================
            # FIXED: Extract hostname with proper fallback order
            # ================================================================
            hostname = None
            hostname_source = None

            # Priority 1: Direct hostname field (from device detection)
            if data.get('hostname'):
                hostname = data['hostname']
                hostname_source = "hostname field"
                logger.debug(f"Using hostname from fingerprint: '{hostname}'")

            # Priority 2: yaml_display_name (from sessions.yaml - user provided)
            if not hostname and additional_info.get('yaml_display_name'):
                hostname = additional_info['yaml_display_name']
                hostname_source = "yaml_display_name"
                logger.debug(f"Using yaml_display_name: '{hostname}'")

            # Priority 3: display_name (computed during fingerprinting)
            if not hostname and additional_info.get('display_name'):
                # Only use if it's not just the IP address
                display_name = additional_info['display_name']
                if display_name != data.get('host', ''):
                    hostname = display_name
                    hostname_source = "display_name"
                    logger.debug(f"Using display_name: '{hostname}'")

            # Priority 4: Parse from detected_prompt
            if not hostname:
                detected_prompt = data.get('detected_prompt', '')
                if detected_prompt:
                    parsed_hostname = self.extract_hostname_from_prompt(detected_prompt)
                    if parsed_hostname:
                        hostname = parsed_hostname
                        hostname_source = "detected_prompt"
                        logger.debug(f"Extracted hostname from prompt: '{hostname}'")

            # Priority 5: Use management IP (last resort)
            if not hostname:
                hostname = data.get('host', '')
                hostname_source = "IP address (fallback)"
                logger.debug(f"Using IP as hostname: {hostname}")

            if not hostname:
                logger.warning(f"No hostname found in {fingerprint_path}")
                return None

            logger.info(f"Final hostname: '{hostname}' (source: {hostname_source})")

            # Extract basic info
            normalized_name = self.normalize_hostname(hostname)
            site_code = self.extract_site_code(hostname)
            vendor_name = self.map_vendor_from_fingerprint(data)
            device_type_name = self.map_device_type_from_fingerprint(data)

            # ================================================================
            # FIXED: Ensure model and version are extracted properly
            # ================================================================
            model = data.get('model', '') or ''
            os_version = data.get('version', '') or ''
            management_ip = data.get('host', '')

            # Log what we're extracting
            logger.debug(f"Extracted - Model: '{model}', Version: '{os_version}', Vendor: '{vendor_name}'")

            # Parse serial numbers
            serial_numbers = []
            raw_serial = data.get('serial_number', '')
            if raw_serial:
                # Handle comma-separated serials for stacks
                serial_numbers = [s.strip() for s in raw_serial.split(',') if s.strip()]

            # Parse TextFSM data for additional info
            uptime = None
            stack_members = []

            # Look for TextFSM parsing results
            command_outputs = data.get('command_outputs', {})
            logger.debug(f"Found {len(command_outputs)} command outputs to process")

            for cmd_name, cmd_data in command_outputs.items():
                logger.debug(f"Processing command: {cmd_name}")
                if cmd_name.endswith('_textfsm') and isinstance(cmd_data, dict):
                    logger.debug(f"Found TextFSM data in {cmd_name}")
                    # Extract uptime if not already found
                    if not uptime:
                        uptime = self.parse_uptime_from_textfsm(cmd_data)
                        if uptime:
                            logger.debug(f"Extracted uptime: {uptime}")

                    # Extract stack members
                    logger.debug(f"Calling parse_stack_members_from_textfsm for {cmd_name}")
                    members = self.parse_stack_members_from_textfsm(cmd_data)
                    logger.debug(f"Found {len(members)} stack members from {cmd_name}")
                    if members:
                        stack_members.extend(members)
                        logger.debug(f"Total stack members so far: {len(stack_members)}")
                else:
                    logger.debug(f"Skipping {cmd_name} - not TextFSM data")

            # Determine if this is a stack
            is_stack = len(serial_numbers) > 1 or len(stack_members) > 1

            return DeviceInfo(
                hostname=hostname,
                normalized_name=normalized_name,
                site_code=site_code,
                vendor_name=vendor_name,
                device_type_name=device_type_name,
                model=model,
                os_version=os_version,
                uptime=uptime,
                management_ip=management_ip,
                serial_numbers=serial_numbers,
                is_stack=is_stack,
                stack_members=stack_members,
                fingerprint_data=data
            )

        except Exception as e:
            logger.error(f"Error parsing {fingerprint_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_or_create_vendor(self, conn: sqlite3.Connection, vendor_name: str) -> int:
        """Get or create vendor ID"""
        if vendor_name in self.vendor_cache:
            return self.vendor_cache[vendor_name]

        cursor = conn.cursor()
        cursor.execute("SELECT id FROM vendors WHERE name = ?", (vendor_name,))
        row = cursor.fetchone()

        if row:
            vendor_id = row[0]
        else:
            cursor.execute(
                "INSERT INTO vendors (name, short_name) VALUES (?, ?)",
                (vendor_name, vendor_name.split()[0].upper())
            )
            vendor_id = cursor.lastrowid
            logger.info(f"Created new vendor: {vendor_name} (ID: {vendor_id})")

        self.vendor_cache[vendor_name] = vendor_id
        return vendor_id

    def get_or_create_device_type(self, conn: sqlite3.Connection, device_type_name: str) -> int:
        """Get or create device type ID"""
        if device_type_name in self.device_type_cache:
            return self.device_type_cache[device_type_name]

        cursor = conn.cursor()
        cursor.execute("SELECT id FROM device_types WHERE name = ?", (device_type_name,))
        row = cursor.fetchone()

        if row:
            device_type_id = row[0]
        else:
            # Create with basic defaults
            cursor.execute("""
                INSERT INTO device_types (name, netmiko_driver, transport, default_port)
                VALUES (?, ?, 'ssh', 22)
            """, (device_type_name, device_type_name.replace('_ssh', '')))
            device_type_id = cursor.lastrowid
            logger.info(f"Created new device type: {device_type_name} (ID: {device_type_id})")

        self.device_type_cache[device_type_name] = device_type_id
        return device_type_id

    def get_or_create_site(self, conn: sqlite3.Connection, site_code: str) -> str:
        """Get or create site"""
        if site_code in self.site_cache:
            return site_code

        cursor = conn.cursor()
        cursor.execute("SELECT code FROM sites WHERE code = ?", (site_code,))
        row = cursor.fetchone()

        if not row:
            cursor.execute(
                "INSERT INTO sites (code, name) VALUES (?, ?)",
                (site_code, f"{site_code} Site")
            )
            logger.info(f"Created new site: {site_code}")

        self.site_cache[site_code] = site_code
        return site_code

    def upsert_device(self, conn: sqlite3.Connection, device_info: DeviceInfo) -> int:
        """Insert or update device in database"""
        cursor = conn.cursor()

        # Get foreign key IDs
        vendor_id = self.get_or_create_vendor(conn, device_info.vendor_name)
        device_type_id = self.get_or_create_device_type(conn, device_info.device_type_name)
        site_code = self.get_or_create_site(conn, device_info.site_code)

        # Check if device exists by normalized_name OR management_ip
        cursor.execute("""
            SELECT id FROM devices 
            WHERE normalized_name = ? OR management_ip = ?
        """, (device_info.normalized_name, device_info.management_ip))
        existing = cursor.fetchone()

        if existing:
            device_id = existing[0]
            # Update existing device
            cursor.execute("""
                UPDATE devices SET
                    name = ?, normalized_name = ?, site_code = ?, vendor_id = ?, device_type_id = ?,
                    model = ?, os_version = ?, uptime = ?, management_ip = ?,
                    is_stack = ?, timestamp = datetime('now')
                WHERE id = ?
            """, (
                device_info.hostname, device_info.normalized_name, site_code, vendor_id, device_type_id,
                device_info.model, device_info.os_version, device_info.uptime,
                device_info.management_ip, device_info.is_stack, device_id
            ))
            logger.info(f"Updated device: {device_info.hostname} (ID: {device_id})")
        else:
            # Insert new device
            cursor.execute("""
                INSERT INTO devices (
                    name, normalized_name, site_code, vendor_id, device_type_id,
                    model, os_version, uptime, management_ip, is_stack, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                device_info.hostname, device_info.normalized_name, site_code,
                vendor_id, device_type_id, device_info.model, device_info.os_version,
                device_info.uptime, device_info.management_ip, device_info.is_stack
            ))
            device_id = cursor.lastrowid
            logger.info(f"Created device: {device_info.hostname} (ID: {device_id})")

        return device_id

    def update_device_serials(self, conn: sqlite3.Connection, device_id: int, serial_numbers: List[str]):
        """Update device serial numbers"""
        cursor = conn.cursor()

        # Remove existing serials
        cursor.execute("DELETE FROM device_serials WHERE device_id = ?", (device_id,))

        # Add new serials
        for i, serial in enumerate(serial_numbers):
            if serial:
                cursor.execute("""
                    INSERT INTO device_serials (device_id, serial, is_primary)
                    VALUES (?, ?, ?)
                """, (device_id, serial, i == 0))

    def update_stack_members(self, conn: sqlite3.Connection, device_id: int, stack_members: List[Dict]):
        """Update stack member information"""
        cursor = conn.cursor()

        # Remove existing stack members
        cursor.execute("DELETE FROM stack_members WHERE device_id = ?", (device_id,))

        # Add new stack members
        for member in stack_members:
            cursor.execute("""
                INSERT INTO stack_members (device_id, serial, position, model, is_master)
                VALUES (?, ?, ?, ?, ?)
            """, (
                device_id,
                member.get('serial', ''),
                member.get('index', 1),
                member.get('model', ''),
                member.get('index', 1) == 1  # First member is master
            ))

    def record_fingerprint_extraction(self, conn: sqlite3.Connection, device_id: int,
                                      fingerprint_path: Path, device_info: DeviceInfo):
        """Record fingerprint extraction in audit table (with duplicate prevention)"""
        cursor = conn.cursor()

        fingerprint_data = device_info.fingerprint_data
        extraction_timestamp = fingerprint_data.get('fingerprint_time', datetime.now().isoformat())

        # Check if this fingerprint extraction already exists
        cursor.execute("""
            SELECT id FROM fingerprint_extractions 
            WHERE device_id = ? AND extraction_timestamp = ?
        """, (device_id, extraction_timestamp))

        existing = cursor.fetchone()
        if existing:
            logger.debug(
                f"Fingerprint extraction already exists for device {device_id} at {extraction_timestamp}, skipping")
            return

        # Calculate metrics from TextFSM data
        fields_extracted = 0
        total_fields = 0
        command_count = len(fingerprint_data.get('command_outputs', {}))

        # Count TextFSM fields
        for cmd_name, cmd_data in fingerprint_data.get('command_outputs', {}).items():
            if cmd_name.endswith('_textfsm') and isinstance(cmd_data, dict):
                records = cmd_data.get('records', [])
                if records:
                    record = records[0]
                    for key, value in record.items():
                        total_fields += 1
                        if value and str(value).strip():
                            fields_extracted += 1

        cursor.execute("""
            INSERT INTO fingerprint_extractions (
                device_id, extraction_timestamp, fingerprint_file_path,
                template_used, template_score, extraction_success,
                fields_extracted, total_fields_available, command_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            device_id,
            extraction_timestamp,
            str(fingerprint_path),
            'auto_detected',
            100.0,
            True,
            fields_extracted,
            total_fields,
            command_count
        ))

    def load_fingerprint_file(self, fingerprint_path: Path) -> bool:
        """Load a single fingerprint file into the database"""
        try:
            device_info = self.parse_fingerprint_json(fingerprint_path)
            if not device_info:
                return False

            with self.get_db_connection() as conn:
                # Insert/update device
                device_id = self.upsert_device(conn, device_info)

                # Update serials
                if device_info.serial_numbers:
                    self.update_device_serials(conn, device_id, device_info.serial_numbers)

                # Update stack members
                if device_info.stack_members:
                    self.update_stack_members(conn, device_id, device_info.stack_members)

                # Record fingerprint extraction
                self.record_fingerprint_extraction(conn, device_id, fingerprint_path, device_info)

                conn.commit()
                return True

        except Exception as e:
            logger.error(f"Error loading {fingerprint_path}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_fingerprints_directory(self, fingerprints_dir: Path) -> Dict[str, int]:
        """Load all fingerprint files from a directory"""
        results = {'success': 0, 'failed': 0, 'total': 0}

        if not fingerprints_dir.exists():
            logger.error(f"Fingerprints directory not found: {fingerprints_dir}")
            return results

        json_files = list(fingerprints_dir.glob('*.json'))
        results['total'] = len(json_files)

        logger.info(f"Found {results['total']} fingerprint files to process")

        for json_file in json_files:
            if self.load_fingerprint_file(json_file):
                results['success'] += 1
            else:
                results['failed'] += 1

            if (results['success'] + results['failed']) % 50 == 0:
                logger.info(f"Processed {results['success'] + results['failed']}/{results['total']} files")

        return results


@click.command()
@click.option('--db-path', default='assets.db', help='Path to SQLite database')
@click.option('--fingerprints-dir', default='fingerprints', help='Directory containing fingerprint JSON files')
@click.option('--single-file', help='Process a single fingerprint file')
@click.option('--verbose', '-v', is_flag=True, help='Verbose logging')
def main(db_path, fingerprints_dir, single_file, verbose):
    """Load fingerprint JSON files into the network asset database"""

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    loader = FingerprintLoader(db_path)

    if single_file:
        # Process single file
        file_path = Path(single_file)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return

        logger.info(f"Processing single file: {file_path}")
        success = loader.load_fingerprint_file(file_path)
        if success:
            logger.info("File processed successfully")
        else:
            logger.error("Failed to process file")
    else:
        # Process directory
        fingerprints_path = Path(fingerprints_dir)
        logger.info(f"Loading fingerprints from: {fingerprints_path}")

        results = loader.load_fingerprints_directory(fingerprints_path)

        logger.info("=" * 60)
        logger.info("FINGERPRINT LOADING RESULTS")
        logger.info("=" * 60)
        logger.info(f"Total files: {results['total']}")
        logger.info(f"Successfully loaded: {results['success']}")
        logger.info(f"Failed: {results['failed']}")
        logger.info(
            f"Success rate: {results['success'] / results['total'] * 100:.1f}%" if results['total'] > 0 else "N/A")


if __name__ == '__main__':
    main()