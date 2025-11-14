#!/usr/bin/env python3
"""
Multi-Process Batch SSH Collection Wrapper for Enhanced SSHPassPython
Filters devices from YAML session files and executes spn.py commands using concurrent processes
Enhanced with fingerprinting support
"""

import os
import queue
import sys
import threading
import time

import yaml
import argparse
import subprocess
import json
import multiprocessing
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime
import re
import concurrent.futures
from functools import partial

# Optional: Hardcoded credential mapping (fallback if env vars not found)
# For production, leave this empty and use environment variables only
CREDENTIAL_MAP = {
    # '1': {'user': 'admin', 'password': 'your_password_here'},
    # '2': {'user': 'netadmin', 'password': 'another_password'},
}


class DeviceFilter:
    """Handles device filtering based on query criteria"""

    def __init__(self, sessions_data: List[Dict]):
        self.sessions_data = sessions_data

    def filter_fingerprinted_devices(self, devices: List[Dict], fingerprint_base_dir: str) -> List[Dict]:
        """Filter devices to only include those with existing fingerprint files"""
        fingerprinted_devices = []
        fingerprint_dir = Path(fingerprint_base_dir)

        if not fingerprint_dir.exists():
            print(f"Warning: Fingerprint directory '{fingerprint_base_dir}' does not exist")
            return []

        for device in devices:
            device_name = device.get('display_name', '')
            fingerprint_file = fingerprint_dir / f"{device_name}.json"

            if fingerprint_file.exists():
                fingerprinted_devices.append(device)
            else:
                if hasattr(self, '_verbose') and self._verbose:
                    print(f"Skipping {device_name} - no fingerprint file found")

        return fingerprinted_devices

    def filter_devices(self, folder_pattern: str = None, name_pattern: str = None,
                       vendor_pattern: str = None, device_type: str = None) -> List[Dict]:
        """Filter devices based on multiple criteria"""
        matched_devices = []

        for folder_group in self.sessions_data:
            folder_name = folder_group.get('folder_name', '')

            # Filter by folder pattern
            if folder_pattern and not self._match_pattern(folder_name, folder_pattern):
                continue

            for device in folder_group.get('sessions', []):
                # Filter by display name pattern
                if name_pattern and not self._match_pattern(device.get('display_name', ''), name_pattern):
                    continue

                # Filter by vendor pattern
                if vendor_pattern and not self._match_pattern(device.get('Vendor', ''), vendor_pattern):
                    continue

                # Filter by device type
                if device_type and device.get('DeviceType', '').lower() != device_type.lower():
                    continue

                # Add folder context to device info
                device_with_context = device.copy()
                device_with_context['folder_name'] = folder_name
                matched_devices.append(device_with_context)

        return matched_devices

    def _match_pattern(self, text: str, pattern: str) -> bool:
        """Match text against pattern (supports wildcards and regex)"""
        if not pattern:
            return True

        text = text.lower()
        pattern = pattern.lower()

        # Simple wildcard support
        if '*' in pattern:
            pattern = pattern.replace('*', '.*')
            return re.match(pattern, text) is not None

        # Substring match
        return pattern in text


class CredentialManager:
    """Handles credential lookup by credential ID"""

    def __init__(self):
        pass

    def get_credentials(self, cred_id: str) -> Dict[str, str]:
        """Get credentials for a given credential ID"""
        # First try environment variables (preferred method)
        env_user = os.getenv(f'CRED_{cred_id}_USER')
        env_pass = os.getenv(f'CRED_{cred_id}_PASS')

        if env_user and env_pass:
            return {'user': env_user, 'password': env_pass}

        # Fallback to hardcoded mapping
        if cred_id in CREDENTIAL_MAP:
            return CREDENTIAL_MAP[cred_id]

        # No credentials found
        raise ValueError(f"No credentials found for cred_id '{cred_id}'. "
                         f"Set environment variables CRED_{cred_id}_USER and CRED_{cred_id}_PASS")

    def validate_credentials(self, devices: List[Dict]) -> bool:
        """Validate that credentials are available for all devices"""
        missing_creds = set()

        for device in devices:
            cred_id = device.get('credsid', '')
            if not cred_id:
                missing_creds.add(f"Device '{device.get('display_name', 'unknown')}' has no credsid")
                continue

            try:
                self.get_credentials(cred_id)
            except ValueError as e:
                missing_creds.add(str(e))

        if missing_creds:
            print("ERROR: Missing credentials:")
            for error in sorted(missing_creds):
                print(f"  - {error}")
            print(f"\nFor Windows, set environment variables like:")
            print(f"  set CRED_1_USER=admin")
            print(f"  set CRED_1_PASS=your_password")
            print(f"\nOr use PowerShell:")
            print(f"  $env:CRED_1_USER='admin'")
            print(f"  $env:CRED_1_PASS='your_password'")
            return False

        return True


