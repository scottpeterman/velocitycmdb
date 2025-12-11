#!/usr/bin/env python3
"""
Batch BGP Migration Analyzer

Processes all Juniper devices (agg*, peer*, qfx*) from assets.db
and generates migration plans for all BGP peers.
"""

import sys
import sqlite3
import re
import argparse
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime

# Import the migration analyzer
try:
    from juniper_peer_report import JuniperToAristaMigration
except ImportError:
    print("ERROR: juniper_peer_report.py not found")
    print("Ensure juniper_peer_report.py is in the same directory")
    sys.exit(1)


class BatchBGPMigrationAnalyzer:
    """Batch process BGP migrations from assets.db"""

    def __init__(self, assets_db_path: str, output_dir: str, vendor_filter: str = 'juniper'):
        self.assets_db_path = assets_db_path
        self.output_dir = Path(output_dir)
        self.vendor_filter = vendor_filter

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self.conn = sqlite3.connect(assets_db_path)
        self.conn.row_factory = sqlite3.Row

        # Statistics
        self.stats = {
            'devices_found': 0,
            'devices_with_config': 0,
            'total_peers': 0,
            'migrations_generated': 0,
            'errors': []
        }

    def get_juniper_devices(self, name_patterns: List[str]) -> List[sqlite3.Row]:
        """
        Get Juniper devices matching name patterns

        Args:
            name_patterns: List of SQL LIKE patterns (e.g., ['agg%', 'peer%', 'qfx%'])
        """
        query = """
            SELECT 
                d.id,
                d.name,
                d.normalized_name,
                d.management_ip,
                d.model,
                d.os_version,
                v.name as vendor_name
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            WHERE LOWER(v.name) LIKE ?
        """

        # Add name pattern filters
        if name_patterns:
            pattern_conditions = " OR ".join([f"LOWER(d.name) LIKE ?" for _ in name_patterns])
            query += f" AND ({pattern_conditions})"

        query += " ORDER BY d.name"

        # Build parameters
        params = [f'%{self.vendor_filter.lower()}%']
        if name_patterns:
            params.extend([f'{pattern.lower()}%' for pattern in name_patterns])

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def get_device_config(self, device_id: int) -> str:
        """Get device configuration from capture_snapshots"""
        query = """
            SELECT content
            FROM capture_snapshots
            WHERE device_id = ?
            AND capture_type = 'configs'
            ORDER BY captured_at DESC
            LIMIT 1
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (device_id,))
        row = cursor.fetchone()

        if row:
            return row['content']
        return None

    def extract_bgp_peers_from_config(self, config: str) -> List[str]:
        """Extract all BGP neighbor IPs from Juniper config"""
        peers = []

        # Pattern: protocols bgp group <group> neighbor <ip>
        pattern = r'protocols\s+bgp\s+group\s+\S+\s+neighbor\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'

        for match in re.finditer(pattern, config):
            peer_ip = match.group(1)
            if peer_ip not in peers:
                peers.append(peer_ip)

        return sorted(peers)

    def process_device(self, device: sqlite3.Row) -> Dict:
        """Process a single device and generate migration plans for all BGP peers"""
        device_name = device['name']
        device_id = device['id']

        print(f"\n{'=' * 80}")
        print(f"Processing: {device_name}")
        print(f"{'=' * 80}")

        result = {
            'device_name': device_name,
            'device_id': device_id,
            'management_ip': device['management_ip'],
            'model': device['model'],
            'peers': [],
            'peer_details': {},  # NEW: Store detailed peer information
            'config_found': False,
            'error': None
        }

        # Get device config
        config = self.get_device_config(device_id)

        if not config:
            error = f"No configuration found in capture_snapshots for {device_name}"
            print(f"  ⚠️  {error}")
            result['error'] = error
            self.stats['errors'].append(error)
            return result

        result['config_found'] = True
        self.stats['devices_with_config'] += 1

        # Extract BGP peers
        peers = self.extract_bgp_peers_from_config(config)

        if not peers:
            msg = f"No BGP peers found in configuration for {device_name}"
            print(f"  ℹ️  {msg}")
            result['error'] = msg
            return result

        print(f"  Found {len(peers)} BGP peers")
        result['peers'] = peers
        self.stats['total_peers'] += len(peers)

        # Create device output directory
        device_output_dir = self.output_dir / self._sanitize_filename(device_name)
        device_output_dir.mkdir(parents=True, exist_ok=True)

        # Save config to temp file for migration analyzer
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as temp_config:
            temp_config.write(config)
            temp_config_path = temp_config.name

        try:
            # Create migration analyzer
            migrator = JuniperToAristaMigration(temp_config_path)

            # Process each peer
            for peer_ip in peers:
                print(f"    → Analyzing peer: {peer_ip}")

                try:
                    # Get peer information for summary table
                    peer_info = migrator.find_bgp_peer(peer_ip)
                    interface, vlan_name, vlan_id, local_ip = migrator.find_interface_for_peer(peer_ip)

                    # Detect if this is iBGP
                    is_ibgp = False
                    local_address = None

                    # Check for iBGP indicators
                    if peer_info.get('group_type') == 'internal':
                        is_ibgp = True
                    elif peer_info.get('peer_as') == migrator.global_asn:
                        is_ibgp = True

                    # Get local-address if configured (common for iBGP)
                    if is_ibgp:
                        for line in peer_info.get('group_config', []):
                            if 'local-address' in line:
                                match = re.search(r'local-address (\d+\.\d+\.\d+\.\d+)', line)
                                if match:
                                    local_address = match.group(1)
                                    break

                    # Get peer information for summary table
                    peer_info = migrator.find_bgp_peer(peer_ip)
                    interface, vlan_name, vlan_id, local_ip = migrator.find_interface_for_peer(peer_ip)

                    # Detect if this is iBGP
                    is_ibgp = False
                    local_address = None

                    # ✅ ADD THIS SECTION - Get peer AS, handle missing peer-as for iBGP
                    peer_as = peer_info.get('peer_as')
                    if not peer_as and peer_info.get('group_type') == 'internal':
                        # Internal BGP without explicit peer-as uses global ASN
                        peer_as = migrator.global_asn

                    # Check for iBGP indicators
                    if peer_info.get('group_type') == 'internal':
                        is_ibgp = True
                    elif peer_as and peer_as == migrator.global_asn:  # ✅ Use peer_as variable here
                        is_ibgp = True

                    # Get local-address if configured (common for iBGP)
                    if is_ibgp:
                        for line in peer_info.get('group_config', []):
                            if 'local-address' in line:
                                match = re.search(r'local-address (\d+\.\d+\.\d+\.\d+)', line)
                                if match:
                                    local_address = match.group(1)
                                    break

                    # Store peer details for summary report
                    result['peer_details'][peer_ip] = {
                        'peer_as': peer_as or 'Unknown',  # ✅ Use the peer_as variable
                        'group_name': peer_info.get('group_name', 'Unknown'),
                        'is_ibgp': is_ibgp,
                        'local_address': local_address,
                        'interface': interface or 'Unknown',
                        'vlan_id': vlan_id or 'N/A',
                        'vlan_name': vlan_name or 'N/A',
                        'local_ip': local_ip or local_address or 'Unknown'
                    }
                    # Generate migration plan
                    output_file = device_output_dir / f"migration_{peer_ip.replace('.', '_')}.txt"

                    # Redirect stdout to file
                    original_stdout = sys.stdout
                    with open(output_file, 'w') as f:
                        sys.stdout = f
                        migrator.analyze_peer_migration(peer_ip)
                    sys.stdout = original_stdout

                    peer_type = "iBGP" if is_ibgp else "eBGP"
                    print(f"      ✓ Generated: {output_file.name} ({peer_type})")
                    self.stats['migrations_generated'] += 1

                    # Also generate Arista config separately
                    if peer_info['group_name']:
                        arista_config = migrator.generate_arista_config(
                            peer_ip, peer_info, interface, vlan_name, vlan_id, local_ip
                        )

                        arista_file = device_output_dir / f"arista_config_{peer_ip.replace('.', '_')}.txt"
                        with open(arista_file, 'w') as f:
                            f.write(arista_config)

                        print(f"      ✓ Generated: {arista_file.name}")

                except Exception as e:
                    error = f"Error processing peer {peer_ip} on {device_name}: {e}"
                    print(f"      ✗ {error}")
                    self.stats['errors'].append(error)

                    # Store error in peer details
                    result['peer_details'][peer_ip] = {
                        'peer_as': 'Error',
                        'group_name': 'Error',
                        'interface': 'Error',
                        'vlan_id': 'Error',
                        'vlan_name': 'Error',
                        'local_ip': 'Error'
                    }

        finally:
            # Clean up temp config file
            Path(temp_config_path).unlink(missing_ok=True)

        return result

    def generate_summary_report(self, devices_processed: List[Dict]):
        """Generate a summary report of all migrations"""
        summary_file = self.output_dir / "MIGRATION_SUMMARY.md"

        # Calculate statistics for iBGP vs eBGP
        total_ibgp = 0
        total_ebgp = 0
        for device in devices_processed:
            for peer_details in device.get('peer_details', {}).values():
                if peer_details.get('is_ibgp'):
                    total_ibgp += 1
                else:
                    total_ebgp += 1

        with open(summary_file, 'w') as f:
            f.write("# BGP Migration Summary Report\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Assets Database:** {self.assets_db_path}\n\n")

            f.write("## Statistics\n\n")
            f.write(f"- **Devices Found:** {self.stats['devices_found']}\n")
            f.write(f"- **Devices with Config:** {self.stats['devices_with_config']}\n")
            f.write(f"- **Total BGP Peers:** {self.stats['total_peers']}\n")
            f.write(f"  - **eBGP Peers (External):** {total_ebgp} - *Migrate to Arista*\n")
            f.write(f"  - **iBGP Peers (Internal):** {total_ibgp} - *Handle during decommission*\n")
            f.write(f"- **Migration Plans Generated:** {self.stats['migrations_generated']}\n")
            if self.stats['errors']:
                f.write(f"- **Errors:** {len(self.stats['errors'])}\n")
            f.write("\n")

            # Device summary table with iBGP/eBGP breakdown
            f.write("## Devices Processed\n\n")
            f.write("| Device | Management IP | Model | eBGP | iBGP | Total | Status |\n")
            f.write("|--------|---------------|-------|------|------|-------|--------|\n")

            for device in devices_processed:
                status = "✓" if device['config_found'] and device['peers'] else "⚠️"
                peer_count = len(device['peers']) if device['peers'] else 0
                mgmt_ip = device['management_ip'] or 'N/A'
                model = device['model'] or 'N/A'

                # Count iBGP vs eBGP
                ibgp_count = sum(1 for p in device.get('peer_details', {}).values() if p.get('is_ibgp'))
                ebgp_count = peer_count - ibgp_count

                f.write(
                    f"| {device['device_name']} | {mgmt_ip} | {model} | {ebgp_count} | {ibgp_count} | {peer_count} | {status} |\n")

            f.write("\n")

            # Detailed peer information with AS and interface details
            f.write("## BGP Peer Details\n\n")
            f.write(
                "⚠️ **Note:** iBGP peers are internal sessions that will be handled during final device decommission, not during external peer migration.\n\n")

            for device in devices_processed:
                if device['peers']:
                    f.write(f"### {device['device_name']}\n\n")
                    f.write(f"**Management IP:** {device['management_ip'] or 'N/A'}  \n")
                    f.write(f"**Model:** {device['model'] or 'N/A'}  \n")

                    # Count iBGP vs eBGP
                    ibgp_count = sum(1 for p in device.get('peer_details', {}).values() if p.get('is_ibgp'))
                    ebgp_count = len(device['peers']) - ibgp_count

                    f.write(f"**Total Peers:** {len(device['peers'])} ({ebgp_count} eBGP, {ibgp_count} iBGP)\n\n")

                    device_dir = self._sanitize_filename(device['device_name'])

                    # Enhanced table with peer AS and interface information
                    f.write(
                        "| Peer IP | Type | Remote AS | Interface | VLAN | Local IP | Group | Migration Plan | Arista Config |\n")
                    f.write(
                        "|---------|------|-----------|-----------|------|----------|-------|----------------|---------------|\n")

                    # Get detailed peer information
                    for peer_ip in device['peers']:
                        peer_safe = peer_ip.replace('.', '_')
                        migration_file = f"{device_dir}/migration_{peer_safe}.txt"
                        arista_file = f"{device_dir}/arista_config_{peer_safe}.txt"

                        # Get peer details from the stored config
                        peer_details = device.get('peer_details', {}).get(peer_ip, {})

                        is_ibgp = peer_details.get('is_ibgp', False)
                        peer_type = "**iBGP**" if is_ibgp else "eBGP"
                        remote_as = peer_details.get('peer_as', 'N/A')
                        interface = peer_details.get('interface', 'N/A')
                        vlan_id = peer_details.get('vlan_id', 'N/A')
                        local_ip = peer_details.get('local_ip', 'N/A')
                        group_name = peer_details.get('group_name', 'N/A')

                        # Format interface display (shorten if needed)
                        if interface and interface != 'N/A':
                            if interface.startswith('irb.'):
                                interface_display = interface
                            else:
                                # Truncate long interface names for table readability
                                interface_display = interface if len(interface) <= 12 else f"{interface[:10]}..."
                        else:
                            interface_display = interface if not is_ibgp else "Routed*"

                        # Format local IP (show just IP without mask for brevity)
                        if local_ip and local_ip != 'N/A' and '/' in local_ip:
                            local_ip_display = local_ip.split('/')[0]
                        else:
                            local_ip_display = local_ip

                        # For iBGP, note that migration plan is for reference only
                        plan_link = f"[Ref](./{migration_file})" if is_ibgp else f"[View](./{migration_file})"
                        config_link = f"[Ref](./{arista_file})" if is_ibgp else f"[View](./{arista_file})"

                        f.write(
                            f"| {peer_ip} | {peer_type} | AS{remote_as} | {interface_display} | "
                            f"{vlan_id} | {local_ip_display} | {group_name} | "
                            f"{plan_link} | {config_link} |\n"
                        )

                    f.write("\n")

                    # Add footnote if there are iBGP peers
                    if ibgp_count > 0:
                        f.write(
                            f"*\\* iBGP peers ({ibgp_count}) use internal routing and will be decommissioned with the device, not migrated to Arista.*\n\n")

            # Errors
            if self.stats['errors']:
                f.write("## Errors\n\n")
                for error in self.stats['errors']:
                    f.write(f"- {error}\n")
                f.write("\n")

            # Migration guidance
            f.write("## Migration Process\n\n")

            f.write("### ⚠️ Important: iBGP vs eBGP\n\n")
            f.write("**eBGP Peers (External BGP):**\n")
            f.write("- These connect to external networks/customers\n")
            f.write("- **ACTION REQUIRED:** Migrate these peers to Arista\n")
            f.write("- Use the generated migration plans and Arista configs\n")
            f.write("- Follow the detailed steps in each migration document\n\n")

            f.write("**iBGP Peers (Internal BGP):**\n")
            f.write("- These are internal sessions between your own routers\n")
            f.write("- **NO ACTION NEEDED:** These will be handled during final device decommission\n")
            f.write("- Migration plans are provided for reference only\n")
            f.write("- These sessions will be removed when the Juniper device is retired\n\n")

            f.write("### Recommended Order\n\n")
            f.write("1. **Review All eBGP Migration Plans**\n")
            f.write("   - Focus ONLY on eBGP peers (marked as 'eBGP' in the table)\n")
            f.write("   - Check each device's migration files in the subdirectories\n")
            f.write("   - Verify route-map translations\n")
            f.write("   - Confirm VLAN/interface mappings\n\n")

            f.write("2. **Coordinate with Teams**\n")
            f.write("   - Schedule maintenance windows\n")
            f.write("   - Notify BGP peer operators\n")
            f.write("   - Plan for VRRP coordination if applicable\n\n")

            f.write("3. **Execute Migrations**\n")
            f.write("   - Start with lowest-risk peers (test/dev environments)\n")
            f.write("   - Use generated Arista configs as templates\n")
            f.write("   - Follow detailed steps in each migration plan\n\n")

            f.write("4. **Validation**\n")
            f.write("   - Monitor BGP session establishment\n")
            f.write("   - Verify route exchange\n")
            f.write("   - Check remaining Juniper peers are unaffected\n\n")

            f.write("### File Organization\n\n")
            f.write("```\n")
            f.write(f"{self.output_dir.name}/\n")
            f.write("├── MIGRATION_SUMMARY.md          (this file)\n")
            f.write("└── <device_name>/\n")
            f.write("    ├── migration_<peer_ip>.txt   (full migration plan)\n")
            f.write("    └── arista_config_<peer_ip>.txt (Arista config only)\n")
            f.write("```\n\n")

        print(f"\n{'=' * 80}")
        print(f"Summary report saved: {summary_file}")
        print(f"{'=' * 80}\n")

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize device name for use as directory name"""
        return re.sub(r'[^\w\-.]', '_', name)

    def run(self, name_patterns: List[str] = None):
        """Run batch migration analysis"""
        print(f"\n{'=' * 80}")
        print("BGP MIGRATION BATCH PROCESSOR")
        print(f"{'=' * 80}")
        print(f"Assets Database: {self.assets_db_path}")
        print(f"Output Directory: {self.output_dir}")
        print(f"Vendor Filter: {self.vendor_filter}")
        if name_patterns:
            print(f"Name Patterns: {', '.join(name_patterns)}")
        print(f"{'=' * 80}\n")

        # Get devices
        print("Querying database for Juniper devices...")
        devices = self.get_juniper_devices(name_patterns or [])
        self.stats['devices_found'] = len(devices)

        if not devices:
            print("❌ No devices found matching criteria")
            return

        print(f"✓ Found {len(devices)} devices\n")

        # Process each device
        devices_processed = []

        for idx, device in enumerate(devices, 1):
            print(f"\n[{idx}/{len(devices)}]", end=' ')
            result = self.process_device(device)
            devices_processed.append(result)

        # Generate summary report
        print(f"\n\n{'=' * 80}")
        print("Generating summary report...")
        self.generate_summary_report(devices_processed)

        # Print final statistics
        print(f"\n{'=' * 80}")
        print("FINAL STATISTICS")
        print(f"{'=' * 80}")
        print(f"Devices Found:          {self.stats['devices_found']}")
        print(f"Devices with Config:    {self.stats['devices_with_config']}")
        print(f"Total BGP Peers:        {self.stats['total_peers']}")
        print(f"Migration Plans:        {self.stats['migrations_generated']}")
        if self.stats['errors']:
            print(f"Errors:                 {len(self.stats['errors'])}")
        print(f"{'=' * 80}\n")

        print(f"✓ All migration plans saved to: {self.output_dir}")
        print(f"✓ Review MIGRATION_SUMMARY.md for details\n")

    def close(self):
        """Clean up database connection"""
        if self.conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Batch process BGP migrations from assets.db',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all agg*, peer*, qfx* Juniper devices
  python batch_bgp_migration.py assets.db -o migrations

  # Process only aggregation routers
  python batch_bgp_migration.py assets.db -o migrations -n agg

  # Process specific patterns
  python batch_bgp_migration.py assets.db -o migrations -n agg peer qfx

  # Specify different vendor
  python batch_bgp_migration.py assets.db -o migrations --vendor juniper

