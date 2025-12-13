#!/usr/bin/env python3
"""
Inventory Loader v4 - Unified Component Management

Parses inventory captures, classifies components, and provides maintenance operations.

Usage:
    # Load operations
    python db_loader_inventory.py load --from-directory ./inventory/
    python db_loader_inventory.py load --purge --reclassify --from-directory ./inventory/

    # Maintenance operations
    python db_loader_inventory.py cleanup --all
    python db_loader_inventory.py cleanup --device-name "sw-core"
    python db_loader_inventory.py reclassify --dry-run
    python db_loader_inventory.py reclassify --delete-junk

    # Analysis
    python db_loader_inventory.py stats
    python db_loader_inventory.py analyze
"""

import os
import re
import sqlite3
import logging
import argparse
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    from tfsm_fire import TextFSMAutoEngine

    TEXTFSM_AVAILABLE = True
except ImportError:
    TEXTFSM_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def find_textfsm_db() -> str:
    """
    Find tfsm_templates.db in the expected locations.

    Search order:
    1. Same directory as this script (for pip-installed package)
    2. Parent directory of this script
    3. Current working directory

    Returns:
        Path to tfsm_templates.db

    Raises:
        FileNotFoundError: If tfsm_templates.db cannot be found
    """
    db_filename = "tfsm_templates.db"

    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))

    search_paths = [
        # 1. Same directory as script (pip-installed package location)
        os.path.join(script_dir, db_filename),

        # 2. Parent directory of script
        os.path.join(os.path.dirname(script_dir), db_filename),

        # 3. Current working directory (backward compatibility)
        os.path.join(os.getcwd(), db_filename),
    ]

    for path in search_paths:
        if os.path.exists(path):
            logger.info(f"Found tfsm_templates.db at: {path}")
            return path

    # Not found - provide helpful error message
    searched = "\n  ".join(search_paths)
    raise FileNotFoundError(
        f"Cannot find {db_filename}. Searched:\n  {searched}\n"
        f"Please ensure tfsm_templates.db is in the package directory or parent directory."
    )


# =============================================================================
# SHARED PATTERNS
# =============================================================================

class ComponentPatterns:
    """Centralized pattern definitions for component classification"""

    # Component type classification patterns
    TYPE_PATTERNS = {
        'transceiver': [
            r'\bXcvr\b', r'\bSFP\b', r'\bQSFP\b', r'\bXFP\b', r'\bCFP\b',
            r'\bQSFP\+\b', r'\bQSFP28\b', r'\bQSFP-DD\b', r'-T$',
            r'\boptic', r'transceiver', r'GLC-', r'SFP\+-\d+G',
            r'QSFP-\d+G', r'^Q\d+-', r'^ET-', r'-CWDM',
            r'-LR\d*$', r'-SR\d*$', r'\bgbic\b', r'SFPP-',
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
            r'\bAFEB\b', r'\bMidplane\b', r'^Management$',
        ],
        'chassis': [
            r'\bchassis\b', r'\bCHAS\b', r'C\d+K-CHAS', r'-CHAS$',
            r'^DCS-\d+', r'^WS-C\d+', r'\bstack\b', r'\bswitch\s+\d+',
        ],
    }

    # Description-based patterns (secondary classification)
    DESC_PATTERNS = {
        'transceiver': [
            r'1000BASE', r'10GBASE', r'25GBASE', r'40GBASE',
            r'100GBASE', r'\bSR\b', r'\bLR\b', r'\bER\b',
        ],
    }

    # Junk detection patterns
    JUNK_PATTERNS = [
        # CLI artifacts and separators
        r'^-+$',  # Just dashes (---, ----, etc)
        r'^Item\s+Version',
        r'^Screen\s+length',
        r'^\s*$',

        # CLI prompts (various formats)
        r'@[\w\.-]+[>#]',  # user@device> or user@device#
        r'^[\w]+@[\w\.-]+>',  # speterman@agg361.iad1>
        r'^[\w]+@[\w\.-]+#',  # user@device#

        # IP addresses (not components)
        r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$',

        # Single numbers or very short strings
        r'^\d+$',
        r'^.{1,2}$',

        # Timezone/time artifacts
        r'^UTC$',
        r'^\d{2}:\d{2}:\d{2}$',  # Timestamps like 23:35:46

        # Vendor names alone (not components)
        r'^Juniper\s+Networks$',
        r'^Cisco\s+Systems',
        r'^Arista\s+Networks',

        # Version/build strings
        r'^JNPR-\d+',
        r'JUNOS\s+\d+\.',
        r'^\d+-bit\b',
        r'_buil[td]?',
        r'^JUNOS\s+\d+',

        # Login/session artifacts
        r'\blogin:',
        r'\bfrom\b.*\d{1,2}:\d{2}',
        r'^Last\s+login',

        # Screen-length/CLI settings
        r'^screen-length$',
        r'^set\s+cli',
        r'^set$',

        # Backtick garbage (malformed parsing)
        r'`.*`',

        # Python errors (from failed captures)
        r'^Traceback', r'^File\s+"/.*\.py"', r'^\s*from\s+', r'^\s*import\s+',
        r'^Fatal\s+Python\s+error', r'<frozen\s+importlib', r'<module>$',
        r'\.py",\s+line', r'/site-packages/', r'/lib/python',
        r'_bootstrap', r'exec_module', r'get_code', r'get_data',
        r'_find_and_load', r'path\.search',

        # Cisco IOSv EULA/legal text
        r'IOSv is strictly limited to use for evaluation',
        r'IOSv is provided as-is and is not supported',
        r'Technical Advisory Center',
        r'Any use or disclosure.*to any third party',
        r'purposes is',
        r'except as otherwise',
        r'demonstration.*education',
        r'in whole or',
        r'of the IOSv Software',

        # Generic legal/formatting junk
        r'^\s*\*\s*$',
        r'unknown`\*`',
    ]

    # Single-word junk
    JUNK_WORDS = {
        'Item', 'Screen', 'Networks', 'Switched', 'SwitchedBootstrap',
        'Bootstrap', 'File', 'Traceback', 'from', 'import', 'Routing',
        'set', 'cli', 'length', 'UTC', 'built', 'Last',
    }

    # Model numbers that shouldn't be standalone components
    JUNK_MODEL_PATTERNS = [
        r'^qfx\d+-[\w-]+$',  # qfx5120-48y-8c
        r'^ex\d+-[\w-]+$',  # ex4300-48t
        r'^mx\d+-[\w-]+$',  # mx480
        r'^srx\d+-[\w-]+$',  # srx340
        r'^WS-C\d+[\w-]*$',  # WS-C3750X (when alone, not in description)
        r'^N\dK-[\w-]+$',  # N9K-C93180YC
    ]

    # Legitimate Juniper prefixes (don't filter these as junk)
    JUNIPER_PREFIXES = [
        'Routing Engine', 'FPC', 'PIC', 'PEM', 'Fan Tray',
        'Power Supply', 'Midplane', 'CB', 'Chassis', 'Xcvr'
    ]


