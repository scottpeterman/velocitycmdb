# VelocityCMDB Import Script

Import VelocityMaps network discovery results into VelocityCMDB's asset database.

## Quick Start

```bash
# Dry run (preview only)
python velocitycmdb_import.py \
  --results-dir ~/PycharmProjects/velocitymaps/tests/ \
  --db-path ~/.velocitycmdb/data/assets.db \
  --dry-run

# Live import
python velocitycmdb_import.py \
  --results-dir ~/PycharmProjects/velocitymaps/tests/ \
  --db-path ~/.velocitycmdb/data/assets.db

# Import with domain stripping
python velocitycmdb_import.py \
  --results-dir ~/PycharmProjects/velocitymaps/tests/ \
  --db-path ~/.velocitycmdb/data/assets.db \
  --remove-domains "kentik.com,kentik.eu,lab.local"
```

## What It Does

Reads VelocityMaps discovery output (JSON files) and populates VelocityCMDB database with:
- Device name (with optional domain stripping)
- Management IP address
- Vendor, model, OS version (parsed from SNMP sysDescr)
- Site assignment (defaults to "IMPORTED")
- Source system tracking ("VelocityMaps")

## Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--results-dir PATH` | VelocityMaps output directory (required) | `~/velocitymaps/tests` |
| `--db-path PATH` | VelocityCMDB assets.db path | `~/.velocitycmdb/data/assets.db` |
| `--dry-run` | Preview changes without modifying database | (flag) |
| `--remove-domains LIST` | Strip domain suffixes from hostnames | `"kentik.com,kentik.eu"` |

## Requirements

- **Python**: 3.6+
- **Dependencies**: None (uses standard library only)
- **VelocityMaps Output**: Directory with device folders containing `device.json` files
- **VelocityCMDB Database**: SQLite database with proper schema

## Expected Directory Structure

```
velocitymaps/tests/
├── device-1/
│   ├── device.json      ← Required
│   ├── lldp.json        (ignored)
│   └── cdp.json         (ignored)
├── device-2/
│   └── device.json
└── ...
```

## Features

### Idempotent Updates
Run multiple times safely. Devices are matched by normalized hostname or management IP:
- **First run**: Creates all devices
- **Second run**: Updates existing devices (no duplicates)

### Smart Vendor Parsing
Extracts model and OS version from SNMP sysDescr:

**Cisco:**
```
Input:  "Cisco IOS Software, IOSv Software (VIOS-ADVENTERPRISEK9-M), Version 15.6(2)T"
Output: model="VIOS-ADVENTERPRISEK9-M", os_version="15.6(2)T"
```

**Arista:**
```
Input:  "Arista Networks EOS version 4.33.1F running on an Arista vEOS-lab"
Output: model="vEOS-lab", os_version="4.33.1F"
```

**Juniper:**
```
Input:  "Juniper Networks, Inc. srx300 internet router, kernel JUNOS 15.1X49-D170.4"
Output: model="SRX300", os_version="15.1X49-D170.4"
```

### Domain Stripping
Remove domain suffixes to keep device names clean:

```bash
--remove-domains "kentik.com,kentik.eu,lab.local"

# Results:
router1.kentik.com    → router1
switch2.kentik.eu     → switch2
firewall.lab.local    → firewall
ROUTER1.KENTIK.COM    → ROUTER1  (case-insensitive)
core-switch           → core-switch  (unchanged - no domain)
```

### Pre-Flight Checks
Automatically creates missing vendors and sites:
- Arista Networks (ARISTA)
- Juniper Networks (JUNIPER)
- Cisco Systems (Cisco)
- Unknown (UNKNOWN)
- IMPORTED site (for new devices)

## Output Example

```
================================================================================
VelocityCMDB Importer
================================================================================
Results Directory: /home/speterman/PycharmProjects/velocitymaps/tests/
Database: /home/speterman/.velocitycmdb/data/assets.db
Mode: LIVE
Remove Domains: home.com, lab.local
================================================================================

✓ Created vendor: Arista Networks
✓ Created vendor: Juniper Networks
✓ Created vendor: Cisco Systems
✓ Created vendor: Unknown
✓ Created site: IMPORTED

Found 12 devices to import

✓ Created device: eng-leaf-1
✓ Created device: eng-spine-1
  Cleaned hostname: wan-core-1.home.com → wan-core-1
✓ Created device: wan-core-1
...

================================================================================
Import Summary
================================================================================
Created:  12
Updated:  0
Skipped:  0
Errors:   0
================================================================================
```

## Integration with VelocityCMDB

### Workflow

1. **Run VelocityMaps discovery** (SNMP-based, fast)
2. **Import results** with this script
3. **Organize devices** using VelocityCMDB's Bulk Operations
   - Filter by pattern (e.g., `eng-*`)
   - Set site code (e.g., `ENG`)
4. **Let collectors take over** (components, configs, etc.)

### Post-Import Organization

