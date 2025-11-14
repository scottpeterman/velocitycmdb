#!/usr/bin/env python3
"""
PyQt6 Network Job Runner
Desktop frontend for batch SSH automation jobs
"""

import sys
import os
import json
import yaml
import subprocess
import threading
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QWidget, QPushButton, QLabel, QComboBox, QLineEdit, QTextEdit,
    QProgressBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QGroupBox, QCheckBox, QSpinBox, QFileDialog, QMessageBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QFont, QTextCursor, QColor


class DeviceFilter:
    """Handles device filtering based on query criteria"""

    def __init__(self, sessions_data: List[Dict]):
        self.sessions_data = sessions_data
        self.last_filter_stats = {}

    def _match_pattern(self, text: str, pattern: str) -> bool:
        """
        Enhanced pattern matching with wildcard support
        Supports: exact match, wildcard (*), case-insensitive
        """
        if not pattern or not text:
            return not pattern  # Empty pattern matches empty text

        # Convert to lowercase for case-insensitive matching
        text = text.lower()
        pattern = pattern.lower()

        # Handle simple wildcard patterns
        if '*' in pattern:
            # Convert shell-style wildcards to regex
            regex_pattern = pattern.replace('*', '.*')
            return re.match(f'^{regex_pattern}$', text) is not None
        else:
            # Exact match or substring match
            return pattern in text

    def filter_devices(self, folder_pattern: str = None, name_pattern: str = None,
                       vendor_pattern: str = None, device_type: str = None) -> List[Dict]:
        """Filter devices based on multiple criteria with robust error handling"""
        matched_devices = []

        # Initialize statistics
        stats = {
            'total_folders': 0,
            'total_devices': 0,
            'matched_devices': 0,
            'folders_processed': 0,
            'filter_reasons': {
                'folder': 0,
                'name': 0,
                'vendor': 0,
                'device_type': 0
            }
        }

        try:
            if not self.sessions_data:
                raise ValueError("No session data available for filtering")

            for folder_group in self.sessions_data:
                stats['total_folders'] += 1

                if not isinstance(folder_group, dict):
                    print(f"Warning: Invalid folder group format: {type(folder_group)}")
                    continue

                folder_name = folder_group.get('folder_name', '')
                sessions = folder_group.get('sessions', [])

                # Filter by folder pattern
                if folder_pattern and not self._match_pattern(folder_name, folder_pattern):
                    stats['filter_reasons']['folder'] += len(sessions)
                    continue

                stats['folders_processed'] += 1

                for device in sessions:
                    stats['total_devices'] += 1

                    if not isinstance(device, dict):
                        print(f"Warning: Invalid device format in folder '{folder_name}': {type(device)}")
                        continue

                    # Filter by display name pattern
                    if name_pattern:
                        device_name = device.get('display_name', '')
                        if not self._match_pattern(device_name, name_pattern):
                            stats['filter_reasons']['name'] += 1
                            continue

                    # Filter by vendor pattern
                    if vendor_pattern:
                        vendor = device.get('Vendor', '')
                        if not self._match_pattern(vendor, vendor_pattern):
                            stats['filter_reasons']['vendor'] += 1
                            continue

                    # Filter by device type
                    if device_type:
                        dev_type = device.get('DeviceType', '')
                        if not self._match_pattern(dev_type, device_type):
                            stats['filter_reasons']['device_type'] += 1
                            continue

                    # Add folder context to device info
                    device_with_context = device.copy()
                    device_with_context['folder_name'] = folder_name
                    matched_devices.append(device_with_context)
                    stats['matched_devices'] += 1

        except Exception as e:
            print(f"Error during device filtering: {str(e)}")
            raise

        # Store statistics for later use
        self.last_filter_stats = stats
        return matched_devices

    def get_filter_summary(self) -> str:
        """Get a summary of the last filtering operation"""
        if not self.last_filter_stats:
            return "No filtering performed yet"

        stats = self.last_filter_stats
        summary = [
            f"Total devices: {stats['total_devices']}",
            f"Matched devices: {stats['matched_devices']}",
            f"Folders processed: {stats['folders_processed']}/{stats['total_folders']}"
        ]

        if any(stats['filter_reasons'].values()):
            filtered = []
            for reason, count in stats['filter_reasons'].items():
                if count > 0:
                    filtered.append(f"{count} by {reason}")
            if filtered:
                summary.append(f"Filtered out: {', '.join(filtered)}")

        return " | ".join(summary)

    def get_available_values(self) -> Dict[str, set]:
        """Get all available values for each filterable field"""
        values = {
            'folders': set(),
            'vendors': set(),
            'device_types': set(),
            'device_names': set()
        }

        try:
            for folder_group in self.sessions_data:
                folder_name = folder_group.get('folder_name', '')
                if folder_name:
                    values['folders'].add(folder_name)

                for device in folder_group.get('sessions', []):
                    if isinstance(device, dict):
                        vendor = device.get('Vendor', '')
                        if vendor:
                            values['vendors'].add(vendor)

                        dev_type = device.get('DeviceType', '')
                        if dev_type:
                            values['device_types'].add(dev_type)

                        name = device.get('display_name', '')
                        if name:
                            values['device_names'].add(name)

        except Exception as e:
            print(f"Error getting available values: {str(e)}")

        return values


