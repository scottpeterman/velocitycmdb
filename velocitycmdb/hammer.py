#!/usr/bin/env python3
"""
SSH Connectivity Diagnostic Tool
Tests multiple connection methods and reports what works for each device
"""

import sys
import subprocess
import concurrent.futures
from pathlib import Path
from datetime import datetime
import csv


class ConnectivityTest:
    def __init__(self, hostname, ip, ssh_key):
        self.hostname = hostname
        self.ip = ip
        self.ssh_key = ssh_key
        self.results = {
            'hostname': hostname,
            'ip': ip,
            'direct_ip': 'UNTESTED',
            'fqdn_kentik': 'UNTESTED',
            'fqdn_simple': 'UNTESTED',
            'working_method': None,
            'error_details': ''
        }

    def test_ssh_method(self, target, method_name, timeout=10):
        """Test SSH connection using native SSH"""
        ssh_opts = [
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', f'ConnectTimeout={timeout}',
            '-o', 'PasswordAuthentication=no',
            '-o', 'PreferredAuthentications=publickey',
            '-o', 'BatchMode=yes',
            '-i', self.ssh_key,
            '-o', 'LogLevel=ERROR'
        ]

        cmd = ['ssh'] + ssh_opts + [f'speterman@{target}', 'echo "OK"']

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 5,
                text=True
            )

            if result.returncode == 0 and 'OK' in result.stdout:
                return 'SUCCESS', None
            else:
                error = result.stderr.strip()[:100] if result.stderr else 'Unknown error'
                return 'FAILED', error

        except subprocess.TimeoutExpired:
            return 'TIMEOUT', f'Timeout after {timeout}s'
        except Exception as e:
            return 'ERROR', str(e)[:100]

    def run_all_tests(self):
        """Test all connection methods"""
        print(f"\nTesting {self.hostname} ({self.ip})...")

        # Test 1: Direct IP
        print(f"  [1/3] Testing direct IP: {self.ip}")
        status, error = self.test_ssh_method(self.ip, 'direct_ip')
        self.results['direct_ip'] = status
        if status == 'SUCCESS':
            self.results['working_method'] = f'direct_ip:{self.ip}'
            print(f"        ✓ SUCCESS")
            return self.results
        else:
            print(f"        ✗ {status}: {error}")
            if not self.results['error_details']:
                self.results['error_details'] = f"IP:{error}"

        # Test 2: FQDN with home.com
        fqdn_kentik = f"{self.hostname}home.com"
        print(f"  [2/3] Testing FQDN: {fqdn_kentik}")
        status, error = self.test_ssh_method(fqdn_kentik, 'fqdn_kentik')
        self.results['fqdn_kentik'] = status
        if status == 'SUCCESS':
            self.results['working_method'] = f'fqdn:{fqdn_kentik}'
            print(f"        ✓ SUCCESS")
            return self.results
        else:
            print(f"        ✗ {status}: {error}")
            if 'IP:' not in self.results['error_details']:
                self.results['error_details'] += f" | FQDN1:{error}"

        # Test 3: Simple hostname (let SSH config handle it)
        print(f"  [3/3] Testing hostname: {self.hostname}")
        status, error = self.test_ssh_method(self.hostname, 'fqdn_simple')
        self.results['fqdn_simple'] = status
        if status == 'SUCCESS':
            self.results['working_method'] = f'hostname:{self.hostname}'
            print(f"        ✓ SUCCESS")
        else:
            print(f"        ✗ {status}: {error}")
            if 'FQDN1:' not in self.results['error_details']:
                self.results['error_details'] += f" | HOST:{error}"

        if not self.results['working_method']:
            print(f"        ✗✗✗ ALL METHODS FAILED")

        return self.results


def parse_device_line(line):
    """Parse the device list format you provided"""
    parts = line.strip().split('\t')
    if len(parts) < 12:
        return None

    return {
        'hostname': parts[1].strip(),
        'ip': parts[11].strip() if len(parts) > 11 else None
    }


def load_devices_from_file(filepath):
    """Load devices from your tab-separated format"""
    devices = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                device = parse_device_line(line)
                if device and device['ip']:
                    devices.append(device)
    return devices


