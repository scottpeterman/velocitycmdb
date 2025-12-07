#!/usr/bin/env python3
"""
Convert legacy SQL-based job definitions to new JSON format
"""

import json
import os
import re
import argparse
from typing import Dict, Any, List, Tuple
from datetime import datetime


class SQLQueryParser:
    """Parse SQL WHERE clauses and convert to filter syntax"""

    def __init__(self):
        # Command type to actual command mapping
        self.cmd_mappings = {
            # Cisco Commands
            'cisco_show_run': 'show running-config',
            'cisco_show_version': 'show version',
            'cisco_show_ip_bgp_summary': 'show ip bgp summary',
            'cisco_show_ip_bgp_neighbor': 'show ip bgp neighbors',
            'cisco_show_ip_bgp': 'show ip bgp',
            'cisco_show_ip_bgp_detail': 'show ip bgp detail',
            'cisco_int_desc': 'show interfaces description',
            'cisco_int_status': 'show interfaces status',
            'cisco_cdp_neighbor_detail': 'show cdp neighbors detail',
            'cisco_lldp_neighbor_detail': 'show lldp neighbors detail',
            'cisco_show_ip_arp': 'show ip arp',
            'cisco_mac_address_table': 'show mac address-table',
            'cisco_show_inventory': 'show inventory',
            'cisco_show_ip_ospf_neighbor': 'show ip ospf neighbor',
            'cisco_show_ip_eigrp_neighbor': 'show ip eigrp neighbor',
            'cisco_show_tacacs': 'show tacacs',
            'cisco_show_ip_route': 'show ip route',
            'cisco_ios_port_channel_summary': 'show etherchannel summary',
            'cisco_nxos_port_channel_summary': 'show port-channel summary',

            # Arista Commands
            'arista_show_run': 'show running-config',
            'arista_show_version': 'show version',
            'arista_show_ip_bgp_summary': 'show ip bgp summary',
            'arista_show_ip_bgp_neighbors': 'show ip bgp neighbors',
            'arista_show_interfaces_status': 'show interfaces status',
            'arista_show_lldp_neighbors_detail': 'show lldp neighbors detail',
            'arista_show_ip_arp': 'show ip arp',
            'arista_show_mac_address_table': 'show mac address-table',
            'arista_show_inventory': 'show inventory',
            'arista_show_ip_ospf_neighbor': 'show ip ospf neighbor',
            'arista_show_ip_route': 'show ip route',
            'arista_show_port_channel_summary': 'show port-channel summary',

            # Aruba Commands
            'aruba_show_run': 'show running-config',
            'aruba_show_mac_address': 'show mac-address',
            'aruba_show_cdp_detail': 'show cdp neighbors detail',
            'aruba_show_cdp': 'show cdp neighbors',
            'aruba_show_lldp_remote': 'show lldp remote',
            'aruba_show_lldp_remote_detail': 'show lldp remote detail',
            'aruba_show_int_status': 'show interface status',
            'aruba_show_system_info': 'show system information',
            'aruba_show_console': 'show console',
            'aruba_show_ip_ssh': 'show ip ssh',
            'aruba_show_authentication': 'show authentication',
            'aruba_show_authorization': 'show authorization',
            'aruba_show_syslog_config': 'show syslog configuration',
            'aruba_show_ntp_status': 'show ntp status',
            'aruba_show_snmp_server': 'show snmp-server',
            'aruba_show_tacacs': 'show tacacs',

            # Palo Alto Commands
            'paloalto_show_arp': 'show arp',

            # CloudGenix/Ion Commands
            'ion_inspect_system_arp_all': 'inspect system arp all',
        }

        # Vendor detection patterns
        self.vendor_patterns = {
            'cisco': ['Cisco', 'IOS', 'NX-OS', 'IOS-XE', 'N7K', 'N9K'],
            'arista': ['Arista', 'EOS'],
            'aruba': ['Aruba', 'SW-OS'],
            'paloalto': ['Palo', 'PAN-OS'],
            'cloudgenix': ['Cloud', 'Ion']
        }

    def parse_sql_conditions(self, query: str, use_device_type_mapping: bool = False) -> Dict[str, Any]:
        """Parse SQL WHERE clause into filter components"""
        filters = {
            'folder': '',
            'name': '',
            'vendor': '',
            'device_type': ''
        }

        # Remove SELECT and FROM parts, focus on WHERE clause
        where_match = re.search(r'where\s+(.+?)(?:\s+order\s+by|\s+group\s+by|\s+limit|$)', query.lower())
        if not where_match:
            return filters

        where_clause = where_match.group(1)

        # Split on AND (simple approach - doesn't handle nested parentheses perfectly)
        and_conditions = re.split(r'\s+and\s+', where_clause, flags=re.IGNORECASE)

        device_type_patterns = []
        vendor_patterns = []
        hostname_patterns = []

        # NetBox role mapping from old DeviceType patterns to new roles
        netbox_role_mapping = {
            'cisco ios': 'Router',
            'cisco ios-xe': 'Router',
            'cisco nx-os': 'Core Switch',
            'cisco n7k': 'Core Switch',
            'cisco n9k': 'Core Switch',
            'cisco nx': 'Core Switch',
            'arista': 'Router',
            'aruba sw-os': 'Access Switch',
            'palo': 'Firewall',
            'cloud': 'Router',  # CloudGenix/Ion devices
            'server': 'Server'
        }

        for condition in and_conditions:
            condition = condition.strip()

            # Skip credential and monitoring conditions
            if any(keyword in condition.lower() for keyword in ['credsid', 'monitored', 'ssh_reachable', 'mgmtip']):
                continue

            # Parse DeviceType conditions - extract vendor info and optionally map device types
            if 'devicetype' in condition.lower():
                # Extract the LIKE pattern
                like_match = re.search(r'like\s+["\']([^"\']+)["\']', condition, re.IGNORECASE)
                eq_match = re.search(r'=\s+["\']([^"\']+)["\']', condition, re.IGNORECASE)

                original_pattern = None
                if like_match:
                    original_pattern = like_match.group(1).replace('%', '').lower()
                elif eq_match:
                    original_pattern = eq_match.group(1).lower()

                if original_pattern:
                    # Extract vendor from DeviceType field (since old DB mixed vendor + type)
                    vendor_extracted = False
                    for vendor_key in ['cisco', 'arista', 'aruba', 'palo', 'cloudgenix', 'dell', 'apc']:
                        if vendor_key in original_pattern:
                            vendor_patterns.append(f"*{vendor_key}*")
                            vendor_extracted = True
                            break

                    # Only process device type mapping if explicitly enabled
                    if use_device_type_mapping:
                        # Map to NetBox roles with wildcards for flexible matching
                        mapped_roles = []
                        for old_pattern, new_role in netbox_role_mapping.items():
                            if old_pattern in original_pattern:
                                # Use wildcards around role names for flexible matching
                                mapped_roles.append(f"*{new_role}*")

                        # If no specific mapping found, try to infer from common patterns
                        if not mapped_roles:
                            if 'switch' in original_pattern:
                                if 'core' in original_pattern or 'nx' in original_pattern:
                                    mapped_roles.append('*Core Switch*')
                                else:
                                    mapped_roles.append('*Switch*')  # Catches Access Switch, Core Switch, etc.
                            elif 'router' in original_pattern:
                                mapped_roles.append('*Router*')
                            elif 'firewall' in original_pattern or 'fw' in original_pattern:
                                mapped_roles.append('*Firewall*')
                            elif 'server' in original_pattern:
                                mapped_roles.append('*Server*')
                            elif 'pdu' in original_pattern:
                                mapped_roles.append('*PDU*')
                            elif 'ups' in original_pattern:
                                mapped_roles.append('*UPS*')
                            elif 'access point' in original_pattern or 'ap' in original_pattern:
                                mapped_roles.append('*Access Point*')
                            else:
                                # Keep original pattern with wildcards for manual review
                                if like_match:
                                    pattern_with_wildcards = like_match.group(1).replace('%', '*')
                                    mapped_roles.append(
                                        f"*{pattern_with_wildcards}*" if not pattern_with_wildcards.startswith(
                                            '*') else pattern_with_wildcards)
                                else:
                                    mapped_roles.append(f"*{original_pattern}*")

                        device_type_patterns.extend(mapped_roles)

            # Parse Vendor conditions
            elif 'vendor' in condition.lower():
                like_match = re.search(r'like\s+["\']([^"\']+)["\']', condition, re.IGNORECASE)
                eq_match = re.search(r'=\s+["\']([^"\']+)["\']', condition, re.IGNORECASE)

                if like_match:
                    pattern = like_match.group(1).replace('%', '*').lower()
                    # Normalize vendor names with wildcards for better matching
                    vendor_mapping = {
                        '*cisco*': '*cisco*',
                        'cisco': '*cisco*',
                        '*arista*': '*arista*',
                        'arista': '*arista*',
                        '*aruba*': '*aruba*',
                        'aruba': '*aruba*',
                        '*palo*': '*palo*',
                        'palo': '*palo*',
                        '*dell*': '*dell*',
                        'dell': '*dell*',
                        '*apc*': '*apc*',
                        'apc': '*apc*',
                        '*cloudgenix*': '*cloudgenix*',
                        'cloudgenix': '*cloudgenix*'
                    }
                    vendor_patterns.append(
                        vendor_mapping.get(pattern, f"*{pattern}*" if not pattern.startswith('*') else pattern))
                elif eq_match:
                    pattern = eq_match.group(1).lower()
                    vendor_mapping = {
                        'cisco': '*cisco*',
                        'arista': '*arista*',
                        'aruba': '*aruba*',
                        'palo': '*palo*',
                        'dell': '*dell*',
                        'apc': '*apc*',
                        'cloudgenix': '*cloudgenix*'
                    }
                    vendor_patterns.append(vendor_mapping.get(pattern, f"*{pattern}*"))

            # Parse Hostname conditions
            elif 'hostname' in condition.lower():
                like_match = re.search(r'like\s+["\']([^"\']+)["\']', condition, re.IGNORECASE)
                if like_match:
                    pattern = like_match.group(1).replace('%', '*')
                    hostname_patterns.append(pattern)

        # Combine patterns
        if device_type_patterns:
            # Remove duplicates while preserving order
            unique_types = []
            for dt in device_type_patterns:
                if dt not in unique_types:
                    unique_types.append(dt)
            filters['device_type'] = '|'.join(unique_types) if len(unique_types) > 1 else unique_types[0]

        if vendor_patterns:
            unique_vendors = []
            for v in vendor_patterns:
                if v not in unique_vendors:
                    unique_vendors.append(v)
            filters['vendor'] = '|'.join(unique_vendors) if len(unique_vendors) > 1 else unique_vendors[0]

        if hostname_patterns:
            filters['name'] = '|'.join(hostname_patterns) if len(hostname_patterns) > 1 else hostname_patterns[0]

        return filters

    def detect_vendor_from_cmd_type(self, cmd_type: str) -> str:
        """Detect vendor from command type"""
        cmd_lower = cmd_type.lower()

        if cmd_lower.startswith('cisco_'):
            return 'cisco'
        elif cmd_lower.startswith('arista_'):
            return 'arista'
        elif cmd_lower.startswith('aruba_'):
            return 'aruba'
        elif cmd_lower.startswith('paloalto_'):
            return 'paloalto'
        elif cmd_lower.startswith('ion_'):
            return 'cloudgenix'
        else:
            return 'generic'

    def get_command_text(self, cmd_type: str) -> str:
        """Convert command type to actual command text"""
        return self.cmd_mappings.get(cmd_type, f"# Unknown command type: {cmd_type}")

    def convert_job_definition(self, job_id: str, job_def: Dict[str, Any], use_device_type_mapping: bool = False) -> \
    Dict[str, Any]:
        """Convert a single job definition from old to new format"""

        # Parse the SQL query to extract filters
        filters = self.parse_sql_conditions(job_def['query'], use_device_type_mapping)

        # Detect vendor from command type
        vendor = self.detect_vendor_from_cmd_type(job_def['cmd_type'])

        # Get the actual command text
        command_text = self.get_command_text(job_def['cmd_type'])

        # Create the new job definition
        new_job = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "session_file": "sessions.yaml",  # Default - user may need to adjust
            "vendor": {
                "selected": vendor.title(),
                "auto_paging": True
            },
            "credentials": {
                "username": "el-admin",  # Default - user may need to adjust
                "credential_system": "Auto-detect from script",
                "password_provided": False,
                "enable_password_provided": False
            },
            "filters": filters,
            "commands": {
                "template": f"{vendor.title()} Command Template",
                "command_text": command_text,
                "output_directory": job_def['destination']
            },
            "execution": {
                "batch_script": "batch_spn_concurrent.py (Multi-process)",
                "max_workers": 12,
                "verbose": False,
                "dry_run": False
            },
            "ui_state": {
                "current_tab": 0
            },
            "legacy_info": {
                "original_job_id": job_id,
                "original_query": job_def['query'],
                "original_cmd_type": job_def['cmd_type'],
                "vrf_support": job_def.get('vrf_support', False)
            }
        }

        return new_job


