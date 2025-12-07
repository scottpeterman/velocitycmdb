#!/usr/bin/env python3
"""
Multi-Map Network Monitor

Monitors multiple network maps by processing all SVG files in a source directory
and outputting status-overlaid versions to a destination directory.

Source maps remain untouched, monitored versions go to the output folder.

Default paths:
  Source: ~/.velocitycmdb/data/monitored_maps/
  Output: ~/.velocitycmdb/data/maps/monitoring/

Usage:
  python multi_map_monitor.py [options]
  python multi_map_monitor.py --run-once
  python multi_map_monitor.py --interval 60 --ports 22,443
"""

import os
import sys
import time
import argparse
import logging
import json
import traceback
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to import lxml, fall back to standard ElementTree if not available
try:
    from lxml import etree as ET

    USING_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET

    USING_LXML = False
    print("Warning: lxml not found. Using standard ElementTree instead.")

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

# Default paths
DEFAULT_SOURCE_DIR = os.path.expanduser("~/.velocitycmdb/data/monitored_maps")
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/.velocitycmdb/data/maps/monitoring")
DEFAULT_CONFIG = os.path.expanduser("~/.velocitycmdb/monitor_config.json")
DEFAULT_LOG_FILE = os.path.expanduser("~/.velocitycmdb/logs/multi_map_monitor.log")


def setup_logging(log_file: str, console_level: str = "INFO") -> logging.Logger:
    """Set up logging configuration."""
    # Create log directory if needed
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("multi_map_monitor")
    logger.setLevel(logging.DEBUG)

    # Clear any existing handlers
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler()
    console_level_num = getattr(logging, console_level.upper(), logging.INFO)
    console_handler.setLevel(console_level_num)
    console_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    return logger


def discover_svg_files(source_dir: str, logger: logging.Logger) -> List[Path]:
    """Find all SVG files in the source directory."""
    source_path = Path(source_dir)

    if not source_path.exists():
        logger.error(f"Source directory does not exist: {source_dir}")
        return []

    svg_files = sorted(source_path.glob("*.svg"))
    logger.info(f"Found {len(svg_files)} SVG files in {source_dir}")

    for svg in svg_files:
        logger.debug(f"  - {svg.name}")

    return svg_files


def process_single_map(
        input_path: Path,
        output_dir: str,
        config: Dict[str, Any],
        timeout: float,
        ports: Optional[List[int]],
        no_test: bool,
        test_mode: bool,
        simulate_failures: Optional[List[str]],
        logger: logging.Logger
) -> Dict[str, Any]:
    """
    Process a single SVG map file.

    Returns:
        Dict with status counts and metadata
    """
    map_name = input_path.stem
    output_path = os.path.join(output_dir, input_path.name)

    result = {
        "map_name": map_name,
        "input_path": str(input_path),
        "output_path": output_path,
        "success": False,
        "status_counts": {},
        "device_count": 0,
        "error": None
    }

    try:
        logger.info(f"Processing map: {map_name}")

        # Update config with ports if provided
        if ports:
            config["monitor_ports"] = ports

        # Parse the SVG
        parsed_data = parse_svg_network_map(str(input_path), config["thresholds"]["proximity"])

        if not parsed_data:
            result["error"] = "Failed to parse SVG"
            logger.error(f"  [{map_name}] Failed to parse SVG")
            return result

        result["device_count"] = parsed_data["totalDevices"]
        logger.info(f"  [{map_name}] Found {parsed_data['totalDevices']} devices")

        # Set timeout in config
        config["monitoring"] = config.get("monitoring", {})
        config["monitoring"]["timeout"] = timeout

        # Create status overlay
        status_counts = create_status_overlay(
            str(input_path),
            parsed_data,
            output_path,
            config,
            not no_test,  # run_tests
            timeout,
            simulate_failures,
            test_mode,
            False  # save_json - we'll handle this separately
        )

        result["status_counts"] = status_counts
        result["success"] = True

        # Save JSON alongside the output SVG
        json_path = os.path.join(output_dir, f"{map_name}.json")
        json_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "map_name": map_name,
            "totalDevices": parsed_data["totalDevices"],
            "status": status_counts
        }

        with open(json_path, 'w') as f:
            json.dump(json_data, f, indent=2)

        logger.info(
            f"  [{map_name}] ✓ UP: {status_counts.get('up', 0)}, DOWN: {status_counts.get('down', 0)}, EXCLUDED: {status_counts.get('excluded', 0)}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  [{map_name}] Error: {e}")
        logger.debug(traceback.format_exc())

    return result


