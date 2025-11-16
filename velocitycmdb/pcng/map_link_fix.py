#!/usr/bin/env python3
"""
Fix Malformed Topology Connections v2

Repairs topology files where connections have incorrect port mappings.
Uses bidirectional peer data and cluster-based pairing to reconstruct connections.

Strategies:
1. Reverse lookup - Find correct remote port from peer's reverse connection
2. Cluster pairing - For equal-count parallel links, pair by sorted interface order
3. Mark unknown - Use placeholder [?] when connection exists but can't be determined

Author: Network Topology Tools
"""
import json
import sys
import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# Try to import enhanced normalizer, fall back to simple version
try:
    from enh_int_normalizer import InterfaceNormalizer as EnhancedNormalizer


    class InterfaceNormalizer:
        """Wrapper for enhanced interface normalizer"""

        @classmethod
        def normalize(cls, iface: str, vendor: Optional[str] = None) -> str:
            if not iface:
                return ""
            return EnhancedNormalizer.normalize(iface).lower()

except ImportError:
    class InterfaceNormalizer:
        """Simple fallback interface normalizer"""

        @staticmethod
        def normalize(iface: str, vendor: Optional[str] = None) -> str:
            if not iface:
                return ""

            iface = str(iface).strip().lower()

            # Juniper - keep as-is
            if re.match(r'^(xe|et|ge|ae|fxp|me|em|irb|lo)-?[\d/:]', iface, re.I):
                return iface

            # Cisco/Arista - normalize to short form
            replacements = [
                (r'tengigabitethernet', 'te'),
                (r'gigabitethernet', 'gi'),
                (r'fastethernet', 'fa'),
                (r'fortygige', 'fo'),
                (r'hundredgige', 'hu'),
                (r'twentyfivegige', 'twe'),
                (r'ethernet', 'eth'),
                (r'port-channel', 'po'),
                (r'management', 'ma'),
                (r'loopback', 'lo'),
                (r'vlan', 'vl'),
            ]

            result = iface
            for pattern, replacement in replacements:
                result = re.sub(f'^{pattern}', replacement, result, flags=re.I)

            return result


