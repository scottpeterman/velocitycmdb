#!/usr/bin/env python3
"""
OSPF to Secure Cartography Topology Schema v2
Improved correlation engine with multi-pass router-id resolution.

The key insight: if we have OSPF data from both ends of a link,
we can correlate them to build complete connection info.

Usage:
    python ospf_to_topology_v2.py -i ./capture/ospf_analytics -o topology.json
    python ospf_to_topology_v2.py -i ./capture/ospf_analytics -o topology.json --overview-dir ./capture/ospf_overview
"""

import os
import re
import json
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional

try:
    from ttp import ttp

    HAS_TTP = True
except ImportError:
    HAS_TTP = False


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Link:
    """Represents one side of an OSPF adjacency."""
    local_host: str
    local_interface: str
    local_ip: str  # IP on our side of the link
    remote_router_id: str  # Neighbor's router-id
    remote_ip: str  # Neighbor's IP on the link (neighbor_address)
    area: str
    state: str


@dataclass
class Connection:
    """A fully resolved bidirectional connection."""
    device_a: str
    interface_a: str
    device_b: str
    interface_b: str
    area: str
    state: str
    bidirectional: bool = False

    def as_tuple(self) -> Tuple[str, str]:
        """Return as [local_int, remote_int] from device_a's perspective."""
        return (self.interface_a, self.interface_b)


# ─────────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────────

JUNIPER_NEIGHBOR_TEMPLATE = """
<group name="neighbors*">
{{ neighbor_address | IP }} {{ interface }} {{ state }} {{ router_id | IP }} {{ priority | to_int }} {{ dead_time | to_int }}
  Area {{ area | IP }}, opt {{ options }}, DR {{ dr | IP }}, BDR {{ bdr | IP }}
  Up {{ uptime | ORPHRASE }}, adjacent {{ adjacent_time | ORPHRASE }}
  Topology {{ topology_name }} (ID {{ topology_id | to_int }}) -> {{ topology_state }}
</group>
"""

ARISTA_NEIGHBOR_TEMPLATE = """
<group name="neighbors*">
Neighbor {{ router_id | IP }}, instance {{ instance | to_int }}, VRF {{ vrf }}, interface address {{ neighbor_address | IP }}
  In area {{ area | IP }} interface {{ interface }}
  Neighbor priority is {{ priority | to_int }}, State is {{ state }}, {{ state_changes | to_int }} state changes
  Adjacency was established {{ adjacency_time | ORPHRASE }} ago
  Current state was established {{ current_state_time | ORPHRASE }} ago
  DR IP Address {{ dr | IP }} BDR IP Address {{ bdr | IP }}
  Options is {{ options }}
  Dead timer is due in {{ dead_timer }}
</group>
"""

# OSPFv3 templates - completely different format from v2

# Juniper: show ospf3 neighbor extensive
JUNIPER_OSPFV3_TEMPLATE = """
<group name="neighbors*">
{{ router_id | IP }} {{ interface }} {{ state }} {{ priority | to_int }} {{ dead_time | to_int }}
  Neighbor-address {{ neighbor_address }}
  Area {{ area | IP }}, opt {{ options }}, OSPF3-Intf-Index {{ intf_index | to_int }}
  DR-ID {{ dr | IP }}, BDR-ID {{ bdr | IP }}
  Up {{ uptime | ORPHRASE }}, adjacent {{ adjacent_time | ORPHRASE }}
</group>
"""

# Arista: show ipv6 ospf neighbor
ARISTA_OSPFV3_TEMPLATE = """
<group name="neighbors*">
Neighbor {{ router_id | IP }} VRF {{ vrf }} priority is {{ priority | to_int }}, state is {{ state }}
  In area {{ area | IP }} interface {{ interface }}
  Adjacency was established {{ adjacency_time | ORPHRASE }} ago
  Current state was established {{ current_state_time | ORPHRASE }} ago
  DR is {{ dr }} BDR is {{ bdr }}
  Options is {{ options | ORPHRASE }}
  Dead timer is due in {{ dead_timer }}
  Graceful-restart-helper mode is {{ gr_helper_mode }}
  Graceful-restart attempts: {{ gr_attempts | to_int }}
</group>
"""

