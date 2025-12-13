# app/blueprints/terminal/routes.py
"""
SSH Terminal - Streamlined terminal interface for connection manager integration.
Supports:
- Session-based connections (from saved connections)
- Quick connect (ad-hoc)
- Direct connections (legacy support)
"""

from flask import render_template, request, jsonify, session, redirect, url_for, current_app
from flask_socketio import emit
from functools import wraps
from . import terminal_bp
from velocitycmdb.app import socketio
from velocitycmdb.app.utils.database import get_db_connection
import paramiko
import threading
import queue
import time
import io
import os
import sqlite3
import base64
import logging

logger = logging.getLogger(__name__)

# Store active SSH sessions
active_sessions = {}


def get_users_db():
    """Get connection to users database"""
    db_path = current_app.config.get('USERS_DATABASE')
    if not db_path:
        db_path = os.path.expanduser('~/.velocitycmdb/data/users.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_user_id():
    """Get the current user's database ID from their username"""
    username = session.get('username')
    if not username:
        return None

    try:
        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            return row['id'] if row else None
    except Exception as e:
        logger.error(f"Error getting user ID for {username}: {e}")
        return None


def login_required(f):
    """Decorator to require login for protected routes"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.is_json or request.path.startswith('/terminal/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


@terminal_bp.route('/')
@login_required
def index():
    """Redirect to connection manager - this is now the hub"""
    return redirect(url_for('connections.index'))


@terminal_bp.route('/session/<int:connection_id>')
@login_required
def session_terminal(connection_id):
    """Terminal for a saved connection - auto-connects on load"""
    user_id = get_current_user_id()
    if not user_id:
        return "User not found", 404

    # Get connection details from database
    try:
        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    sc.connection_name, sc.host, sc.port, sc.device_type,
                    uc.username
                FROM saved_connections sc
                LEFT JOIN user_credentials uc ON sc.credential_id = uc.id
                WHERE sc.id = ? AND sc.user_id = ?
            """, (connection_id, user_id))

            row = cursor.fetchone()
            if not row:
                return "Connection not found", 404

            connection_info = {
                'id': connection_id,
                'name': row['connection_name'],
                'host': row['host'],
                'port': row['port'],
                'username': row['username'],
                'device_type': row['device_type'],
                'mode': 'session'
            }

            return render_template('terminal/session.html', connection=connection_info)

    except Exception as e:
        logger.error(f"Error loading session terminal: {e}")
        return f"Error: {str(e)}", 500


@terminal_bp.route('/device-connect', methods=['POST'])
@login_required
def device_connect():
    """Quick connect from device detail page - sets up session and redirects to terminal"""
    from cryptography.fernet import Fernet

    device_name = request.form.get('device_name', 'Device')
    host = request.form.get('host')
    port = request.form.get('port', 22, type=int)
    auth_mode = request.form.get('auth_mode', 'manual')

    if not host:
        return "Missing host", 400

    user_id = get_current_user_id()
    if not user_id:
        return "User not found", 404

    # Handle saved credential
    if auth_mode == 'saved':
        credential_id = request.form.get('credential_id', type=int)
        if not credential_id:
            return "No credential selected", 400

        # Check vault is unlocked
        if 'vault_key' not in session:
            return "Vault locked - please unlock in Connection Manager", 401

        try:
            key_bytes = base64.b64decode(session['vault_key'])
            fernet = Fernet(base64.urlsafe_b64encode(key_bytes[:32]))
        except Exception:
            return "Invalid vault key", 401

        # Get and decrypt credential
        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT username, password_encrypted, ssh_key_encrypted, ssh_key_passphrase_encrypted
                FROM user_credentials
                WHERE id = ? AND user_id = ?
            """, (credential_id, user_id))
            row = cursor.fetchone()

            if not row:
                return "Credential not found", 404

            username = row['username']
            password = None
            private_key = None
            key_passphrase = None

            if row['password_encrypted']:
                password = fernet.decrypt(row['password_encrypted'].encode()).decode()

            if row['ssh_key_encrypted']:
                private_key = fernet.decrypt(row['ssh_key_encrypted'].encode()).decode()

            if row['ssh_key_passphrase_encrypted']:
                key_passphrase = fernet.decrypt(row['ssh_key_passphrase_encrypted'].encode()).decode()

        # Store in session for quick terminal
        session['quick_connect'] = {
            'device_name': device_name,
            'host': host,
            'username': username,
            'password': password,
            'private_key': private_key,
            'key_passphrase': key_passphrase,
            'port': port
        }
    else:
        # Manual credential entry
        username = request.form.get('username')
        password = request.form.get('password')

        if not username:
            return "Missing username", 400

        # Store in session for quick terminal
        session['quick_connect'] = {
            'device_name': device_name,
            'host': host,
            'username': username,
            'password': password,
            'port': port
        }

    return redirect(url_for('terminal.quick_terminal'))


@terminal_bp.route('/quick')
@login_required
def quick_terminal():
    """Terminal for quick connect (ad-hoc connection)"""
    quick_data = session.get('quick_connect')

    if not quick_data:
        return redirect(url_for('connections.index'))

    connection_info = {
        'id': None,
        'name': quick_data.get('device_name', quick_data['host']),
        'host': quick_data['host'],
        'port': quick_data.get('port', 22),
        'username': quick_data['username'],
        'device_type': None,
        'mode': 'quick'
    }

    return render_template('terminal/session.html', connection=connection_info)


@terminal_bp.route('/direct')
@login_required
def direct_terminal():
    """Direct terminal access with device selector (legacy mode)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
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
            return render_template('terminal/direct.html', devices=devices)
    except Exception as e:
        logger.error(f"Error loading direct terminal: {e}")
        return render_template('terminal/direct.html', devices=[], error=str(e))


