"""
Fingerprinting orchestration service
Wraps existing device_fingerprint.py and db_load_fingerprints.py
"""

import os
import sys
from pathlib import Path
from typing import Dict, Callable, Optional, List
import yaml
import json
from datetime import datetime
import time

# Add pcng to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'pcng'))


class FingerprintOrchestrator:
    """
    Orchestrates device fingerprinting and database loading

    Pipeline:
    1. Parse sessions.yaml
    2. Fingerprint each device (SSH + show version + TextFSM)
    3. Save fingerprint JSON files
    4. Load JSONs into assets.db
    """

    def __init__(self, data_dir: Path):
        """
        Args:
            data_dir: Base data directory (e.g., ~/.velocitycmdb/data)
        """
        self.data_dir = Path(data_dir)
        self.fingerprints_dir = self.data_dir / 'fingerprints'
        self.fingerprints_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / 'assets.db'

        # TextFSM template database path
        self.textfsm_db = self._find_textfsm_db()

    def _find_textfsm_db(self) -> Optional[Path]:
        """Find TextFSM template database"""
        possible_paths = [
            Path(__file__).parent.parent / 'pcng' / 'tfsm_templates.db',
            Path.cwd() / 'tfsm_templates.db',
            Path.cwd() / 'pcng' / 'tfsm_templates.db',
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def fingerprint_inventory(self,
                              sessions_file: Path,
                              username: str,
                              password: str,
                              ssh_key_path: Optional[str] = None,
                              progress_callback: Optional[Callable] = None) -> Dict:
        """
        Fingerprint all devices in inventory and load into database

        Args:
            sessions_file: Path to sessions.yaml from discovery
            username: SSH username
            password: SSH password
            ssh_key_path: Optional SSH key path
            progress_callback: Function(dict) for progress updates

        Returns:
            {
                'success': True,
                'fingerprinted': 12,
                'failed': 0,
                'loaded_to_db': 12,
                'fingerprints_dir': Path(...),
                'db_path': Path(...)
            }
        """

        if progress_callback:
            progress_callback({
                'stage': 'fingerprinting',
                'progress': 0,
                'message': 'Loading device inventory...'
            })

        # Parse sessions.yaml
        devices = self._parse_sessions_yaml(sessions_file)
        total_devices = len(devices)

        if progress_callback:
            progress_callback({
                'stage': 'fingerprinting',
                'progress': 5,
                'message': f'Found {total_devices} devices to fingerprint'
            })

        # Fingerprint each device
        fingerprinted = 0
        failed = 0
        failed_devices = []

        for i, device in enumerate(devices):
            device_name = device['name']
            device_ip = device['ip']

            try:
                if progress_callback:
                    progress_callback({
                        'stage': 'fingerprinting',
                        'progress': int(5 + (i / total_devices * 70)),
                        'message': f'Fingerprinting {device_name} ({device_ip})...',
                        'current_device': device_name,
                        'devices_completed': i,
                        'devices_total': total_devices
                    })

                # Fingerprint device
                result = self._fingerprint_single_device(
                    device_ip=device_ip,
                    device_name=device_name,
                    username=username,
                    password=password,
                    ssh_key_path=ssh_key_path
                )

                if result['success']:
                    fingerprinted += 1
                else:
                    failed += 1
                    failed_devices.append({
                        'name': device_name,
                        'ip': device_ip,
                        'error': result.get('error', 'Unknown error')
                    })

            except Exception as e:
                failed += 1
                failed_devices.append({
                    'name': device_name,
                    'ip': device_ip,
                    'error': str(e)
                })

                if progress_callback:
                    progress_callback({
                        'stage': 'fingerprinting',
                        'progress': int(5 + (i / total_devices * 70)),
                        'message': f'Failed to fingerprint {device_name}: {str(e)}',
                        'error': str(e)
                    })

        # Load fingerprints into database
        if fingerprinted > 0:
            if progress_callback:
                progress_callback({
                    'stage': 'loading',
                    'progress': 80,
                    'message': f'Loading {fingerprinted} fingerprints into database...'
                })

            db_result = self._load_fingerprints_to_db(progress_callback)

            if progress_callback:
                progress_callback({
                    'stage': 'complete',
                    'progress': 100,
                    'message': f'✓ Fingerprinted {fingerprinted} devices, loaded {db_result["success"]} to database'
                })
        else:
            db_result = {'success': 0, 'failed': 0, 'total': 0}

            if progress_callback:
                progress_callback({
                    'stage': 'error',
                    'progress': 100,
                    'message': 'No devices were successfully fingerprinted'
                })

        return {
            'success': fingerprinted > 0,
            'fingerprinted': fingerprinted,
            'failed': failed,
            'failed_devices': failed_devices,
            'loaded_to_db': db_result['success'],
            'db_load_failed': db_result['failed'],
            'fingerprints_dir': self.fingerprints_dir,
            'db_path': self.db_path
        }

    def _parse_sessions_yaml(self, sessions_file: Path) -> List[Dict]:
        """Parse sessions.yaml into list of devices"""
        with open(sessions_file, 'r') as f:
            data = yaml.safe_load(f)

        devices = []
        for site in data:
            site_name = site.get('folder_name', 'Unknown')
            for session in site.get('sessions', []):
                devices.append({
                    'name': session.get('display_name', session.get('name', 'unknown')),
                    'ip': session.get('host', session.get('ip', '')),
                    'site': site_name,
                    'vendor': session.get('Vendor', ''),
                    'model': session.get('Model', '')
                })

        return devices

    def _fingerprint_single_device(self,
                                   device_ip: str,
                                   device_name: str,
                                   username: str,
                                   password: str,
                                   ssh_key_path: Optional[str] = None) -> Dict:
        """
        Fingerprint a single device using device_fingerprint.py
        """
        from device_fingerprint import DeviceFingerprint

        output_file = self.fingerprints_dir / f'{device_name}.json'

        try:
            # Create fingerprinter with SSH key support
            fingerprinter = DeviceFingerprint(
                host=device_ip,
                port=22,
                username=username,
                password=password,
                ssh_key_path=ssh_key_path,  # Pass SSH key if provided
                debug=False,
                verbose=False,
                connection_timeout=10000,
                textfsm_db_path=str(self.textfsm_db) if self.textfsm_db else None
            )

            # Store the display_name from YAML before fingerprinting
            # This ensures we preserve the user-provided name
            fingerprinter._device_info.additional_info['yaml_display_name'] = device_name

            # Run fingerprinting
            device_info = fingerprinter.fingerprint()
            print(f"DEBUG: fingerprint() returned, building result dict")  # ADD THIS

            # Convert to JSON
            result = {
                'host': device_info.host,
                'port': device_info.port,
                'device_type': device_info.device_type.value,
                'detected_prompt': device_info.detected_prompt,
                'disable_paging_command': device_info.disable_paging_command,
                'hostname': device_info.hostname,
                'model': device_info.model,
                'version': device_info.version,
                'serial_number': device_info.serial_number,
                'is_virtual_device': device_info.is_virtual_device,
                'platform': device_info.platform,
                'uptime': device_info.uptime,
                'additional_info': device_info.additional_info,
                'interfaces': device_info.interfaces,
                'ip_addresses': device_info.ip_addresses,
                'cpu_info': device_info.cpu_info,
                'memory_info': device_info.memory_info,
                'storage_info': device_info.storage_info,
                'command_outputs': device_info.command_outputs,
                'fingerprint_time': datetime.now().isoformat(),
                'success': True
            }

            # Save to JSON file
            print(f"DEBUG: Saving JSON to {output_file}")
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
                print(f"DEBUG: Saved successfully -> {output_file}")
            return {
                'success': True,
                'fingerprint_file': output_file,
                'hostname': device_info.hostname,
                'model': device_info.model,
                'vendor': device_info.additional_info.get('vendor', 'Unknown')
            }

        except Exception as e:
            # Save error JSON
            error_result = {
                'host': device_ip,
                'port': 22,
                'hostname': device_name,
                'fingerprint_time': datetime.now().isoformat(),
                'success': False,
                'error': str(e)
            }

            with open(output_file, 'w') as f:
                json.dump(error_result, f, indent=2)

            return {
                'success': False,
                'error': str(e)
            }

    def _load_fingerprints_to_db(self, progress_callback: Optional[Callable] = None) -> Dict:
        """
        Load all fingerprint JSONs into database using db_load_fingerprints.py
        """
        # Import from root level (not pcng)
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from db_load_fingerprints import FingerprintLoader

        try:
            loader = FingerprintLoader(str(self.db_path))

            results = loader.load_fingerprints_directory(self.fingerprints_dir)

            return {
                'success': results['success'],
                'failed': results['failed'],
                'total': results['total']
            }

        except Exception as e:
            return {
                'success': 0,
                'failed': 0,
                'total': 0,
                'error': str(e)
            }