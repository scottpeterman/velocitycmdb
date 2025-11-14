#!/usr/bin/env python3
"""
Component Type Fixup Script
Analyzes and fixes component types in the assets.db database
"""

import sqlite3
import re
from collections import Counter
from typing import Dict, List, Tuple, Optional

DB_PATH = "assets.db"

# Pattern-based rules for component type detection
TYPE_PATTERNS = {
    'transceiver': [
        r'gi\d+/\d+/\d+',  # GigabitEthernet interfaces
        r'te\d+/\d+/\d+',  # TenGigabitEthernet
        r'tengigabitethernet\d+/\d+/\d+',  # TenGigabitEthernet
        r'\d+base',  # 1000Base, 10/100/1000
        r'gbic',
        r'sfp',
        r'xfp',
        r'qsfp',
        r'cab-[qs]-[qs]-\d+g',  # CAB-Q-Q-100G, CAB-S-S-25G cables
        r'cisco-methode',  # Cisco optics/transceivers
    ],
    'fan': [
        r'\bfan\b',
        r'fan\s*\d+',
        r'fan\s*tray',
        r'fan\s*module',
    ],
    'psu': [
        r'\bpsu\b',
        r'power\s*supply',
        r'pw\s*\d+',
        r'ps\d+',
        r'pwr-\d+-ac',  # PWR-1-AC, PWR-2-AC-RED patterns
    ],
    'supervisor': [
        r'\bsup\b',
        r'supervisor',
        r'management',
        r'control.*module',
    ],
    'chassis': [
        r'\bchassis\b',
        r'nexus\s*\d+',
        r'catalyst\s*\d+',
        r'switch\s*chassis',
    ],
    'module': [
        r'\bmodule\b',
        r'linecard',
        r'blade',
        r'\bslot\s*\d+',
        r'voice\s*interface.*daughtercard',  # Voice interface cards
        r'fxs\s*did',  # FXS DID voice cards
        r'rtx\w+-\d+-\w+',  # RTXMN-1-CN type modules
        r'sfc\w+-\w+-\w+-enc',  # SFCN-CIIN-NM-ENC type modules
    ],
}

# Substring matching for names (case-insensitive)
NAME_KEYWORDS = {
    'fan': ['fan'],
    'psu': ['power supply', 'psu', 'power', 'pwr-'],
    'transceiver': ['sfp', 'gbic', 'xfp', 'qsfp', '1000base', '10/100', 'tengigabitethernet', 'cab-q-q', 'cab-s-s',
                    'cisco-methode'],
    'supervisor': ['supervisor', 'sup-'],
    'module': ['module', 'linecard', 'daughtercard', 'rtxmn', 'sfcn'],
}

# Description keywords (case-insensitive)
DESC_KEYWORDS = {
    'fan': ['fan', 'cooling'],
    'psu': ['power supply', 'power', 'psu'],
    'transceiver': ['transceiver', 'optic', 'sfp', 'gbic'],
    'supervisor': ['supervisor', 'management engine'],
    'chassis': ['chassis', 'enclosure'],
}


