"""
Collection Service - Orchestrates network data collection pipeline
Uses run_jobs_batch.py with job definition files

PASSWORD AUTHENTICATION ONLY - No SSH keys
"""
import os
import subprocess
import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Import job mappings
try:
    from .capture_job_mappings import (
        get_jobs_for_capture_types,
        calculate_prompt_count,
        CAPTURE_TYPE_MAPPINGS,
        get_job_file_path
    )
except ImportError:
    # Fallback for when running as script
    from capture_job_mappings import (
        get_jobs_for_capture_types,
        calculate_prompt_count,
        CAPTURE_TYPE_MAPPINGS,
        get_job_file_path
    )


class CollectionOrchestrator:
    """
    Orchestrates network data collection using run_jobs_batch.py

    PASSWORD AUTHENTICATION ONLY
    Job files are dynamically updated to use password auth
    """

    def __init__(self, data_dir: Path = None):
        """
        Initialize collection orchestrator

        Args:
            data_dir: Base data directory (~/.velocitycmdb/data)
        """
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / '.velocitycmdb' / 'data'

        self.capture_dir = self.data_dir / 'capture'
        self.jobs_dir = self.data_dir / 'jobs'

        # Ensure directories exist
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

        # Reference to existing scripts
        self.pcng_dir = Path(__file__).parent.parent / 'pcng'
        self.run_jobs_batch_script = self.pcng_dir / 'run_jobs_batch.py'
        self.jobs_source_dir = self.pcng_dir / 'jobs'
        self.db_load_script = self.pcng_dir / 'db_load_capture.py'

        logger.info(f"Collection orchestrator initialized (PASSWORD AUTH ONLY)")
        logger.info(f"  Capture dir: {self.capture_dir}")
        logger.info(f"  Jobs source: {self.jobs_source_dir}")
        logger.info(f"  run_jobs_batch.py: {self.run_jobs_batch_script}")

    def run_collection_job(self,
                          sessions_file: Path,
                          capture_types: List[str],
                          credentials: Dict[str, str],
                          device_filters: Dict[str, str] = None,
                          options: Dict = None,
                          progress_callback: Optional[Callable] = None) -> Dict:
        """
        Execute data collection using password authentication

        Args:
            sessions_file: Path to sessions.yaml inventory
            capture_types: List of capture types ['configs', 'arp', 'mac']
            credentials: {'username': 'admin', 'password': 'yourpass'}
            device_filters: {'vendor': 'Cisco', 'site': '', 'name': ''}
            options: {'max_workers': 12, 'auto_load_db': True}
            progress_callback: Function(dict) for real-time updates

        Returns:
            {
                'success': True/False,
                'devices_succeeded': 45,
                'devices_failed': 2,
                'execution_time': 234.5
            }
        """
        start_time = datetime.now()
        logger.info(f"DEBUG credentials received: {credentials}")

        device_filters = device_filters or {}
        options = options or {}
        auto_load_db = options.get('auto_load_db', True)

        if progress_callback:
            progress_callback({
                'stage': 'collecting',
                'message': 'Preparing collection job...',
                'progress': 0
            })

        try:
            # Validate credentials
            if not credentials.get('username'):
                raise ValueError("Username is required")
            if not credentials.get('password') and not credentials.get('ssh_key_path'):
                raise ValueError("Password or SSH key path is required")

            # Step 0: Generate sessions.yaml from database
            sessions_file = self._generate_sessions_file(
                device_filters=device_filters,
                progress_callback=progress_callback
            )

            logger.info(f"Generated sessions file: {sessions_file}")

            # Step 1: Create job list with password auth
            job_list_file = self._create_job_list(
                capture_types=capture_types,
                device_filters=device_filters,
                sessions_file=sessions_file,
                credentials=credentials
            )

            logger.info(f"Created job list: {job_list_file}")

            # Step 2: Execute via run_jobs_batch.py
            result = self._execute_job_batch(
                job_list_file=job_list_file,
                credentials=credentials,
                progress_callback=progress_callback
            )

            # Step 3: Load to database if requested
            # Always attempt db_load if enabled - _load_to_database handles missing dirs gracefully
            if auto_load_db:
                if progress_callback:
                    progress_callback({
                        'stage': 'loading',
                        'message': 'Loading captures into database...',
                        'progress': 85
                    })

                db_result = self._load_to_database(
                    capture_dirs=[self.capture_dir / ct for ct in capture_types],
                    progress_callback=progress_callback
                )
                result['loaded_to_db'] = db_result['success']
            else:
                result['loaded_to_db'] = False

            end_time = datetime.now()
            result['execution_time'] = (end_time - start_time).total_seconds()

            if progress_callback:
                progress_callback({
                    'stage': 'complete',
                    'message': f'✓ Collection complete!',
                    'progress': 100
                })

            return result

        except Exception as e:
            logger.exception("Collection job failed")
            return {
                'success': False,
                'error': str(e),
                'execution_time': (datetime.now() - start_time).total_seconds(),
                'devices_succeeded': 0,
                'devices_failed': 0
            }

    def _generate_sessions_file(self,
                                device_filters: Dict[str, str],
                                progress_callback: Optional[Callable] = None) -> Path:
        """Generate sessions.yaml from assets.db"""
        if progress_callback:
            progress_callback({
                'stage': 'collecting',
                'message': 'Generating sessions.yaml from database...',
                'progress': 5
            })

        sessions_file = self.data_dir / 'sessions.yaml'  # FIX: was self.pcng_dir
        db_path = self.data_dir / 'assets.db'
        db_to_sessions_script = Path(__file__).parent.parent / 'db_to_sessions.py'

        # DEBUG: Log all paths with full resolution
        logger.info(f"DEBUG _generate_sessions_file paths:")
        logger.info(f"  data_dir:            {self.data_dir}")
        logger.info(f"  data_dir (resolved): {self.data_dir.resolve()}")
        logger.info(f"  sessions_file:       {sessions_file}")
        logger.info(f"  sessions_file (abs): {sessions_file.resolve()}")
        logger.info(f"  db_path:             {db_path}")
        logger.info(f"  db_path (exists):    {db_path.exists()}")
        logger.info(f"  script:              {db_to_sessions_script}")
        logger.info(f"  script (exists):     {db_to_sessions_script.exists()}")

        cmd = [
            sys.executable,
            str(db_to_sessions_script),
            str(db_path),
            '-o', str(sessions_file)
        ]

        # Add filters
        if device_filters.get('vendor'):
            cmd.extend(['--vendor', device_filters['vendor']])
        if device_filters.get('site'):
            cmd.extend(['--site', device_filters['site']])

        logger.info(f"DEBUG: Full command: {' '.join(cmd)}")

        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                encoding='utf-8',
                errors='replace'
            )

            if result.stdout:
                logger.info(f"db_to_sessions STDOUT: {result.stdout}")
            if result.stderr:
                logger.error(f"db_to_sessions STDERR: {result.stderr}")

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(f"db_to_sessions.py failed: {error_msg}")

            # DEBUG: Verify file creation
            logger.info(f"DEBUG: Checking if sessions_file was created...")
            logger.info(f"  sessions_file.exists(): {sessions_file.exists()}")
            if sessions_file.exists():
                file_size = sessions_file.stat().st_size
                logger.info(f"  sessions_file size:     {file_size} bytes")
                logger.info(f"  sessions_file (real):   {sessions_file.resolve()}")
            else:
                # Check if it ended up somewhere else
                alt_locations = [
                    self.pcng_dir / 'sessions.yaml',
                    Path.cwd() / 'sessions.yaml',
                    Path.home() / 'sessions.yaml'
                ]
                for alt in alt_locations:
                    if alt.exists():
                        logger.warning(f"  FOUND at alternate location: {alt.resolve()}")

            if not sessions_file.exists():
                raise RuntimeError(f"sessions.yaml was not created at {sessions_file.resolve()}")

            logger.info(f"✓ Generated {sessions_file.resolve()}")
            return sessions_file

        except subprocess.TimeoutExpired:
            raise RuntimeError("db_to_sessions.py timed out")
        except Exception as e:
            logger.exception("Failed to generate sessions.yaml")
            raise RuntimeError(f"Could not generate sessions.yaml: {e}")

    def _create_job_list(self,
                        capture_types: List[str],
                        device_filters: Dict[str, str],
                        sessions_file: Path,
                        credentials: Dict) -> Path:
        """
        Create job list file with password authentication using capture type mappings

        This method:
        1. Uses capture_job_mappings to find correct job files
        2. Filters by vendor if specified
        3. Updates each job for password auth
        4. Sets correct prompt_count based on commands
        """
        job_list_path = self.jobs_dir / f'job_list_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'

        # DEBUG: Log what we received
        logger.info(f"DEBUG: device_filters = {device_filters}")
        logger.info(f"DEBUG: capture_types = {capture_types}")

        # Log filtering criteria
        vendor_filter = device_filters.get('vendor', '')
        if vendor_filter:
            logger.info(f"Creating job list with vendor filter: '{vendor_filter}'")
        else:
            logger.info(f"Creating job list with NO vendor filter (all vendors)")

        job_files = []

        # Determine which vendors to include based on filter
        if vendor_filter:
            # Map common vendor names to job file vendor names
            vendor_map = {
                'cisco': ['cisco-ios', 'cisco-nxos'],
                'arista': ['arista'],
                'juniper': ['juniper'],
                'cisco-ios': ['cisco-ios'],
                'cisco-nxos': ['cisco-nxos']
            }
            vendors_to_process = vendor_map.get(vendor_filter.lower(), [vendor_filter.lower()])
            logger.info(f"Vendor filter '{vendor_filter}' mapped to: {vendors_to_process}")
        else:
            vendors_to_process = ['arista', 'cisco-ios', 'cisco-nxos', 'juniper']
            logger.info(f"No vendor filter - processing all vendors: {vendors_to_process}")

        # Process each capture type
        for capture_type in capture_types:
            if capture_type not in CAPTURE_TYPE_MAPPINGS:
                logger.warning(f"Unknown capture type: {capture_type}, skipping")
                continue

            mapping = CAPTURE_TYPE_MAPPINGS[capture_type]
            logger.info(f"Processing capture type '{capture_type}' ({mapping['ui_label']})")

            # Get job files for each vendor
            for vendor in vendors_to_process:
                if vendor not in mapping['vendors']:
                    logger.debug(f"Vendor {vendor} not supported for {capture_type}")
                    continue

                try:
                    job_file = get_job_file_path(capture_type, vendor, self.jobs_source_dir)

                    if not job_file.exists():
                        logger.warning(f"Job file not found: {job_file}")
                        continue

                    # Update job file with password auth AND correct prompt_count
                    updated_job = self._update_job_for_password_auth(
                        job_file,
                        sessions_file,
                        credentials,
                        capture_type,
                        vendor
                    )

                    job_files.append(str(updated_job))
                    logger.info(f"✓ Added job: {updated_job.name} (vendor={vendor}, type={capture_type})")

                except Exception as e:
                    logger.error(f"Failed to process {capture_type} for {vendor}: {e}")
                    continue

        if not job_files:
            raise ValueError(f"No job files found for capture types: {capture_types} with vendor filter: {vendor_filter}")

        # Write job list file
        with open(job_list_path, 'w') as f:
            f.write("# Auto-generated job list - PASSWORD AUTH ONLY\n")
            f.write(f"# Created: {datetime.now().isoformat()}\n")
            f.write(f"# Capture types: {', '.join(capture_types)}\n")
            f.write(f"# Vendor filter: {vendor_filter or 'ALL'}\n")
            f.write(f"# Vendors: {', '.join(vendors_to_process)}\n\n")
            for job_file in job_files:
                f.write(f"{job_file}\n")

        logger.info(f"✓ Created job list with {len(job_files)} jobs: {job_list_path}")
        return job_list_path

    def _update_job_for_password_auth(self,
                                      job_file: Path,
                                      sessions_file: Path,
                                      credentials: Dict,
                                      capture_type: str,
                                      vendor: str) -> Path:
        """
        Update job file to use PASSWORD AUTHENTICATION ONLY

        Also sets correct prompt_count based on the ACTUAL commands in the job file
        Removes any SSH key settings and forces password auth
        """
        # Read original job
        with open(job_file) as f:
            job_data = json.load(f)

        # Update session_file
        job_data['session_file'] = str(sessions_file)

        # FORCE PASSWORD AUTHENTICATION - Remove all SSH key settings
        job_data['authentication'] = {
            'use_keys': False
            # No ssh_key_path at all
        }

        # Update credentials
        job_data['credentials'] = {
            'username': credentials['username'],
            'password_provided': True,  # Via environment variable
            'credential_system': 'Environment variables (CRED_*_PASS)'
        }

        # Get auto_paging setting (default True)
        auto_paging = job_data.get('vendor', {}).get('auto_paging', True)

        # Get the ACTUAL command_text from the job file
        command_text = job_data.get('commands', {}).get('command_text', '')

        logger.info(f"Job file command_text: '{command_text}'")

        # Calculate correct prompt_count based on ACTUAL commands in job file
        correct_prompt_count = calculate_prompt_count(
            capture_type,
            vendor,
            auto_paging,
            command_text=command_text  # Pass the actual command text!
        )

        # Update execution settings with correct prompt_count
        if 'execution' not in job_data:
            job_data['execution'] = {}

        job_data['execution']['prompt_count'] = correct_prompt_count

        # Log the prompt count calculation for debugging
        logger.info(f"Set prompt_count={correct_prompt_count} for {vendor} {capture_type} (auto_paging={auto_paging}, commands='{command_text}')")

        # Update output directory
        if 'commands' in job_data and 'output_directory' in job_data['commands']:
            capture_output_dir = job_data['commands']['output_directory']
            if not Path(capture_output_dir).is_absolute():
                capture_output_dir = Path(capture_output_dir).name
            job_data['commands']['output_directory'] = str(self.capture_dir / capture_output_dir)

            # Also set output.file for run_jobs_batch.py
            # This will be used as a template - run_jobs_batch will add device hostname
            output_base = self.capture_dir / capture_output_dir / 'output.txt'
            if 'output' not in job_data:
                job_data['output'] = {}
            job_data['output']['file'] = str(output_base)

            logger.debug(f"Set output paths: directory={job_data['commands']['output_directory']}, file={output_base}")

        # Write to temp location
        temp_job_file = self.jobs_dir / job_file.name
        with open(temp_job_file, 'w') as f:
            json.dump(job_data, f, indent=2)

        logger.debug(f"Updated {job_file.name}: PASSWORD AUTH, prompt_count={correct_prompt_count}, output_dir={job_data.get('commands', {}).get('output_directory', 'NOT SET')}")
        return temp_job_file

    def _execute_job_batch(self,
                          job_list_file: Path,
                          credentials: Dict,
                          progress_callback: Optional[Callable] = None) -> Dict:
        """Execute run_jobs_batch.py with password credentials"""

        # Set credentials as environment variables
        env = os.environ.copy()
        env['CRED_1_USER'] = credentials['username']
        env['CRED_1_PASS'] = credentials['password']

        # Set for multiple credential IDs (some devices might use different creds)
        for cred_id in range(1, 11):
            env[f'CRED_{cred_id}_USER'] = credentials['username']
            env[f'CRED_{cred_id}_PASS'] = credentials.get('password', '')

        # SSH key support
        if credentials.get('ssh_key_path'):
            env['PYSSH_KEY'] = str(credentials['ssh_key_path'])
            logger.info(f"Set PYSSH_KEY={credentials['ssh_key_path']}")
        else:
            logger.info("DEBUG: No ssh_key_path in credentials")
        # Build command
        cmd = [
            sys.executable,
            str(self.run_jobs_batch_script),
            str(job_list_file),
            '--json-progress',
            '--jobs-folder', str(self.jobs_source_dir)
        ]

        logger.info(f"Executing: {' '.join(cmd)}")
        logger.info(f"Authentication: PASSWORD (user={credentials['username']})")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env,
                cwd=str(self.pcng_dir)
            )

            # Track results
            total_jobs = 0
            successful_jobs = 0
            failed_jobs = 0
            failed_devices = []

            # Parse JSON progress output
            for line in iter(process.stdout.readline, ''):
                if line:
                    line = line.rstrip()
                    logger.info(f"BATCH: {line}")

                    try:
                        data = json.loads(line)
                        msg_type = data.get('type')

                        if msg_type == 'device_start':
                            # Device started processing
                            if progress_callback:
                                progress_callback({
                                    'stage': 'collecting',
                                    'message': f"▶ Starting {data.get('device_name')}...",
                                    'device_name': data.get('device_name'),
                                    'device_started': data.get('device_name'),
                                    'ip_address': data.get('ip_address')
                                })

                        elif msg_type == 'device_complete':
                            # Device completed (success or failure)
                            device_name = data.get('device_name')
                            success = data.get('success', False)
                            message = data.get('message', '')

                            if not success:
                                failed_devices.append({
                                    'name': device_name,
                                    'error': message
                                })

                            if progress_callback:
                                status = '✓' if success else '✗'
                                progress_callback({
                                    'stage': 'collecting',
                                    'message': f"{status} {device_name}",
                                    'device_name': device_name,
                                    'device_completed': device_name,
                                    'device_success': success,
                                    'device_message': message
                                })

                        elif msg_type == 'job_start':
                            if progress_callback:
                                progress_callback({
                                    'stage': 'collecting',
                                    'message': f"Starting {data.get('job_name')}...",
                                    'progress': data.get('percent', 0)
                                })

                        elif msg_type == 'job_complete':
                            success = data.get('success', False)
                            if success:
                                successful_jobs += 1
                            else:
                                failed_jobs += 1

                            if progress_callback:
                                status = '✓' if success else '✗'
                                progress_callback({
                                    'stage': 'collecting',
                                    'message': f"{status} {data.get('job_name')}",
                                    'progress': data.get('percent', 0)
                                })

                        elif msg_type == 'summary':
                            total_jobs = data.get('total_jobs', 0)
                            successful_jobs = data.get('successful_jobs', 0)
                            failed_jobs = data.get('failed_jobs', 0)

                    except json.JSONDecodeError:
                        # Regular log line - look for device results
                        if '[SUCCESS]' in line:
                            match = re.search(r'\[SUCCESS\] ([^\s]+)', line)
                            if match and progress_callback:
                                device_name = match.group(1)
                                progress_callback({
                                    'stage': 'collecting',
                                    'message': f'✓ {device_name}',
                                    'device_completed': device_name
                                })

                        elif '[FAILED]' in line or '[ERROR]' in line:
                            match = re.search(r'\[(FAILED|ERROR)\] ([^\s]+)', line)
                            if match:
                                device_name = match.group(2)
                                failed_devices.append({'name': device_name, 'error': 'Failed'})

            return_code = process.wait(timeout=30)

            return {
                'success': return_code == 0,
                'total_jobs': total_jobs,
                'devices_succeeded': successful_jobs,
                'devices_failed': failed_jobs,
                'failed_devices': failed_devices,
                'captures_created': {}
            }

        except subprocess.TimeoutExpired:
            logger.error("Job batch timeout")
            process.kill()
            return {
                'success': False,
                'error': 'Timeout (>1 hour)',
                'devices_succeeded': 0,
                'devices_failed': 0,
                'failed_devices': []
            }
        except Exception as e:
            logger.exception("Job batch execution failed")
            return {
                'success': False,
                'error': str(e),
                'devices_succeeded': 0,
                'devices_failed': 0,
                'failed_devices': []
            }

    def _load_to_database(self,
                         capture_dirs: List[Path],
                         progress_callback: Optional[Callable] = None) -> Dict:
        """
        Load captured data into database

        Note: db_load_capture.py expects the BASE capture directory and looks for
        subdirectories named after each capture type. We pass --capture-types to
        specify which types to load.
        """
        if progress_callback:
            progress_callback({
                'stage': 'loading',
                'message': 'Loading captures into database...',
                'progress': 90
            })

        db_path = self.data_dir / 'assets.db'

        # Extract capture type names from the paths
        # capture_dirs are like [.../capture/configs, .../capture/ospf-neighbor]
        capture_types = [d.name for d in capture_dirs]

        # Filter to only types that have actual capture directories
        existing_types = [ct for ct in capture_types if (self.capture_dir / ct).exists()]

        if not existing_types:
            logger.warning(f"No capture directories found for types: {capture_types}")
            return {
                'success': False,
                'error': 'No capture directories found',
                'loaded_count': 0,
                'total_requested': len(capture_types)
            }

        try:
            # Call db_load_capture.py ONCE with base capture dir and list of types
            cmd = [
                sys.executable,
                str(self.db_load_script),
                '--data-dir', str(self.data_dir),  # Base data directory
                '--db-path', str(db_path),
                '--captures-dir', str(self.capture_dir),  # Base capture directory
                '--capture-types', ','.join(existing_types),  # Comma-separated types
                '--verbose'
            ]

            logger.info(f"Loading captures: {' '.join(cmd)}")
            logger.info(f"Capture types to load: {existing_types}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode == 0:
                logger.info(f"✓ Loaded captures for types: {', '.join(existing_types)}")
                if result.stdout:
                    logger.debug(f"db_load_capture stdout:\n{result.stdout}")
                return {
                    'success': True,
                    'loaded_count': len(existing_types),
                    'total_requested': len(capture_types)
                }
            else:
                logger.error(f"✗ Failed to load captures")
                if result.stderr:
                    logger.error(f"db_load_capture stderr: {result.stderr}")
                if result.stdout:
                    logger.error(f"db_load_capture stdout: {result.stdout}")
                return {
                    'success': False,
                    'error': result.stderr or 'Unknown error',
                    'loaded_count': 0,
                    'total_requested': len(capture_types)
                }

        except subprocess.TimeoutExpired:
            logger.error("db_load_capture.py timed out after 600 seconds")
            return {
                'success': False,
                'error': 'Database loading timed out',
                'loaded_count': 0,
                'total_requested': len(capture_types)
            }
        except Exception as e:
            logger.exception("Database loading failed")
            return {
                'success': False,
                'error': str(e),
                'loaded_count': 0
            }