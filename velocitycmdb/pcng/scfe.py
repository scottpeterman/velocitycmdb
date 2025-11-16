#!/usr/bin/env python3
"""
Discovery Launcher - PyQt6 GUI for Secure Cartography Discovery
Device lookup from sessions.yaml and automated discovery execution
"""

import sys
import os
import yaml
import json
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox,
    QCheckBox, QTextEdit, QGroupBox, QFileDialog, QMessageBox,
    QProgressBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings
from PyQt6.QtGui import QFont, QTextCursor, QIcon


class DeviceLookup:
    """Handles device lookup from sessions.yaml file"""

    def __init__(self, sessions_file: str = "sessions.yaml"):
        self.sessions_file = sessions_file
        self.devices = {}
        self.load_sessions()

    def load_sessions(self) -> bool:
        """Load devices from sessions.yaml file"""
        try:
            if not os.path.exists(self.sessions_file):
                return False

            with open(self.sessions_file, 'r', encoding='utf-8') as f:
                sessions_data = yaml.safe_load(f)

            self.devices = {}
            for site in sessions_data:
                folder_name = site.get('folder_name', 'Unknown')
                for session in site.get('sessions', []):
                    device_name = session.get('display_name', '')
                    if device_name:
                        self.devices[device_name] = {
                            'host': session.get('host', ''),
                            'folder': folder_name,
                            'vendor': session.get('Vendor', ''),
                            'device_type': session.get('DeviceType', ''),
                            'model': session.get('Model', ''),
                            'session_data': session
                        }

            return True

        except Exception as e:
            print(f"Error loading sessions file: {e}")
            return False

    def find_device(self, device_name: str) -> Optional[Dict[str, Any]]:
        """Find device by name (case-insensitive, partial match)"""
        device_name_lower = device_name.lower()

        # Exact match first
        for name, data in self.devices.items():
            if name.lower() == device_name_lower:
                return data

        # Partial match
        matches = []
        for name, data in self.devices.items():
            if device_name_lower in name.lower():
                matches.append((name, data))

        if len(matches) == 1:
            return matches[0][1]
        elif len(matches) > 1:
            # Return the closest match (shortest name)
            closest = min(matches, key=lambda x: len(x[0]))
            return closest[1]

        return None

    def get_all_devices(self) -> List[str]:
        """Get list of all device names"""
        return sorted(self.devices.keys())

    def search_devices(self, query: str) -> List[str]:
        """Search devices by name, returning matching device names"""
        if not query:
            return self.get_all_devices()

        query_lower = query.lower()
        matches = []

        for name in self.devices.keys():
            if query_lower in name.lower():
                matches.append(name)

        return sorted(matches)


class DiscoveryWorker(QThread):
    """Worker thread for running discovery process"""

    output_received = pyqtSignal(str)
    error_received = pyqtSignal(str)
    finished = pyqtSignal(int, str)  # return_code, final_message

    def __init__(self, command_args: List[str], working_dir: str = None):
        super().__init__()
        self.command_args = command_args
        self.working_dir = working_dir
        self.process = None

    def run(self):
        """Execute the discovery command"""
        try:
            self.process = subprocess.Popen(
                self.command_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                cwd=self.working_dir
            )

            # Read stdout in real-time
            while True:
                output = self.process.stdout.readline()
                if output == '' and self.process.poll() is not None:
                    break
                if output:
                    self.output_received.emit(output.strip())

            # Get final return code
            return_code = self.process.wait()

            # Read any remaining stderr
            stderr = self.process.stderr.read()
            if stderr:
                self.error_received.emit(stderr)

            if return_code == 0:
                self.finished.emit(return_code, "Discovery completed successfully")
            else:
                self.finished.emit(return_code, f"Discovery failed with return code {return_code}")

        except Exception as e:
            self.error_received.emit(f"Failed to execute discovery: {str(e)}")
            self.finished.emit(-1, f"Execution error: {str(e)}")

    def stop(self):
        """Stop the discovery process"""
        if self.process and self.process.poll() is None:
            self.process.terminate()


