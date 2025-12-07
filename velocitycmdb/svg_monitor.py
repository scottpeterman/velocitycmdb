#!/usr/bin/env python3
"""
Network Map SVG Monitoring Dashboard (Color-Coded with Config)

This script creates a monitoring dashboard by:
1. Parsing an SVG network map
2. Loading monitoring configuration (including exclude lists)
3. Testing connectivity to each device
4. Highlighting devices based on connectivity status:
   - Green box = Device has IP and is reachable
   - Red box = Device has IP but is unreachable
   - No box = Device has no IP, excluded, or couldn't be matched

Usage:
  python svg_monitor.py --input network_map.svg --output status_map.svg [--config monitor_config.json]
"""

# Use lxml instead of the standard ElementTree
from lxml import etree as ET
import argparse
import socket
import time
import sys
import os
import json
import subprocess
import platform
import concurrent.futures
from typing import Dict, List, Any, Tuple, Optional, Union

# Import functions from svg_parser
from svg_parser import parse_svg_network_map, NAMESPACES

# Default configuration
DEFAULT_CONFIG = {
    "exclude_lists": {
        "ip": [],
        "name": []
    },
    "thresholds": {
        "proximity": 200
    },
    "visualization": {
        "up_color": "green",
        "down_color": "red",
        "border_width": 3,
        "font_size": 10
    },
    "monitor_ports": [22, 80],  # Default ports to check
    "ip_resolution": {
        "enabled": True,
        "domain_suffixes": [],
        "timeout": 1.0
    },
    "monitoring": {
        "timeout": 2.0,
        "parallel_checks": True,
        "ping_fallback": True  # NEW: Try ping if TCP fails
    }
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from JSON file if available, otherwise use defaults.

    Args:
        config_path: Path to the configuration file

    Returns:
        Dictionary containing configuration
    """
    config = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                loaded_config = json.load(f)

            # Merge loaded config with defaults
            for section in config:
                if section in loaded_config:
                    if isinstance(config[section], dict) and isinstance(loaded_config[section], dict):
                        config[section].update(loaded_config[section])
                    else:
                        config[section] = loaded_config[section]

            print(f"Loaded configuration from {config_path}")

            # Print exclude lists
            ip_count = len(config["exclude_lists"]["ip"])
            name_count = len(config["exclude_lists"]["name"])
            if ip_count > 0 or name_count > 0:
                print(f"Exclude lists: {ip_count} IPs, {name_count} device names")
        except Exception as e:
            print(f"Error loading configuration: {str(e)}")
            print(f"Using default configuration")
    else:
        print(f"No configuration file found, using defaults")

    return config


def resolve_device_ip(device_name: str, config: Dict[str, Any]) -> Optional[str]:
    """
    Attempt to resolve a device's IP address through various methods.

    Args:
        device_name: Name of the device to resolve
        config: Configuration with resolution settings

    Returns:
        IP address as string if successful, None otherwise
    """
    if not device_name or device_name == "Unknown":
        return None

    resolution_config = config.get("ip_resolution", {})
    if not resolution_config.get("enabled", True):
        return None

    timeout = resolution_config.get("timeout", 1.0)
    socket.setdefaulttimeout(timeout)

    # Try direct hostname resolution first
    try:
        ip_address = socket.gethostbyname(device_name)
        return ip_address
    except socket.gaierror:
        pass

    # Try with domain suffixes if provided
    domain_suffixes = resolution_config.get("domain_suffixes", [])
    for suffix in domain_suffixes:
        fqdn = device_name + suffix if not device_name.endswith(suffix) else device_name
        try:
            ip_address = socket.gethostbyname(fqdn)
            return ip_address
        except socket.gaierror:
            continue

    # All resolution attempts failed
    return None


def test_port_connectivity(ip: str, port: int, timeout: float = 2.0) -> bool:
    """
    Test connectivity to a specific port on a device.

    Args:
        ip: The IP address to test
        port: The port number to test
        timeout: Connection timeout in seconds

    Returns:
        True if connection succeeds, False otherwise
    """
    try:
        # Create a socket object
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        # Attempt to connect to the IP address on specified port
        result = sock.connect_ex((ip, port))

        # Close the socket
        sock.close()

        # If result is 0, connection succeeded
        return result == 0
    except:
        return False


def ping_host(ip: str, timeout: float = 2.0) -> bool:
    """
    Test connectivity using ICMP ping.

    Args:
        ip: The IP address to ping
        timeout: Timeout in seconds

    Returns:
        True if ping succeeds, False otherwise
    """
    try:
        # Determine platform-specific ping parameters
        system = platform.system().lower()

        if system == 'windows':
            # Windows: -n count, -w timeout in milliseconds
            count_param = '-n'
            timeout_param = '-w'
            timeout_val = str(int(timeout * 1000))
        else:
            # Linux/Mac: -c count, -W timeout in seconds
            count_param = '-c'
            timeout_param = '-W'
            timeout_val = str(int(timeout))

        # Build ping command
        cmd = ['ping', count_param, '1', timeout_param, timeout_val, ip]

        # Run ping with timeout
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1  # Give a little extra time
        )

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def test_multiple_ports(ip: str, ports: List[int], timeout: float = 2.0,
                        parallel: bool = True, ping_fallback: bool = True) -> Tuple[bool, List[Union[int, str]]]:
    """
    Test connectivity to multiple ports on a device.
    Falls back to ICMP ping if all TCP ports fail.

    Args:
        ip: The IP address to test
        ports: List of port numbers to test
        timeout: Connection timeout in seconds
        parallel: Whether to check ports in parallel
        ping_fallback: Whether to try ping if TCP fails

    Returns:
        Tuple of (overall_status, list_of_open_ports)
        If ping succeeds but TCP fails, returns (True, ['icmp'])
    """
    if not ports:
        # Default to SSH port if no ports specified
        ports = [22]

    open_ports = []

    if parallel and len(ports) > 1:
        # Use ThreadPoolExecutor for parallel port testing
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ports)) as executor:
            # Create a future for each port test
            future_to_port = {
                executor.submit(test_port_connectivity, ip, port, timeout): port
                for port in ports
            }

            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    is_open = future.result()
                    if is_open:
                        open_ports.append(port)
                except Exception:
                    # Handle any exceptions during port testing
                    pass
    else:
        # Sequential port testing
        for port in ports:
            if test_port_connectivity(ip, port, timeout):
                open_ports.append(port)

    # Device is considered up if at least one port is open
    if len(open_ports) > 0:
        return True, open_ports

    # TCP failed - try ping fallback if enabled
    if ping_fallback:
        if ping_host(ip, timeout):
            return True, ['icmp']

    # Everything failed
    return False, []


def modify_svg_with_status(
        svg_path: str,
        output_path: str,
        device_data: Dict[str, Any],
        config: Dict[str, Any],
        test_connectivity: bool = True,
        timeout: float = 2.0,
        simulate_failures: List[str] = None,
        test_mode: bool = False
) -> Dict[str, int]:
    """
    Modify an SVG file to highlight devices based on connectivity status.
    Enhanced version with IP resolution, multi-port checking, improved readability,
    and interactive clickable nodes.
    """
    # Import the interactive functionality
    try:
        from svg_interactive import add_interactive_elements, add_device_data_attributes
        interactive_enabled = True
    except ImportError:
        print("Warning: svg_interactive module not found. Interactive features disabled.")
        interactive_enabled = False

    # Register namespaces for proper ElementTree handling
    for prefix, uri in NAMESPACES.items():
        ET.register_namespace(prefix, uri)

    # Parse the SVG file using lxml
    parser = ET.XMLParser(remove_blank_text=True)
    tree = ET.parse(svg_path, parser)
    root = tree.getroot()

    # Get exclude lists from config
    excluded_ips = set(config["exclude_lists"]["ip"])
    excluded_names = set(config["exclude_lists"]["name"])

    # Get visualization settings
    up_color = config["visualization"]["up_color"]
    down_color = config["visualization"]["down_color"]
    border_width = config["visualization"]["border_width"]
    font_size = config["visualization"]["font_size"]

    # Get monitoring settings
    monitor_ports = config.get("monitor_ports", [22, 80])
    connection_timeout = config.get("monitoring", {}).get("timeout", timeout)
    parallel_checks = config.get("monitoring", {}).get("parallel_checks", True)
    ping_fallback = config.get("monitoring", {}).get("ping_fallback", True)

    # Create a mapping from position to device data
    position_to_device = {}
    for device in device_data["devices"]:
        key = (
            float(device["position"]["x"]),
            float(device["position"]["y"]),
            float(device["position"]["width"]),
            float(device["position"]["height"])
        )
        position_to_device[key] = device

    # Track status counts
    status_counts = {
        "up": 0,
        "down": 0,
        "excluded": 0,
        "unknown": 0
    }

    # Find all image elements (device nodes)
    image_elements = root.findall(".//{%s}image" % NAMESPACES["svg"])

    # Add a timestamp and connectivity status to the SVG
    # Create a group for connectivity results
    results_group = ET.Element("{%s}g" % NAMESPACES["svg"])
    results_group.set("id", "connectivity_results")
    results_group.set("class", "results-panel")
    results_group.set("style", "display: none;")

    # Add current timestamp
    timestamp_text = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
    timestamp_text.set("x", "10")
    timestamp_text.set("y", "20")
    timestamp_text.set("font-size", "14")
    timestamp_text.set("font-weight", "bold")
    import datetime
    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
    timestamp_text.text = f"Last updated: {formatted_time}"

    # Add results_group to the root
    root.append(results_group)

    print(f"Processing {len(image_elements)} device nodes...")
    if ping_fallback:
        print(f"Ping fallback: Enabled (will try ICMP if TCP fails)")

    # Lists to track connectivity results for the summary
    up_devices = []
    down_devices = []

    # Process each image element
    for img_elem in image_elements:
        # Get position and size
        x = float(img_elem.get('x', '0'))
        y = float(img_elem.get('y', '0'))
        width = float(img_elem.get('width', '0'))
        height = float(img_elem.get('height', '0'))

        # Find matching device
        device = None
        for pos, dev in position_to_device.items():
            # Compare with a small tolerance for floating point differences
            if (abs(pos[0] - x) < 1 and
                    abs(pos[1] - y) < 1 and
                    abs(pos[2] - width) < 1 and
                    abs(pos[3] - height) < 1):
                device = dev
                break

        if not device:
            print(f"  Warning: No device data found for image at ({x}, {y})")
            status_counts["unknown"] += 1
            continue

        # Get device info
        device_ip = device["deviceInfo"]["ip"]
        device_name = device["deviceInfo"]["name"] or "Unknown"

        # Check if device is excluded by name
        if device_name and device_name in excluded_names:
            print(f"  Skipping {device_name}: Name in exclude list")
            status_counts["excluded"] += 1
            continue

        # Attempt IP resolution if no IP is already available
        if not device_ip and device_name and device_name != "Unknown":
            print(f"  Attempting to resolve IP for {device_name}...")
            device_ip = resolve_device_ip(device_name, config)
            if device_ip:
                print(f"  Resolved {device_name} to {device_ip}")
                # Update the device info with resolved IP
                device["deviceInfo"]["ip"] = device_ip

        # Check if device is excluded by IP (after potential resolution)
        if device_ip and device_ip in excluded_ips:
            print(f"  Skipping {device_ip} ({device_name}): IP in exclude list")
            status_counts["excluded"] += 1
            continue

        if not device_ip:
            print(f"  Skipping {device_name}: No IP address")
            status_counts["unknown"] += 1
            continue

        # Determine connectivity status
        if test_mode:
            # In test mode, mark all devices with IPs as down
            status = "down"
            open_ports = []
            print(f"  {device_ip} ({device_name}): Marked DOWN for testing")
        elif simulate_failures and device_ip in simulate_failures:
            # Simulate failure for this IP
            status = "down"
            open_ports = []
            print(f"  {device_ip} ({device_name}): DOWN (simulated)")
        elif test_connectivity:
            # Actually test connectivity to multiple ports (with ping fallback)
            print(f"  Testing {device_ip} ({device_name}) on ports {monitor_ports}...", end="", flush=True)
            is_up, open_ports = test_multiple_ports(
                device_ip, monitor_ports, connection_timeout, parallel_checks, ping_fallback
            )
            status = "up" if is_up else "down"

            # Format the result message
            if open_ports == ['icmp']:
                print(f" {status.upper()} (ICMP ping only)")
            else:
                print(f" {status.upper()} (Open ports: {open_ports})")

            # Track connectivity results for summary
            if status == "up":
                up_devices.append((device_name, device_ip, open_ports))
            else:
                down_devices.append((device_name, device_ip))
        else:
            # Default to up if not testing connectivity
            status = "up"
            open_ports = monitor_ports  # Assume all ports are open
            print(f"  {device_ip} ({device_name}): Skipping connectivity test")

        # Update status counts
        status_counts[status] += 1

        # Get the parent of the image element
        parent = img_elem.getparent()

        # Create a rectangle element with appropriate border color
        rect = ET.Element("{%s}rect" % NAMESPACES["svg"])
        rect.set("x", str(x - 2))  # Slightly larger than the image
        rect.set("y", str(y - 2))
        rect.set("width", str(width + 4))
        rect.set("height", str(height + 4))

        # Set background and border based on status
        if status == "up":
            rect.set("fill", "rgba(0, 255, 0, 0.3)")  # Semi-transparent green
            rect.set("stroke", up_color)
            label_text = "UP"  # Simplified label
        else:
            rect.set("fill", "rgba(255, 0, 0, 0.4)")  # Semi-transparent red
            rect.set("stroke", down_color)
            label_text = "DOWN"  # Simplified label

        rect.set("stroke-width", str(border_width))

        # Add interactive data attributes if available
        if interactive_enabled:
            try:
                add_device_data_attributes(
                    rect,
                    device["deviceInfo"],
                    status,
                    open_ports,
                    formatted_time
                )
            except Exception as e:
                print(f"  Warning: Could not add interactive data: {e}")

        # Create a text background rectangle first
        text_width = len(label_text) * font_size * 0.8  # Adjust width calculation for shorter text
        text_bg = ET.Element("{%s}rect" % NAMESPACES["svg"])
        text_bg.set("x", str(x + width / 2 - text_width / 2))  # Center aligned with text
        text_bg.set("y", str(y - 5 - font_size))  # Position above the image
        text_bg.set("width", str(text_width))
        text_bg.set("height", str(font_size * 1.2))  # Slightly taller than font size
        text_bg.set("rx", "3")  # Rounded corners
        text_bg.set("ry", "3")  # Rounded corners

        # Set background color based on status
        if status == "up":
            text_bg.set("fill", "rgba(0, 255, 0, 0.7)")  # Semi-transparent green
        else:
            text_bg.set("fill", "rgba(255, 0, 0, 0.7)")  # Semi-transparent red

        # Create a text element for the status label
        status_text = ET.Element("{%s}text" % NAMESPACES["svg"])
        status_text.set("x", str(x + width / 2))
        status_text.set("y", str(y - 5))
        status_text.set("text-anchor", "middle")
        status_text.set("font-size", str(font_size))
        status_text.set("fill", "black")  # Solid black text for better readability
        status_text.set("font-weight", "bold")  # Make the text bold
        status_text.text = label_text

        # Use append instead of insert to control z-order
        parent.append(rect)
        parent.append(text_bg)
        parent.append(status_text)

    # Add connectivity results summary to the SVG
    # Create a background rectangle for the results
    results_bg = ET.SubElement(results_group, "{%s}rect" % NAMESPACES["svg"])
    results_bg.set("x", "10")
    results_bg.set("y", "30")
    results_bg.set("width", "300")
    results_bg.set("height", str(30 + (len(up_devices) + len(down_devices) + 4) * 20))
    results_bg.set("fill", "rgba(255, 255, 255, 0.8)")
    results_bg.set("stroke", "black")
    results_bg.set("stroke-width", "1")
    results_bg.set("rx", "5")
    results_bg.set("ry", "5")

    # Add summary title
    summary_title = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
    summary_title.set("x", "20")
    summary_title.set("y", "50")
    summary_title.set("font-size", "14")
    summary_title.set("font-weight", "bold")
    summary_title.text = "Connectivity Summary"

    # Add summary counts
    summary_counts = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
    summary_counts.set("x", "20")
    summary_counts.set("y", "70")
    summary_counts.set("font-size", "12")
    summary_counts.text = f"UP: {status_counts['up']} | DOWN: {status_counts['down']} | EXCLUDED: {status_counts['excluded']} | UNKNOWN: {status_counts['unknown']}"

    # Add device status details
    y_pos = 100

    # Add DOWN devices first (they're more important)
    if down_devices:
        down_header = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
        down_header.set("x", "20")
        down_header.set("y", str(y_pos))
        down_header.set("font-size", "12")
        down_header.set("font-weight", "bold")
        down_header.set("fill", down_color)
        down_header.text = "DOWN Devices:"
        y_pos += 20

        for name, ip in down_devices:
            down_device = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
            down_device.set("x", "30")
            down_device.set("y", str(y_pos))
            down_device.set("font-size", "11")
            down_device.set("fill", "black")
            down_device.text = f"{name} ({ip})"
            y_pos += 20

    # Add UP devices
    if up_devices:
        up_header = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
        up_header.set("x", "20")
        up_header.set("y", str(y_pos))
        up_header.set("font-size", "12")
        up_header.set("font-weight", "bold")
        up_header.set("fill", up_color)
        up_header.text = "UP Devices:"
        y_pos += 20

        for name, ip, ports in up_devices:
            up_device = ET.SubElement(results_group, "{%s}text" % NAMESPACES["svg"])
            up_device.set("x", "30")
            up_device.set("y", str(y_pos))
            up_device.set("font-size", "11")
            up_device.set("fill", "black")
            # Handle icmp-only case
            if ports == ['icmp']:
                port_str = "ICMP only"
            else:
                port_str = ", ".join(str(p) for p in sorted(ports))
            up_device.text = f"{name} ({ip}) - {port_str}"
            y_pos += 20

    # Add interactive elements if available
    if interactive_enabled:
        try:
            add_interactive_elements(tree, device_data, formatted_time)
        except Exception as e:
            print(f"Warning: Could not add interactive elements: {e}")

    # Save the modified SVG
    tree.write(output_path, encoding="utf-8", xml_declaration=True, pretty_print=True)

    return status_counts


def save_parsed_data_as_json(parsed_data: Dict[str, Any], svg_path: str) -> str:
    """
    Save the parsed device data as a JSON file.

    Args:
        parsed_data: The parsed device information
        svg_path: Path to the original SVG file

    Returns:
        Path to the saved JSON file
    """
    try:
        # Generate JSON filename from SVG path
        base_name = os.path.basename(svg_path)
        name_without_ext = os.path.splitext(base_name)[0]
        json_path = os.path.join(os.path.dirname(svg_path), f"{name_without_ext}.json")

        # Write the data to a JSON file
        with open(json_path, 'w') as f:
            json.dump(parsed_data, f, indent=2)

        print(f"Saved parsed data to {json_path}")
        return json_path
    except Exception as e:
        print(f"Error saving parsed data: {str(e)}")
        return ""


def create_status_overlay(
        svg_path: str,
        parsed_data: Dict[str, Any],
        output_path: str,
        config: Dict[str, Any],
        test_connectivity: bool = True,
        timeout: float = 2.0,
        simulate_failures: List[str] = None,
        test_mode: bool = False,
        save_json: bool = True
) -> Dict[str, int]:
    """
    Create a network status overlay SVG.

    Enhanced version with IP resolution and multi-port checking.
    """
    print(f"Creating network status overlay...")
    print(f"Input SVG: {svg_path}")
    print(f"Output SVG: {output_path}")
    print(f"Devices found: {parsed_data['totalDevices']}")

    # Get custom monitoring ports from config
    monitor_ports = config.get("monitor_ports", [22, 80])
    print(f"Monitoring ports: {monitor_ports}")

    # Check ping fallback setting
    ping_fallback = config.get("monitoring", {}).get("ping_fallback", True)
    print(f"Ping fallback: {'Enabled' if ping_fallback else 'Disabled'}")

    # Check if IP resolution is enabled
    ip_resolution = config.get("ip_resolution", {})
    if ip_resolution.get("enabled", True):
        domain_suffixes = ip_resolution.get("domain_suffixes", [])
        suffix_msg = f" with domain suffixes: {domain_suffixes}" if domain_suffixes else ""
        print(f"IP resolution: Enabled{suffix_msg}")
    else:
        print("IP resolution: Disabled")

    # Create the status overlay
    status_counts = modify_svg_with_status(
        svg_path,
        output_path,
        parsed_data,
        config,
        test_connectivity,
        timeout,
        simulate_failures,
        test_mode,
    )

    # Print summary
    print("\nStatus Summary:")
    print(f"  Devices UP (green): {status_counts['up']}")
    print(f"  Devices DOWN (red): {status_counts['down']}")
    print(f"  Devices EXCLUDED: {status_counts['excluded']}")
    print(f"  Devices UNKNOWN (no IP or not matched): {status_counts['unknown']}")
    print(f"  Total Devices: {sum(status_counts.values())}")

    if save_json:
        save_parsed_data_as_json(parsed_data, svg_path)

    return status_counts


def main():
    """Main function for command-line usage."""
    parser = argparse.ArgumentParser(description='Create a network status monitoring dashboard from an SVG map')

    parser.add_argument('--input', required=True, help='Path to the input SVG file')
    parser.add_argument('--output', required=True, help='Path to save the modified SVG')
    parser.add_argument('--config', help='Path to configuration JSON file')
    parser.add_argument('--timeout', type=float, default=2.0, help='Connection timeout in seconds')
    parser.add_argument('--test-mode', action='store_true', help='Mark all devices with IPs as down (red)')
    parser.add_argument('--no-test', action='store_true',
                        help='Skip connectivity tests, mark all devices with IPs as up (green)')
    parser.add_argument('--sim-failures', help='Comma-separated list of IPs to simulate as failed')
    parser.add_argument('--no-json', action='store_true', help='Skip saving parsed data as JSON')
    parser.add_argument('--ports', help='Comma-separated list of ports to check (overrides config)')
    parser.add_argument('--no-ping', action='store_true', help='Disable ping fallback')

    args = parser.parse_args()

    try:
        # Load configuration
        config = load_config(args.config)

        # Override ports if specified in command line
        if args.ports:
            try:
                ports = [int(p.strip()) for p in args.ports.split(',')]
                config["monitor_ports"] = ports
                print(f"Using command-line ports: {ports}")
            except ValueError:
                print(f"Error parsing ports from '{args.ports}', using config values")

        # Override ping fallback if specified
        if args.no_ping:
            config["monitoring"]["ping_fallback"] = False
            print("Ping fallback disabled via command line")

        # Parse the SVG to get device information
        print(f"Parsing SVG file: {args.input}")
        parsed_data = parse_svg_network_map(args.input, config["thresholds"]["proximity"])

        # Process simulate failures argument
        simulate_failures = args.sim_failures.split(',') if args.sim_failures else None

        # Create the status overlay
        status_counts = create_status_overlay(
            args.input,
            parsed_data,
            args.output,
            config,
            not args.no_test,  # Skip connectivity tests if no-test is specified
            args.timeout,
            simulate_failures,
            args.test_mode,
            not args.no_json  # Save JSON unless no-json flag is provided
        )

        print(f"\nStatus dashboard created successfully: {args.output}")

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    exit(main())