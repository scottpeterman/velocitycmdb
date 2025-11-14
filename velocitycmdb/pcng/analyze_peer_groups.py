#!/usr/bin/env python3
"""
Peer Group Analysis Script
Analyzes BGP bulk export files to generate a comprehensive peer group report
"""

import json
import os
from collections import defaultdict
from typing import Dict, List, Set


def load_summary(summary_path: str) -> Dict:
    """Load the export summary file"""
    with open(summary_path, 'r') as f:
        return json.load(f)


def load_device_export(filepath: str) -> Dict:
    """Load a single device BGP export file"""
    with open(filepath, 'r') as f:
        return json.load(f)


def analyze_peer_groups(export_dir: str, summary_file: str = '_export_summary.json') -> Dict:
    """
    Analyze all peer groups across all devices

    Returns a dict structured as:
    {
        'peer_group_name': {
            'devices': ['device1', 'device2'],
            'total_peers': 10,
            'group_types': {'external', 'internal'},
            'session_types': {'eBGP', 'iBGP'},
            'peers': [
                {
                    'ip': '1.2.3.4',
                    'peer_as': '12345',
                    'description': 'Peer Name',
                    'session_type': 'eBGP',
                    'devices': ['device1', 'device2']
                }
            ],
            'unique_peer_count': 8,
            'unique_asns': ['12345', '67890']
        }
    }
    """
    summary_path = os.path.join(export_dir, summary_file)

    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"Summary file not found: {summary_path}")

    summary = load_summary(summary_path)
    files_to_process = summary['export_summary']['files_included']

    # Data structures for analysis
    peer_groups = defaultdict(lambda: {
        'devices': [],
        'total_peers': 0,
        'group_types': set(),
        'session_types': set(),
        'peers': defaultdict(lambda: {
            'ip': None,
            'peer_as': None,
            'description': None,
            'session_type': None,
            'devices': []
        }),
        'unique_asns': set()
    })

    device_summary = []

    # Process each device export
    for filename in files_to_process:
        filepath = os.path.join(export_dir, filename)

        if not os.path.exists(filepath):
            print(f"Warning: File not found: {filepath}")
            continue

        device_data = load_device_export(filepath)
        device_name = device_data['device']['name']
        device_vendor = device_data['device']['vendor']
        device_site = device_data['device']['site']
        local_asn = device_data['device']['local_asn']

        bgp_data = device_data['bgp_data']
        groups = bgp_data.get('groups', [])

        device_peer_groups = []

        # Process each BGP group on this device
        for group in groups:
            group_name = group.get('name', 'Unknown')
            group_type = group.get('type') or 'Unknown'
            neighbors = group.get('neighbors', [])

            # Track this device uses this peer group
            peer_groups[group_name]['devices'].append(device_name)
            peer_groups[group_name]['group_types'].add(group_type)
            peer_groups[group_name]['total_peers'] += len(neighbors)

            device_peer_groups.append({
                'group_name': group_name,
                'peer_count': len(neighbors)
            })

            # Process each neighbor in the group
            for neighbor in neighbors:
                peer_ip = neighbor.get('ip')
                peer_as = neighbor.get('peer_as') or 'Unknown'
                description = neighbor.get('description', '')
                session_type = neighbor.get('session_type') or 'Unknown'

                peer_groups[group_name]['session_types'].add(session_type)
                peer_groups[group_name]['unique_asns'].add(peer_as)

                # Track this specific peer
                peer_key = f"{peer_ip}_{peer_as}"
                peer_groups[group_name]['peers'][peer_key]['ip'] = peer_ip
                peer_groups[group_name]['peers'][peer_key]['peer_as'] = peer_as
                peer_groups[group_name]['peers'][peer_key]['description'] = description
                peer_groups[group_name]['peers'][peer_key]['session_type'] = session_type

                if device_name not in peer_groups[group_name]['peers'][peer_key]['devices']:
                    peer_groups[group_name]['peers'][peer_key]['devices'].append(device_name)

        device_summary.append({
            'device': device_name,
            'vendor': device_vendor,
            'site': device_site,
            'local_asn': local_asn,
            'total_peers': bgp_data.get('total_peers', 0),
            'peer_groups': device_peer_groups
        })

    # Convert sets to lists and peers dict to list for JSON serialization
    for group_name, group_data in peer_groups.items():
        # Handle None values in group_types
        group_types = [gt for gt in group_data['group_types'] if gt]
        group_data['group_types'] = sorted(group_types) if group_types else ['Unknown']

        # Handle None values in session_types
        session_types = [st for st in group_data['session_types'] if st]
        group_data['session_types'] = sorted(session_types) if session_types else ['Unknown']

        # Handle None/Unknown ASNs separately
        asns = list(group_data['unique_asns'])
        # Filter out None and 'Unknown', sort the rest, then add them back at the end
        valid_asns = [asn for asn in asns if asn and asn != 'Unknown']
        invalid_asns = [asn for asn in asns if not asn or asn == 'Unknown']
        group_data['unique_asns'] = sorted(valid_asns) + sorted(invalid_asns)

        # Convert peers dict to list and sort by AS then IP (handling None values)
        peers_list = []
        for peer_key, peer_info in group_data['peers'].items():
            peers_list.append({
                'ip': peer_info['ip'],
                'peer_as': peer_info['peer_as'] or 'Unknown',
                'description': peer_info['description'],
                'session_type': peer_info['session_type'] or 'Unknown',
                'devices': sorted(peer_info['devices']),
                'device_count': len(peer_info['devices'])
            })

        # Sort by peer_as (put Unknown at end), then by IP
        group_data['peers'] = sorted(
            peers_list,
            key=lambda x: (x['peer_as'] == 'Unknown', x['peer_as'], x['ip'] or '')
        )
        group_data['unique_peer_count'] = len(peers_list)

    return {
        'analysis_summary': {
            'total_devices': len(files_to_process),
            'total_peer_groups': len(peer_groups),
            'export_timestamp': summary['export_summary']['exported_at']
        },
        'device_summary': sorted(device_summary, key=lambda x: x['device']),
        'peer_groups': dict(sorted(peer_groups.items()))
    }


