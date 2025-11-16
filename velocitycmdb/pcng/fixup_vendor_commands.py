#!/usr/bin/env python3
"""
Script to add vendor keys to existing command_templates.json file
"""

import json
import os
from pathlib import Path


def add_vendor_keys_to_templates():
    """Add vendor keys to command templates based on prefixes"""

    # Define vendor mapping based on prefixes
    vendor_prefixes = {
        'cisco_': 'cisco',
        'arista_': 'arista',
        'aruba_': 'arista',  # Aruba now part of HPE, but similar commands to Arista
        'paloalto_': 'paloalto',
        'ion_': 'cloudgenix',  # CloudGenix ION devices
        'cloudgenix_': 'cloudgenix',
        'juniper_': 'juniper',
        'fortinet_': 'fortinet',
        'fortigate_': 'fortinet'
    }

    template_file = "command_templates.json"

    # Check if file exists
    if not os.path.exists(template_file):
        print(f"Error: {template_file} not found!")
        return False

    # Create backup
    backup_file = f"{template_file}.backup"
    print(f"Creating backup: {backup_file}")

    try:
        # Load existing templates
        with open(template_file, 'r', encoding='utf-8') as f:
            templates = json.load(f)

        # Create backup
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(templates, f, indent=2)

        # Process each template
        updated_count = 0
        for template_key, template_data in templates.items():
            # Skip if vendor already exists
            if 'vendor' in template_data:
                print(f"Template {template_key} already has vendor: {template_data['vendor']}")
                continue

            # Find matching vendor prefix
            detected_vendor = None
            for prefix, vendor in vendor_prefixes.items():
                if template_key.startswith(prefix):
                    detected_vendor = vendor
                    break

            # Add vendor key if detected
            if detected_vendor:
                template_data['vendor'] = detected_vendor
                updated_count += 1
                print(f"Added vendor '{detected_vendor}' to template '{template_key}'")
            else:
                # Set as generic if no prefix matches
                template_data['vendor'] = 'generic'
                updated_count += 1
                print(f"Set vendor 'generic' for template '{template_key}' (no prefix match)")

        # Save updated templates
        with open(template_file, 'w', encoding='utf-8') as f:
            json.dump(templates, f, indent=2, ensure_ascii=False)

        print(f"\nSuccess! Updated {updated_count} templates.")
        print(f"Backup saved as: {backup_file}")
        print(f"Updated file: {template_file}")

        return True

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def preview_vendor_mapping():
    """Preview what vendor keys would be added without making changes"""

    vendor_prefixes = {
        'cisco_': 'cisco',
        'arista_': 'arista',
        'aruba_': 'arista',
        'paloalto_': 'paloalto',
        'ion_': 'cloudgenix',
        'cloudgenix_': 'cloudgenix',
        'juniper_': 'juniper',
        'fortinet_': 'fortinet',
        'fortigate_': 'fortinet'
    }

    template_file = "command_templates.json"

    if not os.path.exists(template_file):
        print(f"Error: {template_file} not found!")
        return

    try:
        with open(template_file, 'r', encoding='utf-8') as f:
            templates = json.load(f)

        print("Preview of vendor assignments:")
        print("=" * 50)

        vendor_counts = {}

        for template_key, template_data in templates.items():
            # Check if vendor already exists
            if 'vendor' in template_data:
                existing_vendor = template_data['vendor']
                vendor_counts[existing_vendor] = vendor_counts.get(existing_vendor, 0) + 1
                print(f"  {template_key:<40} -> {existing_vendor} (existing)")
                continue

            # Find matching vendor prefix
            detected_vendor = None
            for prefix, vendor in vendor_prefixes.items():
                if template_key.startswith(prefix):
                    detected_vendor = vendor
                    break

            if not detected_vendor:
                detected_vendor = 'generic'

            vendor_counts[detected_vendor] = vendor_counts.get(detected_vendor, 0) + 1
            print(f"  {template_key:<40} -> {detected_vendor}")

        print("\nSummary by vendor:")
        print("-" * 30)
        for vendor, count in sorted(vendor_counts.items()):
            print(f"  {vendor}: {count} templates")

        print(f"\nTotal templates: {len(templates)}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("Command Template Vendor Key Updater")
    print("=" * 40)

    # First show preview
    print("\n1. Preview of changes:")
    preview_vendor_mapping()

    # Ask for confirmation
    print("\n" + "=" * 40)
    response = input("Do you want to apply these changes? (y/N): ").strip().lower()

    if response in ['y', 'yes']:
        print("\n2. Applying changes:")
        success = add_vendor_keys_to_templates()

        if success:
            print("\nVendor keys have been successfully added to your templates!")
            print("You can now restart the Network Job Runner application.")
        else:
            print("\nFailed to update templates. Check the error messages above.")
    else:
        print("\nNo changes made. Exiting...")