#!/usr/bin/env python3
"""
OSPF Peering Report Generator
Generates an HTML report of OSPF neighbor relationships from capture data.
Uses tfsm_fire for vendor-agnostic TextFSM parsing.
"""

import os
import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
import logging
import click
import json

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Try to import tfsm_fire - handle gracefully if not available
try:
    from tfsm_fire import TextFSMAutoEngine

    TFSM_AVAILABLE = True
except ImportError:
    TFSM_AVAILABLE = False
    logger.warning("tfsm_fire not available - will use fallback regex parsing")


@dataclass
class OSPFNeighbor:
    """Represents an OSPF neighbor relationship"""
    neighbor_id: str
    neighbor_ip: str
    interface: str
    state: str
    priority: str = ""
    dead_time: str = ""
    vrf: str = ""  # Arista provides this
    instance: str = ""  # Arista provides this
    # Resolved from database lookup
    resolved_name: str = ""
    resolved_site: str = ""

    @property
    def display_name(self) -> str:
        """Return resolved name if available, otherwise neighbor_id"""
        if self.resolved_name:
            return self.resolved_name
        return self.neighbor_id or self.neighbor_ip

    @property
    def is_full(self) -> bool:
        """Check if neighbor is in FULL state"""
        return 'FULL' in self.state.upper()

    @property
    def state_class(self) -> str:
        """CSS class based on state"""
        state_upper = self.state.upper()
        if 'FULL' in state_upper:
            return 'state-full'
        elif 'DOWN' in state_upper:
            return 'state-down'
        elif '2WAY' in state_upper or 'TWO' in state_upper:
            return 'state-2way'
        elif 'INIT' in state_upper or 'ATTEMPT' in state_upper:
            return 'state-init'
        elif 'EXSTART' in state_upper or 'EXCHANGE' in state_upper or 'LOADING' in state_upper:
            return 'state-transition'
        return 'state-unknown'

    @property
    def state_display(self) -> str:
        """Clean state for display (handle Cisco's 'FULL/ -' format)"""
        return self.state.replace('/ -', '').replace('/-', '').strip()


@dataclass
class DeviceOSPFData:
    """OSPF data for a single device"""
    device_id: int
    device_name: str
    site_code: str
    vendor: str
    model: str
    management_ip: str
    capture_timestamp: str
    neighbors: List[OSPFNeighbor] = field(default_factory=list)
    parse_success: bool = True
    parse_error: str = ""
    raw_content: str = ""