class JobExecutorThread(QThread):
    """Thread for executing batch SSH jobs"""

    progress_update = pyqtSignal(str)
    status_update = pyqtSignal(str, str)  # device_name, status
    finished_signal = pyqtSignal(dict)  # execution summary

    def __init__(self, job_config: Dict[str, Any]):
        super().__init__()
        self.job_config = job_config
        self.is_cancelled = False

    def cancel(self):
        """Cancel the running job"""
        self.is_cancelled = True

    def _escape_shell_arg(self, arg: str) -> str:
        """Escape shell arguments properly for different platforms"""
        import shlex
        return shlex.quote(arg)

    def _get_script_args_mapping(self, script_name: str) -> Dict[str, str]:
        """Get the correct argument names for different batch scripts"""
        # Map of script types to their argument variations
        script_args = {
            'batch_spn.py': {
                'verbose': None,  # batch_spn.py doesn't support --verbose
                'dry_run': '--dry-run',
                'max_workers': '--max-workers'
            },
            'batch_spn_single.py': {
                'verbose': '--verbose',
                'dry_run': '--dry-run',
                'max_workers': None  # Single threaded doesn't use workers
            },
            'batch_spn_concurrent.py': {
                'verbose': '--verbose',
                'dry_run': '--dry-run',
                'max_workers': '--max-processes'
            }
        }

        # Get the base script name without path
        base_name = os.path.basename(script_name)

        # Return mapping for the script, or default mapping
        return script_args.get(base_name, script_args['batch_spn.py'])

    def run(self):
        """Execute the batch job with enhanced error handling"""
        try:
            # Validate job configuration
            required_fields = ['batch_script', 'yaml_file', 'commands', 'output_dir']
            for field in required_fields:
                if not self.job_config.get(field):
                    raise ValueError(f"Missing required field: {field}")

            # Get script-specific argument mapping
            script_name = os.path.basename(self.job_config['batch_script'])
            arg_mapping = self._get_script_args_mapping(script_name)

            # Debug logging for argument mapping
            self.progress_update.emit(f"Script: {script_name}, Verbose supported: {arg_mapping['verbose'] is not None}")

            # Build command
            cmd_args = [
                sys.executable,
                self.job_config['batch_script'],
                self.job_config['yaml_file']
            ]

            # Add filters (only if they have values) - with validation and cleaning
            filters_to_add = [
                ('--folder', self.job_config.get('folder_filter')),
                ('--name', self.job_config.get('name_filter')),
                ('--vendor', self.job_config.get('vendor_filter')),
                ('--device-type', self.job_config.get('device_type_filter'))
            ]

            for filter_name, filter_value in filters_to_add:
                if filter_value:
                    # Clean the filter value
                    cleaned_value = filter_value.strip()
                    if cleaned_value:
                        cmd_args.extend([filter_name, cleaned_value])
                        self.progress_update.emit(f"Added filter: {filter_name} = '{cleaned_value}'")

            # Add execution parameters
            cmd_args.extend(['-c', self.job_config['commands']])
            cmd_args.extend(['-o', self.job_config['output_dir']])

            # Add max workers if supported by this script
            if self.job_config.get('max_workers') and arg_mapping['max_workers']:
                cmd_args.extend([arg_mapping['max_workers'], str(self.job_config['max_workers'])])

            # Add verbose flag if supported by this script
            if self.job_config.get('verbose') and arg_mapping['verbose']:
                cmd_args.append(arg_mapping['verbose'])

            # Add dry run flag if supported
            if self.job_config.get('dry_run') and arg_mapping['dry_run']:
                cmd_args.append(arg_mapping['dry_run'])

            # Set up environment variables for credentials
            env = os.environ.copy()

            # Get credential environment variables using the new system
            if 'credentials' in self.job_config:
                credential_vars = self.job_config['credentials']
                for var_name, var_value in credential_vars.items():
                    env[var_name] = var_value
                    self.progress_update.emit(f"Set environment variable: {var_name}")

            # Legacy support: check for individual credential fields
            legacy_credential_vars = [
                'SPN_USERNAME', 'SPN_PASSWORD', 'SPN_ENABLE_PASSWORD',
                'SSH_USERNAME', 'SSH_PASSWORD', 'SSH_ENABLE_PASSWORD',
                'NETMIKO_USERNAME', 'NETMIKO_PASSWORD', 'NETMIKO_SECRET'
            ]

            for var in legacy_credential_vars:
                if var in self.job_config:
                    env[var] = self.job_config[var]
                    self.progress_update.emit(f"Set environment variable: {var} (legacy)")

            # Execute process
            command_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd_args)
            self.progress_update.emit(f"Starting job: {command_str}")

            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env  # Pass the environment with credentials
            )

            # Monitor output
            while True:
                if self.is_cancelled:
                    try:
                        process.terminate()
                        process.wait(timeout=5)  # Wait up to 5 seconds
                    except subprocess.TimeoutExpired:
                        process.kill()  # Force kill if it doesn't terminate
                    self.progress_update.emit("Job cancelled by user")
                    return

                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break

                if output:
                    line = output.strip()
                    self.progress_update.emit(line)

                    # Parse status updates with improved parsing
                    try:
                        if '[SUCCESS]' in line or '[FAILED]' in line or '[ERROR]' in line:
                            # More robust parsing of status lines
                            if ']' in line:
                                parts = line.split(']', 2)
                                if len(parts) >= 2:
                                    status_part = parts[0] + ']'
                                    if '[SUCCESS]' in status_part:
                                        status = 'SUCCESS'
                                    elif '[FAILED]' in status_part:
                                        status = 'FAILED'
                                    elif '[ERROR]' in status_part:
                                        status = 'ERROR'
                                    else:
                                        continue

                                    # Extract device name
                                    if len(parts) >= 3:
                                        device_info = parts[2].strip()
                                        device_name = device_info.split(' ')[0] if device_info else 'unknown'
                                    else:
                                        device_name = 'unknown'

                                    self.status_update.emit(device_name, status)
                    except Exception as e:
                        # Don't let parsing errors stop the job
                        print(f"Error parsing status line: {e}")

            # Get final result
            stdout, stderr = process.communicate()

            if stderr:
                self.progress_update.emit(f"STDERR: {stderr}")

            # Create summary
            summary = {
                'return_code': process.returncode,
                'success': process.returncode == 0,
                'stdout': stdout,
                'stderr': stderr
            }

            self.finished_signal.emit(summary)

        except Exception as e:
            error_summary = {
                'return_code': -1,
                'success': False,
                'error': str(e)
            }
            self.finished_signal.emit(error_summary)


