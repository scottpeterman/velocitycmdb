#!/usr/bin/env python3
"""
Test a single device to see the actual error
This will show you exactly what's failing
"""
import subprocess
import os
import sys

# Test one device
TEST_HOST = "172.16.11.41"  # eng-leaf-1
TEST_USER = os.getenv('CRED_1_USER', 'admin')
TEST_PASS = os.getenv('CRED_1_PASS', '')

print("=" * 70)
print("SINGLE DEVICE CONNECTION TEST")
print("=" * 70)
print(f"Device: eng-leaf-1")
print(f"Host: {TEST_HOST}")
print(f"Username: {TEST_USER}")
print(f"Password set: {'Yes (' + '*' * len(TEST_PASS) + ')' if TEST_PASS else 'NO - EMPTY!'}")
print("=" * 70)

if not TEST_PASS:
    print("\n❌ ERROR: Password is empty!")
    print("\nYou need to set credentials:")
    print("PowerShell:")
    print(f"  $env:CRED_1_USER='{TEST_USER}'")
    print(f"  $env:CRED_1_PASS='your_actual_password'")
    print("\nBash:")
    print(f"  export CRED_1_USER='{TEST_USER}'")
    print(f"  export CRED_1_PASS='your_actual_password'")
    sys.exit(1)

# Test 1: Try native SSH with password (what should work)
print("\nTest 1: Native SSH with sshpass (password-based)")
print("-" * 70)

# Check if sshpass is available
sshpass_available = subprocess.run(['where', 'sshpass'],
                                   capture_output=True,
                                   shell=True).returncode == 0

if not sshpass_available:
    print("⚠ sshpass not found - this is likely the problem!")
    print("\nYour devices need PASSWORD authentication but native SSH")
    print("can't provide passwords without sshpass.")
    print("\nOptions:")
    print("  1. Install sshpass (not available on Windows by default)")
    print("  2. Use --use-keys flag with SSH keys")
    print("  3. Ensure Paramiko works (troubleshoot Paramiko issues)")
else:
    cmd = [
        'sshpass', '-p', TEST_PASS,
        'ssh', '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        f'{TEST_USER}@{TEST_HOST}',
        'show version'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        print("✓ SSH with password WORKS!")
    else:
        print("❌ SSH with password FAILED")
        print(f"STDERR: {result.stderr}")

# Test 2: Try native SSH with keys (what's probably happening now)
print("\nTest 2: Native SSH with keys (what fallback is trying)")
print("-" * 70)

cmd = [
    'ssh',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'PasswordAuthentication=no',  # Force key-only
    '-o', 'PreferredAuthentications=publickey',
    f'{TEST_USER}@{TEST_HOST}',
    'show version'
]

result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

print(f"Return code: {result.returncode}")
if result.returncode == 0:
    print("✓ SSH with keys WORKS!")
    print("\nYou should use --use-keys flag:")
    print("  python batch_spn.py sessions.yaml --vendor cisco --use-keys ...")
else:
    print("❌ SSH with keys FAILED")
    print("\nSTDERR:")
    print(result.stderr)
    print("\nThis is what's happening in your batch job!")

# Test 3: Try Paramiko directly
print("\nTest 3: Paramiko (what should be tried first)")
print("-" * 70)

try:
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting with Paramiko...")
    client.connect(
        hostname=TEST_HOST,
        port=22,
        username=TEST_USER,
        password=TEST_PASS,
        timeout=10,
        allow_agent=False,
        look_for_keys=False
    )

    stdin, stdout, stderr = client.exec_command('show version')
    output = stdout.read().decode()

    print("✓ Paramiko WORKS!")
    print(f"Output preview: {output[:100]}...")
    client.close()

except paramiko.AuthenticationException as e:
    print(f"❌ Paramiko authentication failed: {e}")
    print("\nPossible causes:")
    print("  - Wrong username/password")
    print("  - Device requires SSH keys")
    print("  - Account locked/disabled")

except paramiko.SSHException as e:
    print(f"❌ Paramiko SSH error: {e}")
    print("\nPossible causes:")
    print("  - Incompatible SSH algorithms")
    print("  - Key exchange failed")
    print("  - Try --legacy-mode flag")

except Exception as e:
    print(f"❌ Paramiko connection failed: {e}")

# Summary and recommendations
print("\n" + "=" * 70)
print("DIAGNOSIS SUMMARY")
print("=" * 70)

print("\nBased on your error 'Native SSH failed: Warning: Permanently added...':")
print("\n1. Paramiko probably failed (authentication or compatibility)")
print("2. System fell back to native SSH")
print("3. Native SSH tried using SSH keys from ~/.ssh/")
print("4. Those keys don't exist or aren't authorized")
print("\nRECOMMENDATIONS:")
print("\nOption A: Fix Paramiko (RECOMMENDED)")
print("  - Check if Paramiko auth works (see Test 3 above)")
print("  - If 'incompatible algorithms', try adding --legacy-mode to spn.py")
print("  - Ensure password is correct")
print("\nOption B: Use SSH Keys")
print("  - Generate key: ssh-keygen -t rsa")
print("  - Copy to devices: ssh-copy-id admin@172.16.11.41")
print("  - Use: python batch_spn.py --use-keys ...")
print("\nOption C: Install sshpass (Linux/Mac only)")
print("  - Allows password auth through native SSH")
print("  - Not available on Windows")

print("\n" + "=" * 70)