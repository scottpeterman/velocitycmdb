"""
Discovery Blueprint - Network topology discovery via web UI
"""

from flask import Blueprint, render_template, request, jsonify, session, current_app
from pathlib import Path
import logging
import uuid
import time
from datetime import datetime
import threading

logger = logging.getLogger(__name__)

# Consistent default for all data directory references
DEFAULT_DATA_DIR = '~/.velocitycmdb/data'

# Create blueprint
discovery_bp = Blueprint('discovery', __name__, url_prefix='/discovery')


def get_data_dir():
    """Get data directory with consistent default"""
    return Path(current_app.config.get('VELOCITYCMDB_DATA_DIR', DEFAULT_DATA_DIR)).expanduser()


@discovery_bp.route('/')
def index():
    """Redirect to wizard"""
    from flask import redirect, url_for
    return redirect(url_for('discovery.wizard'))


@discovery_bp.route('/wizard')
def wizard():
    """Show discovery wizard page"""
    return render_template('discovery/wizard.html')


@discovery_bp.route('/start', methods=['POST'])
def start_discovery():
    """
    Start network discovery process

    Expects JSON:
    {
        "seed_ip": "10.0.0.1",
        "username": "admin",
        "password": "password",
        "alternate_username": "",  // optional
        "alternate_password": "",  // optional
        "max_devices": 100,        // optional
        "timeout": 30              // optional
    }

    Returns:
    {
        "success": true,
        "job_id": "discovery_abc123",
        "message": "Discovery started"
    }
    """
    try:
        data = request.json

        # Validate required fields
        seed_ip = data.get('seed_ip', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not all([seed_ip, username, password]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: seed_ip, username, password'
            }), 400

        # Optional parameters
        alternate_username = data.get('alternate_username', '').strip()
        alternate_password = data.get('alternate_password', '').strip()
        max_devices = int(data.get('max_devices', 100))
        timeout = int(data.get('timeout', 30))

        # Create job ID for this discovery
        job_id = f"discovery_{uuid.uuid4().hex[:8]}"

        # Get data directory with consistent default
        data_dir = get_data_dir()

        # Store comprehensive job info in session (for fingerprinting later)
        session[f'job_{job_id}'] = {
            'job_id': job_id,
            'status': 'running',
            'stage': 'initializing',
            'started_at': datetime.now().isoformat(),
            'seed_ip': seed_ip,
            'username': username,
            'password': password,  # Store for fingerprinting (consider encrypting in production)
            'data_dir': str(data_dir)
        }
        session.modified = True

        # Get SocketIO instance
        socketio = current_app.extensions.get('socketio')

        if socketio:
            # Start background task with app context
            socketio.start_background_task(
                target=run_discovery_task,
                app=current_app._get_current_object(),
                job_id=job_id,
                seed_ip=seed_ip,
                username=username,
                password=password,
                alternate_username=alternate_username,
                alternate_password=alternate_password,
                max_devices=max_devices,
                timeout=timeout
            )
        else:
            # No SocketIO, run synchronously (not recommended for production)
            logger.warning("SocketIO not available, running discovery synchronously")
            result = run_discovery_sync(
                seed_ip=seed_ip,
                username=username,
                password=password,
                alternate_username=alternate_username,
                alternate_password=alternate_password,
                max_devices=max_devices,
                timeout=timeout
            )
            return jsonify(result)

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Discovery started'
        })

    except Exception as e:
        logger.exception("Failed to start discovery")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@discovery_bp.route('/status/<job_id>')
def get_status(job_id):
    """
    Get status of discovery job

    Returns:
    {
        "status": "running"|"complete"|"failed",
        "stage": "discovery"|"inventory"|"complete",
        "message": "Current status message",
        "progress": 0-100,
        "result": {...}  // Only if complete
    }
    """
    job_info = session.get(f'job_{job_id}')

    if not job_info:
        return jsonify({
            'error': 'Job not found'
        }), 404

    return jsonify(job_info)


