#!/usr/bin/env python3
"""
Cisco Job Runner - Simple wrapper for password-based Cisco device jobs
Uses ssh_client.py with Paramiko (no fallback, no key auth)
"""

import os
import sys
import json
import yaml
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import concurrent.futures
from threading import Lock

# Import the existing SSH client
from ssh_client import SSHClient, SSHClientOptions


class CiscoJobExecutor:
    """Execute jobs on Cisco devices using password auth only"""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.results_lock = Lock()
        self.results = []

        # Remove fallback config if it exists
        self._disable_fallback_config()

    def _disable_fallback_config(self):
        """Remove or rename fallback config to prevent it from being loaded"""
        config_file = Path('ssh_fallback_config.yaml')
        if config_file.exists():
            backup_file = Path('ssh_fallback_config.yaml.disabled')
            config_file.rename(backup_file)
            print(f"Disabled fallback config: {config_file} -> {backup_file}")

    def log(self, message, level="INFO"):
        """Log with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}", flush=True)

    def load_sessions(self, session_file):
        """Load devices from sessions.yaml"""
        try:
            with open(session_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.log(f"Failed to load sessions: {e}", "ERROR")
            return []

    def filter_devices(self, sessions, filters):
        """Filter devices based on job filters"""
        matched = []

        folder_filter = filters.get('folder', '').lower()
        name_filter = filters.get('name', '').lower()
        vendor_filter = filters.get('vendor', '').lower()
        device_type_filter = filters.get('device_type', '').lower()

        for folder_group in sessions:
            folder_name = folder_group.get('folder_name', '').lower()

            if folder_filter and folder_filter not in folder_name:
                continue

            for device in folder_group.get('sessions', []):
                if name_filter and name_filter not in device.get('display_name', '').lower():
                    continue
                if vendor_filter and vendor_filter not in device.get('Vendor', '').lower():
                    continue
                if device_type_filter and device_type_filter != device.get('DeviceType', '').lower():
                    continue

                device['folder_name'] = folder_group.get('folder_name', '')
                matched.append(device)

        return matched

    def get_credentials(self, cred_id):
        """Get credentials from environment variables"""
        username = os.getenv(f'CRED_{cred_id}_USER')
        password = os.getenv(f'CRED_{cred_id}_PASS')

        if not username or not password:
            raise ValueError(f"Credentials not found for ID {cred_id}. "
                             f"Set CRED_{cred_id}_USER and CRED_{cred_id}_PASS")

        return username, password

    def execute_device(self, device, commands, output_dir):
        """Execute commands on a single device"""
        device_name = device['display_name']
        host = device['host']
        port = device.get('port', 22)
        cred_id = device.get('credsid', '1')

        start_time = time.time()
        output_file = Path(output_dir) / f"{device_name}.txt"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            username, password = self.get_credentials(cred_id)

            if self.verbose:
                self.log(f"Connecting to {device_name} ({host}:{port}) as {username}")

            # Create SSH client options - shell mode for multi-command
            options = SSHClientOptions(
                host=host,
                port=port,
                username=username,
                password=password,
                invoke_shell=True,
                timeout=60,
                shell_timeout=5,
                inter_command_time=1,
                debug=False,
                display_name=device_name
            )

            # Disable fallback
            options.enable_fallback = False

            # Capture output
            output_buffer = []
            options.output_callback = lambda text: output_buffer.append(text)

            # Connect and execute
            client = SSHClient(options)
            client.connect()

            # Execute commands (comma-separated, shell mode handles this)
            result = client.execute_command(commands)

            client.disconnect()

            # Save output
            with open(output_file, 'w') as f:
                f.write(result)

            execution_time = time.time() - start_time

            if self.verbose:
                self.log(f"Saved {len(result)} bytes to {output_file}")

            return {
                'device': device_name,
                'host': host,
                'success': True,
                'execution_time': execution_time,
                'message': 'Completed successfully',
                'output_file': str(output_file)
            }

        except Exception as e:
            execution_time = time.time() - start_time

            # Save error log
            error_file = Path(output_dir) / f"{device_name}.log"
            with open(error_file, 'w') as f:
                f.write(f"Error: {str(e)}\n")
                f.write(f"Device: {device_name} ({host}:{port})\n")
                f.write(f"Cred ID: {cred_id}\n")
                f.write(f"Commands: {commands}\n\n")

                import traceback
                f.write(traceback.format_exc())

            return {
                'device': device_name,
                'host': host,
                'success': False,
                'execution_time': execution_time,
                'message': f'Error: {str(e)}'
            }

    def execute_batch(self, devices, commands, output_dir, max_workers=5):
        """Execute commands on all devices in parallel"""
        self.log(f"Executing on {len(devices)} devices (max {max_workers} parallel)")
        self.log(f"Output directory: {output_dir}")
        self.log(f"Commands: {commands}")
        self.log("-" * 60)

        start_time = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.execute_device, device, commands, output_dir): device
                for device in devices
            }

            for future in concurrent.futures.as_completed(futures):
                device = futures[future]
                try:
                    result = future.result()
                    with self.results_lock:
                        self.results.append(result)

                    status = "SUCCESS" if result['success'] else "FAILED"
                    self.log(f"[{status}] {device['display_name']} - {result['message']}")

                except Exception as e:
                    error_result = {
                        'device': device['display_name'],
                        'host': device['host'],
                        'success': False,
                        'message': f'Exception: {e}',
                        'execution_time': 0
                    }
                    with self.results_lock:
                        self.results.append(error_result)
                    self.log(f"[ERROR] {device['display_name']} - {e}")

        total_time = time.time() - start_time
        successful = len([r for r in self.results if r['success']])
        failed = len(self.results) - successful

        self.log("=" * 60)
        self.log(f"Completed: {successful} successful, {failed} failed")
        self.log(f"Total time: {total_time:.1f}s")

        if failed > 0:
            self.log("\nFailed devices:")
            for r in self.results:
                if not r['success']:
                    self.log(f"  - {r['device']}: {r['message']}")

        return {
            'successful': successful,
            'failed': failed,
            'total_time': total_time,
            'results': self.results
        }


class JobRunner:
    """Run Cisco jobs from job config files"""

    def __init__(self, verbose=False):
        self.executor = CiscoJobExecutor(verbose)
        self.verbose = verbose

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}", flush=True)

    def load_job_config(self, job_file):
        try:
            with open(job_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.log(f"Failed to load job config: {e}", "ERROR")
            return None

    def execute_job(self, job_file):
        self.log(f"Loading job: {job_file}")

        job_config = self.load_job_config(job_file)
        if not job_config:
            return {'success': False, 'error': 'Failed to load job config'}

        session_file = job_config.get('session_file', 'sessions.yaml')
        filters = job_config.get('filters', {})
        commands_info = job_config.get('commands', {})
        execution_info = job_config.get('execution', {})

        commands = commands_info.get('command_text', '')
        output_subdir = commands_info.get('output_directory', 'output')
        max_workers = execution_info.get('max_workers', 5)

        sessions = self.executor.load_sessions(session_file)
        devices = self.executor.filter_devices(sessions, filters)

        if not devices:
            self.log("No devices matched filters", "WARN")
            return {'success': False, 'error': 'No devices matched'}

        self.log(f"Matched {len(devices)} devices")
        for device in devices:
            vendor = device.get('Vendor', 'Unknown')
            self.log(f"  - {device['display_name']} ({device['host']}) [{vendor}]")

        output_dir = f"capture/{output_subdir}"
        result = self.executor.execute_batch(devices, commands, output_dir, max_workers)

        return result

    def run_batch(self, job_list_file, jobs_folder=None, continue_on_error=True):
        self.log("=" * 60)
        self.log("CISCO JOB BATCH RUNNER (Password Auth)")
        self.log("=" * 60)

        job_files = []
        try:
            with open(job_list_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    job_file = line
                    if jobs_folder and not os.path.isabs(job_file):
                        job_file = os.path.join(jobs_folder, job_file)

                    if os.path.exists(job_file):
                        job_files.append(job_file)
                    else:
                        self.log(f"Job file not found: {job_file}", "WARN")
        except Exception as e:
            self.log(f"Failed to load job list: {e}", "ERROR")
            return {'success': False}

        self.log(f"Loaded {len(job_files)} job files")

        total_successful = 0
        total_failed = 0

        for i, job_file in enumerate(job_files, 1):
            job_name = os.path.basename(job_file)

            self.log("-" * 60)
            self.log(f"JOB {i}/{len(job_files)}: {job_name}")
            self.log("-" * 60)

            try:
                result = self.execute_job(job_file)

                if result.get('success', True):
                    total_successful += result.get('successful', 0)
                    total_failed += result.get('failed', 0)
                else:
                    total_failed += 1
                    if not continue_on_error:
                        self.log("Stopping batch due to job failure", "ERROR")
                        break

            except Exception as e:
                self.log(f"Job failed with exception: {e}", "ERROR")
                total_failed += 1
                if not continue_on_error:
                    break

        self.log("=" * 60)
        self.log("BATCH SUMMARY")
        self.log("=" * 60)
        self.log(f"Jobs processed: {len(job_files)}")
        self.log(f"Total successful: {total_successful}")
        self.log(f"Total failed: {total_failed}")

        return {
            'success': total_failed == 0,
            'jobs_processed': len(job_files),
            'total_successful': total_successful,
            'total_failed': total_failed
        }


def main():
    parser = argparse.ArgumentParser(
        description="Cisco Job Runner - Password-based authentication only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a batch of Cisco jobs
  python run_cisco_jobs.py jobs_cisco.txt --jobs-folder ./jobs

  # Run a single job
  python run_cisco_jobs.py --single-job jobs/job_329_cisco-ios_configs.json

  # Run with verbose output
  python run_cisco_jobs.py jobs_cisco.txt --jobs-folder ./jobs --verbose

Prerequisites:
  export CRED_1_USER=network
  export CRED_1_PASS=your_password

Features:
  - Password authentication only (no SSH keys, no fallback)
  - Uses ssh_client.py shell mode for multi-command
  - Automatically disables fallback config
  - Same infrastructure as Juniper jobs
        """
    )

    parser.add_argument('job_list_file', nargs='?', help='Job list file')
    parser.add_argument('--jobs-folder', help='Folder with job configs')
    parser.add_argument('--single-job', help='Execute a single job file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--stop-on-error', action='store_true', help='Stop if any job fails')

    args = parser.parse_args()

    runner = JobRunner(verbose=args.verbose)

    try:
        if args.single_job:
            result = runner.execute_job(args.single_job)
            return 0 if result.get('success', True) else 1

        elif args.job_list_file:
            result = runner.run_batch(
                args.job_list_file,
                jobs_folder=args.jobs_folder,
                continue_on_error=not args.stop_on_error
            )
            return 0 if result['success'] else 1

        else:
            parser.print_help()
            return 1

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())