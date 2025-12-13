# app/blueprints/connections/routes.py
"""
Connection Manager - Credential Vault and Saved Connections
Provides secure credential storage and connection management for SSH sessions.
"""

from flask import render_template, request, jsonify, session, redirect, url_for, current_app
from functools import wraps
from . import connections_bp
from velocitycmdb.app.utils.database import get_db_connection
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import sqlite3
import base64
import os
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


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
            if request.is_json or request.path.startswith('/connections/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


def init_credential_tables():
    """Initialize credential and connection tables if they don't exist"""
    try:
        with get_users_db() as conn:
            cursor = conn.cursor()

            # User credential vault
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    credential_name TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password_encrypted TEXT,
                    ssh_key_encrypted TEXT,
                    ssh_key_passphrase_encrypted TEXT,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            # Saved connections
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS saved_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    connection_name TEXT NOT NULL,
                    device_id INTEGER,
                    host TEXT NOT NULL,
                    port INTEGER DEFAULT 22,
                    credential_id INTEGER,
                    device_type TEXT,
                    notes TEXT,
                    color_tag TEXT,
                    last_used TEXT,
                    use_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (credential_id) REFERENCES user_credentials(id) ON DELETE SET NULL
                )
            """)

            # Master password hash (for vault encryption)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_vault_keys (
                    user_id INTEGER PRIMARY KEY,
                    key_salt TEXT NOT NULL,
                    key_check TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            conn.commit()
            logger.info("Credential tables initialized")
    except Exception as e:
        logger.error(f"Error initializing credential tables: {e}")


class CredentialVault:
    """Handles encryption/decryption of credentials using Fernet with user master password"""

    CHECK_VALUE = "VELOCITYCMDB_VAULT_CHECK"

    @staticmethod
    def derive_key(password: str, salt: bytes) -> bytes:
        """Derive encryption key from master password"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    @classmethod
    def setup_vault(cls, user_id: int, master_password: str) -> bool:
        """Initialize vault for user with master password"""
        salt = os.urandom(16)
        key = cls.derive_key(master_password, salt)
        fernet = Fernet(key)

        # Encrypt check value to verify password later
        check_encrypted = fernet.encrypt(cls.CHECK_VALUE.encode()).decode()

        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_vault_keys (user_id, key_salt, key_check, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, base64.b64encode(salt).decode(), check_encrypted,
                  datetime.utcnow().isoformat()))
            conn.commit()

        return True

    @classmethod
    def verify_master_password(cls, user_id: int, master_password: str) -> tuple:
        """Verify master password and return Fernet instance if valid"""
        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT key_salt, key_check FROM user_vault_keys WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()

            if not row:
                return False, None

            salt = base64.b64decode(row['key_salt'])
            key = cls.derive_key(master_password, salt)
            fernet = Fernet(key)

            try:
                decrypted = fernet.decrypt(row['key_check'].encode()).decode()
                if decrypted == cls.CHECK_VALUE:
                    return True, fernet
            except InvalidToken:
                pass

            return False, None

    @classmethod
    def has_vault(cls, user_id: int) -> bool:
        """Check if user has initialized vault"""
        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM user_vault_keys WHERE user_id = ?",
                (user_id,)
            )
            return cursor.fetchone() is not None

    @classmethod
    def reset_vault(cls, user_id: int, new_master_password: str) -> bool:
        """Reset vault with new master password (deletes all credentials)"""
        with get_users_db() as conn:
            cursor = conn.cursor()

            # Delete all user credentials
            cursor.execute("DELETE FROM user_credentials WHERE user_id = ?", (user_id,))

            # Clear credential references from connections
            cursor.execute(
                "UPDATE saved_connections SET credential_id = NULL WHERE user_id = ?",
                (user_id,)
            )

            # Delete old vault key
            cursor.execute("DELETE FROM user_vault_keys WHERE user_id = ?", (user_id,))

            conn.commit()

        # Setup new vault
        return cls.setup_vault(user_id, new_master_password)