JUNIPER_OVERVIEW_TEMPLATE = """
<group name="ospf">
Instance: {{ instance }}
  Router ID: {{ router_id | IP }}
</group>
"""

ARISTA_OVERVIEW_TEMPLATE = """
<group name="ospf">
Router ID {{ router_id | IP }}
</group>
<group name="ospf_v3">
Routing Process "ospfv3" with ID {{ router_v3_id | IP }} and Instance 0 VRF default
</group>
"""

# Global to force protocol version (set by --protocol flag)
FORCE_PROTOCOL = None


def detect_vendor_and_version(content: str) -> Tuple[str, int]:
    """Detect vendor and OSPF version (2 or 3) from content."""
    global FORCE_PROTOCOL

    # If protocol is forced, use that version
    if FORCE_PROTOCOL is not None:
        version = FORCE_PROTOCOL
    else:
        # Auto-detect version
        is_v3 = False

        # Juniper OSPFv3: "Neighbor-address fe80::", "OSPF3-Intf-Index", "DR-ID"
        if 'Neighbor-address' in content or 'OSPF3-Intf-Index' in content or 'DR-ID' in content:
            is_v3 = True

        # Arista OSPFv3: "ipv6 ospf", "DR is None", "DR is " without "IP Address"
        if 'ipv6 ospf' in content.lower() or re.search(r'DR is \w+\s+BDR is', content):
            is_v3 = True

        # Generic: fe80:: link-local in the content
        if 'fe80::' in content.lower():
            is_v3 = True

        version = 3 if is_v3 else 2

    # Detect vendor
    if "Neighbor-address" in content or ("Area" in content and "opt" in content and "OSPF3" in content):
        return "juniper", version
    elif "priority is" in content and "state is" in content:
        # Arista format: "priority is X, state is Y" (v3) or "Neighbor priority is" (v2)
        return "arista", version
    elif "Neighbor priority is" in content:
        return "arista", version
    elif "Area" in content and "opt" in content:
        return "juniper", version
    # For overview files
    elif "Instance:" in content and "Router ID:" in content:
        return "juniper", version
    elif "Router ID" in content:
        return "arista", version

    return "unknown", version


def detect_vendor(content: str) -> str:
    """Legacy wrapper - returns just vendor."""
    vendor, _ = detect_vendor_and_version(content)
    return vendor


def parse_neighbor_file(filepath: str) -> Tuple[str, str, int, List[dict]]:
    """Parse neighbor file, return (hostname, vendor, ospf_version, neighbors)."""
    global FORCE_PROTOCOL
    hostname = Path(filepath).stem.replace('.log', '')

    with open(filepath) as f:
        content = f.read()

    vendor, version = detect_vendor_and_version(content)
    neighbors = []

    if HAS_TTP and vendor != "unknown":
        # Select template based on vendor AND version
        if vendor == "juniper":
            template = JUNIPER_OSPFV3_TEMPLATE if version == 3 else JUNIPER_NEIGHBOR_TEMPLATE
        else:  # arista
            template = ARISTA_OSPFV3_TEMPLATE if version == 3 else ARISTA_NEIGHBOR_TEMPLATE

        parser = ttp(data=content, template=template)
        parser.parse()
        result = parser.result()
        if result and result[0]:
            neighbors = result[0][0].get('neighbors', [])

        # If v3 template failed and protocol not forced, try v2 as fallback
        if not neighbors and version == 3 and FORCE_PROTOCOL is None:
            template = JUNIPER_NEIGHBOR_TEMPLATE if vendor == "juniper" else ARISTA_NEIGHBOR_TEMPLATE
            parser = ttp(data=content, template=template)
            parser.parse()
            result = parser.result()
            if result and result[0]:
                neighbors = result[0][0].get('neighbors', [])
                version = 2  # Actually was v2
    else:
        # Regex fallback
        if vendor == "arista":
            pattern = r'Neighbor\s+(\S+),.*?interface address\s+(\S+).*?In area\s+(\S+)\s+interface\s+(\S+).*?State is\s+(\w+)'
            for m in re.finditer(pattern, content, re.DOTALL):
                neighbors.append({
                    'router_id': m.group(1),
                    'neighbor_address': m.group(2),
                    'area': m.group(3),
                    'interface': m.group(4),
                    'state': m.group(5)
                })

    # Tag neighbors with version for later processing
    for n in neighbors:
        n['_ospf_version'] = version

    return hostname, vendor, version, neighbors


