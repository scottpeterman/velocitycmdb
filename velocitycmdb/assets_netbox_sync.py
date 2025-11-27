"""
netbox_sync.py - Sync AngularNMS devices to Netbox
Place this in: uguis/netbox_sync/
"""

import sqlite3
import pynetbox
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Track sync statistics"""
    sites_created: int = 0
    sites_updated: int = 0
    manufacturers_created: int = 0
    platforms_created: int = 0
    roles_created: int = 0
    devices_created: int = 0
    devices_updated: int = 0
    devices_skipped: int = 0
    errors: List[str] = field(default_factory=list)
    skip_reasons: Dict[str, int] = field(default_factory=dict)


class AngularNMSNetboxSync:
    """Sync AngularNMS database to Netbox"""

    def __init__(self, db_path: str, netbox_url: str, netbox_token: str):
        self.db_path = db_path
        self.nb = pynetbox.api(netbox_url, token=netbox_token)
        self.conn = None
        self.stats = SyncStats()

        # Cache for lookups to minimize API calls
        self.cache = {
            'sites': {},
            'manufacturers': {},
            'platforms': {},
            'device_roles': {},
            'device_types': {},
            'devices': {}
        }

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

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug (max 100 chars for Netbox)"""
        import re
        if not text:
            return 'unknown'
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        # Netbox has 100 char slug limit
        return text[:100]

    def _increment_skip_reason(self, reason: str):
        """Track why devices are being skipped"""
        if reason not in self.stats.skip_reasons:
            self.stats.skip_reasons[reason] = 0
        self.stats.skip_reasons[reason] += 1

    def get_or_create_site(self, code: str, name: str, description: str = None) -> int:
        """Get existing site or create new one"""
        if not code or not name:
            raise ValueError("Site code and name are required")

        if code in self.cache['sites']:
            return self.cache['sites'][code]

        # Try to find existing
        existing = self.nb.dcim.sites.get(slug=self._slugify(code))
        if existing:
            self.cache['sites'][code] = existing.id
            logger.debug(f"Found existing site: {name} ({code})")
            return existing.id

        # Create new
        try:
            site = self.nb.dcim.sites.create(
                name=name,
                slug=self._slugify(code),
                description=description or '',
                status='active'
            )
            self.cache['sites'][code] = site.id
            self.stats.sites_created += 1
            logger.info(f"Created site: {name} ({code})")
            return site.id
        except Exception as e:
            logger.error(f"Error creating site {name}: {e}")
            self.stats.errors.append(f"Site {name}: {str(e)}")
            raise

    def get_or_create_manufacturer(self, name: str, short_name: str = None) -> int:
        """Get existing manufacturer or create new one"""
        if not name:
            name = "Unknown"

        if name in self.cache['manufacturers']:
            return self.cache['manufacturers'][name]

        existing = self.nb.dcim.manufacturers.get(name=name)
        if existing:
            self.cache['manufacturers'][name] = existing.id
            logger.debug(f"Found existing manufacturer: {name}")
            return existing.id

        try:
            mfg = self.nb.dcim.manufacturers.create(
                name=name,
                slug=self._slugify(name),
                description=short_name or ''
            )
            self.cache['manufacturers'][name] = mfg.id
            self.stats.manufacturers_created += 1
            logger.info(f"Created manufacturer: {name}")
            return mfg.id
        except Exception as e:
            logger.error(f"Error creating manufacturer {name}: {e}")
            self.stats.errors.append(f"Manufacturer {name}: {str(e)}")
            raise

    def get_or_create_platform(self, name: str, manufacturer_name: str = None,
                               netmiko_driver: str = None, napalm_driver: str = None) -> int:
        """Get existing platform or create new one"""
        if not name:
            name = "Unknown"

        if name in self.cache['platforms']:
            return self.cache['platforms'][name]

        existing = self.nb.dcim.platforms.get(name=name)
        if existing:
            self.cache['platforms'][name] = existing.id
            logger.debug(f"Found existing platform: {name}")
            return existing.id

        try:
            platform_data = {
                'name': name,
                'slug': self._slugify(name)
            }

            if manufacturer_name:
                mfg_id = self.get_or_create_manufacturer(manufacturer_name)
                platform_data['manufacturer'] = mfg_id

            if netmiko_driver:
                platform_data['netmiko_driver'] = netmiko_driver
            if napalm_driver:
                platform_data['napalm_driver'] = napalm_driver

            platform = self.nb.dcim.platforms.create(**platform_data)
            self.cache['platforms'][name] = platform.id
            self.stats.platforms_created += 1
            logger.info(f"Created platform: {name}")
            return platform.id
        except Exception as e:
            logger.error(f"Error creating platform {name}: {e}")
            self.stats.errors.append(f"Platform {name}: {str(e)}")
            raise

    def get_or_create_device_role(self, name: str, description: str = None,
                                  is_infrastructure: bool = False) -> int:
        """Get existing device role or create new one"""
        if not name:
            name = "Unknown"

        if name in self.cache['device_roles']:
            return self.cache['device_roles'][name]

        existing = self.nb.dcim.device_roles.get(name=name)
        if existing:
            self.cache['device_roles'][name] = existing.id
            logger.debug(f"Found existing device role: {name}")
            return existing.id

        try:
            # Color codes for common roles
            role_colors = {
                'router': 'f44336',  # Red
                'switch': '2196f3',  # Blue
                'firewall': 'ff9800',  # Orange
                'access-switch': '4caf50',  # Green
                'core-switch': '9c27b0',  # Purple
                'distribution': '00bcd4',  # Cyan
                'unknown': '607d8b'  # Grey
            }
            color = role_colors.get(name.lower(), '607d8b')  # Default grey

            role = self.nb.dcim.device_roles.create(
                name=name,
                slug=self._slugify(name),
                color=color,
                description=description or '',
                vm_role=False
            )
            self.cache['device_roles'][name] = role.id
            self.stats.roles_created += 1
            logger.info(f"Created device role: {name}")
            return role.id
        except Exception as e:
            logger.error(f"Error creating device role {name}: {e}")
            self.stats.errors.append(f"Device role {name}: {str(e)}")
            raise

    def get_or_create_device_type(self, model: str, manufacturer_name: str) -> int:
        """Get existing device type or create new one"""
        if not model:
            model = "Unknown"
        if not manufacturer_name:
            manufacturer_name = "Unknown"

        cache_key = f"{manufacturer_name}:{model}"
        if cache_key in self.cache['device_types']:
            return self.cache['device_types'][cache_key]

        mfg_id = self.get_or_create_manufacturer(manufacturer_name)

        # Try to find existing device type
        existing = list(self.nb.dcim.device_types.filter(
            manufacturer_id=mfg_id,
            model=model
        ))

        if existing:
            device_type = existing[0]
            self.cache['device_types'][cache_key] = device_type.id
            logger.debug(f"Found existing device type: {model}")
            return device_type.id

        try:
            # Ensure slug doesn't exceed limit
            slug = self._slugify(f"{manufacturer_name}-{model}")

            device_type = self.nb.dcim.device_types.create(
                model=model,
                slug=slug,
                manufacturer=mfg_id,
                u_height=1  # Default to 1U
            )
            self.cache['device_types'][cache_key] = device_type.id
            logger.info(f"Created device type: {model} ({manufacturer_name})")
            return device_type.id
        except Exception as e:
            logger.error(f"Error creating device type {model}: {e}")
            self.stats.errors.append(f"Device type {model}: {str(e)}")
            raise

    def sync_sites(self) -> int:
        """Sync all sites from AngularNMS to Netbox"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT code, name, description FROM sites")

        count = 0
        for row in cursor.fetchall():
            try:
                self.get_or_create_site(row['code'], row['name'], row['description'])
                count += 1
            except Exception as e:
                logger.error(f"Failed to sync site {row['name']}: {e}")

        logger.info(f"Synced {count} sites")
        return count

    def sync_vendors(self) -> int:
        """Sync all vendors/manufacturers from AngularNMS to Netbox"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name, short_name FROM vendors")

        count = 0
        for row in cursor.fetchall():
            try:
                self.get_or_create_manufacturer(row['name'], row['short_name'])
                count += 1
            except Exception as e:
                logger.error(f"Failed to sync vendor {row['name']}: {e}")

        logger.info(f"Synced {count} vendors")
        return count

    def sync_device_types_and_platforms(self) -> Tuple[int, int]:
        """Sync device types (as platforms) from AngularNMS to Netbox"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, netmiko_driver, napalm_driver, description
            FROM device_types
        """)

        platform_count = 0
        for row in cursor.fetchall():
            try:
                self.get_or_create_platform(
                    row['name'],
                    netmiko_driver=row['netmiko_driver'],
                    napalm_driver=row['napalm_driver']
                )
                platform_count += 1
            except Exception as e:
                logger.error(f"Failed to sync platform {row['name']}: {e}")

        logger.info(f"Synced {platform_count} platforms")
        return platform_count, 0

    def sync_device_roles(self) -> int:
        """Sync device roles from AngularNMS to Netbox"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, description, is_infrastructure
            FROM device_roles
        """)

        count = 0
        for row in cursor.fetchall():
            try:
                self.get_or_create_device_role(
                    row['name'],
                    row['description'],
                    bool(row['is_infrastructure'])
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to sync device role {row['name']}: {e}")

        logger.info(f"Synced {count} device roles")
        return count

    def sync_devices(self, dry_run: bool = False) -> int:
        """Sync all devices from AngularNMS to Netbox"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 
                d.id,
                d.name,
                d.normalized_name,
                d.site_code,
                d.model,
                d.os_version,
                d.management_ip,
                d.ipv4_address,
                v.name as vendor_name,
                dt.name as device_type_name,
                dr.name as role_name,
                ds.serial as primary_serial
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN device_types dt ON d.device_type_id = dt.id
            LEFT JOIN device_roles dr ON d.role_id = dr.id
            LEFT JOIN device_serials ds ON d.id = ds.device_id AND ds.is_primary = 1
            WHERE d.name IS NOT NULL
            ORDER BY d.name
        """)

        count = 0
        for row in cursor.fetchall():
            try:
                if dry_run:
                    logger.info(f"[DRY RUN] Would sync device: {row['name']}")
                    continue

                self._sync_single_device(dict(row))
                count += 1

            except Exception as e:
                logger.error(f"Failed to sync device {row['name']}: {e}")
                self.stats.devices_skipped += 1

        logger.info(f"Synced {count} devices")
        return count

    def _sync_single_device(self, device_data: Dict):
        """Sync a single device to Netbox"""
        device_name = device_data.get('name', 'Unknown')

        # Handle missing vendor/model with defaults
        vendor_name = device_data.get('vendor_name') or 'Unknown'
        model = device_data.get('model') or 'Unknown Model'

        if vendor_name == 'Unknown' or model == 'Unknown Model':
            logger.warning(f"Device {device_name} has missing vendor/model - using defaults")
            self._increment_skip_reason('missing_vendor_or_model')

        # Ensure dependencies exist
        site_id = None
        if device_data.get('site_code'):
            cursor = self.conn.cursor()
            cursor.execute("SELECT name, description FROM sites WHERE code = ?",
                           (device_data['site_code'],))
            site_row = cursor.fetchone()
            if site_row:
                try:
                    site_id = self.get_or_create_site(
                        device_data['site_code'],
                        site_row['name'],
                        site_row['description']
                    )
                except Exception as e:
                    logger.error(f"Failed to get/create site for {device_name}: {e}")

        if not site_id:
            logger.warning(f"Skipping {device_name}: no valid site")
            self.stats.devices_skipped += 1
            self._increment_skip_reason('no_site')
            self.stats.errors.append(f"Device {device_name}: No valid site")
            return

        # Handle role - provide default if missing
        role_id = None
        if device_data.get('role_name'):
            try:
                role_id = self.get_or_create_device_role(device_data['role_name'])
            except Exception as e:
                logger.warning(f"Failed to get/create role for {device_name}: {e}")

        # If still no role, create/use default
        if not role_id:
            try:
                role_id = self.get_or_create_device_role(
                    'Unknown',
                    'Devices without assigned role'
                )
                logger.info(f"Assigned default 'Unknown' role to {device_name}")
            except Exception as e:
                logger.error(f"Failed to create default role for {device_name}: {e}")
                self.stats.devices_skipped += 1
                self._increment_skip_reason('role_error')
                self.stats.errors.append(f"Device {device_name}: {str(e)}")
                return

        platform_id = None
        if device_data.get('device_type_name'):
            try:
                platform_id = self.get_or_create_platform(
                    device_data['device_type_name'],
                    vendor_name
                )
            except Exception as e:
                logger.warning(f"Failed to get/create platform for {device_name}: {e}")

        try:
            device_type_id = self.get_or_create_device_type(model, vendor_name)
        except Exception as e:
            logger.error(f"Failed to get/create device type for {device_name}: {e}")
            self.stats.devices_skipped += 1
            self._increment_skip_reason('device_type_error')
            self.stats.errors.append(f"Device {device_name}: {str(e)}")
            return

        # Check if device already exists
        existing_device = self.nb.dcim.devices.get(name=device_name)

        device_payload = {
            'name': device_name,
            'device_type': device_type_id,
            'site': site_id,
            'role': role_id,
            'status': 'active'
        }

        if platform_id:
            device_payload['platform'] = platform_id
        if device_data.get('primary_serial'):
            device_payload['serial'] = device_data['primary_serial']

        # Build comments with available info
        comments = []
        if device_data.get('management_ip'):
            comments.append(f"Management IP: {device_data['management_ip']}")
        if device_data.get('os_version'):
            comments.append(f"OS Version: {device_data['os_version']}")
        if comments:
            device_payload['comments'] = '\n'.join(comments)

        try:
            if existing_device:
                for key, value in device_payload.items():
                    setattr(existing_device, key, value)
                existing_device.save()
                self.stats.devices_updated += 1
                logger.info(f"Updated device: {device_name}")
            else:
                device = self.nb.dcim.devices.create(**device_payload)
                self.stats.devices_created += 1
                logger.info(f"Created device: {device_name}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error syncing device {device_name}: {error_msg}")
            self.stats.devices_skipped += 1
            self._increment_skip_reason('netbox_api_error')
            self.stats.errors.append(f"Device {device_name}: {error_msg}")

    def full_sync(self, dry_run: bool = False):
        """Perform a full sync of all data"""
        logger.info("=" * 80)
        logger.info(f"Starting {'DRY RUN' if dry_run else 'FULL SYNC'} from AngularNMS to Netbox")
        logger.info("=" * 80)

        try:
            self.connect_db()

            logger.info("\n1. Syncing Sites...")
            self.sync_sites()

            logger.info("\n2. Syncing Vendors/Manufacturers...")
            self.sync_vendors()

            logger.info("\n3. Syncing Device Types and Platforms...")
            self.sync_device_types_and_platforms()

            logger.info("\n4. Syncing Device Roles...")
            self.sync_device_roles()

            logger.info("\n5. Syncing Devices...")
            self.sync_devices(dry_run=dry_run)

            logger.info("\n" + "=" * 80)
            logger.info("SYNC SUMMARY")
            logger.info("=" * 80)
            logger.info(f"Sites Created: {self.stats.sites_created}")
            logger.info(f"Manufacturers Created: {self.stats.manufacturers_created}")
            logger.info(f"Platforms Created: {self.stats.platforms_created}")
            logger.info(f"Roles Created: {self.stats.roles_created}")
            logger.info(f"Devices Created: {self.stats.devices_created}")
            logger.info(f"Devices Updated: {self.stats.devices_updated}")
            logger.info(f"Devices Skipped: {self.stats.devices_skipped}")

            if self.stats.skip_reasons:
                logger.info("\nSkip Reasons Breakdown:")
                for reason, count in sorted(self.stats.skip_reasons.items(),
                                           key=lambda x: x[1], reverse=True):
                    logger.info(f"  {reason}: {count}")

            if self.stats.errors:
                logger.warning(f"\nErrors encountered: {len(self.stats.errors)}")
                for error in self.stats.errors[:20]:
                    logger.warning(f"  - {error}")
                if len(self.stats.errors) > 20:
                    logger.warning(f"  ... and {len(self.stats.errors) - 20} more errors")

        finally:
            self.disconnect_db()


if __name__ == "__main__":
    DB_PATH = "assets.db"
    NETBOX_URL = "http://10.0.0.108:8000"
    NETBOX_TOKEN = "9bad24d80da7275c2b8738f235e57a83a6e546b2"

    syncer = AngularNMSNetboxSync(DB_PATH, NETBOX_URL, NETBOX_TOKEN)
    syncer.full_sync(dry_run=False)