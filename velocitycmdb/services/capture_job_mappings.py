"""
Capture Job Mappings - Maps UI capture types to actual job files

This mapping connects the user-friendly capture type names in the UI
to the specific job files generated for each vendor.

Job files follow the naming pattern: job_XXX_{vendor}_{capture-type}.json
where vendor can be: arista, cisco-ios, cisco-nxos, juniper
"""

from typing import Dict, List, Tuple
from pathlib import Path

# Map UI capture type names to job file prefixes
# The actual job files are: job_{id}_{vendor}_{capture_type}.json
CAPTURE_TYPE_MAPPINGS = {
    # Core network data
    'configs': {
        'ui_label': 'Configuration (show running-config)',
        'job_suffix': 'configs',
        'description': 'Device running configuration',
        'output_dir': 'configs',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 328,
            'cisco-ios': 329,
            'cisco-nxos': 330,
            'juniper': 331
        },
        'commands': {
            'arista': 'show running-config',
            'cisco-ios': 'show running-config',
            'cisco-nxos': 'show running-config',
            'juniper': 'show configuration'
        },
        'prompt_count': 1
    },

    'arp': {
        'ui_label': 'ARP Table (show ip arp)',
        'job_suffix': 'arp',
        'description': 'ARP table entries',
        'output_dir': 'arp',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 300,
            'cisco-ios': 301,
            'cisco-nxos': 302,
            'juniper': 303
        },
        'commands': {
            'arista': 'show ip arp',
            'cisco-ios': 'show ip arp',
            'cisco-nxos': 'show ip arp',
            'juniper': 'show arp'
        },
        'prompt_count': 1
    },

    'mac': {
        'ui_label': 'MAC Table (show mac address-table)',
        'job_suffix': 'mac',
        'description': 'MAC address table',
        'output_dir': 'mac',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 360,
            'cisco-ios': 361,
            'cisco-nxos': 362,
            'juniper': 363
        },
        'commands': {
            'arista': 'show mac address-table',
            'cisco-ios': 'show mac address-table',
            'cisco-nxos': 'show mac address-table',
            'juniper': 'show ethernet-switching table'
        },
        'prompt_count': 1
    },

    'lldp': {
        'ui_label': 'LLDP Neighbors (show lldp neighbors detail)',
        'job_suffix': 'lldp-detail',
        'description': 'LLDP neighbor information',
        'output_dir': 'lldp',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 356,
            'cisco-ios': 357,
            'cisco-nxos': 358,
            'juniper': 359
        },
        'commands': {
            'arista': 'show lldp neighbors detail',
            'cisco-ios': 'show lldp neighbors detail',
            'cisco-nxos': 'show lldp neighbors detail',
            'juniper': 'show lldp neighbors detail'
        },
        'prompt_count': 1
    },

    'interfaces': {
        'ui_label': 'Interfaces (show interfaces status)',
        'job_suffix': 'int-status',
        'description': 'Interface status and configuration',
        'output_dir': 'interfaces',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 337,
            'cisco-ios': 338,
            'cisco-nxos': 339,
            'juniper': 340
        },
        'commands': {
            'arista': 'show interfaces status',
            'cisco-ios': 'show interfaces status',
            'cisco-nxos': 'show interfaces status',
            'juniper': 'show interfaces terse'
        },
        'prompt_count': 1
    },

    'routes': {
        'ui_label': 'Routes (show ip route)',
        'job_suffix': 'routes',
        'description': 'IP routing table',
        'output_dir': 'routes',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 380,
            'cisco-ios': 381,
            'cisco-nxos': 382,
            'juniper': 383
        },
        'commands': {
            'arista': 'show ip route',
            'cisco-ios': 'show ip route',
            'cisco-nxos': 'show ip route',
            'juniper': 'show route'
        },
        'prompt_count': 1
    },

    'version': {
        'ui_label': 'Version (show version)',
        'job_suffix': 'version',
        'description': 'Device version and hardware info',
        'output_dir': 'version',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 396,
            'cisco-ios': 397,
            'cisco-nxos': 398,
            'juniper': 399
        },
        'commands': {
            'arista': 'show version',
            'cisco-ios': 'show version',
            'cisco-nxos': 'show version',
            'juniper': 'show version'
        },
        'prompt_count': 1
    },

    'inventory': {
        'ui_label': 'Inventory (show inventory)',
        'job_suffix': 'inventory',
        'description': 'Hardware inventory',
        'output_dir': 'inventory',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 344,
            'cisco-ios': 345,
            'cisco-nxos': 346,
            'juniper': 347
        },
        'commands': {
            'arista': 'show inventory',
            'cisco-ios': 'show inventory',
            'cisco-nxos': 'show inventory',
            'juniper': 'show chassis hardware'
        },
        'prompt_count': 1
    },

    # BGP information
    'bgp-summary': {
        'ui_label': 'BGP Summary',
        'job_suffix': 'bgp-summary',
        'description': 'BGP neighbor summary',
        'output_dir': 'bgp',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 316,
            'cisco-ios': 317,
            'cisco-nxos': 318,
            'juniper': 319
        },
        'commands': {
            'arista': 'show ip bgp summary',
            'cisco-ios': 'show ip bgp summary',
            'cisco-nxos': 'show ip bgp summary',
            'juniper': 'show bgp summary'
        },
        'prompt_count': 1
    },

    'bgp-neighbor': {
        'ui_label': 'BGP Neighbors',
        'job_suffix': 'bgp-neighbor',
        'description': 'Detailed BGP neighbor information',
        'output_dir': 'bgp',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 312,
            'cisco-ios': 313,
            'cisco-nxos': 314,
            'juniper': 315
        },
        'commands': {
            'arista': 'show ip bgp neighbors',
            'cisco-ios': 'show ip bgp neighbors',
            'cisco-nxos': 'show ip bgp neighbors',
            'juniper': 'show bgp neighbor'
        },
        'prompt_count': 1
    },

    # OSPF information
    'ospf-neighbor': {
        'ui_label': 'OSPF Neighbors',
        'job_suffix': 'ospf-neighbor',
        'description': 'OSPF neighbor information',
        'output_dir': 'ospf',
        'vendors': ['arista', 'cisco-ios', 'cisco-nxos', 'juniper'],
        'job_ids': {
            'arista': 368,
            'cisco-ios': 369,
            'cisco-nxos': 370,
            'juniper': 371
        },
        'commands': {
            'arista': 'show ip ospf neighbor',
            'cisco-ios': 'show ip ospf neighbor',
            'cisco-nxos': 'show ip ospf neighbor',
            'juniper': 'show ospf neighbor'
        },
        'prompt_count': 1
    },
}