def parse_overview_file(filepath: str) -> Tuple[str, Optional[str]]:
    """Parse overview file, return (hostname, router_id)."""
    hostname = Path(filepath).stem.replace('.log', '').replace('_overview', '').replace('_ospf', '')

    with open(filepath) as f:
        content = f.read()

    vendor = detect_vendor(content)
    router_id = None

    if HAS_TTP:
        template = JUNIPER_OVERVIEW_TEMPLATE if vendor == "juniper" else ARISTA_OVERVIEW_TEMPLATE
        parser = ttp(data=content, template=template)
        parser.parse()
        result = parser.result()
        if result and result[0]:
            data = result[0][0]
            if 'ospf' in data and data['ospf'].get('router_id'):
                router_id = data['ospf']['router_id']
            elif 'ospf_v3' in data and data['ospf_v3'].get('router_v3_id'):
                router_id = data['ospf_v3']['router_v3_id']

    # Regex fallback
    if not router_id:
        match = re.search(r'Router ID[:\s]+(\d+\.\d+\.\d+\.\d+)', content)
        if match:
            router_id = match.group(1)

    if not router_id:
        match = re.search(r'with ID (\d+\.\d+\.\d+\.\d+)', content)
        if match:
            router_id = match.group(1)

    return hostname, router_id


def normalize_interface(intf: str) -> str:
    """Normalize interface naming."""
    if not intf:
        return "unknown"
    intf = intf.replace('Ethernet', 'Eth')
    intf = intf.replace('GigabitEthernet', 'Gi')
    intf = intf.replace('TenGigabitEthernet', 'Te')
    return re.sub(r'\.0$', '', intf)  # Remove Juniper .0


def is_ip_address(s: str) -> bool:
    """Check if string looks like an IP address."""
    if not s:
        return False
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', s))


# ─────────────────────────────────────────────────────────────────────────────
# Topology Builder v2
# ─────────────────────────────────────────────────────────────────────────────

