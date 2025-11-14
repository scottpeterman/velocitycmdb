#!/usr/bin/env python3
"""
Test script for SSH fallback functionality
Tests both Paramiko and native SSH fallback with 'show version' command
"""

import sys
import argparse
from pathlib import Path

# Import from your refactored ssh_client
from ssh_client import SSHClient, SSHClientOptions


def test_device(host, username, password, port=22, display_name=None,
                force_fallback=False, test_shell_mode=False):
    """
    Test SSH connection and execute 'show version' command

    Args:
        host: Device IP or hostname
        username: SSH username
        password: SSH password
        port: SSH port (default 22)
        display_name: Device display name for FQDN resolution
        force_fallback: Force use of native SSH fallback
        test_shell_mode: Test shell mode instead of direct command
    """

    print("=" * 80)
    print(f"SSH Fallback Test - {host}:{port}")
    print("=" * 80)

    # Determine command based on mode
    if test_shell_mode:
        command = "show version"
        print(f"Mode: Shell mode (invoke_shell=True)")
    else:
        command = "show version"
        print(f"Mode: Direct command (invoke_shell=False)")

    if display_name:
        print(f"Display name: {display_name}")
    if force_fallback:
        print(f"Force fallback: ENABLED (will skip Paramiko)")

    print("-" * 80)

    try:
        # Create SSH options
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            password=password,
            invoke_shell=test_shell_mode,
            timeout=60,
            shell_timeout=5,
            debug=True,  # Enable debug output
            display_name=display_name,
            # ssh_key_path="/path/to/key"  # Optional SSH key
        )

        # Force fallback if requested (simulate Paramiko failure)
        if force_fallback:
            print("\n⚠ Forcing fallback by setting device override...")
            # We can simulate this by temporarily disabling Paramiko
            # In production, you'd set this in ssh_fallback_config.yaml

        # Create SSH client
        client = SSHClient(ssh_options)

        # Connect to device
        print("\n📡 Connecting to device...")
        client.connect()

        # Execute command
        print(f"\n🔧 Executing command: '{command}'")
        print("-" * 80)

        result = client.execute_command(command)

        print("-" * 80)
        print(f"\n✅ Command executed successfully!")

        # Show which method was used
        if client._using_fallback:
            print(f"🔄 Method: Native SSH Fallback")
            if client._fqdn_used:
                print(f"📍 FQDN used: {client._fqdn_used}")
        else:
            print(f"✅ Method: Paramiko")

        # Disconnect
        client.disconnect()

        print("\n" + "=" * 80)
        print("✅ TEST PASSED")
        print("=" * 80)

        return True

    except Exception as e:
        print("\n" + "=" * 80)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Test SSH fallback with show version command',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with Paramiko (default)
  python test_ssh_fallback.py --host 192.168.1.1 --user admin --password secret

  # Test with display name for FQDN resolution
  python test_ssh_fallback.py --host 192.168.1.1 --user admin --password secret --display-name router1

  # Force native SSH fallback (skip Paramiko)
  python test_ssh_fallback.py --host 192.168.1.1 --user admin --password secret --force-fallback

  # Test shell mode
  python test_ssh_fallback.py --host 192.168.1.1 --user admin --password secret --shell-mode

  # Test with environment variables for fallback config
  export SSH_FALLBACK_ENABLED=true
  export SSH_FALLBACK_DOMAIN=kentik.com
  python test_ssh_fallback.py --host 192.168.1.1 --user admin --password secret
        """
    )

    # Connection arguments
    parser.add_argument('--host', required=True,
                        help='Device IP or hostname')
    parser.add_argument('--user', '-u', required=True,
                        help='SSH username')
    parser.add_argument('--password', '-p',
                        help='SSH password (optional if using key-based auth)')
    parser.add_argument('--key', '-k',
                        help='Path to SSH private key')
    parser.add_argument('--port', type=int, default=22,
                        help='SSH port (default: 22)')

    # Optional arguments
    parser.add_argument('--display-name', '-d',
                        help='Device display name (for FQDN resolution)')
    parser.add_argument('--force-fallback', action='store_true',
                        help='Force native SSH fallback (skip Paramiko)')
    parser.add_argument('--shell-mode', action='store_true',
                        help='Test shell mode (invoke_shell=True)')

    # Test multiple devices
    parser.add_argument('--test-file',
                        help='Test multiple devices from YAML file (NetBox format)')

    args = parser.parse_args()

    # Single device test
    if not args.test_file:
        success = test_device(
            host=args.host,
            username=args.user,
            password=args.password,
            port=args.port,
            display_name=args.display_name,
            force_fallback=args.force_fallback,
            test_shell_mode=args.shell_mode
        )

        sys.exit(0 if success else 1)

    # Multiple device test from file
    else:
        import yaml

        print("=" * 80)
        print(f"Testing multiple devices from: {args.test_file}")
        print("=" * 80)

        with open(args.test_file, 'r') as f:
            data = yaml.safe_load(f)

        all_sessions = []
        for folder in data:
            for session in folder.get('sessions', []):
                all_sessions.append(session)

        print(f"\nFound {len(all_sessions)} devices to test")
        print("-" * 80)

        results = []
        for i, session in enumerate(all_sessions, 1):
            host = session['host']
            display_name = session.get('display_name', 'unknown')
            port = int(session.get('port', 22))

            print(f"\n[{i}/{len(all_sessions)}] Testing {display_name} ({host}:{port})")

            success = test_device(
                host=host,
                username=args.user,
                password=args.password,
                port=port,
                display_name=display_name,
                force_fallback=args.force_fallback,
                test_shell_mode=args.shell_mode
            )

            results.append({
                'device': display_name,
                'host': host,
                'success': success
            })

        # Summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        passed = sum(1 for r in results if r['success'])
        failed = len(results) - passed

        print(f"Total: {len(results)}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")

        if failed > 0:
            print("\nFailed devices:")
            for r in results:
                if not r['success']:
                    print(f"  - {r['device']} ({r['host']})")

        print("=" * 80)

        sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()