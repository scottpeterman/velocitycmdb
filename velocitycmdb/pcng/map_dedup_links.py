#!/usr/bin/env python3
"""
Topology Link Deduplication Tool

Removes duplicate connections in topology JSON files created by lldp_to_topology.py
or similar tools. Handles both within-peer and cross-peer duplicate detection.

Features:
- Removes exact duplicate connections within same peer relationship
- Detects and removes bidirectional duplicates (A->B, B->A with same ports)
- Preserves topology structure and metadata
- Creates backup before modification
- Detailed reporting of changes
"""
import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict


class TopologyDeduplicator:
    """Deduplicate connections in topology JSON"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.stats = {
            'devices_processed': 0,
            'peer_relationships': 0,
            'total_connections_before': 0,
            'total_connections_after': 0,
            'duplicates_removed': 0,
            'bidirectional_duplicates': 0
        }

    def _log(self, message: str):
        """Log if verbose"""
        if self.verbose:
            print(message)

    def normalize_interface(self, interface: str) -> str:
        """
        Normalize interface name for comparison
        Handles case variations and whitespace
        """
        if not interface:
            return ""
        return str(interface).strip().lower()

    def create_connection_key(self, local_port: str, remote_port: str) -> Tuple[str, str]:
        """Create normalized connection key for comparison"""
        return (
            self.normalize_interface(local_port),
            self.normalize_interface(remote_port)
        )

    def deduplicate_peer_connections(self, connections: List) -> Tuple[List, int]:
        """
        Remove EXACT duplicate connections within a single peer relationship
        Only removes if the EXACT same port pair appears multiple times
        Returns (deduplicated_list, num_duplicates_removed)
        """
        if not connections:
            return [], 0

        seen = set()
        deduplicated = []
        duplicates = 0

        for conn in connections:
            if not isinstance(conn, list) or len(conn) < 2:
                # Keep malformed connections as-is
                deduplicated.append(conn)
                continue

            local_port = conn[0]
            remote_port = conn[1]

            # Create normalized key - this identifies the exact port pair
            conn_key = self.create_connection_key(local_port, remote_port)

            if conn_key not in seen:
                seen.add(conn_key)
                deduplicated.append(conn)
            else:
                # This is a true duplicate - exact same ports listed twice
                duplicates += 1
                self._log(f"    Removed exact duplicate: {local_port} <-> {remote_port}")

        return deduplicated, duplicates

    def find_bidirectional_duplicates(self, topology: Dict) -> Set[Tuple]:
        """
        Find bidirectional duplicate connections across the topology
        Returns set of (device1, device2, port1, port2) tuples to remove
        """
        # Build connection map: (device_a, device_b, port_a, port_b) -> count
        connection_map = defaultdict(int)

        for device, device_data in topology.items():
            if 'peers' not in device_data:
                continue

            for peer, peer_data in device_data['peers'].items():
                connections = peer_data.get('connections', [])

                for conn in connections:
                    if not isinstance(conn, list) or len(conn) < 2:
                        continue

                    local_port = conn[0]
                    remote_port = conn[1]

                    # Normalize for comparison
                    local_norm = self.normalize_interface(local_port)
                    remote_norm = self.normalize_interface(remote_port)

                    # Create canonical key (alphabetically sorted devices)
                    if device < peer:
                        key = (device, peer, local_norm, remote_norm)
                    else:
                        key = (peer, device, remote_norm, local_norm)

                    connection_map[key] += 1

        # Find duplicates (connections that appear more than once)
        duplicates = set()
        for key, count in connection_map.items():
            if count > 1:
                duplicates.add(key)

        return duplicates

    def remove_bidirectional_duplicates(self, topology: Dict) -> int:
        """
        Remove bidirectional duplicate connections
        Keep only one direction (the one from alphabetically first device)
        """
        duplicates = self.find_bidirectional_duplicates(topology)

        if not duplicates:
            return 0

        removed_count = 0

        for dup in duplicates:
            device_a, device_b, port_a, port_b = dup

            # Keep connection from alphabetically first device
            # Remove from alphabetically second device
            device_to_clean = device_b if device_a < device_b else device_a
            peer_to_check = device_a if device_a < device_b else device_b

            if device_to_clean not in topology:
                continue
            if peer_to_check not in topology[device_to_clean]['peers']:
                continue

            peer_data = topology[device_to_clean]['peers'][peer_to_check]
            connections = peer_data.get('connections', [])

            # Find and remove the duplicate connection
            original_len = len(connections)

            if device_to_clean == device_a:
                target_local, target_remote = port_a, port_b
            else:
                target_local, target_remote = port_b, port_a

            # Filter out the duplicate
            filtered = []
            for conn in connections:
                if not isinstance(conn, list) or len(conn) < 2:
                    filtered.append(conn)
                    continue

                local_norm = self.normalize_interface(conn[0])
                remote_norm = self.normalize_interface(conn[1])

                if local_norm == target_local and remote_norm == target_remote:
                    # This is the duplicate, skip it
                    self._log(f"  Removing bidirectional duplicate: "
                              f"{device_to_clean}[{conn[0]}] <-> {peer_to_check}[{conn[1]}]")
                    removed_count += 1
                else:
                    filtered.append(conn)

            peer_data['connections'] = filtered

        return removed_count

    def deduplicate_topology(self, topology: Dict) -> Dict:
        """
        Deduplicate all connections in topology
        Returns modified topology
        """
        self._log("\nDeduplicating topology...")
        self._log("=" * 70)

        # Phase 1: Deduplicate within each peer relationship
        for device, device_data in topology.items():
            if 'peers' not in device_data:
                continue

            self.stats['devices_processed'] += 1
            self._log(f"\nProcessing: {device}")

            for peer, peer_data in device_data['peers'].items():
                connections = peer_data.get('connections', [])

                if not connections:
                    continue

                self.stats['peer_relationships'] += 1
                original_count = len(connections)
                self.stats['total_connections_before'] += original_count

                # Deduplicate connections
                deduplicated, num_removed = self.deduplicate_peer_connections(connections)

                peer_data['connections'] = deduplicated
                self.stats['total_connections_after'] += len(deduplicated)
                self.stats['duplicates_removed'] += num_removed

                if num_removed > 0:
                    self._log(f"  {peer}: {original_count} -> {len(deduplicated)} "
                              f"({num_removed} duplicates removed)")

        # Phase 2: Remove bidirectional duplicates
        self._log("\nChecking for bidirectional duplicates...")
        bidir_removed = self.remove_bidirectional_duplicates(topology)
        self.stats['bidirectional_duplicates'] = bidir_removed
        self.stats['total_connections_after'] -= bidir_removed

        return topology

    def print_summary(self):
        """Print deduplication summary"""
        print(f"\n{'=' * 70}")
        print("DEDUPLICATION SUMMARY")
        print(f"{'=' * 70}")
        print(f"Devices processed:           {self.stats['devices_processed']}")
        print(f"Peer relationships:          {self.stats['peer_relationships']}")
        print(f"Connections before:          {self.stats['total_connections_before']}")
        print(f"Connections after:           {self.stats['total_connections_after']}")
        print(f"Within-peer duplicates:      {self.stats['duplicates_removed']}")
        print(f"Bidirectional duplicates:    {self.stats['bidirectional_duplicates']}")
        print(
            f"Total duplicates removed:    {self.stats['duplicates_removed'] + self.stats['bidirectional_duplicates']}")

        if self.stats['total_connections_before'] > 0:
            reduction = ((self.stats['duplicates_removed'] + self.stats['bidirectional_duplicates']) /
                         self.stats['total_connections_before'] * 100)
            print(f"Reduction:                   {reduction:.1f}%")

        print(f"{'=' * 70}\n")


def create_backup(file_path: Path) -> Path:
    """Create backup of original file"""
    backup_path = file_path.with_suffix(file_path.suffix + '.backup')
    counter = 1

    while backup_path.exists():
        backup_path = file_path.with_suffix(f'{file_path.suffix}.backup{counter}')
        counter += 1

    backup_path.write_text(file_path.read_text())
    return backup_path


def main():
    parser = argparse.ArgumentParser(
        description='Deduplicate connections in topology JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deduplicate topology file (creates backup)
  python map_link_dedup.py topology.json

  # Specify output file (input preserved)
  python map_link_dedup.py topology.json -o topology_clean.json

  # No backup (dangerous!)
  python map_link_dedup.py topology.json --no-backup

  # Verbose output
  python map_link_dedup.py topology.json -v

  # Dry run (show what would be removed)
  python map_link_dedup.py topology.json --dry-run
        """
    )

    parser.add_argument('input',
                        help='Input topology JSON file')

    parser.add_argument('-o', '--output',
                        help='Output file (default: overwrite input)')

    parser.add_argument('--no-backup',
                        action='store_true',
                        help='Do not create backup file')

    parser.add_argument('--dry-run',
                        action='store_true',
                        help='Show what would be removed without modifying files')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Enable verbose output')

    args = parser.parse_args()

    # Validate input
    input_file = Path(args.input)
    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Determine output
    output_file = Path(args.output) if args.output else input_file

    print(f"Topology Link Deduplication Tool")
    print(f"{'=' * 70}")
    print(f"Input:  {input_file}")
    print(f"Output: {output_file}")

    if args.dry_run:
        print(f"Mode:   DRY RUN (no changes will be made)")
    print()

    # Load topology
    try:
        with open(input_file, 'r') as f:
            topology = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading input file: {e}")
        sys.exit(1)

    # Validate topology structure
    if not isinstance(topology, dict):
        print("Error: Topology file must contain a JSON object")
        sys.exit(1)

    # Create backup if needed
    backup_file = None
    if not args.dry_run and not args.no_backup and args.output is None:
        backup_file = create_backup(input_file)
        print(f"Created backup: {backup_file}\n")

    # Deduplicate
    deduplicator = TopologyDeduplicator(verbose=args.verbose)
    deduplicated_topology = deduplicator.deduplicate_topology(topology)

    # Print summary
    deduplicator.print_summary()

    # Save results
    if not args.dry_run:
        try:
            with open(output_file, 'w') as f:
                json.dump(deduplicated_topology, f, indent=2)
            print(f"✓ Saved deduplicated topology: {output_file}")
        except Exception as e:
            print(f"Error writing output file: {e}")
            if backup_file:
                print(f"Original file backed up at: {backup_file}")
            sys.exit(1)
    else:
        print("DRY RUN: No files were modified")

    print(f"\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()