import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime


def stream_subprocess_output(process, device_name, timeout_seconds=600):
    """Stream subprocess output in real-time and return collected stdout/stderr"""

    def read_stream(pipe, stream_name, output_queue):
        try:
            for line in iter(pipe.readline, ''):
                if line:
                    output_queue.put((stream_name, line.rstrip()))
        except Exception as e:
            output_queue.put((stream_name, f"Stream error: {e}"))
        finally:
            pipe.close()

    output_queue = queue.Queue()
    stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, 'OUT', output_queue))
    stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, 'ERR', output_queue))

    stdout_thread.daemon = True
    stderr_thread.daemon = True
    stdout_thread.start()
    stderr_thread.start()

    stdout_data = ""
    stderr_data = ""
    start_time = time.time()

    print(f"[STREAM] {device_name} - Real-time output:")
    print("-" * 40)

    while process.poll() is None:
        if time.time() - start_time > timeout_seconds:
            print(f"[TIMEOUT] {device_name} - Killing process after {timeout_seconds}s")
            process.kill()
            break

        try:
            stream_type, line = output_queue.get(timeout=0.1)
            print(f"[{stream_type}] {line}")

            if stream_type == 'OUT':
                stdout_data += line + '\n'
            else:
                stderr_data += line + '\n'
        except queue.Empty:
            continue

    return_code = process.wait()
    stdout_thread.join(timeout=1)
    stderr_thread.join(timeout=1)

    while not output_queue.empty():
        try:
            stream_type, line = output_queue.get_nowait()
            print(f"[{stream_type}] {line}")
            if stream_type == 'OUT':
                stdout_data += line + '\n'
            else:
                stderr_data += line + '\n'
        except queue.Empty:
            break

    print("-" * 40)
    print(f"[COMPLETE] {device_name} - Exit code: {return_code}")

    return stdout_data, stderr_data, return_code


# Replace the execute_single_device function in batch_spn_concurrent.py with this fixed version:

