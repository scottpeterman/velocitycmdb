"""
Database status checker
"""
import sqlite3
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DatabaseChecker:
    """Check database initialization status"""

    def __init__(self, data_dir='~/.velocitycmdb/data'):
        self.data_dir = Path(data_dir).expanduser()
        self.assets_db = self.data_dir / 'assets.db'
        self.arp_db = self.data_dir / 'arp_cat.db'
        self.users_db = self.data_dir / 'users.db'

    def needs_initialization(self):
        """
        Check if databases need initialization
        Returns: True if needs init, False if already initialized
        """
        # Check if all three databases exist
        if not all([
            self.assets_db.exists(),
            self.arp_db.exists(),
            self.users_db.exists()
        ]):
            return True

        # Check if assets database has any devices
        try:
            conn = sqlite3.connect(str(self.assets_db))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM devices")
            device_count = cursor.fetchone()[0]
            conn.close()

            # If no devices, needs initialization
            return device_count == 0

        except Exception as e:
            logger.error(f"Error checking database: {e}")
            return True

    def get_status(self):
        """
        Get detailed database status
        Returns: dict with status information
        """
        status = {
            'assets_db': {
                'exists': self.assets_db.exists(),
                'size': self.assets_db.stat().st_size if self.assets_db.exists() else 0,
                'device_count': 0,
                'site_count': 0
            },
            'arp_db': {
                'exists': self.arp_db.exists(),
                'size': self.arp_db.stat().st_size if self.arp_db.exists() else 0,
                'entry_count': 0
            },
            'users_db': {
                'exists': self.users_db.exists(),
                'size': self.users_db.stat().st_size if self.users_db.exists() else 0,
                'user_count': 0
            }
        }

        # Get device count
        if self.assets_db.exists():
            try:
                conn = sqlite3.connect(str(self.assets_db))
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) FROM devices")
                status['assets_db']['device_count'] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM sites")
                status['assets_db']['site_count'] = cursor.fetchone()[0]

                conn.close()
            except:
                pass

        # Get ARP entry count
        if self.arp_db.exists():
            try:
                conn = sqlite3.connect(str(self.arp_db))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM arp_entries WHERE is_current = 1")
                status['arp_db']['entry_count'] = cursor.fetchone()[0]
                conn.close()
            except:
                pass

        # Get user count
        if self.users_db.exists():
            try:
                conn = sqlite3.connect(str(self.users_db))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                status['users_db']['user_count'] = cursor.fetchone()[0]
                conn.close()
            except:
                pass

        return status