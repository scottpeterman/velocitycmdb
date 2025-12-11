#!/usr/bin/env python3
"""
Uptime Report Generator
Generates a portable HTML report with charts from CLI uptime JSON data.
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def generate_html_report(data: Dict, output_file: str):
    """Generate standalone HTML report with embedded charts"""

    devices = data.get('devices', [])
    successful = [d for d in devices if d.get('cli_success')]
    failed = [d for d in devices if not d.get('cli_success')]

    # Calculate uptime ranges
    ranges = {
        '< 60 days': [],
        '60 days - 1 year': [],
        '1-3 years': [],
        '> 3 years': []
    }

    for device in successful:
        uptime_days = device.get('uptime_days', 0)
        if uptime_days < 60:
            ranges['< 60 days'].append(device)
        elif uptime_days < 365:
            ranges['60 days - 1 year'].append(device)
        elif uptime_days < 1095:  # 3 years
            ranges['1-3 years'].append(device)
        else:
            ranges['> 3 years'].append(device)

    # Stats
    total = len(devices)
    success_count = len(successful)
    success_pct = (success_count / total * 100) if total > 0 else 0

    uptimes = [d.get('uptime_days', 0) for d in successful if d.get('uptime_days')]
    avg_uptime = sum(uptimes) / len(uptimes) if uptimes else 0
    max_uptime = max(uptimes) if uptimes else 0
    min_uptime = min(uptimes) if uptimes else 0

    # Vendor breakdown
    vendors = {}
    for device in successful:
        vendor = device.get('vendor', 'Unknown')
        if vendor not in vendors:
            vendors[vendor] = []
        vendors[vendor].append(device)

    # Chart data
    range_counts = [len(ranges[r]) for r in ['< 60 days', '60 days - 1 year', '1-3 years', '> 3 years']]
    range_labels = ['< 60 days', '60d - 1yr', '1-3 years', '> 3 years']

    vendor_names = list(vendors.keys())
    vendor_counts = [len(vendors[v]) for v in vendor_names]

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Network Device Uptime Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}

        .header h1 {{
            color: #2d3748;
            font-size: 32px;
            margin-bottom: 10px;
        }}

        .header .meta {{
            color: #718096;
            font-size: 14px;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        .stat-card .label {{
            color: #718096;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}

        .stat-card .value {{
            color: #2d3748;
            font-size: 36px;
            font-weight: bold;
        }}

        .stat-card .subvalue {{
            color: #a0aec0;
            font-size: 14px;
            margin-top: 5px;
        }}

        .stat-card.success {{ border-left: 4px solid #48bb78; }}
        .stat-card.warning {{ border-left: 4px solid #ed8936; }}
        .stat-card.info {{ border-left: 4px solid #4299e1; }}
        .stat-card.danger {{ border-left: 4px solid #f56565; }}

        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .chart-card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        .chart-card h2 {{
            color: #2d3748;
            font-size: 18px;
            margin-bottom: 20px;
        }}

        .chart-container {{
            position: relative;
            height: 300px;
        }}

        .table-card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}

        .table-card h2 {{
            color: #2d3748;
            font-size: 18px;
            margin-bottom: 20px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
        }}

        th {{
            background: #f7fafc;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #4a5568;
            border-bottom: 2px solid #e2e8f0;
            font-size: 14px;
            cursor: pointer;
            user-select: none;
            position: relative;
        }}

        th:hover {{
            background: #edf2f7;
        }}

        th.sortable:after {{
            content: ' ⇅';
            color: #cbd5e0;
            font-size: 12px;
        }}

        th.sort-asc:after {{
            content: ' ▲';
            color: #4299e1;
        }}

        th.sort-desc:after {{
            content: ' ▼';
            color: #4299e1;
        }}

        td {{
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
            color: #2d3748;
            font-size: 14px;
        }}

        tr:hover {{
            background: #f7fafc;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}

        .badge.critical {{ background: #fed7d7; color: #c53030; }}
        .badge.warning {{ background: #feebc8; color: #c05621; }}
        .badge.good {{ background: #c6f6d5; color: #2f855a; }}
        .badge.excellent {{ background: #bee3f8; color: #2c5282; }}

        .footer {{
            text-align: center;
            color: white;
            margin-top: 30px;
            font-size: 14px;
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}
            .chart-container {{
                height: 250px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1> Network Device Uptime Report</h1>
            <div class="meta">
                Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 
                Collection: {data.get('collection_timestamp', 'Unknown')} | 
                Method: CLI (SSH)
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card success">
                <div class="label">Total Devices</div>
                <div class="value">{total}</div>
                <div class="subvalue">{success_count} successful</div>
            </div>

            <div class="stat-card info">
                <div class="label">Success Rate</div>
                <div class="value">{success_pct:.1f}%</div>
                <div class="subvalue">{len(failed)} failed</div>
            </div>

            <div class="stat-card warning">
                <div class="label">Average Uptime</div>
                <div class="value">{avg_uptime:.0f}</div>
                <div class="subvalue">days</div>
            </div>

            <div class="stat-card danger">
                <div class="label">Max Uptime</div>
                <div class="value">{max_uptime:.0f}</div>
                <div class="subvalue">days ({max_uptime / 365:.1f} years)</div>
            </div>
        </div>

        <div class="charts-grid">
            <div class="chart-card">
                <h2> Uptime Distribution</h2>
                <div class="chart-container">
                    <canvas id="uptimeChart"></canvas>
                </div>
            </div>

            <div class="chart-card">
                <h2> Vendor Breakdown</h2>
                <div class="chart-container">
                    <canvas id="vendorChart"></canvas>
                </div>
            </div>
        </div>

        <div class="table-card">
            <h2>⚠️ Devices Requiring Attention</h2>
            <table id="attentionTable">
                <thead>
                    <tr>
                        <th class="sortable" data-sort="device">Device</th>
                        <th class="sortable" data-sort="site">Site</th>
                        <th class="sortable" data-sort="vendor">Vendor</th>
                        <th class="sortable" data-sort="model">Model</th>
                        <th>Uptime</th>
                        <th class="sortable" data-sort="days">Days</th>
                        <th class="sortable" data-sort="status">Status</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add devices needing attention (> 3 years or < 60 days)
    attention_devices = ranges['> 3 years'] + ranges['< 60 days']
    attention_devices.sort(key=lambda x: x.get('uptime_days', 0), reverse=True)

    for device in attention_devices[:20]:  # Top 20
        uptime_days = device.get('uptime_days', 0)
        badge_class = 'critical' if uptime_days > 1095 else 'warning' if uptime_days < 60 else 'good'
        status = 'Needs Patching' if uptime_days > 1095 else 'Recently Rebooted' if uptime_days < 60 else 'Normal'

        html += f"""
                    <tr>
                        <td data-value="{device.get('hostname', 'Unknown')}"><strong>{device.get('hostname', 'Unknown')}</strong></td>
                        <td data-value="{device.get('site_code', 'N/A')}">{device.get('site_code', 'N/A')}</td>
                        <td data-value="{device.get('vendor', 'Unknown')}">{device.get('vendor', 'Unknown')}</td>
                        <td data-value="{device.get('model', 'N/A')}">{device.get('model', 'N/A')}</td>
                        <td>{device.get('uptime_formatted', 'N/A')}</td>
                        <td data-value="{uptime_days}">{uptime_days:.0f}</td>
                        <td data-value="{status}"><span class="badge {badge_class}">{status}</span></td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>

        <div class="table-card">
            <h2> All Devices</h2>
            <table id="allDevicesTable">
                <thead>
                    <tr>
                        <th class="sortable" data-sort="device">Device</th>
                        <th class="sortable" data-sort="site">Site</th>
                        <th class="sortable" data-sort="vendor">Vendor</th>
                        <th class="sortable" data-sort="model">Model</th>
                        <th>OS Version</th>
                        <th>Uptime</th>
                        <th class="sortable" data-sort="days">Days</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add all successful devices
    sorted_devices = sorted(successful, key=lambda x: x.get('uptime_days', 0), reverse=True)
    for device in sorted_devices:
        html += f"""
                    <tr>
                        <td data-value="{device.get('hostname', 'Unknown')}"><strong>{device.get('hostname', 'Unknown')}</strong></td>
                        <td data-value="{device.get('site_code', 'N/A')}">{device.get('site_code', 'N/A')}</td>
                        <td data-value="{device.get('vendor', 'Unknown')}">{device.get('vendor', 'Unknown')}</td>
                        <td data-value="{device.get('model', 'N/A')}">{device.get('model', 'N/A')}</td>
                        <td>{device.get('os_version', 'N/A')}</td>
                        <td>{device.get('uptime_formatted', 'N/A')}</td>
                        <td data-value="{device.get('uptime_days', 0)}">{device.get('uptime_days', 0):.0f}</td>
                    </tr>
"""

    # JavaScript section with proper string formatting
    html += """
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>Network Uptime Report | Generated from CLI uptime collection</p>
        </div>
    </div>

    <script>
        // Uptime Distribution Chart
        const uptimeCtx = document.getElementById('uptimeChart').getContext('2d');
        new Chart(uptimeCtx, {{
            type: 'bar',
            data: {{
                labels: {range_labels_json},
                datasets: [{{
                    label: 'Devices',
                    data: {range_counts_json},
                    backgroundColor: [
                        'rgba(237, 137, 54, 0.8)',
                        'rgba(72, 187, 120, 0.8)',
                        'rgba(66, 153, 225, 0.8)',
                        'rgba(245, 101, 101, 0.8)'
                    ],
                    borderColor: [
                        'rgb(237, 137, 54)',
                        'rgb(72, 187, 120)',
                        'rgb(66, 153, 225)',
                        'rgb(245, 101, 101)'
                    ],
                    borderWidth: 2
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                let total = {success_count};
                                let value = context.parsed.y;
                                let percentage = ((value / total) * 100).toFixed(1);
                                return value + ' devices (' + percentage + '%)';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        ticks: {{
                            stepSize: 1
                        }}
                    }}
                }}
            }}
        }});

        // Vendor Chart
        const vendorCtx = document.getElementById('vendorChart').getContext('2d');
        new Chart(vendorCtx, {{
            type: 'doughnut',
            data: {{
                labels: {vendor_names_json},
                datasets: [{{
                    data: {vendor_counts_json},
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.8)',
                        'rgba(237, 137, 54, 0.8)',
                        'rgba(72, 187, 120, 0.8)',
                        'rgba(245, 101, 101, 0.8)',
                        'rgba(66, 153, 225, 0.8)'
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                let total = {success_count};
                                let value = context.parsed;
                                let percentage = ((value / total) * 100).toFixed(1);
                                return context.label + ': ' + value + ' (' + percentage + '%)';
                            }}
                        }}
                    }}
                }}
            }}
        }});

        // Table sorting functionality
        function sortTable(table, columnIndex, direction) {{
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            rows.sort((a, b) => {{
                const aCell = a.children[columnIndex];
                const bCell = b.children[columnIndex];

                // Get data-value if exists, otherwise use text
                let aValue = aCell.dataset.value || aCell.textContent.trim();
                let bValue = bCell.dataset.value || bCell.textContent.trim();

                // Try to parse as numbers
                const aNum = parseFloat(aValue);
                const bNum = parseFloat(bValue);

                if (!isNaN(aNum) && !isNaN(bNum)) {{
                    return direction === 'asc' ? aNum - bNum : bNum - aNum;
                }}

                // String comparison
                return direction === 'asc' 
                    ? aValue.localeCompare(bValue)
                    : bValue.localeCompare(aValue);
            }});

            // Re-append rows
            rows.forEach(row => tbody.appendChild(row));
        }}

        function initTableSorting(tableId) {{
            const table = document.getElementById(tableId);
            const headers = table.querySelectorAll('th.sortable');

            headers.forEach((header, index) => {{
                let currentDirection = 'desc';

                header.addEventListener('click', () => {{
                    // Remove sort classes from all headers
                    headers.forEach(h => {{
                        h.classList.remove('sort-asc', 'sort-desc');
                    }});

                    // Toggle direction
                    currentDirection = currentDirection === 'asc' ? 'desc' : 'asc';

                    // Add appropriate class
                    header.classList.add(currentDirection === 'asc' ? 'sort-asc' : 'sort-desc');

                    // Sort the table
                    sortTable(table, index, currentDirection);
                }});
            }});
        }}

        // Initialize sorting for both tables
        initTableSorting('attentionTable');
        initTableSorting('allDevicesTable');
    </script>
</body>
</html>
""".format(
        range_labels_json=json.dumps(range_labels),
        range_counts_json=json.dumps(range_counts),
        vendor_names_json=json.dumps(vendor_names),
        vendor_counts_json=json.dumps(vendor_counts),
        success_count=success_count
    )

    # Write to file
    with open(output_file, 'w') as f:
        f.write(html)

    print(f"✓ HTML report generated: {output_file}")
    print(f"  Total devices: {total}")
    print(f"  Successful: {success_count}")
    print(f"  < 60 days: {len(ranges['< 60 days'])}")
    print(f"  60d - 1yr: {len(ranges['60 days - 1 year'])}")
    print(f"  1-3 years: {len(ranges['1-3 years'])}")
    print(f"  > 3 years: {len(ranges['> 3 years'])}")


def main():
    parser = argparse.ArgumentParser(description='Generate HTML uptime report from JSON')
    parser.add_argument('input_json', help='Input JSON file (from CLI uptime collector)')
    parser.add_argument('-o', '--output', default='uptime_report.html',
                        help='Output HTML file (default: uptime_report.html)')

    args = parser.parse_args()

    if not Path(args.input_json).exists():
        print(f"Error: Input file not found: {args.input_json}")
        return 1

    with open(args.input_json, 'r') as f:
        data = json.load(f)

    generate_html_report(data, args.output)

    return 0


if __name__ == '__main__':
    sys.exit(main())