def execute_single_device(device_and_config: Tuple[Dict, Dict]) -> Dict[str, Any]:
    """
    Execute spn.py command against a single device in a separate process.
    This function must be at module level to be pickle-able for multiprocessing.
    """
    device, config = device_and_config

    device_name = device['display_name']
    host = device['host']
    port = device.get('port', '22')
    cred_id = device.get('credsid', '')

    commands = config['commands']
    output_dir = Path(config['output_dir'])
    spn_script_path = config['spn_script_path']

    # Debug: Print process start info
    print(f"[DEBUG] Process {os.getpid()} starting work on {device_name}")

    # Get credentials for this device
    credential_manager = CredentialManager()
    try:
        credentials = credential_manager.get_credentials(cred_id)
    except ValueError as e:
        return {
            'device': device_name,
            'host': host,
            'success': False,
            'message': f'Credential error: {str(e)}',
            'execution_time': 0,
            'process_id': os.getpid()
        }

    # Output file path - let spn.py create and manage this file
    output_file = output_dir / f"{device_name}.txt"

    # Add common paging disable commands to ensure complete output
    # These cover most network device types
    paging_disable_commands = [
        "terminal length 0",  # Cisco IOS/NXOS, Arista
        "terminal width 0",  # Cisco additional
        "set cli screen-length 0",  # Juniper
        "set cli pager off",  # Palo Alto
        "no page"  # HP ProCurve/Aruba
    ]

    # Prepend paging disable commands to user commands
    if commands.strip():
        # Combine paging commands with user commands
        all_commands = ",".join(paging_disable_commands) + "," + commands + ","
    else:
        # Just paging commands
        all_commands = ",".join(paging_disable_commands) + ","

    # Build spn.py command - pass credentials via environment variables
    cmd_args = [
        sys.executable, spn_script_path,
        '--host', f"{host}:{port}",
        '-c', all_commands,  # Use combined commands with paging disable
        '--invoke-shell',
        '--output-file', str(output_file),  # Let spn.py handle the file
        '--no-screen',  # Don't output to screen during batch
        '--verbose'
    ]

    # Set up environment variables for spn.py subprocess
    env = os.environ.copy()
    env['SSH_HOST'] = f"{host}:{port}"
    env['SSH_USER'] = credentials['user']
    env['SSH_PASSWORD'] = credentials['password']

    start_time = datetime.now()

    try:
        # Execute spn.py - let it handle all file output and cleanup
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per device
            env=env
        )

        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        success = result.returncode == 0

        # Only save stderr to log file if there were errors
        if result.stderr:
            log_file = output_dir / f"{device_name}.log"
            with open(log_file, 'w') as f:
                f.write(f"Command: {' '.join(cmd_args)}\n")
                f.write(f"Device: {device_name} ({host})\n")
                f.write(f"Credentials ID: {cred_id}\n")
                f.write(f"Process ID: {os.getpid()}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"STDERR:\n{result.stderr}\n")
                if result.stdout:
                    f.write(f"STDOUT:\n{result.stdout}\n")

        return {
            'device': device_name,
            'host': host,
            'cred_id': cred_id,
            'success': success,
            'return_code': result.returncode,
            'execution_time': execution_time,
            'output_file': str(output_file),
            'process_id': os.getpid(),
            'message': 'Completed successfully' if success else f'Exit code: {result.returncode}'
        }

    except subprocess.TimeoutExpired:
        return {
            'device': device_name,
            'host': host,
            'cred_id': cred_id,
            'success': False,
            'message': 'Command timed out (600s)',
            'execution_time': 600,
            'process_id': os.getpid()
        }
    except Exception as e:
        return {
            'device': device_name,
            'host': host,
            'cred_id': cred_id,
            'success': False,
            'message': f'Execution error: {str(e)}',
            'execution_time': 0,
            'process_id': os.getpid()
        }
class BatchExecutor:
    """Executes spn.py commands in batch using concurrent processes"""

    def __init__(self, spn_script_path: str, base_output_dir: str = "capture"):
        self.spn_script_path = spn_script_path
        self.base_output_dir = base_output_dir
        self.execution_results = []
        self.credential_manager = CredentialManager()

    def execute_batch(self, devices: List[Dict], commands: str, output_subdir: str,
                      max_processes: int = 4, dry_run: bool = False, verbose: bool = False,
                      enable_fingerprint: bool = False, fingerprint_base_dir: str = "fingerprints") -> Dict[str, Any]:
        """Execute commands against all devices using concurrent processes with optional fingerprinting"""

        # Validate credentials first
        if not self.credential_manager.validate_credentials(devices):
            return {"error": "Credential validation failed"}

        # Create directories
        output_dir = Path(self.base_output_dir) / output_subdir
        fingerprint_dir = None

        if enable_fingerprint:
            fingerprint_dir = Path(fingerprint_base_dir)
            fingerprint_dir.mkdir(parents=True, exist_ok=True)

        if commands:  # Only create output dir if commands are provided
            output_dir.mkdir(parents=True, exist_ok=True)

        if dry_run:
            print(f"DRY RUN: Would execute on {len(devices)} devices using {max_processes} processes")
            if commands:
                print(f"Commands: {commands}")
            if enable_fingerprint:
                print(f"Fingerprinting: ENABLED -> {fingerprint_dir}/")
            else:
                print(f"Fingerprinting: DISABLED")

            for device in devices:
                cred_id = device.get('credsid', 'N/A')
                output_info = []
                if commands:
                    output_info.append(f"output: {output_subdir}/{device['display_name']}.txt")
                if enable_fingerprint:
                    output_info.append(f"fingerprint: {fingerprint_dir}/{device['display_name']}.json")
                output_str = " | ".join(output_info) if output_info else "fingerprint only"
                print(f"  - {device['display_name']} ({device['host']}) [cred_id: {cred_id}] -> {output_str}")
            return {"dry_run": True, "device_count": len(devices)}

        print(f"Executing on {len(devices)} devices using {max_processes} processes")
        if commands:
            print(f"Output directory: {output_dir}")
            print(f"Commands: {commands}")
        if enable_fingerprint:
            print(f"Fingerprinting: ENABLED -> {fingerprint_dir}/")
        else:
            print(f"Fingerprinting: DISABLED")
        print(f"CPU cores available: {multiprocessing.cpu_count()}")
        print(f"Multiprocessing start method: {multiprocessing.get_start_method()}")
        print("-" * 60)

        start_time = datetime.now()

        # Prepare configuration for worker processes
        config = {
            'commands': commands or "",
            'output_dir': str(output_dir),
            'spn_script_path': self.spn_script_path,
            'enable_fingerprint': enable_fingerprint,
            'fingerprint_dir': str(fingerprint_dir) if fingerprint_dir else None
        }

        # Prepare data for workers - combine device with config
        work_items = [(device, config) for device in devices]

        # Execute using ProcessPoolExecutor
        completed_count = 0
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_processes) as executor:
                # Submit all tasks
                future_to_device = {
                    executor.submit(execute_single_device, work_item): work_item[0]
                    for work_item in work_items
                }

                # Process completed tasks
                for future in concurrent.futures.as_completed(future_to_device):
                    device = future_to_device[future]
                    try:
                        result = future.result()
                        self.execution_results.append(result)
                        completed_count += 1

                        status = "SUCCESS" if result['success'] else "FAILED"
                        process_info = f"[PID {result.get('process_id', 'unknown')}]" if verbose else ""
                        progress = f"[{completed_count}/{len(devices)}]"

                        # Add fingerprint status to output
                        fingerprint_info = ""
                        if result.get('fingerprint_enabled'):
                            if result['success']:
                                fingerprint_info = " + fingerprint"
                            else:
                                fingerprint_info = " (fingerprint failed)"

                        print(
                            f"{progress} {process_info} [{status}] {device['display_name']}{fingerprint_info} - {result.get('message', '')}")

                    except Exception as exc:
                        error_result = {
                            'device': device['display_name'],
                            'host': device['host'],
                            'success': False,
                            'message': f'Process exception: {exc}',
                            'execution_time': 0,
                            'process_id': 'unknown',
                            'fingerprint_enabled': enable_fingerprint
                        }
                        self.execution_results.append(error_result)
                        completed_count += 1
                        progress = f"[{completed_count}/{len(devices)}]"
                        print(f"{progress} [ERROR] {device['display_name']} - Process exception: {exc}")

        except KeyboardInterrupt:
            print("\nOperation cancelled by user. Cleaning up...")
            return {"error": "Operation cancelled", "partial_results": self.execution_results}

        end_time = datetime.now()
        execution_summary = self._generate_summary(start_time, end_time, max_processes, enable_fingerprint)

        return execution_summary

    def _generate_summary(self, start_time: datetime, end_time: datetime, max_processes: int,
                          fingerprint_enabled: bool) -> Dict[str, Any]:
        """Generate execution summary"""
        total_time = (end_time - start_time).total_seconds()
        successful = len([r for r in self.execution_results if r['success']])
        failed = len(self.execution_results) - successful

        # Calculate process utilization stats
        process_ids = set(r.get('process_id', 'unknown') for r in self.execution_results if r.get('process_id'))
        unique_processes = len([pid for pid in process_ids if pid != 'unknown'])

        # Count fingerprint results
        fingerprint_successful = 0
        fingerprint_failed = 0
        if fingerprint_enabled:
            fingerprint_successful = len(
                [r for r in self.execution_results if r['success'] and r.get('fingerprint_enabled')])
            fingerprint_failed = len(
                [r for r in self.execution_results if not r['success'] and r.get('fingerprint_enabled')])

        summary = {
            'total_devices': len(self.execution_results),
            'successful': successful,
            'failed': failed,
            'total_execution_time': total_time,
            'max_processes_configured': max_processes,
            'actual_processes_used': unique_processes,
            'average_time_per_device': total_time / len(self.execution_results) if self.execution_results else 0,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'fingerprint_enabled': fingerprint_enabled,
            'fingerprint_successful': fingerprint_successful,
            'fingerprint_failed': fingerprint_failed,
            'results': self.execution_results
        }

        print(f"\n{'=' * 60}")
        print(f"EXECUTION SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total devices: {summary['total_devices']}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        if fingerprint_enabled:
            print(f"Fingerprints successful: {fingerprint_successful}")
            print(f"Fingerprints failed: {fingerprint_failed}")
        print(f"Total time: {total_time:.1f}s")
        print(f"Average time per device: {summary['average_time_per_device']:.1f}s")
        print(f"Max processes configured: {max_processes}")
        print(f"Actual processes used: {unique_processes}")

        if failed > 0:
            print(f"\nFailed devices:")
            for result in self.execution_results:
                if not result['success']:
                    print(f"  - {result['device']}: {result['message']}")

        return summary


def load_sessions(yaml_files: List[str]) -> List[Dict]:
    """Load session data from YAML files"""
    all_sessions = []

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, 'r') as f:
                sessions = yaml.safe_load(f)
                if isinstance(sessions, list):
                    all_sessions.extend(sessions)
                else:
                    all_sessions.append(sessions)
            print(f"Loaded {yaml_file}")
        except Exception as e:
            print(f"Error loading {yaml_file}: {e}")
            sys.exit(1)

    return all_sessions


