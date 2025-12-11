#!/usr/bin/env python3
"""
Diagnostic: Test Paramiko connection with SSH key
"""

import sys

sys.path.insert(0, '.')

from ssh_client import SSHClient, SSHClientOptions
from pathlib import Path

print("=" * 80)
print("PARAMIKO CONNECTION DIAGNOSTIC")
print("=" * 80)

# Create SSH options exactly like pni_collector does
ssh_options = SSHClientOptions(
    host='edge01.iad2home.com',
    username='speterman',
    password='',
    ssh_key_path='/Users/speterman/.ssh/id_rsa',
    timeout=60,
    debug=True,  # Enable debug
    display_name='edge01.iad2home.com'
)
ssh_client = SSHClient(options=ssh_options)
ssh_client.connect()
print(f"\nSSH Options:")
print(f"  host: {ssh_options.host}")
print(f"  username: {ssh_options.username}")
print(f"  password: '{ssh_options.password}'")
print(f"  ssh_key_path: {ssh_options.ssh_key_path}")
print(f"  Key exists: {Path(ssh_options.ssh_key_path).exists()}")

print("\nCreating SSH client...")
client = SSHClient(ssh_options)

print("\nAttempting connection...")
try:
    client.connect()
    print("✓ Connection successful!")

    # Check if it used fallback
    if hasattr(client, '_using_fallback'):
        if client._using_fallback:
            print("⚠️  WARNING: Used fallback (not Paramiko)")
        else:
            print("✓ Used Paramiko (not fallback)")

    # Try a simple command
    print("\nTrying test command...")
    result = client.execute_command('show version | display json')
    print(f"Command result length: {len(result)} bytes")
    print(f"First 200 chars: {result[:200]}")

    client.disconnect()
    print("\n✓ Test completed successfully")

except Exception as e:
    print(f"\n❌ Connection failed: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback

    traceback.print_exc()