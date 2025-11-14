#!/usr/bin/env python3
"""
Component Cleanup Utility

Removes component entries from assets.db without resetting the entire database.
"""

import sqlite3
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ComponentCleanup:
    """Clean component data from assets database"""

    def __init__(self, db_path: str = "assets.db"):
        self.db_path = db_path

    def cleanup_all_components(self) -> int:
        """Delete all component records"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get count before deletion
            cursor.execute("SELECT COUNT(*) FROM components")
            count = cursor.fetchone()[0]

            if count == 0:
                logger.info("No components to clean up")
                conn.close()
                return 0

            # Delete all components
            cursor.execute("DELETE FROM components")
            conn.commit()

            # Verify deletion
            cursor.execute("SELECT COUNT(*) FROM components")
            remaining = cursor.fetchone()[0]

            conn.close()

            logger.info(f"Deleted {count} component records")
            if remaining > 0:
                logger.warning(f"Warning: {remaining} records remaining")

            return count

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    def cleanup_by_device(self, device_id: int = None, device_name: str = None) -> int:
        """Delete components for specific device(s)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if device_id:
                cursor.execute("SELECT COUNT(*) FROM components WHERE device_id = ?", (device_id,))
                count = cursor.fetchone()[0]

                cursor.execute("DELETE FROM components WHERE device_id = ?", (device_id,))
                conn.commit()

                logger.info(f"Deleted {count} components for device_id={device_id}")

            elif device_name:
                # Get device IDs matching name pattern
                cursor.execute("""
                    SELECT id, name FROM devices 
                    WHERE name LIKE ? OR normalized_name LIKE ?
                """, (f"%{device_name}%", f"%{device_name}%"))

                devices = cursor.fetchall()
                total_deleted = 0

                for dev_id, dev_name in devices:
                    cursor.execute("SELECT COUNT(*) FROM components WHERE device_id = ?", (dev_id,))
                    count = cursor.fetchone()[0]

                    cursor.execute("DELETE FROM components WHERE device_id = ?", (dev_id,))
                    total_deleted += count

                    logger.info(f"Deleted {count} components from {dev_name}")

                conn.commit()
                logger.info(f"Total deleted: {total_deleted} components from {len(devices)} devices")
                return total_deleted

            conn.close()
            return count if device_id else 0

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    def cleanup_by_source(self, extraction_source: str) -> int:
        """Delete components by extraction source"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM components WHERE extraction_source = ?",
                (extraction_source,)
            )
            count = cursor.fetchone()[0]

            cursor.execute(
                "DELETE FROM components WHERE extraction_source = ?",
                (extraction_source,)
            )
            conn.commit()
            conn.close()

            logger.info(f"Deleted {count} components with source='{extraction_source}'")
            return count

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    def get_statistics(self) -> dict:
        """Get component statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            stats = {}

            # Total components
            cursor.execute("SELECT COUNT(*) FROM components")
            stats['total_components'] = cursor.fetchone()[0]

            # By device
            cursor.execute("SELECT COUNT(DISTINCT device_id) FROM components")
            stats['devices_with_components'] = cursor.fetchone()[0]

            # By type
            cursor.execute("""
                SELECT type, COUNT(*) as count 
                FROM components 
                GROUP BY type 
                ORDER BY count DESC
            """)
            stats['by_type'] = dict(cursor.fetchall())

            # By source
            cursor.execute("""
                SELECT extraction_source, COUNT(*) as count 
                FROM components 
                GROUP BY extraction_source
            """)
            stats['by_source'] = dict(cursor.fetchall())

            # With serials
            cursor.execute("SELECT COUNT(*) FROM components WHERE have_sn = 1")
            stats['with_serial'] = cursor.fetchone()[0]

            conn.close()
            return stats

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return {}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Clean component data from assets database")
    parser.add_argument("--db", default="assets.db", help="Path to assets database")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Delete all components")
    group.add_argument("--device-id", type=int, help="Delete components for specific device ID")
    group.add_argument("--device-name", help="Delete components for devices matching name")
    group.add_argument("--source", help="Delete components by extraction source")
    group.add_argument("--stats", action="store_true", help="Show component statistics")

    parser.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    cleanup = ComponentCleanup(db_path=args.db)

    # Show stats
    if args.stats:
        stats = cleanup.get_statistics()
        print("\nComponent Statistics:")
        print(f"  Total components: {stats.get('total_components', 0)}")
        print(f"  Devices with components: {stats.get('devices_with_components', 0)}")
        print(f"  Components with serials: {stats.get('with_serial', 0)}")

        print("\n  By Type:")
        for comp_type, count in stats.get('by_type', {}).items():
            print(f"    {comp_type or 'unknown'}: {count}")

        print("\n  By Source:")
        for source, count in stats.get('by_source', {}).items():
            print(f"    {source or 'unknown'}: {count}")

        return 0

    # Confirm deletion
    if not args.confirm:
        response = input("\nThis will delete component records. Continue? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled")
            return 0

    # Execute cleanup
    if args.all:
        count = cleanup.cleanup_all_components()
    elif args.device_id:
        count = cleanup.cleanup_by_device(device_id=args.device_id)
    elif args.device_name:
        count = cleanup.cleanup_by_device(device_name=args.device_name)
    elif args.source:
        count = cleanup.cleanup_by_source(args.source)

    print(f"\nCleaned up {count} component records")
    return 0


if __name__ == "__main__":
    exit(main())