def main():
    if len(sys.argv) < 2:
        print("Usage: python ssh_diagnostic.py <device_file> [ssh_key_path] [max_workers]")
        print("\nDevice file format (tab-separated):")
        print("  col1: id")
        print("  col2: hostname")
        print("  col12: ip_address")
        sys.exit(1)

    device_file = sys.argv[1]
    ssh_key = sys.argv[2] if len(sys.argv) > 2 else str(Path.home() / '.ssh/speterman/id_rsa')
    max_workers = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    print("=" * 60)
    print("SSH CONNECTIVITY DIAGNOSTIC TOOL")
    print("=" * 60)
    print(f"Device file: {device_file}")
    print(f"SSH key: {ssh_key}")
    print(f"Max parallel tests: {max_workers}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Validate SSH key
    if not Path(ssh_key).exists():
        print(f"ERROR: SSH key not found: {ssh_key}")
        sys.exit(1)

    # Load devices
    print(f"\nLoading devices from {device_file}...")
    devices = load_devices_from_file(device_file)
    print(f"Loaded {len(devices)} devices")

    if not devices:
        print("ERROR: No devices found in file")
        sys.exit(1)

    # Run tests
    all_results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for device in devices:
            test = ConnectivityTest(device['hostname'], device['ip'], ssh_key)
            future = executor.submit(test.run_all_tests)
            futures.append(future)

        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                print(f"Test failed with exception: {e}")

    # Generate report
    print("\n" + "=" * 60)
    print("DIAGNOSTIC REPORT")
    print("=" * 60)

    success_count = sum(1 for r in all_results if r['working_method'])
    failed_count = len(all_results) - success_count

    print(f"\nTotal devices tested: {len(all_results)}")
    print(f"Successfully connected: {success_count}")
    print(f"Failed to connect: {failed_count}")
    print(f"Success rate: {success_count / len(all_results) * 100:.1f}%")

    # Success breakdown
    if success_count > 0:
        print("\n--- SUCCESSFUL CONNECTIONS ---")
        method_counts = {}
        for r in all_results:
            if r['working_method']:
                method = r['working_method'].split(':')[0]
                method_counts[method] = method_counts.get(method, 0) + 1
                print(f"  ✓ {r['hostname']:<30} {r['working_method']}")

        print("\nConnection method breakdown:")
        for method, count in sorted(method_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {method}: {count} devices ({count / success_count * 100:.1f}%)")

    # Failures
    if failed_count > 0:
        print("\n--- FAILED CONNECTIONS ---")
        for r in all_results:
            if not r['working_method']:
                print(f"  ✗ {r['hostname']:<30} {r['ip']}")
                print(f"    Direct IP: {r['direct_ip']}")
                print(f"    FQDN (home.com): {r['fqdn_kentik']}")
                print(f"    Hostname: {r['fqdn_simple']}")
                if r['error_details']:
                    print(f"    Errors: {r['error_details'][:150]}")

    # Save CSV report
    report_file = f"ssh_diagnostic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(report_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'hostname', 'ip', 'direct_ip', 'fqdn_kentik', 'fqdn_simple',
            'working_method', 'error_details'
        ])
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\nDetailed report saved to: {report_file}")

    # Generate fallback config
    if failed_count > 0:
        print("\n--- SUGGESTED FALLBACK CONFIG ---")
        print("Add this to ssh_fallback_config.yaml:")
        print("\nfallback:")
        print("  enabled: true")
        print("  domain_suffix: \"kentik.com\"")
        print("  auto_fqdn: true")
        print("  device_overrides:")

        # Group by IP pattern
        failed_ips = [r['ip'] for r in all_results if not r['working_method']]
        ip_patterns = set()
        for ip in failed_ips:
            # Create /24 pattern
            octets = ip.split('.')
            if len(octets) == 4:
                pattern = f"{octets[0]}.{octets[1]}.{octets[2]}.*"
                ip_patterns.add(pattern)

        for pattern in sorted(ip_patterns):
            print(f"    - pattern: \"{pattern}\"")
            print(f"      force_fallback: true")

    print("\n" + "=" * 60)
    print("Diagnostic complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()