#!/usr/bin/env python3
"""
OSPF Analytics Parser v2 - Outputs rich JSON for interactive visualization.
Preserves DR/BDR, area, state, uptime, and other OSPF details.

Now supports direct router_id mapping from 'show ospf overview' files.
v2: Added bidirectional validation and reverse correlation for better link accuracy.

Usage:
    python ospf_to_interactive_v2.py -i ./capture/ospf_analytics -o ospf_data.json
    python ospf_to_interactive_v2.py -i ./capture/ospf_analytics -o ospf_data.json --overview-dir ./capture/ospf_overview
"""

import os
import re
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

try:
    from ttp import ttp

    HAS_TTP = True
except ImportError:
    HAS_TTP = False
    print("Warning: TTP not installed. Using regex fallback.")

# TTP Templates for neighbor data
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
  Inactivity timer deferred {{ inactivity_deferred | to_int }} times
  LSAs retransmitted {{ lsa_retransmit_count | to_int }} times to this neighbor
  Graceful-restart-helper mode is {{ gr_helper_mode }}
  Graceful-restart attempts: {{ gr_attempts | to_int }}
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

# TTP Templates for overview/router-id extraction
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


def detect_vendor_and_version(content: str) -> tuple:
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
        return "arista", version
    elif "Neighbor priority is" in content:
        return "arista", version
    elif "Area" in content and "opt" in content:
        return "juniper", version
    elif "Instance:" in content and "Router ID:" in content:
        return "juniper", version
    elif "Router ID" in content:
        return "arista", version

    return "unknown", version


def detect_vendor(content: str) -> str:
    """Legacy wrapper - returns just vendor."""
    vendor, _ = detect_vendor_and_version(content)
    return vendor


def parse_neighbor_file(filepath: str) -> tuple:
    """Parse neighbor file, return (hostname, vendor, neighbors)."""
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

    return hostname, vendor, neighbors


def parse_overview_file(filepath: str) -> tuple:
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
            # Check ospf group first (v2), then ospf_v3 as fallback
            if 'ospf' in data and data['ospf'].get('router_id'):
                router_id = data['ospf']['router_id']
            elif 'ospf_v3' in data and data['ospf_v3'].get('router_v3_id'):
                router_id = data['ospf_v3']['router_v3_id']

    # Regex fallback
    if not router_id:
        # Try standard "Router ID x.x.x.x" format
        match = re.search(r'Router ID[:\s]+(\d+\.\d+\.\d+\.\d+)', content)
        if match:
            router_id = match.group(1)

    if not router_id:
        # Try OSPFv3 format: Routing Process "ospfv3" with ID x.x.x.x
        match = re.search(r'with ID (\d+\.\d+\.\d+\.\d+)', content)
        if match:
            router_id = match.group(1)

    return hostname, router_id


def load_overview_files(overview_dir: str) -> dict:
    """Load all overview files and return hostname -> router_id map."""
    rid_map = {}

    if not overview_dir or not os.path.isdir(overview_dir):
        return rid_map

    for filename in os.listdir(overview_dir):
        if not filename.endswith(('.txt', '.log')):
            continue

        filepath = os.path.join(overview_dir, filename)
        hostname, router_id = parse_overview_file(filepath)

        if router_id:
            rid_map[hostname] = router_id
            print(f"  {hostname} -> {router_id}")

    return rid_map


def normalize_interface(intf: str) -> str:
    """Normalize interface naming."""
    if not intf:
        return "unknown"
    intf = intf.replace('Ethernet', 'Eth')
    intf = intf.replace('GigabitEthernet', 'Gi')
    intf = intf.replace('TenGigabitEthernet', 'Te')
    return re.sub(r'\.0$', '', intf)


def infer_platform(hostname: str, vendor: str) -> str:
    """Infer platform from hostname and vendor."""
    h = hostname.lower()
    if 'qfx' in h: return 'QFX5100'
    if 'mx' in h: return 'MX204'
    if 'edge' in h: return 'MX204' if vendor == 'juniper' else 'DCS-7280'
    if 'agg' in h: return 'DCS-7050' if vendor == 'arista' else 'QFX5100'
    if 'tor' in h: return 'DCS-7050SX'
    if 'oob' in h: return 'DCS-7010T'
    if 'peer' in h: return 'MX204'
    if 'spine' in h: return 'vEOS-lab'
    if 'leaf' in h: return 'IOSv'
    return 'vEOS-lab' if vendor == 'arista' else 'vMX'


