#!/usr/bin/env python3
"""
Network Job Batch Runner CLI - Concurrent Edition
Parallel execution of multiple network automation job configurations
Enhanced with SSH key authentication support and real-time output
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue


class VendorCommandManager:
    """Manages vendor-specific command templates and prefixes"""

    def __init__(self):
        self.vendor_configs = {
            'cisco': {
                'paging_disable': 'terminal length 0',
                'additional_args': '--invoke-shell',
                'description': 'Cisco IOS/IOS-XE devices'
            },
            'arista': {
                'paging_disable': 'terminal length 0',
                'additional_args': '',
                'description': 'Arista EOS devices'
            },
            'paloalto': {
                'paging_disable': 'set cli pager off',
                'additional_args': '--prompt-count 3 --expect-prompt-timeout 15000 --invoke-shell',
                'description': 'Palo Alto firewalls'
            },
            'cloudgenix': {
                'paging_disable': 'set paging off',
                'additional_args': '--prompt-count 3 --expect-prompt-timeout 15000 --invoke-shell',
                'description': 'CloudGenix SD-WAN devices'
            },
            'juniper': {
                'paging_disable': 'set cli screen-length 0',
                'additional_args': '--invoke-shell',
                'description': 'Juniper JunOS devices'
            },
            'fortinet': {
                'paging_disable': 'config system console\nset output standard\nend',
                'additional_args': '--invoke-shell',
                'description': 'Fortinet FortiGate firewalls'
            },
            'generic': {
                'paging_disable': '',
                'additional_args': '',
                'description': 'Generic/Unknown devices (no paging disable)'
            }
        }

    def get_vendor_config(self, vendor: str) -> Dict[str, str]:
        """Get configuration for a specific vendor"""
        return self.vendor_configs.get(vendor.lower(), self.vendor_configs['generic'])


class JobExecutor:
    """Executes individual network automation jobs"""

    def __init__(self, vendor_manager: VendorCommandManager, verbose: bool = False):
        self.vendor_manager = vendor_manager
        self.verbose = verbose
        self.log_lock = threading.Lock()

    def log(self, message: str, level: str = "INFO", job_id: str = ""):
        """Thread-safe log message with timestamp and flush immediately"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"[Job {job_id}] " if job_id else ""
        with self.log_lock:
            print(f"[{timestamp}] [{level}] {prefix}{message}", flush=True)

    def get_credential_env_vars(self, job_config: Dict[str, Any], use_keys: bool = False) -> Dict[str, str]:
        """Get environment variables for credentials from job config"""
        env_vars = {}

        credentials = job_config.get('credentials', {})
        username = credentials.get('username', '')

        if username:
            for cred_id in range(1, 11):
                env_vars[f'CRED_{cred_id}_USER'] = username
                if use_keys:
                    env_vars[f'CRED_{cred_id}_PASS'] = 'notneeded'

        return env_vars

    def execute_job(self, job_config: Dict[str, Any], job_name: str, job_number: int, total_jobs: int) -> Dict[
        str, Any]:
        """Execute a single job configuration"""
        start_time = time.time()
        job_id = f"{job_number}/{total_jobs}"

        try:
            self.log(f"Starting job: {job_name}", job_id=job_id)

            # Validate job configuration
            required_fields = ['session_file', 'commands', 'execution']
            for field in required_fields:
                if field not in job_config:
                    raise ValueError(f"Missing required field in job config: {field}")

            session_file = job_config['session_file']
            if not os.path.exists(session_file):
                raise FileNotFoundError(f"Session file not found: {session_file}")

            # Extract configuration
            vendor_info = job_config.get('vendor', {})
            vendor = vendor_info.get('selected', 'generic').lower()

            filters = job_config.get('filters', {})
            commands_info = job_config.get('commands', {})
            execution_info = job_config.get('execution', {})

            # Authentication configuration
            auth_config = job_config.get('authentication', {})
            use_keys = auth_config.get('use_keys', True)
            ssh_key_path = auth_config.get('ssh_key_path', '~/.ssh/admin/id_rsa')

            if ssh_key_path:
                ssh_key_path = os.path.expanduser(ssh_key_path)

            final_commands = commands_info.get('command_text', '')
            output_dir = commands_info.get('output_directory', 'output')

            # Determine batch script
            batch_script = "batch_spn.py"

            if not os.path.exists(batch_script):
                raise FileNotFoundError(f"Batch script not found: {batch_script}")

            # Build command arguments with unbuffered output
            cmd_args = [sys.executable, '-u', batch_script, session_file]

            # Add authentication options
            if use_keys:
                cmd_args.append('--use-keys')
                if ssh_key_path and ssh_key_path.strip():
                    cmd_args.extend(['--ssh-key', ssh_key_path.strip()])
                    self.log(f"Using SSH key: {ssh_key_path.strip()}", job_id=job_id)

            # Add filters
            filter_mapping = [
                ('--folder', filters.get('folder')),
                ('--name', filters.get('name')),
                ('--vendor', filters.get('vendor')),
                ('--device-type', filters.get('device_type'))
            ]

            for filter_name, filter_value in filter_mapping:
                if filter_value and filter_value.strip():
                    cmd_args.extend([filter_name, filter_value.strip()])
                    self.log(f"Applied filter: {filter_name} = '{filter_value.strip()}'", job_id=job_id)

            # Add fingerprinting options
            fingerprint_options = job_config.get('fingerprint_options', {})

            if fingerprint_options.get('fingerprinted_only') is True:
                cmd_args.append('--fingerprinted-only')
            elif fingerprint_options.get('fingerprint_only') is True:
                cmd_args.append('--fingerprint-only')
            elif fingerprint_options.get('fingerprint') is True:
                cmd_args.append('--fingerprint')

            # Add execution parameters
            cmd_args.extend(['-c', final_commands])
            cmd_args.extend(['-o', output_dir])

            # Add execution settings
            max_workers = execution_info.get('max_workers', 5)
            dry_run = execution_info.get('dry_run', False)

            cmd_args.extend(['--max-workers', str(max_workers)])

            if dry_run:
                cmd_args.append('--dry-run')

            # Set up environment
            env = os.environ.copy()
            credential_vars = self.get_credential_env_vars(job_config, use_keys)
            env.update(credential_vars)

            # Log execution details
            self.log(f"Commands: {final_commands}", job_id=job_id)
            self.log(f"Output: capture/{output_dir}", job_id=job_id)
            self.log(f"Auth: {'key-based' if use_keys else 'password-based'}", job_id=job_id)

            # Execute with real-time streaming
            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )

            stdout_lines = []
            for line in iter(process.stdout.readline, ''):
                if line:
                    # Prefix output with job ID for concurrent execution clarity
                    prefixed_line = f"[Job {job_id}] {line.rstrip()}"
                    with self.log_lock:
                        print(prefixed_line, flush=True)
                    stdout_lines.append(line)

            process.wait()
            stdout = ''.join(stdout_lines)
            execution_time = time.time() - start_time

            # Prepare result
            result = {
                'job_name': job_name,
                'job_number': job_number,
                'success': process.returncode == 0,
                'return_code': process.returncode,
                'execution_time': execution_time,
                'output_directory': f"capture/{output_dir}",
                'commands': final_commands,
                'auth_method': 'key-based' if use_keys else 'password-based',
                'stdout': stdout,
                'stderr': ''
            }

            if result['success']:
                self.log(f"✓ Completed successfully in {execution_time:.1f}s", job_id=job_id)
            else:
                self.log(f"✗ Failed after {execution_time:.1f}s (exit code: {process.returncode})",
                         level="ERROR", job_id=job_id)

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            self.log(f"✗ Exception: {error_msg}", level="ERROR", job_id=job_id)

            return {
                'job_name': job_name,
                'job_number': job_number,
                'success': False,
                'return_code': -1,
                'execution_time': execution_time,
                'error': error_msg,
                'stdout': '',
                'stderr': ''
            }


