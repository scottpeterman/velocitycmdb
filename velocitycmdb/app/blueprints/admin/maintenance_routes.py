# velocitycmdb/app/blueprints/admin/maintenance_routes.py
"""
Maintenance routes - Complete integrated version
Combines backup, topology, component inventory, ARP, and database operations
"""

from flask import render_template, request, jsonify, send_file, current_app
from . import admin_bp
from pathlib import Path
from datetime import datetime
import sqlite3
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

# Consistent default for all data directory references
DEFAULT_DATA_DIR = '~/.velocitycmdb/data'


def admin_required(f):
    """Decorator to require admin privileges"""
    from functools import wraps
    from flask import session, redirect, url_for, flash

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Admin privileges required', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


def get_maintenance_service():
    """Get configured maintenance service"""
    from velocitycmdb.services.maintenance import MaintenanceOrchestrator
    project_root = Path(current_app.root_path).parent
    data_dir = Path(current_app.config.get('VELOCITYCMDB_DATA_DIR', DEFAULT_DATA_DIR)).expanduser()
    return MaintenanceOrchestrator(project_root=project_root, data_dir=data_dir)


def get_assets_db():
    """Get assets database path"""
    data_dir = Path(current_app.config.get('VELOCITYCMDB_DATA_DIR', DEFAULT_DATA_DIR)).expanduser()
    # VELOCITYCMDB_DATA_DIR already points to the data directory
    # e.g., ~/.velocitycmdb/data - assets.db is directly in it
    return data_dir / 'assets.db'


# =============================================================================
# MAIN MAINTENANCE PAGE
# =============================================================================

@admin_bp.route('/maintenance')
@admin_required
def maintenance():
    """Render maintenance panel"""
    return render_template('admin/maintenance.html', now=datetime.now().isoformat())


# =============================================================================
# BACKUP OPERATIONS
# =============================================================================

@admin_bp.route('/maintenance/backup', methods=['POST'])
@admin_required
def create_backup():
    """Create database backup"""
    try:
        data = request.json or {}
        include_captures = data.get('include_captures', True)

        service = get_maintenance_service()
        result = service.create_backup(include_captures=include_captures)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Backup creation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/maintenance/backup/download/<filename>')
