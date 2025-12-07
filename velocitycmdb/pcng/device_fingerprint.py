import os
import re
import sys
import time
import json
import traceback
from enum import Enum, auto

from velocitycmdb.pcng.device_info import DeviceInfo, DeviceType
from velocitycmdb.pcng.ssh_client import SSHClient, SSHClientOptions

# Import TextFSM engine if available
try:
    from velocitycmdb.pcng.tfsm_fire import TextFSMAutoEngine

    TEXTFSM_AVAILABLE = True
except ImportError:
    TEXTFSM_AVAILABLE = False


class NetmikoDriverMap:
    """Maps device types to Netmiko driver names"""

    DRIVER_MAPPING = {
        DeviceType.CiscoIOS: "cisco_ios",
        DeviceType.CiscoNXOS: "cisco_nxos",
        DeviceType.CiscoASA: "cisco_asa",
        DeviceType.AristaEOS: "arista_eos",
        DeviceType.JuniperJunOS: "juniper_junos",
        DeviceType.HPProCurve: "hp_procurve",
        DeviceType.FortiOS: "fortinet",
        DeviceType.PaloAltoOS: "paloalto_panos",
        DeviceType.Linux: "linux",
        DeviceType.FreeBSD: "generic",
        DeviceType.Windows: "generic",
        DeviceType.GenericUnix: "generic",
        DeviceType.Unknown: "generic"
    }

    VENDOR_MAPPING = {
        DeviceType.CiscoIOS: "Cisco",
        DeviceType.CiscoNXOS: "Cisco",
        DeviceType.CiscoASA: "Cisco",
        DeviceType.AristaEOS: "Arista",
        DeviceType.JuniperJunOS: "Juniper",
        DeviceType.HPProCurve: "HP/Aruba",
        DeviceType.FortiOS: "Fortinet",
        DeviceType.PaloAltoOS: "PaloAlto",
        DeviceType.Linux: "Linux",
        DeviceType.FreeBSD: "FreeBSD",
        DeviceType.Windows: "Microsoft",
        DeviceType.GenericUnix: "Unix",
        DeviceType.Unknown: "Unknown"
    }

    @classmethod
    def get_netmiko_driver(cls, device_type):
        """Get netmiko driver name for device type"""
        return cls.DRIVER_MAPPING.get(device_type, "generic")

    @classmethod
    def get_vendor_name(cls, device_type):
        """Get standardized vendor name for device type"""
        return cls.VENDOR_MAPPING.get(device_type, "Unknown")


