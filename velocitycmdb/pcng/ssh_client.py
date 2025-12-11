#!/usr/bin/env python3
"""
Enhanced SSH Client - Password Authentication Only, Invoke Shell Only
Keeps all sophisticated prompt handling, ANSI filtering, and legacy device support
Removes: SSH keys, routing/proxy, direct exec mode
"""
import sys
import time
import re
import logging
import os
import paramiko
from io import StringIO
from datetime import datetime


def filter_ansi_sequences(text):
    """
    Aggressively filter ANSI escape sequences and control characters

    Args:
        text (str): Input text with potential ANSI sequences

    Returns:
        str: Cleaned text
    """
    if not text:
        return text

    # Single comprehensive regex to remove all ANSI sequences and control chars
    # This catches \u001b[1;24r, \u001b[24;1H, \u001b[2K, \u001b[?25h, etc.
    ansi_pattern = r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][AB012]|\x07|[\x00-\x08\x0B\x0C\x0E-\x1F]'
    return re.sub(ansi_pattern, '', text)


class SSHClientOptions:
    """SSH Client Options - Password Authentication Only, Invoke Shell Only"""

    def __init__(self, host, username, password=None, port=22,
                 key_file=None, key_password=None,
                 expect_prompt=None, prompt=None, prompt_count=3, timeout=30,
                 shell_timeout=5, inter_command_time=1, log_file=None, debug=False,
                 expect_prompt_timeout=60, legacy_mode=False, invoke_shell=True):

        # Connection parameters
        self.host = host
        self.port = port
        self.username = username

        # Authentication - support password, key file, or environment variables
        self.password = password or os.environ.get('PYSSH_PASS')
        self.key_file = key_file or os.environ.get('PYSSH_KEY')
        self.key_password = key_password or os.environ.get('PYSSH_KEY_PASS')
        self._pkey = None  # Will hold loaded paramiko key object

        # Validate: must have at least one authentication method
        if not self.password and not self.key_file:
            raise ValueError(
                "Authentication required: provide password, key_file, or set "
                "PYSSH_PASS/PYSSH_KEY environment variables"
            )

        # ALWAYS INVOKE_SHELL MODE
        self.invoke_shell = True

        # Prompt handling
        self.expect_prompt = expect_prompt
        self.prompt = prompt
        self.prompt_count = prompt_count

        # Timeouts and timing
        self.timeout = timeout
        self.shell_timeout = shell_timeout
        self.inter_command_time = inter_command_time
        self.expect_prompt_timeout = expect_prompt_timeout

        # Logging
        self.log_file = log_file
        self.debug = debug

        # Legacy support options
        self.legacy_mode = legacy_mode
        self.legacy_algorithms = True  # Enable by default for compatibility
        self.legacy_auth_methods = True
        self.legacy_prompt_detection = False
        self.disable_host_key_checking = True

        # Legacy-specific timing adjustments
        if legacy_mode:
            self.shell_timeout = max(self.shell_timeout, 3)
            self.inter_command_time = max(self.inter_command_time, 0.5)
            self.expect_prompt_timeout = max(self.expect_prompt_timeout, 10000)
            self.legacy_prompt_detection = True

        # Default callbacks
        self.output_callback = print
        self.error_callback = lambda msg: print("ERROR: {}".format(msg), file=sys.stderr)