# Replace the argument parser section in main() with this corrected version:

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Process Batch SSH automation wrapper for Enhanced SSHPassPython with Fingerprinting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get version info from all Palo Alto devices using 4 processes
  python batch_spn_concurrent.py sessions.yaml --vendor "palo*" -c "show system info" -o version

  # Backup configs from switches using 8 processes  
  python batch_spn_concurrent.py sessions.yaml --folder "ATS*" --name "*sw*" -c "show running-config" -o config --max-processes 8

  # Fingerprint all devices without running commands
  python batch_spn_concurrent.py sessions.yaml --vendor "cisco" --fingerprint-only

  # Run commands only against fingerprinted devices
  python batch_spn_concurrent.py sessions.yaml --vendor "cisco" --fingerprinted-only -c "show running-config" -o configs

  # Combine fingerprinting with command execution
  python batch_spn_concurrent.py sessions.yaml --vendor "aruba" -c "show version" -o inventory --fingerprint

  # Show all Aruba devices (dry run)
  python batch_spn_concurrent.py sessions.yaml --vendor "aruba" --dry-run
        """
    )

    # Input files
    parser.add_argument('yaml_files', nargs='+', help='YAML session files to process')

    # Filter options
    parser.add_argument('--folder', help='Filter by folder name (supports wildcards)')
    parser.add_argument('--name', help='Filter by device display name (supports wildcards)')
    parser.add_argument('--vendor', help='Filter by vendor (supports wildcards)')
    parser.add_argument('--device-type', help='Filter by device type')

    # Execution options
    parser.add_argument('-c', '--commands', help='Commands to execute (same format as spn.py)')
    parser.add_argument('-o', '--output', help='Output subdirectory (e.g., "config", "version")')
    parser.add_argument('--output-base', default='capture', help='Base output directory (default: capture)')

    # Fingerprinting options
    parser.add_argument('--fingerprint', action='store_true',
                        help='Enable device fingerprinting alongside command execution')
    parser.add_argument('--fingerprint-only', action='store_true',
                        help='Only perform fingerprinting (no commands)')
    parser.add_argument('--fingerprinted-only', action='store_true',
                        help='Only execute against devices that have existing fingerprint files')
    parser.add_argument('--fingerprint-base', default='fingerprints',
                        help='Base directory for fingerprint files (default: fingerprints)')

    # Process control
    parser.add_argument('--max-processes', type=int, default=4,
                        help='Maximum concurrent processes (default: 4)')
    parser.add_argument('--spn-script', default='spn.py', help='Path to spn.py script (default: spn.py)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be executed without running')
    parser.add_argument('--verbose', action='store_true', help='Show detailed progress including process IDs')

    # Output control
    parser.add_argument('--save-summary', help='Save execution summary to JSON file')
    parser.add_argument('--list-devices', action='store_true', help='Just list matching devices and exit')

    args = parser.parse_args()

    # Replace the argument validation section with this enhanced version:

    # Validate arguments
    if args.fingerprint_only and args.fingerprinted_only:
        print("Error: --fingerprint-only and --fingerprinted-only are mutually exclusive")
        print("  Use --fingerprint-only to perform fingerprinting on devices")
        print("  Use --fingerprinted-only to run commands only on already fingerprinted devices")
        sys.exit(1)

    if args.fingerprint_only:
        args.fingerprint = True
        if args.commands:
            print("Warning: --fingerprint-only specified, ignoring commands")
        args.commands = None
        args.output = None
    elif args.fingerprinted_only:
        if not args.commands:
            print("Error: --fingerprinted-only requires commands to be specified (-c)")
            sys.exit(1)
        if not args.output:
            print("Error: Output directory (-o) required when commands are specified")
            sys.exit(1)
    elif not args.commands and not args.fingerprint:
        print("Error: Must specify either commands (-c) or fingerprinting (--fingerprint/--fingerprint-only)")
        sys.exit(1)
    elif args.commands and not args.output:
        print("Error: Output directory (-o) required when commands are specified")
        sys.exit(1)

    # Validate max-processes
    cpu_count = multiprocessing.cpu_count()
    if args.max_processes > cpu_count:
        print(f"Warning: Requested {args.max_processes} processes, but only {cpu_count} CPU cores available.")
        print(f"Consider using --max-processes {cpu_count} or lower for optimal performance.")

    # Load session data
    print("Loading session files...")
    sessions = load_sessions(args.yaml_files)

    # Filter devices
    device_filter = DeviceFilter(sessions)
    matched_devices = device_filter.filter_devices(
        folder_pattern=args.folder,
        name_pattern=args.name,
        vendor_pattern=args.vendor,
        device_type=args.device_type
    )

    # Apply fingerprinted-only filter if requested
    if args.fingerprinted_only:
        before_count = len(matched_devices)
        matched_devices = device_filter.filter_fingerprinted_devices(matched_devices, args.fingerprint_base)
        after_count = len(matched_devices)
        print(f"Filtered to fingerprinted devices only: {before_count} -> {after_count} devices")

    if not matched_devices:
        if args.fingerprinted_only:
            print("No devices with existing fingerprint files matched the specified criteria.")
            print(f"Check that fingerprint files exist in: {args.fingerprint_base}/")
        else:
            print("No devices matched the specified criteria.")
        sys.exit(1)

    print(f"\nMatched {len(matched_devices)} devices:")
    for device in matched_devices:
        vendor = device.get('Vendor', 'Unknown')
        folder = device.get('folder_name', 'Unknown')
        print(f"  - {device['display_name']} ({device['host']}) [{vendor}] in '{folder}'")

    if args.list_devices:
        sys.exit(0)

    # Execute batch commands using processes with optional fingerprinting
    executor = BatchExecutor(args.spn_script, args.output_base)
    summary = executor.execute_batch(
        devices=matched_devices,
        commands=args.commands or "",
        output_subdir=args.output or "fingerprint_only",
        max_processes=args.max_processes,
        dry_run=args.dry_run,
        verbose=args.verbose,
        enable_fingerprint=args.fingerprint,
        fingerprint_base_dir=args.fingerprint_base
    )

    # Save summary if requested
    if args.save_summary and not args.dry_run and 'error' not in summary:
        with open(args.save_summary, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\nExecution summary saved to {args.save_summary}")

# python batch_spn_concurrent.py sessions.yaml --name "*core*" --fingerprint-only --fingerprint-base "./fingerprints"
if __name__ == "__main__":
    # Set start method for multiprocessing (critical for proper process creation)
    try:
        multiprocessing.set_start_method('spawn')
    except RuntimeError:
        # start method can only be set once
        pass

    main()