#!/usr/bin/env python3
"""
Diagnose what's in the assets.db database
"""
import sqlite3
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python diagnose_database.py assets.db")
    sys.exit(1)

db_path = Path(sys.argv[1])
if not db_path.exists():
    print(f"Error: {db_path} not found")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print(f"Diagnosing: {db_path}")
print("=" * 70)

# Check capture_snapshots table
print("\n1. Checking capture_snapshots table...")
cursor = conn.cursor()

# Count total snapshots
cursor.execute("SELECT COUNT(*) as total FROM capture_snapshots")
total = cursor.fetchone()['total']
print(f"   Total snapshots: {total}")

# Count by capture_type
cursor.execute("""
    SELECT capture_type, COUNT(*) as count 
    FROM capture_snapshots 
    GROUP BY capture_type
    ORDER BY count DESC
""")
print(f"\n   Snapshots by type:")
for row in cursor.fetchall():
    print(f"     {row['capture_type']}: {row['count']}")

# Check lldp-detail snapshots
cursor.execute("""
    SELECT COUNT(*) as count
    FROM capture_snapshots
    WHERE capture_type = 'lldp-detail'
""")
lldp_count = cursor.fetchone()['count']
print(f"\n   LLDP detail snapshots: {lldp_count}")

if lldp_count == 0:
    print("\n   ⚠️  NO LLDP-DETAIL SNAPSHOTS FOUND!")
    print("   The script is looking for capture_type = 'lldp-detail'")
    print("   Check if your database uses a different type name.")

    # Show what types exist
    cursor.execute("SELECT DISTINCT capture_type FROM capture_snapshots LIMIT 20")
    print("\n   Available capture types:")
    for row in cursor.fetchall():
        print(f"     - {row['capture_type']}")

    conn.close()
    sys.exit(0)

# Check sample LLDP content
print(f"\n2. Checking LLDP content quality...")
cursor.execute("""
    SELECT 
        d.name as device_name,
        cs.capture_type,
        LENGTH(cs.content) as content_length,
        SUBSTR(cs.content, 1, 300) as content_preview,
        cs.content as full_content
    FROM capture_snapshots cs
    JOIN devices d ON cs.device_id = d.id
    WHERE cs.capture_type = 'lldp-detail'
    ORDER BY d.name
    LIMIT 3
""")

for idx, row in enumerate(cursor.fetchall(), 1):
    print(f"\n   Sample {idx}: {row['device_name']}")
    print(f"   Content length: {row['content_length']} bytes")

    content_preview = row['content_preview']

    # Check for common error patterns
    has_error = False
    if 'error' in content_preview.lower():
        print(f"   ⚠️  Contains 'error'")
        has_error = True
    if 'invalid' in content_preview.lower():
        print(f"   ⚠️  Contains 'invalid'")
        has_error = True
    if len(content_preview.strip()) == 0:
        print(f"   ⚠️  Content is empty")
        has_error = True

    if has_error:
        print(f"   Preview (first 300 chars):")
        print(f"   ---")
        print(f"   {content_preview}")
        print(f"   ---")
    else:
        print(f"   ✓ Content looks valid")
        print(f"   Preview (first 300 chars):")
        print(f"   ---")
        print(f"   {content_preview}")
        print(f"   ---")

# Check devices table
print(f"\n3. Checking devices table...")
cursor.execute("""
    SELECT COUNT(*) as count
    FROM devices
""")
device_count = cursor.fetchone()['count']
print(f"   Total devices: {device_count}")

cursor.execute("""
    SELECT 
        d.name,
        d.management_ip,
        v.name as vendor
    FROM devices d
    LEFT JOIN vendors v ON d.vendor_id = v.id
    LIMIT 5
""")
print(f"\n   Sample devices:")
for row in cursor.fetchall():
    print(f"     {row['name']} - {row['vendor']} - {row['management_ip']}")

# Check if devices have LLDP snapshots
print(f"\n4. Checking device-snapshot relationship...")
cursor.execute("""
    SELECT 
        COUNT(DISTINCT d.id) as devices_with_lldp
    FROM devices d
    JOIN capture_snapshots cs ON d.id = cs.device_id
    WHERE cs.capture_type = 'lldp-detail'
""")
devices_with_lldp = cursor.fetchone()['devices_with_lldp']
print(f"   Devices with LLDP snapshots: {devices_with_lldp}")

if devices_with_lldp == 0:
    print(f"   ⚠️  NO DEVICES HAVE LLDP SNAPSHOTS!")
    print(f"   This means the JOIN is failing - check device_id foreign keys")

print("\n" + "=" * 70)
print("Diagnosis complete!")

if lldp_count > 0 and devices_with_lldp > 0:
    print("\n✓ Database looks good - the issue is likely in TextFSM parsing")
    print("  Run: python lldp_to_topology_debug.py assets.db --debug")
else:
    print("\n⚠️  Database has issues - see warnings above")

conn.close()