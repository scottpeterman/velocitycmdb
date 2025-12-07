#!/usr/bin/env python3
"""
Network Map SVG Parser - Updated

This script extracts device information from network map SVG files,
with updated categorization logic based on the actual data structure.
"""

import xml.etree.ElementTree as ET
import argparse
import json
import csv
import math
import re
import os
from typing import List, Dict, Tuple, Any, Optional

# Define XML namespaces for SVG parsing
NAMESPACES = {
    'svg': 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink'
}


def parse_svg_network_map(svg_path: str, proximity_threshold: float = 200.0) -> Dict[str, Any]:
    """
    Parse an SVG network map file and extract device information.

    Args:
        svg_path: Path to the SVG file
        proximity_threshold: Maximum distance to associate text with a device

    Returns:
        Dictionary containing parsed device information
    """
    # Register namespaces for proper ElementTree handling
    for prefix, uri in NAMESPACES.items():
        ET.register_namespace(prefix, uri)

    # Parse the SVG file
    tree = ET.parse(svg_path)
    root = tree.getroot()

    # Extract text elements
    text_elements = extract_text_elements(root)
    print(f"Found {len(text_elements)} text elements")

    # Extract image elements (device nodes)
    image_elements = extract_image_elements(root)
    print(f"Found {len(image_elements)} image elements")

    # Associate text with device nodes
    devices = associate_text_with_images(text_elements, image_elements, proximity_threshold)

    return {
        "totalDevices": len(devices),
        "devices": devices,
        "stats": {
            "totalTextElements": len(text_elements),
            "totalImageElements": len(image_elements)
        }
    }


def extract_text_elements(root: ET.Element) -> List[Dict[str, Any]]:
    """
    Extract all text elements from the SVG.

    Args:
        root: Root element of the parsed SVG

    Returns:
        List of dictionaries containing text element information
    """
    text_elements = []

    # Find all text elements in the SVG
    for text_elem in root.findall(".//svg:text", NAMESPACES):
        x = float(text_elem.get('x', '0'))
        y = float(text_elem.get('y', '0'))
        text = text_elem.text or ""

        text_elements.append({
            "x": x,
            "y": y,
            "text": text
        })

    return text_elements


def extract_image_elements(root: ET.Element) -> List[Dict[str, Any]]:
    """
    Extract all image elements from the SVG.

    Args:
        root: Root element of the parsed SVG

    Returns:
        List of dictionaries containing image element information
    """
    image_elements = []

    # Find all image elements in the SVG
    for img_elem in root.findall(".//svg:image", NAMESPACES):
        x = float(img_elem.get('x', '0'))
        y = float(img_elem.get('y', '0'))
        width = float(img_elem.get('width', '0'))
        height = float(img_elem.get('height', '0'))

        # Get image source if available
        href = img_elem.get(f"{{{NAMESPACES['xlink']}}}href", "")

        image_elements.append({
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "href": href
        })

    return image_elements


