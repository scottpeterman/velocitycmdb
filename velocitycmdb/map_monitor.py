#!/usr/bin/env python3
"""
Network Monitor Poller

This script continuously polls network devices and updates the status dashboard.
It's designed to run unattended during change windows with robust error handling.

Features:
- Periodic polling with configurable interval
- Robust error handling to prevent crashes
- Logging of all activities and errors
- Option to save historical snapshots
- Status summary after each polling cycle
- Option to run once and exit

Usage:
  python monitor_poller.py --input network_map.svg --output dashboard.svg [options]
"""

import os
import sys
import time
import argparse
import logging
import json
import traceback
import socket
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Try to import lxml, fall back to standard ElementTree if not available
try:
    from lxml import etree as ET

    USING_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET

    USING_LXML = False
    print("Warning: lxml not found. Using standard ElementTree instead.")
    print("Some features may be limited. Install lxml for best results:")
    print("  pip install lxml")

# Import functions from other modules with error handling
try:
    from svg_monitor import (
        create_status_overlay, load_config, test_port_connectivity,
        modify_svg_with_status, test_multiple_ports
    )
    from svg_parser import parse_svg_network_map, NAMESPACES
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure svg_monitor.py and svg_parser.py are in the same directory.")
    traceback.print_exc()
    sys.exit(1)


