#!/usr/bin/env python3
"""
Test script for ssh_client.py against Avocent console server
Executes two commands: "shell" and "ts_menu -l"
"""

import sys
import os

# Add the upload directory to the path so we can import ssh_client
sys.path.insert(0, '/mnt/user-data/uploads')

from ssh_client import SSHClient, SSHClientOptions


def test_avocent_connection(host, username, password, port=22):
    """
    Test connection to Avocent console server

    Args:
        host: IP address or hostname of Avocent
        username: SSH username
        password: SSH password
        port: SSH port (default 22)
    """
    print(f"Testing connection to Avocent at {host}:{port}")
    print(f"Username: {username}")
    print("=" * 60)

    # Create SSH client options
    # For Avocent, we need:
    # - invoke_shell=True (for interactive shell)
    # - expect_prompt to detect when commands finish
    # - prompt_count=2 (one for shell command, one for ts_menu output)
    options = SSHClientOptions(
        host=host,
        username=username,
        password=password,
        port=port,
        invoke_shell=True,  # Use interactive shell mode
        expect_prompt="$",  # Shell prompt (adjust if different)
        prompt_count=2,  # Expect 2 prompts (after shell, after ts_menu)
        timeout=30,  # Overall timeout
        shell_timeout=5,  # Time to wait after commands
        inter_command_time=1,  # Wait 1 second between commands
        debug=True,  # Enable debug output
        legacy_mode=False  # Disable legacy mode for modern systems
    )

    # Create client and connect
    client = SSHClient(options)

    try:
        print("\n[1] Connecting to Avocent...")
        client.connect()
        print("✓ Connected successfully\n")

        # Execute the two commands
        print("[2] Executing commands: 'shell' and 'ts_menu -l'")
        print("-" * 60)

        commands = ["shell", "ts_menu -l"]
        output = client.execute_commands(commands)

        print("\n" + "=" * 60)
        print("COMMAND OUTPUT:")
        print("=" * 60)
        print(output)
        print("=" * 60)

        return output

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None

    finally:
        print("\n[3] Disconnecting...")
        client.disconnect()
        print("✓ Disconnected\n")


def main():
    """Main entry point"""

    # Check command line arguments
    if len(sys.argv) < 3:
        print("Usage: python test_avocent.py <host> <username> [password] [port]")
        print("\nExample:")
        print("  python test_avocent.py 192.168.1.100 admin mypassword")
        print("  python test_avocent.py 192.168.1.100 admin mypassword 22")
        print("\nIf password is omitted, you'll be prompted for it.")
        sys.exit(1)

    host = sys.argv[1]
    username = sys.argv[2]

    # Get password
    if len(sys.argv) >= 4:
        password = sys.argv[3]
    else:
        import getpass
        password = getpass.getpass(f"Password for {username}@{host}: ")

    # Get port
    port = int(sys.argv[4]) if len(sys.argv) >= 5 else 22

    # Run the test
    output = test_avocent_connection(host, username, password, port)

    if output:
        print("\n✓ Test completed successfully!")
        sys.exit(0)
    else:
        print("\n✗ Test failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()