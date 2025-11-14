#!/usr/bin/env python3
"""
LLDP Detail Parsing Validator

Validates that collected LLDP detail data from assets.db can be successfully
parsed using tfsm_fire library and reports statistics on parsing success.
"""

import os
import sys
import json
import argparse
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

# Import your tfsm_fire library
try:
    from tfsm_fire import TextFSMAutoEngine
except ImportError:
    print("Error: tfsm_fire module not found. Ensure it's in your Python path.")
    sys.exit(1)


class LLDPParsingValidator:
    """Validates LLDP detail parsing from assets.db"""

    def __init__(self, assets_db_path: str, tfsm_db_path: str, verbose: bool = False, debug: bool = False):
        self.assets_db_path = assets_db_path
        self.tfsm_db_path = tfsm_db_path
        self.verbose = verbose
        self.debug = debug

        # Connect to assets database
        self.assets_conn = sqlite3.connect(assets_db_path)
        self.assets_conn.row_factory = sqlite3.Row

        # Initialize TFSM engine
        self.engine = TextFSMAutoEngine(tfsm_db_path, verbose=debug)

        # Statistics
        self.stats = {
            'total_snapshots': 0,
            'parsed_success': 0,
            'parsed_failed': 0,
            'total_neighbors': 0,
            'parse_errors': [],
            'snapshot_results': []
        }

    def _log(self, message: str, level: str = 'info'):
        """Log message based on verbosity settings"""
        if level == 'debug' and not self.debug:
            return
        if level == 'info' and not self.verbose:
            return

        prefix = {
            'debug': '[DEBUG]',
            'info': '[INFO]',
            'error': '[ERROR]',
            'success': '[SUCCESS]'
        }.get(level, '')

        print(f"{prefix} {message}", flush=True)

    def get_lldp_snapshots(self, vendor_filter: str = None) -> List[sqlite3.Row]:
        """
        Retrieve LLDP detail snapshots from database

        Args:
            vendor_filter: Optional vendor name filter (e.g., 'juniper', 'cisco', 'arista')

        Returns:
            List of snapshot rows with device information
        """
        query = """
            SELECT 
                cs.id as snapshot_id,
                cs.device_id,
                cs.capture_type,
                cs.captured_at,
                cs.content,
                cs.content_hash,
                d.name as device_name,
                d.normalized_name,
                v.name as vendor_name,
                v.short_name as vendor_short
            FROM capture_snapshots cs
            JOIN devices d ON cs.device_id = d.id
            LEFT JOIN vendors v ON d.vendor_id = v.id
            WHERE cs.capture_type = 'lldp-detail'
        """

        params = []
        if vendor_filter:
            query += " AND (LOWER(v.name) LIKE ? OR LOWER(v.short_name) LIKE ?)"
            vendor_pattern = f"%{vendor_filter.lower()}%"
            params.extend([vendor_pattern, vendor_pattern])

        query += " ORDER BY d.name"

        cursor = self.assets_conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def validate_snapshot(self, snapshot: sqlite3.Row) -> Dict:
        """
        Validate parsing for a single LLDP detail snapshot

        Returns:
            {
                'snapshot_id': int,
                'device_id': int,
                'device_name': str,
                'vendor': str,
                'success': bool,
                'template': str,
                'score': float,
                'neighbor_count': int,
                'error': str (if failed)
            }
        """
        device_name = snapshot['device_name']
        vendor = snapshot['vendor_name'] or 'Unknown'

        self._log(f"Processing {device_name} ({vendor})...", 'info')

        result = {
            'snapshot_id': snapshot['snapshot_id'],
            'device_id': snapshot['device_id'],
            'device_name': device_name,
            'vendor': vendor,
            'success': False,
            'neighbor_count': 0
        }

        try:
            content = snapshot['content']

            if not content or not content.strip():
                result['error'] = 'Empty content'
                self._log(f"  {device_name}: Empty content", 'error')
                return result

            # Try parsing with TFSM - use 'lldp' filter for all vendors
            filter_string = 'lldp'

            self._log(f"  Attempting to parse with filter: '{filter_string}'", 'debug')

            # Handle different return formats from tfsm_fire
            parse_result = self.engine.find_best_template(content, filter_string)

            if len(parse_result) == 4:
                template, parsed_data, score, template_content = parse_result
            elif len(parse_result) == 3:
                template, parsed_data, score = parse_result
                template_content = None
            else:
                result['error'] = f'Unexpected return format from tfsm_fire: {len(parse_result)} values'
                self._log(f"  {device_name}: {result['error']}", 'error')
                return result

            # Check if template was found
            if not template or not parsed_data:
                result['error'] = f'No template match (score: {score})'
                self._log(f"  {device_name}: No template found", 'error')
                return result

            # Success!
            result['success'] = True
            result['template'] = template
            result['score'] = score
            result['neighbor_count'] = len(parsed_data)

            self._log(f"  ✓ {device_name}: Template '{template}' (score: {score:.2f}, neighbors: {len(parsed_data)})",
                      'success')

            # Debug: Show sample parsed record
            if self.debug and parsed_data:
                sample = parsed_data[0]
                self._log(f"    Sample fields: {list(sample.keys())}", 'debug')
                self._log(f"    Sample data: {sample}", 'debug')

        except Exception as e:
            result['error'] = str(e)
            self._log(f"  {device_name}: Exception - {e}", 'error')
            if self.debug:
                import traceback
                traceback.print_exc()

        return result

    def validate_all(self, vendor_filter: str = None) -> Dict:
        """
        Validate parsing for all LLDP snapshots in database

        Args:
            vendor_filter: Optional vendor name to filter (e.g., 'juniper')

        Returns summary statistics
        """
        # Get snapshots from database
        snapshots = self.get_lldp_snapshots(vendor_filter)

        if not snapshots:
            print(f"No LLDP detail snapshots found in {self.assets_db_path}")
            if vendor_filter:
                print(f"  (vendor filter: {vendor_filter})")
            return self.stats

        self.stats['total_snapshots'] = len(snapshots)

        print(f"\n{'=' * 70}")
        print(f"LLDP Detail Parsing Validation (Database)")
        print(f"{'=' * 70}")
        print(f"Assets Database: {self.assets_db_path}")
        print(f"TFSM Database: {self.tfsm_db_path}")
        if vendor_filter:
            print(f"Vendor Filter: {vendor_filter}")
        print(f"Total snapshots: {len(snapshots)}")
        print(f"{'=' * 70}\n")

        # Process each snapshot
        for snapshot in snapshots:
            result = self.validate_snapshot(snapshot)
            self.stats['snapshot_results'].append(result)

            if result['success']:
                self.stats['parsed_success'] += 1
                self.stats['total_neighbors'] += result.get('neighbor_count', 0)
            else:
                self.stats['parsed_failed'] += 1
                self.stats['parse_errors'].append({
                    'device': result['device_name'],
                    'vendor': result['vendor'],
                    'error': result.get('error', 'Unknown error')
                })

        return self.stats

    def print_summary(self):
        """Print validation summary"""
        print(f"\n{'=' * 70}")
        print("VALIDATION SUMMARY")
        print(f"{'=' * 70}")
        print(f"Total snapshots processed: {self.stats['total_snapshots']}")

        if self.stats['total_snapshots'] > 0:
            success_pct = self.stats['parsed_success'] / self.stats['total_snapshots'] * 100
            failed_pct = self.stats['parsed_failed'] / self.stats['total_snapshots'] * 100
            print(f"Successfully parsed: {self.stats['parsed_success']} ({success_pct:.1f}%)")
            print(f"Failed to parse: {self.stats['parsed_failed']} ({failed_pct:.1f}%)")

        print(f"Total LLDP neighbors: {self.stats['total_neighbors']}")

        if self.stats['parsed_success'] > 0:
            avg_neighbors = self.stats['total_neighbors'] / self.stats['parsed_success']
            print(f"Average neighbors per device: {avg_neighbors:.1f}")

        # Show template distribution
        template_counts = {}
        vendor_counts = {}
        for result in self.stats['snapshot_results']:
            if result['success']:
                template = result.get('template', 'Unknown')
                template_counts[template] = template_counts.get(template, 0) + 1

                vendor = result.get('vendor', 'Unknown')
                vendor_counts[vendor] = vendor_counts.get(vendor, 0) + 1

        if vendor_counts:
            print(f"\nVendor Distribution:")
            for vendor, count in sorted(vendor_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {vendor}: {count} devices")

        if template_counts:
            print(f"\nTemplate Distribution:")
            for template, count in sorted(template_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {template}: {count} devices")

        # Show failures
        if self.stats['parse_errors']:
            print(f"\nFailed Devices ({len(self.stats['parse_errors'])}):")
            for error in self.stats['parse_errors'][:10]:  # Show first 10
                print(f"  - {error['device']} ({error['vendor']}): {error['error']}")
            if len(self.stats['parse_errors']) > 10:
                print(f"  ... and {len(self.stats['parse_errors']) - 10} more")

        print(f"{'=' * 70}\n")

    def save_results(self, output_file: str):
        """Save detailed results to JSON file"""
        output = {
            'timestamp': datetime.now().isoformat(),
            'assets_db_path': self.assets_db_path,
            'tfsm_db_path': self.tfsm_db_path,
            'summary': {
                'total_snapshots': self.stats['total_snapshots'],
                'parsed_success': self.stats['parsed_success'],
                'parsed_failed': self.stats['parsed_failed'],
                'total_neighbors': self.stats['total_neighbors']
            },
            'results': self.stats['snapshot_results']
        }

        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"Detailed results saved to: {output_file}")

    def close(self):
        """Clean up database connections"""
        if self.assets_conn:
            self.assets_conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Validate TextFSM parsing of LLDP detail data from assets.db',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all LLDP snapshots
  python validate_lldp_parsing.py assets.db

  # Validate only Juniper devices
  python validate_lldp_parsing.py assets.db --vendor juniper

  # With verbose output
  python validate_lldp_parsing.py assets.db -v

  # With debug output (shows tfsm_fire details)
  python validate_lldp_parsing.py assets.db -d

  # Save results to JSON
  python validate_lldp_parsing.py assets.db -o validation_results.json

  # Custom TFSM database path
  python validate_lldp_parsing.py assets.db --tfsm-db /path/to/tfsm_templates.db
        """
    )

    parser.add_argument('assets_db',
                        help='Path to assets.db containing capture_snapshots')

    parser.add_argument('--tfsm-db',
                        default='tfsm_templates.db',
                        help='Path to TFSM templates database (default: tfsm_templates.db)')

    parser.add_argument('--vendor',
                        help='Filter by vendor name (e.g., juniper, cisco, arista)')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='Enable verbose output')

    parser.add_argument('-d', '--debug',
                        action='store_true',
                        help='Enable debug output (includes tfsm_fire debug info)')

    parser.add_argument('-o', '--output',
                        help='Save detailed results to JSON file')

    args = parser.parse_args()

    # Validate inputs
    assets_db = Path(args.assets_db)
    if not assets_db.exists():
        print(f"Error: Assets database not found: {assets_db}")
        sys.exit(1)

    if not assets_db.is_file():
        print(f"Error: Not a database file: {assets_db}")
        sys.exit(1)

    tfsm_db = Path(args.tfsm_db)
    if not tfsm_db.exists():
        print(f"Error: TFSM database not found: {tfsm_db}")
        print(f"Please provide correct path with --tfsm-db")
        sys.exit(1)

    # Create validator
    validator = LLDPParsingValidator(
        assets_db_path=str(assets_db),
        tfsm_db_path=str(tfsm_db),
        verbose=args.verbose,
        debug=args.debug
    )

    try:
        # Run validation
        validator.validate_all(vendor_filter=args.vendor)

        # Print summary
        validator.print_summary()

        # Save results if requested
        if args.output:
            validator.save_results(args.output)

    finally:
        # Clean up
        validator.close()


if __name__ == '__main__':
    main()