class DiscoveryLauncher(QMainWindow):
    """Main GUI application for discovery launcher"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Discovery Launcher")
        self.setGeometry(100, 100, 1200, 800)

        # Initialize components
        self.device_lookup = DeviceLookup()
        self.discovery_worker = None
        self.settings = QSettings("NetworkTools", "DiscoveryLauncher")

        # Setup UI
        self.setup_ui()
        self.load_settings()

        # Auto-refresh device list periodically
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_device_list)
        self.refresh_timer.start(30000)  # Refresh every 30 seconds

    def setup_ui(self):
        """Setup the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel - Configuration
        config_widget = self.create_config_panel()
        splitter.addWidget(config_widget)

        # Right panel - Output and device list
        right_widget = self.create_right_panel()
        splitter.addWidget(right_widget)

        # Set splitter proportions
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Status bar
        self.statusBar().showMessage("Ready")

    def create_config_panel(self) -> QWidget:
        """Create the configuration panel"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Device lookup section
        device_group = QGroupBox("Device Lookup")
        device_layout = QGridLayout(device_group)

        device_layout.addWidget(QLabel("Sessions File:"), 0, 0)
        self.sessions_file_edit = QLineEdit("sessions.yaml")
        device_layout.addWidget(self.sessions_file_edit, 0, 1)

        browse_sessions_btn = QPushButton("Browse")
        browse_sessions_btn.clicked.connect(self.browse_sessions_file)
        device_layout.addWidget(browse_sessions_btn, 0, 2)

        device_layout.addWidget(QLabel("Device Name:"), 1, 0)
        self.device_name_edit = QLineEdit()
        self.device_name_edit.textChanged.connect(self.on_device_name_changed)
        device_layout.addWidget(self.device_name_edit, 1, 1, 1, 2)

        device_layout.addWidget(QLabel("Found IP:"), 2, 0)
        self.found_ip_label = QLabel("(none)")
        self.found_ip_label.setStyleSheet("color: blue; font-weight: bold;")
        device_layout.addWidget(self.found_ip_label, 2, 1, 1, 2)

        device_layout.addWidget(QLabel("Device Info:"), 3, 0)
        self.device_info_label = QLabel("(none)")
        device_layout.addWidget(self.device_info_label, 3, 1, 1, 2)

        layout.addWidget(device_group)

        # Discovery configuration section
        discovery_group = QGroupBox("Discovery Configuration")
        discovery_layout = QGridLayout(discovery_group)

        # SC tool path
        discovery_layout.addWidget(QLabel("SC Tool Path:"), 0, 0)
        self.sc_path_edit = QLineEdit("sc")
        discovery_layout.addWidget(self.sc_path_edit, 0, 1)

        browse_sc_btn = QPushButton("Browse")
        browse_sc_btn.clicked.connect(self.browse_sc_path)
        discovery_layout.addWidget(browse_sc_btn, 0, 2)

        # Authentication
        discovery_layout.addWidget(QLabel("Username:"), 1, 0)
        self.username_edit = QLineEdit()
        discovery_layout.addWidget(self.username_edit, 1, 1, 1, 2)

        discovery_layout.addWidget(QLabel("Password:"), 2, 0)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        discovery_layout.addWidget(self.password_edit, 2, 1, 1, 2)

        discovery_layout.addWidget(QLabel("Alt Username:"), 3, 0)
        self.alt_username_edit = QLineEdit()
        discovery_layout.addWidget(self.alt_username_edit, 3, 1, 1, 2)

        discovery_layout.addWidget(QLabel("Alt Password:"), 4, 0)
        self.alt_password_edit = QLineEdit()
        self.alt_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        discovery_layout.addWidget(self.alt_password_edit, 4, 1, 1, 2)

        # Exclude string
        discovery_layout.addWidget(QLabel("Exclude String:"), 5, 0)
        self.exclude_string_edit = QLineEdit()
        self.exclude_string_edit.setPlaceholderText("Comma-separated strings to exclude")
        discovery_layout.addWidget(self.exclude_string_edit, 5, 1, 1, 2)

        # Options
        discovery_layout.addWidget(QLabel("Output Directory:"), 6, 0)
        self.output_dir_edit = QLineEdit("./discovery_output")
        discovery_layout.addWidget(self.output_dir_edit, 6, 1)

        browse_output_btn = QPushButton("Browse")
        browse_output_btn.clicked.connect(self.browse_output_dir)
        discovery_layout.addWidget(browse_output_btn, 6, 2)

        discovery_layout.addWidget(QLabel("Map Name:"), 7, 0)
        self.map_name_edit = QLineEdit("network_map")
        discovery_layout.addWidget(self.map_name_edit, 7, 1, 1, 2)

        discovery_layout.addWidget(QLabel("Timeout (sec):"), 8, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setValue(30)
        discovery_layout.addWidget(self.timeout_spin, 8, 1, 1, 2)

        discovery_layout.addWidget(QLabel("Max Devices:"), 9, 0)
        self.max_devices_spin = QSpinBox()
        self.max_devices_spin.setRange(1, 1000)
        self.max_devices_spin.setValue(100)
        discovery_layout.addWidget(self.max_devices_spin, 9, 1, 1, 2)

        discovery_layout.addWidget(QLabel("Layout Algorithm:"), 10, 0)
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["kk", "spring", "circular", "random"])
        discovery_layout.addWidget(self.layout_combo, 10, 1, 1, 2)

        # Checkboxes
        self.debug_checkbox = QCheckBox("Save Debug Info")
        discovery_layout.addWidget(self.debug_checkbox, 11, 0, 1, 3)

        layout.addWidget(discovery_group)

        # Control buttons
        button_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start Discovery")
        self.start_btn.clicked.connect(self.start_discovery)
        self.start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        button_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_discovery)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; }")
        button_layout.addWidget(self.stop_btn)

        save_settings_btn = QPushButton("Save Settings")
        save_settings_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_settings_btn)

        layout.addLayout(button_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()
        return widget

    def create_right_panel(self) -> QWidget:
        """Create the right panel with tabs"""
        tab_widget = QTabWidget()

        # Output tab
        output_widget = QWidget()
        output_layout = QVBoxLayout(output_widget)

        output_layout.addWidget(QLabel("Discovery Output:"))
        self.output_text = QTextEdit()
        self.output_text.setFont(QFont("Consolas", 9))
        self.output_text.setReadOnly(True)
        output_layout.addWidget(self.output_text)

        # Clear output button
        clear_btn = QPushButton("Clear Output")
        clear_btn.clicked.connect(self.output_text.clear)
        output_layout.addWidget(clear_btn)

        tab_widget.addTab(output_widget, "Output")

        # Device list tab
        device_widget = QWidget()
        device_layout = QVBoxLayout(device_widget)

        # Search box
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.device_search_edit = QLineEdit()
        self.device_search_edit.textChanged.connect(self.filter_device_list)
        search_layout.addWidget(self.device_search_edit)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_device_list)
        search_layout.addWidget(refresh_btn)

        device_layout.addLayout(search_layout)

        # Device table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4)
        self.device_table.setHorizontalHeaderLabels(["Device Name", "IP Address", "Vendor", "Folder"])
        self.device_table.horizontalHeader().setStretchLastSection(True)
        self.device_table.itemDoubleClicked.connect(self.on_device_double_clicked)
        device_layout.addWidget(self.device_table)

        tab_widget.addTab(device_widget, "Devices")

        # Populate device table
        self.populate_device_table()

        return tab_widget

    def browse_sessions_file(self):
        """Browse for sessions.yaml file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Sessions File", "", "YAML Files (*.yaml *.yml);;All Files (*)"
        )
        if file_path:
            self.sessions_file_edit.setText(file_path)
            self.device_lookup = DeviceLookup(file_path)
            self.populate_device_table()

    def browse_sc_path(self):
        """Browse for SC tool executable"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select SC Tool", "", "Executable Files (*.exe);;All Files (*)"
        )
        if file_path:
            self.sc_path_edit.setText(file_path)

    def browse_output_dir(self):
        """Browse for output directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def on_device_name_changed(self):
        """Handle device name text change"""
        device_name = self.device_name_edit.text().strip()
        if not device_name:
            self.found_ip_label.setText("(none)")
            self.device_info_label.setText("(none)")
            return

        device = self.device_lookup.find_device(device_name)
        if device:
            self.found_ip_label.setText(device['host'])
            info = f"{device['vendor']} {device['device_type']} ({device['folder']})"
            self.device_info_label.setText(info)
        else:
            self.found_ip_label.setText("(not found)")
            self.device_info_label.setText("Device not found in sessions file")

    def populate_device_table(self):
        """Populate the device table with all devices"""
        devices = self.device_lookup.get_all_devices()
        self.device_table.setRowCount(len(devices))

        for row, device_name in enumerate(devices):
            device = self.device_lookup.devices[device_name]

            self.device_table.setItem(row, 0, QTableWidgetItem(device_name))
            self.device_table.setItem(row, 1, QTableWidgetItem(device['host']))
            self.device_table.setItem(row, 2, QTableWidgetItem(device['vendor']))
            self.device_table.setItem(row, 3, QTableWidgetItem(device['folder']))

        self.device_table.resizeColumnsToContents()

    def filter_device_list(self):
        """Filter device table based on search text"""
        search_text = self.device_search_edit.text().lower()

        for row in range(self.device_table.rowCount()):
            item = self.device_table.item(row, 0)  # Device name column
            if item:
                visible = search_text in item.text().lower()
                self.device_table.setRowHidden(row, not visible)

    def on_device_double_clicked(self, item):
        """Handle double-click on device table"""
        row = item.row()
        device_name_item = self.device_table.item(row, 0)
        if device_name_item:
            self.device_name_edit.setText(device_name_item.text())

    def refresh_device_list(self):
        """Refresh the device list from sessions file"""
        sessions_file = self.sessions_file_edit.text()
        if sessions_file and os.path.exists(sessions_file):
            self.device_lookup = DeviceLookup(sessions_file)
            self.populate_device_table()
            self.on_device_name_changed()  # Update current device lookup

    def start_discovery(self):
        """Start the discovery process"""
        # Validate inputs
        device_name = self.device_name_edit.text().strip()
        if not device_name:
            QMessageBox.warning(self, "Error", "Please enter a device name")
            return

        device = self.device_lookup.find_device(device_name)
        if not device:
            QMessageBox.warning(self, "Error", "Device not found in sessions file")
            return

        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if not username or not password:
            QMessageBox.warning(self, "Error", "Username and password are required")
            return

        # Build command arguments
        sc_path = self.sc_path_edit.text().strip() or "sc"
        command_args = [sc_path]

        # Add arguments
        command_args.extend(["--seed-ip", device['host']])
        command_args.extend(["--username", username])
        command_args.extend(["--password", password])

        alt_username = self.alt_username_edit.text().strip()
        if alt_username:
            command_args.extend(["--alternate-username", alt_username])

        alt_password = self.alt_password_edit.text()
        if alt_password:
            command_args.extend(["--alternate-password", alt_password])

        exclude_string = self.exclude_string_edit.text().strip()
        if exclude_string:
            command_args.extend(["--exclude-string", f'"{exclude_string}"'])

        output_dir = self.output_dir_edit.text().strip()
        if output_dir:
            command_args.extend(["--output-dir", output_dir])

        map_name = self.map_name_edit.text().strip()
        if map_name:
            command_args.extend(["--map-name", map_name])

        command_args.extend(["--timeout", str(self.timeout_spin.value())])
        command_args.extend(["--max-devices", str(self.max_devices_spin.value())])
        command_args.extend(["--layout-algo", self.layout_combo.currentText()])

        if self.debug_checkbox.isChecked():
            command_args.append("--save-debug-info")

        # Clear output and start discovery
        self.output_text.clear()
        self.append_output(f"Starting discovery from device: {device_name} ({device['host']})")
        self.append_output(f"Command: {' '.join(command_args)}")
        self.append_output("-" * 60)

        # Start worker thread
        self.discovery_worker = DiscoveryWorker(command_args)
        self.discovery_worker.output_received.connect(self.append_output)
        self.discovery_worker.error_received.connect(self.append_error)
        self.discovery_worker.finished.connect(self.on_discovery_finished)

        # Update UI state
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.statusBar().showMessage("Discovery in progress...")

        # Start the discovery
        self.discovery_worker.start()

    def stop_discovery(self):
        """Stop the discovery process"""
        if self.discovery_worker:
            self.discovery_worker.stop()
            self.append_output("Discovery stop requested...")

    def append_output(self, text: str):
        """Append text to output display"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_text.append(f"[{timestamp}] {text}")

        # Auto-scroll to bottom
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.output_text.setTextCursor(cursor)

    def append_error(self, text: str):
        """Append error text to output display"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.output_text.append(f"[{timestamp}] ERROR: {text}")

        # Auto-scroll to bottom
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.output_text.setTextCursor(cursor)

    def on_discovery_finished(self, return_code: int, message: str):
        """Handle discovery completion"""
        self.append_output(f"Discovery finished: {message}")

        # Update UI state
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)

        if return_code == 0:
            self.statusBar().showMessage("Discovery completed successfully")

            # Show completion dialog
            output_dir = self.output_dir_edit.text().strip()
            map_name = self.map_name_edit.text().strip()

            QMessageBox.information(
                self,
                "Discovery Complete",
                f"Discovery completed successfully!\n\n"
                f"Output directory: {output_dir}\n"
                f"Map name: {map_name}\n\n"
                f"Generated files:\n"
                f"- {map_name}.json\n"
                f"- {map_name}.graphml\n"
                f"- {map_name}.drawio\n"
                f"- {map_name}.svg"
            )
        else:
            self.statusBar().showMessage(f"Discovery failed (code: {return_code})")
            QMessageBox.warning(self, "Discovery Failed", f"Discovery failed with return code {return_code}")

        self.discovery_worker = None

    def save_settings(self):
        """Save current settings"""
        settings = self.settings

        settings.setValue("sessions_file", self.sessions_file_edit.text())
        settings.setValue("sc_path", self.sc_path_edit.text())
        settings.setValue("username", self.username_edit.text())
        settings.setValue("alt_username", self.alt_username_edit.text())
        settings.setValue("exclude_string", self.exclude_string_edit.text())
        settings.setValue("output_dir", self.output_dir_edit.text())
        settings.setValue("map_name", self.map_name_edit.text())
        settings.setValue("timeout", self.timeout_spin.value())
        settings.setValue("max_devices", self.max_devices_spin.value())
        settings.setValue("layout_algo", self.layout_combo.currentText())
        settings.setValue("save_debug", self.debug_checkbox.isChecked())

        self.statusBar().showMessage("Settings saved")
        QMessageBox.information(self, "Settings", "Settings saved successfully")

    def load_settings(self):
        """Load saved settings"""
        settings = self.settings

        self.sessions_file_edit.setText(settings.value("sessions_file", "sessions.yaml"))
        self.sc_path_edit.setText(settings.value("sc_path", "sc"))
        self.username_edit.setText(settings.value("username", ""))
        self.alt_username_edit.setText(settings.value("alt_username", ""))
        self.exclude_string_edit.setText(settings.value("exclude_string", ""))
        self.output_dir_edit.setText(settings.value("output_dir", "./discovery_output"))
        self.map_name_edit.setText(settings.value("map_name", "network_map"))
        self.timeout_spin.setValue(int(settings.value("timeout", 30)))
        self.max_devices_spin.setValue(int(settings.value("max_devices", 100)))

        layout_algo = settings.value("layout_algo", "kk")
        index = self.layout_combo.findText(layout_algo)
        if index >= 0:
            self.layout_combo.setCurrentIndex(index)

        self.debug_checkbox.setChecked(settings.value("save_debug", False, type=bool))

        # Reload device lookup with saved sessions file
        sessions_file = self.sessions_file_edit.text()
        if sessions_file and os.path.exists(sessions_file):
            self.device_lookup = DeviceLookup(sessions_file)

    def closeEvent(self, event):
        """Handle application close"""
        if self.discovery_worker and self.discovery_worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Discovery in Progress",
                "Discovery is still running. Do you want to stop it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.discovery_worker.stop()
                self.discovery_worker.wait(3000)  # Wait up to 3 seconds
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("Discovery Launcher")
    app.setOrganizationName("NetworkTools")

    # Set application icon if available
    try:
        app.setWindowIcon(QIcon("discovery_icon.png"))
    except:
        pass

    # Create and show main window
    window = DiscoveryLauncher()
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()