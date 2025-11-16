#!/usr/bin/env python3
"""
PNI Analytics Data Collector
Collects BGP neighbor statistics from devices using the pni_analytics_job.json definition

Legacy-safe strategy:
- Juniper: use XML only (| display xml | no-more). No JSON. No 'cli -c'.
- Cisco IOS/IOS-XE (old Catalyst): TEXT parsing only (no JSON).
- Arista EOS: TEXT parsing (you can later re-enable JSON if desired).

Constraints honored:
- Commands passed as strings to execute_command()
- No list/dict comprehensions anywhere
"""

import json
import sys
import os
import re
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import time
import xml.etree.ElementTree as ET

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
        self.job_file = job_file
        self.ssh_key_path = ssh_key_path
        self.username = username
        self.password = password
        self.output_dir = output_dir
        self.debug = debug
        self.max_devices = max_devices
        self.domain_suffix = domain_suffix

        if self.ssh_key_path:
            self._validate_ssh_key()

        with open(job_file, 'r') as f:
            self.job_def = json.load(f)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.collection_time = datetime.now().isoformat() + 'Z'

        logger.info("\n" + "=" * 60)
        logger.info("DOMAIN CONFIGURATION")
        logger.info("=" * 60)
        logger.info("Domain Suffix: {}".format(self.domain_suffix))
        logger.info("Device names will be resolved as: <device>.{}".format(self.domain_suffix))
        logger.info("Example: edge01.iad1 → edge01.iad1.{}".format(self.domain_suffix))
        logger.info("=" * 60 + "\n")

    def _build_fqdn(self, device_name: str) -> str:
        if device_name.endswith('.{}'.format(self.domain_suffix)):
            return device_name

        parts = device_name.split('.')
        if len(parts) >= 3:
            logger.debug("Device name {} appears to be FQDN, using as-is".format(device_name))
            return device_name

        fqdn = "{}.{}".format(device_name, self.domain_suffix)
        logger.debug("Built FQDN: {} → {}".format(device_name, fqdn))
        return fqdn

    def _validate_ssh_key(self):
        key_path = Path(self.ssh_key_path)

        logger.info("\n" + "=" * 60)
        logger.info("SSH KEY VALIDATION")
        logger.info("=" * 60)
        logger.info("Key Path: {}".format(self.ssh_key_path))

        if not key_path.exists():
            logger.error("❌ SSH key does not exist: {}".format(self.ssh_key_path))
            raise FileNotFoundError("SSH key not found: {}".format(self.ssh_key_path))
        else:
            logger.info("✓ Key file exists")

        if not os.access(key_path, os.R_OK):
            logger.error("❌ SSH key is not readable: {}".format(self.ssh_key_path))
            raise PermissionError("Cannot read SSH key: {}".format(self.ssh_key_path))
        else:
            logger.info("✓ Key file is readable")

        key_stat = key_path.stat()
        key_perms = oct(key_stat.st_mode)[-3:]

        logger.info("Key Permissions: {}".format(key_perms))

        if key_perms not in ['600', '400']:
            logger.warning("⚠️  SSH key permissions are {}, should be 600 or 400".format(key_perms))
            logger.warning("   Fix with: chmod 600 {}".format(self.ssh_key_path))
        else:
            logger.info("✓ Key permissions are correct ({})".format(key_perms))

        try:
            with open(key_path, 'r') as f:
                first_line = f.readline().strip()

            if 'PRIVATE KEY' in first_line:
                logger.info("✓ Valid private key format detected")
                logger.info("  Key Type: {}".format(first_line))
            else:
                logger.warning("⚠️  Key file doesn't appear to be a private key")
                logger.warning("  First line: {}...".format(first_line[:50]))
        except Exception as e:
            logger.warning("⚠️  Could not validate key format: {}".format(e))

        logger.info("=" * 60 + "\n")

    def _get_vendor_commands(self, vendor: str, peer_ip: str) -> Dict[str, str]:
        """
        Legacy-safe commands:
          - Juniper: XML output
          - Cisco IOS (old Catalyst/IOS-XE): TEXT output (neighbor detail + received/advertised)
          - Arista: TEXT output
        """
        vendor_lower = vendor.lower()

        if 'juniper' in vendor_lower:
            cmds = {}
            cmds['neighbor_summary'] = "show bgp neighbor {} | display xml | no-more".format(peer_ip)
            cmds['received_routes'] = "show route receive-protocol bgp {} | display xml | no-more".format(peer_ip)
            cmds['active_routes'] = "show route receive-protocol bgp {} active-path | display xml | no-more".format(peer_ip)
            return cmds

        if 'cisco' in vendor_lower:
            cmds = {}
            cmds['neighbor_summary'] = "show ip bgp neighbors {}".format(peer_ip)
            cmds['received_routes'] = "show ip bgp neighbors {} received-routes".format(peer_ip)
            cmds['active_routes'] = "show ip bgp neighbors {} advertised-routes".format(peer_ip)
            return cmds

        if 'arista' in vendor_lower:
            cmds = {}
            cmds['neighbor_summary'] = "show bgp neighbors {}".format(peer_ip)
            cmds['received_routes'] = "show ip bgp neighbors {} routes".format(peer_ip)
            cmds['active_routes'] = "show ip bgp neighbors {} routes".format(peer_ip)
            return cmds

        logger.warning("Unknown vendor: {}. Defaulting to Cisco TEXT commands".format(vendor))
        cmds = {}
        cmds['neighbor_summary'] = "show ip bgp neighbors {}".format(peer_ip)
        cmds['received_routes'] = "show ip bgp neighbors {} received-routes".format(peer_ip)
        cmds['active_routes'] = "show ip bgp neighbors {} advertised-routes".format(peer_ip)
        return cmds

    # -----------------------
    # Juniper XML parsing
    # -----------------------
    def _parse_juniper_xml(self, xml_text: str, command_type: str) -> Dict:
        result = {}
        try:
            root = ET.fromstring(xml_text)
        except Exception as e:
            result["error"] = "XML parse error: {}".format(e)
            if xml_text is not None:
                result["raw_output"] = xml_text[:500]
            return result

        if command_type == "neighbor_summary":
            state = "Unknown"
            received = 0
            active = 0
            peer_as = "Unknown"
            local_as = "Unknown"

            peer_elem = None
            for elem in root.iter("bgp-peer"):
                peer_elem = elem
                break

            if peer_elem is not None:
                ps = None
                for x in peer_elem.iter("peer-state"):
                    ps = x
                    break
                if ps is not None and ps.text is not None:
                    state = ps.text

                rib = None
                for x in peer_elem.iter("bgp-rib"):
                    rib = x
                    break
                if rib is not None:
                    recv_node = None
                    for x in rib.iter("received-prefix-count"):
                        recv_node = x
                        break
                    if recv_node is not None and recv_node.text is not None:
                        try:
                            received = int(recv_node.text)
                        except Exception:
                            received = 0

                    active_node = None
                    for x in rib.iter("active-prefix-count"):
                        active_node = x
                        break
                    if active_node is not None and active_node.text is not None:
                        try:
                            active = int(active_node.text)
                        except Exception:
                            active = 0

                p_as = None
                for x in peer_elem.iter("peer-as"):
                    p_as = x
                    break
                if p_as is not None and p_as.text is not None:
                    peer_as = p_as.text

                l_as = None
                for x in peer_elem.iter("local-as"):
                    l_as = x
                    break
                if l_as is not None and l_as.text is not None:
                    local_as = l_as.text

            result["state"] = state
            result["received_routes"] = received
            result["active_routes"] = active
            result["peer_as"] = peer_as
            result["local_as"] = local_as
            return result

        if command_type == "received_routes" or command_type == "active_routes":
            count = 0
            for rt in root.iter("rt"):
                count = count + 1
            result["count"] = count
            return result

        result["error"] = "unsupported command_type: {}".format(command_type)
        return result

    # -----------------------
    # Cisco / Arista TEXT parsing
    # -----------------------
    def _parse_ipv4_prefix_count(self, text: str) -> int:
        pat = re.compile(r"(^|\s)(\d{1,3}\.){3}\d{1,3}/\d{1,2}(\s|$)")
        count = 0
        for line in text.splitlines():
            if pat.search(line):
                count = count + 1
        return count

    def _parse_ipv6_prefix_count(self, text: str) -> int:
        pat = re.compile(r"([0-9a-fA-F:]+:+)+[0-9a-fA-F]+/\d{1,3}")
        count = 0
        for line in text.splitlines():
            if pat.search(line):
                count = count + 1
        return count

    def _parse_cisco_neighbor_text(self, text: str) -> Dict:
        result = {}
        state = "Unknown"
        local_as = "Unknown"
        peer_as = "Unknown"

        pat_state = re.compile(r"BGP\s+state\s*=\s*([A-Za-z]+)")
        m = pat_state.search(text)
        if m:
            state = m.group(1)

        pat_las = re.compile(r"local\s+AS(\s+number)?\s+(\d+)", re.IGNORECASE)
        m = pat_las.search(text)
        if m:
            local_as = m.group(2)

        pat_pas = re.compile(r"remote\s+AS\s+(\d+)", re.IGNORECASE)
        m = pat_pas.search(text)
        if m:
            peer_as = m.group(1)

        # Fallback hints seen in some IOS trains
        if local_as == "Unknown":
            pat_las2 = re.compile(r"local-AS\s+(\d+)", re.IGNORECASE)
            m = pat_las2.search(text)
            if m:
                local_as = m.group(1)

        if peer_as == "Unknown":
            pat_pas2 = re.compile(r"remote-AS\s+(\d+)", re.IGNORECASE)
            m = pat_pas2.search(text)
            if m:
                peer_as = m.group(1)

        result["state"] = state
        result["local_as"] = local_as
        result["peer_as"] = peer_as
        return result

    def _parse_arista_neighbor_text(self, text: str) -> Dict:
        # EOS text format is similar enough for basic fields
        return self._parse_cisco_neighbor_text(text)

    # -----------------------
    # Arista JSON parser (kept for future; unused in current text-only commands)
    # -----------------------
    def _parse_arista_output(self, output: str, command_type: str) -> Dict:
        try:
            data = json.loads(output)

            if command_type == 'neighbor_summary':
                peer_data = {}
                if isinstance(data, dict):
                    if 'vrfs' in data:
                        vrfs = data.get('vrfs')
                        if isinstance(vrfs, dict):
                            if 'default' in vrfs:
                                default_vrf = vrfs.get('default')
                                if isinstance(default_vrf, dict):
                                    if 'peers' in default_vrf:
                                        peer_data = default_vrf.get('peers')

                if peer_data:
                    first_key = None
                    for k in peer_data.keys():
                        first_key = k
                        break
                    if first_key is not None:
                        peer_info = peer_data.get(first_key)
                        if isinstance(peer_info, dict):
                            state = peer_info.get('peerState', 'Unknown')
                            received_routes = 0
                            active_routes = 0
                            peer_as = peer_info.get('asn', 'Unknown')
                            local_as = peer_info.get('localAsn', 'Unknown')

                            if 'prefixReceived' in peer_info:
                                try:
                                    received_routes = int(peer_info.get('prefixReceived'))
                                except Exception:
                                    received_routes = 0
                            if 'prefixAccepted' in peer_info:
                                try:
                                    active_routes = int(peer_info.get('prefixAccepted'))
                                except Exception:
                                    active_routes = 0

                            res = {}
                            res['state'] = state
                            res['received_routes'] = received_routes
                            res['active_routes'] = active_routes
                            res['peer_as'] = peer_as
                            res['local_as'] = local_as
                            return res

            if command_type == 'received_routes' or command_type == 'active_routes':
                routes = {}
                if isinstance(data, dict):
                    if 'bgpRouteEntries' in data:
                        routes = data.get('bgpRouteEntries')
                count = 0
                if isinstance(routes, dict):
                    for _ in routes.keys():
                        count = count + 1
                return {'count': count}

        except (json.JSONDecodeError, KeyError) as e:
            res = {}
            res['error'] = "Error parsing Arista output for {}: {}".format(command_type, e)
            if output is not None:
                res['raw_output'] = output[:500]
            return res

        return {}

    # -----------------------
    # Collection
    # -----------------------
    def collect_peer_data(self, device: Dict, peer: Dict) -> Dict:
        device_name = device['device_name'] + ".{}".format(self.domain_suffix)
        peer_ip = peer['peer_ip']
        vendor = device['vendor']

        logger.info("Collecting data from {} for peer {} (AS{})".format(device_name, peer_ip, peer['peer_as']))

        logger.info("\n" + "=" * 60)
        logger.info("SSH CONNECTION DETAILS")
        logger.info("=" * 60)
        logger.info("Target Device: {}".format(device_name))
        logger.info("Username: {}".format(self.username))
        logger.info("Using SSH Key: {}".format(bool(self.ssh_key_path)))
        if self.ssh_key_path:
            logger.info("Key Path: {}".format(self.ssh_key_path))
        logger.info("Using Password: {}".format(bool(self.password)))
        logger.info("Vendor: {}".format(vendor))
        logger.info("=" * 60 + "\n")

        ssh_options = SSHClientOptions(
            host=device_name,
            username=self.username,
            password=self.password if self.password else "",
            ssh_key_path=self.ssh_key_path,
            timeout=60,
            debug=self.debug,
            display_name=device_name
        )

        if self.ssh_key_path and self.username:
            logger.info("Authentication Method: SSH Key + Username")
        elif self.password and self.username:
            logger.info("Authentication Method: Password + Username")
        else:
            logger.warning("⚠️  No valid authentication method configured!")

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
            logger.info("Establishing SSH connection to {}...".format(device_name))
            client = SSHClient(ssh_options)
            logger.info("✓ SSH connection established successfully")

            commands = self._get_vendor_commands(vendor, peer_ip)

            # Execute each command (string)
            for cmd_name in commands.keys():
                cmd = commands[cmd_name]
                try:
                    logger.debug("  Executing: {}".format(cmd))
                    output = client.execute_command(cmd)
                    result['commands'][cmd_name] = {
                        'command': cmd,
                        'output': output,
                        'success': True
                    }
                except Exception as e:
                    logger.error("  Command failed ({}): {}".format(cmd_name, e))
                    result['commands'][cmd_name] = {
                        'command': cmd,
                        'error': str(e),
                        'success': False
                    }

            logger.info("Disconnecting from {}...".format(device_name))
            client.disconnect()
            logger.info("✓ Disconnected successfully")

            # -----------------------
            # Parse results per vendor
            # -----------------------
            analysis = {}

            if 'juniper' in vendor.lower():
                if 'neighbor_summary' in result['commands']:
                    rec = result['commands']['neighbor_summary']
                    if rec.get('success'):
                        parsed = self._parse_juniper_xml(rec.get('output', ''), 'neighbor_summary')
                        k_iter = parsed.keys()
                        for k in k_iter:
                            analysis[k] = parsed[k]

                if 'received_routes' in result['commands']:
                    rec = result['commands']['received_routes']
                    if rec.get('success'):
                        parsed = self._parse_juniper_xml(rec.get('output', ''), 'received_routes')
                        analysis['received_routes'] = parsed.get('count', 0)

                if 'active_routes' in result['commands']:
                    rec = result['commands']['active_routes']
                    if rec.get('success'):
                        parsed = self._parse_juniper_xml(rec.get('output', ''), 'active_routes')
                        analysis['active_routes'] = parsed.get('count', 0)

            elif 'cisco' in vendor.lower():
                if 'neighbor_summary' in result['commands']:
                    rec = result['commands']['neighbor_summary']
                    if rec.get('success'):
                        parsed = self._parse_cisco_neighbor_text(rec.get('output', ''))
                        k_iter = parsed.keys()
                        for k in k_iter:
                            analysis[k] = parsed[k]

                if 'received_routes' in result['commands']:
                    rec = result['commands']['received_routes']
                    if rec.get('success'):
                        text = rec.get('output', '')
                        v4 = self._parse_ipv4_prefix_count(text)
                        v6 = self._parse_ipv6_prefix_count(text)
                        analysis['received_routes'] = v4 + v6

                if 'active_routes' in result['commands']:
                    rec = result['commands']['active_routes']
                    if rec.get('success'):
                        text = rec.get('output', '')
                        v4 = self._parse_ipv4_prefix_count(text)
                        v6 = self._parse_ipv6_prefix_count(text)
                        analysis['active_routes'] = v4 + v6

            elif 'arista' in vendor.lower():
                if 'neighbor_summary' in result['commands']:
                    rec = result['commands']['neighbor_summary']
                    if rec.get('success'):
                        parsed = self._parse_arista_neighbor_text(rec.get('output', ''))
                        k_iter = parsed.keys()
                        for k in k_iter:
                            analysis[k] = parsed[k]

                if 'received_routes' in result['commands']:
                    rec = result['commands']['received_routes']
                    if rec.get('success'):
                        text = rec.get('output', '')
                        v4 = self._parse_ipv4_prefix_count(text)
                        v6 = self._parse_ipv6_prefix_count(text)
                        analysis['received_routes'] = v4 + v6

                if 'active_routes' in result['commands']:
                    rec = result['commands']['active_routes']
                    if rec.get('success'):
                        text = rec.get('output', '')
                        v4 = self._parse_ipv4_prefix_count(text)
                        v6 = self._parse_ipv6_prefix_count(text)
                        analysis['active_routes'] = v4 + v6

            # -----------------------
            # Health flags
            # -----------------------
            state_val = analysis.get("state", "Unknown")
            recv_val = analysis.get("received_routes", 0)
            actv_val = analysis.get("active_routes", 0)

            is_established = False
            if isinstance(state_val, str):
                is_established = state_val.lower() == "established"

            analysis["is_zombie"] = (recv_val > 0 and actv_val == 0)
            analysis["is_healthy"] = (recv_val > 0 and actv_val > 0)
            analysis["is_down"] = (not is_established)

            result['analysis'] = analysis
            result['collection_status'] = 'success'

            logger.info("  ✓ Collection successful - State: {}, Received: {}, Active: {}".format(
                analysis.get('state', 'Unknown'),
                analysis.get('received_routes', 0),
                analysis.get('active_routes', 0)
            ))

        except Exception as e:
            logger.error("\n" + "=" * 60)
            logger.error("❌ SSH CONNECTION FAILED")
            logger.error("=" * 60)
            logger.error("Device: {}".format(device_name))
            logger.error("Error Type: {}".format(type(e).__name__))
            logger.error("Error Message: {}".format(str(e)))

            error_str = str(e).lower()
            if 'authentication' in error_str or 'permission denied' in error_str:
                logger.error("\n⚠️  AUTHENTICATION FAILURE")
                if self.ssh_key_path:
                    logger.error("   Key Path: {}".format(self.ssh_key_path))
                    logger.error("   Troubleshooting:")
                    logger.error("   1. Verify key is in authorized_keys on {}".format(device_name))
                    logger.error("   2. Check key permissions: chmod 600 {}".format(self.ssh_key_path))
                    logger.error("   3. Test manually: ssh -i {} {}@{}".format(self.ssh_key_path, self.username, device_name))
                else:
                    logger.error("   Using password authentication")
                    logger.error("   Verify password is correct for user: {}".format(self.username))
            elif 'timeout' in error_str or 'timed out' in error_str:
                logger.error("\n⚠️  CONNECTION TIMEOUT")
                logger.error("   1. Verify device is reachable: ping {}".format(device_name))
                logger.error("   2. Check firewall rules")
                logger.error("   3. Verify SSH is running on device")
            elif 'connection refused' in error_str:
                logger.error("\n⚠️  CONNECTION REFUSED")
                logger.error("   1. Verify SSH is running on {}".format(device_name))
                logger.error("   2. Check if SSH is on non-standard port")
            elif 'host key' in error_str:
                logger.error("\n⚠️  HOST KEY VERIFICATION FAILED")
                logger.error("   1. Add {} to known_hosts".format(device_name))
                logger.error("   2. Or connect manually once: ssh {}@{}".format(self.username, device_name))

            logger.error("=" * 60 + "\n")

            result['collection_status'] = 'failed'
            result['error'] = str(e)
            result['error_type'] = type(e).__name__

            if self.debug:
                import traceback
                logger.debug("Full traceback:")
                logger.debug(traceback.format_exc())

        return result

    def collect_device(self, device: Dict) -> Dict:
        device_name = device['device_name']
        logger.info("\n" + "=" * 60)
        logger.info("Device: {} ({}, {})".format(device_name, device['vendor'], device['site']))
        logger.info("PNI Peers: {}".format(device['pni_peer_count']))
        logger.info("=" * 60)

        device_result = {
            'device_name': device_name,
            'vendor': device['vendor'],
            'site': device['site'],
            'local_asn': device['local_asn'],
            'collection_time': self.collection_time,
            'peer_count': device['pni_peer_count'],
            'peers': []
        }

        idx = 0
        while idx < len(device['peers']):
            peer = device['peers'][idx]
            peer_result = self.collect_peer_data(device, peer)
            device_result['peers'].append(peer_result)
            time.sleep(0.5)
            idx = idx + 1

        return device_result

    def run_collection(self, device_filter: Optional[str] = None) -> Dict:
        logger.info("\n" + "=" * 80)
        logger.info("PNI ANALYTICS DATA COLLECTION")
        logger.info("=" * 80)
        logger.info("Job File: {}".format(self.job_file))
        logger.info("Total Devices in Job: {}".format(self.job_def['collection_scope']['total_devices']))
        logger.info("Total Peers in Job: {}".format(self.job_def['collection_scope']['total_peers']))
        logger.info("Max Devices Limit: {}".format(self.max_devices))
        logger.info("Output Directory: {}".format(self.output_dir))

        logger.info("\nAuthentication:")
        logger.info("  Username: {}".format(self.username))
        if self.ssh_key_path:
            logger.info("  SSH Key: {}".format(self.ssh_key_path))
        if self.password:
            logger.info("  Password: {}".format('*' * len(self.password)))

        logger.info("=" * 80 + "\n")

        devices = self.job_def['devices']

        if device_filter:
            filtered = []
            i = 0
            while i < len(devices):
                d = devices[i]
                name = d.get('device_name', '')
                if isinstance(name, str):
                    if device_filter.lower() in name.lower():
                        filtered.append(d)
                i = i + 1
            devices = filtered
            logger.info("Filter applied: {} devices match '{}'".format(len(devices), device_filter))

        original_device_count = len(devices)
        if len(devices) > self.max_devices:
            logger.warning("\n⚠️  Limiting collection to first {} device(s) (found {})".format(self.max_devices, original_device_count))
            logger.warning("   Devices to collect from:")
            i = 0
            while i < len(devices[:self.max_devices]):
                d = devices[i]
                logger.warning("   {}. {} ({} peers)".format(i + 1, d['device_name'], d['pni_peer_count']))
                i = i + 1
            logger.warning("   Skipping {} device(s)".format(original_device_count - self.max_devices))
            logger.warning("   To collect from more devices, use: --max-devices {}\n".format(original_device_count))
            devices = devices[:self.max_devices]
        else:
            logger.info("Collecting from {} device(s):".format(len(devices)))
            i = 0
            while i < len(devices):
                d = devices[i]
                logger.info("  {}. {} ({} peers)".format(i + 1, d['device_name'], d['pni_peer_count']))
                i = i + 1

        total_peers_targeted = 0
        j = 0
        while j < len(devices):
            total_peers_targeted = total_peers_targeted + devices[j]['pni_peer_count']
            j = j + 1

        collection_results = {
            'metadata': {
                'collection_started': self.collection_time,
                'job_file': str(self.job_file),
                'devices_in_job': self.job_def['collection_scope']['total_devices'],
                'devices_targeted': len(devices),
                'devices_limited_by_max': original_device_count > self.max_devices,
                'max_devices_setting': self.max_devices,
                'total_peers_targeted': total_peers_targeted,
                'device_filter': device_filter,
                'ssh_key_used': bool(self.ssh_key_path),
                'ssh_key_path': self.ssh_key_path if self.ssh_key_path else None
            },
            'devices': []
        }

        i = 0
        while i < len(devices):
            device = devices[i]
            logger.info("\n" + "#" * 80)
            logger.info("DEVICE {}/{}".format(i + 1, len(devices)))
            logger.info("#" * 80)

            device_result = self.collect_device(device)
            collection_results['devices'].append(device_result)

            device_output_file = self.output_dir / "{}_pni_data.json".format(device['device_name'])
            with open(device_output_file, 'w') as f:
                json.dump(device_result, f, indent=2)
            logger.info("Saved device data: {}\n".format(device_output_file))

            i = i + 1

        complete_output = self.output_dir / "pni_collection_{}.json".format(datetime.now().strftime('%Y%m%d_%H%M%S'))
        with open(complete_output, 'w') as f:
            json.dump(collection_results, f, indent=2)

        logger.info("\n" + "=" * 80)
        logger.info("COLLECTION COMPLETE")
        logger.info("=" * 80)
        logger.info("Complete results saved: {}".format(complete_output))

        self._generate_summary(collection_results)

        return collection_results

    def _generate_summary(self, results: Dict):
        total_peers = 0
        successful = 0
        failed = 0
        zombie_peers = []
        down_peers = []

        i = 0
        while i < len(results['devices']):
            device = results['devices'][i]
            j = 0
            while j < len(device['peers']):
                peer = device['peers'][j]
                total_peers = total_peers + 1

                if peer['collection_status'] == 'success':
                    successful = successful + 1

                    analysis = peer.get('analysis', {})
                    if analysis.get('is_zombie'):
                        zp = {}
                        zp['device'] = device['device_name']
                        zp['peer_ip'] = peer['peer_ip']
                        zp['peer_as'] = peer['peer_as']
                        zp['description'] = peer['description']
                        zp['received'] = analysis.get('received_routes', 0)
                        zp['active'] = analysis.get('active_routes', 0)
                        zombie_peers.append(zp)

                    if analysis.get('is_down'):
                        dp = {}
                        dp['device'] = device['device_name']
                        dp['peer_ip'] = peer['peer_ip']
                        dp['peer_as'] = peer['peer_as']
                        dp['description'] = peer['description']
                        dp['state'] = analysis.get('state', 'Unknown')
                        down_peers.append(dp)
                else:
                    failed = failed + 1

                j = j + 1
            i = i + 1

        logger.info("\nCollection Summary:")
        logger.info("  Total Peers: {}".format(total_peers))
        logger.info("  Successful: {}".format(successful))
        logger.info("  Failed: {}".format(failed))
        logger.info("  Zombie Peers: {}".format(len(zombie_peers)))
        logger.info("  Down Peers: {}".format(len(down_peers)))

        if len(zombie_peers) > 0:
            logger.warning("\n⚠️  ZOMBIE PEERS DETECTED ({}):".format(len(zombie_peers)))
            k = 0
            while k < len(zombie_peers):
                zp = zombie_peers[k]
                logger.warning("  {}: {} (AS{}) - {} - Received: {}, Active: 0".format(
                    zp['device'], zp['peer_ip'], zp['peer_as'], zp['description'], zp['received']
                ))
                k = k + 1

        if len(down_peers) > 0:
            logger.warning("\n⚠️  DOWN PEERS ({}):".format(len(down_peers)))
            k = 0
            while k < len(down_peers):
                dp = down_peers[k]
                logger.warning("  {}: {} (AS{}) - {} - State: {}".format(
                    dp['device'], dp['peer_ip'], dp['peer_as'], dp['description'], dp['state']
                ))
                k = k + 1


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

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    if not args.job_file.exists():
        logger.error("❌ Job file not found: {}".format(args.job_file))
        logger.error("   Generate it first with: python3 analyze_peer_groups.py")
        return 1

    if not args.ssh_key and not (args.username and args.password):
        logger.error("❌ Authentication required!")
        logger.error("   Must provide either:")
        logger.error("     --ssh-key <path> --username <user>  OR")
        logger.error("     --username <user> --password <pass>")
        logger.error("\nExample:")
        logger.error("  python3 pni_collector.py --ssh-key ~/.ssh/id_rsa --username speterman")
        return 1

    if args.ssh_key and not args.username:
        logger.error("❌ Username required when using SSH key!")
        logger.error("   Usage: --ssh-key <path> --username <user>")
        return 1

    if args.ssh_key:
        if not Path(args.ssh_key).exists():
            logger.error("❌ SSH key not found: {}".format(args.ssh_key))
            logger.error("   Check the path and try again")
            return 1

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
        logger.error("❌ Failed to initialize collector: {}".format(e))
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1

    try:
        collector.run_collection(device_filter=args.device_filter)
        return 0
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Collection interrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        logger.error("\n❌ Collection failed: {}".format(e))
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
