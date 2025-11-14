#!/usr/bin/env python3
"""
Desktop Wrapper for Network Asset Management Web Application
Provides single-instance desktop app with embedded web view and utility menu
WITH PROGRESS BAR AND ETA TRACKING
"""

import sys
import os
import subprocess
import signal
import time
import json
from pathlib import Path
from datetime import timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QMenu,
    QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout, QLabel,
    QProgressBar, QFrame
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer, QThread, pyqtSignal, QMutexLocker, QMutex
from PyQt6.QtGui import QAction, QIcon, QFont
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class CommandRunner(QThread):
    """Thread for running shell commands without blocking UI"""
    output = pyqtSignal(str)
    progress = pyqtSignal(dict)  # Emits progress updates as dict
    finished = pyqtSignal(int)  # exit code

    def __init__(self, command, cwd=None, json_mode=False):
        super().__init__()
        self.command = command
        self.cwd = cwd
        self.json_mode = json_mode
        self.process = None

    def run(self):
        try:
            self.output.emit(f"$ {self.command}\n")
            self.output.emit(f"Working directory: {self.cwd or os.getcwd()}\n\n")

            self.process = subprocess.Popen(
                self.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=self.cwd,
                bufsize=1
            )

            # Stream output line by line
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    # Try to parse as JSON progress message
                    if self.json_mode:
                        try:
                            data = json.loads(line.strip())
                            if isinstance(data, dict) and 'type' in data:
                                msg_type = data['type']

                                # Emit progress updates
                                if msg_type in ['progress', 'job_start', 'job_complete']:
                                    self.progress.emit(data)

                                # Format log messages
                                if msg_type == 'log':
                                    log_line = f"[{data.get('level', 'INFO')}] {data.get('message', '')}\n"
                                    self.output.emit(log_line)
                                    continue
                                elif msg_type == 'job_start':
                                    job_msg = f"\n▶ Starting: {data.get('job_name', 'Unknown')} ({data.get('job_num', 0)}/{data.get('total_jobs', 0)})\n"
                                    self.output.emit(job_msg)
                                    continue
                                elif msg_type == 'job_complete':
                                    status = "✓" if data.get('success', False) else "✗"
                                    job_msg = f"{status} Completed: {data.get('job_name', 'Unknown')} ({data.get('duration', 0):.1f}s)\n"
                                    self.output.emit(job_msg)
                                    continue
                                elif msg_type == 'summary':
                                    self.output.emit(f"\n{'=' * 60}\n")
                                    self.output.emit(
                                        f"Summary: {data.get('successful_jobs', 0)}/{data.get('total_jobs', 0)} successful\n")
                                    continue
                        except json.JSONDecodeError:
                            # Not JSON, just output as normal text
                            pass

                    # Output regular text
                    self.output.emit(line)

            self.process.wait()
            exit_code = self.process.returncode

            if exit_code == 0:
                self.output.emit("\n✓ Command completed successfully\n")
            else:
                self.output.emit(f"\n✗ Command failed with exit code {exit_code}\n")

            self.finished.emit(exit_code)

        except Exception as e:
            self.output.emit(f"\n✗ Error: {str(e)}\n")
            self.finished.emit(-1)

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)