def generate_pni_job_definition(analysis: Dict, pni_groups: list) -> Dict:
    """
    Generate a PNI analytics job definition file

    This creates a structured file specifically for PNI data collection,
    containing only the devices and peers in the specified PNI groups.

    Args:
        analysis: Full analysis dict from analyze_peer_groups()
        pni_groups: List of peer group names to include (e.g., ['peers_v4', 'edge_v4'])

    Returns:
        Dict structured for PNI data collection jobs
    """

    job_def = {
        'job_metadata': {
            'generated_at': analysis['analysis_summary']['export_timestamp'],
            'purpose': 'PNI Analytics Data Collection',
            'pni_groups_included': pni_groups,
            'total_pni_groups': len(pni_groups)
        },
        'collection_scope': {
            'total_devices': 0,
            'total_peers': 0,
            'unique_peer_ips': set(),
            'unique_asns': set()
        },
        'devices': []
    }

    # Track which devices we've seen to avoid duplicates
    device_peers = {}  # device_name -> list of peers

    # Process each PNI group
    for group_name in pni_groups:
        if group_name not in analysis['peer_groups']:
            continue

        group_data = analysis['peer_groups'][group_name]

        # Process each peer in this PNI group
        for peer in group_data['peers']:
            peer_ip = peer['ip']
            peer_as = peer['peer_as']

            # Add to collection scope tracking
            job_def['collection_scope']['unique_peer_ips'].add(peer_ip)
            job_def['collection_scope']['unique_asns'].add(peer_as)

            # Add this peer to each device it appears on
            for device_name in peer['devices']:
                if device_name not in device_peers:
                    device_peers[device_name] = []

                device_peers[device_name].append({
                    'peer_ip': peer_ip,
                    'peer_as': peer_as,
                    'peer_group': group_name,
                    'description': peer['description'],
                    'session_type': peer['session_type']
                })

    # Build device list with their PNI peers
    for device_name, peers in sorted(device_peers.items()):
        # Find device details from device_summary
        device_info = None
        for dev in analysis['device_summary']:
            if dev['device'] == device_name:
                device_info = dev
                break

        if not device_info:
            continue

        device_entry = {
            'device_name': device_name,
            'vendor': device_info['vendor'],
            'site': device_info['site'],
            'local_asn': device_info['local_asn'],
            'pni_peer_count': len(peers),
            'pni_groups': sorted(list(set([p['peer_group'] for p in peers]))),
            'peers': sorted(peers, key=lambda x: (x['peer_group'], x['peer_as'], x['peer_ip']))
        }

        job_def['devices'].append(device_entry)
        job_def['collection_scope']['total_peers'] += len(peers)

    # Convert sets to sorted lists for JSON serialization
    job_def['collection_scope']['unique_peer_ips'] = sorted(list(job_def['collection_scope']['unique_peer_ips']))
    job_def['collection_scope']['unique_asns'] = sorted(list(job_def['collection_scope']['unique_asns']))
    job_def['collection_scope']['total_devices'] = len(job_def['devices'])

    return job_def


