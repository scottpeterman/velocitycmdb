#!/usr/bin/env python3
"""
PNI Analytics Data Collector
Collects BGP neighbor statistics from devices using the pni_analytics_job.json definition

FIXED: Commands are now passed as strings (not lists) to execute_command()

JSON OUTPUT STRATEGY:
- All vendors use structured JSON output (| json or | display json)
- This eliminates the need for text parsing and separators
- Provides consistent, reliable data extraction across vendors
- Juniper: | display json
- Arista EOS: | json
- Cisco IOS-XE: | json
"""

import json
import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import time

# Import your existing SSH client
from ssh_client import SSHClient, SSHClientOptions

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PNIDataCollector:
    """Collects BGP peer statistics from network devices"""

    def __init__(self, job_file: Path, ssh_key_path: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None,
                 output_dir: Path = Path('./pni_data'), debug: bool = False,
                 max_devices: int = 1, domain_suffix: str = 'kentik.com'):
        """
        Initialize PNI data collector

        Args:
            job_file: Path to pni_analytics_job.json
            ssh_key_path: Path to SSH private key
            username: SSH username (if not using key)
            password: SSH password (if not using key)
            output_dir: Directory to save collected data
            debug: Enable debug logging
            max_devices: Maximum number of devices to collect from (default: 1)
            domain_suffix: Domain suffix to append to device names (default: kentik.com)
        """
        self.job_file = job_file
        self.ssh_key_path = ssh_key_path
        self.username = username
        self.password = password
        self.output_dir = output_dir
        self.debug = debug
        self.max_devices = max_devices
        self.domain_suffix = domain_suffix

        # Validate SSH key if provided
        if self.ssh_key_path:
            self._validate_ssh_key()

        # Load job definition
        with open(job_file, 'r') as f:
            self.job_def = json.load(f)

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Collection timestamp
        self.collection_time = datetime.now().isoformat() + 'Z'

        logger.info(f"\n{'=' * 60}")
        logger.info("DOMAIN CONFIGURATION")
        logger.info(f"{'=' * 60}")
        logger.info(f"Domain Suffix: {self.domain_suffix}")
        logger.info(f"Device names will be resolved as: <device>.{self.domain_suffix}")
        logger.info(f"Example: edge01.iad1 → edge01.iad1.{self.domain_suffix}")
        logger.info(f"{'=' * 60}\n")

    def _build_fqdn(self, device_name: str) -> str:
        """
        Build FQDN from device name and domain suffix

        Args:
            device_name: Short device name (e.g., edge01.iad1)

        Returns:
            FQDN (e.g., edge01.iad1home.com)
        """
        # Check if device_name already has the domain suffix
        if device_name.endswith(f'.{self.domain_suffix}'):
            return device_name

        # Check if device_name already looks like an FQDN (has 3+ parts)
        parts = device_name.split('.')
        if len(parts) >= 3:
            logger.debug(f"Device name {device_name} appears to be FQDN, using as-is")
            return device_name

        # Append domain suffix
        fqdn = f"{device_name}.{self.domain_suffix}"
        logger.debug(f"Built FQDN: {device_name} → {fqdn}")
        return fqdn

    def _validate_ssh_key(self):
        """Validate SSH key exists and has correct permissions"""
        key_path = Path(self.ssh_key_path)

        logger.info(f"\n{'=' * 60}")
        logger.info("SSH KEY VALIDATION")
        logger.info(f"{'=' * 60}")
        logger.info(f"Key Path: {self.ssh_key_path}")

        # Check if key exists
        if not key_path.exists():
            logger.error(f"❌ SSH key does not exist: {self.ssh_key_path}")
            raise FileNotFoundError(f"SSH key not found: {self.ssh_key_path}")
        else:
            logger.info(f"✓ Key file exists")

        # Check if key is readable
        if not os.access(key_path, os.R_OK):
            logger.error(f"❌ SSH key is not readable: {self.ssh_key_path}")
            raise PermissionError(f"Cannot read SSH key: {self.ssh_key_path}")
        else:
            logger.info(f"✓ Key file is readable")

        # Check key permissions (should be 600 or 400)
        import stat
        key_stat = key_path.stat()
        key_perms = oct(key_stat.st_mode)[-3:]

        logger.info(f"Key Permissions: {key_perms}")

        if key_perms not in ['600', '400']:
            logger.warning(f"⚠️  SSH key permissions are {key_perms}, should be 600 or 400")
            logger.warning(f"   Fix with: chmod 600 {self.ssh_key_path}")
        else:
            logger.info(f"✓ Key permissions are correct ({key_perms})")

        # Try to read key header to validate it's a valid key
        try:
            with open(key_path, 'r') as f:
                first_line = f.readline().strip()

            if 'PRIVATE KEY' in first_line:
                logger.info(f"✓ Valid private key format detected")
                logger.info(f"  Key Type: {first_line}")
            else:
                logger.warning(f"⚠️  Key file doesn't appear to be a private key")
                logger.warning(f"  First line: {first_line[:50]}...")
        except Exception as e:
            logger.warning(f"⚠️  Could not validate key format: {e}")

        logger.info(f"{'=' * 60}\n")

    def _get_vendor_commands(self, vendor: str, peer_ip: str) -> Dict[str, str]:
        """
        Get BGP commands for a specific vendor

        All vendors use JSON output format for consistent parsing:
        - Juniper: | display json
        - Arista: | json
        - Cisco IOS-XE: | json

        Returns:
            Dict with command names as keys and CLI commands as values
        """
        vendor_lower = vendor.lower()

        if 'juniper' in vendor_lower:
            return {
                'neighbor_summary': f'show bgp neighbor {peer_ip}',
                'received_routes': f'show route receive-protocol bgp {peer_ip}',
                'active_routes': f'show route receive-protocol bgp {peer_ip} active-path'
            }
        elif 'arista' in vendor_lower:
            # Arista EOS uses | json format
            return {
                'neighbor_summary': f'"show bgp neighbors {peer_ip} | json"',
                'received_routes': f'"show ip bgp neighbors {peer_ip} routes | json"',
                'active_routes': f'"show ip bgp neighbors {peer_ip} routes | json"'  # Arista shows active by default
            }
        elif 'cisco' in vendor_lower:
            # Cisco IOS-XE uses | json format
            return {
                'neighbor_summary': f'show bgp neighbors {peer_ip} | json',
                'received_routes': f'show bgp neighbors {peer_ip} routes | json',
                'active_routes': f'show bgp neighbors {peer_ip} routes | json'
            }
        else:
            logger.warning(f"Unknown vendor: {vendor}, using Juniper commands")
            return self._get_vendor_commands('Juniper', peer_ip)

    def _parse_juniper_output(self, output: str, command_type: str) -> Dict:
        """Parse Juniper JSON output"""
        try:
            data = json.loads(output)

            if command_type == 'neighbor_summary':
                # Extract neighbor state and prefix counts
                bgp_info = data.get('bgp-information', [{}])[0]
                peer_info = bgp_info.get('bgp-peer', [{}])[0]

                return {
                    'state': peer_info.get('peer-state', [{'data': 'Unknown'}])[0].get('data'),
                    'received_routes': int(peer_info.get('bgp-rib', [{}])[0]
                                           .get('received-prefix-count', [{'data': '0'}])[0].get('data', '0')),
                    'active_routes': int(peer_info.get('bgp-rib', [{}])[0]
                                         .get('active-prefix-count', [{'data': '0'}])[0].get('data', '0')),
                    'peer_as': peer_info.get('peer-as', [{'data': 'Unknown'}])[0].get('data'),
                    'local_as': peer_info.get('local-as', [{'data': 'Unknown'}])[0].get('data')
                }

            elif command_type == 'received_routes':
                # Count received routes
                route_table = data.get('route-information', [{}])[0]
                routes = route_table.get('route-table', [{}])[0].get('rt', [])
                return {'count': len(routes)}

            elif command_type == 'active_routes':
                # Count active routes
                route_table = data.get('route-information', [{}])[0]
                routes = route_table.get('route-table', [{}])[0].get('rt', [])
                return {'count': len(routes)}

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Error parsing Juniper output for {command_type}: {e}")
            return {'error': str(e), 'raw_output': output[:500]}

        return {}

    def _parse_arista_output(self, output: str, command_type: str) -> Dict:
        """Parse Arista JSON output"""
        try:
            data = json.loads(output)

            if command_type == 'neighbor_summary':
                # Arista BGP neighbor structure
                peer_data = data.get('vrfs', {}).get('default', {}).get('peers', {})
                if peer_data:
                    peer_ip = list(peer_data.keys())[0]
                    peer_info = peer_data[peer_ip]

                    return {
                        'state': peer_info.get('peerState', 'Unknown'),
                        'received_routes': peer_info.get('prefixReceived', 0),
                        'active_routes': peer_info.get('prefixAccepted', 0),
                        'peer_as': peer_info.get('asn', 'Unknown'),
                        'local_as': peer_info.get('localAsn', 'Unknown')
                    }

            elif command_type in ['received_routes', 'active_routes']:
                # Count routes from route table
                routes = data.get('bgpRouteEntries', {})
                return {'count': len(routes)}

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing Arista output for {command_type}: {e}")
            return {'error': str(e), 'raw_output': output[:500]}

        return {}

    def collect_peer_data(self, device: Dict, peer: Dict) -> Dict:
        """
        Collect data for a single peer on a device

        Args:
            device: Device dict from job definition
            peer: Peer dict from job definition

        Returns:
            Dict containing collected peer data
        """
        device_name = device['device_name'] + "home.com"
        peer_ip = peer['peer_ip']
        vendor = device['vendor']

        logger.info(f"Collecting data from {device_name} for peer {peer_ip} (AS{peer['peer_as']})")

        # Debug SSH connection details
        logger.info(f"\n{'=' * 60}")
        logger.info("SSH CONNECTION DETAILS")
        logger.info(f"{'=' * 60}")
        logger.info(f"Target Device: {device_name}")
        logger.info(f"Username: {self.username}")
        logger.info(f"Using SSH Key: {bool(self.ssh_key_path)}")
        if self.ssh_key_path:
            logger.info(f"Key Path: {self.ssh_key_path}")
        logger.info(f"Using Password: {bool(self.password)}")
        logger.info(f"Vendor: {vendor}")
        logger.info(f"{'=' * 60}\n")

        # Prepare SSH options
        # IMPORTANT: Even with key auth, pass empty string password to trigger proper auth flow
        ssh_options = SSHClientOptions(
            host=device_name,
            username=self.username,
            password=self.password if self.password else "",  # Pass empty string if no password
            ssh_key_path=self.ssh_key_path,
            timeout=60,
            debug=self.debug,
            display_name=device_name
        )

        # Log what auth method will be attempted
        if self.ssh_key_path and self.username:
            logger.info("Authentication Method: SSH Key + Username")
        elif self.password and self.username:
            logger.info("Authentication Method: Password + Username")
        else:
            logger.warning("⚠️  No valid authentication method configured!")

        # Result structure
        result = {
            'device_name': device_name,
            'peer_ip': peer_ip,
            'peer_as': peer['peer_as'],
            'peer_group': peer['peer_group'],
            'description': peer['description'],
            'collected_at': self.collection_time,
            'vendor': vendor,
            'collection_status': 'pending',
            'ssh_auth_method': 'key' if self.ssh_key_path else 'password',
            'commands': {},
            'analysis': {}
        }

        try:
            # Create SSH client
            logger.info(f"Establishing SSH connection to {device_name}...")
            client = SSHClient(ssh_options)
            logger.info(f"✓ SSH connection established successfully")

            # Get vendor-specific commands
            commands = self._get_vendor_commands(vendor, peer_ip)

            # Execute each command - FIXED: Pass command as STRING not LIST
            for cmd_name, cmd in commands.items():
                try:
                    logger.debug(f"  Executing: {cmd}")
                    # CRITICAL FIX: Pass cmd directly as string, not [cmd] as list
                    output = client.execute_command(cmd)

                    result['commands'][cmd_name] = {
                        'command': cmd,
                        'output': output,
                        'success': True
                    }

                except Exception as e:
                    logger.error(f"  Command failed ({cmd_name}): {e}")
                    result['commands'][cmd_name] = {
                        'command': cmd,
                        'error': str(e),
                        'success': False
                    }

            # Disconnect
            logger.info(f"Disconnecting from {device_name}...")
            client.disconnect()
            logger.info(f"✓ Disconnected successfully")

            # Parse results
            if 'juniper' in vendor.lower():
                if 'neighbor_summary' in result['commands'] and result['commands']['neighbor_summary']['success']:
                    parsed = self._parse_juniper_output(
                        result['commands']['neighbor_summary']['output'],
                        'neighbor_summary'
                    )
                    result['analysis'] = parsed
            elif 'arista' in vendor.lower():
                if 'neighbor_summary' in result['commands'] and result['commands']['neighbor_summary']['success']:
                    parsed = self._parse_arista_output(
                        result['commands']['neighbor_summary']['output'],
                        'neighbor_summary'
                    )
                    result['analysis'] = parsed

            # Determine if this is a zombie peer
            analysis = result.get('analysis', {})
            if analysis:
                received = analysis.get('received_routes', 0)
                active = analysis.get('active_routes', 0)

                result['analysis']['is_zombie'] = (received > 0 and active == 0)
                result['analysis']['is_healthy'] = (received > 0 and active > 0)
                result['analysis']['is_down'] = (analysis.get('state', '').lower() != 'established')

            result['collection_status'] = 'success'
            logger.info(f"  ✓ Collection successful - State: {analysis.get('state', 'Unknown')}, "
                        f"Received: {analysis.get('received_routes', 0)}, "
                        f"Active: {analysis.get('active_routes', 0)}")

        except Exception as e:
            logger.error(f"\n{'=' * 60}")
            logger.error(f"❌ SSH CONNECTION FAILED")
            logger.error(f"{'=' * 60}")
            logger.error(f"Device: {device_name}")
            logger.error(f"Error Type: {type(e).__name__}")
            logger.error(f"Error Message: {str(e)}")

            # Add more context for common errors
            error_str = str(e).lower()
            if 'authentication' in error_str or 'permission denied' in error_str:
                logger.error(f"\n⚠️  AUTHENTICATION FAILURE")
                if self.ssh_key_path:
                    logger.error(f"   Key Path: {self.ssh_key_path}")
                    logger.error(f"   Troubleshooting:")
                    logger.error(f"   1. Verify key is in authorized_keys on {device_name}")
                    logger.error(f"   2. Check key permissions: chmod 600 {self.ssh_key_path}")
                    logger.error(f"   3. Test manually: ssh -i {self.ssh_key_path} {self.username}@{device_name}")
                else:
                    logger.error(f"   Using password authentication")
                    logger.error(f"   Verify password is correct for user: {self.username}")
            elif 'timeout' in error_str or 'timed out' in error_str:
                logger.error(f"\n⚠️  CONNECTION TIMEOUT")
                logger.error(f"   1. Verify device is reachable: ping {device_name}")
                logger.error(f"   2. Check firewall rules")
                logger.error(f"   3. Verify SSH is running on device")
            elif 'connection refused' in error_str:
                logger.error(f"\n⚠️  CONNECTION REFUSED")
                logger.error(f"   1. Verify SSH is running on {device_name}")
                logger.error(f"   2. Check if SSH is on non-standard port")
            elif 'host key' in error_str:
                logger.error(f"\n⚠️  HOST KEY VERIFICATION FAILED")
                logger.error(f"   1. Add {device_name} to known_hosts")
                logger.error(f"   2. Or connect manually once: ssh {self.username}@{device_name}")

            logger.error(f"{'=' * 60}\n")

            result['collection_status'] = 'failed'
            result['error'] = str(e)
            result['error_type'] = type(e).__name__

            if self.debug:
                import traceback
                logger.debug("Full traceback:")
                logger.debug(traceback.format_exc())

        return result

    def collect_device(self, device: Dict) -> Dict:
        """
        Collect data for all peers on a device

        Args:
            device: Device dict from job definition

        Returns:
            Dict containing all peer data for device
        """
        device_name = device['device_name']
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Device: {device_name} ({device['vendor']}, {device['site']})")
        logger.info(f"PNI Peers: {device['pni_peer_count']}")
        logger.info(f"{'=' * 60}")

        device_result = {
            'device_name': device_name,
            'vendor': device['vendor'],
            'site': device['site'],
            'local_asn': device['local_asn'],
            'collection_time': self.collection_time,
            'peer_count': device['pni_peer_count'],
            'peers': []
        }

        # Collect data for each peer
        for peer in device['peers']:
            peer_result = self.collect_peer_data(device, peer)
            device_result['peers'].append(peer_result)

            # Small delay between peers to avoid overwhelming device
            time.sleep(0.5)

        return device_result

    def run_collection(self, device_filter: Optional[str] = None) -> Dict:
        """
        Run full PNI data collection

        Args:
            device_filter: Optional device name filter

        Returns:
            Dict containing all collected data
        """
        logger.info(f"\n{'=' * 80}")
        logger.info("PNI ANALYTICS DATA COLLECTION")
        logger.info(f"{'=' * 80}")
        logger.info(f"Job File: {self.job_file}")
        logger.info(f"Total Devices in Job: {self.job_def['collection_scope']['total_devices']}")
        logger.info(f"Total Peers in Job: {self.job_def['collection_scope']['total_peers']}")
        logger.info(f"Max Devices Limit: {self.max_devices}")
        logger.info(f"Output Directory: {self.output_dir}")

        # Authentication summary
        logger.info(f"\nAuthentication:")
        logger.info(f"  Username: {self.username}")
        if self.ssh_key_path:
            logger.info(f"  SSH Key: {self.ssh_key_path}")
        if self.password:
            logger.info(f"  Password: {'*' * len(self.password)}")

        logger.info(f"{'=' * 80}\n")

        # Filter devices if requested
        devices = self.job_def['devices']
        if device_filter:
            devices = [d for d in devices if device_filter.lower() in d['device_name'].lower()]
            logger.info(f"Filter applied: {len(devices)} devices match '{device_filter}'")

        # Apply max_devices limit
        original_device_count = len(devices)
        if len(devices) > self.max_devices:
            logger.warning(
                f"\n⚠️  Limiting collection to first {self.max_devices} device(s) (found {original_device_count})")
            logger.warning(f"   Devices to collect from:")
            for i, d in enumerate(devices[:self.max_devices], 1):
                logger.warning(f"   {i}. {d['device_name']} ({d['pni_peer_count']} peers)")
            logger.warning(f"   Skipping {original_device_count - self.max_devices} device(s)")
            logger.warning(f"   To collect from more devices, use: --max-devices {original_device_count}\n")
            devices = devices[:self.max_devices]
        else:
            logger.info(f"Collecting from {len(devices)} device(s):")
            for i, d in enumerate(devices, 1):
                logger.info(f"  {i}. {d['device_name']} ({d['pni_peer_count']} peers)")

        collection_results = {
            'metadata': {
                'collection_started': self.collection_time,
                'job_file': str(self.job_file),
                'devices_in_job': self.job_def['collection_scope']['total_devices'],
                'devices_targeted': len(devices),
                'devices_limited_by_max': original_device_count > self.max_devices,
                'max_devices_setting': self.max_devices,
                'total_peers_targeted': sum(d['pni_peer_count'] for d in devices),
                'device_filter': device_filter,
                'ssh_key_used': bool(self.ssh_key_path),
                'ssh_key_path': self.ssh_key_path if self.ssh_key_path else None
            },
            'devices': []
        }

        # Collect from each device
        for i, device in enumerate(devices, 1):
            logger.info(f"\n{'#' * 80}")
            logger.info(f"DEVICE {i}/{len(devices)}")
            logger.info(f"{'#' * 80}")

            device_result = self.collect_device(device)
            collection_results['devices'].append(device_result)

            # Save device-specific results
            device_output_file = self.output_dir / f"{device['device_name']}_pni_data.json"
            with open(device_output_file, 'w') as f:
                json.dump(device_result, f, indent=2)
            logger.info(f"Saved device data: {device_output_file}\n")

        # Save complete results
        complete_output = self.output_dir / f"pni_collection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(complete_output, 'w') as f:
            json.dump(collection_results, f, indent=2)

        logger.info(f"\n{'=' * 80}")
        logger.info("COLLECTION COMPLETE")
        logger.info(f"{'=' * 80}")
        logger.info(f"Complete results saved: {complete_output}")

        # Generate summary report
        self._generate_summary(collection_results)

        return collection_results

    def _generate_summary(self, results: Dict):
        """Generate and display summary of collection"""
        total_peers = 0
        successful = 0
        failed = 0
        zombie_peers = []
        down_peers = []

        for device in results['devices']:
            for peer in device['peers']:
                total_peers += 1

                if peer['collection_status'] == 'success':
                    successful += 1

                    analysis = peer.get('analysis', {})
                    if analysis.get('is_zombie'):
                        zombie_peers.append({
                            'device': device['device_name'],
                            'peer_ip': peer['peer_ip'],
                            'peer_as': peer['peer_as'],
                            'description': peer['description'],
                            'received': analysis.get('received_routes', 0),
                            'active': analysis.get('active_routes', 0)
                        })

                    if analysis.get('is_down'):
                        down_peers.append({
                            'device': device['device_name'],
                            'peer_ip': peer['peer_ip'],
                            'peer_as': peer['peer_as'],
                            'description': peer['description'],
                            'state': analysis.get('state', 'Unknown')
                        })
                else:
                    failed += 1

        logger.info(f"\nCollection Summary:")
        logger.info(f"  Total Peers: {total_peers}")
        logger.info(f"  Successful: {successful}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Zombie Peers: {len(zombie_peers)}")
        logger.info(f"  Down Peers: {len(down_peers)}")

        if zombie_peers:
            logger.warning(f"\n⚠️  ZOMBIE PEERS DETECTED ({len(zombie_peers)}):")
            for zp in zombie_peers:
                logger.warning(f"  {zp['device']}: {zp['peer_ip']} (AS{zp['peer_as']}) - "
                               f"{zp['description']} - Received: {zp['received']}, Active: 0")

        if down_peers:
            logger.warning(f"\n⚠️  DOWN PEERS ({len(down_peers)}):")
            for dp in down_peers:
                logger.warning(f"  {dp['device']}: {dp['peer_ip']} (AS{dp['peer_as']}) - "
                               f"{dp['description']} - State: {dp['state']}")