def vault_session_required(f):
    """Decorator to ensure vault session is active"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'vault_key' not in session:
            return jsonify({
                'status': 'error',
                'message': 'Vault locked. Please unlock with master password.',
                'code': 'VAULT_LOCKED'
            }), 401
        return f(*args, **kwargs)

    return decorated_function


def get_fernet_from_session():
    """Reconstruct Fernet from session key"""
    if 'vault_key' not in session:
        return None
    try:
        key_bytes = base64.b64decode(session['vault_key'])
        return Fernet(base64.urlsafe_b64encode(key_bytes[:32]))
    except Exception:
        return None


# ============================================================================
# ROUTES - Connection Manager UI
# ============================================================================

@connections_bp.route('/')
@login_required
def index():
    """Connection manager main page"""
    # Initialize tables on first access
    init_credential_tables()

    user_id = get_current_user_id()
    if not user_id:
        return render_template('connections/index.html',
                               has_vault=False,
                               vault_unlocked=False,
                               connections=[],
                               credentials=[],
                               devices=[],
                               error="User account not found")

    has_vault = CredentialVault.has_vault(user_id)
    vault_unlocked = 'vault_key' in session

    # Get saved connections
    connections = []
    credentials = []

    if vault_unlocked:
        with get_users_db() as conn:
            cursor = conn.cursor()

            # Get connections with credential info
            cursor.execute("""
                SELECT 
                    sc.id, sc.connection_name, sc.host, sc.port, 
                    sc.device_id, sc.device_type, sc.notes, sc.color_tag,
                    sc.last_used, sc.use_count, sc.credential_id,
                    uc.credential_name, uc.username
                FROM saved_connections sc
                LEFT JOIN user_credentials uc ON sc.credential_id = uc.id
                WHERE sc.user_id = ?
                ORDER BY sc.last_used DESC NULLS LAST, sc.connection_name
            """, (user_id,))
            connections = [dict(row) for row in cursor.fetchall()]

            # Get credentials list (without passwords)
            cursor.execute("""
                SELECT id, credential_name, username, is_default, created_at,
                       CASE WHEN ssh_key_encrypted IS NOT NULL THEN 1 ELSE 0 END as has_ssh_key
                FROM user_credentials
                WHERE user_id = ?
                ORDER BY is_default DESC, credential_name
            """, (user_id,))
            credentials = [dict(row) for row in cursor.fetchall()]

    # Get devices from main database
    devices = []
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
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")

    return render_template('connections/index.html',
                           has_vault=has_vault,
                           vault_unlocked=vault_unlocked,
                           connections=connections,
                           credentials=credentials,
                           devices=devices)


# ============================================================================
# ROUTES - Vault Management API
# ============================================================================

@connections_bp.route('/api/vault/status')
@login_required
def vault_status():
    """Get vault status for current user"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({
        'has_vault': CredentialVault.has_vault(user_id),
        'unlocked': 'vault_key' in session
    })


@connections_bp.route('/api/vault/setup', methods=['POST'])
@login_required
def vault_setup():
    """Initialize vault with master password"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()
    master_password = data.get('master_password', '')

    if len(master_password) < 8:
        return jsonify({
            'status': 'error',
            'message': 'Master password must be at least 8 characters'
        }), 400

    if CredentialVault.has_vault(user_id):
        return jsonify({
            'status': 'error',
            'message': 'Vault already exists. Use reset to change password.'
        }), 400

    CredentialVault.setup_vault(user_id, master_password)

    # Auto-unlock after setup
    valid, fernet = CredentialVault.verify_master_password(user_id, master_password)
    if valid:
        session['vault_key'] = base64.b64encode(fernet._signing_key + fernet._encryption_key).decode()

    logger.info(f"Vault created for user {session.get('username')}")
    return jsonify({'status': 'success', 'message': 'Vault initialized'})


@connections_bp.route('/api/vault/unlock', methods=['POST'])
@login_required
def vault_unlock():
    """Unlock vault with master password"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()
    master_password = data.get('master_password', '')

    valid, fernet = CredentialVault.verify_master_password(user_id, master_password)

    if valid:
        session['vault_key'] = base64.b64encode(fernet._signing_key + fernet._encryption_key).decode()
        logger.info(f"Vault unlocked for user {session.get('username')}")
        return jsonify({'status': 'success', 'message': 'Vault unlocked'})

    return jsonify({'status': 'error', 'message': 'Invalid master password'}), 401


