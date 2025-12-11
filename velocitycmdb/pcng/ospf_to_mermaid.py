#!/usr/bin/env python3
"""
OSPF Peer Visualization Generator
Parses Arista and Juniper OSPF neighbor data and generates Mermaid diagrams.

Usage:
    python ospf_to_mermaid.py --input-dir ./capture/ospf_analytics --output ospf_topology.mermaid
"""

import os
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

try:
    from ttp import ttp

    HAS_TTP = True
except ImportError:
    HAS_TTP = False
    print("Warning: TTP not installed. Using regex fallback.")

# TTP Templates
JUNIPER_TEMPLATE = """
<group name="neighbors*">
{{ neighbor_address | IP }} {{ interface }} {{ state }} {{ router_id | IP }} {{ priority | to_int }} {{ dead_time | to_int }}
  Area {{ area | IP }}, opt {{ options }}, DR {{ dr | IP }}, BDR {{ bdr | IP }}
  Up {{ uptime | ORPHRASE }}, adjacent {{ adjacent_time | ORPHRASE }}
  Topology {{ topology_name }} (ID {{ topology_id | to_int }}) -> {{ topology_state }}
</group>
"""

ARISTA_TEMPLATE = """
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


@dataclass
class OSPFNeighbor:
    """Represents an OSPF neighbor relationship."""
    local_device: str
    local_interface: str
    neighbor_router_id: str
    neighbor_address: str
    area: str
    state: str
    dr: str = ""
    bdr: str = ""

    def __hash__(self):
        # Create a canonical edge (sorted by router names for deduplication)
        return hash(tuple(sorted([self.local_device, self.neighbor_router_id])) + (self.area,))

    def __eq__(self, other):
        if not isinstance(other, OSPFNeighbor):
            return False
        # Two neighbors are equal if they represent the same link (either direction)
        local_pair = {self.local_device, self.neighbor_router_id}
        other_pair = {other.local_device, other.neighbor_router_id}
        return local_pair == other_pair and self.area == other.area


@dataclass
class OSPFTopology:
    """Container for the full OSPF topology."""
    neighbors: list = field(default_factory=list)
    devices: dict = field(default_factory=dict)  # device_name -> router_id mapping
    areas: dict = field(default_factory=lambda: defaultdict(list))  # area -> list of links

    def add_neighbor(self, neighbor: OSPFNeighbor):
        self.neighbors.append(neighbor)
        self.areas[neighbor.area].append(neighbor)

    def deduplicate_links(self):
        """Remove duplicate bidirectional links, keeping the richer data."""
        seen = {}
        for n in self.neighbors:
            key = tuple(sorted([n.local_device, n.neighbor_router_id])) + (n.area,)
            if key not in seen:
                seen[key] = n
            else:
                # Merge interface info if we have both ends
                existing = seen[key]
                if n.local_device != existing.local_device:
                    # This is the reverse direction - we could store both interfaces
                    pass
        return list(seen.values())


def detect_vendor(content: str) -> str:
    """Detect if the output is from Arista or Juniper."""
    if "Neighbor priority is" in content or "instance" in content.split('\n')[0]:
        return "arista"
    elif "Area" in content and "opt" in content:
        return "juniper"
    return "unknown"


def extract_device_name(filename: str) -> str:
    """Extract device name from filename (e.g., 'agg203.iad2.txt' -> 'agg203.iad2')."""
    return Path(filename).stem.replace('.log', '')


def parse_with_ttp(content: str, template: str) -> list:
    """Parse content using TTP template."""
    if not HAS_TTP:
        return []

    parser = ttp(data=content, template=template)
    parser.parse()
    results = parser.result()

    if results and results[0]:
        return results[0][0].get('neighbors', [])
    return []


def parse_juniper_regex(content: str) -> list:
    """Fallback regex parser for Juniper OSPF output."""
    neighbors = []
    # Pattern for neighbor line
    pattern = r'(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s+(Full|2-Way|Down|Init|ExStart)\s+(\d+\.\d+\.\d+\.\d+)'
    area_pattern = r'Area\s+(\d+\.\d+\.\d+\.\d+)'

    lines = content.split('\n')
    current_neighbor = None

    for i, line in enumerate(lines):
        match = re.match(pattern, line.strip())
        if match:
            current_neighbor = {
                'neighbor_address': match.group(1),
                'interface': match.group(2),
                'state': match.group(3),
                'router_id': match.group(4),
            }
        elif current_neighbor and 'Area' in line:
            area_match = re.search(area_pattern, line)
            if area_match:
                current_neighbor['area'] = area_match.group(1)
                neighbors.append(current_neighbor)
                current_neighbor = None

    return neighbors


def parse_arista_regex(content: str) -> list:
    """Fallback regex parser for Arista OSPF output."""
    neighbors = []
    pattern = r'Neighbor\s+(\d+\.\d+\.\d+\.\d+).*interface address\s+(\d+\.\d+\.\d+\.\d+)'
    area_pattern = r'In area\s+(\d+\.\d+\.\d+\.\d+)\s+interface\s+(\S+)'
    state_pattern = r'State is\s+(\w+)'

    blocks = re.split(r'(?=Neighbor\s+\d+\.)', content)

    for block in blocks:
        if not block.strip():
            continue

        neighbor_match = re.search(pattern, block)
        if not neighbor_match:
            continue

        neighbor = {
            'router_id': neighbor_match.group(1),
            'neighbor_address': neighbor_match.group(2),
        }

        area_match = re.search(area_pattern, block)
        if area_match:
            neighbor['area'] = area_match.group(1)
            neighbor['interface'] = area_match.group(2)

        state_match = re.search(state_pattern, block)
        if state_match:
            neighbor['state'] = state_match.group(1)

        if 'area' in neighbor:
            neighbors.append(neighbor)

    return neighbors


def parse_ospf_file(filepath: str, use_ttp: bool = True) -> tuple[str, list]:
    """Parse an OSPF neighbor file and return device name and neighbors."""
    device_name = extract_device_name(filepath)

    with open(filepath, 'r') as f:
        content = f.read()

    vendor = detect_vendor(content)

    if vendor == "juniper":
        if use_ttp and HAS_TTP:
            neighbors = parse_with_ttp(content, JUNIPER_TEMPLATE)
        else:
            neighbors = parse_juniper_regex(content)
    elif vendor == "arista":
        if use_ttp and HAS_TTP:
            neighbors = parse_with_ttp(content, ARISTA_TEMPLATE)
        else:
            neighbors = parse_arista_regex(content)
    else:
        print(f"Warning: Unknown vendor for {filepath}")
        neighbors = []

    return device_name, neighbors


def build_topology(input_dir: str, use_ttp: bool = True) -> OSPFTopology:
    """Build OSPF topology from all files in directory."""
    topology = OSPFTopology()

    for filename in os.listdir(input_dir):
        if not filename.endswith(('.txt', '.log')):
            continue

        filepath = os.path.join(input_dir, filename)
        device_name, neighbors = parse_ospf_file(filepath, use_ttp)

        for n in neighbors:
            neighbor = OSPFNeighbor(
                local_device=device_name,
                local_interface=n.get('interface', ''),
                neighbor_router_id=n.get('router_id', ''),
                neighbor_address=n.get('neighbor_address', ''),
                area=n.get('area', '0.0.0.0'),
                state=n.get('state', 'Unknown'),
                dr=n.get('dr', ''),
                bdr=n.get('bdr', ''),
            )
            topology.add_neighbor(neighbor)

    return topology


def sanitize_node_id(name: str) -> str:
    """Convert device name to valid Mermaid node ID."""
    # Replace dots and hyphens with underscores
    return re.sub(r'[.\-]', '_', name)


def generate_mermaid(topology: OSPFTopology, style: str = "flowchart") -> str:
    """Generate Mermaid diagram from topology."""
    lines = []

    if style == "flowchart":
        lines.append("flowchart TB")
    else:
        lines.append("graph TB")

    # Deduplicate links
    unique_links = topology.deduplicate_links()

    # Group by area
    areas = defaultdict(list)
    for link in unique_links:
        areas[link.area].append(link)

    # Track all devices for styling
    all_devices = set()

    # Generate subgraphs for each area
    for area, links in sorted(areas.items()):
        area_id = f"area_{area.replace('.', '_')}"
        area_label = f"Area {area}"

        lines.append(f"    subgraph {area_id}[\"{area_label}\"]")

        for link in links:
            local_id = sanitize_node_id(link.local_device)
            neighbor_id = sanitize_node_id(link.neighbor_router_id)

            all_devices.add((local_id, link.local_device))
            all_devices.add((neighbor_id, link.neighbor_router_id))

            # Edge label with interface and state
            state_emoji = "✓" if link.state.upper() == "FULL" else "⚠"
            edge_label = f"{link.local_interface}"

            # Use different arrow styles based on state
            if link.state.upper() == "FULL":
                lines.append(
                    f"        {local_id}[\"{link.local_device}\"] <--\"{edge_label}\"--> {neighbor_id}[\"{link.neighbor_router_id}\"]")
            else:
                lines.append(
                    f"        {local_id}[\"{link.local_device}\"] -.\"{edge_label} ({link.state})\".- {neighbor_id}[\"{link.neighbor_router_id}\"]")

        lines.append("    end")

    # Add styling
    lines.append("")
    lines.append("    %% Styling")
    lines.append("    classDef default fill:#e1f5fe,stroke:#01579b,stroke-width:2px")
    lines.append("    classDef agg fill:#fff3e0,stroke:#e65100,stroke-width:2px")
    lines.append("    classDef edge_device fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px")
    lines.append("    classDef tor fill:#f3e5f5,stroke:#4a148c,stroke-width:2px")

    # Apply styles based on device naming conventions
    for node_id, device_name in all_devices:
        if device_name.startswith('agg'):
            lines.append(f"    class {node_id} agg")
        elif device_name.startswith('edge'):
            lines.append(f"    class {node_id} edge_device")
        elif device_name.startswith('tor'):
            lines.append(f"    class {node_id} tor")

    return '\n'.join(lines)


def generate_mermaid_simple(topology: OSPFTopology) -> str:
    """Generate a simpler Mermaid diagram without subgraphs (better compatibility)."""
    lines = ["graph LR"]

    unique_links = topology.deduplicate_links()
    seen_edges = set()

    for link in unique_links:
        local_id = sanitize_node_id(link.local_device)
        neighbor_id = sanitize_node_id(link.neighbor_router_id)

        # Create canonical edge key to avoid duplicates
        edge_key = tuple(sorted([local_id, neighbor_id]))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        if link.state.upper() == "FULL":
            lines.append(f"    {local_id}[{link.local_device}] --- {neighbor_id}[{link.neighbor_router_id}]")
        else:
            lines.append(f"    {local_id}[{link.local_device}] -.- {neighbor_id}[{link.neighbor_router_id}]")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Generate Mermaid diagram from OSPF neighbor data')
    parser.add_argument('--input-dir', '-i', required=True, help='Directory containing OSPF capture files')
    parser.add_argument('--output', '-o', default='ospf_topology.mermaid', help='Output file')
    parser.add_argument('--style', choices=['flowchart', 'simple'], default='flowchart',
                        help='Diagram style (flowchart with subgraphs or simple)')
    parser.add_argument('--no-ttp', action='store_true', help='Use regex parsing instead of TTP')
    parser.add_argument('--json', action='store_true', help='Also output JSON topology data')

    args = parser.parse_args()

    print(f"Parsing OSPF files from: {args.input_dir}")
    topology = build_topology(args.input_dir, use_ttp=not args.no_ttp)

    print(f"Found {len(topology.neighbors)} neighbor relationships")
    print(f"Areas: {list(topology.areas.keys())}")

    if args.style == 'simple':
        mermaid = generate_mermaid_simple(topology)
    else:
        mermaid = generate_mermaid(topology)

    with open(args.output, 'w') as f:
        f.write(mermaid)
    print(f"Mermaid diagram written to: {args.output}")

    if args.json:
        json_output = args.output.replace('.mermaid', '.json')
        with open(json_output, 'w') as f:
            json.dump({
                'neighbors': [
                    {
                        'local': n.local_device,
                        'neighbor': n.neighbor_router_id,
                        'interface': n.local_interface,
                        'area': n.area,
                        'state': n.state
                    }
                    for n in topology.neighbors
                ]
            }, f, indent=2)
        print(f"JSON data written to: {json_output}")


if __name__ == '__main__':
    main()