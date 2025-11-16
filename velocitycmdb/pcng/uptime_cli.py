#!/usr/bin/env python3
"""
CLI Uptime Collector
Collects accurate device uptimes via SSH CLI commands.
Solves SNMP counter wrap issues by parsing actual CLI output.

Uses the proven SSH pattern from pni_collector.py
"""

import json
import sys
import argparse
import logging
import re
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import sqlite3
import csv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DeviceInfo:
    """Container for device information"""

    def __init__(self, device_id: int, name: str, management_ip: str,
                 model: Optional[str] = None, os_version: Optional[str] = None,
                 vendor: Optional[str] = None, site_code: Optional[str] = None):
        self.device_id = device_id
        self.name = name
        self.management_ip = management_ip
        self.model = model
        self.os_version = os_version
        self.vendor = vendor
        self.site_code = site_code


class CLIUptimeCollector:
    """Collects device uptimes via SSH CLI"""

    def __init__(self, ssh_key_path: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None,
                 domain_suffix: str = 'kentik.com', debug: bool = False):
        self.ssh_key_path = ssh_key_path
        self.username = username
        self.password = password
        self.domain_suffix = domain_suffix
        self.debug = debug

        if self.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        logger.info("\n" + "=" * 60)
        logger.info("DOMAIN CONFIGURATION")
        logger.info("=" * 60)
        logger.info("Domain Suffix: {}".format(self.domain_suffix))
        logger.info("Device names will be resolved as: <device>.{}".format(self.domain_suffix))
        logger.info("=" * 60 + "\n")

    def _build_fqdn(self, device_name: str) -> str:
        """Build FQDN - exact copy from working pni_collector"""
        if device_name.endswith('.{}'.format(self.domain_suffix)):
            return device_name

        parts = device_name.split('.')
        if len(parts) >= 3:
            logger.debug("Device name {} appears to be FQDN, using as-is".format(device_name))
            return device_name

        fqdn = "{}.{}".format(device_name, self.domain_suffix)
        logger.debug("Built FQDN: {} → {}".format(device_name, fqdn))
        return fqdn

    def _get_uptime_command(self, vendor: str) -> str:
        """Get the appropriate uptime command for vendor"""
        vendor_lower = vendor.lower() if vendor else ''

        if 'juniper' in vendor_lower:
            return "show system uptime | no-more"
        elif 'cisco' in vendor_lower:
            return "show version"
        elif 'arista' in vendor_lower:
            return "show version"
        else:
            # Default to Cisco-style
            return "show version"

    def _parse_juniper_uptime(self, output: str) -> Optional[Dict]:
        """
        Parse Juniper 'show system uptime' output

        Example:
        Current time: 2025-10-30 07:55:19 UTC
        System booted: 2016-09-01 22:11:33 UTC (477w6d 09:43 ago)
        """
        # Look for: System booted: ... (477w6d 09:43 ago)
        pattern = r'System booted:.*?\((\d+)w(\d+)d\s+(\d+):(\d+)'
        match = re.search(pattern, output)

        if match:
            weeks = int(match.group(1))
            days = int(match.group(2))
            hours = int(match.group(3))
            minutes = int(match.group(4))

            total_days = (weeks * 7) + days
            uptime_formatted = "{}w{}d {}:{}".format(weeks, days,
                                                     str(hours).zfill(2),
                                                     str(minutes).zfill(2))

            return {
                'uptime_days': total_days,
                'uptime_weeks': weeks,
                'uptime_formatted': uptime_formatted,
                'raw_output': output[:200]
            }

        return None

    def _parse_arista_uptime(self, output: str) -> Optional[Dict]:
        """
        Parse Arista 'show version' output

        Example:
        Uptime: 55 weeks, 1 days, 12 hours and 18 minutes
        """
        # Look for: Uptime: XX weeks, YY days, ZZ hours
        pattern = r'Uptime:\s+(\d+)\s+weeks?,\s+(\d+)\s+days?,\s+(\d+)\s+hours?'
        match = re.search(pattern, output)

        if match:
            weeks = int(match.group(1))
            days = int(match.group(2))
            hours = int(match.group(3))

            total_days = (weeks * 7) + days
            uptime_formatted = "{}w{}d {}h".format(weeks, days, hours)

            return {
                'uptime_days': total_days,
                'uptime_weeks': weeks,
                'uptime_formatted': uptime_formatted,
                'raw_output': output[:200]
            }

        return None

    def _parse_cisco_uptime(self, output: str) -> Optional[Dict]:
        """
        Parse Cisco 'show version' output

        Examples:
        - uptime is 3 years, 45 weeks, 2 days, 14 hours, 32 minutes
        - router01 uptime is 52 weeks, 3 days, 8 hours, 15 minutes
        """
        # Pattern with years
        pattern1 = r'uptime is\s+(\d+)\s+years?,\s+(\d+)\s+weeks?,\s+(\d+)\s+days?'
        match = re.search(pattern1, output)

        if match:
            years = int(match.group(1))
            weeks = int(match.group(2))
            days = int(match.group(3))

            total_days = (years * 365) + (weeks * 7) + days
            uptime_formatted = "{}y{}w{}d".format(years, weeks, days)

            return {
                'uptime_days': total_days,
                'uptime_years': years,
                'uptime_weeks': weeks,
                'uptime_formatted': uptime_formatted,
                'raw_output': output[:200]
            }

        # Pattern without years
        pattern2 = r'uptime is\s+(\d+)\s+weeks?,\s+(\d+)\s+days?'
        match = re.search(pattern2, output)

        if match:
            weeks = int(match.group(1))
            days = int(match.group(2))

            total_days = (weeks * 7) + days
            uptime_formatted = "{}w{}d".format(weeks, days)

            return {
                'uptime_days': total_days,
                'uptime_weeks': weeks,
                'uptime_formatted': uptime_formatted,
                'raw_output': output[:200]
            }

        return None

    def _execute_ssh_command(self, host: str, command: str) -> str:
        """Execute SSH command using subprocess (native SSH)"""
        ssh_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no',
                   '-o', 'ConnectTimeout=10']

        if self.ssh_key_path:
            ssh_cmd.extend(['-i', self.ssh_key_path])

        ssh_cmd.append('{}@{}'.format(self.username, host))
        ssh_cmd.append(command)

        logger.debug("  SSH command: {}".format(' '.join(ssh_cmd)))

        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            raise Exception("SSH command failed: {}".format(result.stderr))

        return result.stdout

    def collect_device_uptime(self, device: DeviceInfo) -> Dict:
        """Collect uptime from a single device via CLI"""

        fqdn = self._build_fqdn(device.name)
        logger.info("Collecting uptime from {}...".format(fqdn))

        result = {
            'device_id': device.device_id,
            'hostname': device.name,
            'management_ip': device.management_ip,
            'model': device.model,
            'os_version': device.os_version,
            'vendor': device.vendor,
            'site_code': device.site_code,
            'collection_method': 'cli',
            'cli_success': False,
            'uptime_days': None,
            'uptime_formatted': None,
            'uptime_source': 'cli',
            'collection_timestamp': datetime.now().isoformat(),
            'error': None
        }

        try:
            # Get appropriate command for vendor
            command = self._get_uptime_command(device.vendor or '')
            logger.debug("  Executing: {}".format(command))

            # Execute via native SSH
            output = self._execute_ssh_command(fqdn, command)

            # Parse output based on vendor
            parsed = None
            vendor_lower = (device.vendor or '').lower()

            if 'juniper' in vendor_lower:
                parsed = self._parse_juniper_uptime(output)
            elif 'arista' in vendor_lower:
                parsed = self._parse_arista_uptime(output)
            elif 'cisco' in vendor_lower:
                parsed = self._parse_cisco_uptime(output)

            if parsed:
                result['cli_success'] = True
                result['uptime_days'] = parsed['uptime_days']
                result['uptime_formatted'] = parsed['uptime_formatted']
                if 'uptime_weeks' in parsed:
                    result['uptime_weeks'] = parsed['uptime_weeks']
                if 'uptime_years' in parsed:
                    result['uptime_years'] = parsed['uptime_years']
                result['cli_raw_output'] = parsed['raw_output']

                logger.info("✓ {} - Uptime: {} ({} days)".format(
                    device.name, parsed['uptime_formatted'], parsed['uptime_days']))
            else:
                result['error'] = "Could not parse uptime from CLI output"
                logger.warning("✗ {} - Failed to parse uptime".format(device.name))

        except Exception as e:
            result['error'] = str(e)
            result['error_type'] = type(e).__name__
            logger.error("✗ {} - SSH failed: {}".format(device.name, str(e)))

        return result

    def collect_all(self, devices: List[DeviceInfo]) -> List[Dict]:
        """Collect uptimes from all devices"""
        results = []

        for i, device in enumerate(devices):
            logger.info("\n[{}/{}] Processing {}".format(i + 1, len(devices), device.name))
            result = self.collect_device_uptime(device)
            results.append(result)

        return results