@connections_bp.route('/api/vault/lock', methods=['POST'])
@login_required
def vault_lock():
    """Lock vault"""
    session.pop('vault_key', None)
    logger.info(f"Vault locked for user {session.get('username')}")
    return jsonify({'status': 'success', 'message': 'Vault locked'})


@connections_bp.route('/api/vault/reset', methods=['POST'])
@login_required
def vault_reset():
    """Reset vault with new master password (deletes all credentials)"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()
    new_password = data.get('new_master_password', '')
    confirm = data.get('confirm_reset', False)

    if not confirm:
        return jsonify({'status': 'error', 'message': 'Must confirm reset'}), 400

    if len(new_password) < 8:
        return jsonify({
            'status': 'error',
            'message': 'Master password must be at least 8 characters'
        }), 400

    # Clear session
    session.pop('vault_key', None)

    # Reset vault
    CredentialVault.reset_vault(user_id, new_password)

    # Auto-unlock with new password
    valid, fernet = CredentialVault.verify_master_password(user_id, new_password)
    if valid:
        session['vault_key'] = base64.b64encode(fernet._signing_key + fernet._encryption_key).decode()

    logger.info(f"Vault reset for user {session.get('username')}")
    return jsonify({'status': 'success', 'message': 'Vault reset successfully'})


# ============================================================================
# ROUTES - Credential Management API
# ============================================================================

@connections_bp.route('/api/credentials', methods=['GET'])
@login_required
@vault_session_required
def list_credentials():
    """List all credentials (without passwords)"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, credential_name, username, is_default, 
                   created_at, updated_at,
                   CASE WHEN ssh_key_encrypted IS NOT NULL THEN 1 ELSE 0 END as has_ssh_key
            FROM user_credentials
            WHERE user_id = ?
            ORDER BY is_default DESC, credential_name
        """, (user_id,))
        credentials = [dict(row) for row in cursor.fetchall()]

    return jsonify({'status': 'success', 'credentials': credentials})


@connections_bp.route('/api/credentials', methods=['POST'])
@login_required
@vault_session_required
def create_credential():
    """Create new credential"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()

    credential_name = data.get('credential_name', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    ssh_key = data.get('ssh_key', '')
    ssh_key_passphrase = data.get('ssh_key_passphrase', '')
    is_default = data.get('is_default', False)

    if not credential_name or not username:
        return jsonify({
            'status': 'error',
            'message': 'Credential name and username are required'
        }), 400

    if not password and not ssh_key:
        return jsonify({
            'status': 'error',
            'message': 'Either password or SSH key is required'
        }), 400

    fernet = get_fernet_from_session()
    if not fernet:
        return jsonify({'status': 'error', 'message': 'Vault key invalid'}), 401

    # Encrypt sensitive data
    password_encrypted = fernet.encrypt(password.encode()).decode() if password else None
    ssh_key_encrypted = fernet.encrypt(ssh_key.encode()).decode() if ssh_key else None
    ssh_passphrase_encrypted = fernet.encrypt(ssh_key_passphrase.encode()).decode() if ssh_key_passphrase else None

    now = datetime.utcnow().isoformat()

    with get_users_db() as conn:
        cursor = conn.cursor()

        # If setting as default, clear other defaults
        if is_default:
            cursor.execute(
                "UPDATE user_credentials SET is_default = 0 WHERE user_id = ?",
                (user_id,)
            )

        cursor.execute("""
            INSERT INTO user_credentials 
            (user_id, credential_name, username, password_encrypted, 
             ssh_key_encrypted, ssh_key_passphrase_encrypted, is_default, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, credential_name, username, password_encrypted,
              ssh_key_encrypted, ssh_passphrase_encrypted, 1 if is_default else 0, now))

        credential_id = cursor.lastrowid
        conn.commit()

    logger.info(f"Credential '{credential_name}' created for user {session.get('username')}")
    return jsonify({
        'status': 'success',
        'message': 'Credential created',
        'credential_id': credential_id
    })


@connections_bp.route('/api/credentials/<int:credential_id>', methods=['GET'])
@login_required
@vault_session_required
def get_credential(credential_id):
    """Get credential details (without sensitive data)"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, credential_name, username, is_default, created_at, updated_at,
                   CASE WHEN ssh_key_encrypted IS NOT NULL THEN 1 ELSE 0 END as has_ssh_key
            FROM user_credentials
            WHERE id = ? AND user_id = ?
        """, (credential_id, user_id))
        row = cursor.fetchone()

        if not row:
            return jsonify({'status': 'error', 'message': 'Credential not found'}), 404

        return jsonify({'status': 'success', 'credential': dict(row)})


@connections_bp.route('/api/credentials/<int:credential_id>', methods=['PUT'])
@login_required
@vault_session_required
def update_credential(credential_id):
    """Update credential"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()

    fernet = get_fernet_from_session()
    if not fernet:
        return jsonify({'status': 'error', 'message': 'Vault key invalid'}), 401

    with get_users_db() as conn:
        cursor = conn.cursor()

        # Verify ownership
        cursor.execute(
            "SELECT id FROM user_credentials WHERE id = ? AND user_id = ?",
            (credential_id, user_id)
        )
        if not cursor.fetchone():
            return jsonify({'status': 'error', 'message': 'Credential not found'}), 404

        updates = []
        params = []

        if 'credential_name' in data:
            updates.append("credential_name = ?")
            params.append(data['credential_name'].strip())

        if 'username' in data:
            updates.append("username = ?")
            params.append(data['username'].strip())

        if 'password' in data and data['password']:
            updates.append("password_encrypted = ?")
            params.append(fernet.encrypt(data['password'].encode()).decode())

        if 'ssh_key' in data:
            if data['ssh_key']:
                updates.append("ssh_key_encrypted = ?")
                params.append(fernet.encrypt(data['ssh_key'].encode()).decode())
            else:
                updates.append("ssh_key_encrypted = NULL")

        if 'ssh_key_passphrase' in data:
            if data['ssh_key_passphrase']:
                updates.append("ssh_key_passphrase_encrypted = ?")
                params.append(fernet.encrypt(data['ssh_key_passphrase'].encode()).decode())
            else:
                updates.append("ssh_key_passphrase_encrypted = NULL")

        if 'is_default' in data:
            if data['is_default']:
                cursor.execute(
                    "UPDATE user_credentials SET is_default = 0 WHERE user_id = ?",
                    (user_id,)
                )
            updates.append("is_default = ?")
            params.append(1 if data['is_default'] else 0)

        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.utcnow().isoformat())
            params.append(credential_id)

            cursor.execute(
                f"UPDATE user_credentials SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()

    return jsonify({'status': 'success', 'message': 'Credential updated'})


@connections_bp.route('/api/credentials/<int:credential_id>', methods=['DELETE'])
@login_required
@vault_session_required
def delete_credential(credential_id):
    """Delete credential"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()

        # Verify ownership
        cursor.execute(
            "SELECT credential_name FROM user_credentials WHERE id = ? AND user_id = ?",
            (credential_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Credential not found'}), 404

        cursor.execute("DELETE FROM user_credentials WHERE id = ?", (credential_id,))
        conn.commit()

    logger.info(f"Credential '{row['credential_name']}' deleted for user {session.get('username')}")
    return jsonify({'status': 'success', 'message': 'Credential deleted'})


# ============================================================================
# ROUTES - Saved Connections API
# ============================================================================

@connections_bp.route('/api/connections', methods=['GET'])
@login_required
@vault_session_required
def list_connections():
    """List saved connections"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                sc.id, sc.connection_name, sc.host, sc.port, 
                sc.device_id, sc.device_type, sc.notes, sc.color_tag,
                sc.last_used, sc.use_count, sc.credential_id,
                uc.credential_name, uc.username
            FROM saved_connections sc
            LEFT JOIN user_credentials uc ON sc.credential_id = uc.id
            WHERE sc.user_id = ?
            ORDER BY sc.last_used DESC NULLS LAST, sc.connection_name
        """, (user_id,))
        connections = [dict(row) for row in cursor.fetchall()]

    return jsonify({'status': 'success', 'connections': connections})


@connections_bp.route('/api/connections', methods=['POST'])
@login_required
@vault_session_required
def create_connection():
    """Create saved connection"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()

    connection_name = data.get('connection_name', '').strip()
    host = data.get('host', '').strip()
    port = data.get('port', 22)
    device_id = data.get('device_id')
    device_type = data.get('device_type', '').strip() or None
    notes = data.get('notes', '').strip() or None
    color_tag = data.get('color_tag', '').strip() or None
    credential_id = data.get('credential_id')

    if not connection_name or not host:
        return jsonify({
            'status': 'error',
            'message': 'Connection name and host are required'
        }), 400

    # Verify credential ownership if provided
    if credential_id:
        with get_users_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM user_credentials WHERE id = ? AND user_id = ?",
                (credential_id, user_id)
            )
            if not cursor.fetchone():
                return jsonify({
                    'status': 'error',
                    'message': 'Credential not found'
                }), 404

    now = datetime.utcnow().isoformat()

    with get_users_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO saved_connections
            (user_id, connection_name, host, port, device_id, device_type,
             notes, color_tag, credential_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, connection_name, host, port, device_id, device_type,
              notes, color_tag, credential_id, now))
        connection_id = cursor.lastrowid
        conn.commit()

    logger.info(f"Connection '{connection_name}' created for user {session.get('username')}")
    return jsonify({
        'status': 'success',
        'message': 'Connection saved',
        'connection_id': connection_id
    })