def generate_pni_collection_commands(job_def: Dict, vendor_type: str = 'juniper') -> str:
    """
    Generate CLI commands for data collection based on job definition

    Args:
        job_def: PNI job definition dict
        vendor_type: 'juniper' or 'arista'

    Returns:
        String containing CLI commands ready to execute
    """
    commands = []

    commands.append("# PNI Data Collection Commands")
    commands.append(f"# Generated: {job_def['job_metadata']['generated_at']}")
    commands.append(f"# Total Devices: {job_def['collection_scope']['total_devices']}")
    commands.append(f"# Total PNI Peers: {job_def['collection_scope']['total_peers']}")
    commands.append("")

    for device in job_def['devices']:
        device_name = device['device_name']
        vendor = device['vendor'].lower()

        commands.append(f"\n{'=' * 80}")
        commands.append(f"# Device: {device_name}")
        commands.append(f"# Vendor: {vendor}")
        commands.append(f"# Site: {device['site']}")
        commands.append(f"# PNI Peers: {device['pni_peer_count']}")
        commands.append(f"# Groups: {', '.join(device['pni_groups'])}")
        commands.append(f"{'=' * 80}")

        if 'juniper' in vendor:
            # Juniper commands
            commands.append(f"\n# Connect to {device_name}")
            commands.append(f"# ssh {device_name}")
            commands.append("")

            for peer in device['peers']:
                commands.append(
                    f"# Peer: {peer['peer_ip']} (AS{peer['peer_as']}) - {peer['description'] or 'No description'}")
                commands.append(f"show bgp neighbor {peer['peer_ip']} | display json")
                commands.append(f"show route receive-protocol bgp {peer['peer_ip']} | display json")
                commands.append(f"show route receive-protocol bgp {peer['peer_ip']} active-path | display json")
                commands.append("")

        elif 'arista' in vendor:
            # Arista commands
            commands.append(f"\n# Connect to {device_name}")
            commands.append(f"# ssh {device_name}")
            commands.append("")

            for peer in device['peers']:
                commands.append(
                    f"# Peer: {peer['peer_ip']} (AS{peer['peer_as']}) - {peer['description'] or 'No description'}")
                commands.append(f"show bgp neighbor {peer['peer_ip']} | json")
                commands.append(f"show ip bgp neighbors {peer['peer_ip']} routes | json")
                commands.append(f"show ip bgp neighbors {peer['peer_ip']} routes | json")
                commands.append("")

    return "\n".join(commands)