class DeviceFingerprint:
    """Enhanced device fingerprinting with TextFSM integration - backwards compatible"""

    def __init__(self, host, port, username, password, output_callback=None,
                 debug=False, verbose=False, connection_timeout=5000, textfsm_db_path=None,
                 ssh_key_path=None):
        self._device_info = DeviceInfo(
            host=host,
            port=port,
            username=username,

        )
        self._device_info.password = password  # Store password for reporting if needed
        self._output_buffer = []
        self._is_connected = False
        self._paging_disabled = False
        self._verbose = verbose
        self._debug = debug
        self._connection_timeout = connection_timeout

        # TextFSM integration - new feature
        self._textfsm_engine = None
        self._textfsm_db_path = textfsm_db_path

        if TEXTFSM_AVAILABLE and textfsm_db_path and os.path.exists(textfsm_db_path):
            try:
                self._textfsm_engine = TextFSMAutoEngine(textfsm_db_path, verbose=debug)
                if debug:
                    print(f"TextFSM engine initialized: {textfsm_db_path}")
            except Exception as e:
                if debug:
                    print(f"TextFSM initialization failed: {e}")
                self._textfsm_engine = None

        # Configure SSH client for fingerprinting with broader compatibility
        ssh_options = SSHClientOptions(
            host=host,
            username=username,
            password=password,
            port=port,
            key_file=ssh_key_path,  # Use key_file parameter name (not ssh_key_path)
            invoke_shell=True,
            # Start with a very broad prompt pattern
            prompt="[#>$\\]\\):]",
            expect_prompt=None,
            prompt_count=1,
            shell_timeout=2,
            inter_command_time=.5,
            expect_prompt_timeout=5000,
            debug=debug
        )

        # Set up output capture
        def buffer_callback(output):
            self._output_buffer.append(output)

        if output_callback:
            ssh_options.output_callback = lambda output: (
                output_callback(output),
                buffer_callback(output)
            )
        else:
            ssh_options.output_callback = buffer_callback
        try:
            self._ssh_client = SSHClient(ssh_options)
        except Exception as e:
            traceback.print_exc()
            raise e
    def _ensure_textfsm_engine(self):
        """
        Ensure TextFSM engine is available, create one if needed.
        Returns True if engine is available, False otherwise.
        """
        # If we already have an engine, we're good
        if self._textfsm_engine:
            return True

        # Try to create engine with different fallback paths
        potential_db_paths = []

        # Use provided path if available
        if self._textfsm_db_path:
            potential_db_paths.append(self._textfsm_db_path)

        # Add common fallback locations
        potential_db_paths.extend([
            "tfsm_templates.db",
            "./tfsm_templates.db",
            "templates/tfsm_templates.db",
            "../tfsm_templates.db",
            os.path.join(os.path.dirname(__file__), "tfsm_templates.db"),
            os.path.join(os.getcwd(), "tfsm_templates.db")
        ])

        # Try each path
        for db_path in potential_db_paths:
            if os.path.exists(db_path):
                try:
                    if self._debug:
                        print(f"Attempting to create TextFSM engine with: {db_path}")
                    from tfsm_fire import TextFSMAutoEngine
                    self._textfsm_engine = TextFSMAutoEngine(db_path, verbose=self._debug)
                    self._textfsm_db_path = db_path  # Store the working path

                    if self._debug:
                        print(f"✓ TextFSM engine created successfully: {db_path}")
                    return True

                except Exception as e:
                    print(f"Failed to create TextFSM engine with {db_path}: {e}")
                    traceback.print_exc()
                    sys.exit()

        if self._debug:
            print("No working TextFSM template database found in any fallback location")
            print(f"Searched paths: {potential_db_paths}")

        return False

    def scrub_unicode_output(self, text):
        """
        Scrub Unicode characters from output to prevent encoding errors on Windows.
        Replaces problematic Unicode with safe ASCII equivalents.
        """
        if not text:
            return text

        # Common Unicode replacements for your debug output
        replacements = {
            # Emojis to plain text
            '\U0001f50d': '[DEBUG]',  # 🔍 magnifying glass
            '\U00002705': '[SUCCESS]',  # ✅ check mark
            '\U0000274c': '[ERROR]',  # ❌ cross mark
            '\U000026a0': '[WARNING]',  # ⚠️ warning sign
            '\U0001f4cb': '[INFO]',  # 📋 clipboard
            '\U0001f6a8': '[CRITICAL]',  # 🚨 police car light
            '\U0001f4ca': '[STATS]',  # 📊 bar chart
            '\U0001f3af': '[TARGET]',  # 🎯 target
            '\U0001f44d': '[OK]',  # 👍 thumbs up
            '\U0001f44e': '[FAIL]',  # 👎 thumbs down
            '\U0001f511': '[KEY]',  # 🔑 key
            '\U0001f4dd': '[NOTE]',  # 📝 memo
            '\U0001f527': '[TOOL]',  # 🔧 wrench
            '\U0001f4e6': '[PACKAGE]',  # 📦 package
            '\U0001f680': '[ROCKET]',  # 🚀 rocket
            '\U0001f4c8': '[TREND]',  # 📈 trending up
            '\U0001f4c9': '[DOWN]',  # 📉 trending down

            # Arrow symbols
            '\u27a4': '->',  # ➤ arrow
            '\u2192': '->',  # → arrow
            '\u2190': '<-',  # ← arrow
            '\u2191': '^',  # ↑ arrow
            '\u2193': 'v',  # ↓ arrow

            # Check marks and crosses
            '\u2713': '[OK]',  # ✓ check
            '\u2717': '[X]',  # ✗ cross
            '\u2714': '[DONE]',  # ✔ heavy check
            '\u2718': '[FAIL]',  # ✘ heavy cross

            # Bullets and symbols
            '\u2022': '*',  # • bullet
            '\u25cf': '*',  # ● black circle
            '\u25cb': 'o',  # ○ white circle
            '\u25a0': '[#]',  # ■ black square
            '\u25a1': '[ ]',  # □ white square

            # Other common symbols
            '\u2026': '...',  # … ellipsis
            '\u00a9': '(c)',  # © copyright
            '\u00ae': '(R)',  # ® registered
            '\u2122': '(TM)',  # ™ trademark
        }

        # Apply all replacements
        cleaned_text = text
        for unicode_char, replacement in replacements.items():
            cleaned_text = cleaned_text.replace(unicode_char, replacement)

        # Remove any remaining non-ASCII characters that could cause issues
        # Keep common extended ASCII but remove problematic Unicode
        cleaned_text = re.sub(r'[^\x00-\xff]', '?', cleaned_text)

        return cleaned_text

    def _extract_from_textfsm(self, textfsm_results):
        """Extract information from TextFSM results - field-aware and context-sensitive"""
        print("TEXTFSM_EXTRACT: Starting field-aware extraction")
        if not textfsm_results:
            print("TEXTFSM_EXTRACT: No results provided")
            return False

        extracted = []

        # Strategy 1: Use field_analysis with field name hints (PRIORITY)
        if 'field_analysis' in textfsm_results:
            print("TEXTFSM_EXTRACT: Processing field_analysis with field name hints")
            field_analysis = textfsm_results['field_analysis']

            for field_name, field_info in field_analysis.items():
                if not isinstance(field_info, dict) or not field_info.get('non_empty', False):
                    continue

                value = field_info.get('value', '').strip()
                if not value:
                    continue

                potential_mapping = field_info.get('potential_mapping', 'unknown')

                # Use field name + potential mapping as strong hints
                field_assigned = False

                # HOSTNAME: If field is named HOSTNAME and has any non-blank value, use it
                if ('HOSTNAME' in field_name.upper() and not self._device_info.hostname):
                    self._device_info.hostname = value
                    extracted.append(f"hostname='{value}' (from {field_name})")
                    field_assigned = True
                    print(f"TEXTFSM_EXTRACT: SUCCESS - Set hostname: '{value}' from {field_name}")

                # HOSTNAME fallback: potential_mapping hint only if no HOSTNAME field found yet
                elif (potential_mapping == 'hostname' and not self._device_info.hostname and not field_assigned):
                    self._device_info.hostname = value
                    extracted.append(f"hostname='{value}' (from {field_name})")
                    field_assigned = True
                    print(f"TEXTFSM_EXTRACT: SUCCESS - Set hostname: '{value}' from {field_name} (mapping hint)")

                # VERSION: Prioritize field names, but handle both SOFTWARE_VERSION and VERSION
                elif not self._device_info.version and not field_assigned:
                    # First priority: SOFTWARE_VERSION field name (Arista)
                    if field_name.upper() == 'SOFTWARE_VERSION':
                        self._device_info.version = value
                        extracted.append(f"version='{value}' (from {field_name})")
                        field_assigned = True
                        print(f"TEXTFSM_EXTRACT: SUCCESS - Set version: '{value}' from {field_name}")

                    # Second priority: VERSION field name (HP, Cisco) - but NOT HW_VERSION
                    elif field_name.upper() == 'VERSION':
                        self._device_info.version = value
                        extracted.append(f"version='{value}' (from {field_name})")
                        field_assigned = True
                        print(f"TEXTFSM_EXTRACT: SUCCESS - Set version: '{value}' from {field_name}")

                    # Third priority: Other VERSION fields (but exclude HW_VERSION, ROM_VERSION)
                    elif ('VERSION' in field_name.upper() and
                          field_name.upper() not in ['HW_VERSION', 'ROM_VERSION', 'ROMMON_VERSION']):
                        if self._looks_like_version_content(value):
                            self._device_info.version = value
                            extracted.append(f"version='{value}' (from {field_name})")
                            field_assigned = True
                            print(f"TEXTFSM_EXTRACT: SUCCESS - Set version: '{value}' from {field_name}")

                    # Fourth priority: potential_mapping hint (but not for hardware versions)
                    elif (potential_mapping == 'software_version' and
                          field_name.upper() not in ['HW_VERSION', 'ROM_VERSION', 'ROMMON_VERSION']):
                        if self._looks_like_version_content(value):
                            self._device_info.version = value
                            extracted.append(f"version='{value}' (from {field_name})")
                            field_assigned = True
                            print(f"TEXTFSM_EXTRACT: SUCCESS - Set version: '{value}' from {field_name}")

                # SERIAL: Check field name first, then content
                elif (('SERIAL' in field_name.upper() or potential_mapping == 'serial_number')
                      and not self._device_info.serial_number
                      and not field_assigned):
                    self._device_info.serial_number = value
                    extracted.append(f"serial='{value}' (from {field_name})")
                    field_assigned = True
                    print(f"TEXTFSM_EXTRACT: SUCCESS - Set serial: '{value}' from {field_name}")

                # MODEL/HARDWARE: Check field name first, then content
                elif ((
                              'HARDWARE' in field_name.upper() or 'MODEL' in field_name.upper() or potential_mapping == 'model')
                      and not self._device_info.model
                      and not field_assigned):
                    self._device_info.model = value
                    extracted.append(f"model='{value}' (from {field_name})")
                    field_assigned = True
                    print(f"TEXTFSM_EXTRACT: SUCCESS - Set model: '{value}' from {field_name}")

                if not field_assigned:
                    print(f"TEXTFSM_EXTRACT: SKIPPED - {field_name}='{value}' (mapping: {potential_mapping})")

        # Strategy 2: Fallback to records/raw_rows if field_analysis missed anything
        missing_fields = []
        if not self._device_info.hostname:
            missing_fields.append('hostname')
        if not self._device_info.version:
            missing_fields.append('version')
        if not self._device_info.model:
            missing_fields.append('model')
        if not self._device_info.serial_number:
            missing_fields.append('serial_number')

        if missing_fields:
            print(f"TEXTFSM_EXTRACT: Still missing {missing_fields}, trying records/raw_rows")

            # Try records structure
            if 'records' in textfsm_results and textfsm_results['records']:
                for i, record in enumerate(textfsm_results['records']):
                    if isinstance(record, dict):
                        self._extract_from_record(record, f"records[{i}]", extracted)

            # Try raw_rows structure
            if 'raw_rows' in textfsm_results and textfsm_results['raw_rows']:
                for i, row in enumerate(textfsm_results['raw_rows']):
                    if isinstance(row, dict):
                        self._extract_from_record(row, f"raw_rows[{i}]", extracted)

        print(f"TEXTFSM_EXTRACT: FINAL RESULT - {len(extracted)} fields extracted")
        for item in extracted:
            print(f"TEXTFSM_EXTRACT: {item}")

        success = len(extracted) > 0
        print(f"TEXTFSM_EXTRACT: Returning {success}")
        return success

    def _extract_from_record(self, record, source_prefix, extracted):
        """Extract from a single record using field names as hints"""
        for field_name, value in record.items():
            clean_value = self._clean_textfsm_value(value)
            if not clean_value:
                continue

            field_assigned = False

            # Hostname fields - use any non-blank value from HOSTNAME field
            if 'HOSTNAME' in field_name.upper() and not self._device_info.hostname:
                self._device_info.hostname = clean_value
                extracted.append(f"hostname='{clean_value}' (from {source_prefix}.{field_name})")
                field_assigned = True
                print(f"TEXTFSM_EXTRACT: SUCCESS - Set hostname: '{clean_value}' from {source_prefix}.{field_name}")

            # Version fields - be more specific
            elif (field_name.upper() in ('VERSION', 'SOFTWARE_VERSION', 'SW_VERSION', 'OS_VERSION')
                  and not self._device_info.version and not field_assigned):
                if self._looks_like_version_content(clean_value):
                    self._device_info.version = clean_value
                    extracted.append(f"version='{clean_value}' (from {source_prefix}.{field_name})")
                    field_assigned = True
                    print("TEXTFSM_EXTRACT: SUCCESS - Set version: '{}' from {}.{}".format(
                        clean_value, source_prefix, field_name
                    ))

            # Serial fields
            elif 'SERIAL' in field_name.upper() and not self._device_info.serial_number and not field_assigned:
                self._device_info.serial_number = clean_value
                extracted.append(f"serial='{clean_value}' (from {source_prefix}.{field_name})")
                field_assigned = True
                print(f"TEXTFSM_EXTRACT: SUCCESS - Set serial: '{clean_value}' from {source_prefix}.{field_name}")

            # Model/Hardware fields
            elif (('HARDWARE' in field_name.upper() or 'MODEL' in field_name.upper())
                  and not self._device_info.model and not field_assigned):
                self._device_info.model = clean_value
                extracted.append(f"model='{clean_value}' (from {source_prefix}.{field_name})")
                field_assigned = True
                print(f"TEXTFSM_EXTRACT: SUCCESS - Set model: '{clean_value}' from {source_prefix}.{field_name}")

    def _looks_like_version_content(self, value):
        """More specific version validation"""
        if not value:
            return False

        # Version should contain numbers and dots, not be too long
        if len(value) > 50:  # Too long for a version
            return False

        # Must contain at least one digit
        if not any(c.isdigit() for c in value):
            return False

        # Common version patterns
        import re
        version_patterns = [
            r'^\d+\.\d+',  # 17.9, 15.1.2
            r'^\d+\.\d+\.\d+',  # 17.9.6
            r'^\d+\.\d+\.\d+[a-zA-Z]',  # 17.9.6a
            r'^[vV]\d+',  # v17
            r'^\d+\.[A-Za-z0-9\.\-]+',  # 15.1(4)M4
            r'^*'
        ]

        for pattern in version_patterns:
            if re.match(pattern, value):
                return True

        # Reject obvious non-versions
        non_version_patterns = [
            r'^[A-Z]{2,}[0-9]{6,}',  # Serial numbers like FXS2516Q2GW
            r'\.bin$',  # Binary files
            r'^[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:',  # MAC addresses
        ]

        for pattern in non_version_patterns:
            if re.search(pattern, value):
                return False

        return False

    def _needs_additional_commands(self, command, output):
        print(f"NEEDS_ADDITIONAL_COMMANDS: cmd='{command}', output_len={len(output)}")
        print(f"NEEDS_ADDITIONAL_COMMANDS: first 200 chars: '{output[:200]}'")

        additional_commands = []

        if command.lower() == "show version":
            print("NEEDS_ADDITIONAL_COMMANDS: Processing show version")

            # Simple check - just look for 'image stamp'
            if 'image stamp' in output.lower():
                print("NEEDS_ADDITIONAL_COMMANDS: Found 'image stamp' - adding show system info")
                additional_commands.append("show system info")
            else:
                print("NEEDS_ADDITIONAL_COMMANDS: 'image stamp' not found in output")

            # Also check for device type
            if self._device_info.device_type == DeviceType.HPProCurve:
                print("NEEDS_ADDITIONAL_COMMANDS: Device is HPProCurve - adding show system info")
                if "show system info" not in additional_commands:
                    additional_commands.append("show system info")

        print(f"NEEDS_ADDITIONAL_COMMANDS: returning {additional_commands}")
        return additional_commands


    def fingerprint(self):
        """Enhanced fingerprinting with dynamic command addition"""
        engine_created = self._ensure_textfsm_engine()
        print(f"Engine creation result: {engine_created}")

        try:
            # Connect to the device
            if self._debug:
                print("Connecting to {}:{}...".format(self._device_info.host, self._device_info.port))
            self._ssh_client.connect()
            self._is_connected = True

            # Detect prompt
            self._device_info.detected_prompt = self.detect_prompt()
            if self._debug:
                print("Detected prompt: {}".format(self._device_info.detected_prompt))

            # Initial device type detection and paging setup
            if self._device_info.detected_prompt:
                initial_output = ''.join(self._output_buffer)
                initial_device_type = self.identify_vendor_from_output(initial_output)

                if initial_device_type != DeviceType.Unknown:
                    self._device_info.device_type = initial_device_type
                    if self._debug:
                        print("Initial device type detection: {}".format(initial_device_type.name))

                # Disable paging
                disable_paging_cmd = self._device_info.device_type.get_disable_paging_command()
                if disable_paging_cmd:
                    if self._debug:
                        print("Disabling paging with command: {}".format(disable_paging_cmd))
                    self._device_info.disable_paging_command = disable_paging_cmd
                    self.safe_execute_command(disable_paging_cmd)
                    self._paging_disabled = True

            # Get initial identification commands
            identification_commands = []
            if self._device_info.device_type != DeviceType.Unknown:
                identification_commands = self._device_info.device_type.get_identification_commands()
            else:
                identification_commands = ["show version"]

            # Execute commands with dynamic addition logic
            commands_executed = 0
            additional_paging_commands = ["terminal length 0", "set cli screen-length 0", "no page",
                                          "set cli pager off"]

            for dcmd in additional_paging_commands:
                self.safe_execute_command(dcmd)

            # Process identification commands
            all_commands_to_run = identification_commands.copy()
            executed_commands = set()  # Track what we've already run

            i = 0

            while i < len(all_commands_to_run):
                cmd = all_commands_to_run[i]

                # Skip if we've already executed this command
                if cmd in executed_commands:
                    i += 1
                    continue

                commands_executed += 1
                if self._debug:
                    print("Executing identification command {}: {}".format(commands_executed, cmd))

                output = self.safe_execute_command(cmd)
                executed_commands.add(cmd)  # Mark as executed

                # Store the command output
                self._device_info.command_outputs[cmd] = output

                # Check if we need additional commands based on this output
                additional_commands = self._needs_additional_commands(cmd, output)

                if additional_commands:
                    if self._debug:
                        print(f"Adding {len(additional_commands)} additional commands: {additional_commands}")

                    # Add new commands to the end of our list if not already present
                    for additional_cmd in additional_commands:
                        if additional_cmd not in all_commands_to_run and additional_cmd not in executed_commands:
                            all_commands_to_run.append(additional_cmd)
                            if self._debug:
                                print(f"Queued additional command: {additional_cmd}")

                # Process TextFSM with priority logic
                if self._textfsm_engine and output:
                    should_process_textfsm = False

                    # Priority 1: Always process 'show system info' if available
                    if cmd.lower() == "show system info":
                        should_process_textfsm = True
                        if self._debug:
                            print(f"Processing TextFSM for '{cmd}' (priority command)")

                    # Priority 2: Only process 'show version' if 'show system info' is NOT queued
                    elif cmd.lower() == "show version":
                        has_show_system_info = any(
                            cmd_name.lower() == "show system info"
                            for cmd_name in all_commands_to_run
                        )
                        if not has_show_system_info:
                            should_process_textfsm = True
                            if self._debug:
                                print(f"Processing TextFSM for '{cmd}' (no show system info available)")
                        else:
                            if self._debug:
                                print(f"Skipping TextFSM for '{cmd}' (show system info will be processed instead)")

                    # Process other commands normally
                    elif cmd.lower() in ["show inventory", "show module", "show chassis"]:
                        should_process_textfsm = True
                        if self._debug:
                            print(f"Processing TextFSM for '{cmd}' (standard command)")

                    if should_process_textfsm:
                        print("Processing TextFSM")
                        textfsm_results = self._parse_with_textfsm(output, cmd)
                        if textfsm_results:
                            # Store TextFSM results
                            self._device_info.command_outputs[f"{cmd}_textfsm"] = textfsm_results

                            # SET DEVICE TYPE BASED ON TEXTFSM TEMPLATE - NEW CODE BLOCK
                            if textfsm_results.get('template_name', '').startswith('hp_procurve'):
                                self._device_info.device_type = DeviceType.HPProCurve
                                if self._debug:
                                    print(
                                        f"Set device type to HPProCurve based on TextFSM template: {textfsm_results.get('template_name')}")
                            elif textfsm_results.get('template_name', '').startswith('cisco_ios'):
                                self._device_info.device_type = DeviceType.CiscoIOS
                                if self._debug:
                                    print(
                                        f"Set device type to CiscoIOS based on TextFSM template: {textfsm_results.get('template_name')}")
                            elif textfsm_results.get('template_name', '').startswith('cisco_nxos'):
                                self._device_info.device_type = DeviceType.CiscoNXOS
                                if self._debug:
                                    print(
                                        f"Set device type to CiscoNXOS based on TextFSM template: {textfsm_results.get('template_name')}")
                            elif textfsm_results.get('template_name', '').startswith('arista'):
                                self._device_info.device_type = DeviceType.AristaEOS
                                if self._debug:
                                    print(
                                        f"Set device type to AristaEOS based on TextFSM template: {textfsm_results.get('template_name')}")
                            elif textfsm_results.get('template_name', '').startswith('juniper'):
                                self._device_info.device_type = DeviceType.JuniperJunOS
                                if self._debug:
                                    print(
                                        f"Set device type to JuniperJunOS based on TextFSM template: {textfsm_results.get('template_name')}")
                            # END NEW CODE BLOCK

                            # Extract information - THIS WAS MISSING!
                            pre_textfsm_state = {
                                'hostname': self._device_info.hostname,
                                'version': self._device_info.version,
                                'model': self._device_info.model,
                                'serial_number': self._device_info.serial_number
                            }


                            extraction_success = self._extract_from_textfsm(textfsm_results,command=cmd)

                            if self._debug:
                                post_textfsm_state = {
                                    'hostname': self._device_info.hostname,
                                    'version': self._device_info.version,
                                    'model': self._device_info.model,
                                    'serial_number': self._device_info.serial_number
                                }
                                print(f"TextFSM extraction result: {extraction_success}")
                                print(f"Before: {pre_textfsm_state}")
                                print(f"After:  {post_textfsm_state}")
                # Try to identify device type from command output if still unknown
                if self._device_info.device_type == DeviceType.Unknown:
                    detected_type = self.identify_vendor_from_output(output)
                    if detected_type != DeviceType.Unknown:
                        self._device_info.device_type = detected_type
                        if self._debug:
                            print("Detected device type: {}".format(detected_type.name))

                        # Update paging if needed
                        if not self._paging_disabled:
                            disable_paging_cmd = self._device_info.device_type.get_disable_paging_command()
                            if disable_paging_cmd:
                                if self._debug:
                                    print("Disabling paging with command: {}".format(disable_paging_cmd))
                                self._device_info.disable_paging_command = disable_paging_cmd
                                self.safe_execute_command(disable_paging_cmd)
                                self._paging_disabled = True

                # Check for early completion
                if self.is_fingerprint_complete():
                    remaining_commands = len(all_commands_to_run) - i - 1
                    if remaining_commands > 0:
                        if self._debug:
                            print("Fingerprinting complete! Skipping {} remaining commands: {}".format(
                                remaining_commands,
                                all_commands_to_run[i + 1:]
                            ))
                    break

                i += 1
            # Continue with TextFSM fallback logic and cleanup
            textfsm_attempted = any(key.endswith('_textfsm') for key in self._device_info.command_outputs.keys())

            if not textfsm_attempted:
                print("TextFSM not available or no templates found - using regex extraction fallback")
                self.extract_device_details()
            else:
                missing_fields = []
                textfsm_extracted_something = any([
                    self._device_info.version,
                    self._device_info.model,
                    self._device_info.serial_number
                ])

                if not textfsm_extracted_something:
                    print("TextFSM didn't extract any key fields - running regex fallback...")
                    self.extract_device_details()
                    missing_fields.append("Data")
                else:
                    if self._debug:
                        extracted_fields = []
                        if self._device_info.version:
                            extracted_fields.append(f"version='{self._device_info.version}'")
                        if self._device_info.model:
                            extracted_fields.append(f"model='{self._device_info.model}'")
                        if self._device_info.serial_number:
                            extracted_fields.append(f"serial='{self._device_info.serial_number}'")
                        print(f"TextFSM successfully extracted: {', '.join(extracted_fields)}")

                if missing_fields:
                    print(f"TextFSM succeeded but missing fields: {', '.join(missing_fields)}")
                    print("Running regex fallback for missing fields...")
                    self.extract_device_details()

            # Add enhanced metadata
            self._add_enhanced_metadata()

            return self._device_info

        except Exception as e:
            if self._debug:
                print("Error during fingerprinting: {}".format(str(e)))
                traceback.print_exc()

            self._device_info.device_type = DeviceType.Unknown
            self._device_info.detected_prompt = None
            return self._device_info
        finally:
            if self._is_connected:
                self._ssh_client.disconnect()
                self._is_connected = False

    def is_fingerprint_complete(self):
        # Remove this line: return True

        # Actually check if we have what we need
        has_required = all([
            self._device_info.hostname
        ])

        has_valuable = any([
            self._device_info.serial_number,
            self._device_info.model
        ])

        return has_required and has_valuable
    def _create_textfsm_filter(self, output, command):
        """Build intelligent filter based on output analysis and command"""

        # Vendor detection patterns from actual output
        vendor_patterns = {
            'cisco_ios': [
                'cisco ios', 'cisco internetwork operating system', 'ios software',
                'catalyst', 'c9300', 'c9200', 'c3850', 'c2960', 'ws-c'
            ],
            'cisco_nxos': [
                'nx-os', 'nexus', 'cisco nexus', 'nxos'
            ],
            'cisco_asa': [
                'adaptive security appliance', 'cisco asa', 'asa version'
            ],
            'cisco_xr': [
                'ios xr', 'cisco xr', 'asr9k', 'crs-'
            ],
            'arista_eos': [
                'arista', 'eos version', 'dcs-', 'arista dcs'
            ],
            'juniper_junos': [
                'juniper', 'junos', 'ex4200', 'mx', 'srx', 'qfx'
            ],
            'hp_procurve': [
                'hp ', 'hewlett-packard', 'procurve', 'aruba', 'hpe','Status and Counters - General System Information'
            ],
            'fortinet': [
                'fortinet', 'fortigate', 'fortios'
            ],
            'paloalto_panos': [
                'palo alto', 'pan-os', 'pa-'
            ],
            'dell_force10': [
                'dell', 'force10', 's4810', 's6000'
            ],
            'brocade_fastiron': [
                'brocade', 'fastiron', 'icx'
            ],
            'checkpoint_gaia': [
                'checkpoint', 'gaia', 'secureplatform'
            ],
            'ubiquiti_edgerouter': [
                'ubiquiti', 'edgerouter', 'unifi'
            ],
            'ubiquiti_edgeswitch': [
                'edgeswitch', 'ubnt'
            ]
        }

        # Analyze output to detect vendor
        output_lower = output.lower()
        detected_vendors = []

        for vendor, patterns in vendor_patterns.items():
            for pattern in patterns:
                if pattern in output_lower:
                    detected_vendors.append(vendor)
                    break

        # Command analysis
        cmd_lower = command.lower().replace(" ", "_")

        # Build filter attempts from most specific to least specific
        filter_attempts = []
        if "Status and Counters - General System Information" in output:
            detected_vendors.append("hp_procurve")
        # Level 1: Exact vendor + command matches
        for vendor in detected_vendors:
            exact_filter = f"{vendor}_{cmd_lower}"
            filter_attempts.append(exact_filter)

        # Level 2: Vendor + base command (show_version vs show_version_detail)
        base_cmd = cmd_lower.split('_')[0:2]  # "show_version" from "show_version_detail"
        if len(base_cmd) >= 2:
            base_cmd_str = "_".join(base_cmd)
            for vendor in detected_vendors:
                base_filter = f"{vendor}_{base_cmd_str}"
                if base_filter not in filter_attempts:
                    filter_attempts.append(base_filter)

        # Level 3: Command-specific fallbacks based on known DB patterns
        command_fallbacks = {
            'show_version': ['show_version', 'version'],
            # 'show_system': ['show_system', 'system'],
            # 'show_inventory': ['show_inventory', 'inventory'],
            # 'show_system_info': ['show_system', 'system'],
            # 'show_system_information': ['show_system', 'system']
        }

        if cmd_lower in command_fallbacks:
            filter_attempts.extend(command_fallbacks[cmd_lower])

        # Level 4: Ultra-generic fallbacks
        if not filter_attempts:
            filter_attempts = [cmd_lower, 'show', 'version']

        if self._debug:
            print(f"Smart filter analysis:")
            print(f"  Command: {command}")
            print(f"  Detected vendors: {detected_vendors}")
            print(f"  Filter attempts: {filter_attempts}")

        return filter_attempts

    # !/usr/bin/env python3
    """
    SIMPLIFIED _parse_with_textfsm and _strip_command_echo methods for device_fingerprint.py

    KEY INSIGHT: tfsm_fire's find_best_template() already:
      - Iterates through all matching templates
      - Parses output with each template
      - Scores results
      - Returns: (template_name, parsed_data_as_list_of_dicts, score)

    We were redundantly iterating and re-parsing, which caused confusion.

    INSTRUCTIONS:
    1. Add the _strip_command_echo method to your DeviceFingerprint class
    2. Replace your existing _parse_with_textfsm method with the simplified one below
    3. Add/update the _extract_from_textfsm method to use the new result format
    """

    def _strip_command_echo(self, output, command):
        """
        Strip the echoed command and prompt artifacts from command output.

        SSH shell mode echoes the command back, which breaks TextFSM parsing.
        Example input:
            show version
            Hostname: edge1-01
            Model: mx10003
            ...
            {master}
            admin@edge1-01>

        Example output (cleaned):
            Hostname: edge1-01
            Model: mx10003
            ...
        """
        if not output:
            return output

        lines = output.splitlines(keepends=True)
        if not lines:
            return output

        # Strip leading empty lines and whitespace-only lines
        while lines and not lines[0].strip():
            lines.pop(0)

        if not lines:
            return output

        # Check if first line is the command echo
        first_line = lines[0].strip()
        cmd_normalized = command.strip()

        # Match exact command or command with trailing whitespace
        if first_line == cmd_normalized or first_line.rstrip() == cmd_normalized:
            lines.pop(0)
            if self._debug:
                print(f"  Stripped command echo: '{cmd_normalized}'")

        # Strip trailing prompt lines (may have {master} prefix on Juniper)
        # Work backwards to remove prompt and any preceding tags like {master}
        while lines:
            last_line = lines[-1].strip()

            # Skip empty lines at end
            if not last_line:
                lines.pop()
                continue

            # Check for prompt
            if self._device_info.detected_prompt:
                if last_line.endswith(self._device_info.detected_prompt) or \
                        last_line == self._device_info.detected_prompt:
                    lines.pop()
                    if self._debug:
                        print(f"  Stripped trailing prompt line")
                    continue

            # Check for Juniper {master} tag or similar
            if last_line.startswith('{') and last_line.endswith('}'):
                lines.pop()
                if self._debug:
                    print(f"  Stripped Juniper tag: '{last_line}'")
                continue

            # No more lines to strip
            break

        return ''.join(lines)

    def _parse_with_textfsm(self, output, command):
        """
        Parse command output with TextFSM using tfsm_fire's find_best_template.

        find_best_template() handles all the heavy lifting:
          - Iterates through matching templates
          - Parses output with each template
          - Scores results
          - Returns: (template_name, parsed_data_as_list_of_dicts, score)
        """
        self._ensure_textfsm_engine()

        if not self._textfsm_engine:
            if self._debug:
                print("TextFSM engine not available")
            return None

        try:
            # ================================================================
            # Strip command echo before parsing
            # SSH shell mode echoes the command, breaking TextFSM templates
            # ================================================================
            cleaned_output = self._strip_command_echo(output, command)
            if self._debug:
                orig_len = len(output)
                clean_len = len(cleaned_output)
                print(f"Output after stripping echo/prompts: {orig_len} -> {clean_len} bytes")

                # Show first line change if any
                orig_first = output.split('\n')[0][:60] if output else ''
                clean_first = cleaned_output.split('\n')[0][:60] if cleaned_output else ''
                if orig_first != clean_first:
                    print(f"  Was: {orig_first!r}")
                    print(f"  Now: {clean_first!r}")

            # ================================================================
            # Create filter strings to try (e.g., "juniper_junos_show_version")
            # ================================================================
            filter_attempts = self._create_textfsm_filter(cleaned_output, command)
            if self._debug:
                print(f"Filter attempts: {filter_attempts}")

            best_result = None
            best_score = 0

            # ================================================================
            # Try each filter - find_best_template does ALL the work
            # ================================================================
            for i, filter_string in enumerate(filter_attempts):
                if self._debug:
                    print(f"\nTrying filter {i + 1}/{len(filter_attempts)}: '{filter_string}'")

                # find_best_template iterates all matching templates internally
                # Returns: (template_name: str, parsed_data: List[Dict], score: float)
                template_name, parsed_data, score = self._textfsm_engine.find_best_template(
                    cleaned_output, filter_string
                )

                if self._debug:
                    record_count = len(parsed_data) if parsed_data else 0
                    print(f"  Result: template='{template_name}', score={score:.1f}, records={record_count}")

                if score > best_score:
                    best_score = score
                    best_result = {
                        "template_name": template_name,
                        "score": score,
                        "records": parsed_data or [],  # Already List[Dict] from tfsm_fire!
                        "filter_used": filter_string,
                        "filter_rank": i + 1,
                    }

                    if self._debug:
                        print(f"  New best match!")
                        if parsed_data and len(parsed_data) > 0:
                            # Show key fields from first record
                            sample = parsed_data[0]
                            print(f"  Fields: {list(sample.keys())}")
                            for key in ['HOSTNAME', 'MODEL', 'VERSION', 'SERIAL', 'HARDWARE', 'JUNOS_VERSION']:
                                if key in sample and sample[key]:
                                    print(f"    {key}: {sample[key]}")

                # Short-circuit on high confidence match
                if score > 50:
                    if self._debug:
                        print("  High confidence match, stopping filter search")
                    break

            # ================================================================
            # Return best result if we found anything useful
            # ================================================================
            if best_result and best_result["score"] > 0:
                if self._debug:
                    print(f"\nBest result: {best_result['template_name']} "
                          f"(filter: {best_result['filter_used']}, score: {best_result['score']:.1f})")
                return best_result

            if self._debug:
                print("\nNo successful TextFSM matches found")
            return None

        except Exception as e:
            if self._debug:
                print(f"TextFSM parsing failed for {command}: {e}")
                import traceback
                traceback.print_exc()
            return None

    def _extract_from_textfsm(self, textfsm_result, command):
        """
        Extract device info from TextFSM parsed results.

        textfsm_result structure:
        {
            "template_name": "juniper_junos_show_version",
            "score": 30.0,
            "records": [{"HOSTNAME": "router1", "MODEL": "MX480", ...}],
            "filter_used": "juniper_junos_show_version"
        }
        """
        if not textfsm_result or not textfsm_result.get("records"):
            return

        records = textfsm_result["records"]
        if not records:
            return

        # Use first record for device-level info
        record = records[0]

        if self._debug:
            print(f"Extracting from TextFSM result: {textfsm_result['template_name']}")
            print(f"  Available fields: {list(record.keys())}")

        # ================================================================
        # Extract hostname
        # ================================================================
        hostname_fields = ['HOSTNAME', 'HOST_NAME', 'DEVICE_NAME', 'SWITCHNAME', 'NAME']
        for field in hostname_fields:
            value = record.get(field)
            if value and not self._device_info.hostname:
                # Validate it's not a garbage value
                invalid_hostnames = {
                    'host-name', 'hostname', 'name', 'device', 'switch', 'router',
                    'description', 'chassis', 'system', 'none', 'null', 'unknown'
                }
                if value.lower() not in invalid_hostnames:
                    self._device_info.hostname = value
                    if self._debug:
                        print(f"  Set hostname: {value} (from {field})")
                    break

        # ================================================================
        # Extract model
        # ================================================================
        model_fields = ['MODEL', 'HARDWARE', 'PLATFORM', 'CHASSIS', 'DEVICE_MODEL']
        for field in model_fields:
            value = record.get(field)
            if value and not self._device_info.model:
                # Handle list values (e.g., stack members)
                if isinstance(value, list):
                    value = value[0] if value else None
                if value:
                    self._device_info.model = value
                    if self._debug:
                        print(f"  Set model: {value} (from {field})")
                    break

        # ================================================================
        # Extract version
        # ================================================================
        version_fields = ['VERSION', 'JUNOS_VERSION', 'OS_VERSION', 'SOFTWARE_VERSION',
                          'RUNNING_IMAGE', 'SYSTEM_IMAGE', 'ROMMON', 'BOOTLDR']
        for field in version_fields:
            value = record.get(field)
            if value and not self._device_info.version:
                self._device_info.version = value
                if self._debug:
                    print(f"  Set version: {value} (from {field})")
                break

        # ================================================================
        # Extract serial number
        # ================================================================
        serial_fields = ['SERIAL', 'SERIAL_NUMBER', 'CHASSIS_SERIAL', 'SYSTEM_SERIAL_NUMBER']
        for field in serial_fields:
            value = record.get(field)
            if value and not self._device_info.serial_number:
                # Handle list values
                if isinstance(value, list):
                    value = value[0] if value else None
                # Validate it's not a garbage value
                invalid_serials = {'description', 'serial', 'serial_number', 'sn', 'chassis', 'none', 'n/a'}
                if value and value.lower() not in invalid_serials:
                    self._device_info.serial_number = value
                    if self._debug:
                        print(f"  Set serial: {value} (from {field})")
                    break

        # ================================================================
        # Extract uptime if available
        # ================================================================
        uptime_fields = ['UPTIME', 'UPTIME_DAYS', 'UPTIME_HOURS', 'UPTIME_MINUTES']
        for field in uptime_fields:
            value = record.get(field)
            if value and not self._device_info.uptime:
                self._device_info.uptime = str(value)
                if self._debug:
                    print(f"  Set uptime: {value} (from {field})")
                break

        # ================================================================
        # Store raw TextFSM data in additional_info for later use
        # ================================================================
        self._device_info.additional_info['textfsm_result'] = {
            'template': textfsm_result.get('template_name'),
            'score': textfsm_result.get('score'),
            'record_count': len(records),
            'fields': list(record.keys())
        }
    def _analyze_textfsm_fields_enhanced(self, headers, raw_data, parsed_dict_data):
        """Enhanced field analysis using both raw TextFSM data and parsed dictionaries"""
        if not headers or not raw_data:
            return self._analyze_textfsm_fields(parsed_dict_data) if parsed_dict_data else {}

        # Use first record for analysis
        first_record = raw_data[0] if raw_data else []

        field_analysis = {}

        for i, header in enumerate(headers):
            value = first_record[i] if i < len(first_record) else None

            # Handle different value types (strings, lists, etc.)
            if isinstance(value, list):
                display_value = value[0] if value else ""
                non_empty = bool(value)
            else:
                display_value = str(value) if value is not None else ""
                non_empty = bool(value and str(value).strip())

            field_analysis[header] = {
                'value': display_value,
                'raw_value': value,
                'type': type(value).__name__,
                'non_empty': non_empty,
                'potential_mapping': self._guess_field_purpose(header, display_value)
            }

        return field_analysis

    # Additional helper method to debug the _looks_like_* functions
    def debug_field_classification(self, value):
        """Debug helper to show why a value is or isn't classified as a certain type"""
        print(f"\nFIELD CLASSIFICATION DEBUG for: '{value}'")

        checks = [
            ('hostname', self._looks_like_hostname),
            ('version', self._looks_like_version),
            ('serial', self._looks_like_serial),
            ('model', self._looks_like_model)
        ]

        for check_name, check_func in checks:
            try:
                result = check_func(value)
                print(f"   {check_name}: {result}")
            except Exception as e:
                print(f"   {check_name}: ERROR - {e}")

        print("END CLASSIFICATION DEBUG\n")



    def _clean_textfsm_value(self, value):
        """Clean and normalize any value from TextFSM, regardless of type"""
        if value is None:
            return None

        # Handle lists - take first non-empty item
        if isinstance(value, list):
            for item in value:
                if item is not None:
                    cleaned = str(item).strip()
                    if cleaned:
                        return cleaned
            return None

        # Handle strings
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned if cleaned else None

        # Handle numbers
        if isinstance(value, (int, float)):
            return str(value)

        # Handle anything else
        try:
            cleaned = str(value).strip()
            return cleaned if cleaned else None
        except:
            return None

    def _could_be_hostname(self, value):
        return True
        """Relaxed hostname detection"""
        if not value or len(value) < 2:
            return False

        # Basic hostname patterns - be more accepting
        if any(char in value.lower() for char in ['host', 'name', 'device', 'switch', 'router']):
            return True

        # Hostname-like patterns (letters, numbers, dashes)
        import re
        if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]{1,63}$', value):
            # Not an IP, not a MAC, not a serial
            if not re.match(r'^\d+\.\d+\.\d+\.\d+$', value):  # Not IP
                if not re.match(
                        r'^[a-fA-F0-9]{2}:[a-fA-F0-9]{2}:[a-fA-F0-9]{2}:[a-fA-F0-9]{2}:[a-fA-F0-9]{2}:[a-fA-F0-9]{2}$',
                        value):  # Not MAC
                    if not re.match(r'^[A-Z0-9]{10,}$', value):  # Not likely a serial
                        return True

        return False

    def _could_be_version(self, value):
        return True
        """Relaxed version detection"""
        if not value:
            return False

        # Version patterns
        import re
        version_patterns = [
            r'\d+\.\d+',  # 17.9
            r'\d+\.\d+\.\d+',  # 17.9.6
            r'\d+\.\d+\.\d+[a-zA-Z]',  # 17.9.6a
            r'[vV]\d+',  # v17
        ]

        for pattern in version_patterns:
            if re.search(pattern, value):
                return True

        return False

    def _could_be_serial(self, value):
        return True
        """Relaxed serial detection"""
        if not value or len(value) < 6:
            return False

        # Serial patterns - typically alphanumeric, 8+ chars
        import re
        if re.match(r'^[A-Z0-9]{8,}$', value):
            return True

        # More flexible serial patterns
        if re.match(r'^[A-Z]{2,3}[0-9]{6,}[A-Z0-9]*$', value):
            return True

        return False

    def _could_be_model(self, value):
        return True
        """Relaxed model detection"""
        if not value or len(value) < 2:
            return False

        # Model patterns
        import re
        model_patterns = [
            r'^[A-Z]+\d+[A-Z]*$',  # C9407R, ASR1000
            r'^\d+[A-Z]+$',  # 3850X
            r'^[A-Z]+-\d+',  # ASR-1000
        ]

        for pattern in model_patterns:
            if re.match(pattern, value):
                return True

        # Special cases
        if any(keyword in value.upper() for keyword in ['CATALYST', 'ASR', 'ISR', 'NEXUS', 'SWITCH', 'ROUTER']):
            return True

        return False

    def _extract_from_field_analysis(self, field_analysis):
        """Extract from the field_analysis structure"""
        extracted = []

        print(f"📊 Processing {len(field_analysis)} fields from field_analysis")

        for field_name, field_info in field_analysis.items():
            if not isinstance(field_info, dict):
                continue

            value = field_info.get('value', '')
            non_empty = field_info.get('non_empty', False)
            potential_mapping = field_info.get('potential_mapping', 'unknown')

            print(f"🔍 Field: {field_name}")
            print(f"   Value: '{value}'")
            print(f"   Non-empty: {non_empty}")
            print(f"   Potential mapping: {potential_mapping}")

            # Skip empty fields
            if not non_empty or not value or not value.strip():
                print(f"   ⏭️  Skipping empty field")
                continue

            clean_value = str(value).strip()

            # Use the potential_mapping as a hint, but still validate
            field_assigned = False

            if potential_mapping == 'hostname' and self._looks_like_hostname(clean_value):
                if not self._device_info.hostname:
                    self._device_info.hostname = clean_value
                    extracted.append(f"hostname='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Set hostname: '{clean_value}'")
                else:
                    print(f"   ⏭️  Hostname already set to '{self._device_info.hostname}'")

            elif potential_mapping == 'software_version' and self._looks_like_version(clean_value):
                if not self._device_info.version:
                    self._device_info.version = clean_value
                    extracted.append(f"version='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Set version: '{clean_value}'")
                else:
                    print(f"   ⏭️  Version already set to '{self._device_info.version}'")

            elif potential_mapping == 'serial_number' and self._looks_like_serial(clean_value):
                if not self._device_info.serial_number:
                    self._device_info.serial_number = clean_value
                    extracted.append(f"serial='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Set serial: '{clean_value}'")
                else:
                    print(f"   ⏭️  Serial already set to '{self._device_info.serial_number}'")

            elif potential_mapping == 'model' and self._looks_like_model(clean_value):
                if not self._device_info.model:
                    self._device_info.model = clean_value
                    extracted.append(f"model='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Set model: '{clean_value}'")
                else:
                    print(f"   ⏭️  Model already set to '{self._device_info.model}'")

            # If potential_mapping didn't work, try content-based detection
            if not field_assigned:
                print(f"   🔍 Potential mapping '{potential_mapping}' didn't work, trying content-based detection")

                if self._looks_like_hostname(clean_value) and not self._device_info.hostname:
                    self._device_info.hostname = clean_value
                    extracted.append(f"hostname='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Content-based: Set hostname: '{clean_value}'")
                elif self._looks_like_version(clean_value) and not self._device_info.version:
                    self._device_info.version = clean_value
                    extracted.append(f"version='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Content-based: Set version: '{clean_value}'")
                elif self._looks_like_serial(clean_value) and not self._device_info.serial_number:
                    self._device_info.serial_number = clean_value
                    extracted.append(f"serial='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Content-based: Set serial: '{clean_value}'")
                elif self._looks_like_model(clean_value) and not self._device_info.model:
                    self._device_info.model = clean_value
                    extracted.append(f"model='{clean_value}'")
                    field_assigned = True
                    print(f"   ✅ Content-based: Set model: '{clean_value}'")

            if not field_assigned:
                print(f"   ❌ Could not assign field '{field_name}' = '{clean_value}'")

        print(f"\n🎯 Field analysis extraction complete:")
        print(f"   Total fields processed: {len(field_analysis)}")
        print(f"   Fields successfully extracted: {len(extracted)}")
        print(f"   Extracted: {extracted}")

        return len(extracted) > 0

    def _extract_from_legacy_structure(self, textfsm_results):
        """Extract from legacy structure (records/parsed_data/raw_rows)"""
        data = None

        for key in ['records', 'parsed_data', 'raw_rows']:
            candidate = textfsm_results.get(key, [])
            if candidate and len(candidate) > 0:
                data = candidate[0]
                break

        if not data or not isinstance(data, dict):
            print(f"❌ No valid legacy data found")
            return False

        print(f"📊 Using legacy structure with {len(data)} fields")

        extracted = []
        for field, value in data.items():
            clean_val = None
            if isinstance(value, list) and value:
                clean_val = str(value[0]).strip()
            elif isinstance(value, str):
                clean_val = value.strip()
            elif value:
                clean_val = str(value).strip()

            if not clean_val:
                continue

            field_assigned = False

            if self._looks_like_hostname(clean_val) and not self._device_info.hostname:
                self._device_info.hostname = clean_val
                extracted.append(f"hostname='{clean_val}'")
                field_assigned = True
            elif self._looks_like_version(clean_val) and not self._device_info.version:
                self._device_info.version = clean_val
                extracted.append(f"version='{clean_val}'")
                field_assigned = True
            elif self._looks_like_serial(clean_val) and not self._device_info.serial_number:
                self._device_info.serial_number = clean_val
                extracted.append(f"serial='{clean_val}'")
                field_assigned = True
            elif self._looks_like_model(clean_val) and not self._device_info.model:
                self._device_info.model = clean_val
                extracted.append(f"model='{clean_val}'")
                field_assigned = True

        return len(extracted) > 0



    def _looks_like_hostname(self, value):
        return (len(value) < 50 and
                not '.' in value and
                not any(char in value for char in '/@#$%'))

    def _looks_like_version(self, value):
        return bool(re.match(r'^\d+\.\d+', value))

    def _looks_like_serial(self, value):
        return (len(value) > 6 and
                value.isalnum() and
                not value.isdigit())

    def _looks_like_model(self, value):
        return (len(value) < 30 and
                any(char.isdigit() for char in value) and
                any(char.isalpha() for char in value))
    def _analyze_textfsm_fields(self, parsed_data):
        """Analyze TextFSM fields for mapping issues"""
        if not parsed_data or len(parsed_data) == 0:
            return {}

        sample_record = parsed_data[0]
        field_analysis = {}

        for field_name, field_value in sample_record.items():
            field_analysis[field_name] = {
                'value': field_value,
                'type': type(field_value).__name__,
                'non_empty': bool(field_value and str(field_value).strip()),
                'potential_mapping': self._guess_field_purpose(field_name, field_value)
            }

        return field_analysis

    def _guess_field_purpose(self, field_name, field_value):
        """Universal field purpose guessing based on field name patterns"""
        field_upper = field_name.upper()
        value_str = str(field_value).lower() if field_value else ""

        # Hostname patterns
        if any(pattern in field_upper for pattern in ['HOSTNAME', 'HOST_NAME', 'DEVICE_NAME']):
            return 'hostname'

        # Version patterns
        if any(pattern in field_upper for pattern in ['VERSION', 'OS_VERSION', 'SW_VERSION', 'JUNOS_VERSION']):
            return 'software_version'

        # Model/Hardware patterns
        if any(pattern in field_upper for pattern in ['MODEL', 'HARDWARE', 'PLATFORM', 'SOFTWARE_IMAGE']):
            return 'model'

        # Serial patterns
        if any(pattern in field_upper for pattern in ['SERIAL', 'SERIAL_NUMBER', 'CHASSIS_SERIAL']):
            return 'serial_number'

        # Uptime patterns
        if 'UPTIME' in field_upper:
            return 'uptime'

        # Memory patterns
        if any(pattern in field_upper for pattern in ['MEMORY', 'RAM']):
            return 'memory_info'

        # MAC address patterns
        if any(pattern in field_upper for pattern in ['MAC', 'MAC_ADDRESS', 'SYS_MAC']):
            return 'mac_address'

        # Version-like values (contains dots and numbers)
        if field_value and re.match(r'^\d+\.\d+', str(field_value)):
            return 'possible_version'

        # Serial-like values (alphanumeric strings)
        if field_value and re.match(r'^[A-Za-z0-9]{8,}$', str(field_value)):
            return 'possible_serial'

        # Vendor/manufacturer info
        if field_value and any(vendor in value_str for vendor in ['cisco', 'arista', 'juniper', 'hp']):
            return 'possible_vendor_info'

        return 'unknown'

    def _add_enhanced_metadata(self):
        """Add enhanced metadata fields"""
        # Add netmiko driver name
        netmiko_driver = NetmikoDriverMap.get_netmiko_driver(self._device_info.device_type)
        self._device_info.additional_info['netmiko_driver'] = netmiko_driver

        # Add standardized vendor name
        vendor = NetmikoDriverMap.get_vendor_name(self._device_info.device_type)
        self._device_info.additional_info['vendor'] = vendor

        # ================================================================
        # FIX: Validate hostname - reject obvious parsing errors
        # ================================================================
        invalid_hostnames = {
            'host-name', 'hostname', 'name', 'device', 'switch', 'router',
            'description', 'chassis', 'system', 'none', 'null', 'unknown'
        }

        if self._device_info.hostname and self._device_info.hostname.lower() in invalid_hostnames:
            # Bad parse - clear it so we fall back to yaml_display_name
            self._device_info.hostname = None

        # ================================================================
        # Set display name with proper fallback order
        # ================================================================
        yaml_display_name = self._device_info.additional_info.get('yaml_display_name')
        if yaml_display_name:
            display_name = yaml_display_name
        elif self._device_info.hostname:
            display_name = self._device_info.hostname
        else:
            display_name = self._device_info.host

        self._device_info.additional_info['display_name'] = display_name

        # Store connection info
        self._device_info.additional_info['host'] = self._device_info.host
        self._device_info.additional_info['port'] = str(self._device_info.port)

    def to_structured_output(self):
        """Convert to structured output format for compatibility"""
        netmiko_driver = self._device_info.additional_info.get('netmiko_driver', 'generic')
        vendor = self._device_info.additional_info.get('vendor', 'Unknown')
        display_name = self._device_info.additional_info.get('display_name', self._device_info.host)

        structured = {
            'DeviceType': netmiko_driver,
            'Model': self._device_info.model or 'Unknown',
            'SerialNumber': self._device_info.serial_number or 'Unknown',
            'SoftwareVersion': self._device_info.version or 'Unknown',
            'Vendor': vendor,
            'display_name': display_name,
            'host': self._device_info.host,
            'port': str(self._device_info.port),
            'detected_prompt': self._device_info.detected_prompt
        }

        # Include TextFSM template selection details
        textfsm_info = {}
        for cmd_output_key in self._device_info.command_outputs.keys():
            if cmd_output_key.endswith('_textfsm'):
                textfsm_data = self._device_info.command_outputs[cmd_output_key]
                if textfsm_data:
                    textfsm_info = {
                        'template_used': textfsm_data.get('template_name', 'Unknown'),
                        'template_score': textfsm_data.get('score', 0),
                        'filter_used': textfsm_data.get('filter_used', 'Unknown'),
                        'filter_rank': textfsm_data.get('filter_rank', 0),
                        'parsed_data': textfsm_data.get('parsed_data', []),
                        'field_analysis': textfsm_data.get('field_analysis', {})
                    }
                break

        if textfsm_info:
            structured['textfsm_info'] = textfsm_info

        return structured

    # ===== ORIGINAL METHODS PRESERVED FOR BACKWARDS COMPATIBILITY =====

    def detect_prompt(self):
        """Super simple prompt detection - send newline, take last line as prompt"""
        if self._debug:
            print("Starting simple prompt detection...")

        # Record current buffer position
        start_position = len(''.join(self._output_buffer))

        # Send newline
        if self._debug:
            print("Sending newline to get prompt...")

        try:
            self._ssh_client.execute_command("\n")
            time.sleep(1)  # Give it a moment

            # Get everything after our starting position
            current_buffer = ''.join(self._output_buffer)
            new_output = current_buffer[start_position:].strip()
            print(new_output)

            if new_output:
                # Split by lines and take the last non-empty line
                lines = [line.strip() for line in new_output.split('\n') if line.strip()]
                if lines:
                    prompt = lines[-1]
                    if self._debug:
                        print(f"Detected prompt: '{prompt}'")

                    # Set it on the SSH client
                    try:
                        self._ssh_client.set_expect_prompt(prompt)
                    except Exception as e:
                        if self._debug:
                            print(f"Error setting expect prompt: {e}")

                    return prompt

            if self._debug:
                print("No new output after newline, trying fallback...")

        except Exception as e:
            if self._debug:
                print(f"Error sending newline: {e}")

        # Fallback: look at the very end of existing buffer
        # Fallback: look at the very end of existing buffer
        current_buffer = ''.join(self._output_buffer)
        if current_buffer:
            lines = [line.strip() for line in current_buffer.split('\n') if line.strip()]
            if lines:
                # Take the last non-whitespace line - that's the prompt
                prompt = lines[-1]
                if self._debug:
                    print(f"Using last line from buffer as prompt: '{prompt}'")
                try:
                    self._ssh_client.set_expect_prompt(prompt)
                except:
                    pass
                return prompt
        # Ultimate fallback
        fallback = "#"
        if self._debug:
            print(f"Using ultimate fallback: '{fallback}'")
        return fallback
    def safe_execute_command(self, command, timeout_ms=3000, retries=1):
        """Execute command safely with timeout and retry logic"""
        for attempt in range(retries + 1):
            try:
                # Record the current buffer length to track only new output
                start_position = len(''.join(self._output_buffer))

                if self._debug:
                    print("Executing command (attempt {}/{}): '{}'".format(attempt + 1, retries + 1, command))
                    print("Buffer position before command: {}".format(start_position))

                # Execute the command
                self._ssh_client.execute_command(command)

                # Wait for initial response
                time.sleep(0.3)

                # Get current position
                current_buffer = ''.join(self._output_buffer)
                current_position = len(current_buffer)
                if self._debug:
                    print("Buffer position after initial wait: {}".format(current_position))

                # Only wait longer if we need to - up to max timeout
                start_time = time.time()
                end_time = start_time + (timeout_ms / 1000)

                # Track buffer changes
                last_known_length = current_position
                last_change_time = time.time()

                while time.time() < end_time:
                    # Check if buffer has changed
                    current_buffer = ''.join(self._output_buffer)
                    current_position = len(current_buffer)

                    if current_position > last_known_length:
                        # Buffer has grown, update last change time
                        last_known_length = current_position
                        last_change_time = time.time()
                    elif (time.time() - last_change_time > 0.3 and
                          time.time() - start_time > 0.5):
                        # Buffer hasn't changed for 300ms and we've waited at least 500ms total
                        if self._debug:
                            print("Command appears complete (no buffer change)")
                        break

                    # Check if output ends with the prompt (if we know it)
                    if self._device_info.detected_prompt:
                        if current_buffer.rstrip().endswith(self._device_info.detected_prompt):
                            if self._debug:
                                print("Command appears complete (prompt detected)")
                            break

                    # Short sleep to prevent CPU spinning
                    time.sleep(0.05)

                # Extract only the new output
                result = ""
                current_buffer = ''.join(self._output_buffer)
                if len(current_buffer) > start_position:
                    result = current_buffer[start_position:]

                if self._debug:
                    print("Command complete, received {} bytes of output".format(len(result)))
                return result

            except Exception as e:
                if self._debug:
                    print("Error executing command: {}".format(str(e)))

                # If we've reached the maximum number of retries, return the error
                if attempt == retries:
                    return "ERROR: {}".format(str(e))

                # Otherwise wait and try again
                time.sleep(1)

                # Try to recover if this is a channel issue
                if "channel" in str(e).lower() and attempt < retries:
                    if self._debug:
                        print("Detected channel issue, attempting to reconnect...")
                    try:
                        self._ssh_client.disconnect()
                        time.sleep(1)
                        self._ssh_client.connect()
                    except Exception as reconnect_ex:
                        if self._debug:
                            print("Reconnection attempt failed: {}".format(str(reconnect_ex)))

        return "ERROR: Max retries exceeded"

    def identify_vendor_from_output(self, output):
        """Enhanced vendor detection with more specific patterns matching TextFSM database"""
        output_lower = output.lower()

        # More specific detection rules based on actual TextFSM template names
        # Order matters - most specific first
        detection_rules = [
            # Cisco variants (most specific first)
            (DeviceType.CiscoASA, ['adaptive security appliance', 'cisco asa']),
            (DeviceType.CiscoNXOS, ['nx-os', 'nexus operating system', 'cisco nexus']),
            (DeviceType.CiscoIOS, ['cisco ios', 'cisco internetwork operating system', 'catalyst l3 switch', 'ios-xe']),

            # Other vendors
            (DeviceType.AristaEOS, ['arista', 'arista networks', 'dcs-', 'eos version']),
            (DeviceType.JuniperJunOS, ['juniper networks', 'junos', 'juniper']),
            (DeviceType.HPProCurve, ['hp ', 'hewlett-packard', 'procurve', 'aruba']),
            (DeviceType.FortiOS, ['fortinet', 'fortigate', 'fortios']),
            (DeviceType.PaloAltoOS, ['palo alto networks', 'pan-os']),
            (DeviceType.Linux, ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'fedora']),
            (DeviceType.FreeBSD, ['freebsd']),
            (DeviceType.Windows, ['windows', 'microsoft'])
        ]

        for device_type, patterns in detection_rules:
            if any(pattern in output_lower for pattern in patterns):
                if self._debug:
                    matching_pattern = next(pattern for pattern in patterns if pattern in output_lower)
                    print(f"Vendor detection: {device_type.name} (matched: '{matching_pattern}')")
                return device_type

        # Fallback pattern matching for model numbers
        if re.search(r'\bws-c\d{4}\b', output_lower) or re.search(r'\bc\d{4}\b', output_lower):
            return DeviceType.CiscoIOS

        if re.search(r'\bn\d{4}\b', output_lower) or "nexus" in output_lower:
            return DeviceType.CiscoNXOS

        return DeviceType.Unknown

    def extract_device_details(self):

        """Extract detailed information from command outputs"""
        # Get the full output buffer content
        output = ''.join(self._output_buffer)

        # Extract hostname
        hostname_patterns = {
            DeviceType.CiscoIOS: r'hostname\s+([^\s\r\n]+)',
            DeviceType.CiscoNXOS: r'hostname\s+([^\s\r\n]+)',
            DeviceType.CiscoASA: r'hostname\s+([^\s\r\n]+)',
            DeviceType.AristaEOS: r'hostname\s+([^\s\r\n]+)',
            DeviceType.JuniperJunOS: r'host-name\s+([^\s\r\n;]+)',
            DeviceType.Linux: r'Hostname:[^\n]*(\S+)[\r\n]',
            DeviceType.GenericUnix: r'([A-Za-z0-9\-]+)[@][^:]+:'
        }

        if self._device_info.device_type in hostname_patterns:
            pattern = hostname_patterns[self._device_info.device_type]
            match = re.search(pattern, output, re.IGNORECASE)
            if match and match.group(1):
                self._device_info.hostname = match.group(1)

        # If we couldn't extract a hostname, use the prompt as a fallback
        if not self._device_info.hostname and self._device_info.detected_prompt:
            # Extract hostname from prompt (typical format username@hostname or hostname#)
            prompt_hostname_match = re.match(
                r'^([A-Za-z0-9\-._]+)(?:[>#]|$)',
                self._device_info.detected_prompt
            )
            if prompt_hostname_match and prompt_hostname_match.group(1):
                self._device_info.hostname = prompt_hostname_match.group(1)

        # Extract serial number - common pattern across many devices
        serial_match = re.search(r'[Ss]erial\s*[Nn]umber\s*:?\s*([A-Za-z0-9\-]+)', output, re.IGNORECASE)
        if serial_match and serial_match.group(1):
            self._device_info.serial_number = serial_match.group(1).strip()

        # Extract more details based on device type
        if self._device_info.device_type == DeviceType.CiscoIOS:
            # Extract version from "show version" output
            version_match = re.search(r'(?:IOS|Software).+?Version\s+([^,\s\r\n]+)', output, re.IGNORECASE)
            if version_match and version_match.group(1):
                self._device_info.version = version_match.group(1).strip()

            # Extract model information
            model_match = re.search(r'[Cc]isco\s+([A-Za-z0-9\-]+)(?:\s+[^\n]*?)(?:processor|chassis|router|switch)',
                                    output,
                                    re.DOTALL)
            if model_match and model_match.group(1):
                self._device_info.model = model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.CiscoNXOS:
            # Extract version for NX-OS
            nxos_version_match = re.search(r'NXOS:\s+version\s+([^,\s\r\n]+)', output, re.IGNORECASE)
            if nxos_version_match and nxos_version_match.group(1):
                self._device_info.version = nxos_version_match.group(1).strip()

            # Extract model for Nexus
            nxos_model_match = re.search(r'cisco\s+Nexus\s+([^\s]+)', output, re.IGNORECASE)
            if nxos_model_match and nxos_model_match.group(1):
                self._device_info.model = "Nexus " + nxos_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.CiscoASA:
            # Extract version for ASA
            asa_version_match = re.search(r'Adaptive Security Appliance.*?Version\s+([^,\s\r\n]+)', output,
                                          re.IGNORECASE)
            if asa_version_match and asa_version_match.group(1):
                self._device_info.version = asa_version_match.group(1).strip()

            # Extract model for ASA
            asa_model_match = re.search(r'Hardware:\s+([^,\r\n]+)', output, re.IGNORECASE)
            if asa_model_match and asa_model_match.group(1):
                self._device_info.model = asa_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.AristaEOS:
            # Extract version for Arista EOS
            arista_version_match = re.search(r'EOS\s+version\s+([^,\s\r\n]+)', output, re.IGNORECASE)
            if arista_version_match and arista_version_match.group(1):
                self._device_info.version = arista_version_match.group(1).strip()

            # Extract model for Arista switches
            arista_model_match = re.search(r'Arista\s+([A-Za-z0-9\-]+)', output, re.IGNORECASE)
            if arista_model_match and arista_model_match.group(1):
                self._device_info.model = arista_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.JuniperJunOS:
            # Extract version for JunOS
            junos_version_match = re.search(r'JUNOS\s+([^,\s\r\n\]]+)', output, re.IGNORECASE)
            if junos_version_match and junos_version_match.group(1):
                self._device_info.version = junos_version_match.group(1).strip()

            # Extract model for Juniper
            junos_model_match = re.search(r'Model:\s*([^\r\n]+)', output, re.IGNORECASE)
            if junos_model_match and junos_model_match.group(1):
                self._device_info.model = junos_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.HPProCurve:
            # Extract version for HP ProCurve
            hp_version_match = re.search(r'Software\s+revision\s*:?\s*([^\r\n]+)', output, re.IGNORECASE)
            if hp_version_match and hp_version_match.group(1):
                self._device_info.version = hp_version_match.group(1).strip()

            # Extract model for HP
            hp_model_match = re.search(r'[Ss]witch\s+([A-Za-z0-9\-]+)', output)
            if hp_model_match and hp_model_match.group(1):
                self._device_info.model = hp_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.FortiOS:
            # Extract version for FortiOS
            forti_version_match = re.search(r'Version:\s*([^\r\n]+)', output, re.IGNORECASE)
            if forti_version_match and forti_version_match.group(1):
                self._device_info.version = forti_version_match.group(1).strip()

            # Extract model for FortiGate
            forti_model_match = re.search(r'FortiGate-([A-Za-z0-9\-]+)', output, re.IGNORECASE)
            if forti_model_match and forti_model_match.group(1):
                self._device_info.model = "FortiGate-" + forti_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.PaloAltoOS:
            # Extract version for PAN-OS
            palo_version_match = re.search(r'sw-version:\s*([^\r\n]+)', output, re.IGNORECASE)
            if palo_version_match and palo_version_match.group(1):
                self._device_info.version = palo_version_match.group(1).strip()

            # Extract model for Palo Alto
            palo_model_match = re.search(r'model:\s*([^\r\n]+)', output, re.IGNORECASE)
            if palo_model_match and palo_model_match.group(1):
                self._device_info.model = palo_model_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.Linux:
            # Extract Linux distribution and version
            linux_version_match = re.search(r'PRETTY_NAME="([^"]+)"', output, re.IGNORECASE)
            if linux_version_match and linux_version_match.group(1):
                self._device_info.version = linux_version_match.group(1).strip()
            else:
                # Try uname output
                uname_match = re.search(r'Linux\s+\S+\s+([^\s]+)', output)
                if uname_match and uname_match.group(1):
                    self._device_info.version = uname_match.group(1).strip()

            # For Linux, we might extract CPU information
            cpu_info_match = re.search(r'model name\s*:\s*([^\r\n]+)', output, re.IGNORECASE)
            if cpu_info_match and cpu_info_match.group(1):
                self._device_info.cpu_info = cpu_info_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.FreeBSD:
            # Extract FreeBSD version
            freebsd_version_match = re.search(r'FreeBSD\s+\S+\s+([^\s]+)', output)
            if freebsd_version_match and freebsd_version_match.group(1):
                self._device_info.version = freebsd_version_match.group(1).strip()

        elif self._device_info.device_type == DeviceType.Windows:
            # Extract Windows version
            windows_version_match = re.search(r'OS Name:\s*([^\r\n]+)', output, re.IGNORECASE)
            if windows_version_match and windows_version_match.group(1):
                self._device_info.version = windows_version_match.group(1).strip()

            # Extract Windows model
            windows_model_match = re.search(r'System Model:\s*([^\r\n]+)', output, re.IGNORECASE)
            if windows_model_match and windows_model_match.group(1):
                self._device_info.model = windows_model_match.group(1).strip()

        # Extract IP address information from outputs if available
        ip_addresses = []

        # Look for IP addresses in output
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b'
        ip_matches = re.finditer(ip_pattern, output)

        # Filter to get likely management IPs (not every IP in the output)
        for match in ip_matches:
            ip = match.group(0)

            # Skip obviously invalid IPs
            if ip.startswith('0.') or ip.startswith('255.'):
                continue

            # Check context - look for lines with "ip address" or similar
            line_start = max(0, match.start() - 50)
            line_end = min(len(output), match.end() + 50)
            context = output[line_start:line_end].lower()

            if any(term in context for term in ['ip address', 'management', 'vlan', 'interface']):
                if ip not in ip_addresses:
                    ip_addresses.append(ip)

        # Add up to 5 most likely IPs, but don't overload with too many
        self._device_info.ip_addresses.extend(ip_addresses[:5])

        # Extract interface information for network devices
        if self._device_info.device_type in [DeviceType.CiscoIOS, DeviceType.CiscoNXOS,
                                             DeviceType.CiscoASA, DeviceType.AristaEOS,
                                             DeviceType.JuniperJunOS]:
            # Look for interface patterns like "GigabitEthernet0/0 is up, line protocol is up"
            interface_matches = re.finditer(r'([A-Za-z0-9/\-\.]+)\s+is\s+(up|down|administratively down)', output)
            for match in interface_matches:
                interface_name = match.group(1)
                interface_status = match.group(2)

                # Get IP if available (for this interface)
                ip_match = re.search(f'{re.escape(interface_name)}.*?({ip_pattern})', output, re.DOTALL)
                interface_info = "Status: {}".format(interface_status)

                if ip_match:
                    interface_info += ", IP: {}".format(ip_match.group(1))

                self._device_info.interfaces[interface_name] = interface_info