def infer_site(hostname: str) -> str:
    """Extract site from hostname."""
    h = hostname.lower()
    if '.iad1' in h or '-iad1' in h: return 'iad1'
    if '.iad2' in h or '-iad2' in h: return 'iad2'
    if '.fra1' in h or '-fra1' in h: return 'fra1'
    return 'unknown'


def infer_role(hostname: str) -> str:
    """Infer device role from hostname."""
    h = hostname.lower()
    if 'edge' in h: return 'edge'
    if 'peer' in h: return 'peer'
    if 'agg' in h: return 'aggregation'
    if 'spine' in h: return 'spine'
    if 'leaf' in h: return 'leaf'
    if 'tor' in h: return 'tor'
    if 'oob' in h: return 'oob'
    if 'qfx' in h: return 'spine'
    if 'core' in h: return 'core'
    return 'unknown'


def are_likely_same_link(ip1: str, ip2: str) -> bool:
    """
    Check if two IPs are likely on the same point-to-point link.
    Handles both IPv4 and IPv6 addresses.
    """
    if not ip1 or not ip2:
        return False

    # Check if both are IPv6 link-local (fe80::)
    if ip1.lower().startswith('fe80') and ip2.lower().startswith('fe80'):
        # For link-local, we can't determine same-link by address alone
        return False

    # Check if mixed v4/v6 - can't be same link
    is_v6_1 = ':' in ip1
    is_v6_2 = ':' in ip2
    if is_v6_1 != is_v6_2:
        return False

    # Handle IPv6 (non link-local)
    if is_v6_1:
        try:
            # Simple prefix check - first 4 hextets (/64)
            parts1 = ip1.split(':')[:4]
            parts2 = ip2.split(':')[:4]
            return parts1 == parts2 and ip1 != ip2
        except:
            return False

    # IPv4 handling
    try:
        o1 = [int(x) for x in ip1.split('.')]
        o2 = [int(x) for x in ip2.split('.')]

        # Same /24? That's good enough
        if o1[0] == o2[0] and o1[1] == o2[1] and o1[2] == o2[2]:
            return True

        # Also allow adjacent IPs across /24 boundaries
        int1 = (o1[0] << 24) + (o1[1] << 16) + (o1[2] << 8) + o1[3]
        int2 = (o2[0] << 24) + (o2[1] << 16) + (o2[2] << 8) + o2[3]

        if abs(int1 - int2) <= 1:
            return True

        return False

    except (ValueError, IndexError):
        return False


def is_ip_address(s: str) -> bool:
    """Check if string looks like an IP address (unmapped router_id)."""
    if not s:
        return False
    return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', s))


def validate_bidirectional_links(raw_data: dict, links: list,
                                 router_id_to_host: dict,
                                 host_to_router_id: dict,
                                 verbose: bool = False) -> list:
    """
    Back-check: For each link, verify we have neighbor data from both sides.
    Flag links that are one-directional and add bidirectional metadata.
    """
    validated_links = []
    orphan_count = 0

    for link in links:
        source = link['source']
        target = link['target']

        # Check if target is a raw router_id (unmapped)
        is_target_unmapped = is_ip_address(target)

        # Check reverse: does target report source as neighbor?
        reverse_exists = False
        if target in raw_data:
            source_rid = host_to_router_id.get(source, '')
            for n in raw_data[target]['neighbors']:
                if n.get('router_id') == source_rid:
                    reverse_exists = True
                    break
                # Also check by neighbor_address proximity
                if are_likely_same_link(link.get('neighbor_address', ''), n.get('neighbor_address', '')):
                    reverse_exists = True
                    break

        link['bidirectional'] = reverse_exists
        link['target_unmapped'] = is_target_unmapped

        # Include all links, but flag orphans
        if is_target_unmapped and not reverse_exists:
            orphan_count += 1
            if verbose:
                print(f"  Orphan link: {source} -> {target} (unmapped, no reverse)")

        validated_links.append(link)

    if orphan_count > 0:
        print(f"Warning: {orphan_count} orphan links (unmapped target, no reverse confirmation)")

    return validated_links