class JobConverter:
    """Main converter class"""

    def __init__(self):
        self.parser = SQLQueryParser()

    def load_legacy_jobs(self, legacy_file: str) -> Dict[str, Any]:
        """Load legacy job definitions"""
        with open(legacy_file, 'r') as f:
            content = f.read()

        # Clean up the content - remove outer braces if present
        content = content.strip()
        if content.startswith('{') and content.endswith('}'):
            content = content[1:-1].strip()

        # Add proper JSON structure
        json_content = '{' + content + '}'

        try:
            return json.loads(json_content)
        except json.JSONDecodeError as e:
            print(f"Error parsing legacy jobs file: {e}")
            return {}

    def convert_all_jobs(self, legacy_jobs: Dict[str, Any], output_dir: str, use_device_type_mapping: bool = False) -> \
    Tuple[List[str], str]:
        """Convert all job definitions and create output files"""

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        job_files = []

        for job_id, job_def in legacy_jobs.items():
            try:
                # Convert the job definition
                new_job = self.parser.convert_job_definition(job_id, job_def, use_device_type_mapping)

                # Create filename based on destination and command type
                destination = job_def['destination']
                cmd_type = job_def['cmd_type']
                vendor = self.parser.detect_vendor_from_cmd_type(cmd_type)

                filename = f"job_{job_id}_{vendor}_{destination}.json"
                filepath = os.path.join(output_dir, filename)

                # Save the job file
                with open(filepath, 'w') as f:
                    json.dump(new_job, f, indent=2)

                job_files.append(filename)
                print(f"Converted job {job_id}: {filename}")

            except Exception as e:
                print(f"Error converting job {job_id}: {e}")
                continue

        # Create the job batch list file
        batch_list_file = os.path.join(output_dir, "job_batch_list.txt")
        with open(batch_list_file, 'w') as f:
            f.write("# Converted Legacy Job Batch List\n")
            f.write(f"# Generated on {datetime.now().isoformat()}\n")
            f.write("# Original SQL-based job definitions converted to JSON format\n\n")

            # Group by destination for better organization
            jobs_by_dest = {}
            for job_id, job_def in legacy_jobs.items():
                dest = job_def['destination']
                if dest not in jobs_by_dest:
                    jobs_by_dest[dest] = []
                jobs_by_dest[dest].append(job_id)

            for destination, job_ids in sorted(jobs_by_dest.items()):
                f.write(f"# {destination.upper()} jobs\n")
                for job_id in sorted(job_ids):
                    if job_id in [jf.split('_')[1] for jf in job_files]:
                        # Find the corresponding filename
                        matching_files = [jf for jf in job_files if f"job_{job_id}_" in jf]
                        if matching_files:
                            f.write(f"{matching_files[0]}\n")
                f.write("\n")

        return job_files, batch_list_file

    def generate_summary(self, legacy_jobs: Dict[str, Any], job_files: List[str], output_dir: str):
        """Generate a conversion summary"""

        # Analyze the conversion
        summary = {
            "conversion_timestamp": datetime.now().isoformat(),
            "total_legacy_jobs": len(legacy_jobs),
            "total_converted_jobs": len(job_files),
            "conversion_success_rate": f"{(len(job_files) / len(legacy_jobs) * 100):.1f}%",
            "jobs_by_vendor": {},
            "jobs_by_destination": {},
            "command_types_found": set(),
            "potential_issues": []
        }

        for job_id, job_def in legacy_jobs.items():
            vendor = self.parser.detect_vendor_from_cmd_type(job_def['cmd_type'])
            destination = job_def['destination']
            cmd_type = job_def['cmd_type']

            # Count by vendor
            summary["jobs_by_vendor"][vendor] = summary["jobs_by_vendor"].get(vendor, 0) + 1

            # Count by destination
            summary["jobs_by_destination"][destination] = summary["jobs_by_destination"].get(destination, 0) + 1

            # Track command types
            summary["command_types_found"].add(cmd_type)

            # Check for potential issues
            if cmd_type not in self.parser.cmd_mappings:
                summary["potential_issues"].append(f"Unknown command type in job {job_id}: {cmd_type}")

            # Check for complex SQL that might not convert well
            query = job_def['query'].lower()
            if 'join' in query or 'union' in query or 'subquery' in query:
                summary["potential_issues"].append(f"Complex SQL in job {job_id} may not convert accurately")

        # Convert set to list for JSON serialization
        summary["command_types_found"] = sorted(list(summary["command_types_found"]))

        # Save summary
        summary_file = os.path.join(output_dir, "conversion_summary.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        # Print summary to console
        print("\n" + "=" * 60)
        print("CONVERSION SUMMARY")
        print("=" * 60)
        print(f"Legacy jobs found: {summary['total_legacy_jobs']}")
        print(f"Jobs converted: {summary['total_converted_jobs']}")
        print(f"Success rate: {summary['conversion_success_rate']}")
        print(f"\nJobs by vendor:")
        for vendor, count in sorted(summary['jobs_by_vendor'].items()):
            print(f"  {vendor}: {count}")
        print(f"\nJobs by destination:")
        for dest, count in sorted(summary['jobs_by_destination'].items()):
            print(f"  {dest}: {count}")

        if summary['potential_issues']:
            print(f"\nPotential issues found:")
            for issue in summary['potential_issues'][:10]:  # Show first 10
                print(f"  - {issue}")
            if len(summary['potential_issues']) > 10:
                print(f"  ... and {len(summary['potential_issues']) - 10} more (see conversion_summary.json)")


def main():
    parser = argparse.ArgumentParser(
        description="Convert legacy SQL-based job definitions to new JSON format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s legacy_jobs.json
  %(prog)s legacy_jobs.json --output-dir converted_jobs
  %(prog)s legacy_jobs.json --output-dir jobs --username myuser --map-device-types

The converter will:
1. Parse SQL WHERE clauses and convert to filter syntax
2. Map command types to actual commands
3. Generate individual JSON job files
4. Create a job batch list file
5. Provide a conversion summary

Note: You may need to manually review and adjust:
- Session file paths
- Username credentials
- Complex SQL queries that don't convert perfectly
- Custom command types not in the mapping
        """
    )

    parser.add_argument(
        'legacy_file',
        help='Legacy job definitions file (JSON format with SQL queries)'
    )

    parser.add_argument(
        '--output-dir', '-o',
        default='converted_jobs',
        help='Output directory for converted job files (default: converted_jobs)'
    )

    parser.add_argument(
        '--username', '-u',
        default='el-admin',
        help='Default username for job credentials (default: el-admin)'
    )

    parser.add_argument(
        '--session-file', '-s',
        default='sessions.yaml',
        help='Default session file name (default: sessions.yaml)'
    )

    parser.add_argument(
        '--map-device-types',
        action='store_true',
        help='Enable device type mapping from legacy DeviceType to NetBox roles (default: False)'
    )

    parser.add_argument(
        '--create-sample',
        action='store_true',
        help='Create a sample job list file and exit'
    )

    args = parser.parse_args()

    # Handle sample creation
    if args.create_sample:
        create_sample_job_list()
        return 0

    # Validate arguments
    if not args.legacy_file:
        parser.error("legacy_file is required (or use --create-sample)")

    if not os.path.exists(args.legacy_file):
        print(f"Error: Legacy file not found: {args.legacy_file}")
        return 1

    try:
        # Initialize converter
        converter = JobConverter()

        # Update default username if provided
        if args.username != 'el-admin':
            converter.parser.default_username = args.username

        print(f"Loading legacy job definitions from {args.legacy_file}...")
        legacy_jobs = converter.load_legacy_jobs(args.legacy_file)

        if not legacy_jobs:
            print("No legacy jobs found or file could not be parsed.")
            return 1

        print(f"Found {len(legacy_jobs)} legacy job definitions")

        print(f"Converting jobs to new format in {args.output_dir}...")
        print(f"Device type mapping: {'ENABLED' if args.map_device_types else 'DISABLED'}")

        job_files, batch_list_file = converter.convert_all_jobs(legacy_jobs, args.output_dir, args.map_device_types)

        print(f"Generating conversion summary...")
        converter.generate_summary(legacy_jobs, job_files, args.output_dir)

        print(f"\nConversion complete!")
        print(f"Output files:")
        print(f"  Job files: {args.output_dir}/ ({len(job_files)} files)")
        print(f"  Batch list: {batch_list_file}")
        print(f"  Summary: {os.path.join(args.output_dir, 'conversion_summary.json')}")

        print(f"\nNext steps:")
        print(f"1. Review converted job files in {args.output_dir}/")
        print(f"2. Adjust session file paths and credentials as needed")
        print(f"3. Test with: python run_jobs_batch.py {batch_list_file}")

        return 0

    except Exception as e:
        print(f"Conversion failed: {e}")
        return 1


def create_sample_job_list():
    """Create a sample job list file for demonstration"""
    sample_content = """# Network Job Batch List
# Lines starting with # are comments
# List one job configuration file per line

# Configuration backup jobs
job1.json
job2.json

# Inventory collection jobs  
job3_interface_status.json
job4_system_info.json

# You can use absolute paths too:
# /path/to/special_job.json
"""

    with open('sample_job_list.txt', 'w') as f:
        f.write(sample_content)

    print("Created sample_job_list.txt")


if __name__ == "__main__":
    import sys

    sys.exit(main())