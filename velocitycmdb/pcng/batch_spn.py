#!/usr/bin/env python3
"""
FIXED: Batch SSH Collection Wrapper
Key fix: Checks BOTH stdout and stderr for error messages
"""

import os
import sys
import yaml
import argparse
import subprocess
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import re
import concurrent.futures
from threading import Lock

CREDENTIAL_MAP = {}


class DeviceFilter:
    """Handles device filtering based on query criteria"""

    def __init__(self, sessions_data: List[Dict]):
        self.sessions_data = sessions_data

    def filter_devices(self, folder_pattern: str = None, name_pattern: str = None,
                       vendor_pattern: str = None, device_type: str = None) -> List[Dict]:
        """Filter devices based on multiple criteria"""
        matched_devices = []

        for folder_group in self.sessions_data:
            folder_name = folder_group.get('folder_name', '')

            if folder_pattern and not self._match_pattern(folder_name, folder_pattern):
                continue

            for device in folder_group.get('sessions', []):
                if name_pattern and not self._match_pattern(device.get('display_name', ''), name_pattern):
                    continue

                if vendor_pattern and not self._match_pattern(device.get('Vendor', ''), vendor_pattern):
                    continue

                if device_type and device.get('DeviceType', '').lower() != device_type.lower():
                    continue

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

        if '*' in pattern:
            pattern = pattern.replace('*', '.*')
            return re.match(pattern, text) is not None

        return pattern in text


class CredentialManager:
    """Handles credential lookup by credential ID"""

    def __init__(self, use_keys: bool = False, ssh_key_path: str = None):
        self.use_keys = use_keys
        self.ssh_key_path = ssh_key_path

    def get_credentials(self, cred_id: str) -> Dict[str, str]:
        """Get credentials for a given credential ID"""
        if self.use_keys:
            env_user = os.getenv(f'CRED_{cred_id}_USER')

            if env_user:
                return {
                    'user': env_user,
                    'password': '',
                    'use_key': True
                }

            raise ValueError(f"No username found for cred_id '{cred_id}'. "
                             f"Set environment variable CRED_{cred_id}_USER")

        env_user = os.getenv(f'CRED_{cred_id}_USER')
        env_pass = os.getenv(f'CRED_{cred_id}_PASS')

        if env_user and env_pass:
            return {'user': env_user, 'password': env_pass, 'use_key': False}

        if cred_id in CREDENTIAL_MAP:
            cred = CREDENTIAL_MAP[cred_id].copy()
            cred['use_key'] = False
            return cred

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

            if self.use_keys:
                print(f"\nFor key-based auth, set usernames like:")
                print(f"  export CRED_1_USER=admin")
            else:
                print(f"\nFor password-based auth, set environment variables like:")
                print(f"  export CRED_1_USER=admin")
                print(f"  export CRED_1_PASS=your_password")
                print(f"\nOr use PowerShell (Windows):")
                print(f"  $env:CRED_1_USER='admin'")
                print(f"  $env:CRED_1_PASS='your_password'")

            return False

        return True