class OSPFReportGenerator:
    """Generate OSPF peering reports from capture database"""

    # TextFSM filter patterns by vendor
    VENDOR_FILTERS = {
        'cisco': [
            'cisco_ios_show_ip_ospf_neighbor',
            'cisco_nxos_show_ip_ospf_neighbor',
            'cisco_xr_show_ospf_neighbor',
            'show_ip_ospf_neighbor',
        ],
        'arista': [
            'arista_eos_show_ip_ospf_neighbor',
            'show_ip_ospf_neighbor',
        ],
        'juniper': [
            'juniper_junos_show_ospf_neighbor',
            'show_ospf_neighbor',
        ],
    }

    # Field mappings for normalization across vendors
    # All three vendors (Cisco, Arista, Juniper) use consistent field names:
    #   NEIGHBOR_ID, PRIORITY, STATE, DEAD_TIME, IP_ADDRESS, INTERFACE
    # Arista additionally provides: INSTANCE, VRF
    FIELD_MAPPINGS = {
        'neighbor_id': ['NEIGHBOR_ID'],
        'neighbor_ip': ['IP_ADDRESS'],
        'interface': ['INTERFACE'],
        'state': ['STATE'],
        'priority': ['PRIORITY'],
        'dead_time': ['DEAD_TIME'],
        'vrf': ['VRF'],
        'instance': ['INSTANCE'],
    }

    def __init__(self, db_path: str, tfsm_db_path: str = None):
        """
        Initialize report generator

        Args:
            db_path: Path to assets.db (capture database)
            tfsm_db_path: Path to tfsm_templates.db (TextFSM templates)
        """
        self.db_path = db_path
        self.tfsm_engine = None

        if TFSM_AVAILABLE and tfsm_db_path:
            try:
                tfsm_db = Path(tfsm_db_path).expanduser().resolve()
                if tfsm_db.exists():
                    self.tfsm_engine = TextFSMAutoEngine(str(tfsm_db))
                    logger.info(f"TextFSM engine initialized: {tfsm_db}")
                else:
                    logger.warning(f"TextFSM database not found: {tfsm_db}")
            except Exception as e:
                logger.warning(f"Could not initialize TextFSM engine: {e}")

    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def resolve_neighbor_ips(self, neighbor_ips: set) -> Dict[str, Dict]:
        """
        Resolve neighbor IPs to device names using management_ip and ipv4_address

        Returns: Dict mapping IP -> {device_name, device_id, site_code, vendor}
        """
        if not neighbor_ips:
            return {}

        ip_to_device = {}

        with self.get_db_connection() as conn:
            cursor = conn.cursor()

            # Build query for all IPs at once
            placeholders = ','.join('?' * len(neighbor_ips))

            cursor.execute(f"""
                SELECT d.id, d.name, d.normalized_name, d.site_code, 
                       d.management_ip, d.ipv4_address,
                       v.name as vendor_name
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE d.management_ip IN ({placeholders})
                   OR d.ipv4_address IN ({placeholders})
            """, list(neighbor_ips) + list(neighbor_ips))

            for row in cursor.fetchall():
                row_dict = dict(row)
                device_info = {
                    'device_id': row_dict['id'],
                    'device_name': row_dict['name'],
                    'normalized_name': row_dict['normalized_name'],
                    'site_code': row_dict['site_code'],
                    'vendor': row_dict.get('vendor_name', ''),
                }

                # Map both management_ip and ipv4_address if they exist
                if row_dict['management_ip']:
                    ip_to_device[row_dict['management_ip']] = device_info
                if row_dict['ipv4_address']:
                    ip_to_device[row_dict['ipv4_address']] = device_info

        logger.info(f"Resolved {len(ip_to_device)} IPs to device names out of {len(neighbor_ips)} unique neighbor IPs")
        return ip_to_device

    def get_ospf_captures(self, site_filter: str = None,
                          device_filter: str = None) -> List[Dict]:
        """
        Retrieve OSPF neighbor captures from database

        Returns list of capture data with device info
        """
        with self.get_db_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT 
                    cs.id as snapshot_id,
                    cs.device_id,
                    cs.capture_type,
                    cs.captured_at,
                    cs.content,
                    cs.file_path,
                    d.name as device_name,
                    d.normalized_name,
                    d.site_code,
                    d.model,
                    d.management_ip,
                    v.name as vendor_name,
                    v.short_name as vendor_short
                FROM capture_snapshots cs
                JOIN devices d ON cs.device_id = d.id
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE cs.capture_type = 'ospf-neighbor'
                AND cs.id IN (
                    SELECT MAX(id) FROM capture_snapshots 
                    WHERE capture_type = 'ospf-neighbor'
                    GROUP BY device_id
                )
            """

            params = []
            conditions = []

            if site_filter:
                conditions.append("d.site_code LIKE ?")
                params.append(f"%{site_filter}%")

            if device_filter:
                conditions.append("(d.name LIKE ? OR d.normalized_name LIKE ?)")
                params.append(f"%{device_filter}%")
                params.append(f"%{device_filter}%")

            if conditions:
                query += " AND " + " AND ".join(conditions)

            query += " ORDER BY d.site_code, d.name"

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def normalize_vendor(self, vendor_name: str) -> str:
        """Normalize vendor name for template matching"""
        if not vendor_name:
            return 'cisco'  # Default fallback

        vendor_lower = vendor_name.lower()

        if 'cisco' in vendor_lower:
            return 'cisco'
        elif 'arista' in vendor_lower:
            return 'arista'
        elif 'juniper' in vendor_lower or 'junos' in vendor_lower:
            return 'juniper'

        return 'cisco'  # Default

    def get_normalized_field(self, row: Dict, field_name: str) -> str:
        """Extract field value using multiple possible field names"""
        possible_names = self.FIELD_MAPPINGS.get(field_name, [field_name.upper()])

        for name in possible_names:
            if name in row and row[name]:
                return str(row[name]).strip()

        return ""

    def parse_with_tfsm(self, content: str, vendor: str) -> Tuple[List[Dict], str]:
        """
        Parse OSPF neighbor output using tfsm_fire

        Returns: (parsed_records, error_message)
        """
        if not self.tfsm_engine:
            return [], "TextFSM engine not available"

        filters = self.VENDOR_FILTERS.get(vendor, self.VENDOR_FILTERS['cisco'])

        for filter_string in filters:
            try:
                result = self.tfsm_engine.find_best_template(content, filter_string)

                # Handle different return formats
                if len(result) == 4:
                    template, parsed_data, score, template_content = result
                elif len(result) == 3:
                    template, parsed_data, score = result
                else:
                    continue

                if parsed_data and score >= 20:  # Lower threshold per your guide
                    logger.debug(f"Template '{template}' matched with score {score}, "
                                 f"parsed {len(parsed_data)} records")
                    return parsed_data, ""

            except Exception as e:
                logger.debug(f"Filter '{filter_string}' failed: {e}")
                continue

        return [], "No matching template found"

    def parse_with_regex(self, content: str, vendor: str) -> List[Dict]:
        """
        Fallback regex parsing for OSPF neighbor output
        Handles common Cisco/Arista/Juniper formats
        Returns same field names as TextFSM templates
        """
        neighbors = []

        # Cisco IOS/NX-OS/Arista pattern
        # Neighbor ID     Pri   State           Dead Time   Address         Interface
        # 10.0.0.1        1     FULL/DR         00:00:39    192.168.1.1     GigabitEthernet0/1
        cisco_pattern = re.compile(
            r'^(\d+\.\d+\.\d+\.\d+)\s+'  # Neighbor ID
            r'(\d+)\s+'  # Priority
            r'(\S+)\s+'  # State (FULL/DR, etc)
            r'(\d+:\d+:\d+|\d+)\s+'  # Dead Time (00:00:39 or just seconds)
            r'(\d+\.\d+\.\d+\.\d+)\s+'  # Address
            r'(\S+)',  # Interface
            re.MULTILINE
        )

        # Juniper pattern
        # Address          Interface              State     ID               Pri  Dead
        # 192.168.1.1      ge-0/0/0.0             Full      10.0.0.1         128  37
        juniper_pattern = re.compile(
            r'^(\d+\.\d+\.\d+\.\d+)\s+'  # Address (IP_ADDRESS)
            r'(\S+)\s+'  # Interface
            r'(\S+)\s+'  # State
            r'(\d+\.\d+\.\d+\.\d+)\s+'  # ID (NEIGHBOR_ID)
            r'(\d+)\s+'  # Priority
            r'(\d+)',  # Dead
            re.MULTILINE
        )

        # Try Cisco/Arista pattern first
        for match in cisco_pattern.finditer(content):
            neighbors.append({
                'NEIGHBOR_ID': match.group(1),
                'PRIORITY': match.group(2),
                'STATE': match.group(3),
                'DEAD_TIME': match.group(4),
                'IP_ADDRESS': match.group(5),
                'INTERFACE': match.group(6),
            })

        # If no Cisco matches, try Juniper
        if not neighbors:
            for match in juniper_pattern.finditer(content):
                neighbors.append({
                    'IP_ADDRESS': match.group(1),
                    'INTERFACE': match.group(2),
                    'STATE': match.group(3),
                    'NEIGHBOR_ID': match.group(4),
                    'PRIORITY': match.group(5),
                    'DEAD_TIME': match.group(6),
                })

        return neighbors

    def parse_ospf_content(self, content: str, vendor: str) -> Tuple[List[OSPFNeighbor], str]:
        """
        Parse OSPF neighbor content and return normalized neighbor objects
        """
        neighbors = []
        error = ""

        # Try tfsm_fire first
        if self.tfsm_engine:
            parsed_data, error = self.parse_with_tfsm(content, vendor)
        else:
            parsed_data = []
            error = "TextFSM not available"

        # Fall back to regex if needed
        if not parsed_data:
            logger.debug(f"Using regex fallback for {vendor}")
            parsed_data = self.parse_with_regex(content, vendor)
            if parsed_data:
                error = ""  # Clear error if regex worked

        # Convert to OSPFNeighbor objects
        for row in parsed_data:
            try:
                neighbor = OSPFNeighbor(
                    neighbor_id=self.get_normalized_field(row, 'neighbor_id'),
                    neighbor_ip=self.get_normalized_field(row, 'neighbor_ip'),
                    interface=self.get_normalized_field(row, 'interface'),
                    state=self.get_normalized_field(row, 'state'),
                    priority=self.get_normalized_field(row, 'priority'),
                    dead_time=self.get_normalized_field(row, 'dead_time'),
                    vrf=self.get_normalized_field(row, 'vrf'),
                    instance=self.get_normalized_field(row, 'instance'),
                )

                # Only add if we have at least neighbor_id or neighbor_ip
                if neighbor.neighbor_id or neighbor.neighbor_ip:
                    neighbors.append(neighbor)

            except Exception as e:
                logger.debug(f"Error creating neighbor object: {e}")
                continue

        return neighbors, error

    def collect_ospf_data(self, site_filter: str = None,
                          device_filter: str = None,
                          exclude_empty: bool = True) -> List[DeviceOSPFData]:
        """
        Collect and parse OSPF data for all matching devices

        Args:
            site_filter: Filter by site code
            device_filter: Filter by device name
            exclude_empty: If True, exclude devices with no OSPF neighbors
        """
        captures = self.get_ospf_captures(site_filter, device_filter)
        logger.info(f"Found {len(captures)} OSPF captures to process")

        devices_data = []
        skipped_count = 0
        all_neighbor_ips = set()

        for capture in captures:
            vendor = self.normalize_vendor(capture.get('vendor_name', ''))

            device_data = DeviceOSPFData(
                device_id=capture['device_id'],
                device_name=capture['device_name'],
                site_code=capture.get('site_code', 'UNKNOWN'),
                vendor=capture.get('vendor_name', 'Unknown'),
                model=capture.get('model', ''),
                management_ip=capture.get('management_ip', ''),
                capture_timestamp=capture['captured_at'],
                raw_content=capture['content'][:500] + "..." if len(capture['content']) > 500 else capture['content']
            )

            neighbors, error = self.parse_ospf_content(capture['content'], vendor)
            device_data.neighbors = neighbors
            device_data.parse_success = len(neighbors) > 0 or not error
            device_data.parse_error = error

            # Skip devices with no neighbors if exclude_empty is True
            if exclude_empty and not neighbors:
                skipped_count += 1
                logger.debug(f"{capture['device_name']}: No OSPF neighbors, skipping")
                continue

            # Collect neighbor IPs for resolution
            for neighbor in neighbors:
                if neighbor.neighbor_id:
                    all_neighbor_ips.add(neighbor.neighbor_id)
                if neighbor.neighbor_ip:
                    all_neighbor_ips.add(neighbor.neighbor_ip)

            devices_data.append(device_data)

            if neighbors:
                logger.debug(f"{capture['device_name']}: {len(neighbors)} OSPF neighbors")
            elif error:
                logger.warning(f"{capture['device_name']}: {error}")

        if skipped_count:
            logger.info(f"Skipped {skipped_count} devices with no OSPF neighbors")

        # Resolve neighbor IPs to device names
        if all_neighbor_ips:
            ip_to_device = self.resolve_neighbor_ips(all_neighbor_ips)

            # Update neighbors with resolved names
            for device_data in devices_data:
                for neighbor in device_data.neighbors:
                    # Try neighbor_id first (router ID), then neighbor_ip
                    device_info = ip_to_device.get(neighbor.neighbor_id) or ip_to_device.get(neighbor.neighbor_ip)
                    if device_info:
                        neighbor.resolved_name = device_info['device_name']
                        neighbor.resolved_site = device_info.get('site_code', '')

        return devices_data

    def build_adjacency_matrix(self, devices_data: List[DeviceOSPFData]) -> Dict:
        """
        Build OSPF adjacency information for visualization
        """
        # Map device names to their router IDs (if we can determine them)
        device_neighbors = defaultdict(list)
        all_neighbor_ids = set()
        resolved_neighbors = {}  # neighbor_id -> resolved_name

        for device in devices_data:
            for neighbor in device.neighbors:
                device_neighbors[device.device_name].append({
                    'neighbor_id': neighbor.neighbor_id,
                    'neighbor_ip': neighbor.neighbor_ip,
                    'interface': neighbor.interface,
                    'state': neighbor.state,
                    'is_full': neighbor.is_full,
                    'resolved_name': neighbor.resolved_name,
                    'resolved_site': neighbor.resolved_site,
                })
                all_neighbor_ids.add(neighbor.neighbor_id)
                if neighbor.resolved_name:
                    resolved_neighbors[neighbor.neighbor_id] = neighbor.resolved_name

        return {
            'device_neighbors': dict(device_neighbors),
            'all_neighbor_ids': list(all_neighbor_ids),
            'resolved_neighbors': resolved_neighbors,
        }

    def generate_html_report(self, devices_data: List[DeviceOSPFData],
                             output_path: str,
                             title: str = "OSPF Peering Report") -> str:
        """
        Generate comprehensive HTML report
        """
        # Build adjacency data for visualization (needed for resolved_count)
        adjacency = self.build_adjacency_matrix(devices_data)

        # Calculate statistics
        total_devices = len(devices_data)
        devices_with_neighbors = sum(1 for d in devices_data if d.neighbors)
        total_neighbors = sum(len(d.neighbors) for d in devices_data)
        full_adjacencies = sum(
            sum(1 for n in d.neighbors if n.is_full)
            for d in devices_data
        )
        resolved_count = len(adjacency['resolved_neighbors'])

        # Group by site
        by_site = defaultdict(list)
        for device in devices_data:
            by_site[device.site_code].append(device)

        # Generate timestamp
        report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg-primary: #f5f7fa;
            --bg-secondary: #ffffff;
            --bg-card: #ffffff;
            --text-primary: #1a1a2e;
            --text-secondary: #5a6978;
            --accent: #e94560;
            --success: #10b981;
            --warning: #f59e0b;
            --info: #3b82f6;
            --border: #e2e8f0;
            --shadow: rgba(0, 0, 0, 0.08);
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .icon {{
            width: 24px;
            height: 24px;
            vertical-align: middle;
            stroke: currentColor;
            stroke-width: 2;
            stroke-linecap: round;
            stroke-linejoin: round;
            fill: none;
        }}

        .icon-sm {{
            width: 18px;
            height: 18px;
        }}

        .icon-lg {{
            width: 32px;
            height: 32px;
        }}

        header {{
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: var(--bg-secondary);
            border-radius: 10px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 4px var(--shadow);
        }}

        header h1 {{
            color: var(--accent);
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }}

        header h1 .icon {{
            stroke: var(--accent);
        }}

        header .timestamp {{
            color: var(--text-secondary);
            font-size: 0.9em;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .stat-card {{
            background: var(--bg-card);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            border: 1px solid var(--border);
            box-shadow: 0 2px 4px var(--shadow);
        }}

        .stat-card .value {{
            font-size: 2.5em;
            font-weight: bold;
            color: var(--accent);
        }}

        .stat-card .label {{
            color: var(--text-secondary);
            font-size: 0.9em;
            margin-top: 5px;
        }}

        .stat-card.success .value {{ color: var(--success); }}
        .stat-card.warning .value {{ color: var(--warning); }}
        .stat-card.info .value {{ color: var(--info); }}

        .site-section {{
            margin-bottom: 30px;
        }}

        .site-header {{
            background: var(--bg-secondary);
            padding: 15px 20px;
            border-radius: 10px 10px 0 0;
            border: 1px solid var(--border);
            border-bottom: none;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .site-header h2 {{
            color: var(--info);
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .site-header h2 .icon {{
            stroke: var(--info);
        }}

        .site-stats {{
            color: var(--text-secondary);
            font-size: 0.9em;
        }}

        .devices-table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--bg-card);
            border-radius: 0 0 10px 10px;
            overflow: hidden;
            border: 1px solid var(--border);
            box-shadow: 0 2px 4px var(--shadow);
        }}

        .devices-table th {{
            background: var(--bg-primary);
            padding: 12px 15px;
            text-align: left;
            font-weight: 600;
            color: var(--text-secondary);
            border-bottom: 2px solid var(--border);
        }}

        .devices-table td {{
            padding: 12px 15px;
            border-bottom: 1px solid var(--border);
        }}

        .devices-table tr:last-child td {{
            border-bottom: none;
        }}

        .devices-table tr:hover {{
            background: rgba(59, 130, 246, 0.05);
        }}

        .device-name {{
            font-weight: 600;
            color: var(--accent);
        }}

        .vendor {{
            color: var(--text-secondary);
            font-size: 0.85em;
        }}

        .neighbors-list {{
            margin: 0;
            padding: 0;
            list-style: none;
        }}

        .neighbor-item {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: var(--bg-primary);
            padding: 4px 10px;
            border-radius: 15px;
            margin: 2px;
            font-size: 0.85em;
            border: 1px solid var(--border);
        }}

        .state-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.75em;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .state-full {{ background: var(--success); color: #fff; }}
        .state-down {{ background: var(--accent); color: #fff; }}
        .state-2way {{ background: var(--warning); color: #000; }}
        .state-init {{ background: var(--info); color: #fff; }}
        .state-transition {{ background: #6c757d; color: #fff; }}
        .state-unknown {{ background: #9ca3af; color: #fff; }}

        .no-neighbors {{
            color: var(--text-secondary);
            font-style: italic;
        }}

        .vrf {{
            color: var(--info);
            font-style: italic;
            margin-left: 4px;
        }}

        .neighbor-name {{
            font-weight: 500;
        }}

        .parse-error {{
            color: var(--warning);
            font-size: 0.85em;
        }}

        .summary-section {{
            background: var(--bg-card);
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 4px var(--shadow);
        }}

        .summary-section h3 {{
            color: var(--info);
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .summary-section h3 .icon {{
            stroke: var(--info);
        }}

        .neighbor-id-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .neighbor-id-tag {{
            background: var(--bg-primary);
            padding: 5px 12px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 0.9em;
            border: 1px solid var(--border);
        }}

        .collapsible {{
            cursor: pointer;
            user-select: none;
        }}

        .collapsible::before {{
            content: '▶ ';
            display: inline-block;
            transition: transform 0.2s;
        }}

        .collapsible.active::before {{
            transform: rotate(90deg);
        }}

        .collapse-content {{
            display: none;
            padding: 10px;
            margin-top: 10px;
            background: var(--bg-primary);
            border-radius: 5px;
        }}

        .collapse-content.show {{
            display: block;
        }}

        .raw-output {{
            font-family: monospace;
            font-size: 0.8em;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 200px;
            overflow-y: auto;
            color: var(--text-secondary);
        }}

        footer {{
            text-align: center;
            margin-top: 30px;
            padding: 20px;
            color: var(--text-secondary);
            font-size: 0.85em;
        }}

        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}

            .devices-table {{
                font-size: 0.85em;
            }}

            .devices-table th,
            .devices-table td {{
                padding: 8px 10px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>
                <svg class="icon icon-lg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                {title}
            </h1>
            <div class="timestamp">Generated: {report_time}</div>
        </header>

        <div class="stats-grid">
            <div class="stat-card info">
                <div class="value">{total_devices}</div>
                <div class="label">Total Devices</div>
            </div>
            <div class="stat-card success">
                <div class="value">{devices_with_neighbors}</div>
                <div class="label">Devices with Neighbors</div>
            </div>
            <div class="stat-card">
                <div class="value">{total_neighbors}</div>
                <div class="label">Total Adjacencies</div>
            </div>
            <div class="stat-card success">
                <div class="value">{full_adjacencies}</div>
                <div class="label">FULL Adjacencies</div>
            </div>
            <div class="stat-card {"success" if resolved_count == len(adjacency['all_neighbor_ids']) else "info"}">
                <div class="value">{resolved_count}/{len(adjacency['all_neighbor_ids'])}</div>
                <div class="label">Names Resolved</div>
            </div>
            <div class="stat-card {"success" if full_adjacencies == total_neighbors else "warning"}">
                <div class="value">{full_adjacencies * 100 // total_neighbors if total_neighbors > 0 else 0}%</div>
                <div class="label">Health Rate</div>
            </div>
        </div>

        <div class="summary-section">
            <h3>
                <svg class="icon" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                Unique Neighbor Router IDs ({len(adjacency['all_neighbor_ids'])})
            </h3>
            <div class="neighbor-id-list">
                {''.join(f'<span class="neighbor-id-tag" title="{nid}">{adjacency["resolved_neighbors"].get(nid, nid)}</span>' for nid in sorted(adjacency['all_neighbor_ids']))}
            </div>
        </div>
'''

        # Generate site sections
        for site_code in sorted(by_site.keys()):
            site_devices = by_site[site_code]
            site_neighbors = sum(len(d.neighbors) for d in site_devices)
            site_full = sum(sum(1 for n in d.neighbors if n.is_full) for d in site_devices)

            html += f'''
        <div class="site-section">
            <div class="site-header">
                <h2>
                    <svg class="icon" viewBox="0 0 24 24"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
                    {site_code}
                </h2>
                <span class="site-stats">{len(site_devices)} devices | {site_neighbors} adjacencies | {site_full} FULL</span>
            </div>
            <table class="devices-table">
                <thead>
                    <tr>
                        <th>Device</th>
                        <th>Management IP</th>
                        <th>OSPF Neighbors</th>
                        <th>Capture Time</th>
                    </tr>
                </thead>
                <tbody>
'''

            for device in sorted(site_devices, key=lambda d: d.device_name):
                neighbor_html = ""

                if device.neighbors:
                    neighbor_items = []
                    for n in device.neighbors:
                        state_class = n.state_class
                        vrf_info = f' <small class="vrf">VRF:{n.vrf}</small>' if n.vrf else ''
                        # Show resolved name with IP as tooltip, or just the ID if not resolved
                        display = n.display_name
                        tooltip = f'{n.neighbor_id}' if n.resolved_name else ''
                        title_attr = f'title="{tooltip}"' if tooltip else ''
                        neighbor_items.append(
                            f'<span class="neighbor-item" {title_attr}>'
                            f'<span class="state-badge {state_class}">{n.state_display}</span>'
                            f'<span class="neighbor-name">{display}</span>'
                            f'<small>via {n.interface}</small>'
                            f'{vrf_info}'
                            f'</span>'
                        )
                    neighbor_html = ''.join(neighbor_items)
                elif device.parse_error:
                    neighbor_html = f'<span class="parse-error">⚠️ {device.parse_error}</span>'
                else:
                    neighbor_html = '<span class="no-neighbors">No neighbors detected</span>'

                html += f'''
                    <tr>
                        <td>
                            <div class="device-name">{device.device_name}</div>
                            <div class="vendor">{device.vendor} {device.model}</div>
                        </td>
                        <td>{device.management_ip or '-'}</td>
                        <td>{neighbor_html}</td>
                        <td>{device.capture_timestamp[:19] if device.capture_timestamp else '-'}</td>
                    </tr>
'''

            html += '''
                </tbody>
            </table>
        </div>
'''

        html += f'''
        <footer>
            <p>VelocityCMDB OSPF Peering Report | Processed {total_devices} devices across {len(by_site)} sites</p>
            <p>TextFSM Engine: {"Active" if self.tfsm_engine else "Fallback Regex"}</p>
        </footer>
    </div>

    <script>
        // Collapsible functionality
        document.querySelectorAll('.collapsible').forEach(item => {{
            item.addEventListener('click', function() {{
                this.classList.toggle('active');
                const content = this.nextElementSibling;
                content.classList.toggle('show');
            }});
        }});
    </script>
</body>
</html>
'''

        # Write to file
        output_path = Path(output_path)
        output_path.write_text(html)
        logger.info(f"Report written to: {output_path}")

        return str(output_path)


@click.command()
@click.option('--db-path', envvar='VELOCITYCMDB_DB_PATH',
              default='~/.velocitycmdb/data/assets.db',
              help='Path to SQLite database')
@click.option('--tfsm-db', envvar='TFSM_TEMPLATES_DB',
              default='~/.velocitycmdb/data/tfsm_templates.db',
              help='Path to TextFSM templates database')
@click.option('--output', '-o', default='ospf_peering_report.html',
              help='Output HTML file path')
@click.option('--site', '-s', default=None,
              help='Filter by site code')
@click.option('--device', '-d', default=None,
              help='Filter by device name')
@click.option('--title', '-t', default='OSPF Peering Report',
              help='Report title')
@click.option('--include-empty', is_flag=True,
              help='Include devices with no OSPF neighbors')
@click.option('--verbose', '-v', is_flag=True,
              help='Enable verbose logging')
def main(db_path, tfsm_db, output, site, device, title, include_empty, verbose):
    """Generate OSPF peering HTML report from capture database"""

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    db_path = Path(db_path).expanduser().resolve()

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return

    logger.info(f"Using database: {db_path}")

    # Resolve tfsm_db path
    tfsm_db_path = Path(tfsm_db).expanduser().resolve() if tfsm_db else None
    if tfsm_db_path and tfsm_db_path.exists():
        logger.info(f"Using TextFSM templates: {tfsm_db_path}")
    else:
        logger.info("TextFSM templates not found, using regex fallback")
        tfsm_db_path = None

    generator = OSPFReportGenerator(str(db_path), tfsm_db_path=str(tfsm_db_path) if tfsm_db_path else None)

    # Collect OSPF data
    devices_data = generator.collect_ospf_data(
        site_filter=site,
        device_filter=device,
        exclude_empty=not include_empty
    )

    if not devices_data:
        logger.warning("No OSPF data found matching filters")
        return

    # Generate report
    output_file = generator.generate_html_report(
        devices_data,
        output,
        title=title
    )

    # Summary
    total_neighbors = sum(len(d.neighbors) for d in devices_data)
    full_count = sum(sum(1 for n in d.neighbors if n.is_full) for d in devices_data)
    resolved_count = sum(1 for d in devices_data for n in d.neighbors if n.resolved_name)
    unique_neighbor_ids = set(n.neighbor_id for d in devices_data for n in d.neighbors if n.neighbor_id)

    print(f"\n{'=' * 60}")
    print("OSPF PEERING REPORT GENERATED")
    print(f"{'=' * 60}")
    print(f"Devices processed:    {len(devices_data)}")
    print(f"Total adjacencies:    {total_neighbors}")
    print(f"FULL adjacencies:     {full_count}")
    print(f"Unique neighbors:     {len(unique_neighbor_ids)}")
    print(
        f"Names resolved:       {resolved_count}/{total_neighbors} ({resolved_count * 100 // total_neighbors if total_neighbors else 0}%)")
    print(f"Output file:          {output_file}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()