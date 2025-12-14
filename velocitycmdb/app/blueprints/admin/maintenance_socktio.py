# velocitycmdb/app/blueprints/admin/maintenance_socketio.py
"""
SocketIO event handlers for real-time maintenance operations
Unified handlers for backup, indexes, topology, ARP, and component inventory

Component inventory operations call db_loader_inventory.py CLI
"""

from flask import session
from flask_socketio import emit
from pathlib import Path
import subprocess
import threading
import logging
import re
import sys

logger = logging.getLogger(__name__)

# Consistent default for all data directory references
DEFAULT_DATA_DIR = '~/.velocitycmdb/data'


def get_maintenance_service(app):
    """Get configured maintenance service"""
    from velocitycmdb.services.maintenance import MaintenanceOrchestrator
    project_root = Path(app.root_path).parent
    data_dir = Path(app.config.get('VELOCITYCMDB_DATA_DIR', DEFAULT_DATA_DIR)).expanduser()
    return MaintenanceOrchestrator(project_root=project_root, data_dir=data_dir)


def get_loader_paths(app):
    """Get paths for inventory loader script and data directory"""
    data_dir = Path(app.config.get('VELOCITYCMDB_DATA_DIR', DEFAULT_DATA_DIR)).expanduser()

    # Script locations to check (in priority order)
    # VELOCITYCMDB_DATA_DIR points to ~/.velocitycmdb/data
    # Scripts are in ~/.velocitycmdb (parent) or project root
    script_candidates = [
        Path(app.root_path).parent / 'db_loader_inventory.py',  # velocitycmdb/db_loader_inventory.py
        Path(app.root_path).parent / 'scripts' / 'db_loader_inventory.py',
        data_dir.parent / 'db_loader_inventory.py',  # ~/.velocitycmdb/db_loader_inventory.py
        data_dir.parent / 'scripts' / 'db_loader_inventory.py',
    ]

    script_path = None
    for path in script_candidates:
        if path.exists():
            script_path = path
            break

    # VELOCITYCMDB_DATA_DIR already points to the data directory
    # e.g., ~/.velocitycmdb/data
    # The CLI expects the directory, not the file path
    return script_path, data_dir