class LegacySSHClientEnhancements:
    """Enhancements for legacy device support"""

    @staticmethod
    def configure_legacy_algorithms(ssh_client):
        """Configure SSH client for legacy algorithm support"""
        paramiko.Transport._preferred_kex = (
            # Legacy KEX algorithms first
            "diffie-hellman-group1-sha1",
            "diffie-hellman-group14-sha1",
            "diffie-hellman-group-exchange-sha1",
            "diffie-hellman-group-exchange-sha256",
            # Modern algorithms
            "ecdh-sha2-nistp256",
            "ecdh-sha2-nistp384",
            "ecdh-sha2-nistp521",
            "curve25519-sha256",
            "curve25519-sha256@libssh.org",
            "diffie-hellman-group16-sha512",
            "diffie-hellman-group18-sha512"
        )

        paramiko.Transport._preferred_ciphers = (
            # Legacy ciphers first
            "aes128-cbc",
            "aes256-cbc",
            "3des-cbc",
            "aes192-cbc",
            # Modern ciphers
            "aes128-ctr",
            "aes192-ctr",
            "aes256-ctr",
            "aes256-gcm@openssh.com",
            "aes128-gcm@openssh.com",
            "chacha20-poly1305@openssh.com",
            "aes256-gcm",
            "aes128-gcm"
        )

        paramiko.Transport._preferred_keys = (
            # Legacy key types first
            "ssh-rsa",
            "ssh-dss",
            # Modern key types
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
            "ssh-ed25519",
            "rsa-sha2-256",
            "rsa-sha2-512"
        )

    @staticmethod
    def create_legacy_connection_params(options):
        """Create connection parameters optimized for legacy devices"""
        connect_params = {
            'hostname': options.host,
            'port': options.port,
            'username': options.username,
            'password': options.password,
            'timeout': options.timeout,
            'allow_agent': False,
            'look_for_keys': False,
            'compress': False,
            'auth_timeout': 10,
        }

        if options.legacy_mode:
            connect_params.update({
                'gss_auth': False,
                'gss_kex': False,
                'disabled_algorithms': {
                    'pubkeys': ['rsa-sha2-256', 'rsa-sha2-512'] if options.legacy_mode else [],
                }
            })


        return connect_params

    @staticmethod
    def legacy_prompt_detection(ssh_client, buffer_content, legacy_patterns=None):
        """Legacy-compatible prompt detection"""
        if legacy_patterns is None:
            legacy_patterns = [
                r'([^\r\n]*[#>$%])\s*$',
                r'([^\r\n]*[#>$%])\s*[\r\n]*$',
                r'([A-Za-z0-9\-_.]+[#>$%])\s*$',
                r'([A-Za-z0-9\-_.@]+[#>$%])\s*$',
            ]

        lines = buffer_content.split('\n')
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue

            for pattern in legacy_patterns:
                match = re.search(pattern, line)
                if match:
                    prompt = match.group(1).strip()
                    if any(line.endswith(char) for char in ['#', '>', '$', '%', ':', ']', ')']):
                        return prompt
        return None

    @staticmethod
    def apply_legacy_ssh_workarounds(ssh_client):
        """Apply workarounds for common legacy device issues"""
        try:
            transport = ssh_client.get_transport()
            if transport:
                transport.use_compression(False)
                transport.set_keepalive(30)
        except Exception:
            pass