class SSHSession:
    """Manage an SSH connection and channel"""

    def __init__(self, host, username, password=None, port=22,
                 private_key=None, key_passphrase=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.key_passphrase = key_passphrase
        self.client = None
        self.channel = None
        self.output_queue = queue.Queue()
        self.running = False

    def connect(self):
        """Establish SSH connection"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Prepare connection kwargs
            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.username,
                'timeout': 10,
                'look_for_keys': False,
                'allow_agent': False
            }

            # Use private key if provided
            if self.private_key:
                key_file = io.StringIO(self.private_key)
                pkey = None

                # Try different key types
                for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
                    try:
                        key_file.seek(0)
                        pkey = key_class.from_private_key(
                            key_file,
                            password=self.key_passphrase if self.key_passphrase else None
                        )
                        break
                    except:
                        continue

                if pkey:
                    connect_kwargs['pkey'] = pkey
                else:
                    return False, "Unable to parse SSH private key"
            else:
                connect_kwargs['password'] = self.password

            self.client.connect(**connect_kwargs)

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

        except paramiko.AuthenticationException:
            return False, "Authentication failed - check credentials"
        except paramiko.SSHException as e:
            return False, f"SSH error: {str(e)}"
        except Exception as e:
            return False, str(e)

    def _read_output(self):
        """Read output from SSH channel"""
        while self.running and self.channel:
            try:
                # Check if channel was closed by remote end
                if self.channel.closed or self.channel.exit_status_ready():
                    self.running = False
                    self.output_queue.put(None)  # Sentinel for disconnect
                    break

                if self.channel.recv_ready():
                    data = self.channel.recv(4096)
                    if data:
                        self.output_queue.put(data.decode('utf-8', errors='ignore'))
                    else:
                        # Empty recv = EOF (remote closed)
                        self.running = False
                        self.output_queue.put(None)  # Sentinel for disconnect
                        break
                else:
                    time.sleep(0.01)
            except Exception:
                self.running = False
                self.output_queue.put(None)  # Sentinel for disconnect
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


# ============================================================================
# WebSocket Handlers
# ============================================================================

@socketio.on('connect', namespace='/terminal')
def handle_connect():
    """Handle WebSocket connection"""
    # Check if user is authenticated
    if not session.get('logged_in'):
        return False

    logger.debug(f"Terminal client connected: {request.sid}")
    emit('status', {'message': 'Connected to terminal server'})


@socketio.on('disconnect', namespace='/terminal')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    socket_id = request.sid
    logger.debug(f"Terminal client disconnected: {socket_id}")

    if socket_id in active_sessions:
        active_sessions[socket_id].close()
        del active_sessions[socket_id]


@socketio.on('start_session', namespace='/terminal')
def handle_start_session(data):
    """Start SSH session to device"""
    socket_id = request.sid

    try:
        host = data.get('host')
        username = data.get('username')
        password = data.get('password')
        port = data.get('port', 22)
        private_key = data.get('private_key')
        key_passphrase = data.get('key_passphrase')

        if not host or not username:
            emit('error', {'message': 'Missing required connection parameters'})
            return

        if not password and not private_key:
            emit('error', {'message': 'Password or SSH key required'})
            return

        # Close existing session if any
        if socket_id in active_sessions:
            active_sessions[socket_id].close()

        # Create new SSH session
        ssh_session = SSHSession(
            host=host,
            username=username,
            password=password,
            port=port,
            private_key=private_key,
            key_passphrase=key_passphrase
        )

        result = ssh_session.connect()

        if result is True:
            active_sessions[socket_id] = ssh_session
            emit('connected', {'message': f'Connected to {host}'})
            logger.info(f"SSH session started to {host} by {session.get('username')}")

            # Start sending output
            def send_output():
                while socket_id in active_sessions:
                    try:
                        output = active_sessions[socket_id].output_queue.get(timeout=0.1)

                        # None is the disconnect sentinel from _read_output
                        if output is None:
                            socketio.emit('server_disconnected',
                                          {'message': 'Connection closed by remote host'},
                                          namespace='/terminal', room=socket_id)
                            # Clean up
                            if socket_id in active_sessions:
                                active_sessions[socket_id].close()
                                del active_sessions[socket_id]
                            break

                        socketio.emit('output', {'data': output},
                                      namespace='/terminal', room=socket_id)
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
        logger.error(f"Error starting SSH session: {e}")
        emit('error', {'message': f'Error: {str(e)}'})


@socketio.on('input', namespace='/terminal')
def handle_input(data):
    """Handle terminal input"""
    socket_id = request.sid

    if socket_id in active_sessions:
        input_data = data.get('data', '')
        active_sessions[socket_id].write(input_data)


@socketio.on('resize', namespace='/terminal')
def handle_resize(data):
    """Handle terminal resize"""
    socket_id = request.sid

    if socket_id in active_sessions:
        cols = data.get('cols', 80)
        rows = data.get('rows', 24)
        active_sessions[socket_id].resize(cols, rows)


# ============================================================================
# API Endpoints
# ============================================================================

@terminal_bp.route('/api/session-credentials/<int:connection_id>', methods=['POST'])
@login_required
def get_session_credentials(connection_id):
    """Get decrypted credentials for a saved connection session"""
    from cryptography.fernet import Fernet

    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    if 'vault_key' not in session:
        return jsonify({'status': 'error', 'message': 'Vault locked'}), 401

    try:
        key_bytes = base64.b64decode(session['vault_key'])
        fernet = Fernet(base64.urlsafe_b64encode(key_bytes[:32]))
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid vault key'}), 401

    with get_users_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                sc.host, sc.port,
                uc.username, uc.password_encrypted, 
                uc.ssh_key_encrypted, uc.ssh_key_passphrase_encrypted
            FROM saved_connections sc
            LEFT JOIN user_credentials uc ON sc.credential_id = uc.id
            WHERE sc.id = ? AND sc.user_id = ?
        """, (connection_id, user_id))

        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Connection not found'}), 404

        if not row['username']:
            return jsonify({'status': 'error', 'message': 'No credential linked to this connection'}), 400

        result = {
            'host': row['host'],
            'port': row['port'],
            'username': row['username']
        }

        if row['password_encrypted']:
            result['password'] = fernet.decrypt(row['password_encrypted'].encode()).decode()

        if row['ssh_key_encrypted']:
            result['private_key'] = fernet.decrypt(row['ssh_key_encrypted'].encode()).decode()

        if row['ssh_key_passphrase_encrypted']:
            result['key_passphrase'] = fernet.decrypt(
                row['ssh_key_passphrase_encrypted'].encode()
            ).decode()

    return jsonify({'status': 'success', 'credentials': result})