# Set up logging
def setup_logging(log_file: str, console_level: str = "INFO") -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        log_file: Path to the log file
        console_level: Logging level for console output

    Returns:
        Configured logger
    """
    # Create logger
    logger = logging.getLogger("network_monitor")
    logger.setLevel(logging.DEBUG)

    # Create handlers
    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(log_file)

    # Set levels
    console_level_num = getattr(logging, console_level.upper(), logging.INFO)
    console_handler.setLevel(console_level_num)
    file_handler.setLevel(logging.DEBUG)  # Log everything to file

    # Create formatters
    console_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    file_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # Set formatters
    console_handler.setFormatter(console_format)
    file_handler.setFormatter(file_format)

    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def safe_parse_svg(svg_path: str, logger: logging.Logger) -> Optional[ET.ElementTree]:
    """
    Safely parse an SVG file with error handling.

    Args:
        svg_path: Path to the SVG file
        logger: Logger instance

    Returns:
        Parsed ElementTree or None if parsing failed
    """
    try:
        if USING_LXML:
            parser = ET.XMLParser(remove_blank_text=True)
            tree = ET.parse(svg_path, parser)
        else:
            tree = ET.parse(svg_path)
        return tree
    except Exception as e:
        logger.error(f"Error parsing SVG file {svg_path}: {e}")
        return None


def save_snapshot(
        output_path: str,
        snapshot_dir: str,
        status_counts: Dict[str, int],
        logger: logging.Logger
) -> Optional[str]:
    """
    Save a timestamped snapshot of the current status dashboard.

    Args:
        output_path: Path to the current dashboard SVG
        snapshot_dir: Directory to save snapshots
        status_counts: Status counts from the monitoring run
        logger: Logger instance

    Returns:
        Path to the saved snapshot or None if failed
    """
    try:
        # Create snapshot directory if it doesn't exist
        os.makedirs(snapshot_dir, exist_ok=True)

        # Generate timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Generate snapshot filename
        base_name = os.path.basename(output_path)
        name_without_ext = os.path.splitext(base_name)[0]
        snapshot_path = os.path.join(snapshot_dir, f"{name_without_ext}_{timestamp}.svg")

        # Copy the current dashboard to the snapshot directory
        with open(output_path, 'rb') as src_file:
            with open(snapshot_path, 'wb') as dst_file:
                dst_file.write(src_file.read())

        # Save status counts alongside the snapshot
        status_path = os.path.join(snapshot_dir, f"{name_without_ext}_{timestamp}.json")
        with open(status_path, 'w') as f:
            json.dump({
                "timestamp": timestamp,
                "status": status_counts
            }, f, indent=2)

        logger.info(f"Saved snapshot to {snapshot_path}")
        return snapshot_path

    except Exception as e:
        logger.error(f"Error saving snapshot: {e}")
        return None


def check_file_access(file_path: str, mode: str, logger: logging.Logger) -> bool:
    """
    Check if a file is accessible with the given mode.

    Args:
        file_path: Path to the file
        mode: Access mode ('r' for read, 'w' for write)
        logger: Logger instance

    Returns:
        True if the file is accessible, False otherwise
    """
    try:
        if mode == 'r':
            # Check if file exists and is readable
            return os.path.isfile(file_path) and os.access(file_path, os.R_OK)
        elif mode == 'w':
            # Check if directory is writable
            dir_path = os.path.dirname(file_path) or '.'
            return os.access(dir_path, os.W_OK)
        return False
    except Exception as e:
        logger.error(f"Error checking file access for {file_path}: {e}")
        return False


# This updated version of run_monitoring_cycle includes status_checks in the JSON output
def run_monitoring_cycle(
        input_path: str,
        output_path: str,
        config: Dict[str, Any],
        timeout: float,
        simulate_failures: Optional[List[str]],
        test_mode: bool,
        no_test: bool,
        snapshot_dir: Optional[str],
        logger: logging.Logger,
        save_json: bool = True,
        ports: Optional[List[int]] = None
) -> Dict[str, int]:
    """
    Run a single monitoring cycle with error handling.

    Args:
        input_path: Path to the input SVG file
        output_path: Path to save the output SVG
        config: Monitoring configuration
        timeout: Connection timeout in seconds
        simulate_failures: List of IPs to simulate as failed
        test_mode: Whether to mark all devices as down
        no_test: Whether to skip connectivity tests
        snapshot_dir: Directory to save snapshots
        logger: Logger instance
        save_json: Whether to save parsed data as JSON in the same folder as output
        ports: Optional list of ports to check (overrides config)

    Returns:
        Status counts dictionary or empty dict if failed
    """
    try:
        logger.info(f"Starting monitoring cycle at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Check file access
        if not check_file_access(input_path, 'r', logger):
            logger.error(f"Input file {input_path} is not readable")
            return {}

        if not check_file_access(output_path, 'w', logger):
            logger.error(f"Output file {output_path} is not writable")
            return {}

        # Update config with ports if provided
        if ports:
            config["monitor_ports"] = ports
            logger.info(f"Using specified ports for monitoring: {ports}")

        # Parse the SVG
        logger.info(f"Parsing SVG file: {input_path}")
        parsed_data = None
        try:
            parsed_data = parse_svg_network_map(input_path, config["thresholds"]["proximity"])
        except Exception as e:
            logger.error(f"Error parsing SVG: {e}")
            logger.debug(traceback.format_exc())
            return {}

        if not parsed_data:
            logger.error("Failed to parse SVG file")
            return {}

        logger.info(f"Found {parsed_data['totalDevices']} devices in the SVG")

        # Create the status overlay
        try:
            # Set timeout in config
            config["monitoring"] = config.get("monitoring", {})
            config["monitoring"]["timeout"] = timeout

            status_counts = create_status_overlay(
                input_path,
                parsed_data,
                output_path,
                config,
                not no_test,
                timeout,
                simulate_failures,
                test_mode,
                False  # Don't save JSON in create_status_overlay, we'll do it here
            )
        except Exception as e:
            logger.error(f"Error creating status overlay: {e}")
            logger.debug(traceback.format_exc())
            return {}

        # Save JSON file if requested
        if save_json:
            try:
                # Generate JSON filename from SVG output path
                output_dir = os.path.dirname(output_path)
                base_name = os.path.basename(output_path)
                name_without_ext = os.path.splitext(base_name)[0]
                json_path = os.path.join(output_dir, f"{name_without_ext}.json")

                # Create array to store status checks
                status_checks = []

                # Get monitoring settings
                monitor_ports = config.get("monitor_ports", [22, 80])
                connection_timeout = config.get("monitoring", {}).get("timeout", timeout)
                parallel_checks = config.get("monitoring", {}).get("parallel_checks", True)

                # Get exclude lists from config
                excluded_ips = set(config["exclude_lists"]["ip"])
                excluded_names = set(config["exclude_lists"]["name"])

                # Test each device and record actual status
                if not no_test and not test_mode:
                    for device in parsed_data["devices"]:
                        device_info = device["deviceInfo"]
                        ip = device_info.get("ip")
                        name = device_info.get("name", "Unknown")

                        # Skip excluded devices
                        if name in excluded_names or (ip and ip in excluded_ips):
                            status_checks.append({
                                "ip": ip,
                                "name": name,
                                "status": "excluded",
                                "excluded": True
                            })
                            continue

                        # Skip devices without IP
                        if not ip:
                            continue

                        # Simulate failures if specified
                        if simulate_failures and ip in simulate_failures:
                            status_checks.append({
                                "ip": ip,
                                "name": name,
                                "status": "down",
                                "open_ports": [],
                                "simulated": True
                            })
                            continue

                        # Actually test connectivity
                        logger.info(f"  Testing {ip} ({name}) on ports {monitor_ports}...")
                        is_up, open_ports = test_multiple_ports(
                            ip, monitor_ports, connection_timeout, parallel_checks
                        )
                        status = "up" if is_up else "down"

                        # Add to status checks
                        status_checks.append({
                            "ip": ip,
                            "name": name,
                            "status": status,
                            "open_ports": open_ports
                        })
                elif test_mode:
                    # In test mode, mark all as down
                    for device in parsed_data["devices"]:
                        device_info = device["deviceInfo"]
                        ip = device_info.get("ip")
                        name = device_info.get("name", "Unknown")

                        if ip:
                            status_checks.append({
                                "ip": ip,
                                "name": name,
                                "status": "down",
                                "open_ports": [],
                                "test_mode": True
                            })
                else:
                    # In no-test mode, mark all as up
                    for device in parsed_data["devices"]:
                        device_info = device["deviceInfo"]
                        ip = device_info.get("ip")
                        name = device_info.get("name", "Unknown")

                        if ip:
                            status_checks.append({
                                "ip": ip,
                                "name": name,
                                "status": "up",
                                "open_ports": monitor_ports,
                                "no_test": True
                            })

                # Create a dictionary with timestamp, device status, and status checks
                json_data = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "devices": parsed_data["devices"],
                    "totalDevices": parsed_data["totalDevices"],
                    "status": status_counts,
                    "status_checks": status_checks
                }

                # Write JSON file
                with open(json_path, 'w') as f:
                    json.dump(json_data, f, indent=2)

                logger.info(f"Saved parsed data to {json_path}")
            except Exception as e:
                logger.error(f"Error saving JSON data: {e}")
                logger.debug(traceback.format_exc())

        # Log status summary
        logger.info("Status Summary:")
        logger.info(f"  Devices UP (green): {status_counts['up']}")
        logger.info(f"  Devices DOWN (red): {status_counts['down']}")
        logger.info(f"  Devices EXCLUDED: {status_counts['excluded']}")
        logger.info(f"  Devices UNKNOWN: {status_counts['unknown']}")
        logger.info(f"  Total Devices: {sum(status_counts.values())}")

        # Save snapshot if requested
        if snapshot_dir:
            save_snapshot(output_path, snapshot_dir, status_counts, logger)

        logger.info(f"Monitoring cycle completed successfully")
        return status_counts

    except Exception as e:
        logger.error(f"Unhandled error in monitoring cycle: {e}")
        logger.debug(traceback.format_exc())
        return {}


def create_status_file(status_file: str, status_counts: Dict[str, int], logger: logging.Logger) -> bool:
    """
    Create a status file with the current monitoring results.

    Args:
        status_file: Path to the status file
        status_counts: Status counts from the monitoring run
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    try:
        status_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "status": status_counts
        }

        with open(status_file, 'w') as f:
            json.dump(status_data, f, indent=2)

        return True
    except Exception as e:
        logger.error(f"Error creating status file: {e}")
        return False


