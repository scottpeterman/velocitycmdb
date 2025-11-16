#!/usr/bin/env python3
"""
Network Job Batch Runner CLI
Concurrent execution of multiple network automation job configurations using multiprocessing
"""

import sys
import os
import json
import yaml
import subprocess
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
from functools import partial


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
                'additional_args': '--invoke-shell',
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

    def get_additional_args(self, vendor: str) -> str:
        """Get additional arguments for vendor-specific execution"""
        config = self.get_vendor_config(vendor)
        return config['additional_args']


def log_message(message: str, level: str = "INFO", job_name: str = None):
    """Log message with timestamp and optional job name"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    job_prefix = f"[{job_name}] " if job_name else ""
    print(f"[{timestamp}] [{level}] {job_prefix}{message}")


def get_credential_env_vars(job_config: Dict[str, Any]) -> Dict[str, str]:
    """Get environment variables for credentials from job config"""
    env_vars = {}

    credentials = job_config.get('credentials', {})
    username = credentials.get('username', '')

    # For batch operations, we typically use CRED_* format
    if username:
        # Set multiple credential IDs as fallback
        for cred_id in range(1, 11):
            env_vars.update({
                f'CRED_{cred_id}_USER': username,
            })

    return env_vars


def execute_single_job(job_file_and_config: Tuple[str, Dict[str, Any]],
                       max_retries: int = 0, verbose: bool = False) -> Dict[str, Any]:
    """
    Execute a single job configuration in a separate process.
    This function is designed to be called by ProcessPoolExecutor.

    Args:
        job_file_and_config: Tuple of (job_file_path, job_config_dict)
        max_retries: Number of retry attempts for failed jobs
        verbose: Enable verbose logging

    Returns:
        Dictionary containing job execution results
    """
    job_file, job_config = job_file_and_config
    job_name = os.path.basename(job_file)

    # Initialize vendor manager for this process
    vendor_manager = VendorCommandManager()

    start_time = time.time()
    attempts = 0

    while attempts <= max_retries:
        try:
            if attempts > 0:
                log_message(f"Retry attempt {attempts}/{max_retries}", "INFO", job_name)
                time.sleep(2)  # Brief pause before retry

            log_message(f"Starting execution (attempt {attempts + 1})", "INFO", job_name)

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
            auto_paging = vendor_info.get('auto_paging', True)

            filters = job_config.get('filters', {})
            commands_info = job_config.get('commands', {})
            execution_info = job_config.get('execution', {})

            # Build command with vendor-specific paging
            base_commands = commands_info.get('command_text', '')
            if auto_paging:
                final_commands = vendor_manager.build_command_with_paging(vendor, base_commands)
            else:
                final_commands = base_commands

            output_dir = commands_info.get('output_directory', 'output')

            # Determine batch script
            batch_script_text = execution_info.get('batch_script', 'batch_spn.py (Multi-threaded)')
            batch_script_map = {
                "batch_spn.py (Multi-threaded)": "batch_spn.py",
                "batch_spn_concurrent.py (Multi-process)": "batch_spn_concurrent.py"
            }
            batch_script = batch_script_map.get(batch_script_text, "batch_spn.py")

            if not os.path.exists(batch_script):
                raise FileNotFoundError(f"Batch script not found: {batch_script}")

            # Build command arguments
            cmd_args = [sys.executable, batch_script, session_file]

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
                    if verbose:
                        log_message(f"Applied filter: {filter_name} = '{filter_value.strip()}'", "INFO", job_name)
                        # Add fingerprinting options (NEW SECTION)
                        fingerprint_options = job_config.get('fingerprint_options', {})

                        # Add --fingerprinted-only if specified
                        if fingerprint_options.get('fingerprinted_only', False):
                            cmd_args.append('--fingerprinted-only')
                            if verbose:
                                log_message("Applied --fingerprinted-only filter", "INFO", job_name)

                        # Add --fingerprint-only if specified (mutually exclusive with above)
                        elif fingerprint_options.get('fingerprint_only', False):
                            cmd_args.append('--fingerprint-only')
                            if verbose:
                                log_message("Applied --fingerprint-only mode", "INFO", job_name)

                        # Add --fingerprint if specified (can be combined with commands)
                        elif fingerprint_options.get('fingerprint', False):
                            cmd_args.append('--fingerprint')
                            if verbose:
                                log_message("Applied --fingerprint mode", "INFO", job_name)

                        # Add custom fingerprint base directory if specified
                        fingerprint_base = fingerprint_options.get('fingerprint_base', '')
                        if fingerprint_base and fingerprint_base.strip():
                            cmd_args.extend(['--fingerprint-base', fingerprint_base.strip()])
                            if verbose:
                                log_message(f"Applied fingerprint base: {fingerprint_base.strip()}", "INFO", job_name)

            # Add execution parameters
            cmd_args.extend(['-c', final_commands])
            cmd_args.extend(['-o', output_dir])

            # Add execution settings
            max_workers = execution_info.get('max_workers', 5)
            job_verbose = execution_info.get('verbose', False)
            dry_run = execution_info.get('dry_run', False)

            # Script-specific argument handling
            script_name = os.path.basename(batch_script)
            if script_name == 'batch_spn_concurrent.py':
                cmd_args.extend(['--max-processes', str(max_workers)])
                if job_verbose:
                    cmd_args.append('--verbose')
            elif script_name == 'batch_spn.py':
                cmd_args.extend(['--max-workers', str(max_workers)])
                # batch_spn.py doesn't support --verbose

            if dry_run:
                cmd_args.append('--dry-run')

            # Set up environment
            env = os.environ.copy()
            credential_vars = get_credential_env_vars(job_config)
            env.update(credential_vars)

            # Log execution details
            if verbose:
                command_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd_args)
                log_message(f"Executing: {command_str}", "INFO", job_name)
                log_message(f"Final commands: {final_commands}", "INFO", job_name)
                log_message(f"Output directory: capture/{output_dir}", "INFO", job_name)

            # Execute the job
            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            # Wait for completion
            stdout, stderr = process.communicate()
            execution_time = time.time() - start_time

            # Prepare result
            result = {
                'job_name': job_name,
                'job_file': job_file,
                'success': process.returncode == 0,
                'return_code': process.returncode,
                'execution_time': execution_time,
                'output_directory': f"capture/{output_dir}",
                'commands': final_commands,
                'stdout': stdout,
                'stderr': stderr,
                'attempts': attempts + 1
            }

            if result['success']:
                log_message(f"Completed successfully in {execution_time:.1f}s", "INFO", job_name)
                return result
            else:
                log_message(f"Failed after {execution_time:.1f}s (attempt {attempts + 1})", "ERROR", job_name)
                if stderr and verbose:
                    log_message(f"Error output: {stderr}", "ERROR", job_name)

                # If this isn't our last attempt, continue to retry
                if attempts < max_retries:
                    attempts += 1
                    continue
                else:
                    return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            log_message(f"Failed with exception (attempt {attempts + 1}): {error_msg}", "ERROR", job_name)

            # If this isn't our last attempt, continue to retry
            if attempts < max_retries:
                attempts += 1
                continue
            else:
                return {
                    'job_name': job_name,
                    'job_file': job_file,
                    'success': False,
                    'return_code': -1,
                    'execution_time': execution_time,
                    'error': error_msg,
                    'stdout': '',
                    'stderr': '',
                    'attempts': attempts + 1
                }

    # Should never reach here, but just in case
    return {
        'job_name': job_name,
        'job_file': job_file,
        'success': False,
        'return_code': -1,
        'execution_time': time.time() - start_time,
        'error': 'Maximum retries exceeded',
        'stdout': '',
        'stderr': '',
        'attempts': attempts
    }


class JobBatchRunner:
    """Manages concurrent batch execution of multiple network automation jobs"""

    def __init__(self, verbose: bool = False, max_processes: int = 5):
        self.verbose = verbose
        self.max_processes = max_processes

    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp"""
        log_message(message, level)

    def load_job_list(self, job_list_file: str) -> List[str]:
        """Load list of job configuration files"""
        job_files = []

        try:
            with open(job_list_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue

                    # Handle absolute and relative paths
                    job_file = line
                    if not os.path.isabs(job_file):
                        # Make relative to the job list file's directory
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

            # Validate basic structure
            if not isinstance(job_config, dict):
                raise ValueError("Job configuration must be a dictionary")

            return job_config

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in job file {job_file}: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Failed to load job file {job_file}: {str(e)}")

    def run_batch(self, job_list_file: str, continue_on_error: bool = True,
                  max_retries: int = 0) -> Dict[str, Any]:
        """Run a batch of jobs concurrently from a job list file"""

        self.log("=" * 60)
        self.log("CONCURRENT NETWORK JOB BATCH RUNNER STARTING")
        self.log("=" * 60)
        self.log(f"Max concurrent processes: {self.max_processes}")

        start_time = time.time()

        # Load job list
        try:
            job_files = self.load_job_list(job_list_file)
        except Exception as e:
            self.log(f"Failed to load job list: {str(e)}", "ERROR")
            return {'success': False, 'error': str(e)}

        if not job_files:
            self.log("No valid job files found in job list", "ERROR")
            return {'success': False, 'error': 'No valid job files found'}

        # Load all job configurations
        job_configs = []
        load_errors = []

        for job_file in job_files:
            try:
                job_config = self.load_job_config(job_file)
                job_configs.append((job_file, job_config))
            except Exception as e:
                load_errors.append({
                    'job_name': os.path.basename(job_file),
                    'job_file': job_file,
                    'success': False,
                    'return_code': -1,
                    'execution_time': 0,
                    'error': f"Failed to load job configuration: {str(e)}",
                    'attempts': 0
                })

        self.log(f"Successfully loaded {len(job_configs)} job configurations")
        if load_errors:
            self.log(f"Failed to load {len(load_errors)} job configurations", "WARN")

        # Execute jobs concurrently
        results = []
        successful_jobs = 0
        failed_jobs = 0
        completed_jobs = 0

        if job_configs:
            self.log(f"Starting concurrent execution of {len(job_configs)} jobs...")

            # Create the execution function with bound parameters
            execute_func = partial(execute_single_job,
                                   max_retries=max_retries,
                                   verbose=self.verbose)

            # Use ProcessPoolExecutor for concurrent execution
            with ProcessPoolExecutor(max_workers=self.max_processes) as executor:
                # Submit all jobs
                future_to_job = {
                    executor.submit(execute_func, job_config): job_config[0]
                    for job_config in job_configs
                }

                # Process completed jobs as they finish
                for future in as_completed(future_to_job):
                    job_file = future_to_job[future]
                    job_name = os.path.basename(job_file)

                    try:
                        result = future.result()
                        results.append(result)
                        completed_jobs += 1

                        if result['success']:
                            successful_jobs += 1
                            self.log(f"✓ Job {completed_jobs}/{len(job_configs)} completed successfully: {job_name}")
                        else:
                            failed_jobs += 1
                            self.log(f"✗ Job {completed_jobs}/{len(job_configs)} failed: {job_name}", "ERROR")

                            if not continue_on_error:
                                self.log("Cancelling remaining jobs due to failure", "WARN")
                                # Cancel remaining futures
                                for remaining_future in future_to_job:
                                    if not remaining_future.done():
                                        remaining_future.cancel()
                                break

                    except Exception as e:
                        failed_jobs += 1
                        completed_jobs += 1
                        error_result = {
                            'job_name': job_name,
                            'job_file': job_file,
                            'success': False,
                            'return_code': -1,
                            'execution_time': 0,
                            'error': f"Execution error: {str(e)}",
                            'attempts': 0
                        }
                        results.append(error_result)
                        self.log(f"✗ Job {completed_jobs}/{len(job_configs)} execution error: {job_name}", "ERROR")

                        if not continue_on_error:
                            self.log("Cancelling remaining jobs due to error", "WARN")
                            break

        # Add load errors to results
        results.extend(load_errors)
        failed_jobs += len(load_errors)

        # Generate summary
        total_time = time.time() - start_time
        total_jobs = len(job_files)

        self.log("=" * 60)
        self.log("CONCURRENT BATCH EXECUTION SUMMARY")
        self.log("=" * 60)
        self.log(f"Total jobs: {total_jobs}")
        self.log(f"Successful: {successful_jobs}")
        self.log(f"Failed: {failed_jobs}")
        self.log(f"Total execution time: {total_time:.1f}s")
        self.log(f"Average time per job: {total_time / len(results):.1f}s" if results else "N/A")
        self.log(f"Concurrent processes used: {min(self.max_processes, len(job_configs))}")

        # Detailed results
        if results:
            self.log("\nDetailed Results:")
            # Sort results by job name for consistent output
            sorted_results = sorted(results, key=lambda x: x['job_name'])
            for result in sorted_results:
                status = "SUCCESS" if result['success'] else "FAILED"
                time_str = f"{result['execution_time']:.1f}s"
                attempts_str = f" (attempts: {result.get('attempts', 1)})" if result.get('attempts', 1) > 1 else ""
                self.log(f"  {result['job_name']}: {status} ({time_str}){attempts_str}")

                if not result['success'] and 'error' in result:
                    self.log(f"    Error: {result['error']}")

        batch_result = {
            'success': failed_jobs == 0,
            'total_jobs': total_jobs,
            'successful_jobs': successful_jobs,
            'failed_jobs': failed_jobs,
            'total_time': total_time,
            'max_processes': self.max_processes,
            'job_results': results
        }

        return batch_result


def create_sample_job_list():
    """Create a sample job list file for demonstration"""
    sample_content = """# Network Job Batch List
# Lines starting with # are comments
# List one job configuration file per line

# Configuration backup jobs
job1.json
job2.json

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
        description="Concurrent Network Job Batch Runner - Execute multiple network automation jobs concurrently using multiprocessing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s jobs.txt                        # Run jobs listed in jobs.txt
  %(prog)s jobs.txt --verbose              # Run with detailed output
  %(prog)s jobs.txt --stop-on-error        # Stop if any job fails
  %(prog)s jobs.txt --retries 2            # Retry failed jobs up to 2 times
  %(prog)s jobs.txt --max-processes 10     # Use up to 10 concurrent processes
  %(prog)s --create-sample                 # Create sample job list file

Job List File Format:
  - One job configuration file per line
  - Lines starting with # are comments
  - Blank lines are ignored
  - Supports both relative and absolute paths
        """
    )

    parser.add_argument(
        'job_list_file',
        nargs='?',
        help='File containing list of job configuration files to execute'
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
        '--max-processes', '-p',
        type=int,
        default=5,
        help='Maximum number of concurrent processes (default: 5)'
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

    if args.max_processes < 1:
        print(f"Error: max-processes must be at least 1")
        return 1

    # Limit max processes to reasonable bounds
    max_processes = min(args.max_processes, mp.cpu_count() * 2)
    if max_processes != args.max_processes:
        print(f"Warning: Limiting max-processes to {max_processes} (system limit)")

    try:
        # Create and run batch runner
        batch_runner = JobBatchRunner(
            verbose=args.verbose,
            max_processes=max_processes
        )

        result = batch_runner.run_batch(
            job_list_file=args.job_list_file,
            continue_on_error=not args.stop_on_error,
            max_retries=args.retries
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