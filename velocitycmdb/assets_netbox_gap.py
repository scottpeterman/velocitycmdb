"""
netbox_gap_report.py - Compare Anguis discoveries against Netbox inventory
Identifies devices in Anguis but missing/mismatched in Netbox
"""

import sqlite3
import pynetbox
from typing import Dict, List, Set, Tuple
from datetime import datetime
import logging
from dataclasses import dataclass, field
import csv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class GapAnalysis:
    """Track gaps between Anguis and Netbox"""
    devices_only_in_anguis: List[Dict] = field(default_factory=list)
    devices_only_in_netbox: List[Dict] = field(default_factory=list)
    model_mismatches: List[Dict] = field(default_factory=list)
    site_mismatches: List[Dict] = field(default_factory=list)
    role_mismatches: List[Dict] = field(default_factory=list)
    serial_mismatches: List[Dict] = field(default_factory=list)
    ip_mismatches: List[Dict] = field(default_factory=list)

    def total_gaps(self) -> int:
        return (len(self.devices_only_in_anguis) +
                len(self.devices_only_in_netbox) +
                len(self.model_mismatches) +
                len(self.site_mismatches) +
                len(self.role_mismatches) +
                len(self.serial_mismatches) +
                len(self.ip_mismatches))


class NetboxGapAnalyzer:
    """Analyze gaps between Anguis discoveries and Netbox inventory"""

    def __init__(self, db_path: str, netbox_url: str, netbox_token: str):
        self.db_path = db_path
        self.nb = pynetbox.api(netbox_url, token=netbox_token)
        self.conn = None
        self.gaps = GapAnalysis()

    def connect_db(self):
        """Connect to AngularNMS SQLite database"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        logger.info(f"Connected to database: {self.db_path}")

    def disconnect_db(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Disconnected from database")

    def load_anguis_devices(self) -> Dict[str, Dict]:
        """Load all devices from Anguis database"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                d.id,
                d.name,
                d.normalized_name,
                d.site_code,
                d.model,
                d.management_ip,
                v.name as vendor_name,
                dr.name as role_name,
                ds.serial as primary_serial,
                s.name as site_name
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN device_roles dr ON d.role_id = dr.id
            LEFT JOIN device_serials ds ON d.id = ds.device_id AND ds.is_primary = 1
            LEFT JOIN sites s ON d.site_code = s.code
            WHERE d.name IS NOT NULL
        """)

        devices = {}
        for row in cursor.fetchall():
            devices[row['name'].lower()] = dict(row)

        logger.info(f"Loaded {len(devices)} devices from Anguis")
        return devices

    def load_netbox_devices(self) -> Dict[str, object]:
        """Load all devices from Netbox"""
        logger.info("Loading devices from Netbox...")
        devices = {}

        for device in self.nb.dcim.devices.all():
            devices[device.name.lower()] = device

        logger.info(f"Loaded {len(devices)} devices from Netbox")
        return devices

    def analyze_gaps(self) -> GapAnalysis:
        """Perform comprehensive gap analysis"""
        logger.info("=" * 80)
        logger.info("Starting Gap Analysis: Anguis vs Netbox")
        logger.info("=" * 80)

        anguis_devices = self.load_anguis_devices()
        netbox_devices = self.load_netbox_devices()

        anguis_names = set(anguis_devices.keys())
        netbox_names = set(netbox_devices.keys())

        # 1. Devices only in Anguis (discovered but not in Netbox)
        only_anguis = anguis_names - netbox_names
        logger.info(f"\n1. Devices discovered by Anguis but MISSING from Netbox: {len(only_anguis)}")

        for name in only_anguis:
            device = anguis_devices[name]
            self.gaps.devices_only_in_anguis.append({
                'name': device['name'],
                'site': device['site_name'] or device['site_code'],
                'vendor': device['vendor_name'],
                'model': device['model'],
                'role': device['role_name'],
                'management_ip': device['management_ip'],
                'serial': device['primary_serial']
            })
            if len(self.gaps.devices_only_in_anguis) <= 10:
                logger.info(f"  - {device['name']}: {device['vendor_name']} {device['model']} at {device['site_name']}")

        if len(only_anguis) > 10:
            logger.info(f"  ... and {len(only_anguis) - 10} more")

        # 2. Devices only in Netbox (manually added but not discovered)
        only_netbox = netbox_names - anguis_names
        logger.info(f"\n2. Devices in Netbox but NOT discovered by Anguis: {len(only_netbox)}")

        for name in only_netbox:
            nb_device = netbox_devices[name]
            self.gaps.devices_only_in_netbox.append({
                'name': nb_device.name,
                'site': nb_device.site.name if nb_device.site else None,
                'manufacturer': nb_device.device_type.manufacturer.name if nb_device.device_type.manufacturer else None,
                'model': nb_device.device_type.model,
                'role': nb_device.role.name if nb_device.role else None,
                'status': nb_device.status.value if nb_device.status else None
            })
            if len(self.gaps.devices_only_in_netbox) <= 10:
                logger.info(f"  - {nb_device.name}: {nb_device.device_type.model}")

        if len(only_netbox) > 10:
            logger.info(f"  ... and {len(only_netbox) - 10} more")

        # 3. Compare matching devices for discrepancies
        common_devices = anguis_names & netbox_names
        logger.info(f"\n3. Devices in BOTH systems: {len(common_devices)}")
        logger.info("   Checking for data mismatches...\n")

        for name in common_devices:
            anguis_dev = anguis_devices[name]
            netbox_dev = netbox_devices[name]

            # Check model mismatch
            nb_model = netbox_dev.device_type.model if netbox_dev.device_type else None
            if anguis_dev['model'] and nb_model and anguis_dev['model'] != nb_model:
                self.gaps.model_mismatches.append({
                    'name': anguis_dev['name'],
                    'anguis_model': anguis_dev['model'],
                    'netbox_model': nb_model
                })

            # Check site mismatch
            nb_site = netbox_dev.site.slug if netbox_dev.site else None
            if (anguis_dev['site_code'] and nb_site and
                    anguis_dev['site_code'].lower() != nb_site.lower()):  # Compare lowercase
                self.gaps.site_mismatches.append({
                    'name': anguis_dev['name'],
                    'anguis_site': anguis_dev['site_code'],
                    'netbox_site': nb_site
                })

            # Check role mismatch
            nb_role = netbox_dev.role.name if netbox_dev.role else None
            if anguis_dev['role_name'] and nb_role and anguis_dev['role_name'] != nb_role:
                self.gaps.role_mismatches.append({
                    'name': anguis_dev['name'],
                    'anguis_role': anguis_dev['role_name'],
                    'netbox_role': nb_role
                })

            # Check serial mismatch
            nb_serial = netbox_dev.serial if netbox_dev.serial else None
            if anguis_dev['primary_serial'] and nb_serial and anguis_dev['primary_serial'] != nb_serial:
                self.gaps.serial_mismatches.append({
                    'name': anguis_dev['name'],
                    'anguis_serial': anguis_dev['primary_serial'],
                    'netbox_serial': nb_serial
                })

            # Check management IP mismatch (extract from Netbox comments)
            nb_mgmt_ip = None
            if netbox_dev.comments:
                import re
                match = re.search(r'Management IP:\s*(\S+)', netbox_dev.comments)
                if match:
                    nb_mgmt_ip = match.group(1)

            if anguis_dev['management_ip'] and nb_mgmt_ip and anguis_dev['management_ip'] != nb_mgmt_ip:
                self.gaps.ip_mismatches.append({
                    'name': anguis_dev['name'],
                    'anguis_ip': anguis_dev['management_ip'],
                    'netbox_ip': nb_mgmt_ip
                })

        # Report mismatches
        if self.gaps.model_mismatches:
            logger.info(f"   Model mismatches: {len(self.gaps.model_mismatches)}")
            for mismatch in self.gaps.model_mismatches[:5]:
                logger.info(
                    f"     {mismatch['name']}: Anguis={mismatch['anguis_model']}, Netbox={mismatch['netbox_model']}")

        if self.gaps.site_mismatches:
            logger.info(f"   Site mismatches: {len(self.gaps.site_mismatches)}")
            for mismatch in self.gaps.site_mismatches[:5]:
                logger.info(
                    f"     {mismatch['name']}: Anguis={mismatch['anguis_site']}, Netbox={mismatch['netbox_site']}")

        if self.gaps.role_mismatches:
            logger.info(f"   Role mismatches: {len(self.gaps.role_mismatches)}")

        if self.gaps.serial_mismatches:
            logger.info(f"   Serial mismatches: {len(self.gaps.serial_mismatches)}")

        if self.gaps.ip_mismatches:
            logger.info(f"   IP address mismatches: {len(self.gaps.ip_mismatches)}")

        return self.gaps

    def export_gap_report(self, output_dir: str = "."):
        """Export gap analysis to CSV files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Export devices only in Anguis
        if self.gaps.devices_only_in_anguis:
            filename = f"{output_dir}/gap_missing_from_netbox_{timestamp}.csv"
            with open(filename, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['name', 'site', 'vendor', 'model', 'role', 'management_ip',
                                                       'serial'])
                writer.writeheader()
                writer.writerows(self.gaps.devices_only_in_anguis)
            logger.info(f"\nExported missing devices to: {filename}")

        # Export devices only in Netbox
        if self.gaps.devices_only_in_netbox:
            filename = f"{output_dir}/gap_not_discovered_{timestamp}.csv"
            with open(filename, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['name', 'site', 'manufacturer', 'model', 'role', 'status'])
                writer.writeheader()
                writer.writerows(self.gaps.devices_only_in_netbox)
            logger.info(f"Exported undiscovered devices to: {filename}")

        # Export model mismatches
        if self.gaps.model_mismatches:
            filename = f"{output_dir}/gap_model_mismatches_{timestamp}.csv"
            with open(filename, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['name', 'anguis_model', 'netbox_model'])
                writer.writeheader()
                writer.writerows(self.gaps.model_mismatches)
            logger.info(f"Exported model mismatches to: {filename}")

        # Export all mismatches summary
        filename = f"{output_dir}/gap_summary_{timestamp}.csv"
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Gap Type', 'Count'])
            writer.writerow(['Missing from Netbox', len(self.gaps.devices_only_in_anguis)])
            writer.writerow(['Not Discovered by Anguis', len(self.gaps.devices_only_in_netbox)])
            writer.writerow(['Model Mismatches', len(self.gaps.model_mismatches)])
            writer.writerow(['Site Mismatches', len(self.gaps.site_mismatches)])
            writer.writerow(['Role Mismatches', len(self.gaps.role_mismatches)])
            writer.writerow(['Serial Mismatches', len(self.gaps.serial_mismatches)])
            writer.writerow(['IP Mismatches', len(self.gaps.ip_mismatches)])
        logger.info(f"Exported summary to: {filename}")

    def generate_sync_recommendations(self) -> Dict:
        """Generate recommendations for what should be synced"""
        recommendations = {
            'add_to_netbox': [],
            'verify_in_field': [],
            'update_netbox': [],
            'investigate': []
        }

        # Devices discovered by Anguis should be added to Netbox
        for device in self.gaps.devices_only_in_anguis:
            recommendations['add_to_netbox'].append({
                'action': 'ADD',
                'device': device['name'],
                'reason': 'Discovered by Anguis but missing from Netbox',
                'data': device
            })

        # Devices in Netbox but not discovered need investigation
        for device in self.gaps.devices_only_in_netbox:
            if device['status'] == 'active':
                recommendations['verify_in_field'].append({
                    'action': 'VERIFY',
                    'device': device['name'],
                    'reason': 'In Netbox as active but not discovered - may be offline or unreachable',
                    'data': device
                })

        # Model mismatches - Anguis data is authoritative (it's discovered)
        for mismatch in self.gaps.model_mismatches:
            recommendations['update_netbox'].append({
                'action': 'UPDATE',
                'device': mismatch['name'],
                'field': 'model',
                'reason': 'Anguis discovered model differs from Netbox',
                'current_netbox': mismatch['netbox_model'],
                'should_be': mismatch['anguis_model']
            })

        return recommendations

    def run_analysis(self, export: bool = True):
        """Run full gap analysis"""
        try:
            self.connect_db()
            self.analyze_gaps()

            logger.info("\n" + "=" * 80)
            logger.info("GAP ANALYSIS SUMMARY")
            logger.info("=" * 80)
            logger.info(f"Total gaps found: {self.gaps.total_gaps()}")
            logger.info(f"  Missing from Netbox: {len(self.gaps.devices_only_in_anguis)}")
            logger.info(f"  Not discovered: {len(self.gaps.devices_only_in_netbox)}")
            logger.info(
                f"  Data mismatches: {len(self.gaps.model_mismatches) + len(self.gaps.site_mismatches) + len(self.gaps.role_mismatches)}")

            if export:
                self.export_gap_report()

            # Generate recommendations
            recommendations = self.generate_sync_recommendations()
            logger.info(f"\nRECOMMENDATIONS:")
            logger.info(f"  Devices to add to Netbox: {len(recommendations['add_to_netbox'])}")
            logger.info(f"  Devices to verify in field: {len(recommendations['verify_in_field'])}")
            logger.info(f"  Netbox records to update: {len(recommendations['update_netbox'])}")

        finally:
            self.disconnect_db()


if __name__ == "__main__":
    DB_PATH = "assets.db"
    NETBOX_URL = "http://10.0.0.108:8000"
    NETBOX_TOKEN = "9bad24d80da7275c2b8738f235e57a83a6e546b2"

    analyzer = NetboxGapAnalyzer(DB_PATH, NETBOX_URL, NETBOX_TOKEN)
    analyzer.run_analysis(export=True)