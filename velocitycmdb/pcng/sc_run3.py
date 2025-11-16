#!/usr/bin/env python3
"""
Concurrent wrapper for secure_cartography network mapping tool.
Processes sessions.yaml to map multiple sites in parallel.
"""

import yaml
import subprocess
import argparse
import logging
import sys
import os
import threading
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple
import re
from enum import Enum

# Device priority patterns (in order of preference)
DEVICE_PRIORITY = [
    r'core',
    r'spine',
    r'cr',
    r'-sw-',
    r'-swl'
]


class Color(Enum):
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'


def colorize(text: str, color: Color) -> str:
    """Add color to text if terminal supports it"""
    if sys.stdout.isatty():
        return f"{color.value}{text}{Color.RESET.value}"
    return text


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_site_name(folder_name: str) -> str:
    """
    Extract site name from folder name.
    If folder name is long, use first word; otherwise use full name.

    Args:
        folder_name: Full folder name from sessions.yaml

    Returns:
        Cleaned site name suitable for map naming
    """
    # Remove special characters and extra whitespace
    cleaned = folder_name.strip()

    # If folder has pipe separators, take first part
    if '|' in cleaned:
        cleaned = cleaned.split('|')[0].strip()

    # Split on whitespace and check if first word looks like a site code
    words = cleaned.split()
    if words:
        first_word = words[0]
        # If first word is short alphanumeric code (like USWC, USXGA, VNHC), use it
        if len(first_word) <= 10 and re.match(r'^[A-Za-z0-9-]+$', first_word):
            return first_word

    # For longer names or non-standard format, use first word or full name if short
    if len(cleaned) > 30 and words:
        return words[0]

    return cleaned.replace(' ', '_')[:30]  # Limit length


def select_device(sessions: List[Dict], folder_name: str) -> Optional[Dict]:
    """
    Select best device from a site based on priority patterns.

    Args:
        sessions: List of device sessions
        folder_name: Name of the folder/site

    Returns:
        Selected device dict or None if no suitable device found
    """
    # Filter out devices without valid host
    valid_devices = [s for s in sessions if s.get('host') and s['host'].strip()]

    if not valid_devices:
        logger.warning(f"No devices with valid host found in {folder_name}")
        return None

    # Try each priority pattern in order
    for pattern in DEVICE_PRIORITY:
        for device in valid_devices:
            display_name = device.get('display_name', '').lower()
            if re.search(pattern, display_name):
                return device

    # If no priority match, return first valid device
    logger.info(f"No priority device found in {folder_name}, using first available")
    return valid_devices[0]


def load_sessions(sessions_file: Path) -> List[Dict]:
    """
    Load and parse sessions.yaml file.

    Args:
        sessions_file: Path to sessions.yaml

    Returns:
        List of parsed session folders
    """
    try:
        with open(sessions_file, 'r') as f:
            data = yaml.safe_load(f)
        return data if data else []
    except Exception as e:
        logger.error(f"Failed to load sessions file: {e}")
        raise


def build_exclude_string(config: Dict, current_site: str, all_sites: List[str]) -> str:
    """
    Build exclude string by combining user-specified exclusions with other site names.

    Args:
        config: Configuration dictionary
        current_site: The site currently being mapped
        all_sites: List of all site names

    Returns:
        Comma-separated exclude string
    """
    excludes = []

    # Add user-specified exclusions
    if config.get('exclude_string'):
        user_excludes = [e.strip() for e in config['exclude_string'].split(',') if e.strip()]
        excludes.extend(user_excludes)

    # Add all other site names to prevent cross-site discovery
    for site in all_sites:
        if site != current_site:
            excludes.append(site)

    return ','.join(excludes) if excludes else None
    """Stream process output in real-time with site prefix"""
    prefix = colorize(f"[{site_name}]", Color.CYAN)

    try:
        for line in iter(pipe.readline, ''):
            if line:
                if is_stderr:
                    print(f"{prefix} {colorize(line.rstrip(), Color.YELLOW)}", flush=True)
                else:
                    print(f"{prefix} {line.rstrip()}", flush=True)
    finally:
        pipe.close()