def load_devices_from_db(db_path: str, device_filter: Optional[str] = None) -> List[DeviceInfo]:
    """Load devices from SQLite database"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT 
            d.id,
            d.name,
            d.management_ip,
            d.model,
            d.os_version,
            v.name as vendor,
            d.site_code
        FROM devices d
        LEFT JOIN vendors v ON d.vendor_id = v.id
        WHERE d.management_ip IS NOT NULL AND d.management_ip != ''
    """

    params = []
    if device_filter:
        query += " AND d.name LIKE ?"
        params.append("%{}%".format(device_filter))

    query += " ORDER BY d.name"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    devices = []
    for row in rows:
        devices.append(DeviceInfo(
            device_id=row["id"],
            name=row["name"],
            management_ip=row["management_ip"],
            model=row["model"],
            os_version=row["os_version"],
            vendor=row["vendor"],
            site_code=row["site_code"]
        ))

    return devices


def load_devices_from_csv(csv_path: str, device_filter: Optional[str] = None) -> List[DeviceInfo]:
    """Load devices from CSV file"""
    vendor_map = {
        '1': 'Arista', '2': 'Juniper', '3': 'Cisco', '4': 'HP', '5': 'Dell'
    }

    devices = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mgmt_ip = row.get('management_ip', '').strip()
            if not mgmt_ip:
                continue

            device_name = row.get('name', '').strip()
            if device_filter and device_filter.lower() not in device_name.lower():
                continue

            vendor_id = row.get('vendor_id', '').strip()
            vendor = vendor_map.get(vendor_id, 'Unknown')

            devices.append(DeviceInfo(
                device_id=int(row.get('id', 0)),
                name=device_name,
                management_ip=mgmt_ip,
                model=row.get('model', '').strip() or None,
                os_version=row.get('os_version', '').strip() or None,
                vendor=vendor,
                site_code=row.get('site_code', '').strip() or None
            ))

    devices.sort(key=lambda d: d.name)
    return devices