def run_monitoring_cycle(
        source_dir: str,
        output_dir: str,
        config: Dict[str, Any],
        timeout: float,
        ports: Optional[List[int]],
        no_test: bool,
        test_mode: bool,
        simulate_failures: Optional[List[str]],
        parallel: bool,
        logger: logging.Logger
) -> Dict[str, Any]:
    """
    Run a monitoring cycle for all maps.

    Returns:
        Summary of all map processing results
    """
    cycle_start = datetime.datetime.now()
    logger.info(f"{'=' * 70}")
    logger.info(f"Starting monitoring cycle at {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Discover SVG files
    svg_files = discover_svg_files(source_dir, logger)

    if not svg_files:
        logger.warning("No SVG files found to process")
        return {"success": False, "maps_processed": 0}

    results = []

    if parallel and len(svg_files) > 1:
        # Process maps in parallel
        logger.info(f"Processing {len(svg_files)} maps in parallel...")
        with ThreadPoolExecutor(max_workers=min(4, len(svg_files))) as executor:
            futures = {
                executor.submit(
                    process_single_map,
                    svg_file,
                    output_dir,
                    config.copy(),  # Copy config to avoid thread issues
                    timeout,
                    ports,
                    no_test,
                    test_mode,
                    simulate_failures,
                    logger
                ): svg_file for svg_file in svg_files
            }

            for future in as_completed(futures):
                result = future.result()
                results.append(result)
    else:
        # Process maps sequentially
        for svg_file in svg_files:
            result = process_single_map(
                svg_file,
                output_dir,
                config,
                timeout,
                ports,
                no_test,
                test_mode,
                simulate_failures,
                logger
            )
            results.append(result)

    # Generate summary
    cycle_end = datetime.datetime.now()
    elapsed = (cycle_end - cycle_start).total_seconds()

    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    total_devices = sum(r.get("device_count", 0) for r in results)
    total_up = sum(r.get("status_counts", {}).get("up", 0) for r in results)
    total_down = sum(r.get("status_counts", {}).get("down", 0) for r in results)
    total_excluded = sum(r.get("status_counts", {}).get("excluded", 0) for r in results)

    summary = {
        "success": len(failed) == 0,
        "timestamp": cycle_end.isoformat(),
        "elapsed_seconds": elapsed,
        "maps_processed": len(results),
        "maps_successful": len(successful),
        "maps_failed": len(failed),
        "total_devices": total_devices,
        "total_up": total_up,
        "total_down": total_down,
        "total_excluded": total_excluded,
        "results": results
    }

    # Log summary
    logger.info(f"{'=' * 70}")
    logger.info("CYCLE SUMMARY")
    logger.info(f"  Maps processed: {len(results)} ({len(successful)} successful, {len(failed)} failed)")
    logger.info(f"  Total devices: {total_devices}")
    logger.info(f"  Total UP: {total_up}")
    logger.info(f"  Total DOWN: {total_down}")
    logger.info(f"  Total EXCLUDED: {total_excluded}")
    logger.info(f"  Elapsed time: {elapsed:.2f} seconds")
    logger.info(f"{'=' * 70}")

    if failed:
        logger.warning("Failed maps:")
        for r in failed:
            logger.warning(f"  - {r['map_name']}: {r.get('error', 'Unknown error')}")

    # Save cycle summary
    summary_path = os.path.join(output_dir, "monitoring_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    """Main function for multi-map monitoring."""
    parser = argparse.ArgumentParser(
        description='Multi-Map Network Monitor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run once with defaults
  python multi_map_monitor.py --run-once

  # Continuous monitoring every 60 seconds
  python multi_map_monitor.py --interval 60

  # Custom directories
  python multi_map_monitor.py --source-dir /path/to/maps --output-dir /path/to/output

  # Test specific ports
  python multi_map_monitor.py --run-once --ports 22,443

  # Skip actual connectivity tests (mark all as up)
  python multi_map_monitor.py --run-once --no-test
        """
    )

    # Directory arguments
    parser.add_argument('--source-dir', default=DEFAULT_SOURCE_DIR,
                        help=f'Directory containing source SVG maps (default: {DEFAULT_SOURCE_DIR})')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR,
                        help=f'Directory for output SVG maps (default: {DEFAULT_OUTPUT_DIR})')

    # Config and logging
    parser.add_argument('--config', default=DEFAULT_CONFIG,
                        help=f'Path to configuration JSON file (default: {DEFAULT_CONFIG})')
    parser.add_argument('--log-file', default=DEFAULT_LOG_FILE,
                        help=f'Path to log file (default: {DEFAULT_LOG_FILE})')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO',
                        help='Console logging level')

    # Monitoring options
    parser.add_argument('--interval', type=int, default=300,
                        help='Polling interval in seconds (default: 300)')
    parser.add_argument('--timeout', type=float, default=2.0,
                        help='Connection timeout in seconds')
    parser.add_argument('--ports',
                        help='Comma-separated list of ports to check (overrides config)')

    # Test modes
    parser.add_argument('--test-mode', action='store_true',
                        help='Mark all devices as down (red)')
    parser.add_argument('--no-test', action='store_true',
                        help='Skip connectivity tests, mark all as up (green)')
    parser.add_argument('--sim-failures',
                        help='Comma-separated list of IPs to simulate as failed')

    # Execution modes
    parser.add_argument('--run-once', action='store_true',
                        help='Run a single monitoring cycle and exit')
    parser.add_argument('--sequential', action='store_true',
                        help='Process maps sequentially instead of in parallel')

    # Failure handling
    parser.add_argument('--max-failures', type=int, default=0,
                        help='Stop after N consecutive failures (0 = run indefinitely)')

    args = parser.parse_args()

    # Set up logging
    logger = setup_logging(args.log_file, args.log_level)

    # Log startup
    logger.info("=" * 80)
    logger.info("Multi-Map Network Monitor Starting")
    logger.info(f"Version: 1.0.0")
    logger.info(f"Source directory: {args.source_dir}")
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Configuration: {args.config}")
    logger.info(f"Polling Interval: {args.interval} seconds")
    logger.info(f"Connection Timeout: {args.timeout} seconds")

    if args.run_once:
        logger.info("Mode: Run once and exit")
    else:
        logger.info("Mode: Continuous polling")

    if args.test_mode:
        logger.info("Test Mode: All devices will be marked as DOWN")
    if args.no_test:
        logger.info("No Test Mode: All devices will be marked as UP without testing")

    logger.info("=" * 80)

    # Parse ports
    ports = None
    if args.ports:
        try:
            ports = [int(p.strip()) for p in args.ports.split(',')]
            logger.info(f"Monitoring ports: {ports}")
        except ValueError:
            logger.error(f"Error parsing ports from '{args.ports}'")

    # Parse simulate failures
    simulate_failures = args.sim_failures.split(',') if args.sim_failures else None

    try:
        # Load configuration
        config = load_config(args.config)

        # Main loop
        cycle_count = 0
        consecutive_failures = 0

        while True:
            cycle_count += 1
            logger.info(f"\nStarting cycle #{cycle_count}")

            start_time = time.time()

            summary = run_monitoring_cycle(
                args.source_dir,
                args.output_dir,
                config,
                args.timeout,
                ports,
                args.no_test,
                args.test_mode,
                simulate_failures,
                not args.sequential,
                logger
            )

            elapsed_time = time.time() - start_time

            if summary.get("success") or summary.get("maps_successful", 0) > 0:
                consecutive_failures = 0
                logger.info(f"Cycle #{cycle_count} completed in {elapsed_time:.2f} seconds")
            else:
                consecutive_failures += 1
                logger.warning(f"Cycle #{cycle_count} failed. Consecutive failures: {consecutive_failures}")

                if args.max_failures > 0 and consecutive_failures >= args.max_failures:
                    logger.error(f"Reached maximum consecutive failures ({args.max_failures}). Exiting.")
                    return 1

            # Exit if run-once
            if args.run_once:
                logger.info("Run-once mode. Exiting.")
                return 0

            # Wait for next cycle
            wait_time = max(0, args.interval - elapsed_time)
            if wait_time > 0:
                logger.info(f"Waiting {wait_time:.1f} seconds until next cycle...")
                time.sleep(wait_time)

    except KeyboardInterrupt:
        logger.info("\nMonitoring stopped by user")
        return 0
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    exit(main())