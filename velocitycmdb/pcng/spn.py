#!/usr/bin/env python3
"""
Simplified SSHPassPython (SPN) - Password Authentication Only
Environment variable support for credentials
Direct Paramiko invoke_shell mode execution
"""

import os
import sys
import argparse
import traceback
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from ssh_client import SSHClient, SSHClientOptions


class OutputManager:
    """Manages output to screen, file, or both"""

    def __init__(self, output_to_screen=True, output_file=None, append_mode=False):
        self.output_to_screen = output_to_screen
        self.output_file = None
        self.append_mode = append_mode

        if output_file:
            try:
                os.makedirs(os.path.dirname(output_file), exist_ok=True) if os.path.dirname(output_file) else None
                mode = 'a' if append_mode else 'w'
                self.output_file = open(output_file, mode, encoding='utf-8')
            except Exception as e:
                print(f"Warning: Could not open output file {output_file}: {str(e)}")
                self.output_file = None

    def write(self, text):
        """Write text to configured outputs"""
        if self.output_to_screen:
            print(text, end='')
            sys.stdout.flush()

        if self.output_file:
            try:
                # Clean carriage returns for file output
                cleaned_text = text.replace('\r\n', '\n').replace('\r', '\n')
                self.output_file.write(cleaned_text)
                self.output_file.flush()
            except Exception as e:
                print(f"Warning: Error writing to file: {str(e)}")

    def close(self):
        """Close file handle"""
        if self.output_file:
            try:
                self.output_file.close()
            except Exception as e:
                print(f"Warning: Error closing output file: {str(e)}")


