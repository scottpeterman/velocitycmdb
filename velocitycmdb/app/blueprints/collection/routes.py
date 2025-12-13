"""
Collection Blueprint - Data capture wizard
Follows the same pattern as discovery/fingerprinting
"""

from flask import Blueprint, render_template, request, jsonify, session, current_app
from pathlib import Path
import logging
import uuid
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Create blueprint
collection_bp = Blueprint('collection', __name__, url_prefix='/collection')


@collection_bp.route('/')
def index():
    """Redirect to wizard"""
    from flask import redirect, url_for
    return redirect(url_for('collection.wizard'))


@collection_bp.route('/wizard')
def wizard():
    """Show collection wizard page"""
    return render_template('collection/wizard.html')


@collection_bp.route('/devices', methods=['POST'])
def get_devices_for_collection():
    """
    Get devices from assets.db matching filters

    POST JSON:
    {
        "vendor": "Cisco",
        "site": "LAB",
        "role": "access"
    }

    Returns:
    {
        "success": true,
        "devices": [
            {"id": 1, "name": "device1", "ip": "10.0.0.1", ...},
            ...
        ],
        "count": 47
    }
    """
    try:
        from velocitycmdb.app.utils.database import get_db_connection

        filters = request.get_json(silent=True) or {}

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build query with filters
            query = """
                SELECT 
                    d.id,
                    d.name,
                    d.ipv4_address as ip,
                    v.name as vendor,
                    s.name as site,
                    d.model,
                    dt.netmiko_driver as device_type
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                LEFT JOIN sites s ON d.site_code = s.code
                LEFT JOIN device_types dt ON d.device_type_id = dt.id
                WHERE 1=1
            """
            params = []

            # Add filters
            if filters.get('vendor'):
                query += " AND v.name LIKE ?"
                params.append(f"%{filters['vendor']}%")

            if filters.get('site'):
                query += " AND s.code = ?"
                params.append(filters['site'])

            if filters.get('role'):
                query += " AND d.role_id = (SELECT id FROM device_roles WHERE name = ?)"
                params.append(filters['role'])

            query += " ORDER BY d.name"

            cursor.execute(query, params)
            devices = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            'success': True,
            'devices': devices,
            'count': len(devices)
        })

    except Exception as e:
        logger.exception("Failed to get devices")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@collection_bp.route('/start', methods=['POST'])