def main():
    """Main function for the continuous monitoring poller."""
    parser = argparse.ArgumentParser(description='Network Monitor Poller')

    parser.add_argument('--input', required=True, help='Path to the input SVG file')
    parser.add_argument('--output', required=True, help='Path to save the modified SVG')
    parser.add_argument('--config', default='monitor_config.json', help='Path to configuration JSON file')
    parser.add_argument('--interval', type=int, default=300, help='Polling interval in seconds (default: 300)')
    parser.add_argument('--timeout', type=float, default=2.0, help='Connection timeout in seconds')
    parser.add_argument('--test-mode', action='store_true', help='Mark all devices with IPs as down (red)')
    parser.add_argument('--no-test', action='store_true',
                        help='Skip connectivity tests, mark all devices with IPs as up (green)')
    parser.add_argument('--sim-failures', help='Comma-separated list of IPs to simulate as failed')
    parser.add_argument('--log-file', default='network_monitor.log', help='Path to the log file')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO',
                        help='Console logging level')
    parser.add_argument('--snapshot-dir', help='Directory to save timestamped snapshots')
    parser.add_argument('--snapshot-interval', type=int, default=0, help='Take snapshots every N cycles (0 to disable)')
    parser.add_argument('--status-file', help='Path to save current status as JSON')
    parser.add_argument('--max-failures', type=int, default=0,
                        help='Stop after N consecutive failures (0 to run indefinitely)')
    parser.add_argument('--no-json', action='store_true', help='Skip saving parsed data as JSON in output folder')
    parser.add_argument('--ports', help='Comma-separated list of ports to check (overrides config)')
    parser.add_argument('--run-once', action='store_true', help='Run a single monitoring cycle and exit')

    args = parser.parse_args()

    # Set up logging
    logger = setup_logging(args.log_file, args.log_level)

    # Log startup information
    logger.info("=" * 80)
    logger.info("Network Monitor Poller Starting")
    logger.info(f"Version: 1.2.0")  # Updated version number
    logger.info(f"Input SVG: {args.input}")
    logger.info(f"Output SVG: {args.output}")
    logger.info(f"Configuration: {args.config}")
    logger.info(f"Polling Interval: {args.interval} seconds")
    logger.info(f"Connection Timeout: {args.timeout} seconds")

    # Process ports argument
    ports = None
    if args.ports:
        try:
            ports = [int(p.strip()) for p in args.ports.split(',')]
            logger.info(f"Monitoring ports: {ports}")
        except ValueError:
            logger.error(f"Error parsing ports from '{args.ports}', using config values")

    if args.test_mode:
        logger.info("Test Mode: All devices will be marked as DOWN")
    if args.no_test:
        logger.info("No Test Mode: All devices will be marked as UP without testing")
    if args.sim_failures:
        logger.info(f"Simulating failures for: {args.sim_failures}")
    if args.snapshot_dir:
        logger.info(f"Saving snapshots to: {args.snapshot_dir}")
        if args.snapshot_interval > 0:
            logger.info(f"Snapshot interval: Every {args.snapshot_interval} cycles")
    if args.status_file:
        logger.info(f"Saving status to: {args.status_file}")
    if args.max_failures > 0:
        logger.info(f"Will stop after {args.max_failures} consecutive failures")
    if args.no_json:
        logger.info("Skipping JSON output in the SVG output folder")
    else:
        logger.info("Saving device data as JSON in the SVG output folder")
    if args.run_once:
        logger.info("Run-once mode: Will exit after a single monitoring cycle")
    logger.info("=" * 80)

    try:
        # Load configuration
        config = load_config(args.config)

        # Process simulate failures argument
        simulate_failures = args.sim_failures.split(',') if args.sim_failures else None

        # Main polling loop
        cycle_count = 0
        consecutive_failures = 0

        while True:
            cycle_count += 1
            logger.info(f"Starting monitoring cycle #{cycle_count}")

            # Run monitoring cycle
            start_time = time.time()
            status_counts = run_monitoring_cycle(
                args.input,
                args.output,
                config,
                args.timeout,
                simulate_failures,
                args.test_mode,
                args.no_test,
                args.snapshot_dir if args.snapshot_dir and (
                        args.snapshot_interval == 0 or cycle_count % args.snapshot_interval == 0) else None,
                logger,
                not args.no_json,  # Save JSON unless no-json flag is provided
                ports
            )
            elapsed_time = time.time() - start_time

            # Check if monitoring was successful
            if status_counts:
                consecutive_failures = 0
                logger.info(f"Monitoring cycle #{cycle_count} completed in {elapsed_time:.2f} seconds")

                # Save status file if requested
                if args.status_file:
                    create_status_file(args.status_file, status_counts, logger)
            else:
                consecutive_failures += 1
                logger.warning(f"Monitoring cycle #{cycle_count} failed. Consecutive failures: {consecutive_failures}")

                # Check if max failures reached
                if args.max_failures > 0 and consecutive_failures >= args.max_failures:
                    logger.error(f"Reached maximum consecutive failures ({args.max_failures}). Exiting.")
                    return 1

            # Exit after a single cycle if run-once mode is enabled
            if args.run_once:
                logger.info("Run-once mode enabled. Exiting after a single monitoring cycle.")
                return 0

            # Wait for next cycle
            next_run = start_time + args.interval
            wait_time = max(0, next_run - time.time())

            if wait_time > 0:
                logger.info(f"Waiting {wait_time:.2f} seconds until next cycle")
                time.sleep(wait_time)

    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
        return 0
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    exit(main())