def build_ospf_data(input_dir: str, overview_dir: str = None, verbose: bool = False) -> dict:
    """Build rich OSPF dataset for interactive visualization."""

    # Phase 0: Load direct router_id mappings from overview files
    direct_rid_map = {}  # hostname -> router_id (from show ospf overview)

    # If overview_dir specified, use it
    if overview_dir:
        print(f"Loading router IDs from overview files in: {overview_dir}")
        direct_rid_map = load_overview_files(overview_dir)

    # Also check input_dir for files matching *_overview.txt or *_rid.txt patterns
    for filename in os.listdir(input_dir):
        if any(x in filename.lower() for x in ['overview', '_rid', '_routerid', '_ospf_id']):
            if filename.endswith(('.txt', '.log')):
                filepath = os.path.join(input_dir, filename)
                hostname, router_id = parse_overview_file(filepath)
                if router_id and hostname not in direct_rid_map:
                    direct_rid_map[hostname] = router_id

    if direct_rid_map:
        print(f"Loaded {len(direct_rid_map)} direct router_id mappings")
        if verbose:
            for h, r in sorted(direct_rid_map.items()):
                print(f"  {h} -> {r}")

    # Phase 1: Parse all neighbor files
    raw_data = {}
    all_neighbors = []

    for filename in os.listdir(input_dir):
        if not filename.endswith(('.txt', '.log')):
            continue
        # Skip overview files
        if any(x in filename.lower() for x in ['overview', '_rid', '_routerid', '_ospf_id']):
            continue

        filepath = os.path.join(input_dir, filename)
        hostname, vendor, neighbors = parse_neighbor_file(filepath)

        # Skip files with no neighbors (might be overview files we missed)
        if not neighbors:
            continue

        raw_data[hostname] = {
            'vendor': vendor,
            'neighbors': neighbors
        }

        for n in neighbors:
            all_neighbors.append({
                'local_host': hostname,
                'local_vendor': vendor,
                **n
            })

    print(f"Parsed {len(raw_data)} neighbor files with {len(all_neighbors)} total neighbor entries")

    # Phase 2: Build router_id <-> hostname mappings
    # Start with direct mappings from overview files
    router_id_to_host = {}
    host_to_router_id = {}

    # First: use direct mappings (authoritative)
    for hostname, rid in direct_rid_map.items():
        router_id_to_host[rid] = hostname
        host_to_router_id[hostname] = rid

    # Build lookup: for each host, what router_ids does it see?
    host_sees = {}
    for hostname, data in raw_data.items():
        host_sees[hostname] = {}
        for n in data['neighbors']:
            rid = n.get('router_id', '')
            if rid:
                host_sees[hostname][rid] = n

    # PASS 1: Find additional mappings via IP adjacency (for devices without overview)
    print("PASS 1: IP adjacency correlation...")
    hostnames = list(raw_data.keys())
    pass1_mappings = 0
    for i, host_a in enumerate(hostnames):
        for host_b in hostnames[i + 1:]:
            # Skip if both already mapped
            if host_a in host_to_router_id and host_b in host_to_router_id:
                continue

            for rid_a_sees, n_a in host_sees.get(host_a, {}).items():
                for rid_b_sees, n_b in host_sees.get(host_b, {}).items():
                    addr_a = n_a.get('neighbor_address', '')
                    addr_b = n_b.get('neighbor_address', '')

                    if are_likely_same_link(addr_a, addr_b):
                        if rid_a_sees not in router_id_to_host:
                            router_id_to_host[rid_a_sees] = host_b
                            host_to_router_id[host_b] = rid_a_sees
                            pass1_mappings += 1
                            if verbose:
                                print(f"  PASS1: {rid_a_sees} -> {host_b}")
                        if rid_b_sees not in router_id_to_host:
                            router_id_to_host[rid_b_sees] = host_a
                            host_to_router_id[host_a] = rid_b_sees
                            pass1_mappings += 1
                            if verbose:
                                print(f"  PASS1: {rid_b_sees} -> {host_a}")

    print(f"  PASS 1 found {pass1_mappings} mappings")

    # PASS 2: Extend mappings using mutual visibility
    print("PASS 2: Mutual visibility correlation...")
    changed = True
    iterations = 0
    pass2_mappings = 0
    while changed and iterations < 10:
        changed = False
        iterations += 1

        for hostname in raw_data.keys():
            if hostname in host_to_router_id:
                continue

            for rid_we_see, n_data in host_sees[hostname].items():
                if rid_we_see in router_id_to_host:
                    other_host = router_id_to_host[rid_we_see]

                    for rid_other_sees in host_sees.get(other_host, {}).keys():
                        if rid_other_sees not in router_id_to_host:
                            our_addr = n_data.get('neighbor_address', '')
                            their_n = host_sees[other_host][rid_other_sees]
                            their_addr = their_n.get('neighbor_address', '')

                            if are_likely_same_link(our_addr, their_addr):
                                router_id_to_host[rid_other_sees] = hostname
                                host_to_router_id[hostname] = rid_other_sees
                                changed = True
                                pass2_mappings += 1
                                if verbose:
                                    print(f"  PASS2: {rid_other_sees} -> {hostname}")
                                break
                if hostname in host_to_router_id:
                    break

    print(f"  PASS 2 found {pass2_mappings} mappings in {iterations} iterations")

    # PASS 3: Use reverse neighbor reports to resolve unmapped router_ids
    # Key insight: If host A reports neighbor with RID X, and we know A's RID,
    # then any host that reports A's RID is potentially the owner of RID X
    print("PASS 3: Reverse neighbor correlation...")
    pass3_mappings = 0
    changed = True
    iterations = 0

    while changed and iterations < 10:
        changed = False
        iterations += 1

        for hostname, data in raw_data.items():
            if hostname not in host_to_router_id:
                continue
            our_rid = host_to_router_id[hostname]

            # Who reports US as a neighbor?
            for other_host, other_data in raw_data.items():
                if other_host in host_to_router_id:
                    continue  # Already mapped

                for n in other_data['neighbors']:
                    if n.get('router_id') == our_rid:
                        # other_host sees us - now find what RID we see for them
                        other_addr = n.get('neighbor_address', '')

                        for our_n in data['neighbors']:
                            our_neighbor_addr = our_n.get('neighbor_address', '')

                            if are_likely_same_link(other_addr, our_neighbor_addr):
                                their_rid = our_n.get('router_id', '')
                                if their_rid and their_rid not in router_id_to_host:
                                    router_id_to_host[their_rid] = other_host
                                    host_to_router_id[other_host] = their_rid
                                    changed = True
                                    pass3_mappings += 1
                                    if verbose:
                                        print(f"  PASS3: {their_rid} -> {other_host} (via reverse from {hostname})")
                                    break
                        break  # Found the reverse link, move to next other_host

    print(f"  PASS 3 found {pass3_mappings} mappings in {iterations} iterations")

    # PASS 4: Last resort - match by interface naming patterns
    # If host A sees RID X on interface "Ethernet1/1" and host B (unmapped)
    # sees a neighbor on a corresponding interface, try to correlate
    print("PASS 4: Interface pattern matching...")
    pass4_mappings = 0

    # Build a map of all unmapped RIDs and who sees them
    unmapped_rids = {}
    for hostname, data in raw_data.items():
        for n in data['neighbors']:
            rid = n.get('router_id', '')
            if rid and rid not in router_id_to_host:
                if rid not in unmapped_rids:
                    unmapped_rids[rid] = []
                unmapped_rids[rid].append({
                    'seen_by': hostname,
                    'interface': n.get('interface', ''),
                    'neighbor_address': n.get('neighbor_address', ''),
                    'area': n.get('area', '')
                })

    # For each unmapped host, see if it reports neighbors that could identify it
    for hostname in raw_data.keys():
        if hostname in host_to_router_id:
            continue

        # What RIDs does this host see?
        rids_we_see = set(host_sees.get(hostname, {}).keys())

        # Check each unmapped RID - if it's seen by hosts that WE also see,
        # and we're the only unmapped host that fits, we might be it
        for unmapped_rid, sightings in unmapped_rids.items():
            for sighting in sightings:
                seen_by = sighting['seen_by']
                seen_by_rid = host_to_router_id.get(seen_by, '')

                # Do we see the host that sees this unmapped RID?
                if seen_by_rid and seen_by_rid in rids_we_see:
                    # Check address proximity
                    our_view = host_sees[hostname].get(seen_by_rid, {})
                    our_addr = our_view.get('neighbor_address', '')
                    their_addr = sighting['neighbor_address']

                    if are_likely_same_link(our_addr, their_addr):
                        router_id_to_host[unmapped_rid] = hostname
                        host_to_router_id[hostname] = unmapped_rid
                        pass4_mappings += 1
                        if verbose:
                            print(f"  PASS4: {unmapped_rid} -> {hostname} (interface pattern via {seen_by})")
                        break

            if hostname in host_to_router_id:
                break

    print(f"  PASS 4 found {pass4_mappings} mappings")

    total_mappings = len(router_id_to_host)
    print(f"After all correlation passes: {total_mappings} router_id mappings")
    unmapped = set(raw_data.keys()) - set(host_to_router_id.keys())
    print(f"Unmapped hosts: {len(unmapped)}")
    if unmapped and verbose:
        for h in sorted(unmapped):
            print(f"  {h}")

    # Phase 3: Build nodes
    nodes = []
    all_hostnames = set(raw_data.keys())

    # Add devices we see as neighbors but don't have data for
    for n in all_neighbors:
        rid = n.get('router_id', '')
        if rid:
            if rid in router_id_to_host:
                all_hostnames.add(router_id_to_host[rid])
            else:
                all_hostnames.add(rid)  # Use RID as hostname if unmapped

    for hostname in all_hostnames:
        vendor = raw_data.get(hostname, {}).get('vendor', 'unknown')
        neighbor_count = len(raw_data.get(hostname, {}).get('neighbors', []))

        # Check if this is an unmapped router_id being used as hostname
        is_unmapped_rid = is_ip_address(hostname) and hostname not in raw_data

        nodes.append({
            'id': hostname,
            'router_id': host_to_router_id.get(hostname, hostname),
            'platform': infer_platform(hostname, vendor),
            'vendor': vendor,
            'site': infer_site(hostname),
            'role': infer_role(hostname),
            'neighbor_count': neighbor_count,
            'has_data': hostname in raw_data,
            'is_unmapped': is_unmapped_rid
        })

    # Phase 4: Build links
    links = []
    seen_links = set()

    for n in all_neighbors:
        source = n['local_host']
        target_rid = n.get('router_id', '')
        target = router_id_to_host.get(target_rid, target_rid)

        source_intf = normalize_interface(n.get('interface', ''))

        # Find target's interface
        target_interface = 'unknown'
        our_rid = host_to_router_id.get(source, '')

        if target in raw_data:
            # Try exact router_id match first
            for tn in raw_data[target]['neighbors']:
                if tn.get('router_id') == our_rid:
                    target_interface = normalize_interface(tn.get('interface', ''))
                    break

            # Fallback: match by neighbor_address proximity
            if target_interface == 'unknown':
                for tn in raw_data[target]['neighbors']:
                    if are_likely_same_link(n.get('neighbor_address', ''), tn.get('neighbor_address', '')):
                        target_interface = normalize_interface(tn.get('interface', ''))
                        break

        # Dedupe: use sorted pair + sorted interfaces
        link_pair = tuple(sorted([source, target]))
        intf_pair = tuple(sorted([source_intf, target_interface]))
        link_key = (link_pair, intf_pair)

        if link_key in seen_links:
            continue
        seen_links.add(link_key)

        links.append({
            'id': f"{source}_{target}_{source_intf}",
            'source': source,
            'target': target,
            'source_interface': source_intf,
            'target_interface': target_interface,
            'area': n.get('area', '0.0.0.0'),
            'state': n.get('state', 'unknown').upper(),
            'dr': n.get('dr', ''),
            'bdr': n.get('bdr', ''),
            'source_priority': n.get('priority', 0),
            'adjacency_time': n.get('adjacency_time', n.get('adjacent_time', '')),
            'dead_timer': n.get('dead_timer', n.get('dead_time', '')),
            'neighbor_address': n.get('neighbor_address', ''),
            'options': n.get('options', ''),
            'state_changes': n.get('state_changes', 0),
            'lsa_retransmit_count': n.get('lsa_retransmit_count', 0)
        })

    # Phase 4.5: Bidirectional validation
    print("Validating bidirectional links...")
    links = validate_bidirectional_links(raw_data, links, router_id_to_host,
                                         host_to_router_id, verbose=verbose)

    # Phase 5: Build area summary
    areas = defaultdict(lambda: {'device_count': 0, 'link_count': 0, 'devices': set()})
    for link in links:
        area = link['area']
        areas[area]['link_count'] += 1
        areas[area]['devices'].add(link['source'])
        areas[area]['devices'].add(link['target'])

    for area in areas:
        areas[area]['device_count'] = len(areas[area]['devices'])
        del areas[area]['devices']

    # Build peer summary for each node
    node_peers = defaultdict(list)
    for link in links:
        node_peers[link['source']].append({
            'peer': link['target'],
            'interface': link['source_interface'],
            'state': link['state'],
            'bidirectional': link.get('bidirectional', False)
        })
        node_peers[link['target']].append({
            'peer': link['source'],
            'interface': link['target_interface'],
            'state': link['state'],
            'bidirectional': link.get('bidirectional', False)
        })

    # Add peer info to nodes
    for node in nodes:
        node['peers'] = node_peers.get(node['id'], [])
        node['peer_count'] = len(node['peers'])

    return {
        'metadata': {
            'generated': datetime.now().isoformat(),
            'source_directory': input_dir,
            'device_count': len(nodes),
            'link_count': len(links),
            'area_count': len(areas),
            'devices_with_data': len(raw_data),
            'router_id_mappings': len(router_id_to_host),
            'unmapped_nodes': sum(1 for n in nodes if n.get('is_unmapped', False)),
            'bidirectional_links': sum(1 for l in links if l.get('bidirectional', False)),
            'unidirectional_links': sum(1 for l in links if not l.get('bidirectional', False))
        },
        'nodes': nodes,
        'links': links,
        'areas': dict(areas),
        '_debug_rid_map': dict(router_id_to_host)
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description='OSPF to Interactive JSON v2')
    parser.add_argument('-i', '--input-dir', required=True, help='OSPF neighbor capture directory')
    parser.add_argument('-o', '--output', default='ospf_data.json', help='Output JSON file')
    parser.add_argument('--overview-dir', help='Directory with OSPF overview files (for direct router_id mapping)')
    parser.add_argument('--protocol', choices=['2', '3', 'auto'], default='auto',
                        help='Force OSPF version (2=IPv4, 3=IPv6, auto=detect)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    # Set global protocol version
    global FORCE_PROTOCOL
    FORCE_PROTOCOL = None if args.protocol == 'auto' else int(args.protocol)

    if FORCE_PROTOCOL:
        print(f"Forcing OSPFv{FORCE_PROTOCOL} parsing mode")

    print(f"Parsing OSPF neighbor files from: {args.input_dir}")
    print("=" * 60)
    data = build_ospf_data(args.input_dir, overview_dir=args.overview_dir, verbose=args.verbose)
    print("=" * 60)

    print(f"\nSummary:")
    print(f"  Devices: {data['metadata']['device_count']}")
    print(f"  Links: {data['metadata']['link_count']}")
    print(f"  Areas: {list(data['areas'].keys())}")
    print(f"  Router-ID mappings: {data['metadata']['router_id_mappings']}")
    print(f"  Unmapped nodes: {data['metadata']['unmapped_nodes']}")
    print(f"  Bidirectional links: {data['metadata']['bidirectional_links']}")
    print(f"  Unidirectional links: {data['metadata']['unidirectional_links']}")

    if args.verbose:
        print("\nRouter-ID -> Hostname mappings:")
        for rid, host in sorted(data.get('_debug_rid_map', {}).items()):
            print(f"  {rid} -> {host}")

    # Remove debug data before saving
    debug_map = data.pop('_debug_rid_map', {})

    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nWrote: {args.output}")


if __name__ == '__main__':
    main()