class ProgressWidget(QFrame):
    """Custom widget for displaying job progress with progress bar and ETA"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        # Current job label
        self.job_label = QLabel("Ready")
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.job_label.setFont(font)
        layout.addWidget(self.job_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% (%v/%m jobs)")
        layout.addWidget(self.progress_bar)

        # Status and ETA labels
        status_layout = QHBoxLayout()

        self.status_label = QLabel("Idle")
        status_layout.addWidget(self.status_label)

        status_layout.addStretch()

        self.eta_label = QLabel("ETA: --:--")
        font = QFont()
        font.setPointSize(9)
        self.eta_label.setFont(font)
        status_layout.addWidget(self.eta_label)

        layout.addLayout(status_layout)

        self.setLayout(layout)

    def update_progress(self, data: dict):
        """Update progress display from progress data"""
        msg_type = data.get('type', '')

        if msg_type == 'job_start':
            job_name = data.get('job_name', 'Unknown')
            job_num = data.get('job_num', 0)
            total_jobs = data.get('total_jobs', 0)

            self.job_label.setText(f"Job: {job_name}")
            self.status_label.setText(f"Running ({job_num}/{total_jobs})")

            # Update progress bar max and value
            self.progress_bar.setMaximum(total_jobs)
            self.progress_bar.setValue(job_num - 1)  # -1 because job just started

        elif msg_type == 'job_complete':
            job_num = data.get('job_num', 0)
            total_jobs = data.get('total_jobs', 0)
            eta_seconds = data.get('eta_seconds')

            # Update progress bar
            self.progress_bar.setValue(job_num)

            # Update ETA
            if eta_seconds is not None and eta_seconds > 0:
                eta_str = self.format_time(eta_seconds)
                self.eta_label.setText(f"ETA: {eta_str}")
            else:
                self.eta_label.setText("ETA: Calculating...")

        elif msg_type == 'progress':
            current = data.get('current', 0)
            total = data.get('total', 0)
            percent = data.get('percent', 0)
            eta_seconds = data.get('eta_seconds')
            elapsed_seconds = data.get('elapsed_seconds', 0)

            # Update progress bar
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)

            # Update status
            self.status_label.setText(f"Progress: {current}/{total} jobs")

            # Update ETA
            if eta_seconds is not None and eta_seconds > 0:
                eta_str = self.format_time(eta_seconds)
                self.eta_label.setText(f"ETA: {eta_str}")
            elif current >= total:
                elapsed_str = self.format_time(elapsed_seconds)
                self.eta_label.setText(f"Completed in {elapsed_str}")
            else:
                self.eta_label.setText("ETA: Calculating...")

        elif msg_type == 'summary':
            successful = data.get('successful_jobs', 0)
            total = data.get('total_jobs', 0)
            total_time = data.get('total_time', 0)

            self.job_label.setText("Batch Complete")
            self.status_label.setText(f"{successful}/{total} successful")
            self.progress_bar.setValue(total)

            time_str = self.format_time(total_time)
            self.eta_label.setText(f"Completed in {time_str}")

    def format_time(self, seconds: float) -> str:
        """Format seconds into human-readable time string"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def reset(self):
        """Reset progress display"""
        self.job_label.setText("Ready")
        self.status_label.setText("Idle")
        self.eta_label.setText("ETA: --:--")
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)


