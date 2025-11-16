# ARP Cat - Network ARP Table Tracking System

## Overview

ARP Cat is a comprehensive system for tracking ARP table information across network infrastructure over time. It processes ARP output from multiple vendors, normalizes the data, and provides powerful search and analysis capabilities for network troubleshooting and forensics.

## Key Features

- **Multi-vendor support**: Cisco, Arista, Juniper, HP, and others
- **Historical tracking**: Complete audit trail of ARP table changes
- **Context awareness**: Supports VRF, VDOM, logical-system, and other contexts
- **MAC normalization**: Consistent format regardless of vendor syntax
- **Powerful search**: Find MAC/IP associations across time and devices
- **Integration ready**: Works with existing capture systems

## System Components

### Core Components

1. **arp_cat.db** - SQLite database with normalized ARP data
2. **arp_cat_util.py** - Core library for ARP data management
3. **arp_cat_loader.py** - Processes ARP captures into the database
4. **arp_cat_cli.py** - Command-line interface for search and reporting

### Database Schema

The system uses a normalized SQLite schema with:
- **devices** - Network device inventory
- **contexts** - VRF/VDOM/logical-system tracking
- **arp_entries** - Individual ARP records with full history
- **arp_snapshots** - Capture session metadata
- **Views** - Pre-built queries for common operations

## Installation

### Prerequisites
```bash
pip install sqlite3 ipaddress re pathlib typing
```

### Optional TextFSM Support
```bash
# For advanced parsing capabilities
pip install textfsm
# Include tfsm_fire library (custom TextFSM wrapper)
```

### Database Setup
```bash
# Create the database schema
sqlite3 arp_cat.db < arp_cat_schema.sql
```

## Usage

### Loading ARP Data

#### From Assets Database Integration
```bash
# Process all ARP captures from assets.db
python arp_cat_loader.py

# Process with debugging for specific device
python arp_cat_loader.py --device-filter "switch01" --debug

# Limit processing for testing
python arp_cat_loader.py --max-files 10 --verbose
```

#### Direct File Processing
```python
from arp_cat_util import ArpCatUtil

with ArpCatUtil() as arp_util:
    device_id = arp_util.get_or_create_device(
        hostname='switch01.example.com',
        vendor='Cisco',
        device_type='cisco_ios_ssh'
    )
    
    context_id = arp_util.get_or_create_context(
        device_id, 'default', 'vrf'
    )
    
    arp_util.add_arp_entry(
        device_id, context_id,
        '192.168.1.100', 'aa:bb:cc:dd:ee:ff',
        interface_name='GigabitEthernet0/1',
        entry_type='dynamic'
    )
```

### Searching ARP Data

#### Command Line Interface

```bash
# Search by MAC address
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff

# Search with full history
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff --history

# Search by IP address
python arp_cat_cli.py search-ip 192.168.1.100

# Device ARP table
python arp_cat_cli.py search-device switch01

# Site overview
python arp_cat_cli.py search-site NYC01 --summary

# List all devices
python arp_cat_cli.py list-devices

# Database statistics
python arp_cat_cli.py stats
```

#### Output Formats
```bash
# Table format (default)
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff --format table

# CSV for spreadsheets
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff --format csv

# JSON for automation
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff --format json
```

#### Python API

```python
from arp_cat_util import ArpCatUtil

with ArpCatUtil() as arp_util:
    # Search by MAC
    results = arp_util.search_mac('aa:bb:cc:dd:ee:ff')
    
    # Search by IP
    results = arp_util.search_ip('192.168.1.100')
    
    # Device summary
    summary = arp_util.get_device_summary('switch01')
```

### Data Management

#### Export Data
```bash
# Export to CSV
python arp_cat_cli.py export arp_data.csv --format csv

# Export with filters
python arp_cat_cli.py export filtered_data.json --format json --device-filter "switch"

# Export specific MAC patterns
python arp_cat_cli.py export vendor_macs.csv --mac-filter "aa:bb:cc"
```

#### Cleanup Old Data
```bash
# Dry run - see what would be deleted
python arp_cat_cli.py cleanup --days 30

# Actually delete old entries
python arp_cat_cli.py cleanup --days 30 --execute
```

## Integration with Network Monitoring

### Automated Collection

ARP Cat integrates with existing network capture systems through the assets database:

```bash
# Process new captures every 4 hours
*/240 * * * * /usr/bin/python3 /opt/arp_cat/arp_cat_loader.py
```

### Real-time Analysis

