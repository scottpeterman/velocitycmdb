#!/usr/bin/env python3
"""
Diagnostic script to check DeviceFingerprint and SSHClient parameter handling
"""

import sys
import os
import inspect
from pathlib import Path

# Add pcng to path
sys.path.insert(0, str(Path(__file__).parent / 'pcng'))


def check_class_signature(class_name, module_name):
    """Check the __init__ signature of a class"""
    try:
        module = __import__(module_name, fromlist=[class_name])
        cls = getattr(module, class_name)
        sig = inspect.signature(cls.__init__)

        print(f"\n{class_name}.__init__ signature:")
        print(f"  {sig}")
        print(f"\nParameters:")
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            default = param.default
            if default == inspect.Parameter.empty:
                print(f"  - {param_name}: REQUIRED")
            else:
                print(f"  - {param_name}: optional (default={default})")

        return True
    except Exception as e:
        print(f"\nError checking {class_name}: {e}")
        return False


def test_env_vars():
    """Test environment variable reading"""
    print("\n" + "=" * 60)
    print("ENVIRONMENT VARIABLES")
    print("=" * 60)

    vars_to_check = ['PYSSH_KEY', 'PYSSH_PASS', 'SSH_FALLBACK_ENABLED']
    for var in vars_to_check:
        value = os.environ.get(var)
        if value:
            # Mask password
            if 'PASS' in var:
                display = "***SET***"
            else:
                display = value
            print(f"  {var}: {display}")
        else:
            print(f"  {var}: NOT SET")


def main():
    print("=" * 60)
    print("DeviceFingerprint & SSHClient Diagnostic")
    print("=" * 60)

    # Check DeviceFingerprint
    print("\n" + "=" * 60)
    print("CHECKING DEVICE_FINGERPRINT")
    print("=" * 60)
    check_class_signature('DeviceFingerprint', 'device_fingerprint')

    # Check SSHClient
    print("\n" + "=" * 60)
    print("CHECKING SSH_CLIENT")
    print("=" * 60)
    check_class_signature('SSHClient', 'ssh_client')

    # Check SSHClientOptions
    print("\n" + "=" * 60)
    print("CHECKING SSH_CLIENT_OPTIONS")
    print("=" * 60)
    check_class_signature('SSHClientOptions', 'ssh_client')

    # Check environment
    test_env_vars()

    # Test instantiation
    print("\n" + "=" * 60)
    print("TEST INSTANTIATION")
    print("=" * 60)

    try:
        from velocitycmdb.services.fingerprint import DeviceFingerprint

        # Set test env vars
        os.environ['PYSSH_KEY'] = '/tmp/test_key'

        print("\nAttempting to create DeviceFingerprint with:")
        print("  host='192.168.1.1'")
        print("  port=22")
        print("  username='admin'")
        print("  password='password'")
        print("  PYSSH_KEY='/tmp/test_key'")

        # Try creating without connecting
        fp = DeviceFingerprint(
            host='192.168.1.1',
            port=22,
            username='admin',
            password='password',
            debug=False,
            verbose=False,
            connection_timeout=5000
        )

        print("\n✓ DeviceFingerprint instantiated successfully!")
        print(f"  Type: {type(fp)}")

        # Check if it has ssh_client attribute
        if hasattr(fp, 'ssh_client'):
            print(f"  Has ssh_client: Yes")
            if fp.ssh_client:
                print(f"  ssh_client type: {type(fp.ssh_client)}")
        else:
            print(f"  Has ssh_client: No")

    except Exception as e:
        print(f"\n✗ Failed to create DeviceFingerprint:")
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()