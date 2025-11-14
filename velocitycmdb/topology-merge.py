#!/usr/bin/env python3
"""
CLI tool for merging multiple network topology JSON files.
Extracts merge functionality from the GUI TopologyMergeDialog for automation use.
"""

import argparse
import json
import copy
import sys
from pathlib import Path
from typing import Dict, List, Optional
import math
import networkx as nx
import matplotlib.pyplot as plt


class TopologyMerger:
    """CLI topology merging functionality extracted from GUI version."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def log(self, message: str, force: bool = False):
        """Log message if verbose mode is enabled or force is True."""
        if self.verbose or force:
            print(f"[topology-merge] {message}")

    def validate_topology_file(self, file_path: Path) -> bool:
        """Validate that a file contains valid topology data."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                self.log(f"ERROR: {file_path.name} is not a valid JSON object", force=True)
                return False

            # Basic validation - check for expected topology structure
            for node_name, node_data in data.items():
                if not isinstance(node_data, dict):
                    self.log(f"ERROR: Node {node_name} in {file_path.name} is not an object", force=True)
                    return False

                if 'node_details' not in node_data:
                    self.log(f"WARNING: Node {node_name} missing 'node_details'")

                if 'peers' not in node_data:
                    self.log(f"WARNING: Node {node_name} missing 'peers'")

            self.log(f"Validated {file_path.name}: {len(data)} nodes")
            return True

        except json.JSONDecodeError as e:
            self.log(f"ERROR: {file_path.name} contains invalid JSON: {e}", force=True)
            return False
        except Exception as e:
            self.log(f"ERROR: Could not validate {file_path.name}: {e}", force=True)
            return False

    def merge_maps(self, file1_data: Dict, file2_data: Dict) -> Dict:
        """
        Merge two topology maps while preserving the exact schema.
        Based on the GUI merge_maps method.
        """
        combined_data = copy.deepcopy(file1_data)

        for node, details in file2_data.items():
            if node in combined_data:
                # For existing nodes, merge peers and their connections
                for peer, peer_details in details['peers'].items():
                    if peer in combined_data[node]['peers']:
                        # Merge connections for existing peers
                        existing_connections = combined_data[node]['peers'][peer]['connections']
                        new_connections = peer_details['connections']

                        # Add only unique connections
                        for conn in new_connections:
                            if conn not in existing_connections:
                                existing_connections.append(conn)
                                self.log(f"Added connection {conn} for {node} -> {peer}")
                    else:
                        # Add new peers from file2
                        combined_data[node]['peers'][peer] = peer_details
                        self.log(f"Added new peer {peer} to node {node}")
            else:
                # Add new nodes from file2
                combined_data[node] = details
                self.log(f"Added new node {node}")

        return combined_data

    def merge_multiple_files(self, file_paths: List[Path]) -> Dict:
        """Merge multiple topology files sequentially."""
        if not file_paths:
            raise ValueError("No files provided for merging")

        # Validate all files first
        self.log("Validating input files...")
        for file_path in file_paths:
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            if not self.validate_topology_file(file_path):
                raise ValueError(f"Invalid topology file: {file_path}")

        # Start with first file
        self.log(f"Loading base file: {file_paths[0].name}")
        with open(file_paths[0], 'r') as f:
            merged_data = json.load(f)

        base_node_count = len(merged_data)
        self.log(f"Base topology: {base_node_count} nodes")

        # Merge remaining files
        for file_path in file_paths[1:]:
            self.log(f"Merging file: {file_path.name}")
            with open(file_path, 'r') as f:
                file_data = json.load(f)

            before_count = len(merged_data)
            merged_data = self.merge_maps(merged_data, file_data)
            after_count = len(merged_data)

            self.log(f"Merged {file_path.name}: {len(file_data)} nodes -> "
                     f"total now {after_count} nodes (+{after_count - before_count} new)")

        return merged_data

    def calculate_topology_stats(self, topology_data: Dict) -> Dict:
        """Calculate statistics about the merged topology."""
        total_nodes = len(topology_data)
        total_connections = 0
        platforms = {}

        for node, data in topology_data.items():
            # Count connections
            for peer_data in data.get('peers', {}).values():
                total_connections += len(peer_data.get('connections', []))

            # Count platforms
            platform = data.get('node_details', {}).get('platform', 'Unknown')
            platforms[platform] = platforms.get(platform, 0) + 1

        # Connections are counted twice (once for each end), so divide by 2
        unique_connections = total_connections // 2

        return {
            'total_nodes': total_nodes,
            'unique_connections': unique_connections,
            'platforms': platforms
        }

    def create_network_svg(self, map_data: Dict, output_path: Path,
                           dark_mode: bool = True) -> bool:
        """
        Create an SVG visualization of the network map.
        Simplified version of the GUI method.
        """
        try:
            # Create NetworkX graph
            G = nx.Graph()

            # Add nodes and edges
            added_edges = set()
            for node, data in map_data.items():
                G.add_node(node,
                           ip=data.get('node_details', {}).get('ip', ''),
                           platform=data.get('node_details', {}).get('platform', ''))

                # Add edges from peer connections
                for peer, peer_data in data.get('peers', {}).items():
                    if peer in map_data:
                        edge_key = tuple(sorted([node, peer]))
                        if edge_key not in added_edges:
                            connections = peer_data.get('connections', [])
                            if connections:
                                local_port, remote_port = connections[0]
                                label = f"{local_port} - {remote_port}"
                            else:
                                label = ""
                            G.add_edge(node, peer, connection=label)
                            added_edges.add(edge_key)

            # Set up colors based on mode
            if dark_mode:
                bg_color = '#1C1C1C'
                edge_color = '#FFFFFF'
                node_color = '#4B77BE'
                font_color = 'white'
                node_edge_color = '#FFFFFF'
            else:
                bg_color = 'white'
                edge_color = 'gray'
                node_color = 'lightblue'
                font_color = 'black'
                node_edge_color = 'black'

            # Create figure
            plt.figure(figsize=(20, 15))
            plt.gca().set_facecolor(bg_color)
            plt.gcf().set_facecolor(bg_color)

            # Calculate layout
            pos = self._calculate_balloon_layout(G)

            # Draw edges with labels
            for edge in G.edges():
                node1, node2 = edge
                pos1 = pos[node1]
                pos2 = pos[node2]

                # Draw edge
                plt.plot([pos1[0], pos2[0]], [pos1[1], pos2[1]],
                         color=edge_color, linewidth=1.0, alpha=0.6)

                # Add edge label at midpoint
                connection = G.edges[edge].get('connection', '')
                if connection:
                    mid_x = (pos1[0] + pos2[0]) / 2
                    mid_y = (pos1[1] + pos2[1]) / 2
                    plt.text(mid_x, mid_y, connection,
                             horizontalalignment='center', verticalalignment='center',
                             fontsize=6, color=font_color,
                             bbox=dict(facecolor=bg_color, edgecolor='none', alpha=0.7, pad=0.2),
                             zorder=1)

            # Draw nodes
            node_width = 0.1
            node_height = 0.03
            for node, (x, y) in pos.items():
                plt.gca().add_patch(plt.Rectangle((x - node_width / 2, y - node_height / 2),
                                                  node_width, node_height,
                                                  facecolor=node_color, edgecolor=node_edge_color,
                                                  linewidth=1.0, zorder=2))

                plt.text(x, y, node, horizontalalignment='center', verticalalignment='center',
                         fontsize=8, color=font_color,
                         bbox=dict(facecolor=node_color, edgecolor='none', pad=0.5),
                         zorder=3)

            # Remove axes and adjust limits
            plt.axis('off')
            margin = 0.1
            x_values = [x for x, y in pos.values()]
            y_values = [y for x, y in pos.values()]
            plt.xlim(min(x_values) - margin, max(x_values) + margin)
            plt.ylim(min(y_values) - margin, max(y_values) + margin)

            # Save as SVG
            plt.savefig(output_path, format='svg', bbox_inches='tight',
                        pad_inches=0.1, facecolor=bg_color, edgecolor='none',
                        transparent=False)
            plt.close()

            return True

        except Exception as e:
            self.log(f"ERROR: Could not create SVG: {e}", force=True)
            return False

    def _calculate_balloon_layout(self, G, scale: float = 1.0) -> Dict:
        """Calculate balloon layout positions for network visualization."""
        if len(G.nodes()) == 0:
            return {}

        # Find root node (core switch/router)
        core_nodes = [node for node in G.nodes() if 'core' in node.lower()]
        if core_nodes:
            root = max(core_nodes, key=lambda x: G.degree(x))
        else:
            root = max(G.nodes(), key=lambda x: G.degree(x))

        # Initialize positions
        pos = {root: (0, 0)}

        # Position hub nodes
        hub_nodes = {node for node in G.nodes() if G.degree(node) >= 2 and node != root}
        if hub_nodes:
            angle_increment = 2 * math.pi / len(hub_nodes)
            hub_radius = 1.0 * scale
            for i, hub in enumerate(hub_nodes):
                angle = i * angle_increment
                pos[hub] = (hub_radius * math.cos(angle), hub_radius * math.sin(angle))

        # Position leaf nodes around their hubs
        leaf_radius = 0.5 * scale
        leaf_nodes = set(G.nodes()) - {root} - hub_nodes
        for hub in hub_nodes:
            children = [n for n in G.neighbors(hub) if n in leaf_nodes]
            if children:
                child_angle_increment = 2 * math.pi / len(children)
                for j, child in enumerate(children):
                    angle = j * child_angle_increment
                    pos[child] = (
                        pos[hub][0] + leaf_radius * math.cos(angle),
                        pos[hub][1] + leaf_radius * math.sin(angle)
                    )
                    leaf_nodes.discard(child)

        # Position any remaining nodes
        if leaf_nodes:
            remaining_radius = 1.5 * (1.0 * scale)
            angle_increment = 2 * math.pi / len(leaf_nodes)
            for i, node in enumerate(leaf_nodes):
                angle = i * angle_increment
                pos[node] = (
                    remaining_radius * math.cos(angle),
                    remaining_radius * math.sin(angle)
                )

        return pos