class JobBatchRunner:
    """Manages concurrent batch execution of multiple network automation jobs"""

    def __init__(self, verbose: bool = False, max_concurrent: int = 3):
        self.vendor_manager = VendorCommandManager()
        self.job_executor = JobExecutor(self.vendor_manager, verbose)
        self.verbose = verbose
        self.max_concurrent = max_concurrent
        self.log_lock = threading.Lock()

    def log(self, message: str, level: str = "INFO"):
        """Thread-safe log message with timestamp and flush immediately"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.log_lock:
            print(f"[{timestamp}] [{level}] {message}", flush=True)

    def load_job_list(self, job_list_file: str, jobs_folder: str = None) -> List[str]:
        """Load list of job configuration files"""
        job_files = []

        try:
            with open(job_list_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()

                    if not line or line.startswith('#'):
                        continue

                    job_file = line

                    if jobs_folder:
                        if not os.path.isabs(job_file):
                            job_file = os.path.join(jobs_folder, job_file)
                    elif not os.path.isabs(job_file):
                        job_list_dir = os.path.dirname(os.path.abspath(job_list_file))
                        job_file = os.path.join(job_list_dir, job_file)

                    if not os.path.exists(job_file):
                        self.log(f"Warning: Job file not found (line {line_num}): {job_file}", "WARN")
                        continue

                    job_files.append(job_file)

            self.log(f"Loaded {len(job_files)} job configuration files")
            return job_files

        except Exception as e:
            raise RuntimeError(f"Failed to load job list file: {str(e)}")

    def load_job_config(self, job_file: str) -> Dict[str, Any]:
        """Load a job configuration file"""
        try:
            with open(job_file, 'r', encoding='utf-8') as f:
                job_config = json.load(f)

            if not isinstance(job_config, dict):
                raise ValueError("Job configuration must be a dictionary")

            return job_config

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in job file {job_file}: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Failed to load job file {job_file}: {str(e)}")

    def execute_job_wrapper(self, job_file: str, job_number: int, total_jobs: int,
                            max_retries: int) -> Dict[str, Any]:
        """Wrapper for job execution with retry logic"""
        job_name = os.path.basename(job_file)

        try:
            job_config = self.load_job_config(job_file)

            # Execute with retries
            attempts = 0
            job_result = None

            while attempts <= max_retries:
                if attempts > 0:
                    self.log(f"[Job {job_number}/{total_jobs}] Retry attempt {attempts}/{max_retries} for {job_name}")
                    time.sleep(2)

                job_result = self.job_executor.execute_job(job_config, job_name, job_number, total_jobs)

                if job_result['success']:
                    break

                attempts += 1

            return job_result

        except Exception as e:
            return {
                'job_name': job_name,
                'job_number': job_number,
                'success': False,
                'return_code': -1,
                'execution_time': 0,
                'error': f"Failed to load/execute job: {str(e)}"
            }

    def run_batch(self, job_list_file: str, continue_on_error: bool = True,
                  max_retries: int = 0, jobs_folder: str = None) -> Dict[str, Any]:
        """Run a batch of jobs concurrently"""

        self.log("=" * 60)
        self.log("NETWORK JOB BATCH RUNNER (CONCURRENT) STARTING")
        self.log("=" * 60)
        self.log(f"Max concurrent jobs: {self.max_concurrent}")

        if jobs_folder:
            self.log(f"Jobs folder: {jobs_folder}")

        start_time = time.time()

        # Load job list
        try:
            job_files = self.load_job_list(job_list_file, jobs_folder)
        except Exception as e:
            self.log(f"Failed to load job list: {str(e)}", "ERROR")
            return {'success': False, 'error': str(e)}

        if not job_files:
            self.log("No valid job files found in job list", "ERROR")
            return {'success': False, 'error': 'No valid job files found'}

        total_jobs = len(job_files)
        results = []
        successful_jobs = 0
        failed_jobs = 0
        early_exit = False

        # Execute jobs concurrently using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            # Submit all jobs
            future_to_job = {
                executor.submit(
                    self.execute_job_wrapper,
                    job_file,
                    i,
                    total_jobs,
                    max_retries
                ): (i, job_file)
                for i, job_file in enumerate(job_files, 1)
            }

            # Process completed jobs as they finish
            for future in as_completed(future_to_job):
                job_number, job_file = future_to_job[future]
                job_name = os.path.basename(job_file)

                try:
                    job_result = future.result()
                    results.append(job_result)

                    if job_result['success']:
                        successful_jobs += 1
                        self.log(f"✓ Job {job_number}/{total_jobs} ({job_name}) completed successfully")
                    else:
                        failed_jobs += 1
                        self.log(f"✗ Job {job_number}/{total_jobs} ({job_name}) failed", "ERROR")

                        if not continue_on_error:
                            self.log("Stopping batch execution due to job failure", "ERROR")
                            early_exit = True
                            # Cancel remaining futures
                            for f in future_to_job:
                                f.cancel()
                            break

                except Exception as e:
                    failed_jobs += 1
                    self.log(f"✗ Job {job_number}/{total_jobs} ({job_name}) exception: {str(e)}", "ERROR")

                    error_result = {
                        'job_name': job_name,
                        'job_number': job_number,
                        'success': False,
                        'return_code': -1,
                        'execution_time': 0,
                        'error': str(e)
                    }
                    results.append(error_result)

                    if not continue_on_error:
                        self.log("Stopping batch execution due to job failure", "ERROR")
                        early_exit = True
                        for f in future_to_job:
                            f.cancel()
                        break

        # Sort results by job number for consistent reporting
        results.sort(key=lambda x: x.get('job_number', 0))

        # Generate summary
        total_time = time.time() - start_time

        self.log("=" * 60)
        self.log("BATCH EXECUTION SUMMARY")
        self.log("=" * 60)
        self.log(f"Total jobs: {total_jobs}")
        self.log(f"Completed: {len(results)}")
        self.log(f"Successful: {successful_jobs}")
        self.log(f"Failed: {failed_jobs}")
        if early_exit:
            self.log(f"Cancelled: {total_jobs - len(results)}", "WARN")
        self.log(f"Total execution time: {total_time:.1f}s")
        if results:
            self.log(f"Average time per job: {sum(r['execution_time'] for r in results) / len(results):.1f}s")
            self.log(f"Wall-clock speedup: {sum(r['execution_time'] for r in results) / total_time:.1f}x")

        # Detailed results
        if results:
            self.log("\nDetailed Results (by job number):")
            for result in results:
                status = "SUCCESS" if result['success'] else "FAILED"
                time_str = f"{result['execution_time']:.1f}s"
                auth_method = result.get('auth_method', 'unknown')
                job_num = result.get('job_number', '?')
                self.log(f"  [{job_num:2d}] {result['job_name']}: {status} ({time_str}) [{auth_method}]")

                if not result['success'] and 'error' in result:
                    self.log(f"       Error: {result['error']}")

        batch_result = {
            'success': failed_jobs == 0 and not early_exit,
            'total_jobs': total_jobs,
            'completed_jobs': len(results),
            'successful_jobs': successful_jobs,
            'failed_jobs': failed_jobs,
            'cancelled_jobs': total_jobs - len(results) if early_exit else 0,
            'total_time': total_time,
            'job_results': results
        }

        return batch_result


def create_sample_job_list():
    """Create a sample job list file for demonstration"""
    sample_content = """# Network Job Batch List
