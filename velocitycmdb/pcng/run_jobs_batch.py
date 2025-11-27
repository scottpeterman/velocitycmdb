#!/usr/bin/env python3
"""
Simplified Network Job Batch Runner
Password-only authentication via environment variables
CONCURRENT execution of network automation jobs
"""

import sys
import os
import json
import yaml
import subprocess
import argparse
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed


class ProgressTracker:
    """Tracks job execution progress and calculates ETAs (thread-safe)"""

    def __init__(self, total_jobs: int, json_mode: bool = False):
        self.total_jobs = total_jobs
        self.completed_jobs = 0  # Track COMPLETED, not started
        self.json_mode = json_mode
        self.start_time = time.time()
        self.job_durations = deque(maxlen=5)
        self.lock = threading.Lock()

    def emit_progress(self, message_type: str, **kwargs):
        """Emit progress message in JSON or human-readable format"""
        if self.json_mode:
            msg = {"type": message_type, "timestamp": datetime.now().isoformat(), **kwargs}
            with self.lock:
                print(json.dumps(msg), flush=True)

    def start_job(self, job_name: str, job_num: int):
        """Mark the start of a job"""
        # Don't update progress on start, only on completion
        self.emit_progress(
            "job_start",
            job_name=job_name,
            job_num=job_num,
            total_jobs=self.total_jobs
        )

    def complete_job(self, job_name: str, success: bool, duration: float):
        """Mark the completion of a job"""
        with self.lock:
            self.completed_jobs += 1  # Increment on completion
            self.job_durations.append(duration)
            percent = int((self.completed_jobs / self.total_jobs) * 100) if self.total_jobs > 0 else 0
            eta_seconds = self.calculate_eta()

        self.emit_progress(
            "job_complete",
            job_name=job_name,
            completed=self.completed_jobs,
            total_jobs=self.total_jobs,
            success=success,
            duration=duration,
            percent=percent,
            eta_seconds=eta_seconds
        )

    def calculate_eta(self) -> Optional[float]:
        """Calculate estimated time to completion (call with lock held)"""
        if not self.job_durations or self.completed_jobs >= self.total_jobs:
            return None

        avg_duration = sum(self.job_durations) / len(self.job_durations)
        remaining_jobs = self.total_jobs - self.completed_jobs

        return avg_duration * remaining_jobs

    def emit_overall_progress(self):
        """Emit overall progress update"""
        with self.lock:
            percent = int((self.completed_jobs / self.total_jobs) * 100) if self.total_jobs > 0 else 0
            eta_seconds = self.calculate_eta()
            elapsed = time.time() - self.start_time

        self.emit_progress(
            "progress",
            current=self.completed_jobs,
            total=self.total_jobs,
            percent=percent,
            eta_seconds=eta_seconds,
            elapsed_seconds=elapsed
        )


class VendorCommandManager:
    """Manages vendor-specific command templates"""

    def __init__(self):
        self.vendor_configs = {
            'cisco': {
                'paging_disable': 'terminal length 0',
                'description': 'Cisco IOS/IOS-XE devices'
            },
            'arista': {
                'paging_disable': 'terminal length 0',
                'description': 'Arista EOS devices'
            },
            'paloalto': {
                'paging_disable': 'set cli pager off',
                'description': 'Palo Alto firewalls'
            },
            'cloudgenix': {
                'paging_disable': 'set paging off',
                'description': 'CloudGenix SD-WAN devices'
            },
            'juniper': {
                'paging_disable': 'set cli screen-length 0',
                'description': 'Juniper JunOS devices'
            },
            'fortinet': {
                'paging_disable': 'config system console\nset output standard\nend',
                'description': 'Fortinet FortiGate firewalls'
            },
            'generic': {
                'paging_disable': '',
                'description': 'Generic/Unknown devices'
            }
        }

    def get_vendor_config(self, vendor: str) -> Dict[str, str]:
        """Get configuration for a specific vendor (handles variations like cisco-ios, cisco-nxos)"""
        vendor_lower = vendor.lower()

        # Direct match first
        if vendor_lower in self.vendor_configs:
            return self.vendor_configs[vendor_lower]

        # Try prefix match (cisco-ios -> cisco, cisco-nxos -> cisco)
        for key in self.vendor_configs.keys():
            if vendor_lower.startswith(key):
                return self.vendor_configs[key]

        # Fallback to generic
        return self.vendor_configs['generic']

    def build_command_with_paging(self, vendor: str, commands: str) -> str:
        """Build command string with vendor-specific paging disable prefix"""
        config = self.get_vendor_config(vendor)
        paging_cmd = config['paging_disable']

        if paging_cmd and commands:
            return f"{paging_cmd},{commands}"
        elif paging_cmd:
            return paging_cmd
        else:
            return commands