def get_job_file_path(capture_type: str, vendor: str, jobs_dir: Path) -> Path:
    """
    Get the path to a specific job file

    Args:
        capture_type: UI capture type (e.g., 'configs', 'arp')
        vendor: Vendor name (e.g., 'cisco-ios', 'arista')
        jobs_dir: Directory containing job files

    Returns:
        Path to the job file
    """
    if capture_type not in CAPTURE_TYPE_MAPPINGS:
        raise ValueError(f"Unknown capture type: {capture_type}")

    mapping = CAPTURE_TYPE_MAPPINGS[capture_type]

    if vendor not in mapping['job_ids']:
        raise ValueError(f"Vendor {vendor} not supported for capture type {capture_type}")

    job_id = mapping['job_ids'][vendor]
    job_suffix = mapping['job_suffix']

    filename = f"job_{job_id}_{vendor}_{job_suffix}.json"
    return jobs_dir / filename


def get_jobs_for_capture_types(capture_types: List[str],
                                vendors: List[str],
                                jobs_dir: Path) -> List[Tuple[str, Path]]:
    """
    Get all job files needed for the specified capture types and vendors

    Args:
        capture_types: List of UI capture types
        vendors: List of vendors (e.g., ['cisco-ios', 'arista'])
        jobs_dir: Directory containing job files

    Returns:
        List of (capture_type, job_file_path) tuples
    """
    jobs = []

    for capture_type in capture_types:
        if capture_type not in CAPTURE_TYPE_MAPPINGS:
            continue

        mapping = CAPTURE_TYPE_MAPPINGS[capture_type]

        for vendor in vendors:
            if vendor in mapping['job_ids']:
                job_path = get_job_file_path(capture_type, vendor, jobs_dir)
                if job_path.exists():
                    jobs.append((capture_type, job_path))

    return jobs


def calculate_prompt_count(capture_type: str, vendor: str, auto_paging: bool = True,
                          command_text: str = None) -> int:
    """
    Calculate the expected number of prompts for a command sequence

    spn.py expects prompt_count to include the initial prompt PLUS one for each command.

    Example:
        command_text = "enable,terminal length 0,show running-config"
        → 3 commands
        → Initial prompt (1) + 3 commands = prompt_count = 4

    This matches spn.py's calculate_prompt_count logic:
        count = 1  # Initial prompt
        for cmd in commands:
            count += 1

    Args:
        capture_type: The capture type being executed
        vendor: Vendor platform
        auto_paging: Whether auto-paging is enabled (not used - kept for compatibility)
        command_text: The ACTUAL command_text from the job file (comma-separated commands)

    Returns:
        Expected prompt count = 1 (initial) + number of commands
    """
    # If we have the actual command_text, split on commas and count
    if command_text:
        commands = [c.strip() for c in command_text.split(',') if c.strip()]
        # Add 1 for initial prompt that spn.py expects
        prompt_count = 1 + len(commands)
        return max(1, prompt_count)

    # Fallback: shouldn't happen, but return 1 if no command_text
    return 1


def get_all_capture_types() -> List[Dict[str, str]]:
    """
    Get all available capture types for UI display

    Returns:
        List of dicts with 'id', 'label', and 'description' keys
    """
    return [
        {
            'id': key,
            'label': value['ui_label'],
            'description': value['description']
        }
        for key, value in CAPTURE_TYPE_MAPPINGS.items()
    ]


def get_vendors_for_capture_type(capture_type: str) -> List[str]:
    """
    Get list of vendors that support a specific capture type

    Args:
        capture_type: The capture type

    Returns:
        List of vendor names
    """
    if capture_type not in CAPTURE_TYPE_MAPPINGS:
        return []

    return CAPTURE_TYPE_MAPPINGS[capture_type]['vendors']