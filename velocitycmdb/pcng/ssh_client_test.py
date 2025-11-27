#!/usr/bin/env python3
"""
Test script for SSH client authentication methods
Tests: password, key-based, environment variables, and fallback combinations
"""

import sys
import os
import argparse
from pathlib import Path

# Import from your refactored ssh_client
from ssh_client import SSHClient, SSHClientOptions


def test_password_auth(host, username, password, port=22, prompt="#", debug=False):
    """Test 1: Password-only authentication"""
    print("\n" + "=" * 80)
    print("TEST 1: Password Authentication")
    print("=" * 80)

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            password=password,
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print("📡 Connecting with password...")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Password authentication: PASSED")
        return True

    except Exception as e:
        print(f"❌ Password authentication: FAILED - {e}")
        return False


def test_key_auth(host, username, key_file, port=22, prompt="#", debug=False):
    """Test 2: Key-based authentication (no passphrase)"""
    print("\n" + "=" * 80)
    print("TEST 2: Key-Based Authentication (No Passphrase)")
    print("=" * 80)

    if not key_file or not Path(key_file).exists():
        print(f"⚠️  Skipping - key file not found: {key_file}")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            key_file=key_file,
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print(f"📡 Connecting with key: {key_file}")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Key authentication: PASSED")
        return True

    except Exception as e:
        print(f"❌ Key authentication: FAILED - {e}")
        return False


def test_key_with_passphrase(host, username, key_file, key_password, port=22, prompt="#", debug=False):
    """Test 3: Key-based authentication with passphrase"""
    print("\n" + "=" * 80)
    print("TEST 3: Key-Based Authentication (With Passphrase)")
    print("=" * 80)

    if not key_file or not Path(key_file).exists():
        print(f"⚠️  Skipping - key file not found: {key_file}")
        return None

    if not key_password:
        print("⚠️  Skipping - key password not provided")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            key_file=key_file,
            key_password=key_password,
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print(f"📡 Connecting with protected key: {key_file}")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Key with passphrase: PASSED")
        return True

    except Exception as e:
        print(f"❌ Key with passphrase: FAILED - {e}")
        return False


def test_key_with_password_fallback(host, username, key_file, password, port=22, prompt="#", debug=False):
    """Test 4: Key authentication with password fallback"""
    print("\n" + "=" * 80)
    print("TEST 4: Key + Password Fallback")
    print("=" * 80)

    if not key_file or not Path(key_file).exists():
        print(f"⚠️  Skipping - key file not found: {key_file}")
        return None

    if not password:
        print("⚠️  Skipping - password not provided")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            key_file=key_file,
            password=password,  # Fallback if key fails
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print(f"📡 Connecting with key (password fallback available)")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Key + password fallback: PASSED")
        return True

    except Exception as e:
        print(f"❌ Key + password fallback: FAILED - {e}")
        return False


def test_env_password(host, username, port=22, prompt="#", debug=False):
    """Test 5: Environment variable password (PYSSH_PASS)"""
    print("\n" + "=" * 80)
    print("TEST 5: Environment Variable - Password (PYSSH_PASS)")
    print("=" * 80)

    if 'PYSSH_PASS' not in os.environ:
        print("⚠️  Skipping - PYSSH_PASS not set")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            # password will be read from PYSSH_PASS
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print("📡 Connecting with PYSSH_PASS environment variable")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Environment password: PASSED")
        return True

    except Exception as e:
        print(f"❌ Environment password: FAILED - {e}")
        return False


def test_env_key(host, username, port=22, prompt="#", debug=False):
    """Test 6: Environment variable key (PYSSH_KEY)"""
    print("\n" + "=" * 80)
    print("TEST 6: Environment Variable - Key (PYSSH_KEY)")
    print("=" * 80)

    if 'PYSSH_KEY' not in os.environ:
        print("⚠️  Skipping - PYSSH_KEY not set")
        return None

    key_path = os.environ['PYSSH_KEY']
    if not Path(key_path).exists():
        print(f"⚠️  Skipping - key file not found: {key_path}")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            # key_file will be read from PYSSH_KEY
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print(f"📡 Connecting with PYSSH_KEY environment variable: {key_path}")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Environment key: PASSED")
        return True

    except Exception as e:
        print(f"❌ Environment key: FAILED - {e}")
        return False