```python
# Monitor for new MAC addresses
def check_new_macs():
    with ArpCatUtil() as arp_util:
        # Get recent entries (last hour)
        recent = get_recent_entries(hours=1)
        for entry in recent:
            if is_new_mac(entry['mac_address']):
                alert_new_device(entry)
```

## Vendor Support

### Supported Vendors

| Vendor | Formats | Context Support | Notes |
|--------|---------|----------------|-------|
| Cisco IOS | show ip arp | VRF | Standard dot notation |
| Cisco NXOS | show ip arp | VRF | Similar to IOS |
| Arista EOS | show arp | VRF | Full VRF extraction |
| Juniper | show arp | routing-instance | Colon notation |
| HP/Aruba | show arp | - | Dash notation |

### MAC Address Normalization

All MAC addresses are normalized to lowercase colon-separated format:

```python
# Input formats:
'aabb.ccdd.eeff'     # Cisco
'aa:bb:cc:dd:ee:ff'  # Standard
'aabbcc-ddeeff'      # HP

# Output format:
'aa:bb:cc:dd:ee:ff'  # Normalized
```

### Context Support

Different vendors use different terminology for network contexts:

- **VRF** (Virtual Routing and Forwarding) - Cisco, Arista
- **VDOM** (Virtual Domain) - Fortinet
- **routing-instance** - Juniper
- **vsys** (Virtual System) - Palo Alto

## Use Cases

### Network Troubleshooting

```bash
# Find where a MAC has been seen
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff --history

# Track IP movement
python arp_cat_cli.py search-ip 192.168.1.100

# Audit device connectivity
python arp_cat_cli.py search-device core-switch --context production
```

### Security Analysis

```bash
# Find devices in multiple VLANs
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff --history

# Export for SIEM integration
python arp_cat_cli.py export security_data.json --format json

# Check for MAC spoofing
python arp_cat_cli.py search-mac aa:bb:cc:dd:ee:ff | grep -v "expected_device"
```

### Network Planning

```bash
# Site inventory
python arp_cat_cli.py search-site NYC01 --summary

# Growth analysis
python arp_cat_cli.py stats

# Capacity planning
python arp_cat_cli.py list-devices --format csv | analyze_growth.py
```

## Advanced Features

### Custom Queries

Direct database access for complex analysis:

```sql
-- Find MAC addresses seen on multiple devices
SELECT mac_address, COUNT(DISTINCT device_id) as device_count
FROM v_current_arp 
GROUP BY mac_address 
HAVING device_count > 1;

-- Track MAC movement over time
SELECT hostname, mac_address, capture_timestamp
FROM v_mac_history 
WHERE mac_address = 'aa:bb:cc:dd:ee:ff'
ORDER BY capture_timestamp DESC;
```

### API Integration

```python
# Custom analysis scripts
import sqlite3
from arp_cat_util import ArpCatUtil

def analyze_mac_mobility():
    conn = sqlite3.connect('arp_cat.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT mac_address, COUNT(DISTINCT hostname) as moves
        FROM v_mac_history 
        WHERE capture_timestamp > datetime('now', '-24 hours')
        GROUP BY mac_address
        HAVING moves > 1
    """)
    
    mobile_macs = cursor.fetchall()
    return mobile_macs
```

## Performance Considerations

### Database Optimization

- Indexes on commonly searched fields (MAC, IP, timestamp)
- Automatic cleanup of old historical data
- WAL mode for concurrent access
- Optimized views for common queries

### Processing Scale

- Handles hundreds of devices
- Processes thousands of ARP entries per batch
- ~4 hour collection intervals recommended
- Automatic deduplication and normalization

## Troubleshooting

### Common Issues

1. **No data loaded**: Check TextFSM templates and vendor detection
2. **Field mapping errors**: Use debug mode to inspect parsed fields
3. **Score thresholds**: Lower minimum scores for valid but low-confidence templates
4. **Vendor detection**: Verify vendor strings in source data

### Debug Tools

```bash
# Debug specific device
python arp_cat_loader.py --device-filter "device01" --debug

# Check database content
python arp_cat_cli.py stats

# Verify field mappings
python arp_cat_cli.py search-device device01 --format json
```

## Future Enhancements

- Web interface for interactive searching
- Real-time streaming data processing
- Integration with network monitoring systems
- Advanced analytics and machine learning
- API server for external integrations

## Contributing

The system is designed to be extensible:

1. Add new vendor parsers in `arp_cat_loader.py`
2. Extend context types in vendor mapping
3. Add new search capabilities in `arp_cat_cli.py`
4. Enhance database schema as needed

## License

[Specify your chosen license]

## Support

For issues and questions:
- Check the troubleshooting section
- Review debug output with `--debug` flag
- Examine database content with CLI tools