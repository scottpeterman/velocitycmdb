#!/usr/bin/env python3
"""
Async SNMP Uptime Collector
Collects device uptime information via SNMP and saves to JSON.
Uses pysnmp v7 v3arch.asyncio API for efficient parallel querying.

Supports both SQLite database and CSV file as device sources.
"""

import asyncio
import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

# Standard SNMP OIDs
OID_SYSNAME = "1.3.6.1.2.1.1.5.0"  # SNMPv2-MIB::sysName
OID_SYSDESCR = "1.3.6.1.2.1.1.1.0"  # SNMPv2-MIB::sysDescr
OID_SYSUPTIME = "1.3.6.1.2.1.1.3.0"  # SNMPv2-MIB::sysUpTime (TimeTicks)
OID_SYSLOCATION = "1.3.6.1.2.1.1.6.0"  # SNMPv2-MIB::sysLocation


def format_uptime(timeticks: int) -> str:
    """
    Convert SNMP TimeTicks (hundredths of seconds) to human readable format.

    Args:
        timeticks: TimeTicks value from SNMP sysUpTime

    Returns:
        Human readable uptime string (e.g., "45 days, 3:14:52")
    """
    seconds = timeticks // 100
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if days > 0:
        return f"{days} days, {hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def calculate_uptime_days(timeticks: int) -> float:
    """Calculate uptime in days from TimeTicks."""
    seconds = timeticks // 100
    return seconds / 86400


class DeviceInfo:
    """Container for device information from database."""

    def __init__(self, device_id: int, name: str, management_ip: str,
                 model: Optional[str] = None, os_version: Optional[str] = None,
                 vendor: Optional[str] = None, site_code: Optional[str] = None,
                 role: Optional[str] = None):
        self.device_id = device_id
        self.name = name
        self.management_ip = management_ip
        self.model = model
        self.os_version = os_version
        self.vendor = vendor
        self.site_code = site_code
        self.role = role


class UptimeCollector:
    """Async SNMP uptime collector."""

    def __init__(self, communities: List[str], timeout: int = 5,
                 retries: int = 1, max_concurrent: int = 50):
        """
        Initialize the uptime collector.

        Args:
            communities: List of SNMP community strings to try
            timeout: SNMP timeout in seconds
            retries: Number of retries per community
            max_concurrent: Maximum concurrent SNMP queries
        """
        self.communities = communities
        self.timeout = timeout
        self.retries = retries
        self.max_concurrent = max_concurrent
        self.snmp_engine = SnmpEngine()
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def query_device(self, device: DeviceInfo) -> Dict:
        """
        Query a single device with all configured communities.

        Args:
            device: DeviceInfo object containing device details

        Returns:
            Dictionary with device information and SNMP results
        """
        async with self.semaphore:
            result = {
                "device_id": device.device_id,
                "hostname": device.name,
                "management_ip": device.management_ip,
                "model": device.model,
                "os_version": device.os_version,
                "vendor": device.vendor,
                "site_code": device.site_code,
                "role": device.role,
                "snmp_success": False,
                "snmp_community_used": None,
                "sysname": None,
                "sysdescr": None,
                "syslocation": None,
                "uptime_timeticks": None,
                "uptime_formatted": None,
                "uptime_days": None,
                "collection_timestamp": datetime.now().isoformat(),
                "error": None
            }

            # Try each community string
            for community in self.communities:
                try:
                    success = await self._try_community(device, community, result)
                    if success:
                        result["snmp_community_used"] = community
                        result["snmp_success"] = True
                        print(f"✓ {device.name} ({device.management_ip}) - "
                              f"Uptime: {result['uptime_formatted']}")
                        break
                except Exception as e:
                    continue

            if not result["snmp_success"]:
                result["error"] = "All communities failed or device unreachable"
                print(f"✗ {device.name} ({device.management_ip}) - SNMP failed")

            return result

    async def _try_community(self, device: DeviceInfo, community: str,
                             result: Dict) -> bool:
        """
        Try querying device with a specific community string.

        Args:
            device: DeviceInfo object
            community: SNMP community string to try
            result: Result dictionary to populate

        Returns:
            True if successful, False otherwise
        """
        try:
            target = await UdpTransportTarget.create(
                (device.management_ip, 161),
                timeout=self.timeout,
                retries=self.retries
            )

            error_indication, error_status, error_index, var_binds = await get_cmd(
                self.snmp_engine,
                CommunityData(community, mpModel=1),  # SNMPv2c
                target,
                ContextData(),
                ObjectType(ObjectIdentity(OID_SYSNAME)),
                ObjectType(ObjectIdentity(OID_SYSDESCR)),
                ObjectType(ObjectIdentity(OID_SYSUPTIME)),
                ObjectType(ObjectIdentity(OID_SYSLOCATION)),
            )

            if error_indication:
                return False
            elif error_status:
                return False
            else:
                # Parse results
                for oid, val in var_binds:
                    oid_str = str(oid)
                    val_str = str(val)

                    if OID_SYSNAME in oid_str:
                        result["sysname"] = val_str
                    elif OID_SYSDESCR in oid_str:
                        result["sysdescr"] = val_str
                    elif OID_SYSUPTIME in oid_str:
                        # Extract numeric value from TimeTicks
                        try:
                            timeticks = int(val)
                            result["uptime_timeticks"] = timeticks
                            result["uptime_formatted"] = format_uptime(timeticks)
                            result["uptime_days"] = round(calculate_uptime_days(timeticks), 2)
                        except (ValueError, TypeError):
                            pass
                    elif OID_SYSLOCATION in oid_str:
                        result["syslocation"] = val_str

                return result["uptime_timeticks"] is not None

        except Exception as e:
            return False

    async def collect_all(self, devices: List[DeviceInfo]) -> List[Dict]:
        """
        Collect uptime from all devices concurrently.

        Args:
            devices: List of DeviceInfo objects

        Returns:
            List of result dictionaries
        """
        tasks = [self.query_device(device) for device in devices]
        results = await asyncio.gather(*tasks)
        return results

    def close(self):
        """Clean up SNMP engine resources."""
        self.snmp_engine.close_dispatcher()