def connect_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Connect to the SQLite database"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def analyze_unknown_components(conn: sqlite3.Connection) -> None:
    """Analyze components with unknown type to understand patterns"""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, description, serial, position, type
        FROM components
        WHERE type = 'unknown' OR type IS NULL
        ORDER BY name
    """)

    unknowns = cursor.fetchall()
    print(f"\n{'=' * 80}")
    print(f"Found {len(unknowns)} components with unknown type")
    print(f"{'=' * 80}\n")

    # Analyze name patterns
    name_patterns = Counter()
    for row in unknowns:
        name = row['name'] or ''
        # Extract pattern (e.g., "Fan 1" -> "Fan N")
        pattern = re.sub(r'\d+', 'N', name)
        name_patterns[pattern] += 1

    print("Top 20 Name Patterns:")
    print("-" * 80)
    for pattern, count in name_patterns.most_common(20):
        print(f"  {pattern:50} | Count: {count}")

    # Show sample records
    print(f"\n{'=' * 80}")
    print("Sample Unknown Components:")
    print(f"{'=' * 80}")
    for i, row in enumerate(unknowns[:30]):
        print(f"\nID: {row['id']}")
        print(f"  Name: {row['name']}")
        print(f"  Description: {row['description']}")
        print(f"  Position: {row['position']}")
        print(f"  Serial: {row['serial']}")


def is_junk_component(name: str, description: str) -> bool:
    """
    Detect junk/invalid components from parsing errors
    """
    if not name:
        return False

    name_lower = (name or '').lower()
    desc_lower = (description or '').lower()

    # Known junk patterns
    junk_patterns = [
        r'^%$',  # Just a % character
        r'invalid input detected',
        r'^/$',  # Just a / character
        r'^switched$',  # "Switched" alone
        r'^switchedbootstrap$',
        r'^cpu$',  # Just "CPU" - likely parsing error
        r'^daylight$',
        r'^ip$',
        r'^mac$',
        r'^pkts$',
        r'^rom$',
        r'^software$',
        r'^status$',
        r'^system$',
        r'^up$',
        r'^your$',
        r'^access$',
        r'_\s+_\s+\\',  # ASCII art fragments
        r'^terminal\s+(length|width)',  # CLI commands
        r'^set$',  # CLI command
        r'^no\s+page',  # CLI command
        r'^off$',  # Command output
        r'^0$',  # Just "0"
        r'^information$',  # Just "information"
        r'#$',  # Ends with # (CLI prompt)
    ]

    for pattern in junk_patterns:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return True

    # Check for "Invalid input detected" in description
    if 'invalid input' in desc_lower:
        return True

    # Check for banner text fragments
    if 'authorized' in desc_lower and 'limited' in desc_lower:
        return True

    return False


def classify_component(name: str, description: str, position: str) -> Optional[str]:
    """
    Classify a component based on name, description, and position
    Returns the detected type or None if unable to classify
    """
    name_lower = (name or '').lower()
    desc_lower = (description or '').lower()
    pos_lower = (position or '').lower()
    combined = f"{name_lower} {desc_lower} {pos_lower}"

    # Check for junk/invalid entries first
    if is_junk_component(name, description):
        return 'junk'

    # Pattern-based matching
    for comp_type, patterns in TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return comp_type

    # Name keyword matching
    for comp_type, keywords in NAME_KEYWORDS.items():
        for keyword in keywords:
            if keyword in name_lower:
                return comp_type

    # Description keyword matching
    for comp_type, keywords in DESC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in desc_lower:
                return comp_type

    return None


def fix_component_types(conn: sqlite3.Connection, dry_run: bool = True,
                        delete_junk: bool = False) -> Dict[str, int]:
    """
    Fix component types based on classification rules

    Args:
        conn: Database connection
        dry_run: If True, only show what would be changed without making changes
        delete_junk: If True, delete components identified as junk

    Returns:
        Dictionary with statistics about changes
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, description, position, type
        FROM components
        WHERE type = 'unknown' OR type IS NULL
    """)

    components = cursor.fetchall()

    stats = {
        'total_unknown': len(components),
        'classified': 0,
        'still_unknown': 0,
        'junk_found': 0,
        'by_type': Counter(),
    }

    changes = []
    junk_ids = []

    for row in components:
        new_type = classify_component(
            row['name'],
            row['description'],
            row['position']
        )

        if new_type == 'junk':
            stats['junk_found'] += 1
            junk_ids.append({
                'id': row['id'],
                'name': row['name'],
                'description': row['description'],
            })
        elif new_type:
            stats['classified'] += 1
            stats['by_type'][new_type] += 1
            changes.append({
                'id': row['id'],
                'name': row['name'],
                'old_type': row['type'],
                'new_type': new_type,
            })
        else:
            stats['still_unknown'] += 1

    # Display results
    print(f"\n{'=' * 80}")
    print("Classification Results:")
    print(f"{'=' * 80}")
    print(f"Total unknown components: {stats['total_unknown']}")
    print(f"Successfully classified: {stats['classified']}")
    print(f"Junk components found: {stats['junk_found']}")
    print(f"Still unknown: {stats['still_unknown']}")
    print(f"\nClassified by type:")
    for comp_type, count in stats['by_type'].most_common():
        print(f"  {comp_type:15} : {count:5}")

    # Show junk components
    if junk_ids:
        print(f"\n{'=' * 80}")
        print(f"Junk Components Found ({len(junk_ids)}):")
        print(f"{'=' * 80}")
        for junk in junk_ids[:20]:
            print(f"\nID {junk['id']:4} | {junk['name']}")
            if junk['description']:
                print(f"  Desc: {junk['description'][:60]}")
        if len(junk_ids) > 20:
            print(f"\n... and {len(junk_ids) - 20} more")

    # Show sample changes
    if changes:
        print(f"\n{'=' * 80}")
        print("Sample Changes (first 30):")
        print(f"{'=' * 80}")
        for change in changes[:30]:
            print(f"\nID {change['id']:4} | {change['name']}")
            print(f"  {change['old_type'] or 'NULL':10} -> {change['new_type']}")

    # Apply changes if not dry run
    if not dry_run:
        print(f"\n{'=' * 80}")
        print("Applying changes to database...")
        print(f"{'=' * 80}")

        if changes:
            for change in changes:
                cursor.execute("""
                    UPDATE components
                    SET type = ?
                    WHERE id = ?
                """, (change['new_type'], change['id']))
            print(f"✓ Updated {len(changes)} components")

        if delete_junk and junk_ids:
            junk_id_list = [j['id'] for j in junk_ids]
            placeholders = ','.join('?' * len(junk_id_list))
            cursor.execute(f"""
                DELETE FROM components
                WHERE id IN ({placeholders})
            """, junk_id_list)
            print(f"✓ Deleted {len(junk_ids)} junk components")

        conn.commit()
        print(f"✓ Changes committed")
    elif dry_run:
        print(f"\n{'=' * 80}")
        print("DRY RUN - No changes made to database")
        print("Run with --apply to apply these changes")
        if junk_ids:
            print("Run with --delete-junk to also delete junk components")
        print(f"{'=' * 80}")

    return stats


def main():
    """Main execution function"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Analyze and fix component types in assets.db'
    )
    parser.add_argument(
        '--analyze',
        action='store_true',
        help='Analyze unknown components without making changes'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply the fixes to the database'
    )
    parser.add_argument(
        '--delete-junk',
        action='store_true',
        help='Delete junk/invalid components (use with --apply)'
    )
    parser.add_argument(
        '--db',
        default=DB_PATH,
        help=f'Path to database file (default: {DB_PATH})'
    )

    args = parser.parse_args()

    conn = connect_db(args.db)

    try:
        if args.analyze:
            # Just analyze and show patterns
            analyze_unknown_components(conn)
        else:
            # Run the fixup (dry run by default)
            dry_run = not args.apply
            fix_component_types(conn, dry_run=dry_run, delete_junk=args.delete_junk)

    finally:
        conn.close()


if __name__ == '__main__':
    main()