All imported devices start in the "IMPORTED" site. Use VelocityCMDB's built-in Bulk Operations:

```
Bulk Operations → Set Site Code
- Filter: Name pattern = "eng-*"
- New site: ENG
- Preview → Execute

Bulk Operations → Set Site Code  
- Filter: Name pattern = "usa-*"
- New site: USA
- Preview → Execute
```

## Database Schema Mapping

| VelocityMaps Field | VelocityCMDB Column | Notes |
|-------------------|---------------------|-------|
| `hostname` | `name` | Display name |
| `hostname` (lowercased) | `normalized_name` | Unique key for matching |
| `ip` | `management_ip` | Management IP |
| `ip` | `ipv4_address` | Also set to management IP |
| `vendor` | `vendor_id` | FK to vendors table |
| `sysDescr` (parsed) | `model` | Vendor-specific parsing |
| `sysDescr` (parsed) | `os_version` | Vendor-specific parsing |
| `timestamp` | `timestamp` | Last discovery time |
| (default) | `site_code` | Set to "IMPORTED" |
| (default) | `source_system` | Set to "VelocityMaps" |

## Device Matching Logic

The script finds existing devices in this order:

1. **normalized_name** (primary key) - exact match on lowercase hostname
2. **management_ip** - fallback if hostname changed
3. **ipv4_address** - additional fallback

If found → UPDATE  
If not found → INSERT

## Error Handling

```bash
# Missing hostname
✗ Skipping device: no hostname

# Vendor resolution failure (shouldn't happen after pre-flight)
⚠️  Warning: Vendor 'XYZ' not found in database
✗ Skipping device-xyz: couldn't resolve vendor

# Database error
✗ Failed to create device-123: UNIQUE constraint failed

# Invalid JSON
✗ Invalid JSON in /path/to/device.json: Expecting property name
```

## Performance

- **Import Speed**: ~100 devices/second
- **Database Impact**: ~2KB per device
- **106 Kentik devices**: ~2-3 seconds total
- **Memory Usage**: Minimal (streaming JSON parser)

## Production Usage

### Recommended Workflow

```bash
# 1. Run VelocityMaps discovery
# (VelocityMaps GUI or CLI generates results directory)

# 2. Preview import
python velocitycmdb_import.py \
  --results-dir /path/to/results \
  --db-path ~/.velocitycmdb/data/assets.db \
  --remove-domains "kentik.com,kentik.eu" \
  --dry-run

# 3. Review dry-run output
# - Check device count
# - Verify vendor distribution
# - Confirm domain cleaning

# 4. Execute import
python velocitycmdb_import.py \
  --results-dir /path/to/results \
  --db-path ~/.velocitycmdb/data/assets.db \
  --remove-domains "kentik.com,kentik.eu"

# 5. Organize in VelocityCMDB web UI
# - Navigate to Bulk Operations
# - Move devices from IMPORTED to proper sites
# - Set device roles if needed

# 6. Verify collectors are running
# - Check component inventory
# - Verify captures are running
```

### Re-Discovery Workflow

```bash
# Quarterly or when adding new devices:
# 1. Run VelocityMaps discovery again
# 2. Re-import (updates existing, creates new)
python velocitycmdb_import.py \
  --results-dir /path/to/new-results \
  --db-path ~/.velocitycmdb/data/assets.db \
  --remove-domains "kentik.com,kentik.eu"

# Results:
# - Existing devices: Updated
# - New devices: Created in IMPORTED site
# - Removed devices: Remain in database (manual cleanup)
```

## Troubleshooting

### Database not found
```bash
# Check database path
ls -la ~/.velocitycmdb/data/assets.db

# Or specify custom path
--db-path /custom/path/assets.db
```

### No devices found
```bash
# Verify directory structure
ls -la /path/to/results/*/device.json

# Each device folder must contain device.json
```

### Vendor not found (after pre-flight)
This shouldn't happen. If it does, the vendor name in VelocityMaps output doesn't match the expected values (`cisco`, `arista`, `juniper`).

### Permission denied
```bash
# Fix database permissions
chmod 644 ~/.velocitycmdb/data/assets.db
```

## Limitations

- **No interface import**: VelocityCMDB collectors handle this
- **No component import**: VelocityCMDB collectors handle this  
- **No topology persistence**: LLDP/CDP data used for discovery only
- **No credential import**: Credentials remain separate
- **Serial numbers**: Not in VelocityMaps output (collectors will gather)

## Version History

**v1.0.0** - December 12, 2025
- Initial release
- Idempotent device imports
- Vendor-specific sysDescr parsing (Cisco, Arista, Juniper)
- Pre-flight vendor/site creation
- Domain stripping support
- Dry-run preview mode
- Tested at Kentik (106 devices)

## Author

Scott Peterman  
Principal Infrastructure Engineer @ Kentik  
Part of the Velocity Ecosystem (Anguis NMS, VelocityCMDB, VelocityMaps)

## License

GPLv3