def load_devices_from_db(db_path: str, device_filter: Optional[str] = None) -> List[DeviceInfo]:
    """
    Load device information from SQLite database.

    Args:
        db_path: Path to assets.db
        device_filter: Optional filter string to match device names

    Returns:
        List of DeviceInfo objects
    """
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
            d.site_code,
            dr.name as role
        FROM devices d
        LEFT JOIN vendors v ON d.vendor_id = v.id
        LEFT JOIN device_roles dr ON d.role_id = dr.id
        WHERE d.management_ip IS NOT NULL 
        AND d.management_ip != ''
    """

    params = []
    if device_filter:
        query += " AND d.name LIKE ?"
        params.append(f"%{device_filter}%")

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
            site_code=row["site_code"],
            role=row["role"]
        ))

    return devices


def load_devices_from_csv(csv_path: str, device_filter: Optional[str] = None) -> List[DeviceInfo]:
    """
    Load device information from CSV file.

    Expected CSV format (with header):
    id,name,normalized_name,site_code,vendor_id,device_type_id,model,os_version,
    uptime,have_sn,processor_id,ipv4_address,management_ip,role_id,is_stack,
    stack_count,timestamp,source_file,source_system

    Args:
        csv_path: Path to devices CSV file
        device_filter: Optional filter string to match device names

    Returns:
        List of DeviceInfo objects
    """
    # Vendor lookup dictionary (common vendor IDs)
    vendor_map = {
        '1': 'Arista',
        '2': 'Juniper',
        '3': 'Cisco',
        '4': 'HP',
        '5': 'Dell',
        '6': 'Brocade',
        '7': 'Extreme',
        '8': 'Fortinet',
        '9': 'Palo Alto',
        '10': 'F5',
    }

    # Role lookup dictionary (common role IDs)
    role_map = {
        '1': 'Core Router',
        '2': 'Edge Router',
        '3': 'Distribution Switch',
        '4': 'Access Switch',
        '5': 'ToR Switch',
        '6': 'Spine Switch',
        '7': 'Leaf Switch',
        '8': 'Firewall',
        '9': 'Load Balancer',
        '10': 'WAN Router',
    }

    devices = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Skip devices without management IP
            mgmt_ip = row.get('management_ip', '').strip()
            if not mgmt_ip:
                continue

            device_name = row.get('name', '').strip()

            # Apply device filter if specified
            if device_filter and device_filter.lower() not in device_name.lower():
                continue

            # Extract vendor name from vendor_id
            vendor_id = row.get('vendor_id', '').strip()
            vendor = vendor_map.get(vendor_id, f'Vendor_{vendor_id}' if vendor_id else None)

            # Extract role name from role_id
            role_id = row.get('role_id', '').strip()
            role = role_map.get(role_id, f'Role_{role_id}' if role_id else None)

            # Create DeviceInfo object
            try:
                device_id = int(row.get('id', 0))
            except (ValueError, TypeError):
                device_id = 0

            devices.append(DeviceInfo(
                device_id=device_id,
                name=device_name,
                management_ip=mgmt_ip,
                model=row.get('model', '').strip() or None,
                os_version=row.get('os_version', '').strip() or None,
                vendor=vendor,
                site_code=row.get('site_code', '').strip() or None,
                role=role
            ))

    # Sort by name
    devices.sort(key=lambda d: d.name)

    return devices


def save_results(results: List[Dict], output_file: str, pretty: bool = True):
    """
    Save results to JSON file.

    Args:
        results: List of result dictionaries
        output_file: Output file path
        pretty: Whether to pretty-print JSON
    """
    output_data = {
        "collection_timestamp": datetime.now().isoformat(),
        "total_devices": len(results),
        "successful_queries": sum(1 for r in results if r["snmp_success"]),
        "failed_queries": sum(1 for r in results if not r["snmp_success"]),
        "devices": results
    }

    with open(output_file, 'w') as f:
        if pretty:
            json.dump(output_data, f, indent=2)
        else:
            json.dump(output_data, f)

    print(f"\n✓ Results saved to {output_file}")


def print_summary(results: List[Dict]):
    """Print summary statistics."""
    total = len(results)
    successful = sum(1 for r in results if r["snmp_success"])
    failed = total - successful

    print("\n" + "=" * 60)
    print("COLLECTION SUMMARY")
    print("=" * 60)
    print(f"Total devices queried: {total}")
    print(f"Successful queries:    {successful} ({successful / total * 100:.1f}%)")
    print(f"Failed queries:        {failed} ({failed / total * 100:.1f}%)")

    if successful > 0:
        # Uptime statistics
        uptimes = [r["uptime_days"] for r in results if r["uptime_days"] is not None]

        ranges = {
            "< 1 day": sum(1 for u in uptimes if u < 1),
            "1-7 days": sum(1 for u in uptimes if 1 <= u < 7),
            "1-4 weeks": sum(1 for u in uptimes if 7 <= u < 30),
            "1-6 months": sum(1 for u in uptimes if 30 <= u < 180),
            "6-12 months": sum(1 for u in uptimes if 180 <= u < 365),
            "> 1 year": sum(1 for u in uptimes if u >= 365)
        }

        print("\nUPTIME DISTRIBUTION")
        print("-" * 60)
        for range_name, count in ranges.items():
            if count > 0:
                print(f"{range_name:15s}: {count:3d} devices ({count / len(uptimes) * 100:5.1f}%)")

        avg_uptime = sum(uptimes) / len(uptimes)
        print(f"\nAverage uptime: {avg_uptime:.1f} days")
        print(f"Maximum uptime: {max(uptimes):.1f} days")
        print(f"Minimum uptime: {min(uptimes):.1f} days")


async def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Collect device uptime information via SNMP from database or CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using database
  %(prog)s --db assets.db --communities public,private --output uptimes.json
  %(prog)s --db assets.db -c public -c internal --device-filter rtr

  # Using CSV file
  %(prog)s --csv devices.csv -c public --output uptimes.json
  %(prog)s --csv devices.csv -c public --device-filter edge

  # Performance tuning
  %(prog)s --csv devices.csv -c public --max-concurrent 100
        """
    )

    # Source selection (mutually exclusive)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--db",
        help="Path to assets.db SQLite database"
    )
    source_group.add_argument(
        "--csv",
        help="Path to devices CSV file (exported from devices table)"
    )

    parser.add_argument(
        "-c", "--communities",
        action="append",
        required=True,
        help="SNMP community string(s) to try (can specify multiple times)"
    )

    parser.add_argument(
        "-o", "--output",
        default="device_uptimes.json",
        help="Output JSON file (default: device_uptimes.json)"
    )

    parser.add_argument(
        "--device-filter",
        help="Filter devices by name (case-insensitive substring match)"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="SNMP timeout in seconds (default: 5)"
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="SNMP retries per community (default: 1)"
    )

    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=50,
        help="Maximum concurrent SNMP queries (default: 50)"
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: True)"
    )

    args = parser.parse_args()

    # Determine source and load devices
    if args.db:
        # Validate database exists
        db_path = Path(args.db)
        if not db_path.exists():
            print(f"Error: Database file not found: {args.db}", file=sys.stderr)
            sys.exit(1)

        print(f"Loading devices from database: {args.db}...")
        if args.device_filter:
            print(f"Applying filter: name contains '{args.device_filter}'")

        devices = load_devices_from_db(str(db_path), args.device_filter)
        source_type = "database"
        source_path = args.db

    else:  # args.csv
        # Validate CSV exists
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"Error: CSV file not found: {args.csv}", file=sys.stderr)
            sys.exit(1)

        print(f"Loading devices from CSV: {args.csv}...")
        if args.device_filter:
            print(f"Applying filter: name contains '{args.device_filter}'")

        devices = load_devices_from_csv(str(csv_path), args.device_filter)
        source_type = "csv"
        source_path = args.csv

    if not devices:
        print("No devices found matching criteria.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(devices)} devices to query")
    print(f"Communities to try: {', '.join(args.communities)}")
    print(f"Max concurrent queries: {args.max_concurrent}")
    print("\nStarting SNMP collection...\n")

    # Create collector and run queries
    collector = UptimeCollector(
        communities=args.communities,
        timeout=args.timeout,
        retries=args.retries,
        max_concurrent=args.max_concurrent
    )

    try:
        start_time = datetime.now()
        results = await collector.collect_all(devices)
        elapsed = (datetime.now() - start_time).total_seconds()

        # Save results
        save_results(results, args.output, pretty=args.pretty)

        # Print summary
        print_summary(results)
        print(f"\nSource: {source_type} ({source_path})")
        print(f"Collection completed in {elapsed:.1f} seconds")
        print(f"Average time per device: {elapsed / len(devices):.2f} seconds")

    finally:
        collector.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(130)