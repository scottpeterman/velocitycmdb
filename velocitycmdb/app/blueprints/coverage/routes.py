from flask import render_template, request, jsonify, current_app
from collections import defaultdict
from datetime import datetime

from . import coverage_bp


class DatabaseCoverageReporter:
    """Database-only coverage reporter - no file system dependencies"""

    def __init__(self):
        self.capture_types = []
        self.device_status = {}

    def get_db_connection(self):
        """Get database connection"""
        from velocitycmdb.app.utils.database import get_db_connection
        return get_db_connection()

    def discover_capture_types(self):
        """Discover available capture types from capture_snapshots table"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()

            # Get distinct capture types from capture_snapshots
            cursor.execute("""
                SELECT DISTINCT capture_type 
                FROM capture_snapshots 
                ORDER BY capture_type
            """)

            self.capture_types = [row['capture_type'] for row in cursor.fetchall()]

        return self.capture_types

    def analyze_devices(self):
        """Analyze device capture coverage from database"""
        with self.get_db_connection() as conn:
            cursor = conn.cursor()

            # Get all devices that have at least one fingerprint
            cursor.execute("""
                SELECT DISTINCT
                    d.id,
                    d.name,
                    d.normalized_name,
                    d.site_code,
                    s.name as site_name,
                    v.name as vendor_name,
                    d.model
                FROM devices d
                LEFT JOIN sites s ON d.site_code = s.code
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE EXISTS (
                    SELECT 1 FROM capture_snapshots cs 
                    WHERE cs.device_id = d.id
                )
                ORDER BY d.name
            """)

            devices = cursor.fetchall()

            current_app.logger.info(f"Found {len(devices)} devices with fingerprints")

            # For each device, check captures
            for device in devices:
                device_id = device['id']
                device_name = device['name']

                # Initialize device info
                device_info = {
                    'device_id': device_id,
                    'folder': device['site_name'] or 'Unknown',
                    'host': '',  # Not stored in DB currently
                    'vendor': device['vendor_name'] or 'Unknown',
                    'model': device['model'] or 'Unknown',
                    'fingerprint': True,
                    'captures': {},
                    'total_captures': 0,
                    'missing_captures': 0
                }

                # Check each capture type in capture_snapshots
                for capture_type in self.capture_types:
                    cursor.execute("""
                        SELECT COUNT(*) as count 
                        FROM capture_snapshots 
                        WHERE device_id = ? AND capture_type = ?
                    """, (device_id, capture_type))

                    result = cursor.fetchone()
                    has_capture = result['count'] > 0

                    device_info['captures'][capture_type] = has_capture
                    if has_capture:
                        device_info['total_captures'] += 1
                    else:
                        device_info['missing_captures'] += 1

                self.device_status[device_name] = device_info

            current_app.logger.info(f"Analyzed {len(self.device_status)} devices")

    def get_summary_stats(self):
        """Generate summary statistics"""
        total_devices = len(self.device_status)
        if total_devices == 0:
            return {
                'total_devices': 0,
                'capture_types_count': 0,
                'total_successful_captures': 0,
                'perfect_capture_count': 0,
                'zero_capture_count': 0,
                'capture_stats': {},
                'perfect_devices': [],
                'zero_capture_devices': []
            }

        # Calculate capture statistics
        capture_stats = {}
        for capture_type in self.capture_types:
            count = sum(1 for d in self.device_status.values() if d['captures'].get(capture_type, False))
            capture_stats[capture_type] = {
                'count': count,
                'total': total_devices,
                'percentage': (count / total_devices) * 100 if total_devices > 0 else 0
            }

        # Perfect capture devices
        perfect_devices = [
            name for name, info in self.device_status.items()
            if info['total_captures'] == len(self.capture_types) and len(self.capture_types) > 0
        ]

        # Zero capture devices
        zero_capture_devices = [
            name for name, info in self.device_status.items()
            if info['total_captures'] == 0
        ]

        return {
            'total_devices': total_devices,
            'capture_types_count': len(self.capture_types),
            'total_successful_captures': sum(d['total_captures'] for d in self.device_status.values()),
            'perfect_capture_count': len(perfect_devices),
            'zero_capture_count': len(zero_capture_devices),
            'capture_stats': capture_stats,
            'perfect_devices': perfect_devices,
            'zero_capture_devices': zero_capture_devices
        }

    def generate_vendor_coverage_matrix(self):
        """Generate vendor coverage analysis by capture type"""
        coverage_data = {
            'vendors': [],
            'by_capture': {}
        }

        # Collect all vendors
        vendors_set = set()
        for device_info in self.device_status.values():
            vendor = device_info['vendor']
            if vendor and vendor.strip() and vendor != 'Unknown':
                vendors_set.add(vendor)

        # Convert to sorted list
        coverage_data['vendors'] = sorted(list(vendors_set))

        # Analyze coverage by capture type
        for capture_type in self.capture_types:
            vendor_stats = defaultdict(lambda: {'success': 0, 'total': 0})

            for device_info in self.device_status.values():
                vendor = device_info['vendor'] or 'Unknown'
                vendor_stats[vendor]['total'] += 1

                if device_info['captures'].get(capture_type, False):
                    vendor_stats[vendor]['success'] += 1

            # Initialize the capture type entry
            coverage_data['by_capture'][capture_type] = {
                'vendors': dict(vendor_stats),
                'vendor_count': len([
                    v for v, stats in vendor_stats.items()
                    if stats['success'] > 0 and stats['total'] > 0
                ])
            }

        return coverage_data


@coverage_bp.route('/')
def index():
    """Main coverage dashboard"""
    try:
        current_app.logger.info("Starting coverage analysis...")

        reporter = DatabaseCoverageReporter()

        # Discover capture types
        reporter.discover_capture_types()
        current_app.logger.info(f"Found {len(reporter.capture_types)} capture types")

        # Analyze devices
        reporter.analyze_devices()
        current_app.logger.info(f"Analyzed {len(reporter.device_status)} devices")

        # Generate statistics
        summary_stats = reporter.get_summary_stats()
        vendor_coverage = reporter.generate_vendor_coverage_matrix()

        # Group devices by site/folder for display
        devices_by_folder = defaultdict(list)
        for device_name, device_info in reporter.device_status.items():
            devices_by_folder[device_info['folder']].append((device_name, device_info))

        # Sort devices within each folder
        for folder in devices_by_folder:
            devices_by_folder[folder].sort(key=lambda x: x[0])

        current_app.logger.info(f"Coverage stats: {summary_stats['total_devices']} devices, "
                                f"{summary_stats['total_successful_captures']} total captures")

        return render_template('coverage/index.html',
                               summary_stats=summary_stats,
                               vendor_coverage=vendor_coverage,
                               devices_by_folder=dict(devices_by_folder),
                               capture_types=reporter.capture_types,
                               generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    except Exception as e:
        current_app.logger.error(f"Coverage analysis failed: {e}", exc_info=True)

        # Return empty but valid structures to prevent template errors
        return render_template('coverage/index.html',
                               error=f"Failed to generate coverage report: {e}",
                               summary_stats={
                                   'total_devices': 0,
                                   'capture_types_count': 0,
                                   'total_successful_captures': 0,
                                   'perfect_capture_count': 0,
                                   'zero_capture_count': 0,
                                   'capture_stats': {},
                                   'perfect_devices': [],
                                   'zero_capture_devices': []
                               },
                               vendor_coverage={'vendors': [], 'by_capture': {}},
                               devices_by_folder={},
                               capture_types=[],
                               generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@coverage_bp.route('/api/device/<device_name>')
def device_detail(device_name):
    """API endpoint for device-specific coverage details"""
    try:
        reporter = DatabaseCoverageReporter()
        reporter.discover_capture_types()
        reporter.analyze_devices()

        device_info = reporter.device_status.get(device_name)
        if not device_info:
            return jsonify({'error': f'Device {device_name} not found'}), 404

        return jsonify({
            'device_name': device_name,
            'device_info': device_info,
            'capture_types': reporter.capture_types
        })

    except Exception as e:
        current_app.logger.error(f"Device detail failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@coverage_bp.route('/api/refresh')
def refresh_data():
    """API endpoint to trigger a fresh analysis"""
    try:
        reporter = DatabaseCoverageReporter()
        reporter.discover_capture_types()
        reporter.analyze_devices()

        summary_stats = reporter.get_summary_stats()

        return jsonify({
            'status': 'success',
            'summary': summary_stats,
            'refreshed_at': datetime.now().isoformat()
        })

    except Exception as e:
        current_app.logger.error(f"Refresh failed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500