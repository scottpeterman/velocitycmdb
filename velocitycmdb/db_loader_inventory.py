#!/usr/bin/env python3
"""
Inventory Loader v3 - Clean Refactor

Parses inventory captures with comprehensive component classification.
"""

import os
import re
import sqlite3
import logging
from typing import Dict, List, Optional

try:
    from tfsm_fire import TextFSMAutoEngine
    TEXTFSM_AVAILABLE = True
except ImportError:
    TEXTFSM_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class InventoryLoader:
    """Loads inventory captures and populates components table"""

    MINIMUM_SCORE = 2

    JUNK_WORDS = {
        'Item', 'Screen', 'Networks', 'Switched', 'SwitchedBootstrap',
        'Bootstrap', 'File', 'Traceback', 'from', 'import', 'Routing'
    }

    JUNK_PATTERNS = [
        r'^Item\s+Version', r'^Screen\s+length', r'^----+$', r'^\s*$',
        r'^Traceback', r'^File\s+"/.*\.py"', r'^\s*from\s+', r'^\s*import\s+',
        r'^Fatal\s+Python\s+error', r'<frozen\s+importlib', r'<module>$',
        r'\.py",\s+line', r'/site-packages/', r'/lib/python',
        r'_bootstrap', r'exec_module', r'get_code', r'get_data',
        r'_find_and_load', r'path\.search',
    ]

    TYPE_PATTERNS = {
        'transceiver': [
            r'\bXcvr\b', r'\bSFP\b', r'\bQSFP\b', r'\bXFP\b', r'\bCFP\b',
            r'\bQSFP\+\b', r'\bQSFP28\b', r'\bQSFP-DD\b', r'-T$',
            r'\boptic', r'transceiver', r'GLC-', r'SFP\+-\d+G',
            r'QSFP-\d+G', r'^Q\d+-', r'^ET-', r'-CWDM',
            r'-LR\d*$', r'-SR\d*$', r'\bgbic\b',
        ],
        'psu': [
            r'\bPWR\b', r'\bPSU\b', r'\bPS\d+\b',
            r'\bpower\s*supply\b', r'power\s+supply', r'^Power$',
            r'\bpower\s*module\b', r'PWR-\w+', r'C3K-PWR',
            r'AIR-PWR', r'^PWR-\d+', r'\bPEM\b', r'JPSU-',
        ],
        'fan': [
            r'\bFAN\b', r'\bcooling\b', r'fan\s*tray',
            r'fan\s*module', r'FAN-\w+',
        ],
        'supervisor': [
            r'\bsupervisor\b', r'\bsup\b', r'\bengine\b',
            r'routing\s*engine', r'\bRE\b', r'\bRP\b',
            r'supervisor\s*module', r'WS-SUP', r'\bCPU\b',
            r'management\s*module', r'^Routing\s+Engine', r'RE-\w+',
        ],
        'module': [
            r'\bmodule\b', r'\bcard\b', r'\blinecard\b',
            r'\bline\s*card\b', r'\bPIC\b', r'\bFPC\b', r'\bMIC\b',
            r'WS-X\d+', r'C\d+K-\d+PORT', r'interface\s*card',
            r'\bAFEB\b', r'\bMidplane\b',
        ],
        'chassis': [
            r'\bchassis\b', r'\bCHAS\b', r'C\d+K-CHAS', r'-CHAS$',
            r'^DCS-\d+', r'^WS-C\d+', r'\bstack\b', r'\bswitch\s+\d+',
        ],
    }

    def __init__(self, assets_db_path: str = "assets.db",
                 textfsm_db_path: str = "Anguis/tfsm_templates.db",
                 ignore_sn: bool = False):
        self.assets_db_path = assets_db_path
        self.textfsm_db_path = textfsm_db_path
        self.textfsm_engine = None
        self.ignore_sn = ignore_sn

        if not TEXTFSM_AVAILABLE:
            raise ImportError("TextFSM not available")

        self._initialize_textfsm()

    def _initialize_textfsm(self):
        if not os.path.exists(self.textfsm_db_path):
            raise FileNotFoundError(f"TextFSM templates not found: {self.textfsm_db_path}")
        self.textfsm_engine = TextFSMAutoEngine(self.textfsm_db_path, verbose=False)
        logger.info(f"✓ TextFSM initialized: {self.textfsm_db_path}")

    def _create_vendor_filter(self, vendor: str) -> List[str]:
        if not vendor:
            return ['show_inventory']

        vendor_lower = vendor.lower()
        vendor_filters = {
            'cisco': ['cisco_ios_show_inventory', 'cisco_nxos_show_inventory'],
            'arista': ['arista_eos_show_inventory', 'arista_eos_show_version'],
            'hewlett': ['hp_procurve_show_system', 'hp_comware_display_device'],
            'procurve': ['hp_procurve_show_system'],
            'aruba': ['aruba_os_show_system'],
            'juniper': ['juniper_junos_show_chassis_firmware']
        }

        filters = []
        for key, filter_list in vendor_filters.items():
            if key in vendor_lower:
                filters.extend(filter_list)
                break

        filters.append('show_inventory')
        return filters

    def _parse_inventory_with_textfsm(self, content: str, vendor: str,
                                      device_type: str = None) -> Optional[Dict]:
        if not self.textfsm_engine:
            return None

        filter_attempts = self._create_vendor_filter(vendor)
        best_result = None
        best_score = 0

        for filter_string in filter_attempts:
            try:
                result = self.textfsm_engine.find_best_template(content, filter_string)

                if len(result) == 4:
                    template, parsed_data, score, template_content = result
                elif len(result) == 3:
                    template, parsed_data, score = result
                    template_content = None
                else:
                    continue

                if score > best_score and parsed_data:
                    best_score = score
                    best_result = {
                        'template_name': template,
                        'score': score,
                        'parsed_data': parsed_data,
                        'filter_used': filter_string,
                        'template_content': template_content
                    }

                    if score > 70:
                        break

            except Exception:
                continue

        if best_result and best_result['score'] >= self.MINIMUM_SCORE:
            return best_result
        return None

    def load_from_directory(self, inventory_dir: str, vendor: str = None) -> Dict[str, int]:
        """Load inventory files directly from directory, bypassing capture database"""
        import glob

        if not os.path.exists(inventory_dir):
            logger.error(f"Directory not found: {inventory_dir}")
            return {'files_processed': 0, 'files_failed': 0, 'total_components': 0}

        # Find all .txt files in directory
        pattern = os.path.join(inventory_dir, "*.txt")
        files = glob.glob(pattern)

        logger.info(f"Found {len(files)} inventory files in {inventory_dir}")

        stats = {
            'files_processed': 0,
            'files_failed': 0,
            'total_components': 0,
            'failed_devices': []
        }

        for i, file_path in enumerate(sorted(files), 1):
            device_name = os.path.splitext(os.path.basename(file_path))[0]

            try:
                # Read file
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                if not content.strip():
                    logger.warning(f"Empty file: {device_name}")
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    continue

                # Get device_id from database
                conn = sqlite3.connect(self.assets_db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT id, vendor_id FROM devices WHERE name = ?", (device_name,))
                result = cursor.fetchone()

                if not result:
                    logger.warning(f"Device not found in database: {device_name}")
                    conn.close()
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    continue

                device_id, vendor_id = result

                # Get vendor name if available
                cursor.execute("SELECT name FROM vendors WHERE id = ?", (vendor_id,))
                vendor_result = cursor.fetchone()
                vendor_name = vendor_result[0] if vendor_result else (vendor or '')
                conn.close()

                # Parse with TextFSM
                textfsm_result = self._parse_inventory_with_textfsm(content, vendor_name)

                if not textfsm_result:
                    logger.warning(f"TextFSM parsing failed for {device_name}")
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    continue

                # Extract components
                device_info = {
                    'device_id': device_id,
                    'hostname': device_name,
                    'vendor': vendor_name
                }

                components = self._extract_components_from_textfsm(textfsm_result, device_info)

                if not components:
                    logger.warning(f"No components extracted for {device_name} (all filtered as junk)")
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    continue

                # Store components
                count = self._store_components(device_id, components)

                if count > 0:
                    stats['files_processed'] += 1
                    stats['total_components'] += count
                    logger.info(f"✓ {device_name}: {count} components")
                else:
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)

            except Exception as e:
                logger.error(f"✗ Error processing {device_name}: {e}")
                stats['files_failed'] += 1
                stats['failed_devices'].append(device_name)

        logger.info(f"\n{'=' * 70}")
        logger.info("PROCESSING COMPLETE")
        logger.info(f"Files processed: {stats['files_processed']}")
        logger.info(f"Files failed: {stats['files_failed']}")
        logger.info(f"Total components: {stats['total_components']}")

        if stats['failed_devices']:
            logger.info(f"\nFailed devices ({len(stats['failed_devices'])}):")
            for device in stats['failed_devices']:
                logger.info(f"  - {device}")

        return stats
    def _is_junk_component(self, component: Dict) -> bool:
        print(component)
        name = component.get('name', '').strip()
        description = component.get('description', '').strip()

        if not name:
            return True

        # EXCEPTION: Don't mark legitimate Juniper components as junk
        juniper_prefixes = [
            'Routing Engine', 'FPC', 'PIC', 'PEM', 'Fan Tray',
            'Power Supply', 'Midplane', 'CB', 'Chassis', 'Xcvr'
        ]
        if any(name.startswith(prefix) for prefix in juniper_prefixes):
            return False  # These are legitimate components!

        # Check single-word junk
        if name in self.JUNK_WORDS:
            return True

        text = f"{name} {description}"
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in self.JUNK_PATTERNS)


    def _determine_component_type(self, component: Dict) -> str:
        name = component.get('name', '')
        description = component.get('description', '')

        for comp_type, patterns in self.TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, name, re.IGNORECASE):
                    return comp_type

        for comp_type, patterns in self.TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, description, re.IGNORECASE):
                    return comp_type

        return 'unknown'

    def _extract_components_from_textfsm(self, textfsm_result: Dict,
                                         device_info: Dict) -> List[Dict]:
        components = []
        parsed_data = textfsm_result.get('parsed_data', [])

        if not parsed_data:
            return components

        # Check if this is Juniper format (PART/TYPE/VERSION)
        if parsed_data and 'PART' in parsed_data[0]:
            # Juniper format
            field_mappings = {
                'name': ['PART'],
                'type_info': ['TYPE'],
                'version': ['VERSION']
            }
        else:
            # Standard format
            field_mappings = {
                'name': ['NAME', 'name'],
                'description': ['DESCR', 'description', 'DESCRIPTION'],
                'serial': ['SN', 'serial', 'SERIAL_NUMBER'],
                'model': ['PID', 'model', 'MODEL'],
                'version': ['VID', 'version', 'VERSION'],
                'position': ['PORT', 'SLOT', 'position', 'POSITION']
            }

        junk_count = 0
        seen_components = {}  # Track duplicates by (name, serial, type)

        for row in parsed_data:
            if not isinstance(row, dict):
                continue

            component = self._map_fields(row, field_mappings)

            if not component:
                continue

            if self._is_junk_component(component):
                junk_count += 1
                logger.debug(f"Filtered junk: {component.get('name')}")
                continue

            component['type'] = self._determine_component_type(component)

            # Deduplication key: chassis components with same name+serial are duplicates
            # Only keep the first one (usually without position, or position='')
            name = component.get('name', '')
            serial = component.get('serial', '')
            comp_type = component['type']
            position = component.get('position', '')

            # Create dedup key for chassis-type components
            if comp_type == 'chassis' and serial:
                dedup_key = (name, serial, comp_type)

                # If we've seen this exact chassis before
                if dedup_key in seen_components:
                    # Skip if current one has a position (it's a transceiver line)
                    if position:
                        logger.debug(f"Skipping duplicate chassis: {name} at position {position}")
                        continue
                    # If neither has position, skip the duplicate anyway
                    elif not seen_components[dedup_key].get('position'):
                        logger.debug(f"Skipping duplicate chassis: {name}")
                        continue

                # Store this component for dedup tracking
                seen_components[dedup_key] = component

            component['extraction_source'] = 'inventory_capture'
            component['extraction_confidence'] = textfsm_result['score'] / 100.0

            components.append(component)

        if junk_count > 0:
            logger.info(f"✓ Filtered {junk_count} junk components")

        return components


    def _map_fields(self, row: Dict, field_mappings: Dict) -> Optional[Dict]:
        """Map TextFSM fields to component fields"""
        component = {}

        # Extract each field using priority mapping
        for target_field, source_fields in field_mappings.items():
            for source_field in source_fields:
                if source_field in row and row[source_field]:
                    value = str(row[source_field]).strip()
                    if value and value not in ['-', 'N/A', '']:
                        component[target_field] = value
                        break

        # Handle Juniper format (PART/TYPE/VERSION)
        # Handle Juniper format (PART/TYPE/VERSION)
        if 'type_info' in component:
            part = component.get('name', '')
            type_info = component.get('type_info', '')
            version = component.get('version', '')

            # Build smart component name
            if type_info in ['PIC', 'Xcvr', 'CPU', 'Mezz']:
                # Sub-component: combine parent + type
                component['name'] = f"{part} {type_info}"
                if version and version[0].isdigit():
                    num = version.split()[0] if ' ' in version else ''
                    if num:
                        component['name'] = f"{part} {type_info} {num}"
            else:
                # Top-level component: use part name only
                component['name'] = part

            # Description: use version info, clean up BUILTIN spam
            if version and version not in ['BUILTIN BUILTIN', 'BUILTIN', '']:
                component['description'] = version
            elif type_info and type_info not in ['BUILTIN', 'REV']:
                component['description'] = type_info
            else:
                component['description'] = ''

            component['serial'] = ''

            component.pop('type_info', None)
            component.pop('version', None)

            logger.debug(f"Juniper: {component['name']} | desc: {component['description']}")

            return component
        else:
            # Standard format - existing logic
            if not component.get('name') and component.get('description'):
                component['name'] = component['description']

        if not component.get('name'):
            return None

        component['have_sn'] = bool(component.get('serial') and len(component.get('serial', '')) > 3)
        return component
    def get_inventory_captures(self, device_filter: str = None) -> List[Dict]:
        try:
            conn = sqlite3.connect(self.assets_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = """
                SELECT * FROM v_capture_details 
                WHERE capture_type = 'inventory'
                AND extraction_success = 1
                AND file_path IS NOT NULL
            """
            params = []

            if device_filter:
                query += " AND (device_name LIKE ? OR device_normalized_name LIKE ?)"
                params.extend([f"%{device_filter}%", f"%{device_filter}%"])

            query += " ORDER BY capture_timestamp DESC"

            cursor.execute(query, params)
            captures = [dict(row) for row in cursor.fetchall()]
            conn.close()

            logger.info(f"Found {len(captures)} inventory captures")
            return captures

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []

    def load_inventory_capture(self, capture: Dict) -> int:
        file_path = capture.get('file_path')
        device_name = capture.get('device_name')  # ADD THIS

        if not file_path or not os.path.exists(file_path):
            logger.warning(f"File not found for {device_name}: {file_path}")  # ADD THIS
            return 0

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file for {device_name}: {e}")  # ADD THIS
            return 0

        if not content.strip():
            logger.warning(f"Empty file for {device_name}")  # ADD THIS
            return 0

        device_info = {
            'device_id': capture.get('device_id'),
            'hostname': device_name,
            'vendor': capture.get('vendor_name'),
            'model': capture.get('device_model'),
            'site_code': capture.get('site_code')
        }

        textfsm_result = self._parse_inventory_with_textfsm(
            content,
            capture.get('vendor_name', ''),
            capture.get('device_type_name', '')
        )

        if not textfsm_result:
            logger.warning(f"TextFSM parsing failed for {device_name}")  # ADD THIS
            return 0

        components = self._extract_components_from_textfsm(textfsm_result, device_info)

        if not components:
            logger.warning(f"No components extracted for {device_name} (all filtered as junk)")  # ADD THIS
            return 0

        return self._store_components(device_info['device_id'], components)
    def _store_components(self, device_id: int, components: List[Dict]) -> int:
        try:
            conn = sqlite3.connect(self.assets_db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM components WHERE device_id = ?", (device_id,))

            # Filter components based on serial number requirement
            components_to_store = components
            if not self.ignore_sn:
                original_count = len(components)
                components_to_store = [c for c in components if c.get('have_sn', False)]
                filtered_count = original_count - len(components_to_store)
                if filtered_count > 0:
                    logger.debug(f"Filtered {filtered_count} components without serial numbers")

            count = 0
            for comp in components_to_store:
                cursor.execute("""
                    INSERT INTO components (
                        device_id, name, description, serial, position,
                        have_sn, type, subtype, extraction_source, extraction_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    device_id,
                    comp.get('name'),
                    comp.get('description'),
                    comp.get('serial'),
                    comp.get('position'),
                    comp.get('have_sn', False),
                    comp.get('type'),
                    comp.get('subtype'),
                    comp.get('extraction_source'),
                    comp.get('extraction_confidence')
                ))
                count += 1

            conn.commit()
            conn.close()
            return count

        except sqlite3.Error:
            return 0

    def load_all_captures(self, max_files: int = None, device_filter: str = None) -> Dict[str, int]:
        captures = self.get_inventory_captures(device_filter=device_filter)

        if max_files:
            captures = captures[:max_files]

        stats = {
            'files_processed': 0,
            'files_failed': 0,
            'total_components': 0,
            'template_failures': 0,
            'failed_devices': []
        }

        logger.info(f"Processing {len(captures)} inventory captures")
        if not self.ignore_sn:
            logger.info("Filtering mode: Only storing components with serial numbers")
        else:
            logger.info("Filtering mode: Storing all components (--ignore-sn enabled)")

        for i, capture in enumerate(captures, 1):
            device_name = capture.get('device_name')
            try:
                count = self.load_inventory_capture(capture)
                if count > 0:
                    stats['files_processed'] += 1
                    stats['total_components'] += count
                else:
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    logger.warning(f"✗ FAILED: {device_name}")
            except Exception as e:
                logger.error(f"✗ ERROR on {device_name}: {e}")
                stats['files_failed'] += 1
                stats['failed_devices'].append(device_name)

        logger.info(f"\n{'=' * 70}")
        logger.info("PROCESSING COMPLETE")
        logger.info(f"Files processed: {stats['files_processed']}")
        logger.info(f"Files failed: {stats['files_failed']}")
        logger.info(f"Total components: {stats['total_components']}")

        if stats['failed_devices']:
            logger.info(f"\nFailed devices ({len(stats['failed_devices'])}):")
            for device in stats['failed_devices']:
                logger.info(f"  - {device}")

        return stats

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Load inventory captures")
    parser.add_argument("--assets-db", default="../assets.db")
    parser.add_argument("--textfsm-db", default="tfsm_templates.db")
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--device-filter")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--from-directory", help="Load directly from inventory directory (bypass capture database)")
    parser.add_argument("--ignore-sn", action="store_true",
                        help="Import all components regardless of serial number presence (default: only import components with serial numbers)")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        loader = InventoryLoader(
            assets_db_path=args.assets_db,
            textfsm_db_path=args.textfsm_db,
            ignore_sn=args.ignore_sn
        )

        if args.from_directory:
            stats = loader.load_from_directory(args.from_directory)
        else:

            stats = loader.load_all_captures(
            max_files=args.max_files,
            device_filter=args.device_filter
        )

        print(f"\nInventory Loading Summary:")
        print(f"  Processed: {stats['files_processed']}")
        print(f"  Failed: {stats['files_failed']}")
        print(f"  Components: {stats['total_components']}")
        if not args.ignore_sn:
            print(f"  Note: Only components with serial numbers were imported")
            print(f"        Use --ignore-sn to import all components")
        if stats.get('failed_devices'):
            print(f"\nFailed Devices:")
            for device in stats['failed_devices']:
                print(f"  - {device}")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())