def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def is_interface_pattern(text: str) -> bool:
    """
    Check if the given text matches any common network interface pattern.

    Args:
        text: The text to check

    Returns:
        True if the text matches an interface pattern, False otherwise
    """
    # Expanded list of interface prefixes
    interface_prefixes = [
        # Ethernet interfaces
        'Eth', 'Et', 'Ethernet',

        # Gigabit interfaces
        'Gi', 'GigE', 'GigabitEth', 'GigabitEthernet', 'Gigabit',

        # Ten-Gigabit interfaces
        'Te', 'TenGig', 'TenGigE', 'TenGigabitEthernet', 'TenGigabit',

        # 25-Gigabit interfaces
        'Twe', 'TwentyFiveGig', 'TwentyFiveGigE', 'TwentyFiveGigabitEthernet',

        # 40-Gigabit interfaces
        'Fo', 'FortyGig', 'FortyGigE', 'FortyGigabitEthernet',

        # 100-Gigabit interfaces
        'Hu', 'Hun', 'HundredGig', 'HundredGigE', 'HundredGigabitEthernet', '100Gig',

        # Port channels
        'Po', 'Port-Channel', 'PortChannel', 'Port_Channel',

        # Management interfaces
        'Ma', 'Mgmt', 'Management', 'OOB', 'OOB_Management', 'Wan',

        # VLAN interfaces
        'Vl', 'Vlan',

        # Loopback interfaces
        'Lo', 'Loopback',

        # FastEthernet interfaces
        'Fa', 'Fast', 'FastEthernet'
    ]

    # Common interface number patterns
    number_patterns = [
        r'\d+',  # Single number (e.g., Gi1)
        r'\d+/\d+',  # Two-part (e.g., Gi1/0)
        r'\d+/\d+/\d+',  # Three-part (e.g., Gi1/0/1)
        r'\d+/\d+\.\d+',  # Subinterface (e.g., Gi1/0.1)
        r'\d+/\d+/\d+\.\d+'  # Complex subinterface (e.g., Gi1/0/1.1)
    ]

    # Check if text starts with any interface prefix
    for prefix in interface_prefixes:
        if any(re.match(f"^{prefix}{pattern}$", text, re.IGNORECASE) for pattern in number_patterns):
            return True

        # Special case for management interfaces that might not have numbers
        if prefix in ['Ma', 'Mgmt', 'Management', 'OOB', 'OOB_Management', 'Wan'] and text.upper() == prefix.upper():
            return True

    return False


def calculate_edge_distance(rect_x, rect_y, rect_width, rect_height, text_x, text_y):
    """
    Calculate the minimum distance from any edge or corner of a rectangle to a point.

    Args:
        rect_x, rect_y: Rectangle top-left coordinates
        rect_width, rect_height: Rectangle dimensions
        text_x, text_y: Text element coordinates

    Returns:
        Minimum distance from the rectangle edge to the text point
    """
    # Calculate rectangle corners and edges
    rect_right = rect_x + rect_width
    rect_bottom = rect_y + rect_height

    # Check if point is inside rectangle (should be rare for text elements)
    if rect_x <= text_x <= rect_right and rect_y <= text_y <= rect_bottom:
        return 0

    # Calculate horizontal distance (if text is above or below the rectangle)
    h_dist = 0
    if text_x < rect_x:
        h_dist = rect_x - text_x
    elif text_x > rect_right:
        h_dist = text_x - rect_right

    # Calculate vertical distance (if text is to the left or right of the rectangle)
    v_dist = 0
    if text_y < rect_y:
        v_dist = rect_y - text_y
    elif text_y > rect_bottom:
        v_dist = text_y - rect_bottom

    # If both h_dist and v_dist are non-zero, text is diagonally away from rectangle
    if h_dist > 0 and v_dist > 0:
        return math.sqrt(h_dist ** 2 + v_dist ** 2)

    # Otherwise text is directly above, below, left, or right of rectangle
    return max(h_dist, v_dist)