class CommandTemplateManager:
    """Manages command templates loaded from external file"""

    def __init__(self, template_file: str = "command_templates.json"):
        self.template_file = template_file
        self.templates = self.load_templates()

    def load_templates(self) -> Dict[str, Dict[str, str]]:
        """Load command templates from JSON file with error handling"""
        try:
            if os.path.exists(self.template_file):
                with open(self.template_file, 'r', encoding='utf-8') as f:
                    templates = json.load(f)

                # Validate template structure
                if not isinstance(templates, dict):
                    print("Warning: Template file should contain a dictionary")
                    return self._get_default_templates()

                # Validate each template
                valid_templates = {}
                for key, template in templates.items():
                    if isinstance(template, dict) and 'name' in template and 'command' in template:
                        valid_templates[key] = template
                    else:
                        print(f"Warning: Invalid template format for '{key}', skipping")

                return valid_templates if valid_templates else self._get_default_templates()
            else:
                # Create default template file
                default_templates = self._get_default_templates()
                self.save_templates(default_templates)
                return default_templates

        except json.JSONDecodeError as e:
            print(f"Error parsing template file: {e}")
            return self._get_default_templates()
        except Exception as e:
            print(f"Error loading templates: {e}")
            return self._get_default_templates()

    def _get_default_templates(self) -> Dict[str, Dict[str, str]]:
        """Get default command templates"""
        return {
            "version_check": {
                "name": "Version Check",
                "command": "show version",
                "description": "Get device version information"
            },
            "interface_status": {
                "name": "Interface Status",
                "command": "show ip interface brief",
                "description": "Show interface status"
            },
            "running_config": {
                "name": "Running Config",
                "command": "show running-config",
                "description": "Display running configuration"
            }
        }

    def save_templates(self, templates: Dict[str, Dict[str, str]]):
        """Save templates to file with error handling"""
        try:
            with open(self.template_file, 'w', encoding='utf-8') as f:
                json.dump(templates, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving templates: {e}")
            raise

    def get_template_names(self) -> List[str]:
        """Get list of template names for UI"""
        names = []
        for template in self.templates.values():
            if isinstance(template, dict) and 'name' in template:
                names.append(template['name'])
        return sorted(names)

    def get_template_by_name(self, name: str) -> Optional[Dict[str, str]]:
        """Get template by display name"""
        for template in self.templates.values():
            if isinstance(template, dict) and template.get('name') == name:
                return template
        return None


class NetworkJobRunner(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Job Runner")
        self.setGeometry(100, 100, 1200, 800)

        # Initialize components
        self.command_manager = CommandTemplateManager()
        self.sessions_data = []
        self.current_devices = []
        self.execution_thread = None
        self.device_filter = None

        # Setup UI
        self.setup_ui()
        self.load_default_settings()

    def setup_ui(self):
        """Setup the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Setup tabs
        self.setup_job_config_tab()
        self.setup_device_selection_tab()
        self.setup_execution_tab()
        self.setup_templates_tab()

    def setup_job_config_tab(self):
        """Setup job configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Session file selection
        session_group = QGroupBox("Session File")
        session_layout = QHBoxLayout(session_group)

        self.session_file_edit = QLineEdit()
        self.session_file_edit.setPlaceholderText("Select YAML session file...")
        session_layout.addWidget(self.session_file_edit)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_session_file)
        session_layout.addWidget(browse_btn)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self.load_session_file)
        session_layout.addWidget(load_btn)

        layout.addWidget(session_group)

        # Credentials section
        creds_group = QGroupBox("Credentials (Environment Variables)")
        creds_layout = QGridLayout(creds_group)

        creds_layout.addWidget(QLabel("Username:"), 0, 0)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Leave empty to use system env vars")
        creds_layout.addWidget(self.username_edit, 0, 1)

        creds_layout.addWidget(QLabel("Password:"), 0, 2)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Leave empty to use system env vars")
        creds_layout.addWidget(self.password_edit, 0, 3)

        creds_layout.addWidget(QLabel("Enable Password:"), 1, 0)
        self.enable_password_edit = QLineEdit()
        self.enable_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.enable_password_edit.setPlaceholderText("Leave empty to use system env vars")
        creds_layout.addWidget(self.enable_password_edit, 1, 1)

        show_passwords_check = QCheckBox("Show Passwords")
        show_passwords_check.toggled.connect(self.toggle_password_visibility)
        creds_layout.addWidget(show_passwords_check, 1, 2)

        # Credential system selection
        creds_layout.addWidget(QLabel("Credential System:"), 2, 0)
        self.credential_system_combo = QComboBox()
        self.credential_system_combo.addItems([
            "Auto-detect from script",
            "SSH_* variables (spn.py)",
            "SPN_* variables (legacy)",
            "Per-device CRED_* variables"
        ])
        self.credential_system_combo.currentTextChanged.connect(self.credential_system_changed)
        creds_layout.addWidget(self.credential_system_combo, 2, 1, 1, 2)

        # Environment variables info
        self.env_info_label = QLabel()
        self.env_info_label.setWordWrap(True)
        self.env_info_label.setStyleSheet("color: #666; font-style: italic; font-size: 10px;")
        creds_layout.addWidget(self.env_info_label, 3, 0, 1, 4)

        # Update info for initial selection
        self.credential_system_changed(self.credential_system_combo.currentText())

        layout.addWidget(creds_group)

        # Filters with help text
        filter_group = QGroupBox("Device Filters (supports wildcards: * for any text)")
        filter_layout = QGridLayout(filter_group)

        filter_layout.addWidget(QLabel("Folder:"), 0, 0)
        self.folder_filter = QLineEdit()
        self.folder_filter.setPlaceholderText("e.g., prod* or datacenter1")
        filter_layout.addWidget(self.folder_filter, 0, 1)

        filter_layout.addWidget(QLabel("Device Name:"), 0, 2)
        self.name_filter = QLineEdit()
        self.name_filter.setPlaceholderText("e.g., *switch* or router01")
        filter_layout.addWidget(self.name_filter, 0, 3)

        filter_layout.addWidget(QLabel("Vendor:"), 1, 0)
        self.vendor_filter = QLineEdit()
        self.vendor_filter.setPlaceholderText("e.g., cisco or juniper")
        filter_layout.addWidget(self.vendor_filter, 1, 1)

        filter_layout.addWidget(QLabel("Device Type:"), 1, 2)
        self.device_type_filter = QLineEdit()
        self.device_type_filter.setPlaceholderText("e.g., switch or router")
        filter_layout.addWidget(self.device_type_filter, 1, 3)

        # Filter action buttons
        filter_btn_layout = QHBoxLayout()

        preview_btn = QPushButton("Preview Devices")
        preview_btn.clicked.connect(self.preview_devices)
        filter_btn_layout.addWidget(preview_btn)

        clear_filters_btn = QPushButton("Clear Filters")
        clear_filters_btn.clicked.connect(self.clear_filters)
        filter_btn_layout.addWidget(clear_filters_btn)

        show_available_btn = QPushButton("Show Available Values")
        show_available_btn.clicked.connect(self.show_available_values)
        filter_btn_layout.addWidget(show_available_btn)

        filter_btn_layout.addStretch()
        filter_layout.addLayout(filter_btn_layout, 2, 0, 1, 4)

        # Filter summary label
        self.filter_summary_label = QLabel("No filtering applied")
        self.filter_summary_label.setWordWrap(True)
        self.filter_summary_label.setStyleSheet("color: #666; font-style: italic;")
        filter_layout.addWidget(self.filter_summary_label, 3, 0, 1, 4)

        layout.addWidget(filter_group)

        # Command configuration
        cmd_group = QGroupBox("Command Configuration")
        cmd_layout = QGridLayout(cmd_group)

        cmd_layout.addWidget(QLabel("Template:"), 0, 0)
        self.template_combo = QComboBox()
        self.template_combo.addItems(self.command_manager.get_template_names())
        self.template_combo.currentTextChanged.connect(self.template_selected)
        cmd_layout.addWidget(self.template_combo, 0, 1, 1, 2)

        cmd_layout.addWidget(QLabel("Commands:"), 1, 0)
        self.commands_edit = QLineEdit()
        self.commands_edit.setPlaceholderText("Enter commands separated by commas...")
        cmd_layout.addWidget(self.commands_edit, 1, 1, 1, 2)

        cmd_layout.addWidget(QLabel("Output Directory:"), 2, 0)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("e.g., configs, version, interfaces")
        cmd_layout.addWidget(self.output_dir_edit, 2, 1, 1, 2)

        layout.addWidget(cmd_group)

        # Execution settings
        exec_group = QGroupBox("Execution Settings")
        exec_layout = QGridLayout(exec_group)

        exec_layout.addWidget(QLabel("Batch Script:"), 0, 0)
        self.batch_script_combo = QComboBox()
        self.batch_script_combo.addItems([
            "batch_spn.py (Multi-threaded)",
            "batch_spn_single.py (Sequential)",
            "batch_spn_concurrent.py (Multi-process)"
        ])
        self.batch_script_combo.currentTextChanged.connect(self.batch_script_changed)
        exec_layout.addWidget(self.batch_script_combo, 0, 1)

        exec_layout.addWidget(QLabel("Max Workers:"), 0, 2)
        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 20)
        self.max_workers_spin.setValue(5)
        exec_layout.addWidget(self.max_workers_spin, 0, 3)

        self.verbose_check = QCheckBox("Verbose Output")
        self.verbose_check.setChecked(True)
        exec_layout.addWidget(self.verbose_check, 1, 0)

        self.dry_run_check = QCheckBox("Dry Run")
        exec_layout.addWidget(self.dry_run_check, 1, 1)

        # Script compatibility info
        self.script_info_label = QLabel()
        self.script_info_label.setWordWrap(True)
        self.script_info_label.setStyleSheet("color: #666; font-style: italic; font-size: 10px;")
        exec_layout.addWidget(self.script_info_label, 2, 0, 1, 4)

        # Update script info for initial selection
        self.batch_script_changed(self.batch_script_combo.currentText())

        layout.addWidget(exec_group)

        # Control buttons
        button_layout = QHBoxLayout()

        self.start_job_btn = QPushButton("Start Job")
        self.start_job_btn.clicked.connect(self.start_job)
        self.start_job_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        button_layout.addWidget(self.start_job_btn)

        self.cancel_job_btn = QPushButton("Cancel Job")
        self.cancel_job_btn.clicked.connect(self.cancel_job)
        self.cancel_job_btn.setEnabled(False)
        self.cancel_job_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
        button_layout.addWidget(self.cancel_job_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.tab_widget.addTab(tab, "Job Configuration")

    def setup_device_selection_tab(self):
        """Setup device selection and preview tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Device count label
        self.device_count_label = QLabel("No devices loaded")
        self.device_count_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(self.device_count_label)

        # Device table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(6)
        self.device_table.setHorizontalHeaderLabels([
            "Device Name", "Host", "Vendor", "Device Type", "Folder", "Creds ID"
        ])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.device_table)

        self.tab_widget.addTab(tab, "Device Selection")

    def setup_execution_tab(self):
        """Setup job execution monitoring tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Progress section
        progress_group = QGroupBox("Execution Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        progress_layout.addWidget(self.status_label)

        layout.addWidget(progress_group)

        # Output log
        log_group = QGroupBox("Execution Log")
        log_layout = QVBoxLayout(log_group)

        self.log_output = QTextEdit()
        self.log_output.setFont(QFont("Consolas", 9))
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)

        # Log controls
        log_controls = QHBoxLayout()

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.log_output.clear)
        log_controls.addWidget(clear_log_btn)

        save_log_btn = QPushButton("Save Log")
        save_log_btn.clicked.connect(self.save_log)
        log_controls.addWidget(save_log_btn)

        log_controls.addStretch()
        log_layout.addLayout(log_controls)

        layout.addWidget(log_group)

        self.tab_widget.addTab(tab, "Execution")

    def setup_templates_tab(self):
        """Setup command templates management tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Template editor
        editor_group = QGroupBox("Command Templates")
        editor_layout = QVBoxLayout(editor_group)

        self.template_editor = QTextEdit()
        self.template_editor.setFont(QFont("Consolas", 10))
        editor_layout.addWidget(self.template_editor)

        # Template controls
        template_controls = QHBoxLayout()

        load_templates_btn = QPushButton("Load Templates")
        load_templates_btn.clicked.connect(self.load_templates)
        template_controls.addWidget(load_templates_btn)

        save_templates_btn = QPushButton("Save Templates")
        save_templates_btn.clicked.connect(self.save_templates)
        template_controls.addWidget(save_templates_btn)

        reset_templates_btn = QPushButton("Reset to Defaults")
        reset_templates_btn.clicked.connect(self.reset_templates)
        template_controls.addWidget(reset_templates_btn)

        template_controls.addStretch()
        editor_layout.addLayout(template_controls)

        layout.addWidget(editor_group)

        self.tab_widget.addTab(tab, "Templates")

    def load_default_settings(self):
        """Load default settings and session file if it exists"""
        self.session_file_edit.setText("sessions.yaml")
        self.output_dir_edit.setText("output")
        self.load_templates()

        # Auto-load sessions.yaml if it exists
        if os.path.exists("sessions.yaml"):
            try:
                self.load_session_file()
            except Exception as e:
                self.log_message(f"Could not auto-load sessions.yaml: {str(e)}")

    def browse_session_file(self):
        """Browse for session file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Session File", "", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if file_path:
            self.session_file_edit.setText(file_path)

    def load_session_file(self):
        """Load session file with enhanced error handling"""
        file_path = self.session_file_edit.text()

        if not file_path:
            QMessageBox.warning(self, "Error", "Please select a session file")
            return

        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Error", f"Session file not found: {file_path}")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.sessions_data = yaml.safe_load(f)

            # Validate session data structure
            if not isinstance(self.sessions_data, list):
                raise ValueError("Session file should contain a list of folder groups")

            # Validate each folder group
            valid_folders = 0
            total_devices = 0

            for i, folder_group in enumerate(self.sessions_data):
                if not isinstance(folder_group, dict):
                    self.log_message(f"Warning: Invalid folder group at index {i}")
                    continue

                if 'folder_name' not in folder_group:
                    self.log_message(f"Warning: Missing folder_name in group {i}")
                    continue

                sessions = folder_group.get('sessions', [])
                if not isinstance(sessions, list):
                    self.log_message(f"Warning: Invalid sessions in folder '{folder_group['folder_name']}'")
                    continue

                valid_folders += 1
                total_devices += len(sessions)

            if valid_folders == 0:
                raise ValueError("No valid folder groups found in session file")

            # Initialize device filter
            self.device_filter = DeviceFilter(self.sessions_data)

            self.log_message(f"Loaded session file: {file_path}")
            self.log_message(f"Found {valid_folders} folders with {total_devices} total devices")

            # Auto-preview all devices
            self.preview_devices()

        except yaml.YAMLError as e:
            QMessageBox.critical(self, "YAML Error", f"Invalid YAML format:\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load session file:\n{str(e)}")

    def toggle_password_visibility(self, checked):
        """Toggle password visibility in credential fields"""
        echo_mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(echo_mode)
        self.enable_password_edit.setEchoMode(echo_mode)

    def credential_system_changed(self, system_text):
        """Handle credential system selection change and update UI accordingly"""
        system_info = {
            "Auto-detect from script": {
                "info": "Automatically detects the correct credential format based on the selected batch script.",
                "vars": "Script-dependent"
            },
            "SSH_* variables (spn.py)": {
                "info": "Uses SSH_USER, SSH_PASSWORD for spn.py script. Credentials apply to all devices.",
                "vars": "SSH_USER, SSH_PASSWORD, SSH_ENABLE_PASSWORD"
            },
            "SPN_* variables (legacy)": {
                "info": "Legacy format: SPN_USERNAME, SPN_PASSWORD, SPN_ENABLE_PASSWORD. Credentials apply to all devices.",
                "vars": "SPN_USERNAME, SPN_PASSWORD, SPN_ENABLE_PASSWORD"
            },
            "Per-device CRED_* variables": {
                "info": "Uses CRED_{ID}_USER, CRED_{ID}_PASS format where {ID} is the device's credential ID. Each device can have different credentials.",
                "vars": "CRED_1_USER, CRED_1_PASS, CRED_2_USER, CRED_2_PASS, etc."
            }
        }

        info = system_info.get(system_text, system_info["Auto-detect from script"])
        info_text = f"{info['info']}\nEnvironment variables: {info['vars']}\n\nLeave fields empty to use existing system environment variables."
        self.env_info_label.setText(info_text)

    def get_credential_env_vars(self, username: str, password: str, enable_password: str = "") -> Dict[str, str]:
        """Get the appropriate environment variables based on credential system and script selection"""
        env_vars = {}

        if not username or not password:
            return env_vars  # Return empty if no credentials provided

        credential_system = self.credential_system_combo.currentText()
        selected_script = self.batch_script_combo.currentText()

        # Auto-detect based on script
        if credential_system == "Auto-detect from script":
            if "batch_spn_concurrent.py" in selected_script:
                # For batch_spn_concurrent.py, we need to set per-device credentials
                # Since we don't know all credential IDs at this point, we'll set both formats
                env_vars.update({
                    'SSH_USER': username,
                    'SSH_PASSWORD': password,
                    # Also set some common credential IDs as fallback
                    'CRED_1_USER': username,
                    'CRED_1_PASS': password,
                    'CRED_2_USER': username,
                    'CRED_2_PASS': password,
                    'CRED_3_USER': username,
                    'CRED_3_PASS': password,
                })
            else:
                # For spn.py and other scripts, use SSH_* format
                env_vars.update({
                    'SSH_USER': username,
                    'SSH_PASSWORD': password,
                })

        # SSH_* format (spn.py)
        elif credential_system == "SSH_* variables (spn.py)":
            env_vars.update({
                'SSH_USER': username,
                'SSH_PASSWORD': password,
            })

        # SPN_* format (legacy)
        elif credential_system == "SPN_* variables (legacy)":
            env_vars.update({
                'SPN_USERNAME': username,
                'SPN_PASSWORD': password,
            })

        # CRED_* format (per-device)
        elif credential_system == "Per-device CRED_* variables":
            # Set common credential IDs - user can set more via system env vars
            for cred_id in range(1, 11):  # Cover credential IDs 1-10
                env_vars.update({
                    f'CRED_{cred_id}_USER': username,
                    f'CRED_{cred_id}_PASS': password,
                })

        # Add enable password if provided
        if enable_password:
            if credential_system == "SSH_* variables (spn.py)" or (
                    credential_system == "Auto-detect from script" and "spn.py" in selected_script):
                env_vars['SSH_ENABLE_PASSWORD'] = enable_password
            elif credential_system == "SPN_* variables (legacy)":
                env_vars['SPN_ENABLE_PASSWORD'] = enable_password

        return env_vars

    def batch_script_changed(self, script_text):
        """Handle batch script selection change and update UI accordingly"""
        script_info = {
            "batch_spn.py (Multi-threaded)": {
                "info": "Multi-threaded execution. No verbose output support.",
                "supports_verbose": False,
                "supports_workers": True
            },
            "batch_spn_single.py (Sequential)": {
                "info": "Sequential execution. Supports verbose output. No worker limit.",
                "supports_verbose": True,
                "supports_workers": False
            },
            "batch_spn_concurrent.py (Multi-process)": {
                "info": "Multi-process execution. Supports verbose output and process limit.",
                "supports_verbose": True,
                "supports_workers": True
            }
        }

        info = script_info.get(script_text, script_info["batch_spn.py (Multi-threaded)"])
        self.script_info_label.setText(info["info"])

        # Enable/disable controls based on script capabilities
        self.verbose_check.setEnabled(info["supports_verbose"])
        self.max_workers_spin.setEnabled(info["supports_workers"])

        # Automatically uncheck verbose if not supported
        if not info["supports_verbose"]:
            self.verbose_check.setChecked(False)

        # Update credential system info when script changes (for auto-detect)
        if hasattr(self, 'credential_system_combo'):
            self.credential_system_changed(self.credential_system_combo.currentText())

    def clear_filters(self):
        """Clear all filter fields"""
        self.folder_filter.clear()
        self.name_filter.clear()
        self.vendor_filter.clear()
        self.device_type_filter.clear()
        self.filter_summary_label.setText("Filters cleared")

    def show_available_values(self):
        """Show available values for filtering"""
        if not self.device_filter:
            QMessageBox.information(self, "Info", "Please load a session file first")
            return

        try:
            values = self.device_filter.get_available_values()

            message = []
            for category, items in values.items():
                if items:
                    sorted_items = sorted(items)[:10]  # Show first 10 items
                    items_str = ", ".join(sorted_items)
                    if len(items) > 10:
                        items_str += f"... ({len(items)} total)"
                    message.append(f"{category.title()}: {items_str}")

            if message:
                QMessageBox.information(
                    self, "Available Values",
                    "Available values for filtering:\n\n" + "\n\n".join(message)
                )
            else:
                QMessageBox.information(self, "Info", "No data available for filtering")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to get available values:\n{str(e)}")

    def template_selected(self, template_name):
        """Handle template selection"""
        if not template_name:
            return

        template = self.command_manager.get_template_by_name(template_name)
        if template and 'command' in template:
            self.commands_edit.setText(template['command'])

    def preview_devices(self):
        """Preview devices based on current filters with robust error handling"""
        if not self.sessions_data:
            self.device_count_label.setText("No session data loaded")
            self.filter_summary_label.setText("Load a session file first")
            return

        if not self.device_filter:
            self.device_filter = DeviceFilter(self.sessions_data)

        try:
            # Get filter values
            folder_filter = self.folder_filter.text().strip() or None
            name_filter = self.name_filter.text().strip() or None
            vendor_filter = self.vendor_filter.text().strip() or None
            device_type_filter = self.device_type_filter.text().strip() or None

            # Log active filters
            active_filters = []
            if folder_filter:
                active_filters.append(f"folder='{folder_filter}'")
            if name_filter:
                active_filters.append(f"name='{name_filter}'")
            if vendor_filter:
                active_filters.append(f"vendor='{vendor_filter}'")
            if device_type_filter:
                active_filters.append(f"type='{device_type_filter}'")

            if active_filters:
                self.log_message(f"Applying filters: {', '.join(active_filters)}")
            else:
                self.log_message("No filters applied - showing all devices")

            # Apply filters
            self.current_devices = self.device_filter.filter_devices(
                folder_pattern=folder_filter,
                name_pattern=name_filter,
                vendor_pattern=vendor_filter,
                device_type=device_type_filter
            )

            # Update filter summary
            summary = self.device_filter.get_filter_summary()
            self.filter_summary_label.setText(summary)

            # Handle no matches
            if not self.current_devices:
                self.device_count_label.setText("No devices match the current filters")
                self.device_table.setRowCount(0)

                # Provide helpful suggestions
                suggestions = []
                if vendor_filter:
                    available_vendors = self.device_filter.get_available_values()['vendors']
                    if available_vendors:
                        vendor_list = sorted(list(available_vendors))[:5]
                        suggestions.append(f"Available vendors: {', '.join(vendor_list)}")

                if device_type_filter:
                    available_types = self.device_filter.get_available_values()['device_types']
                    if available_types:
                        type_list = sorted(list(available_types))[:5]
                        suggestions.append(f"Available device types: {', '.join(type_list)}")

                if suggestions:
                    suggestion_text = "Suggestions:\n" + "\n".join(suggestions)
                    self.log_message(f"No matches found. {suggestion_text}")

                # Switch to device selection tab to show the empty result
                self.tab_widget.setCurrentIndex(1)
                return

            # Update device table
            self.device_table.setRowCount(len(self.current_devices))

            for row, device in enumerate(self.current_devices):
                try:
                    # Safely get device properties with defaults
                    display_name = device.get('display_name', 'Unknown')
                    host = device.get('host', 'Unknown')
                    vendor = device.get('Vendor', 'Unknown')
                    device_type = device.get('DeviceType', 'Unknown')
                    folder_name = device.get('folder_name', 'Unknown')
                    creds_id = str(device.get('credsid', 'Unknown'))

                    self.device_table.setItem(row, 0, QTableWidgetItem(display_name))
                    self.device_table.setItem(row, 1, QTableWidgetItem(host))
                    self.device_table.setItem(row, 2, QTableWidgetItem(vendor))
                    self.device_table.setItem(row, 3, QTableWidgetItem(device_type))
                    self.device_table.setItem(row, 4, QTableWidgetItem(folder_name))
                    self.device_table.setItem(row, 5, QTableWidgetItem(creds_id))

                except Exception as e:
                    self.log_message(f"Error processing device at row {row}: {str(e)}")
                    # Fill with error indicators
                    for col in range(6):
                        self.device_table.setItem(row, col, QTableWidgetItem("ERROR"))

            # Update count
            self.device_count_label.setText(f"Matched {len(self.current_devices)} devices")
            self.log_message(f"Found {len(self.current_devices)} matching devices")

            # Switch to device selection tab
            self.tab_widget.setCurrentIndex(1)

        except Exception as e:
            error_msg = f"Error during device preview: {str(e)}"
            self.log_message(error_msg)
            QMessageBox.critical(self, "Preview Error", error_msg)

            # Reset state
            self.current_devices = []
            self.device_count_label.setText("Error occurred during preview")
            self.device_table.setRowCount(0)

    def start_job(self):
        """Start the batch job with enhanced validation"""
        try:
            # Validate inputs
            if not self.session_file_edit.text():
                QMessageBox.warning(self, "Error", "Please select a session file")
                return

            if not os.path.exists(self.session_file_edit.text()):
                QMessageBox.warning(self, "Error", "Session file does not exist")
                return

            if not self.commands_edit.text().strip():
                QMessageBox.warning(self, "Error", "Please enter commands to execute")
                return

            if not self.output_dir_edit.text().strip():
                QMessageBox.warning(self, "Error", "Please enter an output directory name")
                return

            if not self.current_devices:
                reply = QMessageBox.question(
                    self, "No Devices",
                    "No devices are currently selected. This might mean:\n"
                    "• No session file is loaded\n"
                    "• All devices are filtered out\n"
                    "• Preview hasn't been run\n\n"
                    "Do you want to preview devices first?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.preview_devices()
                return

            # Confirm job execution
            reply = QMessageBox.question(
                self, "Confirm Job Execution",
                f"Ready to execute job on {len(self.current_devices)} devices.\n\n"
                f"Commands: {self.commands_edit.text()}\n"
                f"Output directory: {self.output_dir_edit.text()}\n"
                f"Dry run: {'Yes' if self.dry_run_check.isChecked() else 'No'}\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            # Prepare job configuration
            batch_script_map = {
                "batch_spn.py (Multi-threaded)": "batch_spn.py",
                "batch_spn_single.py (Sequential)": "batch_spn_single.py",
                "batch_spn_concurrent.py (Multi-process)": "batch_spn_concurrent.py"
            }

            selected_script = self.batch_script_combo.currentText()
            batch_script = batch_script_map.get(selected_script, "batch_spn.py")

            # Validate batch script exists
            if not os.path.exists(batch_script):
                QMessageBox.warning(
                    self, "Error",
                    f"Batch script not found: {batch_script}\n"
                    "Please ensure the script is in the current directory."
                )
                return

            job_config = {
                'yaml_file': self.session_file_edit.text(),
                'batch_script': batch_script,
                'folder_filter': self.folder_filter.text().strip(),
                'name_filter': self.name_filter.text().strip(),
                'vendor_filter': self.vendor_filter.text().strip(),
                'device_type_filter': self.device_type_filter.text().strip(),
                'commands': self.commands_edit.text().strip(),
                'output_dir': self.output_dir_edit.text().strip(),
                'max_workers': self.max_workers_spin.value(),
                'verbose': self.verbose_check.isChecked(),
                'dry_run': self.dry_run_check.isChecked()
            }

            # Add credentials using the new system
            username = self.username_edit.text().strip()
            password = self.password_edit.text().strip()
            enable_password = self.enable_password_edit.text().strip()

            if username and password:
                credential_env_vars = self.get_credential_env_vars(username, password, enable_password)
                if credential_env_vars:
                    job_config['credentials'] = credential_env_vars
                    self.log_message(f"Using credential system: {self.credential_system_combo.currentText()}")
                    self.log_message(f"Setting {len(credential_env_vars)} environment variables for credentials")
            else:
                self.log_message("No credentials provided - using system environment variables")

            # Start execution thread
            self.execution_thread = JobExecutorThread(job_config)
            self.execution_thread.progress_update.connect(self.log_message)
            self.execution_thread.status_update.connect(self.update_device_status)
            self.execution_thread.finished_signal.connect(self.job_finished)

            # Update UI
            self.start_job_btn.setEnabled(False)
            self.cancel_job_btn.setEnabled(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self.status_label.setText("Job running...")

            # Switch to execution tab
            self.tab_widget.setCurrentIndex(2)

            # Start thread
            self.execution_thread.start()

            self.log_message(f"Started job with {len(self.current_devices)} devices")

        except Exception as e:
            error_msg = f"Failed to start job: {str(e)}"
            self.log_message(error_msg)
            QMessageBox.critical(self, "Start Job Error", error_msg)

    def cancel_job(self):
        """Cancel the running job"""
        if self.execution_thread and self.execution_thread.isRunning():
            reply = QMessageBox.question(
                self, "Cancel Job",
                "Are you sure you want to cancel the running job?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.execution_thread.cancel()
                self.execution_thread.wait(5000)  # Wait up to 5 seconds

                if self.execution_thread.isRunning():
                    self.log_message("Warning: Job thread did not terminate cleanly")

    def job_finished(self, summary):
        """Handle job completion"""
        # Update UI
        self.start_job_btn.setEnabled(True)
        self.cancel_job_btn.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        if summary.get('cancelled'):
            self.status_label.setText("Job cancelled")
            self.log_message("Job was cancelled by user")
        elif summary.get('success'):
            self.status_label.setText("Job completed successfully")
            self.log_message("Job completed successfully")
            if summary.get('stdout'):
                self.log_message(f"Final output: {summary['stdout']}")
        else:
            self.status_label.setText("Job failed")
            error_info = summary.get('error', summary.get('stderr', 'Unknown error'))
            self.log_message(f"Job failed: {error_info}")

        # Reset thread
        self.execution_thread = None

    def update_device_status(self, device_name, status):
        """Update device status in the table with color coding"""
        try:
            # Find device in table and update status
            for row in range(self.device_table.rowCount()):
                item = self.device_table.item(row, 0)
                if item and item.text() == device_name:
                    # Set background color based on status
                    if status == "SUCCESS":
                        color = QColor(144, 238, 144)  # Light green
                    elif status == "FAILED":
                        color = QColor(255, 182, 193)  # Light red
                    elif status == "ERROR":
                        color = QColor(255, 165, 0)  # Orange
                    else:
                        color = QColor(255, 255, 224)  # Light yellow for unknown

                    # Apply color to all columns in the row
                    for col in range(self.device_table.columnCount()):
                        item = self.device_table.item(row, col)
                        if item:
                            item.setBackground(color)
                    break
        except Exception as e:
            self.log_message(f"Error updating device status: {str(e)}")

    def log_message(self, message):
        """Add message to log output with timestamp"""
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted_message = f"[{timestamp}] {message}"

            self.log_output.append(formatted_message)

            # Auto-scroll to bottom
            cursor = self.log_output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_output.setTextCursor(cursor)

            # Process events to update UI
            QApplication.processEvents()

        except Exception as e:
            print(f"Error logging message: {e}")

    def save_log(self):
        """Save log to file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            default_filename = f"job_log_{timestamp}.txt"

            file_path, _ = QFileDialog.getSaveFileName(
                self, "Save Log", default_filename,
                "Text Files (*.txt);;All Files (*)"
            )

            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_output.toPlainText())
                QMessageBox.information(self, "Success", f"Log saved to {file_path}")
                self.log_message(f"Log saved to {file_path}")

        except Exception as e:
            error_msg = f"Failed to save log: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.log_message(error_msg)

    def load_templates(self):
        """Load templates into editor"""
        try:
            self.command_manager.templates = self.command_manager.load_templates()
            self.template_editor.setPlainText(
                json.dumps(self.command_manager.templates, indent=2)
            )

            # Update combo box
            self.template_combo.clear()
            self.template_combo.addItems(self.command_manager.get_template_names())

        except Exception as e:
            error_msg = f"Failed to load templates: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.log_message(error_msg)

    def save_templates(self):
        """Save templates from editor"""
        try:
            templates_text = self.template_editor.toPlainText()

            if not templates_text.strip():
                QMessageBox.warning(self, "Warning", "Template editor is empty")
                return

            templates = json.loads(templates_text)

            # Validate template structure
            if not isinstance(templates, dict):
                raise ValueError("Templates must be a dictionary")

            for key, template in templates.items():
                if not isinstance(template, dict):
                    raise ValueError(f"Template '{key}' must be a dictionary")
                if 'name' not in template or 'command' not in template:
                    raise ValueError(f"Template '{key}' must have 'name' and 'command' fields")

            # Save templates
            self.command_manager.save_templates(templates)
            self.command_manager.templates = templates

            # Update combo box
            self.template_combo.clear()
            self.template_combo.addItems(self.command_manager.get_template_names())

            QMessageBox.information(self, "Success", "Templates saved successfully")
            self.log_message("Templates saved successfully")

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON format: {str(e)}"
            QMessageBox.critical(self, "JSON Error", error_msg)
        except Exception as e:
            error_msg = f"Failed to save templates: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.log_message(error_msg)

    def reset_templates(self):
        """Reset templates to defaults"""
        reply = QMessageBox.question(
            self, "Reset Templates",
            "This will reset all templates to defaults. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                default_templates = self.command_manager._get_default_templates()
                self.command_manager.save_templates(default_templates)
                self.command_manager.templates = default_templates

                # Update UI
                self.template_editor.setPlainText(
                    json.dumps(default_templates, indent=2)
                )
                self.template_combo.clear()
                self.template_combo.addItems(self.command_manager.get_template_names())

                QMessageBox.information(self, "Success", "Templates reset to defaults")
                self.log_message("Templates reset to defaults")

            except Exception as e:
                error_msg = f"Failed to reset templates: {str(e)}"
                QMessageBox.critical(self, "Error", error_msg)
                self.log_message(error_msg)


def main():
    """Main application entry point"""
    try:
        app = QApplication(sys.argv)

        # Set application properties
        app.setApplicationName("Network Job Runner")
        app.setApplicationVersion("1.1.0")
        app.setOrganizationName("Network Automation Tools")

        # Create and show main window
        window = NetworkJobRunner()
        window.show()

        # Run application
        sys.exit(app.exec())

    except Exception as e:
        print(f"Failed to start application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()