# =============================================================================
# INVENTORY LOADER
# =============================================================================

class InventoryLoader:
    """Loads inventory captures and populates components table"""

    MINIMUM_SCORE = 2

    def __init__(self, assets_db_path: str = "assets.db",
                 textfsm_db_path: Optional[str] = None,
                 ignore_sn: bool = False):
        self.assets_db_path = assets_db_path

        # Auto-locate tfsm_templates.db if not explicitly provided
        if textfsm_db_path is None:
            self.textfsm_db_path = find_textfsm_db()
        else:
            self.textfsm_db_path = textfsm_db_path

        self.textfsm_engine = None
        self.ignore_sn = ignore_sn
        self.patterns = ComponentPatterns()

        if not TEXTFSM_AVAILABLE:
            raise ImportError("TextFSM not available - install tfsm_fire")

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
            'juniper': ['juniper_junos_show_chassis_hardware'],  # Fixed: was firmware
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
        fallback_result = None  # Keep a fallback in case best result is garbage

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
                    # Check if this is a garbage PART/TYPE/VERSION parse
                    if parsed_data and 'PART' in parsed_data[0]:
                        # PART/TYPE/VERSION format - check if it's usable
                        # If most TYPE values are junk indicators, skip this result
                        junk_types = {'REV', 'BUILTIN', 'Xcvr', 'CPU', 'PIC', 'Power', 'Fan', 'length', 'Version'}
                        type_values = [row.get('TYPE', '') for row in parsed_data[:20]]
                        junk_count = sum(1 for t in type_values if t in junk_types or t.startswith('REV'))

                        if junk_count > len(type_values) * 0.5:
                            # More than half are junk - save as fallback but keep looking
                            logger.debug(f"PART/TYPE/VERSION parse looks like garbage, skipping")
                            if not fallback_result or score > fallback_result['score']:
                                fallback_result = {
                                    'template_name': template,
                                    'score': score,
                                    'parsed_data': parsed_data,
                                    'filter_used': filter_string,
                                    'template_content': template_content
                                }
                            continue

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

        # Use fallback only if we got nothing better
        if not best_result and fallback_result:
            logger.debug(f"Using fallback PART/TYPE/VERSION result")
            best_result = fallback_result

        if best_result and best_result['score'] >= self.MINIMUM_SCORE:
            logger.debug(f"Selected template: {best_result['template_name']} (score: {best_result['score']})")
            if best_result['parsed_data']:
                first_row = best_result['parsed_data'][0]
                logger.debug(f"Data format keys: {list(first_row.keys())}")
            return best_result
        return None

    def _is_junk_component(self, component: Dict) -> bool:
        """Check if component is junk/garbage data"""
        name = component.get('name', '').strip()
        description = component.get('description', '').strip()

        if not name:
            return True

        # Exception: Don't mark legitimate Juniper components as junk
        if any(name.startswith(prefix) for prefix in self.patterns.JUNIPER_PREFIXES):
            return False

        # Check single-word junk
        if name in self.patterns.JUNK_WORDS:
            return True

        # Check if it's just a model number (not a real component)
        for pattern in self.patterns.JUNK_MODEL_PATTERNS:
            if re.match(pattern, name, re.IGNORECASE):
                return True

        text = f"{name} {description}"
        return any(re.search(pattern, text, re.IGNORECASE)
                   for pattern in self.patterns.JUNK_PATTERNS)

    def _determine_component_type(self, component: Dict) -> Tuple[str, str]:
        """Determine component type and confidence level"""
        name = component.get('name', '')
        description = component.get('description', '')

        # Check name patterns first (high confidence)
        for comp_type, patterns in self.patterns.TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, name, re.IGNORECASE):
                    return comp_type, 'high'

        # Check description patterns (medium confidence)
        for comp_type, patterns in self.patterns.DESC_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, description, re.IGNORECASE):
                    return comp_type, 'medium'

        # Fallback: check description against type patterns (medium confidence)
        for comp_type, patterns in self.patterns.TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, description, re.IGNORECASE):
                    return comp_type, 'medium'

        return 'unknown', 'low'

    def _map_fields(self, row: Dict, field_mappings: Dict) -> Optional[Dict]:
        """Map TextFSM fields to component fields"""
        component = {}

        for target_field, source_fields in field_mappings.items():
            for source_field in source_fields:
                if source_field in row and row[source_field]:
                    value = str(row[source_field]).strip()
                    if value and value not in ['-', 'N/A', '']:
                        component[target_field] = value
                        break

        # Handle Juniper format (PART/TYPE/VERSION)
        if 'type_info' in component:
            part = component.get('name', '')
            type_info = component.get('type_info', '')
            version = component.get('version', '')

            if type_info in ['PIC', 'Xcvr', 'CPU', 'Mezz']:
                component['name'] = f"{part} {type_info}"
                if version and version[0].isdigit():
                    num = version.split()[0] if ' ' in version else ''
                    if num:
                        component['name'] = f"{part} {type_info} {num}"
            else:
                component['name'] = part

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
            if not component.get('name') and component.get('description'):
                component['name'] = component['description']

        if not component.get('name'):
            return None

        component['have_sn'] = bool(component.get('serial') and len(component.get('serial', '')) > 3)

        # Additional validation: reject if serial looks like junk
        serial = component.get('serial', '')
        if serial:
            # Timestamps are not serials
            if re.match(r'^\d{2}:\d{2}:\d{2}$', serial):
                component['have_sn'] = False
            # CLI keywords are not serials
            if serial.lower() in ('screen-length', 'set', 'cli', 'to', 'from'):
                component['have_sn'] = False

        return component

    def _extract_components_from_textfsm(self, textfsm_result: Dict,
                                         device_info: Dict) -> List[Dict]:
        """Extract and classify components from TextFSM parsed data"""
        components = []
        parsed_data = textfsm_result.get('parsed_data', [])

        if not parsed_data:
            return components

        # Detect format and vendor
        vendor = device_info.get('vendor', '').lower()
        is_juniper = 'juniper' in vendor

        # Fallback: detect Juniper format from data patterns
        # Juniper show chassis hardware has VID as serial and SN as description
        if not is_juniper and parsed_data and 'VID' in parsed_data[0] and 'SN' in parsed_data[0]:
            # Check if SN values look like descriptions (contain letters + special chars)
            # and VID values look like serials (alphanumeric, no common description words)
            sample = parsed_data[:10]
            sn_looks_like_desc = sum(1 for r in sample if '-' in r.get('SN', '') and 'G' in r.get('SN', ''))
            vid_looks_like_serial = sum(1 for r in sample if r.get('VID', '').replace('-', '').isalnum()
                                        and len(r.get('VID', '')) > 5
                                        and not any(x in r.get('VID', '').upper() for x in ['SFP', 'QSFP', 'LR', 'SR']))
            if sn_looks_like_desc >= 3 and vid_looks_like_serial >= 3:
                is_juniper = True
                logger.debug(f"Auto-detected Juniper format from data patterns (SN has descriptions, VID has serials)")

        logger.debug(f"Vendor detection: vendor='{vendor}', is_juniper={is_juniper}")

        if parsed_data and 'PART' in parsed_data[0]:
            # Juniper PART/TYPE/VERSION format
            field_mappings = {
                'name': ['PART'],
                'type_info': ['TYPE'],
                'version': ['VERSION']
            }
        elif is_juniper and parsed_data and 'VID' in parsed_data[0]:
            # Juniper with Cisco-style template - fields are swapped!
            # VID contains serial, SN contains description
            field_mappings = {
                'name': ['NAME', 'name'],
                'description': ['SN'],  # Juniper puts description in SN
                'serial': ['VID'],  # Juniper puts serial in VID
                'model': ['PID', 'model'],
                'position': ['DESCRIPTION'],  # Has port number like "2       REV 01"
            }
            logger.debug(f"Using Juniper-specific field mapping (VID->serial, SN->description)")
        else:
            # Standard Cisco/Arista format
            field_mappings = {
                'name': ['NAME', 'name'],
                'description': ['DESCR', 'description', 'DESCRIPTION'],
                'serial': ['SN', 'serial', 'SERIAL_NUMBER'],
                'model': ['PID', 'model', 'MODEL'],
                'version': ['VID', 'version', 'VERSION'],
                'position': ['PORT', 'SLOT', 'position', 'POSITION']
            }

        junk_count = 0
        seen_components = {}

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

            comp_type, confidence = self._determine_component_type(component)
            component['type'] = comp_type
            component['type_confidence'] = confidence

            # Deduplication for chassis components
            name = component.get('name', '')
            serial = component.get('serial', '')
            position = component.get('position', '')

            if comp_type == 'chassis' and serial:
                dedup_key = (name, serial, comp_type)

                if dedup_key in seen_components:
                    if position:
                        logger.debug(f"Skipping duplicate chassis: {name} at position {position}")
                        continue
                    elif not seen_components[dedup_key].get('position'):
                        logger.debug(f"Skipping duplicate chassis: {name}")
                        continue

                seen_components[dedup_key] = component

            component['extraction_source'] = 'inventory_capture'
            component['extraction_confidence'] = textfsm_result['score'] / 100.0

            components.append(component)

        if junk_count > 0:
            logger.info(f"  Filtered {junk_count} junk components")

        return components

    def _store_components(self, device_id: int, components: List[Dict]) -> int:
        """Store components in database"""
        try:
            conn = sqlite3.connect(self.assets_db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM components WHERE device_id = ?", (device_id,))

            components_to_store = components
            if not self.ignore_sn:
                original_count = len(components)
                components_to_store = [c for c in components if c.get('have_sn', False)]
                filtered_count = original_count - len(components_to_store)
                if filtered_count > 0:
                    logger.debug(f"Filtered {filtered_count} components without serial numbers")
                    # Show sample of what was filtered
                    no_sn = [c for c in components if not c.get('have_sn', False)][:3]
                    for c in no_sn:
                        logger.debug(f"  No SN: {c.get('name')} | serial={c.get('serial')}")

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

        except sqlite3.Error as e:
            logger.error(f"Database error storing components: {e}")
            return 0

    def purge_all_components(self) -> int:
        """Delete ALL components from database"""
        try:
            conn = sqlite3.connect(self.assets_db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM components")
            count = cursor.fetchone()[0]

            if count == 0:
                logger.info("No components to purge")
                conn.close()
                return 0

            cursor.execute("DELETE FROM components")
            conn.commit()

            cursor.execute("SELECT COUNT(*) FROM components")
            remaining = cursor.fetchone()[0]

            conn.close()

            logger.info(f"✓ Purged {count} component records")
            if remaining > 0:
                logger.warning(f"Warning: {remaining} records remaining")

            return count

        except sqlite3.Error as e:
            logger.error(f"Database error during purge: {e}")
            return 0

    def load_from_directory(self, inventory_dir: str, vendor: str = None,
                            device_filter: str = None) -> Dict[str, int]:
        """Load inventory files directly from directory"""
        import glob

        if not os.path.exists(inventory_dir):
            logger.error(f"Directory not found: {inventory_dir}")
            return {'files_processed': 0, 'files_failed': 0, 'total_components': 0}

        pattern = os.path.join(inventory_dir, "*.txt")
        files = glob.glob(pattern)

        # Apply device filter if specified
        if device_filter:
            files = [f for f in files if device_filter.lower() in os.path.basename(f).lower()]
            logger.info(f"Filtered to {len(files)} files matching '{device_filter}'")
        else:
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
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                if not content.strip():
                    logger.warning(f"Empty file: {device_name}")
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    continue

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

                cursor.execute("SELECT name FROM vendors WHERE id = ?", (vendor_id,))
                vendor_result = cursor.fetchone()
                vendor_name = vendor_result[0] if vendor_result else (vendor or '')
                conn.close()

                textfsm_result = self._parse_inventory_with_textfsm(content, vendor_name)

                if not textfsm_result:
                    logger.warning(f"TextFSM parsing failed for {device_name}")
                    stats['files_failed'] += 1
                    stats['failed_devices'].append(device_name)
                    continue

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

        self._log_summary(stats)
        return stats

    def get_inventory_captures(self, device_filter: str = None) -> List[Dict]:
        """Get inventory captures from capture database"""
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
        """Load a single inventory capture"""
        file_path = capture.get('file_path')
        device_name = capture.get('device_name')

        if not file_path or not os.path.exists(file_path):
            logger.warning(f"File not found for {device_name}: {file_path}")
            return 0

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file for {device_name}: {e}")
            return 0

        if not content.strip():
            logger.warning(f"Empty file for {device_name}")
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
            logger.warning(f"TextFSM parsing failed for {device_name}")
            return 0

        components = self._extract_components_from_textfsm(textfsm_result, device_info)

        if not components:
            logger.warning(f"No components extracted for {device_name} (all filtered as junk)")
            return 0

        return self._store_components(device_info['device_id'], components)

    def load_all_captures(self, max_files: int = None, device_filter: str = None) -> Dict[str, int]:
        """Load all inventory captures from database"""
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

        self._log_summary(stats)
        return stats

    def _log_summary(self, stats: Dict):
        """Log processing summary"""
        logger.info(f"\n{'=' * 70}")
        logger.info("PROCESSING COMPLETE")
        logger.info(f"Files processed: {stats['files_processed']}")
        logger.info(f"Files failed: {stats['files_failed']}")
        logger.info(f"Total components: {stats['total_components']}")

        if stats.get('failed_devices'):
            logger.info(f"\nFailed devices ({len(stats['failed_devices'])}):")
            for device in stats['failed_devices']:
                logger.info(f"  - {device}")


# =============================================================================
# COMPONENT MAINTENANCE (Cleanup + Reclassify)
# =============================================================================

class ComponentMaintenance:
    """Maintenance operations for component data"""

    def __init__(self, db_path: str = "assets.db", dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.patterns = ComponentPatterns()
        self.stats = defaultdict(int)

    # -------------------------------------------------------------------------
    # Cleanup Operations
    # -------------------------------------------------------------------------

    def cleanup_all(self) -> int:
        """Delete all component records"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM components")
            count = cursor.fetchone()[0]

            if count == 0:
                logger.info("No components to clean up")
                conn.close()
                return 0

            if not self.dry_run:
                cursor.execute("DELETE FROM components")
                conn.commit()
                logger.info(f"✓ Deleted {count} component records")
            else:
                logger.info(f"[DRY RUN] Would delete {count} component records")

            conn.close()
            return count

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    def cleanup_by_device(self, device_id: int = None, device_name: str = None) -> int:
        """Delete components for specific device(s)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if device_id:
                cursor.execute("SELECT COUNT(*) FROM components WHERE device_id = ?", (device_id,))
                count = cursor.fetchone()[0]

                if not self.dry_run:
                    cursor.execute("DELETE FROM components WHERE device_id = ?", (device_id,))
                    conn.commit()
                    logger.info(f"✓ Deleted {count} components for device_id={device_id}")
                else:
                    logger.info(f"[DRY RUN] Would delete {count} components for device_id={device_id}")

                conn.close()
                return count

            elif device_name:
                cursor.execute("""
                    SELECT id, name FROM devices 
                    WHERE name LIKE ? OR normalized_name LIKE ?
                """, (f"%{device_name}%", f"%{device_name}%"))

                devices = cursor.fetchall()
                total_deleted = 0

                for dev_id, dev_name in devices:
                    cursor.execute("SELECT COUNT(*) FROM components WHERE device_id = ?", (dev_id,))
                    count = cursor.fetchone()[0]

                    if not self.dry_run:
                        cursor.execute("DELETE FROM components WHERE device_id = ?", (dev_id,))
                        logger.info(f"✓ Deleted {count} components from {dev_name}")
                    else:
                        logger.info(f"[DRY RUN] Would delete {count} components from {dev_name}")

                    total_deleted += count

                if not self.dry_run:
                    conn.commit()

                logger.info(f"Total: {total_deleted} components from {len(devices)} devices")
                conn.close()
                return total_deleted

            conn.close()
            return 0

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    def cleanup_by_source(self, extraction_source: str) -> int:
        """Delete components by extraction source"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM components WHERE extraction_source = ?",
                (extraction_source,)
            )
            count = cursor.fetchone()[0]

            if not self.dry_run:
                cursor.execute(
                    "DELETE FROM components WHERE extraction_source = ?",
                    (extraction_source,)
                )
                conn.commit()
                logger.info(f"✓ Deleted {count} components with source='{extraction_source}'")
            else:
                logger.info(f"[DRY RUN] Would delete {count} components with source='{extraction_source}'")

            conn.close()
            return count

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    # -------------------------------------------------------------------------
    # Reclassification Operations
    # -------------------------------------------------------------------------

    def _is_junk(self, name: str, description: str = "") -> bool:
        """Check if component is junk"""
        if name.strip() in self.patterns.JUNK_WORDS:
            return True

        # Exception for Juniper
        if any(name.startswith(prefix) for prefix in self.patterns.JUNIPER_PREFIXES):
            return False

        # Check if it's just a model number (not a real component)
        for pattern in self.patterns.JUNK_MODEL_PATTERNS:
            if re.match(pattern, name, re.IGNORECASE):
                return True

        text = f"{name} {description}"
        return any(re.search(pattern, text, re.IGNORECASE)
                   for pattern in self.patterns.JUNK_PATTERNS)

    def _classify_component(self, name: str, description: str = "") -> Tuple[Optional[str], str]:
        """Classify a component by name/description"""
        if not name:
            return None, 'low'

        if self._is_junk(name, description):
            return 'junk', 'high'

        for comp_type, patterns in self.patterns.TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, name, re.IGNORECASE):
                    return comp_type, 'high'

        for comp_type, patterns in self.patterns.DESC_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, description or '', re.IGNORECASE):
                    return comp_type, 'medium'

        return None, 'low'

    def reclassify_unknown(self) -> Dict[str, int]:
        """Reclassify components with type='unknown'"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, description, type, device_id
                FROM components
                WHERE type = 'unknown' OR type IS NULL
            """)

            unknown_components = cursor.fetchall()
            logger.info(f"Found {len(unknown_components)} unknown components to reclassify")

            reclassified = defaultdict(int)
            updates = []

            for comp in unknown_components:
                new_type, confidence = self._classify_component(
                    comp['name'],
                    comp['description'] or ''
                )

                if new_type and new_type != 'unknown':
                    reclassified[new_type] += 1
                    updates.append({
                        'id': comp['id'],
                        'name': comp['name'],
                        'old_type': comp['type'],
                        'new_type': new_type,
                        'confidence': confidence
                    })

            if updates:
                logger.info("\nSample reclassifications:")
                for update in updates[:20]:
                    logger.info(
                        f"  {update['name'][:40]:40} → {update['new_type']:12} "
                        f"({update['confidence']})"
                    )

            if not self.dry_run and updates:
                for update in updates:
                    cursor.execute("""
                        UPDATE components 
                        SET type = ?, subtype = 'reclassified'
                        WHERE id = ?
                    """, (update['new_type'], update['id']))

                conn.commit()
                logger.info(f"\n✓ Updated {len(updates)} components")
            elif self.dry_run:
                logger.info(f"\n[DRY RUN] Would update {len(updates)} components")

            conn.close()
            return dict(reclassified)

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return {}

    def delete_junk_components(self) -> int:
        """Delete components identified as junk"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT id, name, description FROM components")
            all_components = cursor.fetchall()

            junk_ids = []
            for comp in all_components:
                if self._is_junk(comp['name'], comp['description'] or ''):
                    junk_ids.append(comp['id'])

            logger.info(f"Found {len(junk_ids)} junk components")

            if not self.dry_run and junk_ids:
                placeholders = ','.join('?' * len(junk_ids))
                cursor.execute(
                    f"DELETE FROM components WHERE id IN ({placeholders})",
                    junk_ids
                )
                conn.commit()
                logger.info(f"✓ Deleted {len(junk_ids)} junk components")
            elif self.dry_run:
                logger.info(f"[DRY RUN] Would delete {len(junk_ids)} junk components")

            conn.close()
            return len(junk_ids)

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    # -------------------------------------------------------------------------
    # Statistics & Analysis
    # -------------------------------------------------------------------------

    def get_statistics(self) -> Dict:
        """Get comprehensive component statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            stats = {}

            # Total components
            cursor.execute("SELECT COUNT(*) FROM components")
            stats['total_components'] = cursor.fetchone()[0]

            # Devices with components
            cursor.execute("SELECT COUNT(DISTINCT device_id) FROM components")
            stats['devices_with_components'] = cursor.fetchone()[0]

            # By type
            cursor.execute("""
                SELECT type, COUNT(*) as count 
                FROM components 
                GROUP BY type 
                ORDER BY count DESC
            """)
            stats['by_type'] = dict(cursor.fetchall())

            # By source
            cursor.execute("""
                SELECT extraction_source, COUNT(*) as count 
                FROM components 
                GROUP BY extraction_source
            """)
            stats['by_source'] = dict(cursor.fetchall())

            # With serials
            cursor.execute("SELECT COUNT(*) FROM components WHERE have_sn = 1")
            stats['with_serial'] = cursor.fetchone()[0]

            # Reclassified
            cursor.execute("SELECT COUNT(*) FROM components WHERE subtype = 'reclassified'")
            stats['reclassified_count'] = cursor.fetchone()[0]

            # Unknown percentage
            total = stats['total_components']
            unknown = stats['by_type'].get('unknown', 0)
            stats['unknown_pct'] = (unknown / total * 100) if total > 0 else 0

            conn.close()
            return stats

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return {}

    def analyze_remaining_unknown(self) -> List[Dict]:
        """Analyze patterns in remaining unknown components"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.name, c.description, c.type,
                    d.name as device_name, d.model as device_model,
                    COUNT(*) as count
                FROM components c
                JOIN devices d ON c.device_id = d.id
                WHERE c.type = 'unknown' OR c.type IS NULL
                GROUP BY c.name, c.description, d.model
                ORDER BY count DESC
                LIMIT 50
            """)

            remaining = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if remaining:
                print("\nTop remaining 'unknown' patterns:")
                print("=" * 100)
                for item in remaining[:20]:
                    print(
                        f"{item['count']:4} × {item['name'][:40]:40} "
                        f"| {(item['device_model'] or 'unknown')[:20]:20}"
                    )

            return remaining

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []


# =============================================================================
# CLI
# =============================================================================

def cmd_load(args):
    """Handle load subcommand"""
    try:
        # Create loader - only pass textfsm_db_path if user explicitly provided it
        loader_kwargs = {
            'assets_db_path': args.assets_db,
            'ignore_sn': args.ignore_sn
        }

        # Only pass textfsm_db_path if user specified it (not using default)
        if args.textfsm_db is not None:
            loader_kwargs['textfsm_db_path'] = args.textfsm_db

        loader = InventoryLoader(**loader_kwargs)

        # Purge if requested
        if args.purge:
            print("\n" + "=" * 70)
            print("PURGING ALL COMPONENTS")
            print("=" * 70)
            purged = loader.purge_all_components()
            print(f"Purged {purged} components\n")

        # Load
        if args.from_directory:
            stats = loader.load_from_directory(args.from_directory, device_filter=args.device_filter)
        else:
            stats = loader.load_all_captures(
                max_files=args.max_files,
                device_filter=args.device_filter
            )

        # Reclassify if requested
        if args.reclassify:
            print("\n" + "=" * 70)
            print("RECLASSIFYING UNKNOWN COMPONENTS")
            print("=" * 70)
            maintenance = ComponentMaintenance(db_path=args.assets_db, dry_run=False)
            reclassified = maintenance.reclassify_unknown()
            if reclassified:
                print("\nReclassification results:")
                for comp_type, count in sorted(reclassified.items(), key=lambda x: x[1], reverse=True):
                    print(f"  {comp_type:15} {count:5}")

        # Summary
        print(f"\nInventory Loading Summary:")
        print(f"  Processed: {stats['files_processed']}")
        print(f"  Failed: {stats['files_failed']}")
        print(f"  Components: {stats['total_components']}")
        if not args.ignore_sn:
            print(f"  Note: Only components with serial numbers were imported")
            print(f"        Use --ignore-sn to import all components")

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


def cmd_cleanup(args):
    """Handle cleanup subcommand"""
    maintenance = ComponentMaintenance(db_path=args.assets_db, dry_run=args.dry_run)

    # Confirm
    if not args.confirm and not args.dry_run:
        response = input("\nThis will delete component records. Continue? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled")
            return 0

    if args.all:
        count = maintenance.cleanup_all()
    elif args.device_id:
        count = maintenance.cleanup_by_device(device_id=args.device_id)
    elif args.device_name:
        count = maintenance.cleanup_by_device(device_name=args.device_name)
    elif args.source:
        count = maintenance.cleanup_by_source(args.source)
    else:
        print("Specify --all, --device-id, --device-name, or --source")
        return 1

    print(f"\nCleaned up {count} component records")
    return 0


def cmd_reclassify(args):
    """Handle reclassify subcommand"""
    maintenance = ComponentMaintenance(db_path=args.assets_db, dry_run=args.dry_run)

    # Show initial state
    initial_stats = maintenance.get_statistics()
    total = initial_stats.get('total_components', 0)
    unknown = initial_stats.get('by_type', {}).get('unknown', 0)

    print("\n" + "=" * 70)
    print("INITIAL STATE")
    print("=" * 70)
    print(f"Total components: {total}")
    print(f"Unknown: {unknown} ({initial_stats.get('unknown_pct', 0):.1f}%)")

    # Delete junk if requested
    if args.delete_junk:
        print("\n" + "=" * 70)
        print("DELETING JUNK COMPONENTS")
        print("=" * 70)
        maintenance.delete_junk_components()

    # Reclassify
    print("\n" + "=" * 70)
    print("RECLASSIFYING UNKNOWN COMPONENTS")
    print("=" * 70)
    reclassified = maintenance.reclassify_unknown()

    if reclassified:
        print("\nReclassification Results:")
        for comp_type, count in sorted(reclassified.items(), key=lambda x: x[1], reverse=True):
            print(f"  {comp_type:15} {count:5}")

    # Final state
    final_stats = maintenance.get_statistics()
    total = final_stats.get('total_components', 0)
    unknown = final_stats.get('by_type', {}).get('unknown', 0)

    print("\n" + "=" * 70)
    print("FINAL STATE")
    print("=" * 70)
    print(f"Total components: {total}")
    print(f"Unknown: {unknown} ({final_stats.get('unknown_pct', 0):.1f}%)")
    print(f"Reclassified: {final_stats.get('reclassified_count', 0)}")

    return 0


def cmd_stats(args):
    """Handle stats subcommand"""
    maintenance = ComponentMaintenance(db_path=args.assets_db)
    stats = maintenance.get_statistics()

    total = stats.get('total_components', 0)

    print("\nComponent Statistics:")
    print("=" * 50)
    print(f"  Total components: {total}")
    print(f"  Devices with components: {stats.get('devices_with_components', 0)}")
    print(f"  Components with serials: {stats.get('with_serial', 0)}")
    print(f"  Reclassified: {stats.get('reclassified_count', 0)}")
    print(f"  Unknown: {stats.get('unknown_pct', 0):.1f}%")

    print("\n  By Type:")
    for comp_type, count in sorted(stats.get('by_type', {}).items(), key=lambda x: x[1], reverse=True):
        pct = (count / total * 100) if total > 0 else 0
        print(f"    {comp_type or 'NULL':15} {count:5} ({pct:5.1f}%)")

    print("\n  By Source:")
    for source, count in stats.get('by_source', {}).items():
        print(f"    {source or 'unknown':20} {count}")

    return 0


def cmd_analyze(args):
    """Handle analyze subcommand"""
    maintenance = ComponentMaintenance(db_path=args.assets_db)
    maintenance.analyze_remaining_unknown()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Inventory Loader - Unified Component Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load with purge and reclassify
  %(prog)s load --purge --reclassify --from-directory ./inventory/

  # Cleanup specific device
  %(prog)s cleanup --device-name "sw-core" --confirm

  # Reclassify with dry-run
  %(prog)s reclassify --dry-run --delete-junk

  # Show statistics
  %(prog)s stats
        """
    )

    parser.add_argument("--assets-db",
                        default=os.path.expanduser("~/.velocitycmdb/data/assets.db"),
                        help="Path to assets database")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Load subcommand
    load_parser = subparsers.add_parser("load", help="Load inventory data")
    load_parser.add_argument("--textfsm-db", default=None,
                             help="Path to TextFSM templates database (auto-discovered if not specified)")
    load_parser.add_argument("--from-directory", help="Load from directory (bypass capture database)")
    load_parser.add_argument("--max-files", type=int, help="Maximum files to process")
    load_parser.add_argument("--device-filter", help="Filter devices by name pattern")
    load_parser.add_argument("--ignore-sn", action="store_true",
                             help="Import all components regardless of serial number")
    load_parser.add_argument("--purge", action="store_true",
                             help="Purge all components before loading")
    load_parser.add_argument("--reclassify", action="store_true",
                             help="Reclassify unknown components after loading")

    # Cleanup subcommand
    cleanup_parser = subparsers.add_parser("cleanup", help="Remove component data")
    cleanup_group = cleanup_parser.add_mutually_exclusive_group(required=True)
    cleanup_group.add_argument("--all", action="store_true", help="Delete all components")
    cleanup_group.add_argument("--device-id", type=int, help="Delete by device ID")
    cleanup_group.add_argument("--device-name", help="Delete by device name pattern")
    cleanup_group.add_argument("--source", help="Delete by extraction source")
    cleanup_parser.add_argument("--confirm", action="store_true", help="Skip confirmation")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    # Reclassify subcommand
    reclassify_parser = subparsers.add_parser("reclassify", help="Reclassify unknown components")
    reclassify_parser.add_argument("--dry-run", action="store_true", help="Don't make changes")
    reclassify_parser.add_argument("--delete-junk", action="store_true", help="Delete junk components")

    # Stats subcommand
    stats_parser = subparsers.add_parser("stats", help="Show component statistics")

    # Analyze subcommand
    analyze_parser = subparsers.add_parser("analyze", help="Analyze remaining unknown components")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        'load': cmd_load,
        'cleanup': cmd_cleanup,
        'reclassify': cmd_reclassify,
        'stats': cmd_stats,
        'analyze': cmd_analyze,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    exit(main())