#!/usr/bin/env python3
"""
BGP Peer Migration Analyzer
Analyzes Juniper config to plan individual BGP peer migrations to Arista
"""

import re
import ipaddress
from collections import defaultdict
from typing import Set, Dict, List, Tuple, Optional
import argparse
import sys
# from app.utils.bgp_migration import JuniperToAristaMigration



class JuniperToAristaMigration:
    def __init__(self, config_file: str):
        self.config_file = config_file
        self.config_lines = []
        self.global_asn = None
        self.load_config()
        self.detect_global_asn()

    def load_config(self):
        """Load configuration file into memory"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_lines = [line.strip() for line in f.readlines() if line.strip()]
        except FileNotFoundError:
            print(f"❌ ERROR: Config file '{self.config_file}' not found")
            sys.exit(1)
        except Exception as e:
            print(f"❌ ERROR: Failed to read config file: {e}")
            sys.exit(1)

    def detect_global_asn(self):
        """Detect the global ASN from routing-options"""
        for line in self.config_lines:
            if 'routing-options autonomous-system' in line:
                match = re.search(r'autonomous-system (\d+)', line)
                if match:
                    self.global_asn = match.group(1)
                    break

    def find_bgp_peer(self, peer_ip: str) -> Dict:
        """Find all BGP configuration for a specific peer"""
        peer_info = {
            'neighbor_lines': [],
            'group_name': None,
            'group_config': [],
            'peer_as': None,
            'local_as': None,
            'import_policies': [],
            'export_policies': [],
            'group_type': None,
            'other_neighbors': [],
            'hold_time': None,
            'peer_description': None,
            'bfd_enabled': False,
            'authentication': None,
        }

        # Find the BGP group this peer belongs to
        for line in self.config_lines:
            if f'neighbor {peer_ip}' in line and 'protocols bgp group' in line:
                match = re.search(r'protocols bgp group (\S+)', line)
                if match:
                    peer_info['group_name'] = match.group(1)
                    peer_info['neighbor_lines'].append(line)

                    # Check for neighbor-specific configurations
                    if 'hold-time' in line:
                        ht_match = re.search(r'hold-time (\d+)', line)
                        if ht_match:
                            peer_info['hold_time'] = ht_match.group(1)

                    if 'description' in line:
                        desc_match = re.search(r'description (.+?)(?:\s+\w+\s+|$)', line)
                        if desc_match:
                            peer_info['peer_description'] = desc_match.group(1).strip('"')

        if not peer_info['group_name']:
            return peer_info

        # Get all group configuration
        group_name = peer_info['group_name']
        for line in self.config_lines:
            if f'protocols bgp group {group_name}' in line:
                peer_info['group_config'].append(line)

                # Extract key parameters
                # Check for neighbor-specific peer-as (higher priority)
                if 'neighbor' in line and f'neighbor {peer_ip}' in line and 'peer-as' in line:
                    match = re.search(r'peer-as (\d+)', line)
                    if match:
                        peer_info['peer_as'] = match.group(1)
                # Check for group-level peer-as (lower priority, only if not already set)
                elif 'peer-as' in line and 'neighbor' not in line and not peer_info['peer_as']:
                    match = re.search(r'peer-as (\d+)', line)
                    if match:
                        peer_info['peer_as'] = match.group(1)

                if 'local-as' in line:
                    match = re.search(r'local-as (\d+)', line)
                    if match:
                        peer_info['local_as'] = match.group(1)

                if 'type ' in line:
                    match = re.search(r'type (\S+)', line)
                    if match:
                        peer_info['group_type'] = match.group(1)

                if 'bfd-liveness-detection' in line:
                    peer_info['bfd_enabled'] = True

                if 'authentication-key' in line or 'authentication-algorithm' in line:
                    peer_info['authentication'] = 'configured'

                # Parse import policies - handle multi-policy syntax
                if ' import ' in line and 'import-rib' not in line:
                    # Match: import [ policy1 policy2 ] or import policy1
                    if '[' in line:
                        policies_match = re.search(r'import \[(.*?)\]', line)
                        if policies_match:
                            policies = policies_match.group(1).split()
                            peer_info['import_policies'].extend(policies)
                    else:
                        match = re.search(r'import (\S+)', line)
                        if match and 'import' not in line.split()[-1]:
                            peer_info['import_policies'].append(match.group(1))

                # Parse export policies - handle multi-policy syntax
                if ' export ' in line and 'export-rib' not in line:
                    if '[' in line:
                        policies_match = re.search(r'export \[(.*?)\]', line)
                        if policies_match:
                            policies = policies_match.group(1).split()
                            peer_info['export_policies'].extend(policies)
                    else:
                        match = re.search(r'export (\S+)', line)
                        if match and 'export' not in line.split()[-1]:
                            peer_info['export_policies'].append(match.group(1))

                # Find other neighbors in the group
                if 'neighbor ' in line and peer_ip not in line:
                    match = re.search(r'neighbor (\d+\.\d+\.\d+\.\d+)', line)
                    if match:
                        peer_info['other_neighbors'].append(match.group(1))

        # Deduplicate policies and neighbors
        peer_info['import_policies'] = list(dict.fromkeys(peer_info['import_policies']))
        peer_info['export_policies'] = list(dict.fromkeys(peer_info['export_policies']))
        peer_info['other_neighbors'] = sorted(set(peer_info['other_neighbors']))

        # If peer-as not explicitly set but group type is internal, infer peer-as = local ASN
        if not peer_info['peer_as'] and peer_info['group_type'] == 'internal':
            peer_info['peer_as'] = self.global_asn

        return peer_info

    def find_interface_for_peer(self, peer_ip: str) -> Tuple[
        Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Find the interface, VLAN, local IP, and VLAN ID for reaching this peer"""
        try:
            peer_net = ipaddress.ip_address(peer_ip)
        except ValueError:
            return None, None, None, None

        # First, check for regular routed interfaces (ae, xe, et, etc.) with direct IP addresses
        for line in self.config_lines:
            # Match: set interfaces ae102 unit 0 family inet address 141.193.36.41/31
            # Skip IRB interfaces (handled below)
            if 'set interfaces' in line and 'family inet address' in line and 'irb' not in line:
                # Skip VRRP virtual-address lines
                if 'virtual-address' in line:
                    continue

                # Match physical interface: set interfaces <interface> unit <unit> family inet address <ip/mask>
                # More flexible regex to catch et-0/0/48 style interfaces
                match = re.search(
                    r'set interfaces ([a-zA-Z0-9\-/]+) unit (\d+) family inet address (\d+\.\d+\.\d+\.\d+/\d+)',
                    line
                )
                if match:
                    interface_name = match.group(1)
                    unit = match.group(2)
                    addr_with_mask = match.group(3)

                    try:
                        interface_net = ipaddress.ip_interface(addr_with_mask)
                        # Check if peer is in this subnet
                        if peer_net in interface_net.network:
                            # For routed interfaces, there's no VLAN (or it's not relevant for L3)
                            full_interface = f"{interface_name}.{unit}"
                            return full_interface, None, None, addr_with_mask
                    except (ValueError, ipaddress.AddressValueError):
                        continue

        # Find IRB units with their IP addresses (SVI/VLAN interfaces)
        for line in self.config_lines:
            if 'set interfaces irb unit' in line and 'family inet address' in line:
                # Skip VRRP virtual-address lines
                if 'virtual-address' in line:
                    continue

                # Match: set interfaces irb unit 505 family inet address 209.50.158.3/26
                match = re.search(r'set interfaces irb unit (\d+) family inet address (\d+\.\d+\.\d+\.\d+/\d+)', line)
                if match:
                    unit = match.group(1)
                    addr_with_mask = match.group(2)

                    try:
                        interface_net = ipaddress.ip_interface(addr_with_mask)
                        # Check if peer is in this subnet
                        if peer_net in interface_net.network:
                            # Find VLAN for this IRB
                            vlan_name = None
                            vlan_id = None

                            # Look for l3-interface association
                            for vlan_line in self.config_lines:
                                if f'set vlans' in vlan_line and f'l3-interface irb.{unit}' in vlan_line:
                                    vlan_match = re.search(r'set vlans (\S+)', vlan_line)
                                    if vlan_match:
                                        vlan_name = vlan_match.group(1)

                                        # Get VLAN ID
                                        for vlan_id_line in self.config_lines:
                                            if f'set vlans {vlan_name} vlan-id' in vlan_id_line:
                                                vid_match = re.search(r'vlan-id (\d+)', vlan_id_line)
                                                if vid_match:
                                                    vlan_id = vid_match.group(1)
                                                    break
                                        break

                            return f"irb.{unit}", vlan_name, vlan_id, addr_with_mask
                    except (ValueError, ipaddress.AddressValueError):
                        continue

        return None, None, None, None

    def get_interface_config(self, interface: str) -> List[str]:
        """Get full interface configuration"""
        if not interface or '.' not in interface:
            return []

        interface_base, interface_unit = interface.split('.')
        config_lines = []

        for line in self.config_lines:
            if f'interfaces {interface_base} unit {interface_unit}' in line:
                config_lines.append(line)

        return sorted(config_lines)

    def get_policy_details(self, policy_name: str) -> List[str]:
        """Get policy-statement configuration"""
        policy_lines = []
        for line in self.config_lines:
            if f'policy-options policy-statement {policy_name}' in line:
                policy_lines.append(line)
        return policy_lines

    def get_vlan_config(self, vlan_name: str) -> List[str]:
        """Get VLAN configuration"""
        if not vlan_name:
            return []

        vlan_lines = []
        for line in self.config_lines:
            if f'vlans {vlan_name}' in line:
                vlan_lines.append(line)
        return sorted(vlan_lines)

    def generate_arista_config(self, peer_ip: str, peer_info: Dict, interface: str,
                               vlan_name: str, vlan_id: str, local_ip: str) -> str:
        """Generate Arista configuration for this BGP peer"""
        config = []
        config.append("!" * 80)
        config.append(f"! Arista Configuration for BGP Peer {peer_ip}")
        config.append(f"! Generated from Juniper group: {peer_info['group_name']}")
        config.append("!" * 80)
        config.append("")

        # Interface configuration
        # Check if this is a routed interface (non-IRB) or SVI (IRB)
        is_routed_interface = interface and not interface.startswith('irb.')

        if is_routed_interface and local_ip:
            # This is a point-to-point routed interface
            config.append(f"! Routed Interface Configuration")
            config.append(f"! Note: Juniper interface {interface} is a routed L3 interface")
            config.append(f"! Map to Arista Port-Channel or Ethernet interface as appropriate")
            config.append(f"!")
            config.append(f"! Example for Port-Channel (if using LAG):")
            config.append(f"interface Port-Channel<X>")
            config.append(f"   description BGP_Peering_{peer_info['group_name']}_to_{peer_ip}")
            config.append(f"   no switchport")
            config.append(f"   ip address {local_ip}")
            config.append(f"   no shutdown")
            config.append("!")
            config.append(f"! OR for physical interface:")
            config.append(f"interface Ethernet<X>")
            config.append(f"   description BGP_Peering_{peer_info['group_name']}_to_{peer_ip}")
            config.append(f"   no switchport")
            config.append(f"   ip address {local_ip}")
            config.append(f"   no shutdown")
            config.append("!")
        elif vlan_id and local_ip:
            # This is an SVI/VLAN interface
            config.append(f"! VLAN Configuration")
            config.append(f"vlan {vlan_id}")
            vlan_display_name = vlan_name if vlan_name else f"VLAN{vlan_id}"
            config.append(f"   name {vlan_display_name}")
            config.append("!")
            config.append(f"! SVI Configuration")
            config.append(f"interface Vlan{vlan_id}")
            config.append(f"   description BGP_Peering_{peer_info['group_name']}")
            config.append(f"   ip address {local_ip}")
            config.append(f"   no shutdown")
            config.append("!")
        elif local_ip:
            config.append(f"! WARNING: Could not determine interface type")
            config.append(f"! Local IP should be: {local_ip}")
            config.append(f"! Configure interface manually")
            config.append("!")

        # BGP Configuration
        config.append(f"! BGP Configuration")

        # Use detected global ASN or local-as from group
        if peer_info['local_as']:
            local_as = peer_info['local_as']
        elif self.global_asn:
            local_as = self.global_asn
        else:
            local_as = '<YOUR_ASN>'

        config.append(f"router bgp {local_as}")
        config.append(f"   !")

        # Basic neighbor configuration
        config.append(f"   neighbor {peer_ip} remote-as {peer_info['peer_as']}")

        description = peer_info.get('peer_description') or peer_info['group_name']
        config.append(f"   neighbor {peer_ip} description {description}")

        # Update source - handle both routed and SVI interfaces
        if is_routed_interface and local_ip:
            config.append(f"   neighbor {peer_ip} update-source <Interface>  ! Use the interface configured above")
        elif vlan_id:
            config.append(f"   neighbor {peer_ip} update-source Vlan{vlan_id}")

        # Passive mode
        if any('passive' in line for line in peer_info['group_config']):
            config.append(f"   neighbor {peer_ip} passive")

        # BFD
        if peer_info['bfd_enabled']:
            config.append(f"   neighbor {peer_ip} bfd")

        # Authentication
        if peer_info['authentication']:
            config.append(f"   neighbor {peer_ip} password 7 <ENCRYPTED_PASSWORD>")
            config.append(f"   ! TODO: Configure BGP authentication")

        # Timers
        if peer_info['hold_time']:
            keepalive = int(peer_info['hold_time']) // 3
            config.append(f"   neighbor {peer_ip} timers {keepalive} {peer_info['hold_time']}")

        # Multipath
        if any('multipath' in line for line in peer_info['group_config']):
            config.append(f"   !")
            config.append(f"   maximum-paths 32")
            config.append(f"   maximum-paths 32 ecmp")

        config.append(f"   !")
        config.append(f"   ! Address Family Configuration")
        config.append(f"   address-family ipv4")
        config.append(f"      neighbor {peer_ip} activate")

        # Process import policies
        if peer_info['import_policies']:
            import_has_deny_all = 'deny-all' in peer_info['import_policies']
            import_real_policies = [p for p in peer_info['import_policies'] if p != 'deny-all']

            if import_real_policies:
                config.append(f"      neighbor {peer_ip} route-map {peer_info['group_name']}_IMPORT in")
            elif import_has_deny_all:
                config.append(f"      ! WARNING: Only deny-all configured - no routes will be accepted")
                config.append(f"      neighbor {peer_ip} route-map DENY-ALL in")

        # Process export policies
        if peer_info['export_policies']:
            export_has_deny_all = 'deny-all' in peer_info['export_policies']
            export_real_policies = [p for p in peer_info['export_policies'] if p != 'deny-all']

            if export_real_policies:
                config.append(f"      neighbor {peer_ip} route-map {peer_info['group_name']}_EXPORT out")
            elif export_has_deny_all:
                config.append(f"      ! WARNING: Only deny-all configured - no routes will be advertised")
                config.append(f"      neighbor {peer_ip} route-map DENY-ALL out")

        config.append(f"   exit-address-family")
        config.append("!")

        # Route map stubs
        config.append("!" * 80)
        config.append("! Route-map Templates - Translate Juniper Policies")
        config.append("!" * 80)

        # Get non-deny-all policies
        import_real = [p for p in peer_info['import_policies'] if p != 'deny-all']
        export_real = [p for p in peer_info['export_policies'] if p != 'deny-all']

        # Create combined import route-map if needed
        if import_real:
            config.append("!")
            config.append(f"! Combined IMPORT route-map (Juniper policy chain)")
            config.append(f"! Juniper config: import {' '.join(peer_info['import_policies'])}")
            config.append(f"route-map {peer_info['group_name']}_IMPORT permit 10")
            config.append(f"   ! Sequence 10: Apply {import_real[0]} policy")
            config.append(f"   ! TODO: Translate Juniper policy-statement {import_real[0]}")

            # If there are multiple policies, create additional sequences
            for idx, policy in enumerate(import_real[1:], start=2):
                seq = idx * 10
                config.append(f"!")
                config.append(f"route-map {peer_info['group_name']}_IMPORT permit {seq}")
                config.append(f"   ! Sequence {seq}: Apply {policy} policy")
                config.append(f"   ! TODO: Translate Juniper policy-statement {policy}")

            # If deny-all is in the chain, add final deny sequence
            if 'deny-all' in peer_info['import_policies']:
                final_seq = (len(import_real) + 1) * 10
                config.append(f"!")
                config.append(f"route-map {peer_info['group_name']}_IMPORT deny {final_seq}")
                config.append(f"   ! Final sequence: deny-all (reject everything else)")

        # Create combined export route-map if needed
        if export_real:
            config.append("!")
            config.append(f"! Combined EXPORT route-map (Juniper policy chain)")
            config.append(f"! Juniper config: export {' '.join(peer_info['export_policies'])}")
            config.append(f"route-map {peer_info['group_name']}_EXPORT permit 10")
            config.append(f"   ! Sequence 10: Apply {export_real[0]} policy")
            config.append(f"   ! TODO: Translate Juniper policy-statement {export_real[0]}")

            for idx, policy in enumerate(export_real[1:], start=2):
                seq = idx * 10
                config.append(f"!")
                config.append(f"route-map {peer_info['group_name']}_EXPORT permit {seq}")
                config.append(f"   ! Sequence {seq}: Apply {policy} policy")
                config.append(f"   ! TODO: Translate Juniper policy-statement {policy}")

            if 'deny-all' in peer_info['export_policies']:
                final_seq = (len(export_real) + 1) * 10
                config.append(f"!")
                config.append(f"route-map {peer_info['group_name']}_EXPORT deny {final_seq}")
                config.append(f"   ! Final sequence: deny-all (reject everything else)")

        # Add DENY-ALL route-map if it's used standalone
        if (('deny-all' in peer_info['import_policies'] and not import_real) or
                ('deny-all' in peer_info['export_policies'] and not export_real)):
            config.append("!")
            config.append("! Standalone DENY-ALL route-map")
            config.append("route-map DENY-ALL deny 10")
            config.append("   ! Reject all routes")

        return "\n".join(config)

    def analyze_peer_migration(self, peer_ip: str):
        """Analyze and provide migration plan for a specific BGP peer"""
        print(f"\n{'=' * 80}")
        print(f"BGP PEER MIGRATION ANALYSIS: {peer_ip}")
        print(f"{'=' * 80}\n")

        # Find BGP configuration
        peer_info = self.find_bgp_peer(peer_ip)

        if not peer_info['group_name']:
            print(f"❌ ERROR: {peer_ip} is not configured as a BGP neighbor")
            print(f"\nTip: Verify the IP address is correct and appears in 'show configuration protocols bgp'")
            return

        print(f"✓ Found BGP peer in group: {peer_info['group_name']}")
        print(f"{'=' * 80}\n")

        # Find interface
        interface, vlan_name, vlan_id, local_ip = self.find_interface_for_peer(peer_ip)
        is_routed_interface = interface and not interface.startswith('irb.')

        print("NETWORK DETAILS")
        print("-" * 80)
        if interface:
            print(f"  Interface:  {interface}")
            print(f"  VLAN Name:  {vlan_name or 'N/A'}")
            print(f"  VLAN ID:    {vlan_id or 'N/A'}")
            print(f"  Local IP:   {local_ip}")
            if local_ip:
                net = ipaddress.ip_interface(local_ip).network
                print(f"  Subnet:     {net}")
        else:
            print(f"  ⚠️  WARNING: Could not determine interface/VLAN for peer {peer_ip}")
            print(f"  This may indicate the peer is on a different interface type or")
            print(f"  the configuration uses a non-standard format.")
            local_ip = None

        print(f"\nBGP CONFIGURATION")
        print("-" * 80)
        print(f"  Remote AS:       {peer_info['peer_as']}")
        print(f"  Local AS:        {peer_info['local_as'] or 'Default'}")
        print(f"  Session Type:    {peer_info['group_type'] or 'N/A'}")
        print(f"  Hold Time:       {peer_info['hold_time'] + 's' if peer_info['hold_time'] else 'Default (90s)'}")
        print(f"  BFD:             {'Enabled' if peer_info['bfd_enabled'] else 'Disabled'}")
        print(f"  Authentication:  {peer_info['authentication'] or 'None'}")

        if peer_info.get('peer_description'):
            print(f"  Description:     {peer_info['peer_description']}")

        print(f"\nPOLICIES")
        print("-" * 80)
        if peer_info['import_policies']:
            print(f"  Import (Inbound):  {', '.join(peer_info['import_policies'])}")
        else:
            print(f"  Import (Inbound):  None (accept all routes)")

        if peer_info['export_policies']:
            print(f"  Export (Outbound): {', '.join(peer_info['export_policies'])}")
        else:
            print(f"  Export (Outbound): None (advertise all routes)")

        # Show group features
        features = []
        for line in peer_info['group_config']:
            if 'passive' in line:
                features.append("passive")
            if 'multipath' in line:
                features.append("multipath")
            if 'mtu-discovery' in line:
                features.append("mtu-discovery")
            if 'log-updown' in line:
                features.append("log-updown")
            if 'multihop' in line:
                features.append("multihop")

        if features:
            print(f"\nFEATURES")
            print("-" * 80)
            print(f"  {', '.join(set(features))}")

        print(f"\nGROUP CONTEXT")
        print("-" * 80)
        total_neighbors = len(peer_info['other_neighbors']) + 1
        print(f"  Group Name:            {peer_info['group_name']}")
        print(f"  Total Neighbors:       {total_neighbors}")
        print(f"  Remaining After Move:  {len(peer_info['other_neighbors'])}")

        if peer_info['other_neighbors']:
            print(f"\n  Other Neighbors in Group:")
            display_count = min(10, len(peer_info['other_neighbors']))
            for neighbor in peer_info['other_neighbors'][:display_count]:
                print(f"    • {neighbor}")
            if len(peer_info['other_neighbors']) > display_count:
                print(f"    ... and {len(peer_info['other_neighbors']) - display_count} more")

        # Migration checklist with detailed steps
        print(f"\n{'=' * 80}")
        print(f"INTERFACE & VLAN MIGRATION DETAILS")
        print(f"{'=' * 80}")

        if is_routed_interface and interface and local_ip:
            # Routed interface (point-to-point)
            print(f"\nJuniper Configuration (Current):")
            print(f"  • Interface: {interface} (Routed L3 interface)")
            print(f"  • Type: Point-to-point routed interface")
            print(f"  • IP Address: {local_ip}")
            print(f"  • Subnet: {ipaddress.ip_interface(local_ip).network}")

            # Check if it's an aggregated interface
            interface_base = interface.split('.')[0]
            if interface_base.startswith('ae'):
                print(f"  • LAG: Yes (Aggregated Ethernet)")

            print(f"\nArista Configuration (Target):")
            if interface_base.startswith('ae'):
                print(f"  • Interface: Port-Channel<X> (to be determined)")
                print(f"  • Type: Routed LAG interface")
            else:
                print(f"  • Interface: Ethernet<X> (to be determined)")
                print(f"  • Type: Routed physical interface")
            print(f"  • Configuration: 'no switchport' for L3 routing")
            print(f"  • IP Address: {local_ip} (same as Juniper)")

            print(f"\nKey Differences:")
            print(f"  • Both are Layer 3 routed interfaces (no VLAN tagging)")
            print(f"  • Juniper: '{interface}' → Arista: 'Port-Channel<X>' or 'Ethernet<X>'")
            print(f"  • Same IP address: {local_ip}")
            print(f"  • Must configure 'no switchport' on Arista for L3 routing")

        elif interface and vlan_id:
            # SVI/VLAN interface
            print(f"\nJuniper Configuration (Current):")
            print(f"  • Interface: {interface} (IRB - L3 switched interface)")
            print(f"  • VLAN: {vlan_name} (ID: {vlan_id})")
            print(f"  • IP Address: {local_ip}")

            # Check for VRRP
            interface_config = self.get_interface_config(interface)
            vrrp_info = []
            for line in interface_config:
                if 'vrrp-group' in line:
                    if 'virtual-address' in line:
                        match = re.search(r'virtual-address (\S+)', line)
                        if match:
                            vrrp_info.append(f"Virtual IP: {match.group(1)}")
                    if 'priority' in line:
                        match = re.search(r'priority (\d+)', line)
                        if match:
                            vrrp_info.append(f"Priority: {match.group(1)}")

            if vrrp_info:
                print(f"  • VRRP: Enabled ({', '.join(vrrp_info)})")
                print(f"    ⚠️  IMPORTANT: Coordinate VRRP strategy with team")

            print(f"\nArista Configuration (Target):")
            print(f"  • Interface: Vlan{vlan_id} (SVI - Switched Virtual Interface)")
            print(f"  • VLAN: {vlan_id} (name: {vlan_name or f'VLAN{vlan_id}'})")
            print(f"  • IP Address: {local_ip}")
            print(f"  • Physical: Ensure VLAN {vlan_id} is trunked to appropriate port(s)")

            print(f"\nKey Differences:")
            print(f"  • Juniper uses 'irb.{vlan_id}' naming, Arista uses 'Vlan{vlan_id}'")
            print(f"  • Both are Layer 3 interfaces on the VLAN")
            print(f"  • Same IP address: {local_ip}")
            print(f"  • BGP peer {peer_ip} will see same source IP")
        else:
            print(f"\n⚠️  Could not determine interface configuration details")

        print(f"\n{'=' * 80}")
        print(f"DETAILED MIGRATION PLAN")
        print(f"{'=' * 80}")

        print(f"\n📋 PRE-MIGRATION VERIFICATION")
        print("-" * 80)
        print(f"  1. Review policy translations (see JUNIPER POLICY DETAILS below)")
        print(f"  2. Verify L2/L3 connectivity:")
        if is_routed_interface:
            print(f"     - Verify physical connectivity for routed interface")
            print(f"     - Ensure proper cabling between Arista and peer device")
        else:
            print(f"     - Ensure VLAN {vlan_id or 'TBD'} is trunked to Arista switch")
        print(
            f"     - Verify peer {peer_ip} is reachable on subnet {ipaddress.ip_interface(local_ip).network if local_ip else 'TBD'}")
        print(f"  3. Check IP addressing:")
        print(f"     - Confirm Arista can use {local_ip or 'same subnet as Juniper'}")
        if local_ip and interface and 'vrrp-group' in '\n'.join(self.get_interface_config(interface)):
            print(f"     - ⚠️  WARNING: VRRP detected on Juniper - coordinate failover strategy")
            print(f"     - Consider if Arista should join VRRP or use different approach")
        print(f"  4. Coordinate with peer:")
        print(f"     - Schedule maintenance window")
        print(f"     - Notify that BGP peer IP will remain {peer_ip}")
        print(f"     - Confirm expected routes: Import expects routes from AS {peer_info['peer_as']}")

        print(f"\n🔧 ARISTA CONFIGURATION STEPS")
        print("-" * 80)

        if is_routed_interface:
            interface_base = interface.split('.')[0] if interface else 'ae'
            if interface_base.startswith('ae'):
                print(f"  Step 1: Configure Port-Channel interface")
                print(f"     Arista# configure")
                print(f"     Arista(config)# interface Port-Channel<X>")
                print(f"     Arista(config-if-Po<X>)# description BGP_Peering_{peer_info['group_name']}_to_{peer_ip}")
                print(f"     Arista(config-if-Po<X>)# no switchport")
                print(f"     Arista(config-if-Po<X>)# ip address {local_ip or 'TBD'}")
                print(f"     Arista(config-if-Po<X>)# no shutdown")
                print(f"     Arista(config-if-Po<X>)# exit")
            else:
                print(f"  Step 1: Configure physical interface")
                print(f"     Arista# configure")
                print(f"     Arista(config)# interface Ethernet<X>")
                print(f"     Arista(config-if-Et<X>)# description BGP_Peering_{peer_info['group_name']}_to_{peer_ip}")
                print(f"     Arista(config-if-Et<X>)# no switchport")
                print(f"     Arista(config-if-Et<X>)# ip address {local_ip or 'TBD'}")
                print(f"     Arista(config-if-Et<X>)# no shutdown")
                print(f"     Arista(config-if-Et<X>)# exit")

            print(f"\n  Step 2: Verify connectivity")
            print(f"     Arista(config)# exit")
            print(f"     Arista# ping {peer_ip}")
            print(f"     (Expect: Success - peer should respond)")
        else:
            print(f"  Step 1: Configure VLAN")
            print(f"     Arista# configure")
            print(f"     Arista(config)# vlan {vlan_id or 'TBD'}")
            print(
                f"     Arista(config-vlan-{vlan_id or 'TBD'})# name {vlan_name or f'VLAN{vlan_id}' if vlan_id else 'TBD'}")
            print(f"     Arista(config-vlan-{vlan_id or 'TBD'})# exit")

            print(f"\n  Step 2: Configure SVI")
            print(f"     Arista(config)# interface Vlan{vlan_id or 'TBD'}")
            print(f"     Arista(config-if-Vl{vlan_id or 'TBD'})# description BGP_Peering_{peer_info['group_name']}")
            print(f"     Arista(config-if-Vl{vlan_id or 'TBD'})# ip address {local_ip or 'TBD'}")
            print(f"     Arista(config-if-Vl{vlan_id or 'TBD'})# no shutdown")
            print(f"     Arista(config-if-Vl{vlan_id or 'TBD'})# exit")

            print(f"\n  Step 3: Verify connectivity")
            print(f"     Arista(config)# exit")
            print(f"     Arista# ping {peer_ip} source Vlan{vlan_id or 'TBD'}")
            print(f"     (Expect: Success - peer should respond)")

        print(
            f"\n  Step {'3' if is_routed_interface else '4'}: Configure route-maps (see ARISTA CONFIGURATION section)")

        print(f"\n  Step {'4' if is_routed_interface else '5'}: Configure BGP neighbor")
        print(f"     Arista# configure")
        print(f"     Arista(config)# router bgp {peer_info['local_as'] or self.global_asn or 'YOUR_ASN'}")
        print(f"     (See full BGP configuration in ARISTA CONFIGURATION section)")

        print(f"\n  Step {'5' if is_routed_interface else '6'}: Verify BGP session")
        print(f"     Arista# show ip bgp summary | grep {peer_ip}")
        print(f"     (Expect: State = Established)")
        print(f"     Arista# show ip bgp neighbor {peer_ip}")
        print(f"     (Verify: Remote AS {peer_info['peer_as']}, routes received/sent)")

        print(f"\n  Step {'6' if is_routed_interface else '7'}: Verify routes")
        if peer_info['import_policies'] and 'deny-all' not in peer_info['import_policies'][:1]:
            print(f"     Arista# show ip bgp neighbor {peer_ip} received-routes")
            print(f"     (Expect: Routes matching policy filters)")
        print(f"     Arista# show ip route bgp")
        print(f"     (Verify: Routes are installed in routing table)")

        print(f"\n🗑️  JUNIPER CLEANUP COMMANDS")
        print("-" * 80)
        print(f"  After successful Arista migration, remove from Juniper:")
        print(f"")
        print(f"  Juniper# configure")
        print(f"  Juniper# delete protocols bgp group {peer_info['group_name']} neighbor {peer_ip}")
        print(f"  Juniper# commit check")
        print(f"  Juniper# commit and-quit")
        print(f"")
        print(f"  Verification commands:")
        print(f"  Juniper# show bgp summary | match {peer_ip}")
        print(f"  (Expect: No output - neighbor removed)")
        print(f"  Juniper# show bgp group {peer_info['group_name']} | match Established")
        print(f"  (Verify: {len(peer_info['other_neighbors'])} remaining neighbors still established)")

        if len(peer_info['other_neighbors']) == 0:
            print(f"\n  ⚠️  LAST NEIGHBOR IN GROUP - Additional cleanup:")
            print(f"  Juniper# delete protocols bgp group {peer_info['group_name']}")
            print(f"  (Optional) Delete VLAN/interface if no longer needed:")
            if vlan_name:
                print(f"  Juniper# delete vlans {vlan_name}")
            if interface:
                print(f"  Juniper# delete interfaces {interface.split('.')[0]} unit {interface.split('.')[1]}")

        print(f"\n📊 POST-MIGRATION VALIDATION")
        print("-" * 80)
        print(f"  1. Monitor BGP session stability (30+ minutes)")
        print(f"     Arista# show ip bgp summary | grep {peer_ip}")
        print(f"     (Watch for flaps or state changes)")

        print(f"  2. Verify route counts match expectations")
        print(f"     Compare before/after route counts for prefix consistency")

        print(f"  3. Check remaining Juniper peers")
        print(f"     Juniper# show bgp group {peer_info['group_name']} | match Established")
        print(f"     (Verify: All {len(peer_info['other_neighbors'])} remaining peers unaffected)")

        print(f"  4. Update documentation")
        print(f"     - Network diagrams showing new Arista peering")
        print(f"     - BGP peer inventory spreadsheet")
        print(f"     - Runbook/playbook updates")

        print(f"\n{'=' * 80}\n")

        # Generate Arista config
        print(f"ARISTA CONFIGURATION")
        print(f"{'=' * 80}\n")
        arista_config = self.generate_arista_config(peer_ip, peer_info, interface,
                                                    vlan_name, vlan_id, local_ip)
        print(arista_config)
        print("")

        # Show Juniper policies - condensed for space
        print(f"\n{'=' * 80}")
        print(f"ROUTE-MAP TRANSLATION GUIDE")
        print(f"{'=' * 80}")

        all_policies = set(peer_info['import_policies'] + peer_info['export_policies'])
        all_policies.discard('deny-all')

        if all_policies:
            print(f"\nPolicies to translate: {', '.join(sorted(all_policies))}")
            print(f"\nJuniper Policy Logic → Arista Route-Map:")
            print("-" * 80)

            for policy in sorted(all_policies):
                policy_lines = self.get_policy_details(policy)
                if policy_lines:
                    print(f"\n{policy}:")

                    # Parse the policy structure
                    terms = {}
                    current_term = None

                    for line in policy_lines:
                        if 'term ' in line:
                            term_match = re.search(r'term (\S+)', line)
                            if term_match:
                                current_term = term_match.group(1)
                                if current_term not in terms:
                                    terms[current_term] = {'from': [], 'then': []}

                        if current_term:
                            if ' from ' in line:
                                terms[current_term]['from'].append(line)
                            elif ' then ' in line:
                                terms[current_term]['then'].append(line)

                    # Show translation for each term
                    for idx, (term_name, term_data) in enumerate(sorted(terms.items()), start=1):
                        seq = idx * 10
                        print(f"\n  Term: {term_name} → route-map sequence {seq}")

                        # Match conditions
                        if term_data['from']:
                            print(f"    Match conditions:")
                            for from_line in term_data['from']:
                                if 'route-filter' in from_line:
                                    match = re.search(r'route-filter (\S+) prefix-length-range /(\d+)-/(\d+)',
                                                      from_line)
                                    if match:
                                        prefix, min_len, max_len = match.groups()
                                        print(f"      • Prefix: {prefix}, length {min_len}-{max_len}")
                                        print(
                                            f"        Arista: ip prefix-list {policy}_{term_name} permit {prefix} le {max_len} ge {min_len}")

                        # Actions
                        if term_data['then']:
                            print(f"    Actions:")
                            for then_line in term_data['then']:
                                if 'accept' in then_line:
                                    print(f"      • Action: ACCEPT")
                                    print(f"        Arista: permit")
                                elif 'reject' in then_line:
                                    print(f"      • Action: REJECT")
                                    print(f"        Arista: deny")

                    print(f"\n  Example Arista configuration:")
                    print(f"  !")
                    for idx, (term_name, term_data) in enumerate(sorted(terms.items()), start=1):
                        seq = idx * 10
                        action = 'permit' if any('accept' in line for line in term_data['then']) else 'deny'
                        print(f"  route-map {policy} {action} {seq}")
                        print(f"     description Juniper term: {term_name}")
                        if term_data['from']:
                            print(f"     match ip address prefix-list {policy}_{term_name}")
                        print(f"  !")

        print(f"\n{'=' * 80}")
        print(f"JUNIPER POLICY DETAILS (For Translation)")
        print(f"{'=' * 80}")

        all_policies = set(peer_info['import_policies'] + peer_info['export_policies'])
        all_policies.discard('deny-all')

        if all_policies:
            for policy in sorted(all_policies):
                policy_lines = self.get_policy_details(policy)
                if policy_lines:
                    print(f"\nPolicy: {policy}")
                    print("-" * 80)
                    for line in sorted(policy_lines)[:25]:
                        print(f"  {line}")
                    if len(policy_lines) > 25:
                        print(f"  ... ({len(policy_lines) - 25} more lines)")
                else:
                    print(f"\nPolicy: {policy}")
                    print("-" * 80)
                    print(f"  ⚠️  Policy definition not found in config")
        else:
            print("\nNo custom policies configured (using defaults)")

        # Show Juniper configurations
        print(f"\n\n{'=' * 80}")
        print(f"JUNIPER CONFIGURATION REFERENCE")
        print(f"{'=' * 80}")

        if interface:
            interface_config = self.get_interface_config(interface)
            if interface_config:
                print(f"\nInterface: {interface}")
                print("-" * 80)
                for line in interface_config:
                    print(f"  {line}")

            if vlan_name:
                vlan_config = self.get_vlan_config(vlan_name)
                if vlan_config:
                    print(f"\nVLAN: {vlan_name}")
                    print("-" * 80)
                    for line in vlan_config:
                        print(f"  {line}")

        print(f"\nBGP Group: {peer_info['group_name']}")
        print("-" * 80)
        display_lines = min(30, len(peer_info['group_config']))
        for line in sorted(peer_info['group_config'])[:display_lines]:
            print(f"  {line}")
        if len(peer_info['group_config']) > display_lines:
            print(f"  ... ({len(peer_info['group_config']) - display_lines} more lines)")

        print(f"\n{'=' * 80}")
        print(f"END OF MIGRATION ANALYSIS")
        print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze Juniper BGP peer migration to Arista',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a peer migration
  %(prog)s juniper.conf 192.168.1.1

  # Export analysis to file
  %(prog)s juniper.conf 192.168.1.1 --export migration_plan.txt

  # Analyze and save Arista config only
  %(prog)s juniper.conf 192.168.1.1 --export-arista arista_config.txt
        """
    )
    parser.add_argument('config_file', help='Path to Juniper config file')
    parser.add_argument('peer_ip', help='BGP peer IP address to migrate')
    parser.add_argument('--export', help='Export full analysis to file')
    parser.add_argument('--export-arista', help='Export only Arista config to file')

    args = parser.parse_args()

    # Validate IP address format
    try:
        ipaddress.ip_address(args.peer_ip)
    except ValueError:
        print(f"❌ ERROR: Invalid IP address format: {args.peer_ip}")
        sys.exit(1)

    migrator = JuniperToAristaMigration(args.config_file)

    if args.export:
        original_stdout = sys.stdout
        try:
            with open(args.export, 'w') as f:
                sys.stdout = f
                migrator.analyze_peer_migration(args.peer_ip)
            sys.stdout = original_stdout
            print(f"✓ Migration analysis exported to: {args.export}")
        except Exception as e:
            sys.stdout = original_stdout
            print(f"❌ ERROR: Failed to write export file: {e}")
            sys.exit(1)
    elif args.export_arista:
        # Generate config and extract just Arista portion
        try:
            peer_info = migrator.find_bgp_peer(args.peer_ip)
            interface, vlan_name, vlan_id, local_ip = migrator.find_interface_for_peer(args.peer_ip)
            arista_config = migrator.generate_arista_config(args.peer_ip, peer_info, interface,
                                                            vlan_name, vlan_id, local_ip)

            with open(args.export_arista, 'w') as f:
                f.write(arista_config)
            print(f"✓ Arista configuration exported to: {args.export_arista}")
        except Exception as e:
            print(f"❌ ERROR: Failed to generate Arista config: {e}")
            sys.exit(1)
    else:
        migrator.analyze_peer_migration(args.peer_ip)


if __name__ == "__main__":
    main()