def associate_text_with_images(
        text_elements: List[Dict[str, Any]],
        image_elements: List[Dict[str, Any]],
        proximity_threshold: float
) -> List[Dict[str, Any]]:
    """
    Associate text elements with nearby image elements based on a combined approach:
    - First prioritize text elements directly below a device
    - Then use edge proximity with grouping
    """
    devices = []

    # For each image (device node), find related text elements
    for i, image in enumerate(image_elements):
        image_x = image['x']
        image_y = image['y']
        image_width = image['width']
        image_height = image['height']

        # Define the device's bottom edge
        bottom_y = image_y + image_height

        # Find text elements that are directly below the device (within tolerance)
        below_tolerance = 50  # Pixel tolerance for "directly below"
        horizontal_tolerance = image_width * 0.7  # Allow some horizontal offset

        directly_below_texts = []
        other_nearby_texts = []

        for text in text_elements:
            text_x = text['x']
            text_y = text['y']

            # Calculate edge-based distance
            edge_distance = calculate_edge_distance(
                image_x, image_y, image_width, image_height, text_x, text_y
            )

            # Check if text is directly below the device
            is_below = (text_y > bottom_y and
                        text_y <= bottom_y + below_tolerance and
                        text_x >= image_x - horizontal_tolerance and
                        text_x <= image_x + image_width + horizontal_tolerance)

            if is_below:
                directly_below_texts.append({
                    **text,
                    "distance": edge_distance,
                    "is_below": True
                })
            elif edge_distance < proximity_threshold:
                other_nearby_texts.append({
                    **text,
                    "distance": edge_distance,
                    "is_below": False
                })

        # Group text elements that are vertically aligned (likely from the same label set)
        related_text_groups = []

        # First, add the directly below texts (these are highest priority)
        if directly_below_texts:
            # Sort by vertical position
            directly_below_texts.sort(key=lambda t: t["y"])

            # Group by vertical position (text within 15 pixels vertically are considered together)
            current_group = [directly_below_texts[0]]
            for text in directly_below_texts[1:]:
                if abs(text["y"] - current_group[-1]["y"]) < 15:
                    # Text is part of current group
                    current_group.append(text)
                else:
                    # Start a new group
                    related_text_groups.append(current_group)
                    current_group = [text]

            # Add the last group
            if current_group:
                related_text_groups.append(current_group)

        # If we don't have enough information from directly below texts,
        # include other nearby texts
        if not any(has_complete_device_info(group) for group in related_text_groups):
            # Sort other nearby texts by distance
            other_nearby_texts.sort(key=lambda t: t["distance"])

            # Group by vertical position
            if other_nearby_texts:
                current_group = [other_nearby_texts[0]]
                for text in other_nearby_texts[1:]:
                    if abs(text["y"] - current_group[-1]["y"]) < 15:
                        current_group.append(text)
                    else:
                        related_text_groups.append(current_group)
                        current_group = [text]

                if current_group:
                    related_text_groups.append(current_group)

        # Flatten all text groups and add distance-based priority
        # This gives preference to directly-below texts while preserving grouping
        all_related_texts = []
        for group_index, group in enumerate(related_text_groups):
            # Add group priority (groups with lower index have higher priority)
            for text in group:
                # Directly below texts get highest priority (negative distance)
                if text.get("is_below", False):
                    text["distance"] -= 1000  # Ensure these are chosen first
                # Add group priority to maintain grouping
                text["distance"] += group_index * 10
                all_related_texts.append(text)

        # Sort by adjusted distance
        all_related_texts.sort(key=lambda t: t["distance"])

        # Categorize texts
        device_info = categorize_device_texts(all_related_texts)

        # Create device node with all information
        devices.append({
            "nodeId": f"node_{i}",
            "position": {
                "x": image_x,
                "y": image_y,
                "width": image_width,
                "height": image_height
            },
            "deviceInfo": device_info,
            "allTexts": all_related_texts
        })

    return devices


def has_complete_device_info(text_group):
    """Check if a text group contains complete device information (hostname and IP)"""
    has_ip = any(re.match(r'^\d+\.\d+\.\d+\.\d+$', text["text"].strip()) for text in text_group)
    has_hostname = any('-' in text["text"].strip() and
                       not re.match(r'^(WS-C\d+|C\d+|CISCO\d+|DCS-\d+)', text["text"].strip())
                       for text in text_group)
    return has_ip and has_hostname