class TopologyBuilder:
    """Builds Secure Cartography topology from OSPF data with improved correlation."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.links: List[Link] = []
        self.router_id_to_host: Dict[str, str] = {}
        self.host_to_router_id: Dict[str, str] = {}
        self.host_to_vendor: Dict[str, str] = {}
        self.known_hosts: Set[str] = set()
        # For correlation
        self.host_sees: Dict[str, Dict[str, Link]] = defaultdict(dict)  # host -> {rid -> link}

    def load_overview_dir(self, overview_dir: str):
        """Load router_id mappings from overview files."""
        if not overview_dir or not os.path.isdir(overview_dir):
            return

        print(f"Loading router IDs from: {overview_dir}")
        for filename in os.listdir(overview_dir):
            if not filename.endswith(('.txt', '.log')):
                continue
            filepath = os.path.join(overview_dir, filename)
            hostname, router_id = parse_overview_file(filepath)
            if router_id:
                self.router_id_to_host[router_id] = hostname
                self.host_to_router_id[hostname] = router_id
                if self.verbose:
                    print(f"  {hostname} -> {router_id}")

    def add_file(self, filepath: str):
        """Parse and add a file to the topology."""
        hostname, vendor, version, neighbors = parse_neighbor_file(filepath)

        if not neighbors:
            return  # Skip empty files

        self.known_hosts.add(hostname)
        self.host_to_vendor[hostname] = vendor

        for n in neighbors:
            intf = normalize_interface(n.get('interface', ''))
            rid = n.get('router_id', '')
            neighbor_addr = n.get('neighbor_address', '')
            ospf_version = n.get('_ospf_version', 2)

            link = Link(
                local_host=hostname,
                local_interface=intf,
                local_ip='',  # We don't have our own IP from OSPF output
                remote_router_id=rid,
                remote_ip=neighbor_addr,
                area=n.get('area', '0.0.0.0'),
                state=n.get('state', 'Unknown').upper()
            )
            self.links.append(link)

            # Build lookup for correlation
            if rid:
                self.host_sees[hostname][rid] = link

    def _same_subnet(self, ip1: str, ip2: str) -> bool:
        """
        Check if two IPs are likely on the same point-to-point link.
        Handles both IPv4 and IPv6 link-local addresses.
        """
        if not ip1 or not ip2:
            return False

        # Check if both are IPv6 link-local (fe80::)
        if ip1.lower().startswith('fe80') and ip2.lower().startswith('fe80'):
            # For link-local, we can't easily determine same-link by address
            # But if they're on the same interface (determined elsewhere), they match
            # For now, return False - we'll rely on router-id matching for v3
            return False

        # Check if mixed v4/v6 - can't be same link
        is_v6_1 = ':' in ip1
        is_v6_2 = ':' in ip2
        if is_v6_1 != is_v6_2:
            return False

        # Handle IPv6 (non link-local)
        if is_v6_1:
            # For global IPv6, check /64 prefix match
            try:
                # Simple prefix check - first 4 hextets
                parts1 = ip1.split(':')[:4]
                parts2 = ip2.split(':')[:4]
                return parts1 == parts2 and ip1 != ip2
            except:
                return False

        # IPv4 handling
        try:
            o1 = [int(x) for x in ip1.split('.')]
            o2 = [int(x) for x in ip2.split('.')]

            # Same /24
            if o1[0] == o2[0] and o1[1] == o2[1] and o1[2] == o2[2]:
                return True

            # Adjacent IPs across /24 boundaries
            int1 = (o1[0] << 24) + (o1[1] << 16) + (o1[2] << 8) + o1[3]
            int2 = (o2[0] << 24) + (o2[1] << 16) + (o2[2] << 8) + o2[3]
            if abs(int1 - int2) <= 1:
                return True

            return False
        except (ValueError, IndexError):
            return False

    def correlate(self):
        """
        Multi-pass router_id ↔ hostname correlation.
        Uses the same algorithm as ospf_to_interactive_v2.py
        """
        hostnames = list(self.known_hosts)

        # PASS 1: IP adjacency correlation
        if self.verbose:
            print("PASS 1: IP adjacency correlation...")
        pass1_count = 0

        for i, host_a in enumerate(hostnames):
            for host_b in hostnames[i + 1:]:
                if host_a in self.host_to_router_id and host_b in self.host_to_router_id:
                    continue

                for rid_a_sees, link_a in self.host_sees.get(host_a, {}).items():
                    for rid_b_sees, link_b in self.host_sees.get(host_b, {}).items():
                        if self._same_subnet(link_a.remote_ip, link_b.remote_ip):
                            if rid_a_sees not in self.router_id_to_host:
                                self.router_id_to_host[rid_a_sees] = host_b
                                self.host_to_router_id[host_b] = rid_a_sees
                                pass1_count += 1
                            if rid_b_sees not in self.router_id_to_host:
                                self.router_id_to_host[rid_b_sees] = host_a
                                self.host_to_router_id[host_a] = rid_b_sees
                                pass1_count += 1

        if self.verbose:
            print(f"  PASS 1 found {pass1_count} mappings")

        # PASS 2: Mutual visibility
        if self.verbose:
            print("PASS 2: Mutual visibility correlation...")
        pass2_count = 0
        changed = True
        iterations = 0

        while changed and iterations < 10:
            changed = False
            iterations += 1

            for hostname in self.known_hosts:
                if hostname in self.host_to_router_id:
                    continue

                for rid_we_see, link in self.host_sees[hostname].items():
                    if rid_we_see in self.router_id_to_host:
                        other_host = self.router_id_to_host[rid_we_see]

                        for rid_other_sees, other_link in self.host_sees.get(other_host, {}).items():
                            if rid_other_sees not in self.router_id_to_host:
                                if self._same_subnet(link.remote_ip, other_link.remote_ip):
                                    self.router_id_to_host[rid_other_sees] = hostname
                                    self.host_to_router_id[hostname] = rid_other_sees
                                    changed = True
                                    pass2_count += 1
                                    break
                    if hostname in self.host_to_router_id:
                        break

        if self.verbose:
            print(f"  PASS 2 found {pass2_count} mappings in {iterations} iterations")

        # PASS 3: Reverse neighbor correlation
        if self.verbose:
            print("PASS 3: Reverse neighbor correlation...")
        pass3_count = 0
        changed = True
        iterations = 0

        while changed and iterations < 10:
            changed = False
            iterations += 1

            for hostname in self.known_hosts:
                if hostname not in self.host_to_router_id:
                    continue
                our_rid = self.host_to_router_id[hostname]

                for other_host in self.known_hosts:
                    if other_host in self.host_to_router_id:
                        continue

                    for rid, link in self.host_sees.get(other_host, {}).items():
                        if rid == our_rid:
                            # other_host sees us - find what RID we see for them
                            for our_rid_sees, our_link in self.host_sees.get(hostname, {}).items():
                                if self._same_subnet(link.remote_ip, our_link.remote_ip):
                                    if our_rid_sees not in self.router_id_to_host:
                                        self.router_id_to_host[our_rid_sees] = other_host
                                        self.host_to_router_id[other_host] = our_rid_sees
                                        changed = True
                                        pass3_count += 1
                                        break
                            break

        if self.verbose:
            print(f"  PASS 3 found {pass3_count} mappings in {iterations} iterations")

        # PASS 4: Interface pattern matching
        if self.verbose:
            print("PASS 4: Interface pattern matching...")
        pass4_count = 0

        unmapped_rids = {}
        for hostname in self.known_hosts:
            for rid, link in self.host_sees.get(hostname, {}).items():
                if rid not in self.router_id_to_host:
                    if rid not in unmapped_rids:
                        unmapped_rids[rid] = []
                    unmapped_rids[rid].append({
                        'seen_by': hostname,
                        'link': link
                    })

        for hostname in self.known_hosts:
            if hostname in self.host_to_router_id:
                continue

            rids_we_see = set(self.host_sees.get(hostname, {}).keys())

            for unmapped_rid, sightings in unmapped_rids.items():
                for sighting in sightings:
                    seen_by = sighting['seen_by']
                    seen_by_rid = self.host_to_router_id.get(seen_by, '')

                    if seen_by_rid and seen_by_rid in rids_we_see:
                        our_link = self.host_sees[hostname].get(seen_by_rid)
                        if our_link and self._same_subnet(our_link.remote_ip, sighting['link'].remote_ip):
                            self.router_id_to_host[unmapped_rid] = hostname
                            self.host_to_router_id[hostname] = unmapped_rid
                            pass4_count += 1
                            break

                if hostname in self.host_to_router_id:
                    break

        if self.verbose:
            print(f"  PASS 4 found {pass4_count} mappings")

        # PASS 5: OSPFv3 bidirectional router-id matching
        # For v3 with link-local addresses, we can't use subnet matching
        # Instead: if A sees RID X, and some host B sees A's RID, B might be X
        if self.verbose:
            print("PASS 5: OSPFv3 bidirectional router-id matching...")
        pass5_count = 0

        # Build reverse lookup: which hosts see which router-ids
        rid_seen_by = defaultdict(set)  # rid -> set of hosts that see it
        for hostname in self.known_hosts:
            for rid in self.host_sees.get(hostname, {}).keys():
                rid_seen_by[rid].add(hostname)

        for hostname in self.known_hosts:
            if hostname in self.host_to_router_id:
                continue

            # What RIDs do we see?
            rids_we_see = set(self.host_sees.get(hostname, {}).keys())

            # For each RID we see, check if there's a host that:
            # 1. Is mapped to that RID
            # 2. Sees an unmapped RID that could be us
            for rid_we_see in rids_we_see:
                if rid_we_see not in self.router_id_to_host:
                    continue

                other_host = self.router_id_to_host[rid_we_see]

                # What unmapped RIDs does other_host see?
                for rid_they_see, their_link in self.host_sees.get(other_host, {}).items():
                    if rid_they_see in self.router_id_to_host:
                        continue  # Already mapped

                    # Check if we're the only unmapped host that sees other_host
                    hosts_seeing_rid_we_see = rid_seen_by.get(rid_we_see, set())
                    unmapped_hosts_seeing = [h for h in hosts_seeing_rid_we_see
                                             if h not in self.host_to_router_id]

                    if len(unmapped_hosts_seeing) == 1 and unmapped_hosts_seeing[0] == hostname:
                        # We're the only unmapped host that sees other_host
                        # So rid_they_see is likely us
                        self.router_id_to_host[rid_they_see] = hostname
                        self.host_to_router_id[hostname] = rid_they_see
                        pass5_count += 1
                        if self.verbose:
                            print(f"    {rid_they_see} -> {hostname} (v3 bidir via {other_host})")
                        break

                if hostname in self.host_to_router_id:
                    break

        if self.verbose:
            print(f"  PASS 5 found {pass5_count} mappings")

        total = len(self.router_id_to_host)
        unmapped = len(self.known_hosts) - len(self.host_to_router_id)
        print(f"Correlation complete: {total} mappings, {unmapped} unmapped hosts")

    def get_remote_interface(self, local_host: str, local_intf: str, remote_host: str) -> str:
        """Find what interface the remote host uses to connect to us."""
        our_rid = self.host_to_router_id.get(local_host)

        # Find the link from local to remote
        local_link = None
        remote_rid = self.host_to_router_id.get(remote_host)
        for link in self.links:
            if link.local_host == local_host and link.local_interface == local_intf:
                local_link = link
                break

        if not local_link:
            return "unknown"

        # Now find the reverse link from remote_host
        for link in self.links:
            if link.local_host == remote_host:
                # Match by router_id
                if our_rid and link.remote_router_id == our_rid:
                    # Verify it's the same link by checking IP proximity
                    if self._same_subnet(local_link.remote_ip, link.remote_ip):
                        return link.local_interface

                # Match by hostname mapping
                mapped_host = self.router_id_to_host.get(link.remote_router_id)
                if mapped_host == local_host:
                    if self._same_subnet(local_link.remote_ip, link.remote_ip):
                        return link.local_interface

        # Fallback: just find any link from remote to local
        for link in self.links:
            if link.local_host == remote_host:
                if our_rid and link.remote_router_id == our_rid:
                    return link.local_interface
                mapped_host = self.router_id_to_host.get(link.remote_router_id)
                if mapped_host == local_host:
                    return link.local_interface

        return "unknown"

    def infer_platform(self, hostname: str) -> str:
        """Infer platform from hostname and vendor."""
        vendor = self.host_to_vendor.get(hostname, 'unknown')
        h = hostname.lower()

        if 'qfx' in h: return 'QFX5100'
        if 'mx' in h: return 'MX204'
        if 'edge' in h: return 'DCS-7280' if vendor == 'arista' else 'MX204'
        if 'agg' in h: return 'DCS-7050' if vendor == 'arista' else 'QFX5100'
        if 'tor' in h: return 'DCS-7050SX'
        if 'oob' in h: return 'DCS-7010T'
        if 'peer' in h: return 'MX204'
        if 'spine' in h: return 'vEOS-lab'
        if 'leaf' in h: return 'IOSv'
        if 'rtr' in h: return 'IOSv'
        if 'core' in h: return '7206VXR'

        return 'vEOS-lab' if vendor == 'arista' else 'vMX'

    def build_schema(self) -> dict:
        """Build the Secure Cartography topology schema."""
        self.correlate()

        schema = {}

        # Initialize all known devices
        for host in self.known_hosts:
            rid = self.host_to_router_id.get(host, '0.0.0.0')
            schema[host] = {
                "node_details": {
                    "ip": rid,
                    "platform": self.infer_platform(host),
                    "vendor": self.host_to_vendor.get(host, 'unknown')
                },
                "peers": {}
            }

        # Also add devices we only see as neighbors (no OSPF data from them)
        for link in self.links:
            remote_host = self.router_id_to_host.get(link.remote_router_id, link.remote_router_id)
            if remote_host not in schema:
                schema[remote_host] = {
                    "node_details": {
                        "ip": link.remote_router_id,
                        "platform": self.infer_platform(remote_host),
                        "vendor": "unknown",
                        "inferred": True  # Flag that we don't have direct data
                    },
                    "peers": {}
                }

        # Build peer relationships with full interface info
        seen_connections = set()  # Avoid duplicates

        for link in self.links:
            local = link.local_host
            remote_host = self.router_id_to_host.get(link.remote_router_id, link.remote_router_id)
            remote_intf = self.get_remote_interface(local, link.local_interface, remote_host)

            # Connection key for deduplication
            conn_key = tuple(sorted([
                f"{local}:{link.local_interface}",
                f"{remote_host}:{remote_intf}"
            ]))

            if conn_key in seen_connections:
                continue
            seen_connections.add(conn_key)

            # Add to local's peer list
            if remote_host not in schema[local]["peers"]:
                schema[local]["peers"][remote_host] = {
                    "ip": link.remote_router_id if is_ip_address(link.remote_router_id) else self.host_to_router_id.get(
                        remote_host, ''),
                    "platform": self.infer_platform(remote_host),
                    "connections": []
                }

            connection = [link.local_interface, remote_intf]
            if connection not in schema[local]["peers"][remote_host]["connections"]:
                schema[local]["peers"][remote_host]["connections"].append(connection)

            # Add reverse to remote's peer list (if it exists in schema)
            if remote_host in schema:
                if local not in schema[remote_host]["peers"]:
                    schema[remote_host]["peers"][local] = {
                        "ip": self.host_to_router_id.get(local, ''),
                        "platform": self.infer_platform(local),
                        "connections": []
                    }

                reverse_conn = [remote_intf, link.local_interface]
                if reverse_conn not in schema[remote_host]["peers"][local]["connections"]:
                    schema[remote_host]["peers"][local]["connections"].append(reverse_conn)

        return schema


# ─────────────────────────────────────────────────────────────────────────────
# Output Generators
# ─────────────────────────────────────────────────────────────────────────────

def generate_mermaid(schema: dict) -> str:
    """Generate Mermaid diagram from topology schema."""
    lines = ["graph LR"]
    seen = set()

    for device, data in schema.items():
        dev_id = device.replace('.', '_').replace('-', '_')

        for peer, peer_data in data["peers"].items():
            peer_id = peer.replace('.', '_').replace('-', '_')

            # Create canonical edge to avoid duplicates
            edge = tuple(sorted([dev_id, peer_id]))
            if edge in seen:
                continue
            seen.add(edge)

            # Get connection info
            conns = peer_data.get("connections", [])
            if conns:
                label = f"{conns[0][0]} ↔ {conns[0][1]}"
            else:
                label = ""

            lines.append(f'    {dev_id}["{device}"] --- |"{label}"| {peer_id}["{peer}"]')

    return '\n'.join(lines)


def generate_summary(schema: dict) -> str:
    """Generate text summary of topology."""
    lines = ["=" * 60, "OSPF Topology Summary", "=" * 60, ""]

    total_devices = len(schema)
    total_connections = sum(
        sum(len(p["connections"]) for p in d["peers"].values())
        for d in schema.values()
    ) // 2  # Divide by 2 since bidirectional

    lines.append(f"Devices: {total_devices}")
    lines.append(f"Connections: {total_connections}")
    lines.append("")

    # Group by role/platform
    by_platform = defaultdict(list)
    for device, data in schema.items():
        platform = data["node_details"].get("platform", "unknown")
        by_platform[platform].append(device)

    lines.append("Devices by Platform:")
    for platform, devices in sorted(by_platform.items()):
        lines.append(f"  {platform}: {len(devices)}")

    lines.append("")
    lines.append("Connection Details:")
    lines.append("-" * 60)

    for device in sorted(schema.keys()):
        data = schema[device]
        if not data["peers"]:
            continue

        lines.append(f"\n{device} ({data['node_details'].get('platform', '?')}):")
        for peer, peer_data in sorted(data["peers"].items()):
            for conn in peer_data["connections"]:
                lines.append(f"  {conn[0]:20} <-> {peer}:{conn[1]}")

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description='OSPF to Secure Cartography Topology v2')
    parser.add_argument('-i', '--input-dir', required=True, help='OSPF capture directory')
    parser.add_argument('-o', '--output', default='topology.json', help='Output JSON file')
    parser.add_argument('--overview-dir', help='Directory with OSPF overview files')
    parser.add_argument('--protocol', choices=['2', '3', 'auto'], default='auto',
                        help='Force OSPF version (2=IPv4, 3=IPv6, auto=detect)')
    parser.add_argument('--mermaid', help='Also generate Mermaid diagram')
    parser.add_argument('--summary', help='Also generate text summary')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    # Set global protocol version
    global FORCE_PROTOCOL
    FORCE_PROTOCOL = None if args.protocol == 'auto' else int(args.protocol)

    if FORCE_PROTOCOL:
        print(f"Forcing OSPFv{FORCE_PROTOCOL} parsing mode")

    builder = TopologyBuilder(verbose=args.verbose)

    # Load overview files first (for direct router_id mappings)
    if args.overview_dir:
        builder.load_overview_dir(args.overview_dir)

    # Also check input_dir for overview files
    for f in os.listdir(args.input_dir):
        if any(x in f.lower() for x in ['overview', '_rid', '_routerid']):
            if f.endswith(('.txt', '.log')):
                hostname, router_id = parse_overview_file(os.path.join(args.input_dir, f))
                if router_id and hostname not in builder.host_to_router_id:
                    builder.router_id_to_host[router_id] = hostname
                    builder.host_to_router_id[hostname] = router_id

    # Parse all neighbor files
    for f in os.listdir(args.input_dir):
        if not f.endswith(('.txt', '.log')):
            continue
        if any(x in f.lower() for x in ['overview', '_rid', '_routerid']):
            continue
        builder.add_file(os.path.join(args.input_dir, f))

    print(f"Parsed {len(builder.known_hosts)} devices with {len(builder.links)} neighbor entries")

    # Build schema
    schema = builder.build_schema()

    # Stats
    total_peers = sum(len(d["peers"]) for d in schema.values())
    total_connections = sum(
        sum(len(p["connections"]) for p in d["peers"].values())
        for d in schema.values()
    ) // 2

    print(f"Generated topology: {len(schema)} devices, {total_connections} connections")

    # Count interfaces resolved vs unknown
    resolved = 0
    unknown = 0
    for device, data in schema.items():
        for peer, peer_data in data["peers"].items():
            for conn in peer_data["connections"]:
                if conn[1] != "unknown":
                    resolved += 1
                else:
                    unknown += 1

    print(f"Interface resolution: {resolved} resolved, {unknown} unknown")

    # Write JSON
    with open(args.output, 'w') as f:
        json.dump(schema, f, indent=2)
    print(f"Wrote: {args.output}")

    # Optionally generate Mermaid
    if args.mermaid:
        mermaid = generate_mermaid(schema)
        with open(args.mermaid, 'w') as f:
            f.write(mermaid)
        print(f"Wrote: {args.mermaid}")

    # Optionally generate summary
    if args.summary:
        summary = generate_summary(schema)
        with open(args.summary, 'w') as f:
            f.write(summary)
        print(f"Wrote: {args.summary}")


if __name__ == '__main__':
    main()