def run_mapper(args: Tuple[Dict, Dict, Path, List[str]]) -> Tuple[str, bool, str]:
    """
    Run the sc mapping tool for a single site with real-time output streaming.

    Args:
        args: Tuple of (device, config, sc_path, all_site_names)

    Returns:
        Tuple of (site_name, success, message)
    """
    device, config, sc_path, all_site_names = args
    site_name = device['site_name']

    try:
        # Create site-specific output directory
        base_output_dir = Path(config.get('output_dir', './maps'))
        site_output_dir = base_output_dir / site_name.lower()
        site_output_dir.mkdir(parents=True, exist_ok=True)

        # Determine which sc command to use
        sc_command = config.get('sc_command')
        if not sc_command:
            # Try venv executable first, then fall back to sc.py
            venv_exe = Path('.venv/Scripts/sc.exe')
            if venv_exe.exists():
                sc_command = str(venv_exe)
            elif sc_path.exists():
                sc_command = f'python {sc_path}' if config['use_python'] else str(sc_path)
            else:
                return (site_name, False, "Neither venv/Scripts/sc.exe nor sc.py found")

        cmd = [
            sc_command if ' ' not in sc_command else sc_command.split()[0],
            '--seed-ip', device['host'],
            '--map-name', site_name.lower(),
            '--output-dir', str(site_output_dir),
        ]

        # If sc_command contains 'python', add the script path
        if 'python' in sc_command.lower():
            cmd.insert(1, str(sc_path))

        # Add optional parameters
        if config.get('username'):
            cmd.extend(['--username', config['username']])
        if config.get('password'):
            cmd.extend(['--password', config['password']])
        if config.get('alt_username'):
            cmd.extend(['--alternate-username', config['alt_username']])
        if config.get('alt_password'):
            cmd.extend(['--alternate-password', config['alt_password']])
        if config.get('domain_name'):
            cmd.extend(['--domain-name', config['domain_name']])

        # Build dynamic exclude string with other site names
        exclude_string = build_exclude_string(config, site_name, all_site_names)
        if exclude_string:
            cmd.extend(['--exclude-string', exclude_string])
            logger.debug(f"{site_name}: Excluding {len(exclude_string.split(','))} terms")

        if config.get('timeout'):
            cmd.extend(['--timeout', str(config['timeout'])])
        if config.get('max_devices'):
            cmd.extend(['--max-devices', str(config['max_devices'])])
        if config.get('layout_algo'):
            cmd.extend(['--layout-algo', config['layout_algo']])
        if config.get('save_debug_info'):
            cmd.append('--save-debug-info')

        print(colorize(f"\n{'=' * 60}", Color.BLUE))
        print(colorize(f"Starting: {site_name}", Color.BOLD) +
              f" | Device: {device['display_name']} ({device['host']})")
        print(colorize(f"Output: {site_output_dir}", Color.BLUE))
        print(colorize(f"{'=' * 60}\n", Color.BLUE))

        # Set environment to disable Python buffering
        env = dict(os.environ)
        env['PYTHONUNBUFFERED'] = '1'

        # If using Python, add -u flag for unbuffered output
        if 'python' in cmd[0].lower():
            cmd.insert(1, '-u')

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            shell=False,
            env=env
        )

        # Stream output in real-time using threads
        stdout_thread = threading.Thread(
            target=stream_output,
            args=(process.stdout, site_name, False)
        )
        stderr_thread = threading.Thread(
            target=stream_output,
            args=(process.stderr, site_name, True)
        )

        stdout_thread.start()
        stderr_thread.start()

        # Wait for process to complete
        return_code = process.wait(timeout=config.get('process_timeout', 600))

        # Wait for output threads to finish
        stdout_thread.join()
        stderr_thread.join()

        if return_code == 0:
            # Verify expected files were created
            expected_files = [
                site_output_dir / f"{site_name.lower()}.json",
                site_output_dir / f"{site_name.lower()}.svg",
                site_output_dir / f"{site_name.lower()}.graphml",
                site_output_dir / f"{site_name.lower()}.drawio"
            ]
            created_files = [f.name for f in expected_files if f.exists()]

            success_msg = f"Success - {len(created_files)}/4 files created"
            print(colorize(f"\n✓ {site_name}: {success_msg}\n", Color.GREEN))
            return (site_name, True, success_msg)
        else:
            error_msg = f"Process exited with code {return_code}"
            print(colorize(f"\n✗ {site_name}: {error_msg}\n", Color.RED))
            return (site_name, False, error_msg)

    except subprocess.TimeoutExpired:
        error_msg = "Process timeout"
        print(colorize(f"\n✗ {site_name}: {error_msg}\n", Color.RED))
        return (site_name, False, error_msg)
    except Exception as e:
        error_msg = str(e)
        print(colorize(f"\n✗ {site_name}: {error_msg}\n", Color.RED))
        return (site_name, False, error_msg)