def test_env_key_with_passphrase(host, username, port=22, prompt="#", debug=False):
    """Test 7: Environment variables for key + passphrase (PYSSH_KEY + PYSSH_KEY_PASS)"""
    print("\n" + "=" * 80)
    print("TEST 7: Environment Variables - Key + Passphrase (PYSSH_KEY + PYSSH_KEY_PASS)")
    print("=" * 80)

    if 'PYSSH_KEY' not in os.environ:
        print("⚠️  Skipping - PYSSH_KEY not set")
        return None

    if 'PYSSH_KEY_PASS' not in os.environ:
        print("⚠️  Skipping - PYSSH_KEY_PASS not set")
        return None

    key_path = os.environ['PYSSH_KEY']
    if not Path(key_path).exists():
        print(f"⚠️  Skipping - key file not found: {key_path}")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            # key_file and key_password will be read from env vars
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            debug=debug
        )

        client = SSHClient(ssh_options)
        print(f"📡 Connecting with PYSSH_KEY + PYSSH_KEY_PASS: {key_path}")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Environment key + passphrase: PASSED")
        return True

    except Exception as e:
        print(f"❌ Environment key + passphrase: FAILED - {e}")
        return False


def test_multiple_key_types(host, username, password, port=22, prompt="#", debug=False):
    """Test 8: Multiple key types (RSA, ECDSA, Ed25519)"""
    print("\n" + "=" * 80)
    print("TEST 8: Multiple Key Types (RSA, ECDSA, Ed25519)")
    print("=" * 80)

    key_paths = [
        ("RSA", "~/.ssh/id_rsa"),
        ("ECDSA", "~/.ssh/id_ecdsa"),
        ("Ed25519", "~/.ssh/id_ed25519"),
    ]

    results = []

    for key_type, key_path in key_paths:
        expanded_path = Path(key_path).expanduser()

        if not expanded_path.exists():
            print(f"⚠️  {key_type}: key not found at {key_path}")
            results.append((key_type, None))
            continue

        try:
            ssh_options = SSHClientOptions(
                host=host,
                port=port,
                username=username,
                key_file=str(expanded_path),
                password=password,  # Fallback
                prompt=prompt,
                prompt_count=2,
                timeout=30,
                debug=False  # Suppress per-key debug
            )

            client = SSHClient(ssh_options)
            print(f"📡 Testing {key_type} key: {key_path}")
            client.connect()

            result = client.execute_command("show version")
            client.disconnect()

            print(f"✅ {key_type}: PASSED")
            results.append((key_type, True))

        except Exception as e:
            print(f"❌ {key_type}: FAILED - {e}")
            results.append((key_type, False))

    # Summary
    passed = sum(1 for _, result in results if result is True)
    failed = sum(1 for _, result in results if result is False)
    skipped = sum(1 for _, result in results if result is None)

    print(f"\nMultiple key types: {passed} passed, {failed} failed, {skipped} skipped")

    return passed > 0  # Pass if at least one key type worked