def register_maintenance_socketio_handlers(socketio, app):
    """Register all maintenance-related SocketIO handlers"""

    def require_admin():
        """Check admin privileges, emit error if not admin"""
        if not session.get('is_admin'):
            emit('maintenance_error', {'error': 'Admin privileges required'})
            return False
        return True

    def progress_callback(update):
        """Standard progress callback for service operations"""
        emit('maintenance_progress', {
            'stage': update.get('stage', ''),
            'message': update.get('message', ''),
            'progress': update.get('progress', 0)
        })

    def run_inventory_loader(args, operation_name):
        """
        Run db_loader_inventory.py CLI and emit progress/results via SocketIO.
        Runs in a background thread to avoid blocking.
        """
        script_path, data_dir = get_loader_paths(app)

        # Emit resolved paths for troubleshooting
        socketio.emit('maintenance_progress', {
            'stage': 'resolving',
            'message': f'Python interpreter: {sys.executable}',
            'progress': 2
        })

        if not script_path:
            # Show where we looked
            script_candidates = [
                Path(app.root_path).parent / 'db_loader_inventory.py',
                Path(app.root_path).parent / 'scripts' / 'db_loader_inventory.py',
                data_dir.parent / 'db_loader_inventory.py',
                data_dir.parent / 'scripts' / 'db_loader_inventory.py',
            ]
            socketio.emit('maintenance_error', {
                'error': 'db_loader_inventory.py not found. Searched:\n' +
                         '\n'.join(f'  - {p}' for p in script_candidates)
            })
            return

        socketio.emit('maintenance_progress', {
            'stage': 'resolving',
            'message': f'Script: {script_path}',
            'progress': 3
        })

        if not data_dir.exists():
            socketio.emit('maintenance_error', {
                'error': f'Data directory not found: {data_dir}'
            })
            return

        socketio.emit('maintenance_progress', {
            'stage': 'resolving',
            'message': f'Data dir: {data_dir}',
            'progress': 4
        })

        cmd = [sys.executable, str(script_path),
               '--assets-db', str(data_dir) + "/assets.db"] + args

        # Emit full command for troubleshooting
        socketio.emit('maintenance_progress', {
            'stage': 'executing',
            'message': f'Command: {" ".join(cmd)}',
            'progress': 5
        })
        socketio.emit('maintenance_progress', {
            'stage': 'executing',
            'message': f'Working dir: {script_path.parent}',
            'progress': 6
        })

        logger.info(f"Running inventory loader: {' '.join(cmd)}")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Capture stderr separately
                text=True,
                bufsize=1,
                cwd=str(script_path.parent)  # Run from script directory so it finds tfsm_templates.db
            )

            output_lines = []
            stderr_lines = []
            stats = {}

            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if not line:
                    continue

                output_lines.append(line)

                # Parse key metrics from CLI output
                if match := re.search(r'Components:\s*(\d+)', line):
                    stats['components_loaded'] = int(match.group(1))
                elif match := re.search(r'Processed:\s*(\d+)', line):
                    stats['files_processed'] = int(match.group(1))
                elif match := re.search(r'[Rr]eclassified[:\s]*(\d+)', line):
                    stats['reclassified'] = int(match.group(1))
                elif ('Deleted' in line or 'Cleaned up' in line) and (match := re.search(r'(\d+)', line)):
                    stats['deleted_count'] = int(match.group(1))
                elif match := re.search(r'Unknown:\s*(\d+)', line):
                    stats['unknown_count'] = int(match.group(1))

                # Emit progress update
                socketio.emit('maintenance_progress', {
                    'stage': 'processing',
                    'message': line[:120],  # Truncate long lines
                    'progress': 50
                })

            # Capture stderr after stdout is done
            stderr_output = process.stderr.read()
            if stderr_output:
                stderr_lines = stderr_output.strip().split('\n')
                for line in stderr_lines:
                    logger.error(f"STDERR: {line}")

            process.wait()

            if process.returncode == 0:
                socketio.emit('maintenance_complete', {
                    'success': True,
                    'operation': operation_name,
                    'output': '\n'.join(output_lines[-30:]),  # Last 30 lines
                    **stats
                })
                logger.info(f"{operation_name} completed successfully: {stats}")
            else:
                error_msg = '\n'.join(stderr_lines[-10:]) if stderr_lines else 'No stderr captured'
                socketio.emit('maintenance_error', {
                    'error': f'Command failed (rc={process.returncode}): {error_msg[:200]}',
                    'output': '\n'.join(output_lines[-20:])
                })
                logger.error(f"{operation_name} failed (rc={process.returncode})")
                logger.error(f"STDERR: {error_msg}")
                logger.error(f"STDOUT tail: {output_lines[-5:] if output_lines else 'empty'}")

        except Exception as e:
            import traceback
            logger.error(f"Inventory loader error: {e}\n{traceback.format_exc()}")
            socketio.emit('maintenance_error', {'error': str(e)})

    # =========================================================================
    # BACKUP HANDLERS
    # =========================================================================

    @socketio.on('maintenance_backup')
    def handle_backup(data):
        """Create database backup with progress updates"""
        if not require_admin():
            return

        try:
            emit('maintenance_progress', {
                'stage': 'starting',
                'message': 'Initializing backup...',
                'progress': 10
            })

            service = get_maintenance_service(app)
            result = service.create_backup(
                include_captures=data.get('include_captures', True),
                progress_callback=progress_callback
            )

            if result.get('success'):
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'backup',
                    'filename': result.get('filename'),
                    'size_mb': result.get('size_mb')
                })
            else:
                emit('maintenance_error', {'error': result.get('error', 'Backup failed')})

        except Exception as e:
            logger.error(f"Backup error: {e}")
            emit('maintenance_error', {'error': str(e)})

    # =========================================================================
    # SEARCH INDEX HANDLERS
    # =========================================================================

    @socketio.on('maintenance_rebuild_indexes')
    def handle_rebuild_indexes(data):
        """Rebuild FTS5 search indexes"""
        if not require_admin():
            return

        try:
            emit('maintenance_progress', {
                'stage': 'starting',
                'message': 'Rebuilding search indexes...',
                'progress': 10
            })

            service = get_maintenance_service(app)
            result = service.rebuild_search_indexes(progress_callback=progress_callback)

            if result.get('success'):
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'indexes',
                    'indexes_rebuilt': result.get('indexes_rebuilt', 0)
                })
            else:
                emit('maintenance_error', {'error': result.get('error', 'Index rebuild failed')})

        except Exception as e:
            logger.error(f"Index rebuild error: {e}")
            emit('maintenance_error', {'error': str(e)})

    # =========================================================================
    # TOPOLOGY HANDLERS
    # =========================================================================

    @socketio.on('maintenance_generate_topology')
    def handle_generate_topology(data):
        """Generate topology map from LLDP data"""
        if not require_admin():
            return

        try:
            root_device = data.get('root_device')
            if not root_device:
                emit('maintenance_error', {'error': 'Root device required'})
                return

            emit('maintenance_progress', {
                'stage': 'starting',
                'message': f'Generating topology from {root_device}...',
                'progress': 10
            })

            service = get_maintenance_service(app)
            result = service.generate_topology_from_lldp(
                root_device=root_device,
                max_hops=data.get('max_hops', 4),
                domain_suffix=data.get('domain_suffix', ''),
                filter_platform=data.get('filter_platform', []),
                filter_device=data.get('filter_device', []),
                progress_callback=progress_callback
            )

            if result.get('success'):
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'topology',
                    'filename': result.get('filename'),
                    'device_count': result.get('device_count', 0),
                    'connection_count': result.get('connection_count', 0)
                })
            else:
                emit('maintenance_error', {'error': result.get('error', 'Topology generation failed')})

        except Exception as e:
            logger.error(f"Topology generation error: {e}")
            emit('maintenance_error', {'error': str(e)})

    # =========================================================================
    # ARP HANDLERS
    # =========================================================================

    @socketio.on('maintenance_load_arp')
    def handle_load_arp(data):
        """Load ARP data from captures"""
        if not require_admin():
            return

        try:
            emit('maintenance_progress', {
                'stage': 'starting',
                'message': 'Loading ARP data...',
                'progress': 10
            })

            service = get_maintenance_service(app)
            result = service.load_arp_data(progress_callback=progress_callback)

            if result.get('success'):
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'arp',
                    'entries_loaded': result.get('entries_loaded', 0)
                })
            else:
                emit('maintenance_error', {'error': result.get('error', 'ARP load failed')})

        except Exception as e:
            logger.error(f"ARP load error: {e}")
            emit('maintenance_error', {'error': str(e)})

    # =========================================================================
    # CAPTURE DATA HANDLERS
    # =========================================================================

    @socketio.on('maintenance_load_captures')
    def handle_load_captures(data):
        """Load capture data into database"""
        if not require_admin():
            return

        try:
            capture_types = data.get('capture_types', [])

            emit('maintenance_progress', {
                'stage': 'starting',
                'message': f'Loading captures: {", ".join(capture_types)}...',
                'progress': 10
            })

            service = get_maintenance_service(app)
            result = service.load_capture_data(
                capture_types=capture_types,
                progress_callback=progress_callback
            )

            if result.get('success'):
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'captures',
                    'files_processed': result.get('files_processed', 0)
                })
            else:
                emit('maintenance_error', {'error': result.get('error', 'Capture load failed')})

        except Exception as e:
            logger.error(f"Capture load error: {e}")
            emit('maintenance_error', {'error': str(e)})

    # =========================================================================
    # COMPONENT INVENTORY HANDLERS (CLI-based)
    # =========================================================================

    @socketio.on('maintenance_inventory_load')
    def handle_inventory_load(data):
        """Load components from capture database via CLI"""
        if not require_admin():
            return

        logger.info(f"Inventory load requested with options: {data}")

        emit('maintenance_progress', {
            'stage': 'starting',
            'message': 'Starting component load...',
            'progress': 5
        })

        # Build args for load command - CLI handles --purge natively
        args = ['load']

        if data.get('purge'):
            args.append('--purge')

        if data.get('reclassify'):
            args.append('--reclassify')

        if data.get('ignore_sn'):
            args.append('--ignore-sn')

        if data.get('device_filter'):
            args.extend(['--device-filter', data['device_filter']])

        threading.Thread(
            target=run_inventory_loader,
            args=(args, 'inventory_load'),
            daemon=True
        ).start()

    @socketio.on('maintenance_inventory_purge')
    def handle_inventory_purge(data):
        """Purge all components without reloading (cleanup --all)"""
        if not require_admin():
            return

        logger.info("Inventory purge (cleanup only) requested")

        emit('maintenance_progress', {
            'stage': 'starting',
            'message': 'Purging all components...',
            'progress': 5
        })

        args = ['cleanup', '--all', '--confirm']

        threading.Thread(
            target=run_inventory_loader,
            args=(args, 'inventory_purge'),
            daemon=True
        ).start()

    @socketio.on('maintenance_inventory_reclassify')
    def handle_inventory_reclassify(data):
        """Reclassify unknown components via CLI"""
        if not require_admin():
            return

        args = ['reclassify']

        if data.get('delete_junk'):
            args.append('--delete-junk')
        if data.get('dry_run'):
            args.append('--dry-run')

        logger.info(f"Inventory reclassify requested: {args}")

        emit('maintenance_progress', {
            'stage': 'starting',
            'message': 'Starting reclassification...',
            'progress': 5
        })

        threading.Thread(
            target=run_inventory_loader,
            args=(args, 'inventory_reclassify'),
            daemon=True
        ).start()

    @socketio.on('maintenance_inventory_cleanup')
    def handle_inventory_cleanup(data):
        """Delete component records via CLI"""
        if not require_admin():
            return

        args = ['cleanup', '--confirm']
        scope = data.get('scope', 'device')

        if scope == 'all':
            args.append('--all')
        elif scope == 'device' and data.get('device_name'):
            args.extend(['--device-name', data['device_name']])
        elif scope == 'source' and data.get('source'):
            args.extend(['--source', data['source']])
        else:
            emit('maintenance_error', {'error': 'Invalid cleanup parameters'})
            return

        logger.info(f"Inventory cleanup requested: {args}")

        emit('maintenance_progress', {
            'stage': 'starting',
            'message': f'Cleaning up components ({scope})...',
            'progress': 5
        })

        threading.Thread(
            target=run_inventory_loader,
            args=(args, 'inventory_cleanup'),
            daemon=True
        ).start()

    @socketio.on('maintenance_inventory_analyze')
    def handle_inventory_analyze(data):
        """Analyze unknown components via CLI"""
        if not require_admin():
            return

        logger.info("Inventory analyze requested")

        emit('maintenance_progress', {
            'stage': 'starting',
            'message': 'Analyzing unknown components...',
            'progress': 5
        })

        threading.Thread(
            target=run_inventory_loader,
            args=(['analyze'], 'inventory_analyze'),
            daemon=True
        ).start()

    # Legacy handler - redirects to new reclassify
    @socketio.on('maintenance_reclassify_components')
    def handle_reclassify_legacy(data):
        """Legacy component reclassify - redirects to new handler"""
        logger.info("Legacy reclassify_components called, redirecting to inventory_reclassify")
        handle_inventory_reclassify({
            'delete_junk': data.get('delete_junk', False),
            'dry_run': False
        })

    # =========================================================================
    # DATABASE RESET HANDLER
    # =========================================================================

    @socketio.on('maintenance_reset_database')
    def handle_reset_database(data):
        """Reset database to initial state (DANGEROUS)"""
        if not require_admin():
            return

        try:
            emit('maintenance_progress', {
                'stage': 'starting',
                'message': 'Resetting database...',
                'progress': 10
            })

            service = get_maintenance_service(app)
            result = service.reset_database(confirm=True, progress_callback=progress_callback)

            if result.get('success'):
                emit('maintenance_reset_complete', {'success': True})
            else:
                emit('maintenance_error', {'error': result.get('error', 'Reset failed')})

        except Exception as e:
            logger.error(f"Database reset error: {e}")
            emit('maintenance_error', {'error': str(e)})

    logger.info("Maintenance SocketIO handlers registered successfully")