def start_collection():
    """
    Start collection job

    POST JSON:
    {
        "devices": [1, 2, 3],
        "capture_types": ["configs", "arp", "mac"],
        "credentials": {
            "username": "admin",
            "password": "pass",
            "use_keys": false,
            "ssh_key_path": null
        },
        "options": {
            "max_workers": 12,
            "auto_load_db": true
        }
    }

    Returns:
    {
        "success": true,
        "job_id": "collection_abc123",
        "message": "Collection started"
    }
    """
    try:
        data = request.get_json(silent=True) or {}

        # Validate required fields
        if not data.get('capture_types'):
            return jsonify({
                'success': False,
                'error': 'No capture types selected'
            }), 400

        # Create job ID
        job_id = f"collection_{uuid.uuid4().hex[:8]}"

        # Store in session
        session[f'collection_{job_id}'] = {
            'job_id': job_id,
            'started_at': datetime.now().isoformat(),
            'status': 'running',
            'capture_types': data.get('capture_types', []),
            'device_count': len(data.get('devices', []))
        }
        session.modified = True

        # Get SocketIO
        socketio = current_app.extensions.get('socketio')
        if not socketio:
            return jsonify({'error': 'SocketIO not available'}), 500

        # Start background task (same pattern as fingerprinting)
        socketio.start_background_task(
            target=run_collection_task,
            app=current_app._get_current_object(),
            job_id=job_id,
            device_ids=data.get('devices', []),
            capture_types=data.get('capture_types', []),
            credentials=data.get('credentials', {}),
            device_filters=data.get('filters', {}),
            options=data.get('options', {})
        )

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Collection started'
        })

    except Exception as e:
        logger.exception("Failed to start collection")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def run_collection_task(app, job_id, device_ids, capture_types, credentials,
                       device_filters, options):
    """
    Background task for collection

    Your batch_spn.py does all the work - we just orchestrate it!

    IMPORTANT: Runs with app context pushed
    """
    with app.app_context():
        from velocitycmdb.services.collection import CollectionOrchestrator

        socketio = app.extensions['socketio']

        def progress_callback(data):
            """Emit progress via SocketIO"""
            # Main progress update
            socketio.emit('collection_progress', {
                'job_id': job_id,
                **data
            })

            # Device started event
            if 'device_started' in data:
                socketio.emit('device_started', {
                    'job_id': job_id,
                    'device_name': data['device_started'],
                    'ip_address': data.get('ip_address', '')
                })

            # Device completed event
            if 'device_completed' in data:
                socketio.emit('device_completed', {
                    'job_id': job_id,
                    'device_name': data['device_completed'],
                    'success': data.get('device_success', False),
                    'message': data.get('device_message', '')
                })

        try:
            logger.info(f"Starting collection job: {job_id}")
            logger.info(f"Capture types: {capture_types}")
            if credentials.get('use_keys') and not credentials.get('ssh_key_path'):
                credentials['ssh_key_path'] = str(Path.home() / '.ssh' / 'id_rsa')
                logger.info(f"Using default SSH key: {credentials['ssh_key_path']}")

            logger.info(f"Credentials: username={credentials.get('username')}, "
                        f"use_keys={credentials.get('use_keys')}, "
                        f"ssh_key_path={credentials.get('ssh_key_path')}")
            # Get data directory
            data_dir = Path(app.config['VELOCITYCMDB_DATA_DIR'])

            # Get sessions file - batch_spn.py uses this to know which devices to talk to
            possible_paths = [
                data_dir / 'sessions.yaml',  # ~/.velocitycmdb/data/sessions.yaml
                data_dir.parent / 'discovery' / 'sessions.yaml',  # ~/.velocitycmdb/discovery/sessions.yaml
                data_dir.parent / 'data' / 'sessions.yaml',  # alternate layout
                Path('pcng/sessions.yaml'),  # ./pcng/sessions.yaml
                Path('sessions.yaml'),  # ./sessions.yaml
            ]

            sessions_file = None
            for path in possible_paths:
                if path.exists():
                    sessions_file = path
                    logger.info(f"Found sessions file: {sessions_file}")
                    break

            # if not sessions_file:
            #     searched = [str(p) for p in possible_paths]
            #     raise FileNotFoundError(
            #         f"Sessions file not found. Searched: {searched}. "
            #         f"Run discovery first or place sessions.yaml in {data_dir}"
            #     )
            #
            # logger.info(f"Using sessions file: {sessions_file}")

            # Create orchestrator
            orchestrator = CollectionOrchestrator(data_dir=data_dir)

            # Execute collection - orchestrator loads job files for each vendor/type combo
            result = orchestrator.run_collection_job(
                sessions_file=sessions_file,
                capture_types=capture_types,  # Just pass the types user selected
                credentials=credentials,
                device_filters=device_filters,
                options=options,
                progress_callback=progress_callback
            )

            logger.info(f"Collection complete: {result}")

            # Emit completion
            socketio.emit('collection_complete', {
                'job_id': job_id,
                'success': True,
                'devices_attempted': result.get('devices_attempted', 0),
                'devices_succeeded': result.get('devices_succeeded', 0),
                'devices_failed': result.get('devices_failed', 0),
                'captures_created': result.get('captures_created', {}),
                'loaded_to_db': result.get('loaded_to_db', False),
                'execution_time': result.get('execution_time', 0),
                'failed_devices': result.get('failed_devices', [])
            })

        except Exception as e:
            logger.exception(f"Collection task {job_id} failed")
            socketio.emit('collection_error', {
                'job_id': job_id,
                'error': str(e)
            })


@collection_bp.route('/status/<job_id>', methods=['GET'])
def get_collection_status(job_id):
    """
    Get status of a collection job (polling fallback if SocketIO fails)
    """
    job_info = session.get(f'collection_{job_id}')

    if not job_info:
        return jsonify({'error': 'Collection job not found'}), 404

    return jsonify({
        'job_id': job_id,
        'status': job_info.get('status', 'running'),
        'started_at': job_info.get('started_at'),
        'capture_types': job_info.get('capture_types', []),
        'device_count': job_info.get('device_count', 0)
    })