@admin_required
def download_backup(filename):
    """Download backup file"""
    try:
        service = get_maintenance_service()
        backup_file = service.backup_dir / filename

        if not backup_file.exists():
            return jsonify({'error': 'Backup file not found'}), 404

        return send_file(backup_file, as_attachment=True, download_name=filename)

    except Exception as e:
        logger.error(f"Backup download error: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/maintenance/backup/inspect', methods=['POST'])
@admin_required
def inspect_backup():
    """Inspect backup archive"""
    try:
        if 'backup_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'})

        file = request.files['backup_file']

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar.gz') as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)

        try:
            service = get_maintenance_service()
            result = service.inspect_backup(tmp_path)
            return jsonify(result)
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Backup inspection error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/maintenance/backup/list')
@admin_required
def list_backups():
    """List available backup files"""
    try:
        service = get_maintenance_service()

        if not service.backup_dir.exists():
            return jsonify({'backups': []})

        backups = []
        for file in sorted(service.backup_dir.glob('*.tar.gz'), reverse=True):
            stat = file.stat()
            backups.append({
                'filename': file.name,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'created': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

        return jsonify({'backups': backups})

    except Exception as e:
        logger.error(f"Backup list error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# SEARCH INDEX OPERATIONS
# =============================================================================

@admin_bp.route('/maintenance/indexes/rebuild', methods=['POST'])
@admin_required
def rebuild_indexes():
    """Rebuild FTS5 search indexes"""
    try:
        service = get_maintenance_service()
        result = service.rebuild_search_indexes()
        return jsonify(result)

    except Exception as e:
        logger.error(f"Index rebuild error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# TOPOLOGY OPERATIONS
# =============================================================================

@admin_bp.route('/maintenance/topology/generate', methods=['POST'])
@admin_required
def generate_topology_map():
    """Generate topology map from LLDP data"""
    try:
        data = request.json or {}
        root_device = data.get('root_device')

        if not root_device:
            return jsonify({'success': False, 'error': 'Root device required'}), 400

        service = get_maintenance_service()
        result = service.generate_topology_from_lldp(
            root_device=root_device,
            max_hops=data.get('max_hops', 4),
            domain_suffix=data.get('domain_suffix', ''),
            filter_platform=data.get('filter_platform', []),
            filter_device=data.get('filter_device', [])
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Topology generation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/maintenance/topology/download/<filename>')
@admin_required
def download_topology(filename):
    """Download topology file"""
    try:
        service = get_maintenance_service()
        maps_dir = service.data_dir / 'maps'
        topology_file = maps_dir / filename

        if not topology_file.exists():
            return jsonify({'error': 'Topology file not found'}), 404

        return send_file(
            topology_file,
            as_attachment=True,
            download_name=filename,
            mimetype='application/json'
        )

    except Exception as e:
        logger.error(f"Topology download error: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/maintenance/topology/list')
@admin_required
def list_topologies():
    """List available topology files"""
    try:
        service = get_maintenance_service()
        maps_dir = service.data_dir / 'maps'

        if not maps_dir.exists():
            return jsonify({'topologies': []})

        topologies = []
        for file in sorted(maps_dir.glob('topology_*.json'), reverse=True):
            stat = file.stat()
            topologies.append({
                'filename': file.name,
                'size_kb': round(stat.st_size / 1024, 2),
                'created': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

        return jsonify({'topologies': topologies})

    except Exception as e:
        logger.error(f"Topology list error: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/maintenance/devices/search')
@admin_required
def search_devices():
    """Search for devices (for topology root selection)"""
    try:
        query = request.args.get('q', '').lower()

        if not query or len(query) < 2:
            return jsonify({'devices': []})

        db_path = get_assets_db()
        if not db_path.exists():
            return jsonify({'devices': [], 'error': 'Database not found'})

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name, normalized_name, management_ip, model
            FROM devices
            WHERE LOWER(name) LIKE ? OR LOWER(normalized_name) LIKE ?
            ORDER BY name
            LIMIT 20
        """, (f'%{query}%', f'%{query}%'))

        devices = []
        for row in cursor.fetchall():
            devices.append({
                'name': row[0],
                'normalized_name': row[1],
                'ip': row[2] or '',
                'model': row[3] or ''
            })

        conn.close()

        return jsonify({'devices': devices})

    except Exception as e:
        logger.error(f"Device search error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# COMPONENT INVENTORY OPERATIONS
# =============================================================================

@admin_bp.route('/maintenance/components/stats')
@admin_required
def component_stats():
    """Get component statistics - AJAX endpoint"""
    try:
        db_path = get_assets_db()

        if not db_path.exists():
            return jsonify({
                'total_components': 0,
                'with_serial': 0,
                'devices_with_components': 0,
                'by_type': {},
                'unknown_pct': 0,
                'error': 'Database not found'
            })

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        stats = {}

        # Total components
        cursor.execute("SELECT COUNT(*) FROM components")
        stats['total_components'] = cursor.fetchone()[0]

        # Components with serial numbers (length > 3 to filter junk)
        cursor.execute("""
            SELECT COUNT(*) FROM components 
            WHERE serial_number IS NOT NULL AND LENGTH(serial_number) > 3
        """)
        stats['with_serial'] = cursor.fetchone()[0]

        # Unique devices with components
        cursor.execute("SELECT COUNT(DISTINCT device_id) FROM components")
        stats['devices_with_components'] = cursor.fetchone()[0]

        # Breakdown by component type
        cursor.execute("""
            SELECT COALESCE(component_type, 'unknown'), COUNT(*) 
            FROM components 
            GROUP BY component_type 
            ORDER BY COUNT(*) DESC
        """)
        stats['by_type'] = {row[0] or 'unknown': row[1] for row in cursor.fetchall()}

        # Calculate unknown percentage
        total = stats['total_components']
        unknown = stats['by_type'].get('unknown', 0)
        stats['unknown_pct'] = (unknown / total * 100) if total > 0 else 0

        # Serial coverage percentage
        stats['serial_coverage_pct'] = (stats['with_serial'] / total * 100) if total > 0 else 0

        conn.close()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Component stats error: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/maintenance/components/reclassify', methods=['POST'])
@admin_required
def reclassify_components():
    """Reclassify hardware components (legacy sync endpoint)"""
    try:
        service = get_maintenance_service()
        result = service.reclassify_components()
        return jsonify(result)

    except Exception as e:
        logger.error(f"Component reclassify error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# ARP DATABASE OPERATIONS
# =============================================================================

@admin_bp.route('/maintenance/arp/load', methods=['POST'])
@admin_required
def load_arp_data():
    """Load ARP data from captures"""
    try:
        service = get_maintenance_service()
        result = service.load_arp_data()
        return jsonify(result)

    except Exception as e:
        logger.error(f"ARP load error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/maintenance/arp/stats')
@admin_required
def arp_stats():
    """Get ARP database statistics"""
    try:
        service = get_maintenance_service()
        stats = service.get_arp_stats()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"ARP stats error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# CAPTURE DATA OPERATIONS
# =============================================================================

@admin_bp.route('/maintenance/captures/load', methods=['POST'])
@admin_required
def load_capture_data():
    """Manually load capture data"""
    try:
        data = request.json or {}
        capture_types = data.get('capture_types', [])

        service = get_maintenance_service()
        result = service.load_capture_data(capture_types)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Capture load error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# DATABASE RESET (DANGER ZONE)
# =============================================================================

@admin_bp.route('/maintenance/database/reset', methods=['POST'])
@admin_required
def reset_database():
    """Reset database to initial state (DANGEROUS)"""
    try:
        service = get_maintenance_service()
        result = service.reset_database(confirm=True)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Database reset error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500