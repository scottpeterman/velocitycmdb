#!/usr/bin/env python3
"""
Network Capture Gap Report Generator

Analyzes YAML inventory against captured data and generates an HTML gap report
showing which devices have successful captures and which are missing data.
"""

import yaml
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import argparse


class NetworkGapReporter:
    def __init__(self, yaml_file, capture_dir, fingerprints_dir):
        self.yaml_file = Path(yaml_file)
        self.capture_dir = Path(capture_dir)
        self.fingerprints_dir = Path(fingerprints_dir)
        self.inventory_data = {}
        self.capture_types = []
        self.device_status = defaultdict(dict)

    def load_inventory(self):
        """Load and parse the YAML inventory file."""
        print(f"Loading inventory from {self.yaml_file}")

        with open(self.yaml_file, 'r') as f:
            self.inventory_data = yaml.safe_load(f)

        print(f"Loaded {len(self.inventory_data)} site folders")

    def discover_capture_types(self):
        """Discover available capture types from directory structure."""
        if not self.capture_dir.exists():
            print(f"Capture directory not found: {self.capture_dir}")
            return

        self.capture_types = []
        for item in self.capture_dir.iterdir():
            if item.is_dir():
                self.capture_types.append(item.name)

        self.capture_types.sort()
        print(f"Found {len(self.capture_types)} capture types: {', '.join(self.capture_types)}")

    def analyze_devices(self):
        """Analyze each device's capture status (only devices with fingerprints)."""
        print("Analyzing device capture status...")

        total_devices_in_yaml = 0
        devices_with_fingerprints = 0

        for site in self.inventory_data:
            folder_name = site['folder_name']

            for session in site['sessions']:
                device_name = session['display_name']
                total_devices_in_yaml += 1

                # Check for fingerprint file first - skip if doesn't exist
                fingerprint_file = self.fingerprints_dir / f"{device_name}.json"
                if not fingerprint_file.exists():
                    continue  # Skip devices without fingerprints

                devices_with_fingerprints += 1

                # Initialize device status
                device_info = {
                    'folder': folder_name,
                    'host': session.get('host', ''),
                    'vendor': session.get('Vendor', ''),
                    'model': session.get('Model', ''),
                    'fingerprint': True,  # We know it exists
                    'captures': {},
                    'total_captures': 0,
                    'missing_captures': 0
                }

                # Load fingerprint data for vendor info
                try:
                    with open(fingerprint_file, 'r') as f:
                        fp_data = json.load(f)
                        if not device_info['vendor']:
                            # Extract vendor from fingerprint if not in YAML
                            driver = fp_data.get('additional_info', {}).get('netmiko_driver', '')
                            if 'cisco' in driver:
                                device_info['vendor'] = 'Cisco'
                            elif 'hp' in driver or 'procurve' in driver:
                                device_info['vendor'] = 'HP/Aruba'
                            elif 'arista' in driver:
                                device_info['vendor'] = 'Arista'
                except Exception as e:
                    print(f"Error reading fingerprint for {device_name}: {e}")

                # Check each capture type
                for capture_type in self.capture_types:
                    capture_file = self.capture_dir / capture_type / f"{device_name}.txt"
                    has_capture = capture_file.exists()

                    device_info['captures'][capture_type] = has_capture
                    if has_capture:
                        device_info['total_captures'] += 1
                    else:
                        device_info['missing_captures'] += 1

                self.device_status[device_name] = device_info

        print(f"Total devices in YAML: {total_devices_in_yaml}")
        print(f"Network devices (with fingerprints): {devices_with_fingerprints}")
        print(f"Non-network devices (PDUs, UPS, etc): {total_devices_in_yaml - devices_with_fingerprints}")
        print(f"Analyzed {len(self.device_status)} network devices")

    def generate_vendor_coverage_matrix(self):
        """Generate vendor coverage analysis by capture type."""
        coverage_data = {
            'vendors': set(),
            'by_capture': defaultdict(lambda: {'vendors': {}, 'vendor_count': 0})
        }

        # Collect all vendors
        for device_info in self.device_status.values():
            vendor = device_info['vendor']
            if vendor and vendor.strip():
                coverage_data['vendors'].add(vendor)

        # Analyze coverage by capture type
        for capture_type in self.capture_types:
            vendor_stats = defaultdict(lambda: {'success': 0, 'total': 0})

            for device_info in self.device_status.values():
                vendor = device_info['vendor'] or 'Unknown'
                vendor_stats[vendor]['total'] += 1

                if device_info['captures'].get(capture_type, False):
                    vendor_stats[vendor]['success'] += 1

            coverage_data['by_capture'][capture_type]['vendors'] = dict(vendor_stats)
            coverage_data['by_capture'][capture_type]['vendor_count'] = len([
                v for v, stats in vendor_stats.items()
                if stats['success'] > 0 and stats['total'] > 0
            ])

        return coverage_data

    def generate_html_report(self, output_file):
        """Generate comprehensive HTML gap report."""
        print(f"Generating HTML report: {output_file}")

        # Calculate summary statistics
        total_devices = len(self.device_status)

        # Group devices by folder for the report
        devices_by_folder = defaultdict(list)
        for device_name, device_info in self.device_status.items():
            devices_by_folder[device_info['folder']].append((device_name, device_info))

        # Sort devices within each folder
        for folder in devices_by_folder:
            devices_by_folder[folder].sort(key=lambda x: x[0])

        # Generate vendor coverage matrix
        vendor_coverage = self.generate_vendor_coverage_matrix()

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Network Capture Gap Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 30px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
            padding: 10px;
            background-color: #ecf0f1;
            border-radius: 5px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            font-size: 2em;
        }}
        .summary-card p {{
            margin: 0;
            opacity: 0.9;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            background: white;
        }}
        th, td {{
            padding: 12px 8px;
            text-align: left;
            border-bottom: 1px solid #ddd;
            font-size: 11px;
        }}
        th {{
            background-color: #34495e;
            color: white;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}
        tr:nth-child(even) {{
            background-color: #f8f9fa;
        }}
        tr:hover {{
            background-color: #e8f4f8;
        }}
        .device-name {{
            font-weight: bold;
            color: #2c3e50;
            min-width: 150px;
        }}
        .status-yes {{
            background-color: #27ae60;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            text-align: center;
            font-weight: bold;
        }}
        .status-no {{
            background-color: #e74c3c;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            text-align: center;
            font-weight: bold;
        }}
        .vendor-cisco {{ background-color: #1f4e79; color: white; padding: 2px 6px; border-radius: 3px; }}
        .vendor-hp {{ background-color: #0096d6; color: white; padding: 2px 6px; border-radius: 3px; }}
        .vendor-arista {{ background-color: #ff6600; color: white; padding: 2px 6px; border-radius: 3px; }}
        .vendor-palo {{ background-color: #fa582d; color: white; padding: 2px 6px; border-radius: 3px; }}
        .vendor-other {{ background-color: #95a5a6; color: white; padding: 2px 6px; border-radius: 3px; }}
        .vendor-unknown {{ background-color: #bdc3c7; color: #2c3e50; padding: 2px 6px; border-radius: 3px; }}
        .capture-score {{
            font-weight: bold;
            padding: 4px 8px;
            border-radius: 4px;
            text-align: center;
        }}
        .score-high {{ background-color: #27ae60; color: white; }}
        .score-medium {{ background-color: #f39c12; color: white; }}
        .score-low {{ background-color: #e74c3c; color: white; }}
        .score-zero {{ background-color: #95a5a6; color: white; }}
        .timestamp {{
            color: #7f8c8d;
            font-style: italic;
            margin-top: 20px;
            text-align: center;
        }}
        .folder-header {{
            background: linear-gradient(90deg, #2c3e50 0%, #3498db 100%);
            color: white;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0 10px 0;
            font-weight: bold;
        }}
        .table-container {{
            overflow-x: auto;
            margin-bottom: 30px;
        }}
        .legend {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .legend h4 {{
            margin-top: 0;
            color: #2c3e50;
        }}
        .legend-item {{
            display: inline-block;
            margin-right: 15px;
            margin-bottom: 5px;
        }}
        .coverage-matrix {{
            margin-bottom: 40px;
        }}
        .coverage-table th {{
            background-color: #2c3e50;
            color: white;
            text-align: center;
            font-size: 12px;
            padding: 8px;
        }}
        .coverage-table td {{
            text-align: center;
            font-size: 11px;
            padding: 6px;
        }}
        .coverage-universal {{ background-color: #e8f5e8; }}
        .coverage-partial {{ background-color: #fff3cd; }}
        .coverage-missing {{ background-color: #f8d7da; }}
        .coverage-percentage {{
            font-weight: bold;
            padding: 3px 6px;
            border-radius: 3px;
            font-size: 10px;
        }}
        .pct-high {{ background-color: #28a745; color: white; }}
        .pct-medium {{ background-color: #ffc107; color: black; }}
        .pct-low {{ background-color: #dc3545; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Network Capture Gap Report</h1>

        <div class="summary">
            <div class="summary-card">
                <h3>{total_devices}</h3>
                <p>Network Devices</p>
            </div>
            <div class="summary-card">
                <h3>{len(self.capture_types)}</h3>
                <p>Capture Types</p>
            </div>
            <div class="summary-card">
                <h3>{sum(d['total_captures'] for d in self.device_status.values())}</h3>
                <p>Total Successful Captures</p>
            </div>
            <div class="summary-card">
                <h3>{len([d for d in self.device_status.values() if d['total_captures'] == len(self.capture_types)])}</h3>
                <p>100% Complete Devices</p>
            </div>
        </div>

        <div class="legend">
            <h4>Legend</h4>
            <div class="legend-item"><span class="status-yes">✓</span> Data Available</div>
            <div class="legend-item"><span class="status-no">✗</span> Missing Data</div>
            <div class="legend-item"><span class="vendor-cisco">Cisco</span></div>
            <div class="legend-item"><span class="vendor-hp">HP/Aruba</span></div>
            <div class="legend-item"><span class="vendor-arista">Arista</span></div>
            <div class="legend-item"><span class="vendor-palo">Palo Alto</span></div>
            <div class="legend-item"><span class="vendor-other">Other</span></div>
            <div class="legend-item"><span class="vendor-unknown">Unknown</span></div>
            <p><em>Note: Only showing network devices with fingerprint files. PDUs, UPS devices, and other infrastructure are excluded.</em></p>
        </div>

        <div class="coverage-matrix">
            <h2>Vendor Coverage Matrix by Capture Type</h2>
            <div class="table-container">
                <table class="coverage-table">
                    <thead>
                        <tr>
                            <th>Capture Type</th>
                            <th>Total Success</th>"""

        # Add vendor columns
        for vendor in sorted(vendor_coverage['vendors']):
            html_content += f'<th>{vendor}</th>'

        html_content += """
                            <th>Coverage Level</th>
                        </tr>
                    </thead>
                    <tbody>"""

        # Add rows for each capture type
        for capture_type in sorted(self.capture_types):
            total_success = sum(1 for d in self.device_status.values() if d['captures'].get(capture_type, False))
            success_percentage = (total_success / total_devices * 100) if total_devices > 0 else 0

            # Determine overall percentage class
            if success_percentage >= 80:
                pct_class = 'pct-high'
            elif success_percentage >= 50:
                pct_class = 'pct-medium'
            else:
                pct_class = 'pct-low'

            # Determine coverage level
            vendor_count = vendor_coverage['by_capture'][capture_type]['vendor_count']
            total_vendors = len(vendor_coverage['vendors'])
            if vendor_count == total_vendors:
                coverage_class = 'coverage-universal'
                coverage_text = 'Universal'
            elif vendor_count > total_vendors / 2:
                coverage_class = 'coverage-partial'
                coverage_text = 'Partial'
            else:
                coverage_class = 'coverage-missing'
                coverage_text = 'Limited'

            html_content += f"""
                        <tr class="{coverage_class}">
                            <td><strong>{capture_type}</strong></td>
                            <td><span class="coverage-percentage {pct_class}">{total_success}/{total_devices} ({success_percentage:.1f}%)</span></td>"""

            # Add vendor-specific success rates
            for vendor in sorted(vendor_coverage['vendors']):
                vendor_data = vendor_coverage['by_capture'][capture_type]['vendors'].get(vendor,
                                                                                         {'success': 0, 'total': 0})
                if vendor_data['total'] > 0:
                    vendor_pct = (vendor_data['success'] / vendor_data['total']) * 100
                    status_text = f"{vendor_data['success']}/{vendor_data['total']} ({vendor_pct:.0f}%)"
                    if vendor_pct >= 80:
                        vendor_class = 'status-yes'
                    else:
                        vendor_class = 'status-no'
                else:
                    status_text = "N/A"
                    vendor_class = 'status-no'

                html_content += f'<td><span class="{vendor_class}" style="font-size: 9px;">{status_text}</span></td>'

            html_content += f'<td><strong>{coverage_text}</strong></td></tr>'

        html_content += """
                    </tbody>
                </table>
            </div>
        </div>"""

        # Generate table for each folder
        for folder_name in sorted(devices_by_folder.keys()):
            devices = devices_by_folder[folder_name]

            html_content += f"""
        <div class="folder-header">
            {folder_name} ({len(devices)} devices)
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Device Name</th>
                        <th>Host</th>
                        <th>Vendor</th>"""

            # Add column headers for each capture type
            for capture_type in self.capture_types:
                html_content += f"<th>{capture_type}</th>"

            html_content += """
                        <th>Score</th>
                    </tr>
                </thead>
                <tbody>"""

            # Add rows for each device in this folder
            for device_name, device_info in devices:
                # Determine vendor class
                vendor = device_info['vendor'].lower()
                if 'cisco' in vendor:
                    vendor_class = 'vendor-cisco'
                elif 'hp' in vendor or 'aruba' in vendor:
                    vendor_class = 'vendor-hp'
                elif 'arista' in vendor:
                    vendor_class = 'vendor-arista'
                elif 'palo' in vendor:
                    vendor_class = 'vendor-palo'
                elif vendor and vendor.strip():
                    vendor_class = 'vendor-other'
                else:
                    vendor_class = 'vendor-unknown'
                    vendor = 'Unknown'

                # Calculate capture score
                if len(self.capture_types) > 0:
                    capture_percentage = (device_info['total_captures'] / len(self.capture_types)) * 100
                    if capture_percentage >= 80:
                        score_class = 'score-high'
                    elif capture_percentage >= 50:
                        score_class = 'score-medium'
                    elif capture_percentage > 0:
                        score_class = 'score-low'
                    else:
                        score_class = 'score-zero'
                    score_text = f"{device_info['total_captures']}/{len(self.capture_types)}"
                else:
                    score_class = 'score-zero'
                    score_text = "0/0"

                html_content += f"""
                    <tr>
                        <td class="device-name">{device_name}</td>
                        <td>{device_info['host']}</td>
                        <td><span class="{vendor_class}">{vendor}</span></td>"""

                # Add capture status for each type
                for capture_type in self.capture_types:
                    has_capture = device_info['captures'].get(capture_type, False)
                    status_text = "✓" if has_capture else "✗"
                    status_class = "status-yes" if has_capture else "status-no"
                    html_content += f'<td><span class="{status_class}">{status_text}</span></td>'

                html_content += f"""
                        <td><span class="capture-score {score_class}">{score_text}</span></td>
                    </tr>"""

            html_content += """
                </tbody>
            </table>
        </div>"""

        html_content += f"""

        <div class="timestamp">
            Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>"""

        # Write the HTML file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"HTML report generated successfully: {output_file}")

    def generate_summary_stats(self):
        """Print summary statistics to console."""
        total_devices = len(self.device_status)
        if total_devices == 0:
            print("No network devices found with fingerprints")
            return

        # Calculate capture statistics
        capture_stats = {}
        for capture_type in self.capture_types:
            count = sum(1 for d in self.device_status.values() if d['captures'].get(capture_type, False))
            capture_stats[capture_type] = count

        print(f"\n=== SUMMARY STATISTICS ===")
        print(f"Network devices analyzed: {total_devices}")
        print(f"(Note: Only devices with fingerprint files are included)")

        print(f"\n=== CAPTURE TYPE STATISTICS ===")
        for capture_type, count in sorted(capture_stats.items()):
            percentage = (count / total_devices) * 100 if total_devices > 0 else 0
            print(f"{capture_type:20s}: {count:3d}/{total_devices} ({percentage:5.1f}%)")

        # Identify devices with zero captures
        zero_capture_devices = [name for name, info in self.device_status.items() if info['total_captures'] == 0]
        if zero_capture_devices:
            print(f"\n=== DEVICES WITH NO CAPTURES ({len(zero_capture_devices)}) ===")
            for device in sorted(zero_capture_devices):
                folder = self.device_status[device]['folder']
                host = self.device_status[device]['host']
                print(f"  {device:30s} ({folder}) - {host}")

        # Show devices with perfect capture rates
        perfect_devices = [name for name, info in self.device_status.items() if
                           info['total_captures'] == len(self.capture_types) and len(self.capture_types) > 0]
        print(f"\n=== DEVICES WITH 100% CAPTURE SUCCESS ({len(perfect_devices)}) ===")
        if perfect_devices:
            for device in sorted(perfect_devices):
                folder = self.device_status[device]['folder']
                vendor = self.device_status[device]['vendor']
                print(f"  {device:30s} ({folder}) - {vendor}")
        else:
            print("  None - all devices have at least one missing capture type")


def main():
    parser = argparse.ArgumentParser(description="Generate network capture gap report")
    parser.add_argument("--yaml", "-y", required=True, help="Path to sessions.yaml inventory file")
    parser.add_argument("--capture-dir", "-c", required=True, help="Path to capture directory")
    parser.add_argument("--fingerprints-dir", "-f", required=True, help="Path to fingerprints directory")
    parser.add_argument("--output", "-o", default="network_gap_report.html", help="Output HTML file name")
    parser.add_argument("--stats-only", "-s", action="store_true", help="Only print statistics, don't generate HTML")

    args = parser.parse_args()

    # Create reporter
    reporter = NetworkGapReporter(args.yaml, args.capture_dir, args.fingerprints_dir)

    # Load data and analyze
    reporter.load_inventory()
    reporter.discover_capture_types()
    reporter.analyze_devices()

    # Generate output
    if args.stats_only:
        reporter.generate_summary_stats()
    else:
        reporter.generate_html_report(args.output)
        reporter.generate_summary_stats()


if __name__ == "__main__":
    main()