def main():
    parser = argparse.ArgumentParser(description='PNI Analytics Data Collector')
    parser.add_argument('--job-file', type=Path, default='./bgp_analytics/pni_analytics_job.json',
                        help='Path to PNI analytics job definition')
    parser.add_argument('--ssh-key', type=str, help='Path to SSH private key')
    parser.add_argument('--username', type=str, help='SSH username')
    parser.add_argument('--password', type=str, help='SSH password')
    parser.add_argument('--output-dir', type=Path, default='./pni_data',
                        help='Output directory for collected data')
    parser.add_argument('--device-filter', type=str,
                        help='Filter devices by name (case-insensitive substring match)')
    parser.add_argument('--max-devices', type=int, default=1,
                        help='Maximum number of devices to collect from (default: 1)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Set logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Validate job file
    if not args.job_file.exists():
        logger.error(f"❌ Job file not found: {args.job_file}")
        logger.error(f"   Generate it first with: python3 analyze_peer_groups.py")
        return 1

    # Check authentication
    if not args.ssh_key and not (args.username and args.password):
        logger.error("❌ Authentication required!")
        logger.error("   Must provide either:")
        logger.error("     --ssh-key <path> --username <user>  OR")
        logger.error("     --username <user> --password <pass>")
        logger.error("\nExample:")
        logger.error("  python3 pni_collector.py --ssh-key ~/.ssh/id_rsa --username speterman")
        return 1

    # If using SSH key without password, ensure we have username
    if args.ssh_key and not args.username:
        logger.error("❌ Username required when using SSH key!")
        logger.error("   Usage: --ssh-key <path> --username <user>")
        return 1

    # Validate SSH key if provided
    if args.ssh_key:
        if not Path(args.ssh_key).exists():
            logger.error(f"❌ SSH key not found: {args.ssh_key}")
            logger.error(f"   Check the path and try again")
            return 1

    # Create collector
    try:
        collector = PNIDataCollector(
            job_file=args.job_file,
            ssh_key_path=args.ssh_key,
            username=args.username,
            password=args.password,
            output_dir=args.output_dir,
            debug=args.debug,
            max_devices=args.max_devices
        )
    except Exception as e:
        logger.error(f"❌ Failed to initialize collector: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1

    # Run collection
    try:
        collector.run_collection(device_filter=args.device_filter)
        return 0
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Collection interrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        logger.error(f"\n❌ Collection failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())