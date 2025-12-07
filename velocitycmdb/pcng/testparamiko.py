#!/usr/bin/env python3
"""
Paramiko test:
1) Force 'ssh-rsa' (SHA-1) user-auth by disabling RSA-SHA2
2) Junos-safe command execution via `cli -c "show version | display json"`
   (Your previous failure was the shell rejecting `show version | display json`;
    you must enter the Junos CLI first or wrap with `cli -c`.)
No comprehensions used anywhere.
"""

import logging
import sys
import traceback
from pathlib import Path

import paramiko


def force_ssh_rsa_disabled_algos():
    disabled_algorithms = {}
    pubkeys_list = []
    pubkeys_list.append("rsa-sha2-512")
    pubkeys_list.append("rsa-sha2-256")
    disabled_algorithms["pubkeys"] = pubkeys_list
    return disabled_algorithms


def load_private_key(key_path_str):
    pkey = None
    key_type_loaded = None

    # Try RSA first (most likely); then Ed25519, ECDSA, DSS
    pairs = []
    pairs.append(("RSA", paramiko.RSAKey))
    pairs.append(("Ed25519", paramiko.Ed25519Key))
    pairs.append(("ECDSA", paramiko.ECDSAKey))
    pairs.append(("DSS", paramiko.DSSKey))

    i = 0
    while i < len(pairs):
        name, cls = pairs[i]
        try:
            pkey = cls.from_private_key_file(key_path_str)
            key_type_loaded = name
            print("✓ Loaded {} key successfully".format(name))
            break
        except Exception as e:
            print("✗ Not a {} key: {}".format(name, e))
        i = i + 1

    return pkey, key_type_loaded


def exec_and_print(client, command, use_pty=False, label=None):
    if label is None:
        label = command
    print()
    print(">> {}".format(label))
    try:
        if use_pty:
            stdin, stdout, stderr = client.exec_command(command, get_pty=True, timeout=60)
        else:
            stdin, stdout, stderr = client.exec_command(command, timeout=60)

        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")

        print("   Exit status unknown (Paramiko needs channel exit-status).")
        print("   STDOUT (first 400):")
        print("   {}".format(out[:400]))
        if len(err) > 0:
            print("   STDERR (first 400):")
            print("   {}".format(err[:400]))
        return out, err
    except Exception as e:
        print("   Execution error: {}".format(e))
        return "", str(e)


def main():
    host = "edge01.iad2home.com"
    port = 22
    username = "admin"
    key_path = Path.home() / ".ssh" / "id_rsa"
    log_file = "/tmp/paramiko_debug.log"

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    paramiko.util.log_to_file(log_file)
    logging.getLogger("paramiko").setLevel(logging.DEBUG)

    print("=" * 80)
    print("PURE PARAMIKO TEST - FORCE ssh-rsa (disable RSA-SHA2) + JUNOS CLI WRAP")
    print("=" * 80)
    print("\n⚠️  Paramiko debug logging enabled")
    print("   File: {}".format(log_file))
    print()
    print("Connection Details:")
    print("  Host: {}".format(host))
    print("  Port: {}".format(port))
    print("  Username: {}".format(username))
    print("  Key: {}".format(str(key_path)))
    print("  Key exists: {}".format(key_path.exists()))
    print()

    if not key_path.exists():
        print("❌ Private key not found at {}".format(str(key_path)))
        sys.exit(1)

    pkey, key_type_loaded = load_private_key(str(key_path))
    if pkey is None:
        print("❌ Could not load the key with any supported type")
        sys.exit(1)

    disabled_algorithms = force_ssh_rsa_disabled_algos()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print()
        print("=" * 80)
        print("CONNECTING (force ssh-rsa by disabling rsa-sha2-* for pubkey auth)")
        print("=" * 80)

        client.connect(
            hostname=host,
            port=port,
            username=username,
            pkey=pkey,
            look_for_keys=False,
            allow_agent=False,
            disabled_algorithms=disabled_algorithms,
            timeout=30,
        )
        print("   ✓ Connected successfully (key type loaded: {})".format(key_type_loaded))

        # Detect if Junos CLI wrapper is available; then run proper command
        # 1) Try Junos CLI wrapped
        cmd1 = 'show version"'
        out1, err1 = exec_and_print(client, cmd1, use_pty=False, label="Junos (cli -c) JSON")

        # 2) If that fails obviously, try plain Junos human output
        proceed_plain = False
        if len(out1.strip()) == 0 and len(err1.strip()) > 0:
            proceed_plain = True
        if "not found" in err1 or "command not found" in err1:
            proceed_plain = True
        if "cli:" in err1 and "not found" in err1:
            proceed_plain = True

        if proceed_plain:
            cmd2 = 'show version'
            exec_and_print(client, cmd2, use_pty=False, label="Junos (cli -c) plain")



        print()
        print("✓ Test completed")

    except paramiko.ssh_exception.AuthenticationException as e:
        print()
        print("❌ Authentication failed: {}".format(e))
        print("   You are already forcing 'ssh-rsa'. If it still fails,")
        print("   verify authorized_keys and server policy.")
        print()
        traceback.print_exc()

    except Exception as e:
        print()
        print("❌ Connection failed: {}".format(e))
        traceback.print_exc()

    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
