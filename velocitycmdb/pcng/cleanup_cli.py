#!/usr/bin/env python3
"""
Multi-vendor CLI output cleanup script for network devices.
Handles Cisco, HP/Aruba, and Arista devices with vendor-specific patterns.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


class MultiVendorCLICleaner:
    def __init__(self, fingerprints_dir: str):
        self.fingerprints_dir = Path(fingerprints_dir)
        self.device_prompts = {}
        self.device_vendors = {}

        # Vendor-specific noise patterns
        self.vendor_patterns = {
            'cisco': [
                r'^.*terminal length \d+.*$',
                r'^.*terminal width \d+.*$',
                r'^.*% Invalid input detected at.*$',
                r'^\s*\^\s*$',
                r'^.*set cli screen-length.*$',
                r'^.*set cli pager.*$',
                r'^.*no page.*$',
            ],
            'hp_aruba': [
                r'^.*Invalid input:.*$',
                r'^.*Cannot translate variable.*$',
                r'^.*no page.*#.*show.*$',  # Handles mashed commands
                r'^.*terminal length \d+.*Invalid input:.*$',
                r'^.*terminal width \d+.*Invalid input:.*$',
            ],
            'arista': [
                r'^.*terminal length \d+.*$',
                r'^.*terminal width \d+.*$',
                r'^.*% Invalid input.*$',
            ],
            'generic': [
                r'^.*Your previous successful login.*$',
                r'^.*was on \d{4}-\d{2}-\d{2}.*$',
                r'^.*from \d+\.\d+\.\d+\.\d+.*$',
                r'^\s*$',
            ]
        }

        self.load_device_info()

    def load_device_info(self):
        """Load device prompts and vendor information from fingerprint files."""
        if not self.fingerprints_dir.exists():
            print(f"Fingerprints directory not found: {self.fingerprints_dir}")
            return

        for json_file in self.fingerprints_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                device_name = json_file.stem
                prompt = data.get('detected_prompt', '').strip()
                hostname = data.get('hostname', '')

                # Determine vendor from netmiko_driver
                netmiko_driver = data.get('additional_info', {}).get('netmiko_driver', '')
                if 'cisco' in netmiko_driver:
                    vendor = 'cisco'
                elif 'hp' in netmiko_driver or 'procurve' in netmiko_driver:
                    vendor = 'hp_aruba'
                elif 'arista' in netmiko_driver:
                    vendor = 'arista'
                else:
                    vendor = 'generic'

                # Get device prompt
                if prompt and prompt != "#":
                    final_prompt = prompt
                elif hostname:
                    final_prompt = f"{hostname}#"
                else:
                    final_prompt = f"{device_name}#"

                self.device_prompts[device_name] = final_prompt
                self.device_vendors[device_name] = vendor

                print(f"Loaded {device_name} ({vendor}): '{final_prompt}'")

            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error reading {json_file}: {e}")

    def clean_content(self, content: str, vendor: str, prompt: str) -> str:
        """Clean content using vendor-specific patterns."""
        lines = content.split('\n')
        cleaned_lines = []

        # Get patterns for this vendor + generic patterns
        patterns = self.vendor_patterns.get('generic', [])
        patterns.extend(self.vendor_patterns.get(vendor, []))

        for line in lines:
            # Check if line matches noise patterns
            is_noise = False
            for pattern in patterns:
                if re.match(pattern, line, re.IGNORECASE):
                    is_noise = True
                    break

            # Special handling for HP/Aruba mashed commands
            if not is_noise and vendor == 'hp_aruba':
                if 'no page' in line and '#' in line and 'show' in line:
                    # Extract the prompt and command parts
                    if '#' in line:
                        parts = line.split('#', 1)
                        if len(parts) == 2:
                            prompt_part = parts[0] + '#'
                            command_part = parts[1].strip()
                            if command_part.startswith('show'):
                                cleaned_lines.append(prompt_part)
                                cleaned_lines.append(f"{prompt_part}{command_part}")
                            continue

            if not is_noise:
                cleaned_lines.append(line)

        # Remove duplicate prompts
        result_lines = []
        prev_line = ""
        for line in cleaned_lines:
            if not (line.strip() == prompt.strip() and prev_line.strip() == prompt.strip()):
                result_lines.append(line)
            prev_line = line

        # Clean up excessive empty lines
        result = '\n'.join(result_lines)
        result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
        return result.strip()

    def find_device_files(self, cli_dir: Path) -> Dict[str, List[Path]]:
        """Find all CLI files organized by device name."""
        device_files = {}

        # Get all .txt files recursively
        all_files = list(cli_dir.rglob("*.txt"))

        for file_path in all_files:
            device_name = file_path.stem

            # Match to known devices
            if device_name in self.device_prompts:
                if device_name not in device_files:
                    device_files[device_name] = []
                device_files[device_name].append(file_path)

        return device_files

    def process_file(self, file_path: Path, device_name: str, output_dir: Path = None) -> bool:
        """Process a single CLI file."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            if not content.strip():
                print(f"    {file_path.parent.name}/{file_path.name}: Empty, skipping")
                return True

            vendor = self.device_vendors.get(device_name, 'generic')
            prompt = self.device_prompts.get(device_name, '')

            original_size = len(content)
            cleaned_content = self.clean_content(content, vendor, prompt)
            cleaned_size = len(cleaned_content)

            print(f"    {file_path.parent.name}/{file_path.name} ({vendor}): {original_size} -> {cleaned_size} chars")

            # Determine output path
            if output_dir:
                relative_path = file_path.relative_to(file_path.parents[1])
                output_path = output_dir / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                output_path = file_path

            # Write cleaned content
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_content)

            return True

        except Exception as e:
            print(f"    Error processing {file_path}: {e}")
            return False

    def clean_all_files(self, cli_dir: Path, output_dir: Path = None) -> Tuple[int, int]:
        """Clean all CLI files."""
        device_files = self.find_device_files(cli_dir)

        if not device_files:
            print("No matching device files found!")
            return 0, 0

        total_files = sum(len(files) for files in device_files.values())
        successful = 0

        print(f"\nProcessing {len(device_files)} devices with {total_files} files...")
        print("-" * 60)

        for device_name, file_list in device_files.items():
            print(f"\nDevice: {device_name} ({len(file_list)} files)")

            device_success = 0
            for file_path in file_list:
                if self.process_file(file_path, device_name, output_dir):
                    device_success += 1
                    successful += 1

            print(f"  Summary: {device_success}/{len(file_list)} files processed successfully")

        return successful, total_files


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Multi-vendor CLI output cleaner")
    parser.add_argument("--fingerprints-dir", required=True, help="Directory with fingerprint JSON files")
    parser.add_argument("--cli-dir", required=True, help="Directory with CLI output files")
    parser.add_argument("--output-dir", help="Output directory (overwrites originals if not specified)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")

    args = parser.parse_args()

    # Initialize cleaner
    cleaner = MultiVendorCLICleaner(args.fingerprints_dir)

    if not cleaner.device_prompts:
        print("No device prompts loaded!")
        return

    cli_dir = Path(args.cli_dir)
    output_dir = Path(args.output_dir) if args.output_dir else None

    if args.dry_run:
        device_files = cleaner.find_device_files(cli_dir)
        total_files = sum(len(files) for files in device_files.values())

        print(f"\n--- DRY RUN ---")
        print(f"Would process {len(device_files)} devices with {total_files} files")

        for device_name, file_list in list(device_files.items())[:5]:  # Show first 5
            vendor = cleaner.device_vendors.get(device_name, 'unknown')
            dirs = sorted(set(f.parent.name for f in file_list))
            print(f"  {device_name} ({vendor}): {len(file_list)} files in {dirs}")

        if len(device_files) > 5:
            print(f"  ... and {len(device_files) - 5} more devices")
        return

    # Process files
    successful, total = cleaner.clean_all_files(cli_dir, output_dir)

    # Summary
    print("\n" + "=" * 60)
    print("CLEANUP SUMMARY")
    print("=" * 60)
    print(f"Total files processed: {total}")
    print(f"Successfully cleaned: {successful}")

    if successful < total:
        print(f"Files with errors: {total - successful}")

    if output_dir:
        print(f"Cleaned files saved to: {output_dir}")
    else:
        print("Original files were overwritten")


if __name__ == "__main__":
    main()