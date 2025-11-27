#!/usr/bin/env python3
"""
Component Reclassifier v3

Reclassifies unknown components using pattern matching.
"""

import sqlite3
import re
import logging
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ComponentReclassifier:
    """Reclassify unknown components using pattern matching"""

    TYPE_PATTERNS = {
        'transceiver': [
            r'\bXcvr\b', r'\bSFP\b', r'\bQSFP\b', r'\bXFP\b', r'\bCFP\b',
            r'\bQSFP\+\b', r'\bQSFP28\b', r'\bQSFP-DD\b', r'-T$',
            r'\boptic', r'transceiver', r'GLC-', r'SFP\+-\d+G',
            r'QSFP-\d+G', r'^Q\d+-', r'^ET-', r'-CWDM',
            r'-LR\d*$', r'-SR\d*$', r'\bgbic\b',
            r'SFPP-',
        ],
        'psu': [
            r'\bPWR\b', r'\bPSU\b', r'\bPS\d+\b',
            r'\bpower\s*supply\b', r'power\s+supply', r'^Power$',
            r'\bpower\s*module\b', r'PWR-\w+', r'C3K-PWR',
            r'AIR-PWR', r'^PWR-\d+', r'\bPEM\b', r'JPSU-',
        ],
        'fan': [
            r'\bFAN\b', r'\bcooling\b', r'fan\s*tray',
            r'fan\s*module', r'FAN-\w+',
        ],
        'supervisor': [
            r'\bsupervisor\b', r'\bsup\b', r'\bengine\b',
            r'routing\s*engine', r'\bRE\b', r'\bRP\b',
            r'supervisor\s*module', r'WS-SUP', r'\bCPU\b',
            r'management\s*module', r'^Routing\s+Engine', r'RE-\w+',
        ],
        'module': [
            r'\bmodule\b', r'\bcard\b', r'\blinecard\b',
            r'\bline\s*card\b', r'\bPIC\b', r'\bFPC\b', r'\bMIC\b',
            r'WS-X\d+', r'C\d+K-\d+PORT', r'interface\s*card',
            r'\bAFEB\b', r'\bMidplane\b',
            r'^Management$',
        ],
        'chassis': [
            r'\bchassis\b', r'\bCHAS\b', r'C\d+K-CHAS', r'-CHAS$',
            r'^DCS-\d+', r'^WS-C\d+', r'\bstack\b', r'\bswitch\s+\d+',
        ],
    }

    DESC_PATTERNS = {
        'transceiver': [
            r'1000BASE', r'10GBASE', r'25GBASE', r'40GBASE',
            r'100GBASE', r'\bSR\b', r'\bLR\b', r'\bER\b',
        ],
    }

    JUNK_PATTERNS = [
        r'^Item\s+Version',
        r'^Screen\s+length',
        r'^----+$',
        r'^\s*$',
        r'^Traceback',
        r'^File\s+"/.*\.py"',
        r'^\s*from\s+',
        r'^\s*import\s+',
        r'^Fatal\s+Python\s+error',
        r'<frozen\s+importlib',
        r'<module>$',
        r'\.py",\s+line',
        r'/site-packages/',
        r'/lib/python',
        r'_bootstrap',
        r'exec_module',
        r'get_code',
        r'get_data',
        r'_find_and_load',
        r'path\.search',

        # Cisco IOSv EULA/legal text
        r'IOSv is strictly limited to use for evaluation',
        r'IOSv is provided as-is and is not supported',
        r'Technical Advisory Center',
        r'Any use or disclosure.*to any third party',
        r'purposes is',
        r'except as otherwise',
        r'demonstration.*education',
        r'in whole or',
        r'of the IOSv Software',

        # Generic legal/EULA patterns
        r'^\s*\*\s*$',  # Lines with just asterisks
        r'unknown`\*`—',  # IOSv-specific formatting
    ]

    JUNK_WORDS = {
        'Item', 'Screen', 'Networks', 'Switched', 'SwitchedBootstrap',
        'Bootstrap', 'File', 'Traceback', 'from', 'import', 'Routing'
    }

    def __init__(self, db_path: str = "assets.db", dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.stats = defaultdict(int)

    def is_junk(self, name: str, description: str = "") -> bool:
        if name.strip() in self.JUNK_WORDS:
            return True

        text = f"{name} {description}"
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in self.JUNK_PATTERNS)

    def classify_component(self, name: str, description: str = "",
                          current_type: str = None) -> Tuple[Optional[str], str]:
        if not name:
            return None, 'low'

        if self.is_junk(name, description):
            return 'junk', 'high'

        for comp_type, patterns in self.TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, name, re.IGNORECASE):
                    return comp_type, 'high'

        for comp_type, patterns in self.DESC_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, description or '', re.IGNORECASE):
                    return comp_type, 'medium'

        return None, 'low'

    def reclassify_unknown(self) -> Dict[str, int]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, name, description, type, device_id
                FROM components
                WHERE type = 'unknown' OR type IS NULL
            """)

            unknown_components = cursor.fetchall()
            logger.info(f"Found {len(unknown_components)} unknown components to reclassify")

            reclassified = defaultdict(int)
            updates = []

            for comp in unknown_components:
                new_type, confidence = self.classify_component(
                    comp['name'],
                    comp['description'] or '',
                    comp['type']
                )

                if new_type and new_type != 'unknown':
                    reclassified[new_type] += 1
                    updates.append({
                        'id': comp['id'],
                        'name': comp['name'],
                        'old_type': comp['type'],
                        'new_type': new_type,
                        'confidence': confidence
                    })

                    if confidence == 'high':
                        self.stats['high_confidence'] += 1
                    elif confidence == 'medium':
                        self.stats['medium_confidence'] += 1

            if updates:
                logger.info("\nSample reclassifications:")
                for update in updates[:20]:
                    logger.info(
                        f"  {update['name'][:40]:40} → {update['new_type']:12} "
                        f"({update['confidence']})"
                    )

            if not self.dry_run and updates:
                for update in updates:
                    cursor.execute("""
                        UPDATE components 
                        SET type = ?, subtype = 'reclassified'
                        WHERE id = ?
                    """, (update['new_type'], update['id']))

                conn.commit()
                logger.info(f"\n✓ Updated {len(updates)} components")
            elif self.dry_run:
                logger.info(f"\n[DRY RUN] Would update {len(updates)} components")

            conn.close()
            return dict(reclassified)

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return {}

    def delete_junk_components(self) -> int:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT id, name, description FROM components")
            all_components = cursor.fetchall()

            junk_ids = []
            for comp in all_components:
                if self.is_junk(comp['name'], comp['description'] or ''):
                    junk_ids.append(comp['id'])

            logger.info(f"Found {len(junk_ids)} junk components")

            if not self.dry_run and junk_ids:
                placeholders = ','.join('?' * len(junk_ids))
                cursor.execute(
                    f"DELETE FROM components WHERE id IN ({placeholders})",
                    junk_ids
                )
                conn.commit()
                logger.info(f"✓ Deleted {len(junk_ids)} junk components")
            elif self.dry_run:
                logger.info(f"[DRY RUN] Would delete {len(junk_ids)} junk components")

            conn.close()
            return len(junk_ids)

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return 0

    def analyze_remaining_unknown(self) -> List[Dict]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    c.name, c.description, c.type,
                    d.name as device_name, d.model as device_model,
                    COUNT(*) as count
                FROM components c
                JOIN devices d ON c.device_id = d.id
                WHERE c.type = 'unknown' OR c.type IS NULL
                GROUP BY c.name, c.description, d.model
                ORDER BY count DESC
                LIMIT 50
            """)

            remaining = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if remaining:
                logger.info("\nTop 20 remaining 'unknown' patterns:")
                logger.info("=" * 100)
                for item in remaining[:20]:
                    logger.info(
                        f"{item['count']:4} × {item['name'][:40]:40} "
                        f"| {item['device_model'][:20]:20}"
                    )

            return remaining

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []

    def generate_statistics(self) -> Dict:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            stats = {}

            cursor.execute("""
                SELECT type, COUNT(*) as count
                FROM components
                GROUP BY type
                ORDER BY count DESC
            """)
            stats['by_type'] = dict(cursor.fetchall())

            total = sum(stats['by_type'].values())
            unknown = stats['by_type'].get('unknown', 0)
            stats['unknown_pct'] = (unknown / total * 100) if total > 0 else 0

            cursor.execute("""
                SELECT COUNT(*) FROM components WHERE subtype = 'reclassified'
            """)
            stats['reclassified_count'] = cursor.fetchone()[0]

            conn.close()
            return stats

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return {}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reclassify unknown components")
    parser.add_argument("--db", default="assets.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delete-junk", action="store_true")
    parser.add_argument("--analyze", action="store_true")

    args = parser.parse_args()

    reclassifier = ComponentReclassifier(db_path=args.db, dry_run=args.dry_run)

    initial_stats = reclassifier.generate_statistics()
    total = sum(initial_stats['by_type'].values())
    unknown = initial_stats['by_type'].get('unknown', 0)

    print("\n" + "=" * 80)
    print("INITIAL STATE")
    print("=" * 80)
    print(f"Total components: {total}")
    print(f"Unknown: {unknown} ({initial_stats['unknown_pct']:.1f}%)")
    print("\nBy Type:")
    for comp_type, count in sorted(
        initial_stats['by_type'].items(),
        key=lambda x: x[1],
        reverse=True
    ):
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {comp_type or 'NULL':15} {count:5} ({pct:5.1f}%)")

    if args.delete_junk:
        print("\n" + "=" * 80)
        print("DELETING JUNK COMPONENTS")
        print("=" * 80)
        deleted = reclassifier.delete_junk_components()

    print("\n" + "=" * 80)
    print("RECLASSIFYING UNKNOWN COMPONENTS")
    print("=" * 80)
    reclassified = reclassifier.reclassify_unknown()

    if reclassified:
        print("\nReclassification Results:")
        for comp_type, count in sorted(
            reclassified.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            print(f"  {comp_type:15} {count:5}")

    final_stats = reclassifier.generate_statistics()
    total = sum(final_stats['by_type'].values())
    unknown = final_stats['by_type'].get('unknown', 0)

    print("\n" + "=" * 80)
    print("FINAL STATE")
    print("=" * 80)
    print(f"Total components: {total}")
    print(f"Unknown: {unknown} ({final_stats['unknown_pct']:.1f}%)")
    print(f"Reclassified: {final_stats['reclassified_count']}")
    print("\nBy Type:")
    for comp_type, count in sorted(
        final_stats['by_type'].items(),
        key=lambda x: x[1],
        reverse=True
    ):
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {comp_type or 'NULL':15} {count:5} ({pct:5.1f}%)")

    if args.analyze:
        print("\n" + "=" * 80)
        print("ANALYZING REMAINING UNKNOWNS")
        print("=" * 80)
        reclassifier.analyze_remaining_unknown()

    return 0


if __name__ == "__main__":
    exit(main())