def run_discovery_task(app, job_id, seed_ip, username, password, **kwargs):
    """
    Background task to run discovery
    Called by SocketIO background thread

    IMPORTANT: Runs with app context pushed
    """
    # Push application context for this thread
    with app.app_context():
        from velocitycmdb.services.discovery import DiscoveryOrchestrator

        # Get SocketIO from app extensions
        socketio = app.extensions['socketio']

        def progress_callback(data):
            """Emit progress via SocketIO"""
            socketio.emit('discovery_progress', {
                'job_id': job_id,
                **data
            })

        try:
            # Create orchestrator
            orchestrator = DiscoveryOrchestrator()

            # Run full discovery
            result = orchestrator.run_full_discovery(
                seed_ip=seed_ip,
                username=username,
                password=password,
                progress_callback=progress_callback,
                **kwargs
            )

            if result['success']:
                # Update session with results
                # NOTE: This won't work in background thread - use alternative storage
                # For now, we'll emit the data via SocketIO and let client store it

                # Emit completion
                socketio.emit('discovery_complete', {
                    'job_id': job_id,
                    'success': True,
                    'device_count': result['device_count'],
                    'site_count': result['site_count'],
                    'topology_file': str(result['topology_file']),
                    'inventory_file': str(result['inventory_file']),
                    'map_url': f"/discovery/map/{job_id}" if result.get('map_file') else None
                })

                logger.info(f"Discovery {job_id} completed successfully")
            else:
                # Emit failure
                socketio.emit('discovery_failed', {
                    'job_id': job_id,
                    'error': result.get('error', 'Unknown error')
                })

                logger.error(f"Discovery {job_id} failed: {result.get('error')}")

        except Exception as e:
            logger.exception(f"Discovery task {job_id} failed with exception")
            socketio.emit('discovery_failed', {
                'job_id': job_id,
                'error': str(e)
            })


def run_discovery_sync(seed_ip, username, password, **kwargs):
    """
    Synchronous discovery (fallback when no SocketIO)
    """
    from velocitycmdb.services.discovery import DiscoveryOrchestrator

    try:
        orchestrator = DiscoveryOrchestrator()
        result = orchestrator.run_full_discovery(
            seed_ip=seed_ip,
            username=username,
            password=password,
            **kwargs
        )
        return result
    except Exception as e:
        logger.exception("Synchronous discovery failed")
        return {'success': False, 'error': str(e)}


@discovery_bp.route('/results/<job_id>')
def get_results(job_id):
    """
    Get discovery results for a job
    Returns device list from the discovered sessions.yaml file
    """
    try:
        job_info = session.get(f'job_{job_id}')

        if not job_info:
            return jsonify({'error': 'Job not found'}), 404

        # Get data directory with consistent default
        data_dir = Path(job_info.get('data_dir', str(get_data_dir())))
        sessions_file = data_dir / 'disco' / 'sessions.yaml'

        if not sessions_file.exists():
            return jsonify({'error': 'Sessions file not found'}), 404

        # Parse sessions.yaml
        import yaml
        with open(sessions_file) as f:
            sessions = yaml.safe_load(f) or {}

        # Extract devices
        devices = []
        for site_name, site in sessions.items():
            if not isinstance(site, dict):
                continue

            for session_data in site.get('sessions', []):
                devices.append({
                    'name': session_data.get('display_name', session_data.get('name', 'unknown')),
                    'ip': session_data.get('host', session_data.get('ip', '')),
                    'site': site_name,
                    'vendor': session_data.get('Vendor', 'Unknown'),
                    'model': session_data.get('Model', 'Unknown')
                })

        # Store sessions_file path in job_info for fingerprinting
        job_info['inventory_file'] = str(sessions_file)
        session[f'job_{job_id}'] = job_info
        session.modified = True

        return jsonify({
            'success': True,
            'total': len(devices),
            'devices': devices,
            'sessions_file': str(sessions_file)
        })

    except Exception as e:
        logger.exception("Error reading sessions file")
        return jsonify({'error': str(e)}), 500