def save_results(results: List[Dict], output_file: str):
    """Save results to JSON"""
    output_data = {
        "collection_timestamp": datetime.now().isoformat(),
        "collection_method": "cli",
        "total_devices": len(results),
        "successful_collections": sum(1 for r in results if r["cli_success"]),
        "failed_collections": sum(1 for r in results if not r["cli_success"]),
        "devices": results
    }

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    logger.info("\n✓ Results saved to {}".format(output_file))


def print_summary(results: List[Dict]):
    """Print collection summary"""
    total = len(results)
    successful = sum(1 for r in results if r["cli_success"])
    failed = total - successful

    print("\n" + "=" * 60)
    print("CLI UPTIME COLLECTION SUMMARY")
    print("=" * 60)
    print("Total devices: {}".format(total))
    print("Successful:    {} ({:.1f}%)".format(successful, successful / total * 100 if total > 0 else 0))
    print("Failed:        {} ({:.1f}%)".format(failed, failed / total * 100 if total > 0 else 0))

    if successful > 0:
        uptimes = [r["uptime_days"] for r in results if r.get("uptime_days")]
        if uptimes:
            print("\nUptime Statistics:")
            print("  Average: {:.1f} days".format(sum(uptimes) / len(uptimes)))
            print("  Maximum: {:.1f} days".format(max(uptimes)))
            print("  Minimum: {:.1f} days".format(min(uptimes)))

            # Show devices with extremely long uptimes
            long_uptime = [r for r in results if r.get("uptime_days", 0) > 365]
            if long_uptime:
                print("\n⚠️  Devices with >1 year uptime ({})".format(len(long_uptime)))
                for r in long_uptime:
                    print("  {} - {} days".format(r["hostname"], r["uptime_days"]))


def main():
    parser = argparse.ArgumentParser(
        description="CLI-based uptime collector (solves SNMP wrap issues)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Source
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--db', help="Path to assets.db")
    source_group.add_argument('--csv', help="Path to devices CSV")

    # SSH auth (required)
    parser.add_argument('--username', required=True, help="SSH username")
    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument('--ssh-key', help="Path to SSH private key")
    auth_group.add_argument('--password', help="SSH password")

    # Options
    parser.add_argument('--device-filter', help="Filter devices by name")
    parser.add_argument('--domain-suffix', default='kentik.com',
                        help="Domain suffix to append (default: kentik.com)")
    parser.add_argument('-o', '--output', default='cli_uptimes.json',
                        help="Output JSON file")
    parser.add_argument('--debug', action='store_true', help="Debug logging")

    args = parser.parse_args()

    # Load devices
    if args.db:
        if not Path(args.db).exists():
            logger.error("Database not found: {}".format(args.db))
            return 1
        devices = load_devices_from_db(args.db, args.device_filter)
        source = args.db
    else:
        if not Path(args.csv).exists():
            logger.error("CSV not found: {}".format(args.csv))
            return 1
        devices = load_devices_from_csv(args.csv, args.device_filter)
        source = args.csv

    if not devices:
        logger.error("No devices found")
        return 1

    logger.info("Loaded {} devices from {}".format(len(devices), source))
    if args.device_filter:
        logger.info("Filter: {}".format(args.device_filter))

    # Collect
    collector = CLIUptimeCollector(
        ssh_key_path=args.ssh_key,
        username=args.username,
        password=args.password,
        domain_suffix=args.domain_suffix,
        debug=args.debug
    )

    results = collector.collect_all(devices)

    # Save and summarize
    save_results(results, args.output)
    print_summary(results)

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)