Output Structure:
  migrations/
  ├── MIGRATION_SUMMARY.md              (Master summary report)
  ├── agg203.iad2/
  │   ├── migration_10_252_4_1.txt      (Full migration plan)
  │   └── arista_config_10_252_4_1.txt  (Arista config only)
  ├── agg469.iad2/
  │   ├── migration_10_252_4_22.txt
  │   └── arista_config_10_252_4_22.txt
  └── ...
        """
    )

    parser.add_argument('assets_db',
                        help='Path to assets.db')

    parser.add_argument('-o', '--output',
                        default='bgp_migrations',
                        help='Output directory for migration plans (default: bgp_migrations)')

    parser.add_argument('-n', '--names',
                        nargs='+',
                        help='Device name patterns to match (e.g., agg peer qfx)')

    parser.add_argument('--vendor',
                        default='juniper',
                        help='Vendor filter (default: juniper)')

    args = parser.parse_args()

    # Validate assets database
    if not Path(args.assets_db).exists():
        print(f"❌ ERROR: Assets database not found: {args.assets_db}")
        sys.exit(1)

    # Set default name patterns if none provided
    name_patterns = args.names or ['agg', 'peer', 'qfx', 'edge']

    # Create batch analyzer
    analyzer = BatchBGPMigrationAnalyzer(
        assets_db_path=args.assets_db,
        output_dir=args.output,
        vendor_filter=args.vendor
    )

    try:
        analyzer.run(name_patterns=name_patterns)
    finally:
        analyzer.close()


if __name__ == "__main__":
    main()