def main():
    parser = argparse.ArgumentParser(
        description='Concurrent wrapper for secure_cartography network mapping'
    )
    parser.add_argument(
        '--sessions-file',
        type=Path,
        default=Path('sessions.yaml'),
        help='Path to sessions.yaml file'
    )
    parser.add_argument(
        '--sc-path',
        type=Path,
        default=Path('sc.py'),
        help='Path to sc.py script (fallback if venv executable not found)'
    )
    parser.add_argument(
        '--sc-command',
        type=str,
        help='Override sc command (default: auto-detect .venv/Scripts/sc.exe or sc.py)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Number of concurrent workers (default: 1)'
    )
    parser.add_argument(
        '--username',
        help='Primary username for device authentication'
    )
    parser.add_argument(
        '--password',
        help='Primary password for device authentication'
    )
    parser.add_argument(
        '--alternate-username',
        dest='alt_username',
        help='Alternate username for fallback authentication'
    )
    parser.add_argument(
        '--alternate-password',
        dest='alt_password',
        help='Alternate password for fallback authentication'
    )
    parser.add_argument(
        '--domain-name',
        dest='domain_name',
        help='Domain name for device resolution'
    )
    parser.add_argument(
        '--exclude-string',
        dest='exclude_string',
        help='Comma-separated strings to exclude from discovery'
    )
    parser.add_argument(
        '--output-dir',
        dest='output_dir',
        default='./maps',
        help='Base output directory for discovery results (default: ./maps). Each site will get its own subdirectory.'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='Timeout in seconds for device connections'
    )
    parser.add_argument(
        '--max-devices',
        type=int,
        dest='max_devices',
        help='Maximum number of devices to discover per site'
    )
    parser.add_argument(
        '--layout-algo',
        dest='layout_algo',
        choices=['kk', 'spring', 'circular', 'random'],
        default='kk',
        help='Layout algorithm for network visualization'
    )
    parser.add_argument(
        '--save-debug-info',
        dest='save_debug_info',
        action='store_true',
        help='Save debug information during discovery'
    )
    parser.add_argument(
        '--process-timeout',
        type=int,
        dest='process_timeout',
        default=600,
        help='Timeout for each mapping process in seconds (default: 600)'
    )
    parser.add_argument(
        '--use-python',
        action='store_true',
        help='Use "python" command instead of direct script execution'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be mapped without executing'
    )
    parser.add_argument(
        '--filter',
        type=str,
        help='Filter sites by folder name (case-insensitive substring match). Use comma to separate multiple filters.'
    )

    args = parser.parse_args()

    # Validate files
    if not args.sessions_file.exists():
        logger.error(colorize(f"Sessions file not found: {args.sessions_file}", Color.RED))
        return 1

    # Check for sc executable or script
    venv_exe = Path('.venv/Scripts/sc.exe')
    if not args.sc_command:
        if venv_exe.exists():
            logger.info(colorize(f"Found venv executable: {venv_exe}", Color.GREEN))
        elif args.sc_path.exists():
            logger.info(colorize(f"Using Python script: {args.sc_path}", Color.GREEN))
        else:
            logger.error(colorize(f"Neither .venv/Scripts/sc.exe nor {args.sc_path} found", Color.RED))
            return 1

    # Load sessions
    logger.info(f"Loading sessions from {args.sessions_file}")
    folders = load_sessions(args.sessions_file)
    logger.info(f"Found {len(folders)} site folders")

    # Apply filter if specified
    if args.filter:
        filter_terms = [term.strip().lower() for term in args.filter.split(',')]
        original_count = len(folders)
        folders = [
            folder for folder in folders
            if any(term in folder.get('folder_name', '').lower() for term in filter_terms)
        ]
        logger.info(colorize(
            f"Filter applied: {original_count} -> {len(folders)} folders (matching: {args.filter})",
            Color.YELLOW
        ))
        if not folders:
            logger.error(colorize("No folders match the filter criteria", Color.RED))
            return 1

    # Select devices for mapping
    mapping_tasks = []
    for folder in folders:
        folder_name = folder.get('folder_name', 'Unknown')
        sessions = folder.get('sessions', [])

        device = select_device(sessions, folder_name)
        if device:
            site_name = extract_site_name(folder_name)
            device['site_name'] = site_name
            device['folder_name'] = folder_name
            mapping_tasks.append(device)
        else:
            logger.warning(f"Skipping {folder_name}: no suitable device")

    logger.info(f"Selected {len(mapping_tasks)} sites for mapping")

    if args.dry_run:
        print(colorize("\n=== DRY RUN - Would map the following sites ===", Color.YELLOW))
        for device in mapping_tasks:
            print(f"  {colorize(device['site_name'], Color.CYAN)}: "
                  f"{device['display_name']} ({device['host']})")
        return 0

    # Prepare config for workers
    config = {
        'username': args.username,
        'password': args.password,
        'alt_username': args.alt_username,
        'alt_password': args.alt_password,
        'domain_name': args.domain_name,
        'exclude_string': args.exclude_string,
        'output_dir': args.output_dir,
        'timeout': args.timeout,
        'max_devices': args.max_devices,
        'layout_algo': args.layout_algo,
        'save_debug_info': args.save_debug_info,
        'process_timeout': args.process_timeout,
        'use_python': args.use_python,
        'sc_command': args.sc_command,
    }

    # Run mapping with concurrent.futures
    print(colorize(f"\nStarting concurrent mapping with {args.workers} worker(s)", Color.BOLD))

    # Extract all site names for cross-site exclusion
    all_site_names = [device['site_name'] for device in mapping_tasks]

    worker_args = [(device, config, args.sc_path, all_site_names) for device in mapping_tasks]

    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        future_to_site = {
            executor.submit(run_mapper, task): task[0]['site_name']
            for task in worker_args
        }

        # Process results as they complete
        for future in as_completed(future_to_site):
            site_name = future_to_site[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                error_msg = f"Exception: {str(e)}"
                print(colorize(f"\n✗ {site_name}: {error_msg}\n", Color.RED))
                results.append((site_name, False, error_msg))

    # Summarize results
    print(colorize("\n" + "=" * 60, Color.BOLD))
    print(colorize("MAPPING SUMMARY", Color.BOLD))
    print(colorize("=" * 60 + "\n", Color.BOLD))

    success_count = sum(1 for _, success, _ in results if success)
    total = len(results)

    success_color = Color.GREEN if success_count == total else Color.YELLOW
    print(colorize(f"Successfully mapped: {success_count}/{total} sites\n", success_color))

    if success_count < total:
        print(colorize("Failed sites:", Color.RED))
        for site_name, success, message in results:
            if not success:
                print(f"  {colorize('✗', Color.RED)} {colorize(site_name, Color.YELLOW)}: {message}")
        print()

    if success_count > 0:
        print(colorize("Successful sites:", Color.GREEN))
        for site_name, success, message in results:
            if success:
                print(f"  {colorize('✓', Color.GREEN)} {colorize(site_name, Color.CYAN)}: {message}")
        print()

    return 0 if success_count == total else 1


if __name__ == '__main__':
    exit(main())