class JobExecutor:
    """Executes individual network automation jobs (thread-safe)"""

    def __init__(self, vendor_manager: VendorCommandManager, verbose: bool = False, json_mode: bool = False):
        self.vendor_manager = vendor_manager
        self.verbose = verbose
        self.json_mode = json_mode
        self.log_lock = threading.Lock()

    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp (thread-safe)"""
        with self.log_lock:
            if self.json_mode:
                log_msg = {
                    "type": "log",
                    "level": level,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                    "thread": threading.current_thread().name
                }
                print(json.dumps(log_msg), flush=True)
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                thread_name = threading.current_thread().name
                print(f"[{timestamp}] [{level}] [{thread_name}] {message}", flush=True)

    def get_credential_env_vars(self, job_config: Dict[str, Any]) -> Dict[str, str]:
        """Get environment variables for credentials from job config"""
        env_vars = {}

        credentials = job_config.get('credentials', {})
        username = credentials.get('username', '')

        if username:
            # Set credential env vars for password-based auth
            for cred_id in range(1, 11):
                env_vars[f'CRED_{cred_id}_USER'] = username

            self.log(f"Configured credentials for user: {username}")
            self.log("Note: Passwords must be set via CRED_*_PASS environment variables")

        return env_vars

    def execute_job(self, job_config: Dict[str, Any], job_name: str) -> Dict[str, Any]:
        """Execute a single job configuration with CONCURRENT device execution"""
        start_time = time.time()

        try:
            self.log(f"Starting job: {job_name}")

            # Validate job configuration
            required_fields = ['session_file', 'commands', 'execution']
            for field in required_fields:
                if field not in job_config:
                    raise ValueError(f"Missing required field: {field}")

            session_file = job_config['session_file']
            if not os.path.exists(session_file):
                raise FileNotFoundError(f"Session file not found: {session_file}")

            # Extract configuration
            vendor_info = job_config.get('vendor', {})
            vendor = vendor_info.get('selected', 'generic').lower()
            auto_paging = vendor_info.get('auto_paging', True)

            filters = job_config.get('filters', {})
            commands_info = job_config.get('commands', {})
            commands_str = commands_info.get('command_text', '') or commands_info.get('command_string', '')

            self.log(f"Commands from job config: '{commands_str}'", "DEBUG")
            if not commands_str:
                self.log(f"WARNING: No commands found in job config!", "WARNING")
                self.log(f"Job config 'commands' section: {commands_info}", "DEBUG")

            execution_config = job_config.get('execution', {})
            prompt_count = execution_config.get('prompt_count', 1)
            timeout = execution_config.get('timeout', 60)
            expect_prompt_timeout = execution_config.get('expect_prompt_timeout', 30000)

            # NEW: Get max concurrent devices from job config or default to 10
            max_device_workers = execution_config.get('max_device_workers', 10)

            output_config = job_config.get('output', {})
            output_file = output_config.get('file', '')

            self.log(f"Vendor: {vendor}, Auto-paging: {auto_paging}")
            self.log(f"Session file: {session_file}")
            self.log(f"Concurrent device workers: {max_device_workers}")

            # Build commands with paging disable if enabled
            if auto_paging:
                paging_cmd = self.vendor_manager.get_vendor_config(vendor)['paging_disable']
                if paging_cmd and paging_cmd not in commands_str:
                    commands_str = self.vendor_manager.build_command_with_paging(vendor, commands_str)
                    self.log(f"Added vendor-specific paging disable command: {paging_cmd}")
                elif paging_cmd:
                    self.log(f"Paging command already in commands, skipping: {paging_cmd}", "DEBUG")
                else:
                    self.log(f"No paging command for vendor: {vendor}", "DEBUG")

            self.log(f"Using prompt_count from job file: {prompt_count}", "DEBUG")

            # Load session data
            session_data = self._load_session_file(session_file, filters)
            if not session_data:
                raise ValueError("No devices found in session file matching filters")

            self.log(f"Loaded {len(session_data)} devices from session")

            # Get credential environment variables
            cred_env_vars = self.get_credential_env_vars(job_config)

            # Execute against each device - CONCURRENT
            commands_str += ",,"
            device_results = []

            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=max_device_workers) as device_pool:
                # Submit all device tasks
                futures = {
                    device_pool.submit(
                        self._execute_on_device,
                        device=device,
                        commands=commands_str,
                        output_file=output_file,
                        prompt_count=prompt_count,
                        timeout=timeout,
                        expect_prompt_timeout=expect_prompt_timeout,
                        cred_env_vars=cred_env_vars
                    ): device
                    for device in session_data
                }

                # Collect results as they complete
                for future in as_completed(futures):
                    device = futures[future]
                    hostname = (device.get('hostname') or device.get('display_name') or
                                device.get('name') or 'unknown')
                    try:
                        device_result = future.result()
                        device_results.append(device_result)
                    except Exception as e:
                        self.log(f"  ✗ {hostname} exception: {e}", "ERROR")
                        device_results.append({
                            'success': False,
                            'device': hostname,
                            'error': str(e)
                        })

            # Calculate success
            successful_devices = sum(1 for r in device_results if r.get('success', False))
            success = successful_devices == len(device_results)

            execution_time = time.time() - start_time

            result = {
                'success': success,
                'job_name': job_name,
                'execution_time': execution_time,
                'total_devices': len(device_results),
                'successful_devices': successful_devices,
                'failed_devices': len(device_results) - successful_devices,
                'device_results': device_results
            }

            if success:
                self.log(f"Job completed successfully in {execution_time:.1f}s")
            else:
                self.log(f"Job completed with errors in {execution_time:.1f}s", "WARNING")

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            self.log(f"Job failed: {error_msg}", "ERROR")

            return {
                'success': False,
                'job_name': job_name,
                'execution_time': execution_time,
                'error': error_msg
            }

    def _load_session_file(self, session_file: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Load and filter devices from session file"""
        try:
            # Determine file type
            file_ext = os.path.splitext(session_file)[1].lower()

            if file_ext == '.json':
                with open(session_file, 'r') as f:
                    data = json.load(f)
            elif file_ext in ['.yaml', '.yml']:
                with open(session_file, 'r') as f:
                    data = yaml.safe_load(f)
            else:
                raise ValueError(f"Unsupported session file format: {file_ext}")

            # Extract devices list - handle multiple formats
            devices = []

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if 'sessions' in item and 'folder_name' in item:
                            folder_name = item['folder_name']
                            for device in item.get('sessions', []):
                                device['folder_name'] = folder_name
                                devices.append(device)
                        else:
                            devices.append(item)
            elif isinstance(data, dict):
                if 'devices' in data:
                    devices = data['devices']
                elif 'sessions' in data:
                    devices = data['sessions']
                else:
                    devices = [data]
            else:
                raise ValueError("Invalid session file format")

            # Apply filters
            if filters:
                devices = self._apply_filters(devices, filters)

            return devices

        except Exception as e:
            raise ValueError(f"Error loading session file: {str(e)}")

    def _apply_filters(self, devices: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Apply filters to device list with flexible matching"""
        filtered = devices

        if 'vendor' in filters and filters['vendor']:
            vendor_filter = filters['vendor'].lower()

            def matches_vendor(device):
                device_vendor = (device.get('vendor', '') or device.get('Vendor', '')).lower()
                device_type = (device.get('DeviceType', '') or device.get('device_type', '')).lower()

                if vendor_filter in device_vendor:
                    return True

                if 'cisco' in vendor_filter:
                    if 'cisco' in device_vendor:
                        if 'ios' in vendor_filter and 'nx-os' not in vendor_filter and 'nxos' not in vendor_filter:
                            return 'ios' in device_type and 'nxos' not in device_type
                        elif 'nx-os' in vendor_filter or 'nxos' in vendor_filter:
                            return 'nxos' in device_type
                        else:
                            return True

                return False

            filtered = [d for d in filtered if matches_vendor(d)]

        if 'site' in filters and filters['site']:
            site_filter = filters['site'].lower()
            filtered = [d for d in filtered
                        if site_filter in d.get('site', '').lower() or
                        site_filter in d.get('folder_name', '').lower()]

        if 'role' in filters and filters['role']:
            role_filter = filters['role'].lower()
            filtered = [d for d in filtered
                        if role_filter in d.get('role', '').lower() or
                        role_filter in d.get('display_name', '').lower()]

        return filtered

    def _execute_on_device(self, device: Dict[str, Any], commands: str, output_file: str,
                           prompt_count: int, timeout: int, expect_prompt_timeout: int,
                           cred_env_vars: Dict[str, str]) -> Dict[str, Any]:
        """Execute commands on a single device"""
        hostname = (device.get('hostname') or device.get('display_name') or
                    device.get('name') or 'unknown')
        ip_address = (device.get('ip_address') or device.get('host') or
                      device.get('ip') or '')

        try:
            # Emit device start event
            if self.json_mode:
                device_start_msg = {
                    "type": "device_start",
                    "timestamp": datetime.now().isoformat(),
                    "device_name": hostname,
                    "ip_address": ip_address
                }
                with self.log_lock:
                    print(json.dumps(device_start_msg), flush=True)

            self.log(f"  Executing on {hostname} ({ip_address})")

            cmd_parts = [
                sys.executable, 'spn.py',
                '--host', ip_address,
                '-c', commands,
                '--prompt-count', str(prompt_count),
                '--timeout', str(timeout),
            ]

            if 'CRED_1_USER' in cred_env_vars:
                cmd_parts.extend(['-u', cred_env_vars['CRED_1_USER']])

            device_output = None
            if output_file:
                output_dir = os.path.dirname(output_file)
                device_output = os.path.join(output_dir, f'{hostname}.txt')
                cmd_parts.extend(['-o', device_output])

            self.log(f"  CMD: {' '.join(cmd_parts)}", "DEBUG")
            self.log(f"  Credentials: CRED_1_USER={cred_env_vars.get('CRED_1_USER', 'NOT SET')}", "DEBUG")
            self.log(f"  Output file: {device_output if output_file else 'NONE'}", "DEBUG")

            env = os.environ.copy()
            env.update(cred_env_vars)

            if 'CRED_1_USER' in cred_env_vars:
                env['SSH_USER'] = cred_env_vars['CRED_1_USER']
            if 'CRED_1_PASS' in env:
                env['SSH_PASSWORD'] = env['CRED_1_PASS']

            result = subprocess.run(
                cmd_parts,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )

            success = result.returncode == 0

            if result.stderr:
                self.log(f"  STDERR: {result.stderr}", "DEBUG")

            if result.stdout:
                self.log(f"  STDOUT length: {len(result.stdout)} chars", "DEBUG")

            # Emit device completion event
            if self.json_mode:
                device_complete_msg = {
                    "type": "device_complete",
                    "timestamp": datetime.now().isoformat(),
                    "device_name": hostname,
                    "ip_address": ip_address,
                    "success": success,
                    "message": "Completed successfully" if success else (result.stderr or result.stdout or "Failed")
                }
                with self.log_lock:
                    print(json.dumps(device_complete_msg), flush=True)

            if success:
                self.log(f"  ✓ {hostname} completed successfully")
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                self.log(f"  ✗ {hostname} failed: {error_msg}", "ERROR")

            return {
                'success': success,
                'hostname': hostname,
                'ip_address': ip_address,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }

        except Exception as e:
            # Emit device failure event
            if self.json_mode:
                device_complete_msg = {
                    "type": "device_complete",
                    "timestamp": datetime.now().isoformat(),
                    "device_name": hostname,
                    "ip_address": ip_address,
                    "success": False,
                    "message": str(e)
                }
                with self.log_lock:
                    print(json.dumps(device_complete_msg), flush=True)

            self.log(f"  ✗ {hostname} error: {str(e)}", "ERROR")
            return {
                'success': False,
                'hostname': hostname,
                'ip_address': ip_address,
                'error': str(e)
            }


class JobBatchRunner:
    """Manages batch execution of multiple jobs with concurrent execution"""

    def __init__(self, verbose: bool = False, json_mode: bool = False):
        self.vendor_manager = VendorCommandManager()
        self.executor = JobExecutor(self.vendor_manager, verbose, json_mode)
        self.verbose = verbose
        self.json_mode = json_mode

    def log(self, message: str):
        """Log message"""
        self.executor.log(message)

    def run_batch(self, job_list_file: str, continue_on_error: bool = True,
                  max_retries: int = 0, jobs_folder: Optional[str] = None,
                  max_workers: int = 5) -> Dict[str, Any]:
        """Run a batch of jobs from a job list file with concurrent execution"""
        start_time = time.time()

        # Load job files
        job_files = self._load_job_list(job_list_file, jobs_folder)

        if not job_files:
            self.log("No job files found in job list")
            return {'success': False, 'error': 'No jobs to execute'}

        self.log(f"Loaded {len(job_files)} jobs from {job_list_file}")
        self.log(f"Running with {max_workers} concurrent workers")

        # Initialize progress tracker
        progress_tracker = ProgressTracker(len(job_files), self.json_mode)

        # Thread-safe counters
        results_lock = threading.Lock()
        results = []
        successful_jobs = 0
        failed_jobs = 0
        job_counter = 0

        def execute_job_with_tracking(job_file):
            """Execute a single job with progress tracking"""
            nonlocal job_counter, successful_jobs, failed_jobs

            job_name = os.path.basename(job_file)

            with results_lock:
                job_counter += 1
                current_job_num = job_counter

            # Start job tracking
            progress_tracker.start_job(job_name, current_job_num)

            # Load job config
            try:
                with open(job_file, 'r') as f:
                    job_config = json.load(f)
            except Exception as e:
                self.log(f"Error loading job config {job_file}: {str(e)}", "ERROR")
                with results_lock:
                    failed_jobs += 1
                return None

            # Execute job with retries
            job_result = None
            for attempt in range(max_retries + 1):
                if attempt > 0:
                    self.log(f"Retry attempt {attempt}/{max_retries} for {job_name}")

                job_result = self.executor.execute_job(job_config, job_name)

                if job_result['success']:
                    break

            # Track result
            with results_lock:
                if job_result['success']:
                    successful_jobs += 1
                else:
                    failed_jobs += 1

            # Complete job tracking
            progress_tracker.complete_job(
                job_name,
                job_result['success'],
                job_result['execution_time']
            )

            # Emit overall progress
            progress_tracker.emit_overall_progress()

            return job_result

        # Execute jobs concurrently
        with ThreadPoolExecutor(max_workers=max_workers) as executor_pool:
            future_to_job = {executor_pool.submit(execute_job_with_tracking, job_file): job_file
                             for job_file in job_files}

            for future in as_completed(future_to_job):
                job_file = future_to_job[future]
                try:
                    job_result = future.result()
                    if job_result:
                        with results_lock:
                            results.append(job_result)

                        # Check if should stop on error
                        if not continue_on_error and not job_result['success']:
                            self.log(f"Stopping batch due to job failure", "WARNING")
                            # Cancel remaining jobs
                            for f in future_to_job:
                                if not f.done():
                                    f.cancel()
                            break
                except Exception as e:
                    self.log(f"Unexpected error executing {job_file}: {str(e)}", "ERROR")
                    with results_lock:
                        failed_jobs += 1

        # Generate summary
        total_time = time.time() - start_time

        self.log("=" * 60)
        self.log("BATCH EXECUTION SUMMARY")
        self.log("=" * 60)
        self.log(f"Total jobs: {len(job_files)}")
        self.log(f"Successful: {successful_jobs}")
        self.log(f"Failed: {failed_jobs}")
        self.log(f"Total execution time: {total_time:.1f}s")
        self.log(f"Average time per job: {total_time / len(job_files):.1f}s")

        # Emit final summary in JSON mode
        if self.json_mode:
            summary = {
                "type": "summary",
                "total_jobs": len(job_files),
                "successful_jobs": successful_jobs,
                "failed_jobs": failed_jobs,
                "total_time": total_time,
                "timestamp": datetime.now().isoformat()
            }
            print(json.dumps(summary), flush=True)

        return {
            'success': failed_jobs == 0,
            'total_jobs': len(job_files),
            'successful_jobs': successful_jobs,
            'failed_jobs': failed_jobs,
            'total_time': total_time,
            'job_results': results
        }

    def _load_job_list(self, job_list_file: str, jobs_folder: Optional[str]) -> List[str]:
        """Load job file list from file"""
        job_files = []

        try:
            with open(job_list_file, 'r') as f:
                for line in f:
                    line = line.strip()

                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue

                    # Resolve path
                    if os.path.isabs(line):
                        job_path = line
                    elif jobs_folder:
                        job_path = os.path.join(jobs_folder, line)
                    else:
                        job_path = line

                    if os.path.exists(job_path):
                        job_files.append(job_path)
                    else:
                        self.log(f"Warning: Job file not found: {job_path}", "WARNING")

        except Exception as e:
            self.log(f"Error loading job list: {str(e)}", "ERROR")

        return job_files


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Simplified Network Job Batch Runner - CONCURRENT execution",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'job_list_file',
        help='File containing list of job configuration files'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )

    parser.add_argument(
        '--json-progress',
        action='store_true',
        help='Output progress as JSON lines'
    )

    parser.add_argument(
        '--stop-on-error',
        action='store_true',
        help='Stop if any job fails'
    )

    parser.add_argument(
        '--retries', '-r',
        type=int,
        default=0,
        help='Number of retry attempts (default: 0)'
    )

    parser.add_argument(
        '--jobs-folder', '-j',
        help='Folder containing job configuration files'
    )

    parser.add_argument(
        '--max-workers', '-w',
        type=int,
        default=5,
        help='Maximum number of concurrent workers (default: 5)'
    )

    args = parser.parse_args()

    # Validate arguments
    if not os.path.exists(args.job_list_file):
        print(f"Error: Job list file not found: {args.job_list_file}")
        return 1

    try:
        # Create and run batch runner
        batch_runner = JobBatchRunner(verbose=args.verbose, json_mode=args.json_progress)

        result = batch_runner.run_batch(
            job_list_file=args.job_list_file,
            continue_on_error=not args.stop_on_error,
            max_retries=args.retries,
            jobs_folder=args.jobs_folder,
            max_workers=args.max_workers
        )

        return 0 if result['success'] else 1

    except KeyboardInterrupt:
        print("\nBatch execution interrupted by user")
        return 1
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())