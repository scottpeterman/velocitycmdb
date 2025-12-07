
def add_interactive_elements(tree, device_data, timestamp):
    """Add interactive elements to SVG tree for device information display."""
    # svg_interactive.py
    from lxml import etree as ET
    from svg_parser import NAMESPACES

    # Find all rectangle elements that represent devices
    script_element = ET.Element("{%s}script" % NAMESPACES["svg"])

    # Add minimal JavaScript that will call the external function
    script_element.set("type", "text/javascript")
    script_element.text = """
    function handleDeviceClick(evt) {
        const rect = evt.target;
        const data = {
            ip: rect.getAttribute('data-ip'),
            name: rect.getAttribute('data-name'),
            status: rect.getAttribute('data-status'),
            lastChecked: rect.getAttribute('data-last-checked'),
            openPorts: rect.getAttribute('data-open-ports'),
            model: rect.getAttribute('data-model')
        };

        // Call external function if it exists
        if (window.showNetworkDeviceInfo) {
            window.showNetworkDeviceInfo(data, evt);
        }
    }
    """

    # Add the script element to the SVG
    root = tree.getroot()
    root.append(script_element)

    return tree


def add_device_data_attributes(rect_element, device_info, status, open_ports, timestamp):
    """Add data attributes to device rectangle for interactive display."""
    # Debug output to verify the data being attached
    print(f"  Adding data attributes for device: {device_info.get('name', 'Unknown')}")
    print(f"    IP: {device_info.get('ip', '')}")
    print(f"    Status: {status}")
    print(f"    Open ports: {open_ports}")

    # Add data attributes for the interactive popup
    rect_element.set("data-ip", device_info.get("ip", ""))
    rect_element.set("data-name", device_info.get("name", "Unknown"))
    rect_element.set("data-status", status)
    rect_element.set("data-last-checked", timestamp)
    rect_element.set("data-open-ports", ",".join(map(str, open_ports)) if open_ports else "")

    # Add model information if available
    if device_info.get("model"):
        rect_element.set("data-model", device_info.get("model"))

    # Try to extract model information from additionalInfo if available
    elif device_info.get("additionalInfo"):
        # Look for common Cisco model patterns in additional info
        model_info = next((info for info in device_info.get("additionalInfo", [])
                           if "C9200" in info or "WS-C" in info or "C2960" in info or
                           "DCS-7" in info), "")
        if model_info:
            rect_element.set("data-model", model_info)

    # Add cursor style and click handler
    rect_element.set("style", "cursor:pointer;")
    rect_element.set("onclick", "handleDeviceClick(evt)")

    return rect_element