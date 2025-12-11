#!/usr/bin/env python3
"""
IP Locator Service
Find where an IP lives: ARP entry, access port, and routing information
"""

import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ARPEntry:
    """ARP table entry"""
    ip_address: str
    mac_address: str
    interface: str
    device_name: str
    device_id: Optional[int] = None
    vlan: Optional[str] = None
    age: Optional[str] = None


@dataclass
class MACEntry:
    """MAC table entry"""
    mac_address: str
    vlan: str
    port: str
    device_name: str
    device_id: Optional[int] = None
    mac_type: str = "dynamic"  # dynamic, static


@dataclass
class RouteEntry:
    """Routing table entry"""
    prefix: str
    next_hop: str
    protocol: str  # C, S, O, B, etc.
    interface: Optional[str]
    device_name: str
    device_id: Optional[int] = None
    metric: Optional[str] = None
    ad: Optional[str] = None


@dataclass
class IPLocation:
    """Complete location result for an IP"""
    ip_address: str
    arp_entries: List[ARPEntry]
    mac_entries: List[MACEntry]
    route_entries: List[RouteEntry]
    access_port: Optional[Dict] = None  # Best guess at physical location
    summary: str = ""


class IPLocatorService:
    """Service to locate IPs across the network"""

    def __init__(self, assets_db_path: str, arp_db_path: str = None, data_dir: Path = None):
        self.assets_db_path = assets_db_path
        self.arp_db_path = arp_db_path

        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(assets_db_path).parent

        if not self.arp_db_path:
            self.arp_db_path = str(self.data_dir / 'arp_cat.db')

    def get_assets_connection(self) -> sqlite3.Connection:
        """Get connection to assets database"""
        conn = sqlite3.connect(self.assets_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_arp_connection(self) -> sqlite3.Connection:
        """Get connection to ARP database"""
        conn = sqlite3.connect(self.arp_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def normalize_mac(self, mac: str) -> str:
        """Normalize MAC address to lowercase with colons"""
        if not mac:
            return ""
        # Remove all separators and convert to lowercase
        clean = re.sub(r'[.:\-]', '', mac.lower())
        # Format as xx:xx:xx:xx:xx:xx
        if len(clean) == 12:
            return ':'.join(clean[i:i + 2] for i in range(0, 12, 2))
        return mac.lower()

    def find_arp_entries(self, ip_address: str) -> List[ARPEntry]:
        """Search ARP tables for an IP address"""
        entries = []

        # First try the dedicated arp_cat.db if it exists
        if Path(self.arp_db_path).exists():
            try:
                with self.get_arp_connection() as conn:
                    cursor = conn.cursor()
                    # Check what tables exist
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]

                    if 'arp_entries' in tables:
                        cursor.execute("""
                            SELECT ip_address, mac_address, interface, device_name, vlan
                            FROM arp_entries 
                            WHERE ip_address = ?
                        """, (ip_address,))

                        for row in cursor.fetchall():
                            entries.append(ARPEntry(
                                ip_address=row['ip_address'],
                                mac_address=self.normalize_mac(row['mac_address']),
                                interface=row['interface'] or '',
                                device_name=row['device_name'],
                                vlan=row['vlan'] if 'vlan' in row.keys() else None
                            ))
            except Exception as e:
                logger.warning(f"Error searching arp_cat.db: {e}")

        # Also search capture snapshots for ARP data
        try:
            with self.get_assets_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cs.content, cs.device_id, d.name as device_name
                    FROM capture_snapshots cs
                    JOIN devices d ON cs.device_id = d.id
                    WHERE cs.capture_type = 'arp'
                    AND cs.id IN (
                        SELECT MAX(id) FROM capture_snapshots 
                        WHERE capture_type = 'arp' 
                        GROUP BY device_id
                    )
                """)

                for row in cursor.fetchall():
                    # Parse ARP output for the IP
                    content = row['content']
                    for line in content.splitlines():
                        if ip_address in line:
                            parsed = self._parse_arp_line(line, row['device_name'], row['device_id'])
                            if parsed and parsed.ip_address == ip_address:
                                # Avoid duplicates
                                if not any(e.device_name == parsed.device_name and
                                           e.mac_address == parsed.mac_address for e in entries):
                                    entries.append(parsed)
        except Exception as e:
            logger.warning(f"Error searching ARP captures: {e}")

        return entries

    def _parse_arp_line(self, line: str, device_name: str, device_id: int) -> Optional[ARPEntry]:
        """Parse a single ARP table line"""
        # Cisco IOS format: Internet  10.1.1.1    5   0011.2233.4455  ARPA   Vlan100
        # Arista format: 10.1.1.1    0:11:22:33:44:55  Vlan100

        # Try Cisco format
        cisco_pattern = r'Internet\s+(\d+\.\d+\.\d+\.\d+)\s+\S+\s+([0-9a-fA-F.]+)\s+\S+\s+(\S+)'
        match = re.search(cisco_pattern, line)
        if match:
            return ARPEntry(
                ip_address=match.group(1),
                mac_address=self.normalize_mac(match.group(2)),
                interface=match.group(3),
                device_name=device_name,
                device_id=device_id
            )

        # Try Arista/simple format
        simple_pattern = r'(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:.\-]+)\s+(\S+)'
        match = re.search(simple_pattern, line)
        if match:
            return ARPEntry(
                ip_address=match.group(1),
                mac_address=self.normalize_mac(match.group(2)),
                interface=match.group(3),
                device_name=device_name,
                device_id=device_id
            )

        return None

    def find_mac_entries(self, mac_address: str) -> List[MACEntry]:
        """Search MAC tables for a MAC address"""
        entries = []
        normalized_mac = self.normalize_mac(mac_address)

        # Also create dot notation for Cisco matching
        clean = re.sub(r'[.:\-]', '', mac_address.lower())
        cisco_mac = '.'.join([clean[i:i + 4] for i in range(0, 12, 4)]) if len(clean) == 12 else ""

        try:
            with self.get_assets_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cs.content, cs.device_id, d.name as device_name
                    FROM capture_snapshots cs
                    JOIN devices d ON cs.device_id = d.id
                    WHERE cs.capture_type = 'mac'
                    AND cs.id IN (
                        SELECT MAX(id) FROM capture_snapshots 
                        WHERE capture_type = 'mac' 
                        GROUP BY device_id
                    )
                """)

                for row in cursor.fetchall():
                    content = row['content']
                    for line in content.splitlines():
                        # Check for MAC in various formats
                        line_lower = line.lower()
                        if normalized_mac in self.normalize_mac(line) or \
                                (cisco_mac and cisco_mac in line_lower):
                            parsed = self._parse_mac_line(line, row['device_name'], row['device_id'])
                            if parsed:
                                entries.append(parsed)
        except Exception as e:
            logger.warning(f"Error searching MAC captures: {e}")

        return entries

    def _parse_mac_line(self, line: str, device_name: str, device_id: int) -> Optional[MACEntry]:
        """Parse a single MAC table line"""
        # Cisco format: 100    0011.2233.4455    DYNAMIC     Gi1/0/24
        # Arista format: 100    00:11:22:33:44:55    DYNAMIC    Et1

        # Generic pattern - VLAN, MAC, type, port
        pattern = r'(\d+)\s+([0-9a-fA-F.:]+)\s+(\w+)\s+(\S+)'
        match = re.search(pattern, line)
        if match:
            port = match.group(4)
            # Filter out CPU/internal ports
            if any(x in port.lower() for x in ['cpu', 'switch', 'router', 'sup']):
                return None

            return MACEntry(
                mac_address=self.normalize_mac(match.group(2)),
                vlan=match.group(1),
                mac_type=match.group(3).lower(),
                port=port,
                device_name=device_name,
                device_id=device_id
            )

        return None

    def find_route_entries(self, ip_address: str) -> List[RouteEntry]:
        """Search routing tables for routes covering an IP"""
        entries = []

        try:
            with self.get_assets_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cs.content, cs.device_id, d.name as device_name
                    FROM capture_snapshots cs
                    JOIN devices d ON cs.device_id = d.id
                    WHERE cs.capture_type = 'routes'
                    AND cs.id IN (
                        SELECT MAX(id) FROM capture_snapshots 
                        WHERE capture_type = 'routes' 
                        GROUP BY device_id
                    )
                """)

                for row in cursor.fetchall():
                    content = row['content']
                    device_routes = self._parse_routes(content, row['device_name'], row['device_id'])

                    # Find matching routes for this IP
                    matching = self._find_matching_routes(ip_address, device_routes)
                    entries.extend(matching)

        except Exception as e:
            logger.warning(f"Error searching route captures: {e}")

        # Sort by prefix length (most specific first)
        entries.sort(key=lambda r: self._prefix_length(r.prefix), reverse=True)

        return entries

    def _parse_routes(self, content: str, device_name: str, device_id: int) -> List[RouteEntry]:
        """Parse routing table output - handles Cisco IOS, Arista EOS, and Juniper formats"""
        routes = []
        lines = content.splitlines()

        # State for multi-line Arista format
        current_prefix = None
        current_protocol = None
        current_ad = None
        current_metric = None

        for i, line in enumerate(lines):
            # Skip header lines and empty
            if not line.strip() or line.startswith('Codes:') or 'Routing Table' in line:
                continue

            # === ARISTA EOS FORMAT (multi-line) ===
            # 819   O        10.255.255.1/32 [110/140]
            # 820            via 100.64.2.22, Ethernet49/1
            # 821            via 100.64.2.18, Ethernet50/1
            # Also: O E2, B I, etc.

            # Check for Arista route line (has prefix with [AD/metric])
            arista_route = re.search(
                r'^\s*\d*\s*([OCSLBI](?:\s+[EI12])?)\s+(\d+\.\d+\.\d+\.\d+/\d+)\s+\[(\d+)/(\d+)\]',
                line
            )
            if arista_route:
                # Save current route info for following via lines
                proto_code = arista_route.group(1).strip()
                current_prefix = arista_route.group(2)
                current_ad = arista_route.group(3)
                current_metric = arista_route.group(4)

                # Map protocol codes
                if proto_code.startswith('O'):
                    current_protocol = 'OSPF'
                elif proto_code.startswith('B'):
                    current_protocol = 'BGP'
                elif proto_code.startswith('S'):
                    current_protocol = 'static'
                elif proto_code.startswith('C'):
                    current_protocol = 'connected'
                elif proto_code.startswith('L'):
                    current_protocol = 'local'
                elif proto_code.startswith('I'):
                    current_protocol = 'ISIS'
                else:
                    current_protocol = proto_code

                # Check if via is on same line
                via_same_line = re.search(r'via\s+(\d+\.\d+\.\d+\.\d+),?\s*(\S+)?', line)
                if via_same_line:
                    routes.append(RouteEntry(
                        prefix=current_prefix,
                        next_hop=via_same_line.group(1),
                        protocol=current_protocol,
                        interface=via_same_line.group(2),
                        device_name=device_name,
                        device_id=device_id,
                        ad=current_ad,
                        metric=current_metric
                    ))
                continue

            # Check for Arista "via" continuation line
            arista_via = re.search(r'^\s*\d*\s+via\s+(\d+\.\d+\.\d+\.\d+),?\s*(\S+)?', line)
            if arista_via and current_prefix:
                routes.append(RouteEntry(
                    prefix=current_prefix,
                    next_hop=arista_via.group(1),
                    protocol=current_protocol,
                    interface=arista_via.group(2),
                    device_name=device_name,
                    device_id=device_id,
                    ad=current_ad,
                    metric=current_metric
                ))
                continue

            # Arista directly connected
            arista_connected = re.search(
                r'^\s*\d*\s*([CL])\s+(\d+\.\d+\.\d+\.\d+/\d+)\s+is directly connected,?\s*(\S+)?',
                line
            )
            if arista_connected:
                current_prefix = None  # Reset state
                routes.append(RouteEntry(
                    prefix=arista_connected.group(2),
                    next_hop='directly connected',
                    protocol='connected' if arista_connected.group(1) == 'C' else 'local',
                    interface=arista_connected.group(3),
                    device_name=device_name,
                    device_id=device_id
                ))
                continue

            # === JUNIPER FORMAT ===
            # 10.255.255.1/32 *[OSPF/10] 49w5d 06:22:29, metric 1
            # 10.255.255.1/32 *[Direct/0] 129w1d 11:19:23
            # === JUNIPER FORMAT ===
            # 10.255.255.1/32 *[OSPF/10] 49w5d 06:22:29, metric 1
            # 10.255.255.1/32 *[Direct/0] 129w1d 11:19:23
            # 10.255.255.200/32  *[Access-internal/12] 6d 07:04:00
            #                     > to 10.255.0.2 via irb.127
            juniper_match = re.search(
                r'(\d+\.\d+\.\d+\.\d+/\d+)\s+\*?\[([\w-]+)/(\d+)\]',  # [\w-]+ to match hyphens
                line
            )
            if juniper_match:
                current_prefix = juniper_match.group(1)  # Save for continuation line
                protocol_raw = juniper_match.group(2)
                metric = juniper_match.group(3)

                # Check for via on same line
                via_match = re.search(r'(?:to|via)\s+(\d+\.\d+\.\d+\.\d+)', line)

                # Only "Direct" and "Local" are actually directly connected
                if protocol_raw in ('Direct', 'Local'):
                    next_hop = 'directly connected'
                elif via_match:
                    next_hop = via_match.group(1)
                else:
                    next_hop = None  # Will be filled by continuation line or marked as learned

                # Check for interface
                intf_match = re.search(r'via\s+(\S+)', line)
                interface = intf_match.group(1) if intf_match else None

                # Map Juniper protocol names
                protocol_map = {
                    'Direct': 'connected',
                    'Local': 'local',
                    'Static': 'static',
                    'OSPF': 'OSPF',
                    'BGP': 'BGP',
                    'IS-IS': 'ISIS',
                    'Access-internal': 'Access-internal'
                }
                current_protocol = protocol_map.get(protocol_raw, protocol_raw)
                current_metric = metric

                # If we have next_hop, add route now; otherwise wait for continuation
                if next_hop:
                    routes.append(RouteEntry(
                        prefix=current_prefix,
                        next_hop=next_hop,
                        protocol=current_protocol,
                        interface=interface,
                        device_name=device_name,
                        device_id=device_id,
                        metric=metric
                    ))
                    current_prefix = None  # Reset
                continue

            # Juniper continuation line: > to 10.255.0.2 via irb.127
            juniper_continuation = re.search(r'^\s*>\s*to\s+(\d+\.\d+\.\d+\.\d+)(?:\s+via\s+(\S+))?', line)
            if juniper_continuation and current_prefix:
                routes.append(RouteEntry(
                    prefix=current_prefix,
                    next_hop=juniper_continuation.group(1),
                    protocol=current_protocol,
                    interface=juniper_continuation.group(2),
                    device_name=device_name,
                    device_id=device_id,
                    metric=current_metric
                ))
                current_prefix = None  # Reset after consuming
                continue
            # === CISCO IOS FORMAT ===
            # Reset Arista state for Cisco parsing
            current_prefix = None

            # Connected route
            if re.match(r'^[CL]\s+', line) or 'directly connected' in line.lower():
                match = re.search(r'([CL])\s+(\d+\.\d+\.\d+\.\d+(?:/\d+)?)\s+is directly connected,?\s*(\S+)?', line)
                if match:
                    routes.append(RouteEntry(
                        prefix=match.group(2),
                        next_hop='directly connected',
                        protocol='connected' if match.group(1) == 'C' else 'local',
                        interface=match.group(3),
                        device_name=device_name,
                        device_id=device_id
                    ))
                continue

            # Static route
            if re.match(r'^S[\*]?\s+', line):
                match = re.search(
                    r'S[\*]?\s+(\d+\.\d+\.\d+\.\d+(?:/\d+)?)\s+(?:\[[\d/]+\]\s+)?via\s+(\d+\.\d+\.\d+\.\d+)', line)
                if match:
                    routes.append(RouteEntry(
                        prefix=match.group(1),
                        next_hop=match.group(2),
                        protocol='static',
                        interface=None,
                        device_name=device_name,
                        device_id=device_id
                    ))
                continue

            # OSPF route
            if re.match(r'^O\s+', line):
                match = re.search(r'O\s+(\d+\.\d+\.\d+\.\d+(?:/\d+)?)\s+\[(\d+)/(\d+)\]\s+via\s+(\d+\.\d+\.\d+\.\d+)',
                                  line)
                if match:
                    routes.append(RouteEntry(
                        prefix=match.group(1),
                        next_hop=match.group(4),
                        protocol='OSPF',
                        interface=None,
                        device_name=device_name,
                        device_id=device_id,
                        ad=match.group(2),
                        metric=match.group(3)
                    ))
                continue

            # BGP route
            if re.match(r'^B\s+', line):
                match = re.search(r'B\s+(\d+\.\d+\.\d+\.\d+(?:/\d+)?)\s+\[[\d/]+\]\s+via\s+(\d+\.\d+\.\d+\.\d+)', line)
                if match:
                    routes.append(RouteEntry(
                        prefix=match.group(1),
                        next_hop=match.group(2),
                        protocol='BGP',
                        interface=None,
                        device_name=device_name,
                        device_id=device_id
                    ))

        return routes
    def _prefix_length(self, prefix: str) -> int:
        """Extract prefix length from CIDR notation"""
        if '/' in prefix:
            try:
                return int(prefix.split('/')[1])
            except ValueError:
                return 0
        return 32  # Host route assumed

    def _ip_to_int(self, ip: str) -> int:
        """Convert IP address to integer"""
        parts = ip.split('.')
        return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])

    def _ip_in_prefix(self, ip: str, prefix: str) -> bool:
        """Check if IP is within a prefix"""
        try:
            if '/' in prefix:
                network, length = prefix.split('/')
                length = int(length)
            else:
                network = prefix
                length = 32

            ip_int = self._ip_to_int(ip)
            net_int = self._ip_to_int(network)
            mask = (0xFFFFFFFF << (32 - length)) & 0xFFFFFFFF

            return (ip_int & mask) == (net_int & mask)
        except (ValueError, IndexError):
            return False

    def _find_matching_routes(self, ip: str, routes: List[RouteEntry]) -> List[RouteEntry]:
        """Find all routes that match an IP, excluding defaults and overly broad prefixes"""
        matching = []
        for route in routes:
            # Skip default routes
            if route.prefix.startswith('0.0.0.0'):
                continue

            # Skip overly broad prefixes (/16 and larger)
            prefix_len = self._prefix_length(route.prefix)
            if prefix_len <= 16:
                continue

            if self._ip_in_prefix(ip, route.prefix):
                matching.append(route)
        return matching

    def locate_ip(self, ip_address: str) -> IPLocation:
        """Main entry point - find everything about an IP"""
        # Validate IP format
        if not re.match(r'^\d+\.\d+\.\d+\.\d+$', ip_address):
            return IPLocation(
                ip_address=ip_address,
                arp_entries=[],
                mac_entries=[],
                route_entries=[],
                summary="Invalid IP address format"
            )

        # Find ARP entries
        arp_entries = self.find_arp_entries(ip_address)

        # Find MAC entries for any MACs found in ARP
        mac_entries = []
        for arp in arp_entries:
            if arp.mac_address:
                mac_entries.extend(self.find_mac_entries(arp.mac_address))

        # Deduplicate MAC entries
        seen_macs = set()
        unique_macs = []
        for mac in mac_entries:
            key = (mac.mac_address, mac.device_name, mac.port)
            if key not in seen_macs:
                seen_macs.add(key)
                unique_macs.append(mac)
        mac_entries = unique_macs

        # Find route entries
        route_entries = self.find_route_entries(ip_address)
        seen_routes = set()
        unique_routes = []
        for route in route_entries:
            key = (route.device_name, route.prefix, route.next_hop)
            if key not in seen_routes:
                seen_routes.add(key)
                unique_routes.append(route)
        route_entries = unique_routes
        # Determine access port (best guess)
        access_port = None
        if mac_entries:
            # Prefer dynamic entries on edge ports (Et, Gi, Fa patterns)
            for mac in mac_entries:
                if mac.mac_type == 'dynamic':
                    port_lower = mac.port.lower()
                    if any(p in port_lower for p in ['et', 'gi', 'fa', 'xe', 'ge']):
                        access_port = {
                            'device': mac.device_name,
                            'port': mac.port,
                            'vlan': mac.vlan,
                            'mac': mac.mac_address
                        }
                        break

            # Fallback to first MAC entry
            if not access_port and mac_entries:
                mac = mac_entries[0]
                access_port = {
                    'device': mac.device_name,
                    'port': mac.port,
                    'vlan': mac.vlan,
                    'mac': mac.mac_address
                }

        # Build summary
        summary_parts = []
        if access_port:
            summary_parts.append(
                f"Located on {access_port['device']} port {access_port['port']} (VLAN {access_port['vlan']})")
        elif arp_entries:
            summary_parts.append(f"Found in ARP on {arp_entries[0].device_name} ({arp_entries[0].interface})")
        else:
            summary_parts.append("Not found in ARP tables")

        if route_entries:
            best_route = route_entries[0]  # Already sorted by specificity
            summary_parts.append(
                f"Best route: {best_route.prefix} via {best_route.next_hop} ({best_route.protocol}) on {best_route.device_name}")

        return IPLocation(
            ip_address=ip_address,
            arp_entries=arp_entries,
            mac_entries=mac_entries,
            route_entries=route_entries,
            access_port=access_port,
            summary=" | ".join(summary_parts)
        )


# CLI for testing
if __name__ == '__main__':
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python ip_locator.py <ip_address> [data_dir]")
        sys.exit(1)

    ip = sys.argv[1]
    data_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('~/.velocitycmdb/data').expanduser()

    service = IPLocatorService(
        assets_db_path=str(data_dir / 'assets.db'),
        arp_db_path=str(data_dir / 'arp_cat.db'),
        data_dir=data_dir
    )

    result = service.locate_ip(ip)

    print(f"\n{'=' * 60}")
    print(f"IP Location: {result.ip_address}")
    print(f"{'=' * 60}")
    print(f"\nSummary: {result.summary}")

    if result.access_port:
        print(f"\n--- Access Port ---")
        print(f"  Device: {result.access_port['device']}")
        print(f"  Port:   {result.access_port['port']}")
        print(f"  VLAN:   {result.access_port['vlan']}")
        print(f"  MAC:    {result.access_port['mac']}")

    if result.arp_entries:
        print(f"\n--- ARP Entries ({len(result.arp_entries)}) ---")
        for arp in result.arp_entries:
            print(f"  {arp.device_name}: {arp.mac_address} on {arp.interface}")

    if result.mac_entries:
        print(f"\n--- MAC Table Entries ({len(result.mac_entries)}) ---")
        for mac in result.mac_entries:
            print(f"  {mac.device_name}: VLAN {mac.vlan} port {mac.port} ({mac.mac_type})")

    if result.route_entries:
        print(f"\n--- Routing Entries ({len(result.route_entries)}) ---")
        for route in result.route_entries:
            print(f"  {route.device_name}: {route.prefix} -> {route.next_hop} ({route.protocol})")