# Lines starting with # are comments
# List one job configuration file per line

# Configuration backup jobs
job1_cisco_config_backup.json
job2_arista_version_check.json

# Inventory collection jobs  
job3_interface_status.json
job4_system_info.json

# You can use absolute paths too:
# /path/to/special_job.json
"""

    with open('sample_job_list.txt', 'w') as f:
        f.write(sample_content)

    print("Created sample_job_list.txt")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Network Job Batch Runner (Concurrent) - Execute multiple network automation jobs in parallel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s jobs.txt                          # Run jobs with 3 concurrent workers (default)
  %(prog)s jobs.txt --max-concurrent 5       # Run with 5 concurrent workers
  %(prog)s jobs.txt --verbose                # Run with detailed output
  %(prog)s jobs.txt --stop-on-error          # Stop if any job fails
  %(prog)s jobs.txt --retries 2              # Retry failed jobs up to 2 times
  %(prog)s jobs.txt --jobs-folder ./jobs     # Load job files from ./jobs directory
  %(prog)s --create-sample                   # Create sample job list file

Job List File Format:
  - One job configuration file per line
  - Lines starting with # are comments
  - Blank lines are ignored
  - Supports both relative and absolute paths

Authentication:
  Jobs can specify authentication in their JSON config:
  {
    "authentication": {
      "use_keys": true,
      "ssh_key_path": "~/.ssh/id_rsa"
    }
  }

Note: 
  - Jobs execute in parallel (controlled by --max-concurrent)
  - Each job's output is prefixed with [Job X/Y] for clarity
  - Results are sorted by job number in the final summary
        """
    )

    parser.add_argument(
        'job_list_file',
        nargs='?',
        help='File containing list of job configuration files to execute'
    )

    parser.add_argument(
        '--max-concurrent', '-m',
        type=int,
        default=3,
        help='Maximum number of jobs to run concurrently (default: 3)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output (show job execution details)'
    )

    parser.add_argument(
        '--stop-on-error',
        action='store_true',
        help='Stop batch execution if any job fails (default: continue with remaining jobs)'
    )

    parser.add_argument(
        '--retries', '-r',
        type=int,
        default=0,
        help='Number of retry attempts for failed jobs (default: 0)'
    )

    parser.add_argument(
        '--jobs-folder', '-j',
        help='Folder containing job configuration files (default: same directory as job list file)'
    )

    parser.add_argument(
        '--create-sample',
        action='store_true',
        help='Create a sample job list file and exit'
    )

    args = parser.parse_args()

    # Handle sample creation
    if args.create_sample:
        create_sample_job_list()
        return 0

    # Validate arguments
    if not args.job_list_file:
        parser.error("job_list_file is required (or use --create-sample)")

    if not os.path.exists(args.job_list_file):
        print(f"Error: Job list file not found: {args.job_list_file}")
        return 1

    if args.max_concurrent < 1:
        print(f"Error: --max-concurrent must be at least 1")
        return 1

    try:
        # Create and run batch runner
        batch_runner = JobBatchRunner(
            verbose=args.verbose,
            max_concurrent=args.max_concurrent
        )

        result = batch_runner.run_batch(
            job_list_file=args.job_list_file,
            continue_on_error=not args.stop_on_error,
            max_retries=args.retries,
            jobs_folder=args.jobs_folder
        )

        # Exit with appropriate code
        return 0 if result['success'] else 1

    except KeyboardInterrupt:
        print("\nBatch execution interrupted by user")
        return 1
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())