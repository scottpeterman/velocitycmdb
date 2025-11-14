#!/usr/bin/env python3
"""
Diagnose Cisco authentication issues
"""

import os
import sys
import yaml
import paramiko


def check_credentials():
    """Check if credentials are set"""
    print("=" * 60)
    print("CREDENTIAL CHECK")
    print("=" * 60)

    for i in range(1, 5):
        user = os.getenv(f'CRED_{i}_USER')
        password = os.getenv(f'CRED_{i}_PASS')

        if user or password:
            print(f"CRED_{i}:")
            print(f"  USER: {user if user else 'NOT SET'}")
            print(f"  PASS: {'SET (' + str(len(password)) + ' chars)' if password else 'NOT SET'}")
    print()


def load_cisco_devices():
    """Load Cisco devices from sessions.yaml"""
    try:
        with open('sessions.yaml', 'r') as f:
            sessions = yaml.safe_load(f)

        cisco_devices = []
        for folder_group in sessions:
            for device in folder_group.get('sessions', []):
                if 'cisco' in device.get('Vendor', '').lower():
                    cisco_devices.append(device)

        return cisco_devices
    except Exception as e:
        print(f"Error loading sessions.yaml: {e}")
        return []


def test_device(device):
    """Test connection to a single device"""
    name = device['display_name']
    host = device['host']
    port = device.get('port', 22)
    cred_id = device.get('credsid', '1')

    print("=" * 60)
    print(f"TESTING: {name}")
    print("=" * 60)
    print(f"Host: {host}:{port}")
    print(f"Cred ID: {cred_id}")

    # Get credentials
    username = os.getenv(f'CRED_{cred_id}_USER')
    password = os.getenv(f'CRED_{cred_id}_PASS')

    if not username:
        print(f"✗ ERROR: CRED_{cred_id}_USER not set")
        return False

    if not password:
        print(f"✗ ERROR: CRED_{cred_id}_PASS not set")
        return False

    print(f"Username: {username}")
    print(f"Password: {'*' * len(password)}")
    print()

    # Test Paramiko connection
    print("Attempting Paramiko connection...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=30,
            allow_agent=False,
            look_for_keys=False
        )

        print("✓ Connection successful!")

        # Try a simple command
        print("\nTesting command execution: 'show version | include Version'")
        stdin, stdout, stderr = ssh.exec_command("show version | include Version", timeout=30)

        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')

        if output:
            print("✓ Command output:")
            print(output[:200])

        if error:
            print("⚠ STDERR:")
            print(error[:200])

        ssh.close()
        print("\n✓ Test passed!")
        return True

    except paramiko.AuthenticationException as e:
        print(f"\n✗ AUTHENTICATION FAILED: {e}")
        print("\nPossible causes:")
        print(f"  1. Wrong username (currently using: {username})")
        print(f"  2. Wrong password")
        print(f"  3. Wrong credential ID mapping in sessions.yaml")
        print(f"\nTry manually: ssh {username}@{host}")
        return False

    except paramiko.SSHException as e:
        print(f"\n✗ SSH ERROR: {e}")
        print("\nPossible causes:")
        print("  1. SSH not enabled on device")
        print("  2. Firewall blocking connection")
        print("  3. Key exchange/cipher mismatch")
        return False

    except Exception as e:
        print(f"\n✗ CONNECTION FAILED: {e}")
        return False


def main():
    print("\n")
    print("*" * 60)
    print("CISCO AUTHENTICATION DIAGNOSTIC")
    print("*" * 60)
    print()

    # Check credentials
    check_credentials()

    # Load devices
    print("=" * 60)
    print("LOADING CISCO DEVICES")
    print("=" * 60)

    devices = load_cisco_devices()

    if not devices:
        print("✗ No Cisco devices found in sessions.yaml")
        return 1

    print(f"Found {len(devices)} Cisco devices")

    # Show unique credential IDs
    cred_ids = set(d.get('credsid', '1') for d in devices)
    print(f"Credential IDs used: {sorted(cred_ids)}")
    print()

    # Test first device
    if devices:
        print(f"Testing first device: {devices[0]['display_name']}")
        print()

        success = test_device(devices[0])

        if success:
            print("\n" + "=" * 60)
            print("✓ DIAGNOSTIC PASSED")
            print("=" * 60)
            print("\nYour credentials work! The problem is elsewhere.")
            print("Try running your jobs again.")
            return 0
        else:
            print("\n" + "=" * 60)
            print("✗ DIAGNOSTIC FAILED")
            print("=" * 60)
            print("\nFix the authentication issue above, then:")
            print("1. Set correct credentials:")
            print(f"   export CRED_{devices[0].get('credsid', '1')}_USER=correct_username")
            print(f"   export CRED_{devices[0].get('credsid', '1')}_PASS=correct_password")
            print("2. Run this diagnostic again")
            print("3. Then run your jobs")
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())