class SSHClient:
    """
    Enhanced SSH Client - Password Only, Invoke Shell Only

    Features:
    - Password authentication via environment variables or parameters
    - Always uses invoke_shell (interactive terminal)
    - Sophisticated prompt detection and counting
    - ANSI sequence filtering
    - Legacy device support
    - Trailing comma handling (empty commands = extra newlines)
    """

    def __init__(self, options):
        """
        Initialize SSHClient with an SSHClientOptions object

        Args:
            options: SSHClientOptions instance containing all configuration
        """
        self._options = options
        self._ssh_client = None
        self._shell = None
        self._output_buffer = StringIO()
        self._prompt_detected = False
        self._pkey = None  # Will hold loaded paramiko key object

        # Validate required options
        if not options.host:
            raise ValueError("Host is required")
        if not options.username:
            raise ValueError("Username is required")

        # Authentication validation happens in SSHClientOptions
        # But double-check here as safety measure
        if not options.password and not options.key_file:
            raise ValueError(
                "Authentication required: provide password, key_file, or set "
                "PYSSH_PASS/PYSSH_KEY environment variables"
            )

    def _auto_detect_ssh_key(self):
        """
        Auto-detect SSH private key in standard locations.

        Priority order:
        1. id_rsa (most common)
        2. id_ed25519 (modern, secure)
        3. id_ecdsa
        4. id_dsa (legacy)

        Returns:
            str: Path to first found key file, or None if no keys found
        """
        from pathlib import Path

        ssh_dir = Path.home() / '.ssh'

        # Check if .ssh directory exists
        if not ssh_dir.exists():
            return None

        # Preferred order: id_rsa first (most common), then modern keys
        key_names = ['id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa']

        for key_name in key_names:
            key_path = ssh_dir / key_name
            if key_path.exists():
                return str(key_path)

        return None

    def _load_private_key(self):
        """
        Load and parse private key file.
        Supports RSA, ECDSA, Ed25519 (and DSA if available) with optional password protection.
        """
        if not self._options.key_file:
            return None

        key_file = os.path.expanduser(self._options.key_file)
        key_password = self._options.key_password

        self._log_with_timestamp(f"Loading private key from: {key_file}")

        if not os.path.exists(key_file):
            raise ValueError(f"Key file not found: {key_file}")

        # Try each key type in order
        # Note: DSA is deprecated in Paramiko 3.0+ and removed for security reasons
        key_types = [
            ('Ed25519', paramiko.Ed25519Key),
            ('RSA', paramiko.RSAKey),
            ('ECDSA', paramiko.ECDSAKey),
        ]

        # Add DSA support only if available (older Paramiko versions)
        if hasattr(paramiko, 'DSSKey'):
            key_types.append(('DSA', paramiko.DSSKey))

        last_exception = None

        for key_name, key_class in key_types:
            try:
                if self._options.debug:
                    self._log_with_timestamp(f"Attempting to load as {key_name} key")

                if key_password:
                    pkey = key_class.from_private_key_file(key_file, password=key_password)
                else:
                    pkey = key_class.from_private_key_file(key_file)

                self._log_with_timestamp(f"Successfully loaded {key_name} key", True)
                return pkey

            except paramiko.ssh_exception.PasswordRequiredException:
                self._log_with_timestamp(f"Key requires password but none provided")
                raise ValueError(f"Private key {key_file} requires a password")

            except paramiko.ssh_exception.SSHException as e:
                # Key might be different type, continue trying
                last_exception = e
                if self._options.debug:
                    self._log_with_timestamp(f"Not a {key_name} key: {str(e)}")
                continue

            except Exception as e:
                last_exception = e
                if self._options.debug:
                    self._log_with_timestamp(f"Error loading {key_name} key: {str(e)}")
                continue

        # If we got here, none of the key types worked
        raise ValueError(f"Could not load private key from {key_file}. "
                         f"Make sure it's a valid RSA, ECDSA, or Ed25519 key. "
                         f"Last error: {str(last_exception)}")

    def _recv_filtered(self, size=4096):
        """Receive data from shell with ANSI filtering applied immediately"""
        if not self._shell or not self._shell.recv_ready():
            return ""

        try:
            raw_data = self._shell.recv(size).decode('utf-8', errors='replace')
            filtered_data = filter_ansi_sequences(raw_data)

            if self._options.debug and len(raw_data) != len(filtered_data):
                chars_filtered = len(raw_data) - len(filtered_data)
                self._log_with_timestamp(f"Filtered {chars_filtered} ANSI characters")

            return filtered_data
        except Exception as e:
            self._log_with_timestamp(f"Error reading from shell: {str(e)}")
            return ""

    def _log_with_timestamp(self, message, always_print=False):
        """Helper method to log with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        timestamped_message = "[{}] {}".format(timestamp, message)

        if self._options.debug or always_print:
            print(timestamped_message)

        self._log_message(timestamped_message)

    def find_prompt(self, attempt_count=5, timeout=5):
        """Auto-detect command prompt with ANSI filtering"""
        if not self._shell:
            raise RuntimeError("Shell not initialized")

        self._log_with_timestamp("Attempting to auto-detect command prompt with ANSI filtering...", True)

        # Clear buffer
        self._output_buffer = StringIO()
        buffer = ""

        # Clear pending data
        while self._shell.recv_ready():
            self._recv_filtered()

        # Send newline to trigger prompt
        self._log_with_timestamp("Sending single newline to trigger prompt")
        self._shell.send("\n")
        time.sleep(3)

        # Collect filtered output
        buffer = ""
        start_time = time.time()

        while time.time() - start_time < 3:
            if self._shell.recv_ready():
                filtered_data = self._recv_filtered()
                if filtered_data:
                    buffer += filtered_data
                    self._output_buffer.write(filtered_data)
            else:
                time.sleep(0.1)

        # Extract prompt from filtered buffer
        prompt = self._extract_clean_prompt(buffer)
        if prompt:
            self._log_with_timestamp(f"Detected prompt: '{prompt}'", True)
            return prompt

        # Try additional attempts
        for i in range(attempt_count):
            self._log_with_timestamp(f"Prompt detection attempt {i + 1}/{attempt_count}")

            buffer = ""
            self._shell.send("\n")

            start_time = time.time()
            while time.time() - start_time < timeout:
                if self._shell.recv_ready():
                    filtered_data = self._recv_filtered()
                    if filtered_data:
                        buffer += filtered_data
                        self._output_buffer.write(filtered_data)
                        self._options.output_callback(filtered_data)
                else:
                    if buffer:
                        prompt = self._extract_clean_prompt(buffer)
                        if prompt:
                            self._log_with_timestamp(f"Detected prompt: '{prompt}'", True)
                            return prompt
                    time.sleep(0.1)

            if buffer:
                prompt = self._extract_clean_prompt(buffer)
                if prompt:
                    self._log_with_timestamp(f"Extracted prompt: '{prompt}'", True)
                    return prompt

        # Last resort
        self._log_with_timestamp("Could not detect prompt, using default '#'")
        return '#'

    def _extract_clean_prompt(self, buffer):
        """
        Extract a clean prompt from buffer, handling cases where the prompt is repeated.
        """
        if not buffer or not buffer.strip():
            return None

        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_buffer = ansi_escape.sub('', buffer)

        # Get non-empty lines
        lines = [line.strip() for line in clean_buffer.split('\n') if line.strip()]
        if not lines:
            return None

        # Look for repeated patterns in the last line
        last_line = lines[-1]

        # Common prompt ending characters
        common_endings = ['#', '>', '$', '%', ':', '~]', ']', '}', ')', '|']

        # First check if the last line is a simple prompt (no repetition)
        if any(last_line.endswith(char) for char in common_endings) and len(last_line) < 30:
            if not self._is_repeated_prompt(last_line):
                return last_line

        # Check for repetitions (like 'device# device# device#')
        base_prompt = self._extract_base_prompt(last_line)
        if base_prompt:
            self._log_with_timestamp(f"Extracted base prompt from repeated pattern: '{base_prompt}'")
            return base_prompt

        # If the last line doesn't have repetitions but looks like a prompt
        for line in reversed(lines):
            if any(line.endswith(char) for char in common_endings):
                base_prompt = self._extract_base_prompt(line)
                if base_prompt:
                    return base_prompt
                return line

        # Last resort - try to find anything that looks like a prompt in any line
        for line in reversed(lines):
            if len(line) < 50:
                for ending in common_endings:
                    if ending in line:
                        parts = line.split(ending)
                        if len(parts) > 1 and not parts[-1].strip():
                            base = parts[0].strip()
                            for i in range(1, len(parts) - 1):
                                base += ending + parts[i].strip()
                            return base + ending

        # If all else fails, just use the last line
        return lines[-1]

    def _is_repeated_prompt(self, text):
        """Check if text contains repeated prompt patterns."""
        parts = re.split(r'[#>$%:]', text)
        if len(parts) > 2:
            base_parts = [part.strip() for part in parts if part.strip()]
            if len(base_parts) > 1 and len(set(base_parts)) == 1:
                return True
        return False

    def _extract_base_prompt(self, text):
        """
        Extract a base prompt from text that might contain repetitions.
        Example: 'device# device# device#' -> 'device#'
        """
        # Find common ending characters
        for char in ['#', '>', '$', '%', ':', '~]', ']', '}', ')', '|']:
            if char in text:
                parts = text.split(char)
                if len(parts) > 1:
                    base_parts = [part.strip() for part in parts[:-1]]
                    if base_parts and all(part == base_parts[0] for part in base_parts):
                        return base_parts[0] + char

        # Look for repeated whitespace-separated patterns
        parts = text.split()
        if len(parts) > 1:
            potential_prompts = []
            for part in parts:
                if any(part.endswith(char) for char in ['#', '>', '$', '%', ':', '~]', ']', '}', ')', '|']):
                    potential_prompts.append(part)

            if len(potential_prompts) > 1 and len(set(potential_prompts)) == 1:
                return potential_prompts[0]

        return None

    def _create_shell_stream(self):
        """Create interactive shell stream with ANSI filtering"""
        self._log_with_timestamp("Creating shell stream with ANSI filtering")

        if self._shell:
            self._log_with_timestamp("Shell stream already exists, reusing")
            return

        self._shell = self._ssh_client.invoke_shell()
        self._shell.settimeout(self._options.timeout)

        # Wait for shell initialization
        self._log_with_timestamp("SSHClient Message: Waiting for shell initialization (2000ms)")
        time.sleep(2)

        # Read initial output with filtering
        if self._shell.recv_ready():
            filtered_data = self._recv_filtered()
            if filtered_data:
                self._output_buffer.write(filtered_data)
                self._options.output_callback(filtered_data)

    def execute_command(self, command):
        """Execute command on the remote device - INVOKE_SHELL ONLY"""
        if not self._ssh_client or not self._ssh_client.get_transport() or not self._ssh_client.get_transport().is_active():
            raise RuntimeError("SSH client is not connected")

        # Warn if using shell mode with no prompt information
        if not self._options.prompt and not self._options.expect_prompt:
            self._log_with_timestamp(
                "WARNING: Executing shell command with no prompt pattern or expect prompt defined!", True)

        self._log_with_timestamp("SSHClient Message: Executing command: '{}'".format(command), True)
        start_time = time.time()

        # ALWAYS use shell mode
        commands = command.split(',')
        result = self._execute_shell_commands(commands)

        # Wait between commands if specified
        if self._options.inter_command_time > 0:
            self._log_with_timestamp(
                "SSHClient Message: Waiting between commands: {}s".format(self._options.inter_command_time))
            time.sleep(self._options.inter_command_time)

        duration = time.time() - start_time
        self._log_with_timestamp("SSHClient Message: Command execution completed in {:.2f}ms".format(duration * 1000),
                                 True)

        return result

    def _scrub_prompt(self, raw_prompt):
        """Clean up a detected prompt to get just the prompt pattern"""
        self._log_with_timestamp(f"Raw detected prompt: '{raw_prompt}'")

        lines = raw_prompt.strip().split('\n')
        cleaned_lines = [line.strip() for line in lines if line.strip()]

        # Look through lines in reverse to find the first one that looks like a prompt
        for line in reversed(cleaned_lines):
            if line.endswith('#') or line.endswith('>') or line.endswith('$') or line.endswith('%'):
                if ' ' in line:
                    parts = line.split()
                    if parts[-1][-1] in '#>$%':
                        self._log_with_timestamp(f"Extracted prompt from command line: '{parts[-1]}'")
                        return parts[-1]

                    prompt_chars = ['#', '>', '$', '%']
                    for char in prompt_chars:
                        if char in line:
                            prompt_parts = line.split(char)
                            if len(prompt_parts) > 1:
                                potential_prompt = prompt_parts[0] + char
                                if len(potential_prompt) < 30 and ' ' not in potential_prompt[-15:]:
                                    self._log_with_timestamp(
                                        f"Extracted prompt by character split: '{potential_prompt}'")
                                    return potential_prompt
                else:
                    self._log_with_timestamp(f"Found clean prompt line: '{line}'")
                    return line

        # Fallback: regex extraction
        prompt_patterns = [
            r'(\S+[#>$%])\s*$',
            r'((?:[A-Za-z0-9_\-]+(?:\([^\)]+\))?)?[#>$%])\s*$',
            r'(\S+@\S+[#>$%])\s*$'
        ]

        for pattern in prompt_patterns:
            match = re.search(pattern, raw_prompt)
            if match:
                extracted = match.group(1)
                self._log_with_timestamp(f"Extracted prompt via regex: '{extracted}'")
                return extracted

        # Last resort
        if cleaned_lines and len(cleaned_lines[-1]) < 50:
            self._log_with_timestamp(f"Using last line as prompt: '{cleaned_lines[-1]}'")
            return cleaned_lines[-1]

        self._log_with_timestamp(f"WARNING: Could not scrub prompt, using as-is: '{raw_prompt}'", True)
        return raw_prompt

    def _execute_shell_commands(self, commands):
        """
        Execute commands in interactive shell mode with ANSI filtering

        Handles trailing commas: "term len 0,show run,,"
        - "term len 0" = command
        - "show run" = command
        - "" = newline only
        - "" = newline only

        Prompt count should match: initial + per command + per trailing newline
        """
        self._log_with_timestamp("Using shell mode for command execution with ANSI filtering")
        start_time = time.time()

        if not self._shell:
            self._log_with_timestamp("Shell stream not initialized, creating now")
            self._create_shell_stream()

        # Clear buffer and reset prompt detection flag
        self._output_buffer = StringIO()
        self._prompt_detected = False

        try:
            # Only process commands if there are meaningful commands to send
            has_commands = True

            if has_commands:
                # Process each command
                for i, cmd in enumerate(commands):
                    if not cmd.strip() or cmd.strip() == "\\n":
                        self._log_with_timestamp("Sending newline command {}/{}".format(i + 1, len(commands)))
                        self._shell.send('\n')
                    if cmd == "":
                        self._log_with_timestamp("Sending newline command {}/{}".format(i + 1, len(commands)))
                        self._shell.send('\n')


                    else:
                        self._log_with_timestamp("Sending command {}/{}: '{}'".format(i + 1, len(commands), cmd))
                        self._shell.send(cmd + '\n')

                    # Wait between commands
                    if self._options.inter_command_time > 0 and i < len(commands) - 1:
                        self._log_with_timestamp(
                            "Waiting between sub-commands: {}s".format(self._options.inter_command_time))
                        time.sleep(self._options.inter_command_time)

                # PROMPT COUNTING WITH ANSI FILTERING
                if self._options.expect_prompt:
                    expected_prompts = self._options.prompt_count
                    found_prompts = 0
                    accumulated_buffer = ""

                    self._log_with_timestamp("Monitoring for EXACTLY {} occurrences of: '{}'".format(
                        expected_prompts, self._options.expect_prompt))

                    timeout_ms = self._options.expect_prompt_timeout
                    timeout_time = time.time() + timeout_ms / 1000

                    while found_prompts < expected_prompts and time.time() < timeout_time:
                        if self._shell.recv_ready():
                            try:
                                # Use the filtered receive method
                                filtered_data = self._recv_filtered()
                                if filtered_data:
                                    accumulated_buffer += filtered_data
                                    self._output_buffer.write(filtered_data)
                                    self._options.output_callback(filtered_data)

                                    # Count prompts in filtered buffer
                                    current_count = accumulated_buffer.count(self._options.expect_prompt)

                                    if current_count > found_prompts:
                                        found_prompts = current_count
                                        self._log_with_timestamp(
                                            "PROMPT DETECTED: {}/{}".format(found_prompts, expected_prompts))

                                        if found_prompts >= expected_prompts:
                                            self._log_with_timestamp(
                                                "TARGET REACHED: {} prompts detected. STOPPING NOW.".format(
                                                    found_prompts))
                                            break

                            except Exception as e:
                                self._log_with_timestamp("Error reading output: {}".format(str(e)))
                                continue
                        else:
                            time.sleep(0.01)

                    # Final status
                    if found_prompts >= expected_prompts:
                        self._log_with_timestamp(
                            "SUCCESS: Command execution completed with {}/{} prompts".format(found_prompts,
                                                                                             expected_prompts), True)
                    else:
                        self._log_with_timestamp(
                            "TIMEOUT: Only detected {}/{} prompts after {}ms".format(found_prompts, expected_prompts,
                                                                                     timeout_ms), True)
                else:
                    # Timeout-based approach with filtering
                    self._log_with_timestamp(
                        "No expect prompt defined, waiting shell timeout: {}s".format(self._options.shell_timeout))
                    time.sleep(self._options.shell_timeout)

                    # Read remaining data with filtering
                    while self._shell.recv_ready():
                        filtered_data = self._recv_filtered()
                        if filtered_data:
                            self._output_buffer.write(filtered_data)
                            self._options.output_callback(filtered_data)

                self._log_with_timestamp("Shell command execution completed")
            else:
                self._log_with_timestamp("No commands to execute, skipping shell command execution")

        except Exception as e:
            error_message = "Error during shell execution: {}".format(str(e))
            self._log_with_timestamp(error_message, True)
            self._log_message(error_message)
            self._options.error_callback(error_message)

        total_time = time.time() - start_time
        self._log_with_timestamp("Total shell command execution time: {:.2f}ms".format(total_time * 1000))

        return self._output_buffer.getvalue()

    def set_expect_prompt(self, prompt_string):
        """Set the expected prompt string"""
        if prompt_string:
            self._options.expect_prompt = prompt_string
            self._log_with_timestamp("Expect prompt set to: '{}'".format(prompt_string), True)

    def connect(self):
        """Connect to device - PASSWORD OR KEY AUTH"""
        self._log_with_timestamp(
            f"Connecting to {self._options.host}:{self._options.port}...", True)

        try:
            self._ssh_client = paramiko.SSHClient()
            self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Apply legacy support if needed
            if self._options.legacy_mode:
                LegacySSHClientEnhancements.configure_legacy_algorithms(self._ssh_client)

            # Build connection parameters
            connect_params = {
                'hostname': self._options.host,
                'port': self._options.port,
                'username': self._options.username,
                'timeout': self._options.timeout,
                'allow_agent': False,
                'look_for_keys': False,
                'disabled_algorithms': {'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']}

            }

            # Add authentication method
            if self._options.key_file:
                # Key-based authentication
                self._log_with_timestamp("Using key-based authentication", True)
                pkey = self._load_private_key()
                connect_params['pkey'] = pkey

                # If password is also provided, it can be used as fallback
                if self._options.password:
                    self._log_with_timestamp("Password provided as fallback for key auth")
                    connect_params['password'] = self._options.password

            elif self._options.password:
                # Password-only authentication
                self._log_with_timestamp("Using password-based authentication", True)
                connect_params['password'] = self._options.password

            else:
                raise ValueError("No authentication method available")

            # Make connection
            try:
                self._ssh_client.connect(**connect_params)
            except Exception as e:
                self._log_with_timestamp("Retrying with SHA2 RSA algorithms enabled...")
                connect_params.pop('disabled_algorithms', None)  # Remove the restriction
                self._ssh_client.connect(**connect_params)


            self._log_with_timestamp(
                f"Connected to {self._options.host}:{self._options.port}", True)

            # ALWAYS create shell - invoke_shell is the only mode
            self._create_shell_stream()

            # Check if a prompt pattern is defined
            if not self._options.prompt and not self._options.expect_prompt:
                self._log_with_timestamp(
                    "WARNING: No prompt pattern or expect prompt defined. "
                    "Shell commands may not work correctly!",
                    True)

        except paramiko.AuthenticationException as e:
            self._log_with_timestamp(f"Authentication failed: {str(e)}", True)
            raise
        except Exception as e:
            self._log_with_timestamp(f"Connection error: {str(e)}", True)
            raise

    def disconnect(self):
        """Disconnect from device"""
        self._log_with_timestamp("Disconnecting from device")

        try:
            if self._shell:
                self._shell.close()
                self._shell = None

            if self._ssh_client:
                self._ssh_client.close()

            self._log_with_timestamp("Successfully disconnected")
        except Exception as e:
            self._log_with_timestamp("Error during disconnect: {}".format(str(e)), True)

    def _log_message(self, message):
        """Log message to file if log file is specified"""
        if not self._options.log_file:
            return

        try:
            log_dir = os.path.dirname(self._options.log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            with open(self._options.log_file, 'a') as f:
                f.write(message + '\n')
                f.flush()
        except Exception as e:
            self._options.error_callback("Error writing to log file: {}".format(str(e)))