class BatchExecutor:
    """Executes spn.py commands in batch - FIXED VERSION"""

    def __init__(self, spn_script_path: str, base_output_dir: str = "capture",
                 use_keys: bool = False, ssh_key_path: str = None):
        self.spn_script_path = spn_script_path
        self.base_output_dir = base_output_dir
        self.results_lock = Lock()
        self.execution_results = []
        self.use_keys = use_keys
        self.ssh_key_path = ssh_key_path
        self.credential_manager = CredentialManager(use_keys, ssh_key_path)

    def execute_batch(self, devices: List[Dict], commands: str, output_subdir: str,
                      max_workers: int = 5, dry_run: bool = False) -> Dict[str, Any]:
        """Execute commands against all devices in parallel"""

        if not self.credential_manager.validate_credentials(devices):
            return {"error": "Credential validation failed"}

        if dry_run:
            print(f"DRY RUN: Would execute on {len(devices)} devices")
            auth_method = "key-based" if self.use_keys else "password-based"
            print(f"Authentication: {auth_method}")
            if self.ssh_key_path:
                print(f"SSH Key: {self.ssh_key_path}")

            for device in devices:
                cred_id = device.get('credsid', 'N/A')
                print(f"  - {device['display_name']} ({device['host']}) [cred_id: {cred_id}]")
            return {"dry_run": True, "device_count": len(devices)}

        output_dir = Path(self.base_output_dir) / output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        auth_method = "key-based" if self.use_keys else "password-based"
        print(f"Executing commands on {len(devices)} devices (max {max_workers} parallel)")
        print(f"Authentication: {auth_method}")
        if self.ssh_key_path:
            print(f"SSH Key: {self.ssh_key_path}")
        print(f"Output directory: {output_dir}")
        print(f"Commands: {commands}")
        print("-" * 60)

        start_time = datetime.now()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_device = {
                executor.submit(self._execute_single_device, device, commands, output_dir): device
                for device in devices
            }

            for future in concurrent.futures.as_completed(future_to_device):
                device = future_to_device[future]
                try:
                    result = future.result()
                    with self.results_lock:
                        self.execution_results.append(result)

                    status = "SUCCESS" if result['success'] else "FAILED"
                    print(f"[{status}] {device['display_name']} - {result.get('message', '')}")

                except Exception as exc:
                    error_result = {
                        'device': device['display_name'],
                        'host': device['host'],
                        'success': False,
                        'message': f'Exception: {exc}',
                        'execution_time': 0
                    }
                    with self.results_lock:
                        self.execution_results.append(error_result)
                    print(f"[ERROR] {device['display_name']} - Exception: {exc}")

        end_time = datetime.now()
        execution_summary = self._generate_summary(start_time, end_time)

        return execution_summary

    def _extract_error_message(self, stdout: str, stderr: str) -> str:
        """
        FIXED: Extract error message from BOTH stdout and stderr
        IGNORES benign SSH warnings that aren't actual errors
        """
        # Combine both outputs for searching
        combined = (stdout or '') + '\n' + (stderr or '')

        if not combined.strip():
            return "Process exited with no output - likely missing dependencies or import error"

        # **IGNORE BENIGN SSH WARNINGS** - these are informational, not errors
        benign_patterns = [
            r'Warning: Permanently added .* to the list of known hosts\.',
            r'Pseudo-terminal will not be allocated',
            r'Warning: the .* host key for .* differs from the key for the IP address',
        ]

        # Remove benign warnings from combined output
        cleaned_output = combined
        for pattern in benign_patterns:
            cleaned_output = re.sub(pattern, '', cleaned_output, flags=re.IGNORECASE | re.MULTILINE)

        cleaned_output = cleaned_output.strip()

        # If nothing left after removing benign warnings, there's no actual error
        if not cleaned_output:
            return ""  # Empty string means success, not an error

        # Look for specific error patterns (case insensitive) in the cleaned output
        error_patterns = [
            (r'Error: Missing required credentials: (.+)', 'Missing credentials: {}'),
            (r'Error: (.+)', '{}'),
            (r'Connection error: (.+)', 'Connection error: {}'),
            (r'Paramiko connection failed: (.+)', 'Connection failed: {}'),
            (r'Authentication failed', 'Authentication failed'),
            (r'Connection refused', 'Connection refused'),
            (r'No route to host', 'No route to host'),
            (r'timed out', 'Connection timed out'),
            (r'Permission denied', 'Permission denied'),
            (r'Host key verification failed', 'Host key verification failed'),
        ]

        for pattern, msg_template in error_patterns:
            match = re.search(pattern, cleaned_output, re.IGNORECASE | re.MULTILINE)
            if match:
                if '{}' in msg_template and match.groups():
                    return msg_template.format(match.group(1).strip())
                else:
                    return msg_template if '{}' not in msg_template else match.group(0)

        # If no pattern matched, return first meaningful line from cleaned output
        lines = [line.strip() for line in cleaned_output.split('\n') if line.strip()]
        if lines:
            # Look for lines that start with "Error:" or contain error keywords
            for line in lines:
                if any(keyword in line.lower() for keyword in ['error', 'failed', 'missing', 'denied', 'refused']):
                    return line

        # Last resort: return first line of cleaned output
        first_line = cleaned_output.strip().split('\n')[0]
        return first_line[:100] if first_line else "Unknown error"
    def _execute_single_device(self, device: Dict, commands: str, output_dir: Path) -> Dict[str, Any]:
        """Execute spn.py command against a single device - FIXED VERSION"""
        device_name = device['display_name']
        host = device['host']
        port = device.get('port', '22')
        cred_id = device.get('credsid', '')

        try:
            credentials = self.credential_manager.get_credentials(cred_id)
        except ValueError as e:
            return {
                'device': device_name,
                'host': host,
                'cred_id': cred_id,
                'success': False,
                'message': f'Credential error: {str(e)}',
                'execution_time': 0
            }

        output_file = output_dir / f"{device_name}.txt"

        # Gather credentials from environment with clear priority order
        user = os.getenv('CRED_1_USER') or os.getenv('SSH_USER') or ''
        password = os.getenv('CRED_1_PASS') or os.getenv('SSH_PASSWORD') or ''

        cmd_args = [
            sys.executable, '-u', self.spn_script_path,
            '--host', f"{host}:{port}",
            '-c', commands,
            '--output-file', str(output_file),
            # '--no-screen',
            '--user', user,
            '--password', password,
            '--verbose',
            # '--display-name', device_name,
            # '--invoke-shell'
        ]

        # if self.use_keys and self.ssh_key_path:
        #     cmd_args.extend(['--ssh-key', self.ssh_key_path])

        # **DEBUG OUTPUT**
        print(f"\n[DEBUG] Executing command for {device_name}:")
        print(f"  Command: {' '.join(cmd_args)}")

        env = os.environ.copy()
        env['SSH_HOST'] = f"{host}:{port}"
        env['SSH_USER'] = credentials['user']
        env['SSH_DISPLAY_NAME'] = device_name

        if not self.use_keys:
            env['SSH_PASSWORD'] = credentials['password']
            print(f"  Auth: password-based (user: {credentials['user']})")
        else:
            print(f"  Auth: key-based (user: {credentials['user']}, key: {self.ssh_key_path})")

        if self.ssh_key_path:
            env['SSH_KEY_PATH'] = self.ssh_key_path

        start_time = datetime.now()

        try:
            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=600,
                env=env
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            # Check for actual errors (ignore benign SSH warnings)
            error_msg = self._extract_error_message(result.stdout, result.stderr)
            success = result.returncode == 0 and not error_msg

            # Save detailed log if failed OR if there's stderr output
            if not success or result.stderr:
                log_file = output_dir / f"{device_name}.log"
                with open(log_file, 'w') as f:
                    f.write(f"Command: {' '.join(cmd_args)}\n")
                    f.write(f"Device: {device_name} ({host})\n")
                    f.write(f"Credentials ID: {cred_id}\n")
                    f.write(f"Auth method: {'key-based' if self.use_keys else 'password-based'}\n")
                    f.write(f"Return code: {result.returncode}\n")
                    f.write(f"Execution time: {execution_time:.2f}s\n")
                    f.write(f"\n{'=' * 60}\nSTDERR:\n{result.stderr}\n")
                    if result.stdout:
                        f.write(f"\n{'=' * 60}\nSTDOUT:\n{result.stdout}\n")

            return {
                'device': device_name,
                'host': host,
                'cred_id': cred_id,
                'success': success,
                'return_code': result.returncode,
                'execution_time': execution_time,
                'output_file': str(output_file),
                'auth_method': 'key-based' if self.use_keys else 'password-based',
                'message': 'Completed successfully' if success else error_msg
            }

        except subprocess.TimeoutExpired:
            return {
                'device': device_name,
                'host': host,
                'cred_id': cred_id,
                'success': False,
                'message': 'Command timed out (600s)',
                'execution_time': 600
            }
        except Exception as e:
            return {
                'device': device_name,
                'host': host,
                'cred_id': cred_id,
                'success': False,
                'message': f'Execution error: {str(e)}',
                'execution_time': 0
            }
    def _generate_summary(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Generate execution summary"""
        total_time = (end_time - start_time).total_seconds()
        successful = len([r for r in self.execution_results if r['success']])
        failed = len(self.execution_results) - successful

        summary = {
            'total_devices': len(self.execution_results),
            'successful': successful,
            'failed': failed,
            'total_execution_time': total_time,
            'auth_method': 'key-based' if self.use_keys else 'password-based',
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'results': self.execution_results
        }

        print(f"\n{'=' * 60}")
        print(f"EXECUTION SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total devices: {summary['total_devices']}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Auth method: {summary['auth_method']}")
        print(f"Total time: {total_time:.1f}s")
        print(f"Average time per device: {total_time / len(self.execution_results):.1f}s")

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


def main():
    parser = argparse.ArgumentParser(
        description="Batch SSH automation wrapper - FIXED VERSION",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python batch_spn_fixed.py sessions.yaml --vendor cisco -c "show version" -o version
        """
    )

    parser.add_argument('yaml_files', nargs='+', help='YAML session files to process')
    parser.add_argument('--folder', help='Filter by folder name (supports wildcards)')
    parser.add_argument('--name', help='Filter by device display name (supports wildcards)')
    parser.add_argument('--vendor', help='Filter by vendor (supports wildcards)')
    parser.add_argument('--device-type', help='Filter by device type')
    parser.add_argument('--use-keys', default=False, action='store_true', help='Use SSH key-based authentication')
    parser.add_argument('--ssh-key', help='Path to SSH private key')
    parser.add_argument('-c', '--commands', required=True, help='Commands to execute')
    parser.add_argument('-o', '--output', required=True, help='Output subdirectory')
    parser.add_argument('--output-base', default='capture', help='Base output directory')
    parser.add_argument('--max-workers', type=int, default=5, help='Maximum parallel executions')
    parser.add_argument('--spn-script', default='spn.py', help='Path to spn.py script')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be executed')
    parser.add_argument('--save-summary', help='Save execution summary to JSON file')
    parser.add_argument('--list-devices', action='store_true', help='Just list matching devices')

    args = parser.parse_args()
    ssh_user = os.getenv("SSH_USER")
    ssh_password = os.getenv("SSH_PASSWORD")

    if ssh_user:
        parser.add_argument('--user', default=ssh_user, help='SSH username (from SSH_USER env var)')
    if ssh_password:
        parser.add_argument('--password', default=ssh_password, help='SSH password (from SSH_PASSWORD env var)')

    print("Loading session files...")
    sessions = load_sessions(args.yaml_files)

    device_filter = DeviceFilter(sessions)
    matched_devices = device_filter.filter_devices(
        folder_pattern=args.folder,
        name_pattern=args.name,
        vendor_pattern=args.vendor,
        device_type=args.device_type
    )

    if not matched_devices:
        print("No devices matched the specified criteria.")
        sys.exit(1)

    print(f"\nMatched {len(matched_devices)} devices:")
    for device in matched_devices:
        vendor = device.get('Vendor', 'Unknown')
        folder = device.get('folder_name', 'Unknown')
        print(f"  - {device['display_name']} ({device['host']}) [{vendor}] in '{folder}'")

    if args.list_devices:
        sys.exit(0)

    executor = BatchExecutor(
        args.spn_script,
        args.output_base,
        use_keys=args.use_keys,
        ssh_key_path=args.ssh_key
    )

    summary = executor.execute_batch(
        devices=matched_devices,
        commands=args.commands,
        output_subdir=args.output,
        max_workers=args.max_workers,
        dry_run=args.dry_run
    )

    if args.save_summary and not args.dry_run:
        with open(args.save_summary, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\nExecution summary saved to {args.save_summary}")


if __name__ == "__main__":
    main()