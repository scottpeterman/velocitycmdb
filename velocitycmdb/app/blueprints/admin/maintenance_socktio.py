# velocitycmdb/app/blueprints/admin/maintenance_socketio.py
"""
SocketIO event handlers for real-time maintenance operations
"""

from flask import session
from flask_socketio import emit
from pathlib import Path
from velocitycmdb.services.maintenance import MaintenanceOrchestrator
import logging

logger = logging.getLogger(__name__)


def get_maintenance_service(app):
    """Get configured maintenance service"""
    project_root = Path(app.root_path).parent
    data_dir = Path(app.config.get('VELOCITYCMDB_DATA_DIR', '.'))
    return MaintenanceOrchestrator(project_root=project_root, data_dir=data_dir)


def register_maintenance_socketio_handlers(socketio, app):
    """Register all maintenance-related SocketIO handlers"""

    def require_admin():
        """Check if user is admin"""
        if not session.get('is_admin'):
            emit('maintenance_error', {'error': 'Admin privileges required'})
            return False
        return True

    def progress_callback(update):
        """Emit progress updates to client"""
        emit('maintenance_progress', {
            'stage': update['stage'],
            'message': update['message'],
            'progress': update['progress']
        })

    @socketio.on('maintenance_backup')
    def handle_backup(data):
        """Handle backup creation with progress"""
        if not require_admin():
            return

        try:
            logger.info(f"Starting backup (include_captures={data.get('include_captures')})")

            service = get_maintenance_service(app)
            result = service.create_backup(
                include_captures=data.get('include_captures', True),
                progress_callback=progress_callback
            )

            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'backup',
                    'filename': result['filename'],
                    'size_mb': result['size_mb'],
                    'backup_path': result.get('backup_path', ''),  # Full path
                    'data_dir': result.get('data_dir', '')  # Source data directory
                })
                logger.info(f"Backup completed: {result['filename']} ({result['size_mb']} MB)")
                logger.info(f"Backup location: {result.get('backup_path', 'unknown')}")
            else:
                emit('maintenance_error', {'error': result['error']})
                logger.error(f"Backup failed: {result['error']}")

        except Exception as e:
            logger.error(f"Backup error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            emit('maintenance_error', {'error': str(e)})

    @socketio.on('maintenance_rebuild_indexes')
    def handle_rebuild_indexes(data):
        """Handle search index rebuild with progress"""
        if not require_admin():
            return

        try:
            logger.info("Starting index rebuild")

            service = get_maintenance_service(app)
            result = service.rebuild_search_indexes(progress_callback=progress_callback)

            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'indexes',
                    'indexes_rebuilt': result['indexes_rebuilt'],
                    'statistics': result.get('statistics', {})
                })
                logger.info(f"Index rebuild completed: {result['indexes_rebuilt']}")
                if 'statistics' in result:
                    logger.info(f"Statistics: {result['statistics']}")
            else:
                # Send detailed error information to UI
                error_msg = result.get('error', 'Unknown error')
                emit('maintenance_error', {
                    'error': error_msg,
                    'statistics': result.get('statistics', {}),
                    'indexes_rebuilt': result.get('indexes_rebuilt', []),
                    'return_code': result.get('return_code'),
                    'full_output': result.get('full_output')
                })
                logger.error(f"Index rebuild failed: {error_msg}")
                if 'return_code' in result:
                    logger.error(f"Return code: {result['return_code']}")

        except Exception as e:
            logger.error(f"Index rebuild error: {e}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(error_trace)

            # Send detailed error to UI
            emit('maintenance_error', {
                'error': str(e),
                'traceback': error_trace if app.debug else None
            })

    # Add this to velocitycmdb/app/blueprints/admin/maintenance_socketio.py
    # Inside the register_maintenance_socketio_handlers function

    @socketio.on('maintenance_generate_topology')
    def handle_generate_topology(data):
        """Handle topology generation with progress"""
        if not require_admin():
            return

        try:
            root_device = data.get('root_device')
            max_hops = data.get('max_hops', 4)
            domain_suffix = data.get('domain_suffix', 'home.com')
            filter_platform = data.get('filter_platform', [])
            filter_device = data.get('filter_device', [])

            if not root_device:
                emit('maintenance_error', {'error': 'Root device required'})
                return

            logger.info(f"Starting topology generation from {root_device} (max_hops={max_hops})")

            service = get_maintenance_service(app)
            result = service.generate_topology_from_lldp(
                root_device=root_device,
                max_hops=max_hops,
                domain_suffix=domain_suffix,
                filter_platform=filter_platform,
                filter_device=filter_device,
                progress_callback=progress_callback
            )

            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'topology',
                    'filename': result['filename'],
                    'device_count': result['device_count'],
                    'connection_count': result['connection_count'],
                    'size_kb': result['size_kb']
                })
                logger.info(f"Topology generated: {result['filename']} ({result['device_count']} devices)")
            else:
                emit('maintenance_error', {'error': result['error']})
                logger.error(f"Topology generation failed: {result['error']}")

        except Exception as e:
            logger.error(f"Topology generation error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            emit('maintenance_error', {'error': str(e)})

    @socketio.on('maintenance_load_arp')
    def handle_load_arp(data):
        """Handle ARP data loading with progress"""
        if not require_admin():
            return

        try:
            logger.info("Starting ARP data load")

            service = get_maintenance_service(app)
            result = service.load_arp_data(progress_callback=progress_callback)

            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'arp',
                    'entries_loaded': result['entries_loaded']
                })
                logger.info(f"Loaded {result['entries_loaded']} ARP entries")
            else:
                emit('maintenance_error', {'error': result['error']})
                logger.error(f"ARP load failed: {result['error']}")

        except Exception as e:
            logger.error(f"ARP load error: {e}")
            emit('maintenance_error', {'error': str(e)})

    @socketio.on('maintenance_load_captures')
    def handle_load_captures(data):
        """Handle capture data loading with progress"""
        if not require_admin():
            return

        try:
            capture_types = data.get('capture_types', [])
            logger.info(f"Starting capture load: {capture_types}")

            service = get_maintenance_service(app)
            result = service.load_capture_data(
                capture_types=capture_types,
                progress_callback=progress_callback
            )

            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'captures',
                    'files_processed': result['files_processed']
                })
                logger.info(f"Loaded {result['files_processed']} capture files")
            else:
                emit('maintenance_error', {'error': result['error']})
                logger.error(f"Capture load failed: {result['error']}")

        except Exception as e:
            logger.error(f"Capture load error: {e}")
            emit('maintenance_error', {'error': str(e)})



    @socketio.on('maintenance_reset_database')
    def handle_reset_database(data):
        """Handle database reset with progress"""
        if not require_admin():
            return

        try:
            logger.warning("Starting database reset - DESTRUCTIVE OPERATION")

            service = get_maintenance_service(app)
            result = service.reset_database(
                confirm=True,
                progress_callback=progress_callback
            )

            if result['success']:
                emit('maintenance_reset_complete', {'success': True})
                logger.warning("Database reset completed")
            else:
                emit('maintenance_error', {'error': result['error']})
                logger.error(f"Database reset failed: {result['error']}")

        except Exception as e:
            logger.error(f"Database reset error: {e}")
            emit('maintenance_error', {'error': str(e)})

    logger.info("Maintenance SocketIO handlers registered")


    @socketio.on('maintenance_reclassify_components')
    def handle_reclassify_components(data):
        """Handle component processing with real-time progress (2-step process)"""
        if not require_admin():
            return

        try:
            delete_junk = data.get('delete_junk', False)

            logger.info(f"Starting component processing (delete_junk={delete_junk})")

            service = get_maintenance_service(app)
            result = service.reclassify_components(
                delete_junk=delete_junk,
                progress_callback=progress_callback
            )

            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'components',
                    'step1': result.get('step1', {}),
                    'step2': result.get('step2', {}),
                    'summary': {
                        'files_processed': result['step1'].get('files_processed', 0),
                        'components_loaded': result['step1'].get('components_loaded', 0),
                        'components_reclassified': result['step2'].get('reclassified_count', 0),
                        'junk_deleted': result['step2'].get('junk_deleted', 0),
                        'unknown_remaining': result['step2'].get('unknown_count', 0)
                    }
                })
                logger.info(f"Component processing completed")
                logger.info(f"  Step 1: {result['step1']}")
                logger.info(f"  Step 2: {result['step2']}")
            else:
                # Send detailed error information
                error_msg = result.get('error', 'Unknown error')
                emit('maintenance_error', {
                    'error': error_msg,
                    'step1': result.get('step1', {}),
                    'step2': result.get('step2', {}),
                    'return_code': result.get('return_code')
                })
                logger.error(f"Component processing failed: {error_msg}")

        except Exception as e:
            logger.error(f"Component processing error: {e}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(error_trace)

            emit('maintenance_error', {
                'error': str(e),
                'traceback': error_trace if app.debug else None
            })