@terminal_bp.route('/api/quick-credentials', methods=['POST'])
@login_required
def get_quick_credentials():
    """Get credentials for quick connect session"""
    quick_data = session.get('quick_connect')

    if not quick_data:
        return jsonify({'status': 'error', 'message': 'No quick connect session'}), 404

    credentials = {
        'host': quick_data['host'],
        'port': quick_data.get('port', 22),
        'username': quick_data['username'],
        'password': quick_data.get('password', '')
    }

    # Include SSH key fields if present
    if quick_data.get('private_key'):
        credentials['private_key'] = quick_data['private_key']
    if quick_data.get('key_passphrase'):
        credentials['key_passphrase'] = quick_data['key_passphrase']

    return jsonify({
        'status': 'success',
        'credentials': credentials
    })


# ============================================================================
# Cleanup
# ============================================================================

def cleanup_stale_sessions():
    """Background thread to cleanup stale sessions"""
    while True:
        time.sleep(300)  # Every 5 minutes
        stale = []
        for sid, ssh_session in list(active_sessions.items()):
            if not ssh_session.running:
                stale.append(sid)
        for sid in stale:
            try:
                active_sessions[sid].close()
                del active_sessions[sid]
                logger.debug(f"Cleaned up stale session: {sid}")
            except:
                pass


# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_stale_sessions, daemon=True)
cleanup_thread.start()