def categorize_device_texts(text_elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Categorize text elements into device information categories.
    Enhanced with text grouping to prevent IP/hostname mismatches.
    """
    device_info = {
        "name": None,  # Network device name
        "ip": None,  # IP address
        "interface": None,  # Interface information
        "additionalInfo": []  # Any other text associated with the device
    }

    # Handle empty case
    if not text_elements:
        return device_info

    # Group text elements by vertical position (likely to be the same device)
    vertical_groups = {}
    for text in text_elements:
        y_rounded = round(text["y"] / 15) * 15  # Group texts within 15 pixels vertically
        if y_rounded not in vertical_groups:
            vertical_groups[y_rounded] = []
        vertical_groups[y_rounded].append(text)

    # Sort groups by average distance (closest group first)
    sorted_groups = sorted(vertical_groups.values(),
                           key=lambda group: sum(text["distance"] for text in group) / len(group))

    # Process each group of texts
    for group in sorted_groups:
        # Sort texts within group by y position
        sorted_texts = sorted(group, key=lambda t: t["y"])

        # Extract texts
        texts = [text["text"].strip() for text in sorted_texts if text["text"].strip()]

        # Skip empty groups
        if not texts:
            continue

        # Try to identify elements in this group
        ip_address = None
        hostname = None
        model = None
        interface = None

        for text in texts:
            # Check for IP address
            if re.match(r'^\d+\.\d+\.\d+\.\d+$', text):
                ip_address = text
                continue

            # Check for hostname pattern (contains hyphens but not model numbers)
            if '-' in text and not re.match(r'^(WS-C\d+|C\d+|CISCO\d+|DCS-\d+)', text):
                hostname = text
                continue

            # Check for model number patterns
            if re.match(r'^(WS-C\d+|C\d+|CISCO\d+|DCS-\d+)', text):
                model = text
                continue

            # Check for interface patterns
            if not interface and is_interface_pattern(text):
                interface = text
                continue

            # Add to additional info if it doesn't match any pattern
            if text not in device_info["additionalInfo"]:
                device_info["additionalInfo"].append(text)

        # If we found a hostname and IP in the same group, use them
        if hostname and ip_address:
            device_info["name"] = hostname
            device_info["ip"] = ip_address
            if model:
                device_info["additionalInfo"].append(model)
            if interface:
                device_info["interface"] = interface

            # Found a complete set, use it
            return device_info

        # If we only found one of them, store it for later
        if hostname and not device_info["name"]:
            device_info["name"] = hostname

        if ip_address and not device_info["ip"]:
            device_info["ip"] = ip_address

        if model and model not in device_info["additionalInfo"]:
            device_info["additionalInfo"].append(model)

        if interface and not device_info["interface"]:
            device_info["interface"] = interface

    # Handle fallback cases
    if not device_info["name"] and device_info["ip"]:
        device_info["name"] = f"Device-{device_info['ip']}"

    return device_info


def save_output(data: Dict[str, Any], output_format: str, output_path: str) -> None:
    """
    Save parsed data to the specified output format.

    Args:
        data: Parsed device data
        output_format: Format to save (json, csv, or text)
        output_path: Path to save the output file
    """
    if output_format == 'json':
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)

    elif output_format == 'csv':
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow([
                'Node ID', 'X', 'Y', 'Width', 'Height',
                'Interface', 'IP', 'Name', 'Additional Info'
            ])

            # Write data rows
            for device in data['devices']:
                writer.writerow([
                    device['nodeId'],
                    device['position']['x'],
                    device['position']['y'],
                    device['position']['width'],
                    device['position']['height'],
                    device['deviceInfo']['interface'] or '',
                    device['deviceInfo']['ip'] or '',
                    device['deviceInfo']['name'] or '',
                    '; '.join(device['deviceInfo']['additionalInfo'])
                ])

    elif output_format == 'text':
        with open(output_path, 'w') as f:
            f.write(f"Network Map Analysis Report\n")
            f.write(f"Generated: {os.path.basename(output_path)}\n")
            f.write(f"Total Devices: {data['totalDevices']}\n")
            f.write(f"Text Elements: {data['stats']['totalTextElements']}\n")
            f.write(f"Image Elements: {data['stats']['totalImageElements']}\n")
            f.write("\nDevice Details:\n")

            for device in data['devices']:
                f.write(f"\n[{device['nodeId']}] {device['deviceInfo']['name'] or 'Unnamed Device'}\n")
                f.write(f"  Position: ({device['position']['x']}, {device['position']['y']})\n")
                f.write(f"  Size: {device['position']['width']} × {device['position']['height']}\n")

                if device['deviceInfo']['interface']:
                    f.write(f"  Interface: {device['deviceInfo']['interface']}\n")

                if device['deviceInfo']['ip']:
                    f.write(f"  IP: {device['deviceInfo']['ip']}\n")

                if device['deviceInfo']['additionalInfo']:
                    f.write(f"  Additional Info: {', '.join(device['deviceInfo']['additionalInfo'])}\n")

                f.write("  Associated Texts:\n")
                for text in device['allTexts']:
                    f.write(f"    \"{text['text']}\" at ({text['x']}, {text['y']}), distance: {text['distance']:.2f}\n")
    else:
        raise ValueError(f"Unsupported output format: {output_format}")

