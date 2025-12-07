#!/usr/bin/env python3
"""
Trace exactly what happens when processing a single capture file
"""

import sqlite3
import sys
import re
from pathlib import Path

# Add current directory and parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'pcng'))


def extract_device_info_from_filename(file_path, capture_types):
    """
    Replicated from CaptureLoader to avoid import issues
    Extract device info from capture filename
    """
    filename = file_path.name
    parent_dir = file_path.parent.name

    # Remove common extensions
    name_without_ext = re.sub(r'\.(txt|log|cfg|conf)$', '', filename, flags=re.IGNORECASE)

    # Pattern 1: parent directory is capture type
    if parent_dir in capture_types:
        capture_type = parent_dir
        device_part = name_without_ext
    else:
        # Pattern 2: capture type in filename
        capture_type = None
        for ct in capture_types:
            patterns = [
                f'_{ct}$',
                f'_{ct}_',
                f'\\.{ct}$',
                f'_{ct.replace("-", "_")}$',
                f'_{ct.replace("-", "-")}$'
            ]

            for pattern in patterns:
                if re.search(pattern, name_without_ext, re.IGNORECASE):
                    capture_type = ct
                    device_part = re.sub(pattern, '', name_without_ext, flags=re.IGNORECASE)
                    break

            if capture_type:
                break

        if not capture_type:
            return None

    # Extract site code from device name (device.siteXX pattern)
    site_match = re.search(r'\.([a-z]{3,4}\d+)$', device_part, re.IGNORECASE)
    if site_match:
        site_code = site_match.group(1).upper()
        device_name = device_part.lower()
    else:
        site_code = "UNKNOWN"
        device_name = device_part.lower()

    return site_code, device_name, capture_type


def trace_single_file(file_path, db_path='assets.db'):
    """Trace processing of a single file"""

    file_path = Path(file_path)

    print(f"\n{'=' * 80}")
    print(f"TRACING FILE: {file_path}")
    print(f"{'=' * 80}\n")

    # Step 1: Check if file exists
    print(f"1. File exists: {file_path.exists()}")
    if not file_path.exists():
        print("   ✗ FILE NOT FOUND - stopping")
        return

    # Step 2: Extract device info
    CAPTURE_TYPES = [
        'arp', 'authentication', 'authorization', 'bgp-neighbor', 'bgp-summary',
        'bgp-table', 'bgp-table-detail', 'cdp', 'cdp-detail', 'configs',
        'console', 'eigrp-neighbor', 'int-status', 'interface-status',
        'inventory', 'ip_ssh', 'lldp', 'lldp-detail', 'mac', 'ntp_status',
        'ospf-neighbor', 'port-channel', 'routes', 'snmp_server', 'syslog',
        'tacacs', 'version'
    ]

    print(f"\n2. Extracting device info from filename...")
    device_info = extract_device_info_from_filename(file_path, CAPTURE_TYPES)

    if device_info:
        site_code, device_name, capture_type = device_info
        print(f"   ✓ Extracted successfully:")
        print(f"     - Device name: '{device_name}'")
        print(f"     - Site code: '{site_code}'")
        print(f"     - Capture type: '{capture_type}'")
    else:
        print(f"   ✗ FAILED to extract device info - stopping")
        return

    # Step 3: Check database for device
    print(f"\n3. Looking up device in database...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Show what we're searching for
    print(f"   Searching for:")
    print(f"     - normalized_name = '{device_name}'")
    print(f"     - site_code = '{site_code}'")

    # Try the exact query that the loader uses
    if site_code and site_code != "UNKNOWN":
        cursor.execute("""
            SELECT id, name, normalized_name, site_code
            FROM devices 
            WHERE normalized_name = ? AND site_code = ?
        """, (device_name, site_code))
    else:
        cursor.execute("""
            SELECT id, name, normalized_name, site_code
            FROM devices 
            WHERE normalized_name = ?
        """, (device_name,))

    result = cursor.fetchone()

    if result:
        print(f"   ✓ FOUND device in database:")
        print(f"     - ID: {result['id']}")
        print(f"     - Name: {result['name']}")
        print(f"     - Normalized name: {result['normalized_name']}")
        print(f"     - Site code: {result['site_code']}")
    else:
        print(f"   ✗ NOT FOUND in database")

        # Try to find similar devices
        print(f"\n   Looking for similar devices...")

        # Search by site only
        cursor.execute("""
            SELECT id, name, normalized_name, site_code
            FROM devices 
            WHERE site_code = ?
            ORDER BY name
        """, (site_code,))

        site_devices = cursor.fetchall()
        if site_devices:
            print(f"   Devices in site '{site_code}':")
            for dev in site_devices:
                print(f"     - {dev['normalized_name']:<30} (name: {dev['name']}, ID: {dev['id']})")
        else:
            print(f"   No devices found in site '{site_code}'")

        # Search by partial name match
        cursor.execute("""
            SELECT id, name, normalized_name, site_code
            FROM devices 
            WHERE normalized_name LIKE ? OR name LIKE ?
            ORDER BY name
        """, (f"%{device_name.split('.')[0]}%", f"%{device_name.split('.')[0]}%"))

        partial_matches = cursor.fetchall()
        if partial_matches:
            print(f"\n   Devices with similar names:")
            for dev in partial_matches:
                print(f"     - {dev['normalized_name']:<30} (site: {dev['site_code']}, ID: {dev['id']})")

    # Step 4: Show all devices (if few enough)
    cursor.execute("SELECT COUNT(*) as count FROM devices")
    total_devices = cursor.fetchone()['count']

    print(f"\n4. Database contains {total_devices} total devices")

    if total_devices <= 30:
        print(f"\n   All devices in database:")
        cursor.execute("""
            SELECT id, name, normalized_name, site_code
            FROM devices 
            ORDER BY site_code, name
        """)
        for dev in cursor.fetchall():
            print(f"     {dev['id']:<4} | {dev['normalized_name']:<35} | {dev['site_code']:<8} | {dev['name']}")

    conn.close()

    print(f"\n{'=' * 80}")
    print(f"CONCLUSION")
    print(f"{'=' * 80}")

    if result:
        print(f"✓ This file SHOULD be loaded successfully")
        print(f"  Device ID: {result['id']}")
    else:
        print(f"✗ This file WILL NOT be loaded")
        print(f"  Reason: Device '{device_name}' with site '{site_code}' not found in database")
        print(f"\n  TO FIX:")
        print(f"  1. Check if device name format matches between database and capture files")
        print(f"  2. Verify site_code is correct in database")
        print(f"  3. Check normalized_name field in database")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python trace_file.py <file_path> [db_path]")
        print("\nExample: python trace_file.py pcng/capture/configs/edge1-01.txt ../assets.db")
        sys.exit(1)

    file_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else 'assets.db'

    trace_single_file(file_path, db_path)