def generate_text_report(analysis: Dict) -> str:
    """Generate a human-readable text report"""
    lines = []

    lines.append("=" * 80)
    lines.append("BGP PEER GROUP ANALYSIS REPORT")
    lines.append("=" * 80)
    lines.append("")

    summary = analysis['analysis_summary']
    lines.append(f"Export Timestamp: {summary['export_timestamp']}")
    lines.append(f"Total Devices Analyzed: {summary['total_devices']}")
    lines.append(f"Total Unique Peer Groups: {summary['total_peer_groups']}")
    lines.append("")

    lines.append("=" * 80)
    lines.append("PEER GROUPS SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    for group_name, group_data in analysis['peer_groups'].items():
        lines.append(f"\n{'=' * 80}")
        lines.append(f"Peer Group: {group_name}")
        lines.append(f"{'=' * 80}")
        lines.append(f"  Devices Using This Group: {len(group_data['devices'])}")
        lines.append(f"  Device List: {', '.join(sorted(group_data['devices']))}")
        lines.append(f"  Group Types: {', '.join(group_data['group_types'])}")
        lines.append(f"  Session Types: {', '.join(group_data['session_types'])}")
        lines.append(f"  Total Peer Instances: {group_data['total_peers']}")
        lines.append(f"  Unique Peers: {group_data['unique_peer_count']}")
        lines.append(f"  Unique ASNs: {len(group_data['unique_asns'])}")
        lines.append("")

        # Show peer details
        lines.append("  Peers:")
        lines.append("  " + "-" * 76)

        for peer in group_data['peers']:
            devices_str = ', '.join(peer['devices'])
            desc = peer['description'] or 'No description'
            lines.append(f"    IP: {peer['ip']:<16} AS: {peer['peer_as']:<8} Type: {peer['session_type']:<5}")
            lines.append(f"      Description: {desc}")
            lines.append(f"      Present on: {devices_str} ({peer['device_count']} device(s))")
            lines.append("")

    lines.append("\n" + "=" * 80)
    lines.append("DEVICE SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    for device in analysis['device_summary']:
        lines.append(f"\nDevice: {device['device']}")
        lines.append(f"  Vendor: {device['vendor']}")
        lines.append(f"  Site: {device['site']}")
        lines.append(f"  Local ASN: {device['local_asn']}")
        lines.append(f"  Total Peers: {device['total_peers']}")
        lines.append(f"  Peer Groups:")
        for pg in device['peer_groups']:
            lines.append(f"    - {pg['group_name']}: {pg['peer_count']} peers")

    return "\n".join(lines)


def generate_csv_report(analysis: Dict) -> str:
    """Generate a CSV report of all peer group relationships"""
    lines = []

    # Header
    lines.append("peer_group,device,peer_ip,peer_as,description,session_type,device_count")

    # Data rows
    for group_name, group_data in sorted(analysis['peer_groups'].items()):
        for peer in group_data['peers']:
            for device in peer['devices']:
                desc = peer['description'].replace(',', ';') if peer['description'] else ''
                lines.append(
                    f"{group_name},{device},{peer['ip']},{peer['peer_as']},"
                    f"{desc},{peer['session_type']},{peer['device_count']}"
                )

    return "\n".join(lines)


def main():
    """Main execution"""
    import argparse

    parser = argparse.ArgumentParser(description='Analyze BGP peer groups from bulk export')
    parser.add_argument('--export-dir', default='./bulk', help='Directory containing the BGP export files')
    parser.add_argument('--output-dir', default='./bgp_analytics', help='Output directory for reports')
    parser.add_argument('--text', action='store_true', help='Generate text report')
    parser.add_argument('--csv', action='store_true', help='Generate CSV report')
    parser.add_argument('--all', action='store_true', help='Generate all report formats')
    parser.add_argument('--pni-groups',
                        default='peers_v4,peers_v6,edge_v4,customer_v4,drt_v4',
                        help='Comma-separated list of PNI peer groups (default: peers_v4,peers_v6,edge_v4,customer_v4,drt_v4)')

    args = parser.parse_args()

    # JSON is always generated by default
    # If --all is specified, generate all formats
    # Otherwise only generate JSON plus any explicitly requested formats

    print(f"Analyzing BGP exports in: {args.export_dir}")
    print(f"Output directory: {args.output_dir}")

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    print("Processing...")

    # Run analysis
    analysis = analyze_peer_groups(args.export_dir)

    print(f"\nAnalysis complete!")
    print(f"  Devices analyzed: {analysis['analysis_summary']['total_devices']}")
    print(f"  Peer groups found: {analysis['analysis_summary']['total_peer_groups']}")

    # Always generate JSON report
    json_output = os.path.join(args.output_dir, 'peer_group_analysis.json')
    with open(json_output, 'w') as f:
        json.dump(analysis, f, indent=2)
    print(f"\n✓ JSON report saved: {json_output}")

    # Generate PNI job definition
    pni_groups = [g.strip() for g in args.pni_groups.split(',')]
    print(f"\nGenerating PNI analytics job definition...")
    print(f"  PNI Groups: {', '.join(pni_groups)}")

    pni_job_def = generate_pni_job_definition(analysis, pni_groups)

    pni_job_output = os.path.join(args.output_dir, 'pni_analytics_job.json')
    with open(pni_job_output, 'w') as f:
        json.dump(pni_job_def, f, indent=2)
    print(f"✓ PNI job definition saved: {pni_job_output}")
    print(f"  Devices with PNI peers: {pni_job_def['collection_scope']['total_devices']}")
    print(f"  Total PNI peers to monitor: {pni_job_def['collection_scope']['total_peers']}")
    print(f"  Unique peer IPs: {len(pni_job_def['collection_scope']['unique_peer_ips'])}")
    print(f"  Unique ASNs: {len(pni_job_def['collection_scope']['unique_asns'])}")

    # Generate CLI commands for data collection
    commands_output = os.path.join(args.output_dir, 'pni_collection_commands.txt')
    commands = generate_pni_collection_commands(pni_job_def)
    with open(commands_output, 'w') as f:
        f.write(commands)
    print(f"✓ CLI commands saved: {commands_output}")

    # Generate additional reports based on flags
    if args.all or args.text:
        text_output = os.path.join(args.output_dir, 'peer_group_analysis.txt')
        text_report = generate_text_report(analysis)
        with open(text_output, 'w') as f:
            f.write(text_report)
        print(f"✓ Text report saved: {text_output}")

    if args.all or args.csv:
        csv_output = os.path.join(args.output_dir, 'peer_group_analysis.csv')
        csv_report = generate_csv_report(analysis)
        with open(csv_output, 'w') as f:
            f.write(csv_report)
        print(f"✓ CSV report saved: {csv_output}")

    print("\nDone!")


if __name__ == '__main__':
    main()