def create_additional_formats(json_file: Path, output_dir: Path, map_name: str):
    """
    Create additional output formats (GraphML, Draw.io).
    This would import from secure_cartography.map_json_platform if available.
    """
    try:
        from secure_cartography.map_json_platform import create_network_diagrams
        create_network_diagrams(
            json_file=str(json_file),
            output_dir=str(output_dir),
            map_name=map_name
        )
        return True
    except ImportError:
        print("[topology-merge] WARNING: secure_cartography not available - skipping GraphML/Draw.io generation")
        return False
    except Exception as e:
        print(f"[topology-merge] WARNING: Could not create additional formats: {e}")
        return False


def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="Merge multiple network topology JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  topology-merge.py site1.json site2.json -o merged.json
  topology-merge.py *.json -o complete_topology.json --format all
  topology-merge.py file1.json file2.json -o out.json --validate --verbose
        """.strip()
    )

    parser.add_argument(
        'files',
        nargs='+',
        help='Topology JSON files to merge'
    )

    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output file path for merged topology'
    )

    parser.add_argument(
        '-f', '--format',
        choices=['json', 'svg', 'graphml', 'drawio', 'all'],
        default='json',
        help='Output format(s) to generate (default: json)'
    )

    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate topology consistency after merge'
    )

    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show detailed statistics about merged topology'
    )

    parser.add_argument(
        '--dark-mode',
        action='store_true',
        default=True,
        help='Use dark mode for SVG visualization (default: true)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed progress information'
    )

    args = parser.parse_args()

    try:
        # Initialize merger
        merger = TopologyMerger(verbose=args.verbose)

        # Convert file arguments to Path objects
        input_files = [Path(f) for f in args.files]
        output_file = Path(args.output)

        # Ensure output directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Merge topologies
        merger.log("Starting topology merge operation...")
        merged_topology = merger.merge_multiple_files(input_files)

        # Save merged JSON
        merger.log(f"Saving merged topology to: {output_file}")
        with open(output_file, 'w') as f:
            json.dump(merged_topology, f, indent=4)

        # Generate statistics
        stats = merger.calculate_topology_stats(merged_topology)
        print(f"\nMerge completed successfully!")
        print(f"Total nodes: {stats['total_nodes']}")
        print(f"Total connections: {stats['unique_connections']}")

        if args.stats:
            print(f"\nPlatform breakdown:")
            for platform, count in sorted(stats['platforms'].items()):
                print(f"  {platform}: {count} devices")

        # Generate additional formats
        output_dir = output_file.parent
        map_name = output_file.stem

        if args.format in ['svg', 'all']:
            svg_path = output_dir / f"{map_name}.svg"
            merger.log(f"Generating SVG visualization: {svg_path}")
            if merger.create_network_svg(merged_topology, svg_path, args.dark_mode):
                print(f"Generated SVG: {svg_path}")
            else:
                print("WARNING: SVG generation failed")

        if args.format in ['graphml', 'drawio', 'all']:
            merger.log("Generating additional diagram formats...")
            if create_additional_formats(output_file, output_dir, map_name):
                if args.format in ['graphml', 'all']:
                    print(f"Generated GraphML: {output_dir / f'{map_name}.graphml'}")
                if args.format in ['drawio', 'all']:
                    print(f"Generated Draw.io: {output_dir / f'{map_name}.drawio'}")

        # Validation
        if args.validate:
            merger.log("Validating merged topology...")
            if merger.validate_topology_file(output_file):
                print("Topology validation: PASSED")
            else:
                print("Topology validation: FAILED")
                return 1

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())