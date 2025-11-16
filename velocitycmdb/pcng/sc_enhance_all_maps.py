#!/usr/bin/env python3
"""
POC: Batch Map Enhancement Wrapper
Scans ./maps folder structure and enhances all JSON topology files with icons and improved SVG.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed


def find_topology_files(base_dir: Path) -> List[Path]:
    """
    Recursively find all .json files in the maps directory structure.

    Args:
        base_dir: Base directory to search (typically ./maps)

    Returns:
        List of paths to JSON topology files
    """
    json_files = []

    if not base_dir.exists():
        print(f"Warning: Directory not found: {base_dir}")
        return json_files

    # Find all JSON files recursively
    for json_file in base_dir.rglob("*.json"):
        json_files.append(json_file)

    return sorted(json_files)


def enhance_single_map(args: Tuple[Path, dict]) -> Tuple[str, bool, str]:
    """
    Enhance a single topology map.

    Args:
        args: Tuple of (json_path, config_dict)

    Returns:
        Tuple of (site_name, success, message)
    """
    json_path, config = args
    site_name = json_path.stem

    try:
        # Build enhancement command
        enhance_script = Path('sc_enhance_map3.py')
        if not enhance_script.exists():
            return (site_name, False, "Enhancement script not found")

        cmd = [sys.executable, str(enhance_script), str(json_path)]

        # Add enhancement options
        if config.get('icons_dir'):
            cmd.extend(['--icons-dir', config['icons_dir']])

        if config.get('layout'):
            cmd.extend(['--layout', config['layout']])

        if config.get('svg_layout'):
            cmd.extend(['--svg-layout', config['svg_layout']])

        if config.get('svg_no_endpoints'):
            cmd.append('--svg-no-endpoints')

        if config.get('no_endpoints'):
            cmd.append('--no-endpoints')

        if config.get('light_mode'):
            cmd.append('--light-mode')

        if config.get('skip_svg'):
            cmd.append('--skip-svg')

        # Run enhancement
        print(f"[{site_name}] Enhancing maps...")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.get('timeout', 120)
        )

        if result.returncode == 0:
            # Count created files
            output_dir = json_path.parent
            expected_files = [
                output_dir / f"{site_name}.graphml",
                output_dir / f"{site_name}.drawio",
                output_dir / f"{site_name}.svg"
            ]
            created = sum(1 for f in expected_files if f.exists())

            return (site_name, True, f"Created {created}/3 enhanced files")
        else:
            error = result.stderr.strip() or result.stdout.strip()
            # Extract just the first line of error for brevity
            error_line = error.split('\n')[0] if error else "Unknown error"
            return (site_name, False, f"Failed: {error_line[:80]}")

    except subprocess.TimeoutExpired:
        return (site_name, False, "Timeout")
    except Exception as e:
        return (site_name, False, f"Error: {str(e)[:80]}")


def main():
    parser = argparse.ArgumentParser(
        description='Batch enhance all network topology maps in ./maps directory',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Basic usage - enhance all maps with default settings
  %(prog)s

  # Clean SVGs for web, full detail in GraphML/DrawIO
  %(prog)s --svg-no-endpoints

  # Custom settings with parallel processing
  %(prog)s --svg-no-endpoints --layout tree --svg-layout LR --workers 4

  # Exclude endpoints from everything
  %(prog)s --no-endpoints --svg-no-endpoints

  # Light mode SVGs
  %(prog)s --svg-no-endpoints --light-mode

  # Skip SVG generation for faster processing
  %(prog)s --skip-svg --workers 8
        '''
    )

    parser.add_argument(
        '--maps-dir',
        type=Path,
        default=Path('./maps'),
        help='Base directory containing site subdirectories with JSON files (default: ./maps)'
    )

    parser.add_argument(
        '--icons-dir',
        type=str,
        help='Custom icon library directory (default: auto-detect)'
    )

    parser.add_argument(
        '--layout',
        choices=['grid', 'tree', 'balloon'],
        default='tree',
        help='Layout algorithm for GraphML/DrawIO (default: tree)'
    )

    parser.add_argument(
        '--svg-layout',
        choices=['TD', 'LR'],
        default='TD',
        help='Mermaid layout for SVG: TD (top-down) or LR (left-right) (default: TD)'
    )

    parser.add_argument(
        '--no-endpoints',
        action='store_true',
        help='Exclude endpoint devices from GraphML/DrawIO'
    )

    parser.add_argument(
        '--svg-no-endpoints',
        action='store_true',
        help='Exclude endpoint devices from SVG (cleaner web view)'
    )

    parser.add_argument(
        '--light-mode',
        action='store_true',
        help='Use light theme for SVG (default: dark mode)'
    )

    parser.add_argument(
        '--skip-svg',
        action='store_true',
        help='Skip SVG generation for faster processing'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Number of concurrent workers (default: 1)'
    )

    parser.add_argument(
        '--timeout',
        type=int,
        default=120,
        help='Timeout per map in seconds (default: 120)'
    )

    parser.add_argument(
        '--filter',
        type=str,
        help='Filter sites by name (case-insensitive substring match)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be enhanced without executing'
    )

    args = parser.parse_args()

    # Find all JSON files
    print(f"Scanning {args.maps_dir} for topology files...")
    json_files = find_topology_files(args.maps_dir)

    if not json_files:
        print(f"No JSON files found in {args.maps_dir}")
        return 1

    print(f"Found {len(json_files)} topology file(s)")

    # Apply filter if specified
    if args.filter:
        filter_term = args.filter.lower()
        json_files = [f for f in json_files if filter_term in f.stem.lower()]
        print(f"After filtering: {len(json_files)} file(s) match '{args.filter}'")

        if not json_files:
            print("No files match the filter criteria")
            return 1

    # Show what will be processed
    print("\nFiles to enhance:")
    for json_file in json_files:
        site_name = json_file.stem
        site_path = json_file.parent.name
        print(f"  {site_path}/{site_name}")

    if args.dry_run:
        print("\nDry run - no files will be modified")
        return 0

    # Prepare config
    config = {
        'icons_dir': args.icons_dir,
        'layout': args.layout,
        'svg_layout': args.svg_layout,
        'no_endpoints': args.no_endpoints,
        'svg_no_endpoints': args.svg_no_endpoints,
        'light_mode': args.light_mode,
        'skip_svg': args.skip_svg,
        'timeout': args.timeout,
    }

    print(f"\nConfiguration:")
    print(f"  Layout: {args.layout}")
    print(f"  SVG Layout: {args.svg_layout}")
    print(f"  GraphML/DrawIO Endpoints: {'excluded' if args.no_endpoints else 'included'}")
    print(f"  SVG Endpoints: {'excluded' if args.svg_no_endpoints else 'included'}")
    print(f"  SVG Theme: {'light' if args.light_mode else 'dark'}")
    print(f"  Workers: {args.workers}")

    # Process maps
    print(f"\n{'=' * 60}")
    print("Starting batch enhancement...")
    print(f"{'=' * 60}\n")

    worker_args = [(json_file, config) for json_file in json_files]
    results = []

    if args.workers == 1:
        # Sequential processing
        for task in worker_args:
            result = enhance_single_map(task)
            results.append(result)
    else:
        # Parallel processing
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_site = {
                executor.submit(enhance_single_map, task): task[0].stem
                for task in worker_args
            }

            for future in as_completed(future_to_site):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    site_name = future_to_site[future]
                    results.append((site_name, False, f"Exception: {str(e)[:80]}"))

    # Summarize results
    print(f"\n{'=' * 60}")
    print("ENHANCEMENT SUMMARY")
    print(f"{'=' * 60}\n")

    success_count = sum(1 for _, success, _ in results if success)
    total = len(results)

    print(f"Successfully enhanced: {success_count}/{total} sites\n")

    if success_count < total:
        print("Failed sites:")
        for site_name, success, message in results:
            if not success:
                print(f"  ✗ {site_name}: {message}")
        print()

    if success_count > 0:
        print("Successful sites:")
        for site_name, success, message in results:
            if success:
                print(f"  ✓ {site_name}: {message}")
        print()

    return 0 if success_count == total else 1


if __name__ == '__main__':
    sys.exit(main())