class CommandDialog(QDialog):
    """Dialog for showing command output with progress tracking"""

    def __init__(self, parent, title, command, cwd=None, use_json_progress=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 700)

        layout = QVBoxLayout()

        # Progress widget (only shown if using JSON progress)
        self.use_json_progress = use_json_progress
        if use_json_progress:
            self.progress_widget = ProgressWidget()
            layout.addWidget(self.progress_widget)

        # Output text area
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Courier New', monospace;
                font-size: 10pt;
            }
        """)
        layout.addWidget(self.output)

        # Button layout
        btn_layout = QHBoxLayout()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_command)

        btn_layout.addStretch()
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # Start command runner
        self.runner = CommandRunner(command, cwd, json_mode=use_json_progress)
        self.runner.output.connect(self.append_output)
        self.runner.progress.connect(self.update_progress)
        self.runner.finished.connect(self.command_finished)
        self.runner.start()

    def append_output(self, text):
        self.output.insertPlainText(text)
        self.output.verticalScrollBar().setValue(
            self.output.verticalScrollBar().maximum()
        )

    def update_progress(self, data: dict):
        """Update progress widget with new data"""
        if self.use_json_progress:
            self.progress_widget.update_progress(data)

    def command_finished(self, exit_code):
        self.stop_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

        if exit_code == 0:
            self.setWindowTitle(f"{self.windowTitle()} - Completed")
        else:
            self.setWindowTitle(f"{self.windowTitle()} - Failed")

    def stop_command(self):
        self.runner.stop()
        self.stop_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.append_output("\n✗ Command stopped by user\n")
        if self.use_json_progress:
            self.progress_widget.reset()

    def closeEvent(self, event):
        if self.runner.isRunning():
            reply = QMessageBox.question(
                self,
                'Command Running',
                'Command is still running. Stop it?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.runner.stop()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


class SingleInstanceManager:
    """Ensures only one instance of the application runs"""

    def __init__(self, app_id):
        self.app_id = app_id
        self.server = None
        self.socket = QLocalSocket()

    def is_running(self):
        """Check if another instance is already running"""
        self.socket.connectToServer(self.app_id)

        if self.socket.waitForConnected(500):
            return True

        # No existing instance, create server
        self.server = QLocalServer()
        self.server.removeServer(self.app_id)

        if not self.server.listen(self.app_id):
            return True

        return False

    def cleanup(self):
        """Cleanup server on exit"""
        if self.server:
            self.server.close()


class NetworkAssetApp(QMainWindow):
    """Main application window"""

    def __init__(self, project_root):
        super().__init__()
        self.project_root = Path(project_root)
        self.pcng_dir = self.project_root / "pcng"
        self.web_process = None

        self.setWindowTitle("Network Asset Manager")
        self.resize(1400, 900)

        # Create web view
        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)

        # Create menu
        self.create_menu()

        # Start web server
        self.start_web_server()

        # Load the application after a short delay
        QTimer.singleShot(2000, self.load_app)

    def create_menu(self):
        """Create application menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        reload_action = QAction("Reload", self)
        reload_action.setShortcut("Ctrl+R")
        reload_action.triggered.connect(self.reload_page)
        file_menu.addAction(reload_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Utilities menu
        utils_menu = menubar.addMenu("&Utilities")

        # Data pipeline submenu
        pipeline_menu = QMenu("Data Pipeline", self)

        juniper_action = QAction("Run Juniper Jobs", self)
        juniper_action.triggered.connect(self.run_juniper_jobs)
        pipeline_menu.addAction(juniper_action)

        cisco_action = QAction("Run Cisco Jobs", self)
        cisco_action.triggered.connect(self.run_cisco_jobs)
        pipeline_menu.addAction(cisco_action)

        arista_action = QAction("Run Arista Jobs", self)
        arista_action.triggered.connect(self.run_arista_jobs)
        pipeline_menu.addAction(arista_action)

        pipeline_menu.addSeparator()

        all_jobs_action = QAction("Run All Vendor Jobs", self)
        all_jobs_action.triggered.connect(self.run_all_jobs)
        pipeline_menu.addAction(all_jobs_action)

        utils_menu.addMenu(pipeline_menu)
        utils_menu.addSeparator()

        # Data loading
        load_captures_action = QAction("Load Captures", self)
        load_captures_action.triggered.connect(self.load_captures)
        utils_menu.addAction(load_captures_action)

        load_inventory_action = QAction("Load Inventory", self)
        load_inventory_action.triggered.connect(self.load_inventory)
        utils_menu.addAction(load_inventory_action)

        utils_menu.addSeparator()

        # Full pipeline
        full_pipeline_action = QAction("Run Full Pipeline", self)
        full_pipeline_action.setShortcut("Ctrl+Shift+P")
        full_pipeline_action.triggered.connect(self.run_full_pipeline)
        utils_menu.addAction(full_pipeline_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def start_web_server(self):
        """Start the Flask web application"""
        try:
            cmd = f"{sys.executable} -m app.run"
            self.web_process = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"Started web server (PID: {self.web_process.pid})")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Startup Error",
                f"Failed to start web server:\n{str(e)}"
            )

    def load_app(self):
        """Load the web application in the browser"""
        self.browser.setUrl(QUrl("http://localhost:8086"))

    def reload_page(self):
        """Reload the current page"""
        self.browser.reload()

    def run_command(self, title, command, cwd=None, use_json_progress=False):
        """Run a command and show output dialog"""
        dialog = CommandDialog(self, title, command, cwd, use_json_progress)
        dialog.exec()

    def run_juniper_jobs(self):
        """Run Juniper device jobs"""
        cmd = "python run_jobs_batch.py ./job_batch_juniper.txt --jobs-folder ./ --json-progress"
        self.run_command("Juniper Jobs", cmd, str(self.pcng_dir), use_json_progress=True)

    def run_cisco_jobs(self):
        """Run Cisco device jobs"""
        # Note: If run_cisco_jobs.py doesn't support --json-progress yet, omit it
        cmd = "python run_cisco_jobs.py ./jobs_cisco.txt --jobs-folder ./"
        self.run_command("Cisco Jobs", cmd, str(self.pcng_dir), use_json_progress=False)

    def run_arista_jobs(self):
        """Run Arista device jobs"""
        cmd = "python run_jobs_batch.py ./job_batch_arista.txt --jobs-folder ./ --json-progress"
        self.run_command("Arista Jobs", cmd, str(self.pcng_dir), use_json_progress=True)

    def run_all_jobs(self):
        """Run all vendor jobs sequentially"""
        # Note: Chained commands can't use JSON progress effectively, so disable it
        cmd = (
            "python run_jobs_batch.py ./job_batch_juniper.txt --jobs-folder ./ && "
            "python run_cisco_jobs.py ./jobs_cisco.txt --jobs-folder ./ && "
            "python run_jobs_batch.py ./job_batch_arista.txt --jobs-folder ./"
        )
        self.run_command("All Vendor Jobs", cmd, str(self.pcng_dir), use_json_progress=False)

    def load_captures(self):
        """Load capture files into database"""
        cmd = "python db_load_capture.py --captures-dir capture --db-path ../assets.db"
        self.run_command("Load Captures", cmd, str(self.pcng_dir))

    def load_inventory(self):
        """Load inventory data into database"""
        cmd = "python ../db_loader_inventory.py --assets-db ../assets.db --textfsm-db tfsm_templates.db"
        self.run_command("Load Inventory", cmd, str(self.pcng_dir))

    def run_full_pipeline(self):
        """Run the complete data pipeline"""
        cmd = (
            "python run_jobs_batch.py ./job_batch_juniper.txt --jobs-folder ./ --json-progress && "
            "python run_cisco_jobs.py ./job_batch_cisco.txt --jobs-folder ./ --json-progress && "
            "python run_jobs_batch.py ./job_batch_arista.txt --jobs-folder ./ --json-progress && "
            "python db_load_capture.py --captures-dir capture --db-path ../assets.db && "
            "python ../db_loader_inventory.py --assets-db ../assets.db --textfsm-db tfsm_templates.db"
        )
        self.run_command("Full Pipeline", cmd, str(self.pcng_dir), use_json_progress=True)

    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About Network Asset Manager",
            "<h3>Network Asset Manager</h3>"
            "<p>Desktop application for managing network device assets</p>"
            "<p>Version 1.1 - With Progress Tracking</p>"
        )

    def closeEvent(self, event):
        """Clean shutdown of web server"""
        if self.web_process:
            print("Stopping web server...")
            self.web_process.terminate()
            try:
                self.web_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.web_process.kill()
        event.accept()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("Network Asset Manager")

    # Single instance check
    instance_manager = SingleInstanceManager("network-asset-manager-instance")

    if instance_manager.is_running():
        QMessageBox.warning(
            None,
            "Already Running",
            "Network Asset Manager is already running."
        )
        return 1

    # Determine project root (where app.run is located)
    # Assumes this script is in project root or adjust as needed
    project_root = os.getcwd()

    # Create and show main window
    window = NetworkAssetApp(project_root)
    window.show()

    # Run application
    exit_code = app.exec()

    # Cleanup
    instance_manager.cleanup()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())