class TopologyConnectionFixer:
    """Fix malformed connections in topology JSON"""

    def __init__(self, verbose: bool = False, debug: bool = False,
                 unknown_remote_placeholder: str = "[?]"):
        self.verbose = verbose
        self.debug = debug
        self.unknown_remote_placeholder = unknown_remote_placeholder
        self.stats = {
            'devices_checked': 0,
            'connections_checked': 0,
            'malformed_found': 0,
            'connections_fixed': 0,
            'connections_unfixable': 0,
            'placeholders_set': 0,
            'cluster_repairs': 0
        }
        self.failure_reasons = []

    def _log(self, message: str):
        """Log message if verbose enabled"""
        if self.verbose:
            print(message)

    def is_valid_peer_name(self, peer_name: str) -> bool:
        """
        Check if peer name looks valid (not a parsing artifact).
        Used for warnings only - we keep all peers.
        """
        if not peer_name or not isinstance(peer_name, str):
            return False

        name = peer_name.strip()

        # Too short
        if len(name) < 2:
            return False

        # Single digit or very short number
        if len(name) <= 2 and name.isdigit():
            return False

        # Known junk keywords from parsing
        junk_keywords = ['command', 'error', 'invalid', 'unknown', 'none', 'null']
        if name.lower() in junk_keywords:
            return False

        return True

    def normalize_interface(self, iface: str) -> str:
        """Normalize interface for comparison"""
        return InterfaceNormalizer.normalize(iface)

    def is_malformed_connection(self, connection: List) -> bool:
        """
        Detect if connection is malformed (local == remote port).
        """
        if not isinstance(connection, list) or len(connection) < 2:
            return False

        local = self.normalize_interface(connection[0])
        remote = self.normalize_interface(connection[1])

        return local == remote and local != ""

    def needs_repair(self, connection: List) -> bool:
        """
        Check if connection needs repair.
        Covers: malformed, placeholder, or empty remote.
        """
        if not isinstance(connection, list) or len(connection) < 2:
            return False

        local = self.normalize_interface(connection[0])
        remote = self.normalize_interface(connection[1])

        # Classic malformed
        if local != "" and local == remote:
            return True

        # Placeholder or empty remote
        placeholder = self.normalize_interface(self.unknown_remote_placeholder)
        if remote == "" or (placeholder != "" and remote == placeholder):
            return True

        return False

    def find_correct_remote_port(self, topology: Dict, device: str, peer: str,
                                 local_port: str, debug: bool = False) -> Tuple[Optional[str], str]:
        """
        Find correct remote port by reverse lookup.
        Returns: (correct_remote_port, failure_reason)
        """
        if peer not in topology:
            return None, f"peer '{peer}' not found in topology"

        if 'peers' not in topology[peer]:
            return None, f"peer '{peer}' has no 'peers' section"

        if device not in topology[peer]['peers']:
            return None, f"reverse connection '{peer}' → '{device}' does not exist"

        # Get reverse connections
        reverse_connections = topology[peer]['peers'][device].get('connections', [])

        if not reverse_connections:
            return None, f"reverse connection '{peer}' → '{device}' has no connections"

        local_norm = self.normalize_interface(local_port)

        # Debug output
        if debug:
            self._log(f"      Looking for local_port '{local_port}' (normalized: '{local_norm}')")
            self._log(f"      Reverse connections from {peer} → {device}:")
            for i, rev_conn in enumerate(reverse_connections):
                if isinstance(rev_conn, list) and len(rev_conn) >= 2:
                    self._log(f"        [{i}] [{rev_conn[0]}] → [{rev_conn[1]}] "
                              f"(norm: {self.normalize_interface(rev_conn[1])})")

        # Look for matching reverse connection
        for rev_conn in reverse_connections:
            if not isinstance(rev_conn, list) or len(rev_conn) < 2:
                continue

            rev_local = rev_conn[0]  # peer's local port
            rev_remote = rev_conn[1]  # peer's remote port (should match our local)

            if self.normalize_interface(rev_remote) == local_norm:
                return rev_local, "success"

        return None, f"no matching reverse connection found (checked {len(reverse_connections)} connections)"

    def _iface_sort_key(self, name: str) -> tuple:
        """
        Create sortable key from interface name.
        Supports Cisco (Te1/49) and Juniper (xe-0/0/47) formats.
        """
        if name is None:
            return ("", 0, 0, 0, 0)

        s = str(name).strip().lower()

        # Canonicalize long forms
        if s.startswith("tengigabitethernet"):
            s = "te" + s[18:]
        elif s.startswith("gigabitethernet"):
            s = "gi" + s[15:]
        elif s.startswith("fastethernet"):
            s = "fa" + s[12:]
        elif s.startswith("ethernet"):
            s = "e" + s[8:]

        # Extract type prefix
        t = ""
        idx = 0
        while idx < len(s) and (s[idx].isalpha() or s[idx] == '-'):
            t += s[idx]
            idx += 1

        rest = s[idx:] if idx < len(s) else ""

        # Map type to rank
        type_rank = 50
        if t.startswith("xe"):
            type_rank = 10
        elif t.startswith("et"):
            type_rank = 20
        elif t.startswith("te"):
            type_rank = 30
        elif t.startswith("gi"):
            type_rank = 40
        elif t.startswith("fa"):
            type_rank = 45
        elif t.startswith("e"):
            type_rank = 49

        # Extract up to 4 numeric components
        nums = [0, 0, 0, 0]
        cur = ""
        count = 0
        for ch in rest:
            if ch.isdigit():
                cur += ch
            else:
                if cur and count < 4:
                    try:
                        nums[count] = int(cur)
                    except:
                        nums[count] = 0
                    count += 1
                    cur = ""
        if cur and count < 4:
            try:
                nums[count] = int(cur)
            except:
                nums[count] = 0

        return (type_rank, nums[0], nums[1], nums[2], nums[3])

    def _get_peer_key(self, topology: Dict, a: str, b: str) -> Optional[str]:
        """
        Find peer key allowing for FQDN variations.
        """
        if a not in topology or 'peers' not in topology[a]:
            return None

        peers = topology[a]['peers']

        # Exact match
        if b in peers:
            return b

        # Normalize (strip domain)
        def norm(x: str) -> str:
            if not x:
                return ""
            v = str(x).strip().lower()
            dot = v.find(".")
            return v[:dot] if dot != -1 else v

        target = norm(b)

        # Try normalized match
        for k in peers.keys():
            if norm(k) == target:
                return k

        # Try substring match
        for k in peers.keys():
            nk = norm(k)
            if nk and target and (nk in target or target in nk):
                return k

        return None

    def _attempt_cluster_repair(self, topology: Dict, a: str, b: str) -> bool:
        """
        Cluster-based repair: when both A→B and B→A have equal malformed links,
        pair by sorted interface order.
        Returns True if changes were applied.
        """
        key_ab = self._get_peer_key(topology, a, b)
        key_ba = self._get_peer_key(topology, b, a)

        if not key_ab or not key_ba:
            return False

        block_ab = topology[a]['peers'].get(key_ab, {})
        block_ba = topology[b]['peers'].get(key_ba, {})

        list_ab = block_ab.get('connections', [])
        list_ba = block_ba.get('connections', [])

        if not isinstance(list_ab, list) or not isinstance(list_ba, list):
            return False
        if len(list_ab) == 0 or len(list_ba) == 0:
            return False
        if len(list_ab) != len(list_ba):
            return False

        # Extract local port lists
        locals_ab = []
        locals_ba = []

        for item in list_ab:
            if isinstance(item, list) and len(item) >= 1:
                locals_ab.append(item[0])

        for item in list_ba:
            if isinstance(item, list) and len(item) >= 1:
                locals_ba.append(item[0])

        if len(locals_ab) != len(locals_ba) or len(locals_ab) == 0:
            return False

        # Sort by interface order
        idxs_ab = list(range(len(locals_ab)))
        idxs_ba = list(range(len(locals_ba)))

        # Insertion sort
        for x in range(1, len(idxs_ab)):
            y = x
            while y > 0 and self._iface_sort_key(locals_ab[idxs_ab[y - 1]]) > self._iface_sort_key(
                    locals_ab[idxs_ab[y]]):
                idxs_ab[y - 1], idxs_ab[y] = idxs_ab[y], idxs_ab[y - 1]
                y -= 1

        for x in range(1, len(idxs_ba)):
            y = x
            while y > 0 and self._iface_sort_key(locals_ba[idxs_ba[y - 1]]) > self._iface_sort_key(
                    locals_ba[idxs_ba[y]]):
                idxs_ba[y - 1], idxs_ba[y] = idxs_ba[y], idxs_ba[y - 1]
                y -= 1

        # Pair and repair
        changed = False
        for k in range(len(idxs_ab)):
            idx_ab = idxs_ab[k]
            idx_ba = idxs_ba[k]

            local_ab = list_ab[idx_ab][0]
            local_ba = list_ba[idx_ba][0]

            # Repair A→B
            if len(list_ab[idx_ab]) < 2 or self.needs_repair(list_ab[idx_ab]):
                if len(list_ab[idx_ab]) >= 2:
                    list_ab[idx_ab][1] = local_ba
                else:
                    list_ab[idx_ab].append(local_ba)
                changed = True

            # Repair B→A
            if len(list_ba[idx_ba]) < 2 or self.needs_repair(list_ba[idx_ba]):
                if len(list_ba[idx_ba]) >= 2:
                    list_ba[idx_ba][1] = local_ab
                else:
                    list_ba[idx_ba].append(local_ab)
                changed = True

        if changed:
            block_ab['connections'] = list_ab
            block_ba['connections'] = list_ba

        return changed

    def fix_topology_connections(self, topology: Dict) -> Dict:
        """
        Two-pass connection repair:
        1. Reverse lookup
        2. Cluster-based pairing
        """
        self._log("\nFixing topology connections...")
        self._log("=" * 70)

        pending_pairs = set()

        # Pass 1: Reverse lookup and mark placeholders
        for device, device_data in topology.items():
            if 'peers' not in device_data:
                continue

            self.stats['devices_checked'] += 1
            self._log(f"\nChecking: {device}")

            for peer, peer_data in device_data['peers'].items():
                # Warn about suspicious peer names
                if not self.is_valid_peer_name(peer):
                    self._log(f"  ⚠ Suspicious peer name (parsing artifact?): '{peer}'")

                connections = peer_data.get('connections', [])
                if not connections:
                    continue

                fixed_connections = []
                modified = False

                for conn in connections:
                    self.stats['connections_checked'] += 1

                    if not isinstance(conn, list) or len(conn) < 2:
                        fixed_connections.append(conn)
                        continue

                    local_port = conn[0]
                    remote_port = conn[1]

                    if self.needs_repair(conn):
                        self.stats['malformed_found'] += 1
                        self._log(f"  ✗ Needs repair: {device}[{local_port}] → {peer}[{remote_port}]")

                        # Try reverse lookup
                        correct_remote, reason = self.find_correct_remote_port(
                            topology, device, peer, local_port, debug=self.debug
                        )

                        if correct_remote:
                            fixed_conn = [local_port, correct_remote]
                            fixed_connections.append(fixed_conn)
                            self.stats['connections_fixed'] += 1
                            self._log(f"    ✓ Fixed: {device}[{local_port}] → {peer}[{correct_remote}]")
                            modified = True
                        else:
                            # Mark with placeholder
                            fixed_conn = [local_port, self.unknown_remote_placeholder]
                            fixed_connections.append(fixed_conn)
                            self.stats['placeholders_set'] += 1
                            self.stats['connections_unfixable'] += 1
                            self._log(f"    ⚠ Cannot fix now: {reason}")
                            self.failure_reasons.append({
                                'device': device,
                                'peer': peer,
                                'connection': [local_port, remote_port],
                                'reason': reason
                            })
                            modified = True
                            pending_pairs.add((device, peer))
                    else:
                        fixed_connections.append(conn)

                if modified:
                    peer_data['connections'] = fixed_connections

        # Pass 2: Cluster repair
        if pending_pairs:
            self._log("\nSecond pass: cluster-based pairing...")
            for a, b in pending_pairs:
                changed = self._attempt_cluster_repair(topology, a, b)
                if changed:
                    self._log(f"    ✓ Cluster repair applied: {a} ↔ {b}")
                    self.stats['cluster_repairs'] += 1

        return topology

    def print_summary(self):
        """Print fix summary"""
        print(f"\n{'=' * 70}")
        print("CONNECTION FIX SUMMARY")
        print(f"{'=' * 70}")
        print(f"Devices checked:          {self.stats['devices_checked']}")
        print(f"Connections checked:      {self.stats['connections_checked']}")
        print(f"Malformed found:          {self.stats['malformed_found']}")
        print(f"Successfully fixed:       {self.stats['connections_fixed']} (reverse lookup)")
        print(f"Cluster repairs:          {self.stats['cluster_repairs']} (sorted pairing)")
        print(f"Could not fix:            {self.stats['connections_unfixable']}")
        print(f"Unknown placeholders set: {self.stats['placeholders_set']}")

        total_fixed = self.stats['connections_fixed'] + self.stats['cluster_repairs']
        if self.stats['malformed_found'] > 0:
            fix_rate = (total_fixed / self.stats['malformed_found'] * 100.0)
            print(f"Total recovery rate:      {fix_rate:.1f}%")

        if self.failure_reasons:
            print(f"\n{'=' * 70}")
            print("FAILURE REASONS (before cluster repair)")
            print(f"{'=' * 70}")

            reason_counts = {}
            for failure in self.failure_reasons:
                reason = failure['reason']
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            sorted_items = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)

            for reason, count in sorted_items:
                print(f"{count:3d}  {reason}")

            if self.debug and self.failure_reasons:
                print(f"\nFirst 10 examples:")
                for i, failure in enumerate(self.failure_reasons[:10], 1):
                    print(f"  {i}. {failure['device']} → {failure['peer']}: {failure['connection']}")
                    print(f"     Reason: {failure['reason']}")

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
        description='Fix malformed connections in topology JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fix topology file (creates backup)
  python map_link_fix_v2.py topology.json

  # Specify output file
  python map_link_fix_v2.py topology.json -o topology_fixed.json

  # Dry run
  python map_link_fix_v2.py topology.json --dry-run -v

  # Debug mode
  python map_link_fix_v2.py topology.json -v -d
        """
    )

    parser.add_argument('input', help='Input topology JSON file')
    parser.add_argument('-o', '--output', help='Output file (default: overwrite input)')
    parser.add_argument('--no-backup', action='store_true', help='Do not create backup file')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-d', '--debug', action='store_true', help='Debug output')
    parser.add_argument('--unknown-remote', default='[?]',
                        help="Placeholder for unknown remote ports (default: '[?]')")

    args = parser.parse_args()

    # Validate input
    input_file = Path(args.input)
    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    output_file = Path(args.output) if args.output else input_file

    print(f"Topology Connection Fixer v2")
    print(f"{'=' * 70}")
    print(f"Input:  {input_file}")
    print(f"Output: {output_file}")
    if args.dry_run:
        print(f"Mode:   DRY RUN")
    print()

    # Load topology
    try:
        with open(input_file, 'r') as f:
            topology = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)

    if not isinstance(topology, dict):
        print("Error: Topology must be a JSON object")
        sys.exit(1)

    # Create backup
    backup_file = None
    if not args.dry_run and not args.no_backup and not args.output:
        backup_file = create_backup(input_file)
        print(f"Created backup: {backup_file}\n")

    # Fix connections
    fixer = TopologyConnectionFixer(
        verbose=args.verbose,
        debug=args.debug,
        unknown_remote_placeholder=args.unknown_remote
    )
    fixed_topology = fixer.fix_topology_connections(topology)

    # Print summary
    fixer.print_summary()

    # Save results
    if not args.dry_run:
        total_changes = (fixer.stats['connections_fixed'] +
                         fixer.stats['cluster_repairs'] +
                         fixer.stats['placeholders_set'])
        if total_changes > 0:
            try:
                with open(output_file, 'w') as f:
                    json.dump(fixed_topology, f, indent=2)
                print(f"✓ Saved fixed topology: {output_file}")
                if fixer.stats['connections_fixed'] > 0:
                    print(f"  - {fixer.stats['connections_fixed']} connections fixed (reverse lookup)")
                if fixer.stats['cluster_repairs'] > 0:
                    print(f"  - {fixer.stats['cluster_repairs']} device pairs cluster-repaired")
                if fixer.stats['placeholders_set'] > 0:
                    print(f"  - {fixer.stats['placeholders_set']} connections marked as [?]")
            except Exception as e:
                print(f"Error writing output: {e}")
                if backup_file:
                    print(f"Original backed up at: {backup_file}")
                sys.exit(1)
        else:
            print("No fixes applied - file not modified")
    else:
        print("DRY RUN: No files were modified")

    if fixer.stats['connections_unfixable'] > 0:
        print(f"\n⚠️  Warning: {fixer.stats['connections_unfixable']} connections could not be fixed")
        print("These may require manual inspection or re-running the topology builder")

    print(f"\n{'=' * 70}")
    print("COMPLETE")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()