@discovery_bp.route('/fingerprint/<job_id>', methods=['POST'])
def start_fingerprinting(job_id):
    """
    Start fingerprinting devices from discovery job

    Expects JSON:
    {
        "username": "admin",      // Optional, will use discovery credentials if not provided
        "password": "password",   // Optional, will use discovery credentials if not provided
        "ssh_key_path": null      // Optional SSH key
    }
    """
    try:
        from velocitycmdb.services.fingerprint import FingerprintOrchestrator

        # Get discovery job info
        job_info = session.get(f'job_{job_id}')

        if not job_info:
            return jsonify({'error': 'Discovery job not found'}), 404

        # Get credentials from request or use discovery credentials
        # Handle empty body gracefully
        try:
            data = request.get_json(silent=True) or {}
        except:
            data = {}

        username = data.get('username') or job_info.get('username')
        password = data.get('password') or job_info.get('password')
        ssh_key_path = data.get('ssh_key_path')
        inventory_file_override = data.get('inventory_file')  # Allow client to specify

        if not username or not password:
            return jsonify({'error': 'Credentials required'}), 400

        # Get paths with consistent default
        data_dir = Path(job_info.get('data_dir', str(get_data_dir())))

        # Get inventory file path - priority order:
        # 1. From request body (client stored it from discovery_complete)
        # 2. From session (if available)
        # 3. Fallback to standard location
        if inventory_file_override:
            sessions_file = Path(inventory_file_override)
        elif job_info.get('inventory_file'):
            sessions_file = Path(job_info.get('inventory_file'))
        else:
            # Fallback: look in discovery output directory
            sessions_file = data_dir / 'disco' / 'sessions.yaml'

        logger.info(f"Fingerprint request for job {job_id}")
        logger.info(f"Data dir: {data_dir}")
        logger.info(f"Sessions file from job_info: {job_info.get('inventory_file')}")
        logger.info(f"Sessions file resolved: {sessions_file}")
        logger.info(f"Sessions file exists: {sessions_file.exists()}")

        if not sessions_file.exists():
            logger.error(f"Inventory file not found: {sessions_file}")
            return jsonify({'error': f'Inventory file not found: {sessions_file}'}), 404

        # Create fingerprint job ID
        fingerprint_job_id = f"fingerprint_{job_id}_{int(time.time())}"

        # Store fingerprint job info
        session[f'fingerprint_{fingerprint_job_id}'] = {
            'job_id': fingerprint_job_id,
            'discovery_job_id': job_id,
            'sessions_file': str(sessions_file),
            'data_dir': str(data_dir),
            'username': username,
            'started_at': datetime.now().isoformat(),
            'status': 'running'
        }
        session.modified = True

        # Get SocketIO
        socketio = current_app.extensions.get('socketio')

        if not socketio:
            return jsonify({'error': 'SocketIO not available'}), 500

        # Use SocketIO background task (properly passes app context)
        socketio.start_background_task(
            target=run_fingerprinting_task,
            app=current_app._get_current_object(),
            fingerprint_job_id=fingerprint_job_id,
            discovery_job_id=job_id,
            sessions_file=sessions_file,
            data_dir=data_dir,
            username=username,
            password=password,
            ssh_key_path=ssh_key_path
        )
        return jsonify({
            'success': True,
            'fingerprint_job_id': fingerprint_job_id,
            'message': 'Fingerprinting started'
        })

    except Exception as e:
        logger.exception("Failed to start fingerprinting")
        return jsonify({'error': str(e)}), 500


def run_fingerprinting_task(app, fingerprint_job_id, discovery_job_id, sessions_file,
                           data_dir, username, password, ssh_key_path=None):
    """
    Background task to run fingerprinting
    Called by SocketIO background thread

    IMPORTANT: Runs with app context pushed (like discovery does)
    """
    # Push application context for this thread
    with app.app_context():
        from velocitycmdb.services.fingerprint import FingerprintOrchestrator

        # Get SocketIO from app extensions
        socketio = app.extensions['socketio']

        def progress_update(data):
            """Emit progress via SocketIO"""
            socketio.emit('fingerprint_progress', {
                'job_id': fingerprint_job_id,
                **data
            })

        try:
            logger.info(f"Starting fingerprinting job: {fingerprint_job_id}")
            logger.info(f"Sessions file: {sessions_file}")
            logger.info(f"Data directory: {data_dir}")

            orchestrator = FingerprintOrchestrator(data_dir=data_dir)

            result = orchestrator.fingerprint_inventory(
                sessions_file=sessions_file,
                username=username,
                password=password,
                ssh_key_path=ssh_key_path,
                progress_callback=progress_update
            )

            logger.info(f"Fingerprinting complete: {result}")

            # Convert Path objects to strings for JSON serialization
            result_serializable = {
                'success': result['success'],
                'fingerprinted': result['fingerprinted'],
                'failed': result['failed'],
                'failed_devices': result['failed_devices'],
                'loaded_to_db': result['loaded_to_db'],
                'db_load_failed': result['db_load_failed'],
                'fingerprints_dir': str(result['fingerprints_dir']),
                'db_path': str(result['db_path'])
            }

            # Emit completion
            socketio.emit('fingerprint_complete', {
                'job_id': fingerprint_job_id,
                'discovery_job_id': discovery_job_id,
                'success': True,
                **result_serializable
            })

        except Exception as e:
            logger.exception("Fingerprinting error")
            socketio.emit('fingerprint_error', {
                'job_id': fingerprint_job_id,
                'discovery_job_id': discovery_job_id,
                'error': str(e)
            })


@discovery_bp.route('/fingerprint/status/<fingerprint_job_id>', methods=['GET'])
def get_fingerprint_status(fingerprint_job_id):
    """
    Get status of a fingerprinting job (polling fallback)
    """
    job_info = session.get(f'fingerprint_{fingerprint_job_id}')

    if not job_info:
        return jsonify({'error': 'Fingerprint job not found'}), 404

    # Count fingerprint files to show progress - use consistent default
    data_dir = Path(job_info.get('data_dir', str(get_data_dir())))
    fingerprints_dir = data_dir / 'fingerprints'

    if fingerprints_dir.exists():
        json_files = list(fingerprints_dir.glob('*.json'))
        completed_count = len(json_files)
    else:
        completed_count = 0

    return jsonify({
        'job_id': fingerprint_job_id,
        'status': job_info.get('status', 'running'),
        'completed_count': completed_count,
        'started_at': job_info.get('started_at')
    })