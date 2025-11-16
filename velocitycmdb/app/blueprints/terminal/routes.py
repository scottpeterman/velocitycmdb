# app/blueprints/terminal/routes.py
from flask import render_template, request, jsonify, session
from flask_socketio import emit, disconnect
from . import terminal_bp
from velocitycmdb.app import socketio
from velocitycmdb.app.utils.database import get_db_connection
import paramiko
import threading
import queue
import time

# Store active SSH sessions
active_sessions = {}


@terminal_bp.route('/')
def index():
    """SSH terminal interface"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Get all devices with management IPs
            cursor.execute("""
                SELECT 
                    d.id, d.name, d.management_ip, 
                    v.name as vendor_name, d.model, d.site_code
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE d.management_ip IS NOT NULL AND d.management_ip != ''
                ORDER BY d.name
            """)

            devices = [dict(row) for row in cursor.fetchall()]

            return render_template('terminal/index.html', devices=devices)

    except Exception as e:
        return render_template('terminal/index.html', devices=[], error=str(e))


@terminal_bp.route('/api/devices')
def api_devices():
    """API endpoint to get devices for SSH"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    d.id, d.name, d.management_ip, 
                    v.name as vendor_name, d.model
                FROM devices d
                LEFT JOIN vendors v ON d.vendor_id = v.id
                WHERE d.management_ip IS NOT NULL AND d.management_ip != ''
                ORDER BY d.name
            """)

            devices = [dict(row) for row in cursor.fetchall()]

            return jsonify({'devices': devices, 'status': 'success'})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


class SSHSession:
    """Manage an SSH connection and channel"""

    def __init__(self, host, username, password, port=22):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client = None
        self.channel = None
        self.output_queue = queue.Queue()
        self.running = False

    def connect(self):
        """Establish SSH connection"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=10,
                look_for_keys=False,
                allow_agent=False
            )

            # Get interactive shell
            self.channel = self.client.invoke_shell(
                term='xterm-256color',
                width=120,
                height=40
            )

            self.running = True

            # Start output reader thread
            reader_thread = threading.Thread(target=self._read_output)
            reader_thread.daemon = True
            reader_thread.start()

            return True

        except Exception as e:
            return False, str(e)

    def _read_output(self):
        """Read output from SSH channel"""
        while self.running and self.channel:
            try:
                if self.channel.recv_ready():
                    data = self.channel.recv(4096)
                    if data:
                        self.output_queue.put(data.decode('utf-8', errors='ignore'))
                else:
                    time.sleep(0.01)
            except Exception as e:
                self.running = False
                break

    def write(self, data):
        """Send data to SSH channel"""
        if self.channel and self.running:
            try:
                self.channel.send(data)
                return True
            except:
                return False
        return False

    def resize(self, cols, rows):
        """Resize terminal"""
        if self.channel and self.running:
            try:
                self.channel.resize_pty(width=cols, height=rows)
            except:
                pass

    def close(self):
        """Close SSH connection"""
        self.running = False
        if self.channel:
            try:
                self.channel.close()
            except:
                pass
        if self.client:
            try:
                self.client.close()
            except:
                pass


@socketio.on('connect', namespace='/terminal')
def handle_connect():
    """Handle WebSocket connection"""
    print(f"Client connected: {request.sid}")
    emit('status', {'message': 'Connected to terminal server'})


@socketio.on('disconnect', namespace='/terminal')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    session_id = request.sid
    print(f"Client disconnected: {session_id}")

    # Close SSH session if exists
    if session_id in active_sessions:
        active_sessions[session_id].close()
        del active_sessions[session_id]


@socketio.on('start_session', namespace='/terminal')
def handle_start_session(data):
    """Start SSH session to device"""
    session_id = request.sid

    try:
        host = data.get('host')
        username = data.get('username')
        password = data.get('password')
        port = data.get('port', 22)

        if not all([host, username, password]):
            emit('error', {'message': 'Missing required credentials'})
            return

        # Close existing session if any
        if session_id in active_sessions:
            active_sessions[session_id].close()

        # Create new SSH session
        ssh_session = SSHSession(host, username, password, port)
        result = ssh_session.connect()

        if result is True:
            active_sessions[session_id] = ssh_session
            emit('connected', {'message': f'Connected to {host}'})

            # Start sending output
            def send_output():
                while session_id in active_sessions:
                    try:
                        output = active_sessions[session_id].output_queue.get(timeout=0.1)
                        socketio.emit('output', {'data': output},
                                      namespace='/terminal', room=session_id)
                    except queue.Empty:
                        continue
                    except:
                        break

            output_thread = threading.Thread(target=send_output)
            output_thread.daemon = True
            output_thread.start()
        else:
            emit('error', {'message': f'Connection failed: {result[1]}'})

    except Exception as e:
        emit('error', {'message': f'Error: {str(e)}'})


@socketio.on('input', namespace='/terminal')
def handle_input(data):
    """Handle terminal input"""
    session_id = request.sid

    if session_id in active_sessions:
        input_data = data.get('data', '')
        active_sessions[session_id].write(input_data)

def cleanup_stale_sessions():
    while True:
        time.sleep(300)  # Every 5 minutes
        stale = []
        for sid, session in active_sessions.items():
            if not session.running:
                stale.append(sid)
        for sid in stale:
            try:
                active_sessions[sid].close()
                del active_sessions[sid]
            except:
                pass

@socketio.on('disconnect', namespace='/terminal')
def handle_disconnect():
    session_id = request.sid
    if session_id in active_sessions:
        active_sessions[session_id].close()
        del active_sessions[session_id]

@socketio.on('resize', namespace='/terminal')
def handle_resize(data):
    """Handle terminal resize"""
    session_id = request.sid

    if session_id in active_sessions:
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        active_sessions[session_id].resize(cols, rows)

cleanup_thread = threading.Thread(target=cleanup_stale_sessions, daemon=True)
cleanup_thread.start()