@connections_bp.route('/api/connections/<int:connection_id>', methods=['GET'])
@login_required
@vault_session_required
def get_connection(connection_id):
    """Get connection details"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                sc.id, sc.connection_name, sc.host, sc.port, 
                sc.device_id, sc.device_type, sc.notes, sc.color_tag,
                sc.last_used, sc.use_count, sc.credential_id,
                uc.credential_name, uc.username
            FROM saved_connections sc
            LEFT JOIN user_credentials uc ON sc.credential_id = uc.id
            WHERE sc.id = ? AND sc.user_id = ?
        """, (connection_id, user_id))
        row = cursor.fetchone()

        if not row:
            return jsonify({'status': 'error', 'message': 'Connection not found'}), 404

        return jsonify({'status': 'success', 'connection': dict(row)})


@connections_bp.route('/api/connections/<int:connection_id>', methods=['PUT'])
@login_required
@vault_session_required
def update_connection(connection_id):
    """Update saved connection"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    data = request.get_json()

    with get_users_db() as conn:
        cursor = conn.cursor()

        # Verify ownership
        cursor.execute(
            "SELECT id FROM saved_connections WHERE id = ? AND user_id = ?",
            (connection_id, user_id)
        )
        if not cursor.fetchone():
            return jsonify({'status': 'error', 'message': 'Connection not found'}), 404

        updates = []
        params = []

        for field in ['connection_name', 'host', 'port', 'device_id', 'device_type',
                      'notes', 'color_tag', 'credential_id']:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field] if data[field] != '' else None)

        if updates:
            params.append(connection_id)
            cursor.execute(
                f"UPDATE saved_connections SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()

    return jsonify({'status': 'success', 'message': 'Connection updated'})


@connections_bp.route('/api/connections/<int:connection_id>', methods=['DELETE'])
@login_required
@vault_session_required
def delete_connection(connection_id):
    """Delete saved connection"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT connection_name FROM saved_connections WHERE id = ? AND user_id = ?",
            (connection_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Connection not found'}), 404

        cursor.execute("DELETE FROM saved_connections WHERE id = ?", (connection_id,))
        conn.commit()

    logger.info(f"Connection '{row['connection_name']}' deleted for user {session.get('username')}")
    return jsonify({'status': 'success', 'message': 'Connection deleted'})


@connections_bp.route('/api/connections/<int:connection_id>/launch', methods=['POST'])
@login_required
@vault_session_required
def launch_connection(connection_id):
    """Get connection details for launching terminal and update usage stats"""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404

    with get_users_db() as conn:
        cursor = conn.cursor()

        # Verify ownership and get basic info
        cursor.execute("""
            SELECT sc.id, sc.connection_name, sc.host, sc.port
            FROM saved_connections sc
            WHERE sc.id = ? AND sc.user_id = ?
        """, (connection_id, user_id))

        row = cursor.fetchone()
        if not row:
            return jsonify({'status': 'error', 'message': 'Connection not found'}), 404

        # Update usage stats
        cursor.execute("""
            UPDATE saved_connections 
            SET last_used = ?, use_count = use_count + 1
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), connection_id))
        conn.commit()

    return jsonify({
        'status': 'success',
        'terminal_url': f'/terminal/session/{connection_id}'
    })


# ============================================================================
# ROUTES - Quick Connect (ad-hoc without saving)
# ============================================================================

@connections_bp.route('/api/quick-connect', methods=['POST'])
@login_required
def quick_connect():
    """Generate quick connect URL for ad-hoc connection"""
    data = request.get_json()

    host = data.get('host', '').strip()
    port = data.get('port', 22)
    auth_mode = data.get('auth_mode', 'manual')
    device_name = data.get('device_name', host)

    if not host:
        return jsonify({
            'status': 'error',
            'message': 'Host is required'
        }), 400

    # Handle saved credential auth
    if auth_mode == 'saved':
        credential_id = data.get('credential_id')
        if not credential_id:
            return jsonify({
                'status': 'error',
                'message': 'Credential ID is required for saved auth mode'
            }), 400

        # Check vault is unlocked
        if 'vault_key' not in session:
            return jsonify({
                'status': 'error',
                'message': 'Vault locked',
                'code': 'VAULT_LOCKED'
            }), 401

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404

        fernet = get_fernet_from_session()
        if not fernet:
            return jsonify({'status': 'error', 'message': 'Vault key invalid'}), 401

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
                return jsonify({'status': 'error', 'message': 'Credential not found'}), 404

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

        # Store in session
        session['quick_connect'] = {
            'host': host,
            'port': port,
            'username': username,
            'password': password,
            'private_key': private_key,
            'key_passphrase': key_passphrase,
            'device_name': device_name
        }
    else:
        # Manual credentials
        username = data.get('username', '').strip()
        if not username:
            return jsonify({
                'status': 'error',
                'message': 'Username is required'
            }), 400

        # Store in session temporarily
        session['quick_connect'] = {
            'host': host,
            'port': port,
            'username': username,
            'password': data.get('password', ''),
            'device_name': device_name
        }

    return jsonify({
        'status': 'success',
        'terminal_url': '/terminal/quick'
    })