class SimpleSPN:
    """
    Simplified SSHPassPython - Password Authentication Only

    INVOKE_SHELL MODE ONLY - Always uses interactive shell sessions
    Environment variable support for credentials
    No SSH keys, no direct exec mode
    """

    VERSION = "2.0.0-simplified"

    def __init__(self):
        self.args = self.parse_arguments()
        self.credentials = self.resolve_credentials()
        self.host, self.port = self.parse_host_port(self.credentials['host'])
        self.output_manager = self.setup_output_management()
        self.log_file = self.setup_logging()

    def parse_arguments(self):
        """Parse command line arguments"""
        parser = argparse.ArgumentParser(
            description=f"Simplified SSHPassPython {self.VERSION}\n\n"
                        "Password-only authentication with environment variable support:\n"
                        "  SSH_HOST, SSH_USER, SSH_PASSWORD, SSH_PORT\n"
                        "  CRED_1_USER, CRED_1_PASS (alternative credential format)\n"
                        "CLI arguments take precedence over environment variables.",
            formatter_class=argparse.RawTextHelpFormatter,
            add_help=False
        )

        parser.add_argument("--help", action="help", help="Show this help message and exit")

        # Connection arguments (support env vars)
        parser.add_argument("--host", "-h",
                            default=os.getenv('SSH_HOST', ''),
                            help="SSH Host (ip:port) [Env: SSH_HOST]")
        parser.add_argument("-u", "--user",
                            default=os.getenv('SSH_USER', ''),
                            help="SSH Username [Env: SSH_USER or CRED_1_USER]")
        parser.add_argument("-p", "--password",
                            default=os.getenv('SSH_PASSWORD', ''),
                            help="SSH Password [Env: SSH_PASSWORD or CRED_1_PASS]")
        parser.add_argument("--port", type=int,
                            default=int(os.getenv('SSH_PORT', '22')),
                            help="SSH Port (default: 22) [Env: SSH_PORT]")

        # Command options
        parser.add_argument("-c", "--cmds", default="",
                            help="Commands to run, separated by comma")
        parser.add_argument("--cmd-file",
                            help="File containing commands (one per line)")

        # Shell options (invoke_shell mode always used)
        parser.add_argument("--prompt", default="",
                            help="Expected prompt pattern (auto-detected if not provided)")
        parser.add_argument("--prompt-count", type=int, default=None,
                            help="Number of prompts to expect (default: auto-calculated)")
        parser.add_argument("-t", "--timeout", type=int, default=360,
                            help="Command timeout in seconds (default: 360)")
        parser.add_argument("--shell-timeout", type=int, default=10,
                            help="Shell timeout in seconds (default: 10)")
        parser.add_argument("--expect-prompt-timeout", type=int, default=30000,
                            help="Expect prompt timeout in milliseconds (default: 30000)")
        parser.add_argument("-i", "--inter-command-time", type=int, default=1,
                            help="Inter-command delay in seconds (default: 1)")

        # Output options
        parser.add_argument("--no-screen", action="store_true",
                            help="Disable screen output")
        parser.add_argument("-o", "--output-file", default="",
                            help="Save output to file")
        parser.add_argument("--append", action="store_true",
                            help="Append to output file instead of overwriting")

        # Logging and debugging
        parser.add_argument("--log-file", default="",
                            help="Log file path (default: ./logs/hostname.log)")
        parser.add_argument("-d", "--debug", action="store_true",
                            help="Enable debug output")
        parser.add_argument("-v", "--verbose", action="store_true",
                            help="Enable verbose output")

        # Version
        parser.add_argument("--version", action="version",
                            version=f"Simplified SSHPassPython {self.VERSION}")
        parser.add_argument("-k", "--key",
                            default=os.getenv('PYSSH_KEY', ''),
                            help="SSH private key file [Env: PYSSH_KEY]")

        return parser.parse_args()

    def resolve_credentials(self):
        """Resolve credentials from CLI args and environment variables"""
        # Check CLI args first, then SSH_* vars, then CRED_* vars
        host = self.args.host or os.getenv('SSH_HOST', '')

        # Username: CLI > SSH_USER > CRED_1_USER
        user = self.args.user or os.getenv('SSH_USER', '') or os.getenv('CRED_1_USER', '')

        # Password: CLI > SSH_PASSWORD > CRED_1_PASS
        password = self.args.password or os.getenv('SSH_PASSWORD', '') or os.getenv('CRED_1_PASS', '')

        # SSH Key: CLI > PYSSH_KEY
        key_file = getattr(self.args, 'key', '') or os.getenv('PYSSH_KEY', '')

        # Validate required credentials
        missing = []
        if not host:
            missing.append("host (--host or SSH_HOST)")
        if not user:
            missing.append("username (--user or SSH_USER or CRED_1_USER)")
        if not password and not key_file:
            missing.append("password or ssh key (--password or --key or PYSSH_KEY)")

        if missing:
            print(f"Error: Missing required credentials: {', '.join(missing)}")
            sys.exit(1)

        # Set environment variables for downstream components
        os.environ['SSH_HOST'] = host
        os.environ['SSH_USER'] = user
        if password:
            os.environ['SSH_PASSWORD'] = password
            os.environ['PYSSH_PASS'] = password
        if key_file:
            os.environ['PYSSH_KEY'] = key_file

        return {
            'host': host,
            'user': user,
            'password': password,
            'key_file': key_file
        }

    def parse_host_port(self, host_str):
        """Parse host and port from host string"""
        if ':' in host_str:
            host, port_str = host_str.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                print(f"Error: Invalid port number: {port_str}")
                sys.exit(1)
        else:
            host = host_str
            port = self.args.port

        return host, port

    def setup_output_management(self):
        """Setup output management"""
        output_to_screen = not self.args.no_screen
        return OutputManager(
            output_to_screen=output_to_screen,
            output_file=self.args.output_file if self.args.output_file else None,
            append_mode=self.args.append
        )

    def setup_logging(self):
        """Setup logging"""
        if self.args.log_file:
            return self.args.log_file

        # Default log location
        log_dir = "./logs"
        hostname_safe = self.host.replace(':', '_').replace('/', '_')
        return f"{log_dir}/{hostname_safe}.log"

    def prepare_commands(self):
        """Prepare command list from arguments or file"""
        commands = []

        # Get commands from --cmds argument
        if self.args.cmds:
            for cmd in self.args.cmds.split(','):
                cmd = cmd.strip()
                if cmd or self.args.cmds.endswith(','):
                    commands.append(cmd if cmd else "\\n")

        # Get commands from file
        if self.args.cmd_file:
            if not os.path.exists(self.args.cmd_file):
                print(f"Error: Command file not found: {self.args.cmd_file}")
                sys.exit(1)

            try:
                with open(self.args.cmd_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            commands.append(line)
            except Exception as e:
                print(f"Error reading command file: {str(e)}")
                sys.exit(1)

        return commands

    def calculate_prompt_count(self, commands):
        """Calculate expected prompt count based on commands"""
        if self.args.prompt_count is not None:
            return self.args.prompt_count

        # Count non-empty commands plus one for initial prompt
        count = 1  # Initial prompt
        for cmd in commands:
            if cmd and cmd != "\\n":
                count += 1

        return count

    def create_ssh_options(self, commands):
        """Create SSH client options"""
        prompt_count = self.calculate_prompt_count(commands)

        ssh_options = SSHClientOptions(
            host=self.host,
            port=self.port,
            username=self.credentials['user'],
            password=self.credentials['password'],
            prompt=self.args.prompt,
            prompt_count=prompt_count,
            timeout=self.args.timeout,
            shell_timeout=self.args.shell_timeout,
            inter_command_time=self.args.inter_command_time,
            log_file=self.log_file,
            debug=self.args.debug,
            expect_prompt_timeout=self.args.expect_prompt_timeout,
            key_file=self.credentials.get('key_file'),
        )

        # Set output callback
        ssh_options.output_callback = self.output_manager.write

        return ssh_options

    def execute_commands(self, commands: List[str]):
        """Execute commands using invoke_shell mode (always)"""
        if not commands:
            print("No commands to execute.")
            return

        if self.args.verbose:
            print(f"Executing {len(commands)} commands on {self.host}:{self.port}")

        ssh_options = self.create_ssh_options(commands)
        ssh_client = SSHClient(ssh_options)

        try:
            # Connect (automatically creates shell session)
            ssh_client.connect()

            # Auto-detect prompt if not specified
            if not self.args.prompt and not ssh_options.expect_prompt:
                if self.args.verbose:
                    print("Attempting automatic prompt detection...")

                detected_prompt = ssh_client.find_prompt()
                if detected_prompt:
                    ssh_client.set_expect_prompt(detected_prompt)
                    if self.args.verbose:
                        print(f"Auto-detected prompt: '{detected_prompt}'")
                else:
                    if self.args.verbose:
                        print("Warning: Could not auto-detect prompt, using timeout-based execution")

            # Convert commands to comma-separated string for shell execution
            command_parts = []
            for cmd in commands:
                if cmd == "\\n":
                    command_parts.append("")  # Empty creates trailing comma = newline
                else:
                    command_parts.append(cmd)

            combined_commands = ",".join(command_parts)

            if self.args.verbose:
                print(f"Executing commands in single shell session...")
                if self.args.debug:
                    for i, cmd in enumerate(commands, 1):
                        display_cmd = "send newline" if cmd == "\\n" else cmd
                        print(f"  [{i}] {display_cmd}")

            # Execute all commands in single shell session
            result = ssh_client.execute_command(combined_commands)

            # Disconnect
            ssh_client.disconnect()

        except Exception as e:
            print(f"Error during command execution: {str(e)}")
            if self.args.debug:
                traceback.print_exc()
            sys.exit(1)

    def run(self):
        """Main execution logic"""
        print(f"Simplified SSHPassPython {self.VERSION}")
        print(f"Connecting to {self.host}:{self.port} as {self.credentials['user']}...")

        # Prepare and execute commands
        commands = self.prepare_commands()

        if commands:
            self.execute_commands(commands)
        else:
            print("No commands provided. Use -c or --cmd-file.")

        # Close output manager
        self.output_manager.close()

        if self.args.verbose:
            print("Execution completed.")


def main():
    """Entry point"""
    try:
        spn = SimpleSPN()
        spn.run()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()