def test_legacy_mode_with_key(host, username, key_file, port=22, prompt="#", debug=False):
    """Test 9: Legacy mode with key authentication"""
    print("\n" + "=" * 80)
    print("TEST 9: Legacy Mode + Key Authentication")
    print("=" * 80)

    if not key_file or not Path(key_file).exists():
        print(f"⚠️  Skipping - key file not found: {key_file}")
        return None

    try:
        ssh_options = SSHClientOptions(
            host=host,
            port=port,
            username=username,
            key_file=key_file,
            prompt=prompt,
            prompt_count=2,
            timeout=30,
            legacy_mode=True,  # Enable legacy support
            debug=debug
        )

        client = SSHClient(ssh_options)
        print(f"📡 Connecting in legacy mode with key: {key_file}")
        client.connect()

        print("🔧 Executing: 'show version'")
        result = client.execute_command("show version")

        client.disconnect()

        print("✅ Legacy mode + key: PASSED")
        return True

    except Exception as e:
        print(f"❌ Legacy mode + key: FAILED - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Test SSH client authentication methods',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Coverage:
  1. Password authentication
  2. Key-based authentication (no passphrase)
  3. Key-based authentication (with passphrase)
  4. Key + password fallback
  5. Environment variable - password (PYSSH_PASS)
  6. Environment variable - key (PYSSH_KEY)
  7. Environment variables - key + passphrase
  8. Multiple key types (RSA, ECDSA, Ed25519)
  9. Legacy mode with key authentication

Examples:
  # Test all methods with password
  python test_auth.py --host 192.168.1.1 --user admin --password cisco123

  # Test all methods with key
  python test_auth.py --host 192.168.1.1 --user admin --key ~/.ssh/id_rsa

  # Test with key + passphrase
  python test_auth.py --host 192.168.1.1 --user admin --key ~/.ssh/id_rsa --key-pass mypass

  # Test with both key and password (fallback)
  python test_auth.py --host 192.168.1.1 --user admin --password cisco123 --key ~/.ssh/id_rsa

  # Test with environment variables
  export PYSSH_PASS=cisco123
  export PYSSH_KEY=~/.ssh/id_rsa
  export PYSSH_KEY_PASS=keypass
  python test_auth.py --host 192.168.1.1 --user admin

  # Run specific tests only
  python test_auth.py --host 192.168.1.1 --user admin --password cisco123 --tests 1,2,5

  # Enable debug output
  python test_auth.py --host 192.168.1.1 --user admin --password cisco123 --debug
        """
    )

    # Required arguments
    parser.add_argument('--host', required=True,
                        help='Device IP or hostname')
    parser.add_argument('--user', '-u', required=True,
                        help='SSH username')

    # Authentication options
    parser.add_argument('--password', '-p',
                        help='SSH password')
    parser.add_argument('--key', '-k',
                        help='Path to SSH private key')
    parser.add_argument('--key-pass',
                        help='SSH key passphrase')

    # Connection options
    parser.add_argument('--port', type=int, default=22,
                        help='SSH port (default: 22)')
    parser.add_argument('--prompt', default='#',
                        help='Expected prompt (default: #)')

    # Test options
    parser.add_argument('--tests',
                        help='Comma-separated test numbers to run (e.g., 1,2,5). Default: all')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output')

    args = parser.parse_args()

    # Determine which tests to run
    if args.tests:
        test_numbers = [int(x.strip()) for x in args.tests.split(',')]
    else:
        test_numbers = list(range(1, 10))  # All tests

    print("=" * 80)
    print("SSH CLIENT AUTHENTICATION TEST SUITE")
    print("=" * 80)
    print(f"Host: {args.host}:{args.port}")
    print(f"Username: {args.user}")
    print(f"Password: {'***' if args.password else 'Not provided'}")
    print(f"Key: {args.key if args.key else 'Not provided'}")
    print(f"Key passphrase: {'***' if args.key_pass else 'Not provided'}")
    print(f"Tests to run: {test_numbers}")
    print("=" * 80)

    # Run tests
    results = {}

    if 1 in test_numbers:
        results[1] = test_password_auth(
            args.host, args.user, args.password,
            args.port, args.prompt, args.debug
        )

    if 2 in test_numbers:
        results[2] = test_key_auth(
            args.host, args.user, args.key,
            args.port, args.prompt, args.debug
        )

    if 3 in test_numbers:
        results[3] = test_key_with_passphrase(
            args.host, args.user, args.key, args.key_pass,
            args.port, args.prompt, args.debug
        )

    if 4 in test_numbers:
        results[4] = test_key_with_password_fallback(
            args.host, args.user, args.key, args.password,
            args.port, args.prompt, args.debug
        )

    if 5 in test_numbers:
        results[5] = test_env_password(
            args.host, args.user,
            args.port, args.prompt, args.debug
        )

    if 6 in test_numbers:
        results[6] = test_env_key(
            args.host, args.user,
            args.port, args.prompt, args.debug
        )

    if 7 in test_numbers:
        results[7] = test_env_key_with_passphrase(
            args.host, args.user,
            args.port, args.prompt, args.debug
        )

    if 8 in test_numbers:
        results[8] = test_multiple_key_types(
            args.host, args.user, args.password,
            args.port, args.prompt, args.debug
        )

    if 9 in test_numbers:
        results[9] = test_legacy_mode_with_key(
            args.host, args.user, args.key,
            args.port, args.prompt, args.debug
        )

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    test_names = {
        1: "Password authentication",
        2: "Key authentication (no passphrase)",
        3: "Key authentication (with passphrase)",
        4: "Key + password fallback",
        5: "Environment variable - password",
        6: "Environment variable - key",
        7: "Environment variables - key + passphrase",
        8: "Multiple key types",
        9: "Legacy mode + key",
    }

    passed = 0
    failed = 0
    skipped = 0

    for test_num in test_numbers:
        result = results.get(test_num)
        test_name = test_names.get(test_num, f"Test {test_num}")

        if result is True:
            print(f"✅ Test {test_num}: {test_name}")
            passed += 1
        elif result is False:
            print(f"❌ Test {test_num}: {test_name}")
            failed += 1
        else:
            print(f"⚠️  Test {test_num}: {test_name} (skipped)")
            skipped += 1

    print("-" * 80)
    print(f"Total: {len(test_numbers)} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}")
    print("=" * 80)

    # Exit code
    if failed > 0:
        sys.exit(1)
    elif passed == 0:
        print("\n⚠️  No tests were able to run. Check your credentials and environment.")
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()