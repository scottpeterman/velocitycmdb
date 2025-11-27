# app/blueprints/auth/auth_manager.py
"""
Authentication manager supporting LDAP, local (Windows/Linux), SSH fallback, and database authentication
with shadow user support for external authentication backends
"""
import os
import platform
import logging
import sqlite3
import bcrypt
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Authentication result with user details"""
    success: bool
    username: str
    groups: List[str] = None
    error: str = None
    auth_method: str = None
    is_admin: bool = False

    def __post_init__(self):
        if self.groups is None:
            self.groups = []


class AuthenticationManager:
    """
    Unified authentication manager supporting multiple backends:
    - Database authentication (via SQLite + bcrypt)
    - Windows local authentication (via win32security)
    - Linux/Unix local authentication (via PAM with SSH fallback)
    - LDAP/Active Directory authentication

    Supports shadow user records for external auth backends to control permissions
    """

    def __init__(self, config: dict = None):
        """
        Initialize authentication manager with configuration

        Args:
            config: Dictionary with authentication configuration
                   Falls back to environment variables and defaults
        """
        self.config = config or {}
        self.system = platform.system()

        # Determine available authentication methods
        self._setup_auth_methods()

        logger.info(f"Authentication manager initialized on {self.system}")
        logger.info(f"Available methods: {self.available_methods}")

    def _setup_auth_methods(self):
        """Detect and configure available authentication methods"""
        self.available_methods = []

        # Check for local authentication support
        if self.system == "Windows":
            try:
                import win32security
                self.available_methods.append("local")
                self._windows_auth_available = True
                logger.info("Windows authentication available")
            except ImportError:
                self._windows_auth_available = False
                logger.warning("Windows authentication unavailable (pywin32 not installed)")
        else:
            # On Linux, we can use either PAM or SSH fallback
            self.available_methods.append("local")

            try:
                import pam
                self._pam_auth_available = True
                logger.info("PAM authentication available")
            except ImportError:
                self._pam_auth_available = False
                logger.info("PAM authentication unavailable, will use SSH fallback")

            # Check if SSH fallback is enabled
            self._ssh_fallback_enabled = self.config.get('local', {}).get('use_ssh_fallback', True)
            if self._ssh_fallback_enabled:
                try:
                    import paramiko
                    self._ssh_available = True
                    logger.info("SSH fallback authentication available")
                except ImportError:
                    self._ssh_available = False
                    logger.warning("SSH fallback unavailable (paramiko not installed)")

        # Check for LDAP support
        ldap_enabled = self.config.get('ldap', {}).get('enabled', False)
        if ldap_enabled:
            try:
                import ldap3
                self.available_methods.append("ldap")
                self._ldap_available = True
                logger.info("LDAP authentication available")
            except ImportError:
                self._ldap_available = False
                logger.warning("LDAP authentication unavailable (ldap3 not installed)")
        else:
            self._ldap_available = False

        # Check for database authentication support
        db_enabled = self.config.get('database', {}).get('enabled', False)
        if db_enabled:
            db_path = self.config.get('database', {}).get('path', 'app/users.db')
            db_path_expanded = str(Path(db_path).expanduser())
            if Path(db_path_expanded).exists():
                self.available_methods.append("database")
                self._db_auth_available = True
                self._db_path = db_path_expanded
                logger.info(f"Database authentication available: {db_path_expanded}")
            else:
                logger.warning(f"Database auth enabled but database not found: {db_path_expanded}")
        else:
            self._db_auth_available = False

    def _merge_database_permissions(self, username: str, auth_method: str) -> Tuple[List[str], bool]:
        """
        Check if user has a database shadow record, auto-create if needed

        Shadow records control permissions for external (LDAP/local) users
        without storing their credentials in the database.

        Args:
            username: Username from external auth
            auth_method: 'ldap' or 'local'

        Returns:
            (groups, is_admin) tuple
        """
        if not self._db_auth_available:
            # No database available - default to non-admin
            logger.warning("Database not available for permission management")
            return [], False

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            logger.info(f"Looking up shadow user: username='{username}', auth_backend='{auth_method}'")

            cursor.execute("""
                SELECT is_admin, groups_json, is_active
                FROM users 
                WHERE username = ? AND auth_backend = ?
            """, (username, auth_method))

            row = cursor.fetchone()

            if row:
                logger.info(
                    f"Found shadow user {username}: is_admin={row['is_admin']}, is_active={row['is_active']}, groups={row['groups_json']}")
            else:
                logger.info(f"No shadow user found for username='{username}', auth_backend='{auth_method}'")

            if row:
                # Shadow user record exists - use database permissions
                if not row['is_active']:
                    conn.close()
                    logger.warning(f"Shadow user {username} exists but is deactivated")
                    # Return empty groups and not admin to deny access
                    return [], False

                # User exists in database - use database permissions
                is_admin = bool(row['is_admin'])
                groups = json.loads(row['groups_json'] or '[]')

                conn.close()
                logger.info(f"Loaded permissions for {username}: admin={is_admin}, groups={groups}")
                return groups, is_admin
            else:
                # No shadow record - auto-create one as non-admin
                logger.info(f"Auto-creating shadow user for {username} (backend: {auth_method})")

                cursor.execute("""
                    INSERT INTO users (
                        username, email, password_hash, is_active, is_admin,
                        display_name, groups_json, created_at, auth_backend
                    ) VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?)
                """, (
                    username,
                    f"{username}@external",
                    "EXTERNAL_AUTH_NO_PASSWORD",
                    username,
                    json.dumps([]),
                    datetime.now().isoformat(),
                    auth_method
                ))

                conn.commit()
                conn.close()

                logger.info(f"Auto-created shadow user: {username} (non-admin)")
                return [], False

        except sqlite3.IntegrityError as e:
            # Race condition - user was created between check and insert
            logger.warning(f"Shadow user {username} was created concurrently: {e}")
            # Retry the lookup
            try:
                conn = sqlite3.connect(self._db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT is_admin, groups_json, is_active
                    FROM users 
                    WHERE username = ? AND auth_backend = ?
                """, (username, auth_method))
                row = cursor.fetchone()
                conn.close()

                if row and row['is_active']:
                    return json.loads(row['groups_json'] or '[]'), bool(row['is_admin'])
                else:
                    return [], False
            except Exception as retry_error:
                logger.error(f"Error on retry for {username}: {retry_error}")
                return [], False

        except Exception as e:
            logger.error(f"Error managing database permissions for {username}: {e}")
            # On error, default to non-admin
            return [], False

    def authenticate(self,
                     username: str,
                     password: str,
                     auth_method: str = None,
                     domain: str = None) -> AuthResult:
        """
        Authenticate user with specified method

        Args:
            username: Username
            password: Password
            auth_method: Authentication method ('local', 'ldap', or 'database')
                        If None, uses default from config
            domain: Domain for Windows authentication (optional)

        Returns:
            AuthResult with authentication outcome including merged permissions
        """
        # Determine authentication method
        if auth_method is None:
            auth_method = self.config.get('default_method', 'local')

        if auth_method not in self.available_methods:
            return AuthResult(
                success=False,
                username=username,
                error=f"Authentication method '{auth_method}' not available",
                auth_method=auth_method
            )

        # Route to appropriate authentication handler
        if auth_method == "local":
            return self._authenticate_local(username, password, domain)
        elif auth_method == "ldap":
            return self._authenticate_ldap(username, password)
        elif auth_method == "database":
            return self._authenticate_database(username, password)
        else:
            return AuthResult(
                success=False,
                username=username,
                error=f"Unknown authentication method: {auth_method}",
                auth_method=auth_method
            )

    def _authenticate_local(self,
                            username: str,
                            password: str,
                            domain: str = None) -> AuthResult:
        """Authenticate against local system (Windows or Linux)"""
        if self.system == "Windows" and self._windows_auth_available:
            return self._authenticate_windows(username, password, domain)
        elif self._pam_auth_available:
            return self._authenticate_pam(username, password)
        elif self._ssh_fallback_enabled and self._ssh_available:
            logger.info(f"Using SSH fallback for {username}")
            return self._authenticate_ssh_fallback(username, password)
        else:
            return AuthResult(
                success=False,
                username=username,
                error="Local authentication not available on this system",
                auth_method="local"
            )

    def _authenticate_windows(self,
                              username: str,
                              password: str,
                              domain: str = None) -> AuthResult:
        """Authenticate against Windows using win32security"""
        import win32security
        import win32con

        try:
            # Determine domain
            if domain is None:
                domain_required = self.config.get('local', {}).get('domain_required', False)
                if domain_required:
                    return AuthResult(
                        success=False,
                        username=username,
                        error="Domain required for Windows authentication",
                        auth_method="local"
                    )

                # Use computer name as domain if configured
                use_computer_name = self.config.get('local', {}).get(
                    'use_computer_name_as_domain', True
                )
                if use_computer_name:
                    domain = os.environ.get('COMPUTERNAME', 'WORKGROUP')

            # Attempt authentication
            handle = win32security.LogonUser(
                username,
                domain,
                password,
                win32con.LOGON32_LOGON_NETWORK,
                win32con.LOGON32_PROVIDER_DEFAULT
            )

            # Create filesystem-safe username
            safe_username = f"{domain}@{username}".replace('\\', '@')

            # Get or create shadow user and load permissions
            groups, is_admin = self._merge_database_permissions(safe_username, 'local')

            return AuthResult(
                success=True,
                username=safe_username,
                groups=groups,
                auth_method="local",
                is_admin=is_admin
            )

        except Exception as e:
            logger.error(f"Windows authentication failed for {username}: {e}")
            return AuthResult(
                success=False,
                username=username,
                error=str(e),
                auth_method="local"
            )

    def _authenticate_pam(self, username: str, password: str) -> AuthResult:
        """Authenticate against PAM (Linux/Unix)"""
        try:
            import pam

            p = pam.pam()
            success = p.authenticate(username, password)

            if success:
                logger.info(f"PAM authentication successful for {username}")

                # Get or create shadow user and load permissions
                groups, is_admin = self._merge_database_permissions(username, 'local')

                return AuthResult(
                    success=True,
                    username=username,
                    groups=groups,
                    auth_method="local",
                    is_admin=is_admin
                )
            else:
                return AuthResult(
                    success=False,
                    username=username,
                    error="Invalid credentials",
                    auth_method="local"
                )
        except ImportError:
            # If PAM not available, try SSH fallback
            if self._ssh_fallback_enabled and self._ssh_available:
                logger.info(f"PAM not available, attempting SSH fallback for {username}")
                return self._authenticate_ssh_fallback(username, password)
            else:
                return AuthResult(
                    success=False,
                    username=username,
                    error="PAM not available and SSH fallback disabled",
                    auth_method="local"
                )
        except Exception as e:
            logger.warning(f"PAM authentication failed for {username}: {e}")
            # Try SSH fallback on PAM failure
            if self._ssh_fallback_enabled and self._ssh_available:
                logger.info(f"Attempting SSH fallback for {username}")
                return self._authenticate_ssh_fallback(username, password)
            else:
                return AuthResult(
                    success=False,
                    username=username,
                    error=str(e),
                    auth_method="local"
                )

    def _authenticate_ssh_fallback(self, username: str, password: str) -> AuthResult:
        """Fallback to SSH authentication if PAM fails or is unavailable"""
        try:
            import paramiko

            # Get SSH host from config (default to localhost)
            ssh_host = self.config.get('local', {}).get('ssh_host', 'localhost')
            ssh_port = self.config.get('local', {}).get('ssh_port', 22)

            # Try to SSH to configured host
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            ssh.connect(
                hostname=ssh_host,
                port=ssh_port,
                username=username,
                password=password,
                timeout=5,
                look_for_keys=False,
                allow_agent=False
            )

            # If connection succeeds, auth is valid
            ssh.close()

            logger.info(f"SSH fallback authentication successful for {username}")

            # Get or create shadow user and load permissions
            groups, is_admin = self._merge_database_permissions(username, 'local')

            return AuthResult(
                success=True,
                username=username,
                groups=groups,
                auth_method="local",
                is_admin=is_admin
            )

        except Exception as e:
            # Check if it's specifically an auth failure
            error_str = str(e).lower()
            if 'authentication' in error_str or 'password' in error_str:
                logger.warning(f"SSH fallback authentication failed for {username}: Invalid credentials")
                return AuthResult(
                    success=False,
                    username=username,
                    error="Invalid credentials",
                    auth_method="local"
                )
            else:
                logger.error(f"SSH fallback connection error for {username}: {e}")
                return AuthResult(
                    success=False,
                    username=username,
                    error=f"SSH authentication error: {str(e)}",
                    auth_method="local"
                )

    def _authenticate_database(self, username: str, password: str) -> AuthResult:
        """Authenticate against local SQLite database"""
        if not self._db_auth_available:
            return AuthResult(
                success=False,
                username=username,
                error="Database authentication not available",
                auth_method="database"
            )

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Fetch user record - only for database backend users
            cursor.execute("""
                SELECT id, username, password_hash, email, is_active, is_admin, 
                       display_name, groups_json
                FROM users 
                WHERE username = ? AND is_active = 1 AND auth_backend = 'database'
            """, (username,))

            user = cursor.fetchone()

            if not user:
                conn.close()
                logger.warning(f"Database auth failed for {username}: User not found or inactive")
                return AuthResult(
                    success=False,
                    username=username,
                    error="Invalid credentials",
                    auth_method="database"
                )

            # Verify password
            stored_hash = user['password_hash']
            if not bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
                conn.close()
                logger.warning(f"Database auth failed for {username}: Invalid password")
                return AuthResult(
                    success=False,
                    username=username,
                    error="Invalid credentials",
                    auth_method="database"
                )

            # Parse groups (stored as JSON string)
            groups = json.loads(user['groups_json'] or '[]')

            # Get admin status from database
            is_admin = bool(user['is_admin'])

            # Add admin group if user is admin (for consistency)
            if is_admin and 'admin' not in groups:
                groups.append('admin')

            # Update last login timestamp
            cursor.execute("""
                UPDATE users 
                SET last_login = ? 
                WHERE id = ?
            """, (datetime.now().isoformat(), user['id']))
            conn.commit()
            conn.close()

            logger.info(f"Database authentication successful for {username}")

            return AuthResult(
                success=True,
                username=username,
                groups=groups,
                auth_method="database",
                is_admin=is_admin
            )

        except Exception as e:
            logger.error(f"Database authentication error for {username}: {e}")
            return AuthResult(
                success=False,
                username=username,
                error=str(e),
                auth_method="database"
            )

    def create_user(self, username: str, email: str, password: str,
                    is_admin: bool = False, display_name: str = None,
                    groups: List[str] = None) -> Tuple[bool, str]:
        """
        Create a new database user

        Returns:
            (success, message) tuple
        """
        if not self._db_auth_available:
            return False, "Database authentication not available"

        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            # Check if user already exists
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                conn.close()
                return False, f"User '{username}' already exists"

            # Hash password
            password_hash = bcrypt.hashpw(
                password.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            # Prepare groups JSON
            groups_json = json.dumps(groups or [])

            # Insert user
            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, is_active, is_admin,
                    display_name, groups_json, created_at, auth_backend
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'database')
            """, (
                username, email, password_hash,
                is_admin, display_name or username,
                groups_json, datetime.now().isoformat()
            ))

            conn.commit()
            user_id = cursor.lastrowid
            conn.close()

            logger.info(f"Created database user: {username} (ID: {user_id})")
            return True, f"User '{username}' created successfully"

        except Exception as e:
            logger.error(f"Error creating user {username}: {e}")
            return False, str(e)

    def create_external_user(self, username: str, auth_backend: str,
                             email: str = None, is_admin: bool = False,
                             groups: List[str] = None, display_name: str = None) -> Tuple[bool, str]:
        """
        Create a shadow user record for LDAP/local authentication

        Shadow users store authorization info (admin status, custom groups) but not credentials.
        They authenticate via external systems (LDAP/OS) but permissions are managed locally.

        Args:
            username: Username (must match LDAP/local username exactly)
            auth_backend: 'ldap' or 'local'
            email: Email (optional, can be placeholder)
            is_admin: Whether user should have admin rights
            groups: Additional groups to assign (merged with external groups)
            display_name: Display name (optional)

        Returns:
            (success, message) tuple
        """
        if not self._db_auth_available:
            return False, "Database not available"

        if auth_backend not in ['ldap', 'local']:
            return False, "auth_backend must be 'ldap' or 'local'"

        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            # Check if user already exists
            cursor.execute("SELECT id, auth_backend FROM users WHERE username = ?", (username,))
            existing = cursor.fetchone()
            if existing:
                conn.close()
                return False, f"User '{username}' already exists with backend '{existing[1]}'"

            # Use dummy password hash for external users (they don't authenticate via database)
            dummy_hash = "EXTERNAL_AUTH_NO_PASSWORD"

            cursor.execute("""
                INSERT INTO users (
                    username, email, password_hash, is_active, is_admin,
                    display_name, groups_json, created_at, auth_backend
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, (
                username,
                email or f"{username}@external",
                dummy_hash,
                1 if is_admin else 0,
                display_name or username,
                json.dumps(groups or []),
                datetime.now().isoformat(),
                auth_backend
            ))

            conn.commit()
            user_id = cursor.lastrowid
            conn.close()

            logger.info(f"Created external user record: {username} (ID: {user_id}, backend: {auth_backend})")
            return True, f"External user '{username}' created for {auth_backend} authentication"

        except sqlite3.IntegrityError as e:
            return False, f"Database integrity error: {e}"
        except Exception as e:
            logger.error(f"Error creating external user: {e}")
            return False, str(e)

    def update_user_password(self, username: str, new_password: str) -> Tuple[bool, str]:
        """
        Update user password (only for database auth users)

        Args:
            username: Username to update
            new_password: New password (will be hashed)

        Returns:
            (success, message) tuple
        """
        if not self._db_auth_available:
            return False, "Database authentication not available"

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Check user exists and is database auth
            cursor.execute("SELECT auth_backend FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()

            if not user:
                conn.close()
                return False, f"User '{username}' not found"

            if user['auth_backend'] != 'database':
                conn.close()
                return False, f"Cannot change password for {user['auth_backend']} user. They authenticate externally."

            # Hash new password
            password_hash = bcrypt.hashpw(
                new_password.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            # Update password
            cursor.execute("""
                UPDATE users 
                SET password_hash = ?, updated_at = ?
                WHERE username = ?
            """, (password_hash, datetime.now().isoformat(), username))

            conn.commit()
            conn.close()

            logger.info(f"Updated password for user: {username}")
            return True, f"Password updated for '{username}'"

        except Exception as e:
            logger.error(f"Error updating password for {username}: {e}")
            return False, str(e)

    def get_user(self, username: str) -> Optional[Dict]:
        """
        Get a single user by username

        Args:
            username: Username to look up

        Returns:
            User dictionary or None if not found
        """
        if not self._db_auth_available:
            return None

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, username, email, is_active, is_admin,
                       display_name, groups_json, created_at, updated_at, last_login, auth_backend
                FROM users
                WHERE username = ?
            """, (username,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'id': row['id'],
                    'username': row['username'],
                    'email': row['email'],
                    'is_active': bool(row['is_active']),
                    'is_admin': bool(row['is_admin']),
                    'display_name': row['display_name'],
                    'groups': json.loads(row['groups_json'] or '[]'),
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                    'last_login': row['last_login'],
                    'auth_backend': row['auth_backend']
                }

            return None

        except Exception as e:
            logger.error(f"Error getting user {username}: {e}")
            return None

    def change_password(self, username: str, new_password: str) -> Tuple[bool, str]:
        """
        Change password for a user (alias for update_user_password)

        Args:
            username: Username to update password for
            new_password: New password (will be hashed with bcrypt)

        Returns:
            (success: bool, message: str) tuple
        """
        return self.update_user_password(username, new_password)

    def update_user(self, username: str, email: str = None, display_name: str = None,
                    groups: str = None, is_admin: bool = None, is_active: bool = None) -> Tuple[bool, str]:
        """
        Update user details

        Args:
            username: Username to update
            email: New email (optional)
            display_name: New display name (optional)
            groups: New groups as comma-separated string or list (optional)
            is_admin: New admin flag (optional)
            is_active: New active flag (optional)

        Returns:
            (success, message) tuple
        """
        if not self._db_auth_available:
            return False, "Database authentication not available"

        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            # Build update query dynamically based on provided parameters
            updates = []
            params = []

            if email is not None:
                updates.append("email = ?")
                params.append(email)

            if display_name is not None:
                updates.append("display_name = ?")
                params.append(display_name)

            if groups is not None:
                # Handle both comma-separated string and list
                if isinstance(groups, str):
                    groups_list = [g.strip() for g in groups.split(',') if g.strip()]
                else:
                    groups_list = groups
                updates.append("groups_json = ?")
                params.append(json.dumps(groups_list))

            if is_admin is not None:
                updates.append("is_admin = ?")
                params.append(1 if is_admin else 0)

            if is_active is not None:
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)

            # Always update timestamp
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())

            # Add username to params for WHERE clause
            params.append(username)

            # Execute update
            query = f"UPDATE users SET {', '.join(updates)} WHERE username = ?"
            cursor.execute(query, params)

            if cursor.rowcount == 0:
                conn.close()
                return False, f"User '{username}' not found"

            conn.commit()
            conn.close()

            logger.info(f"Updated user: {username}")
            return True, f"User '{username}' updated successfully"

        except Exception as e:
            logger.error(f"Error updating user {username}: {e}")
            return False, str(e)

    def delete_user(self, username: str) -> Tuple[bool, str]:
        """
        Delete a user (actually just deactivates for safety)

        Args:
            username: Username to delete/deactivate

        Returns:
            (success, message) tuple
        """
        if not self._db_auth_available:
            return False, "Database authentication not available"

        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            # Safer: Deactivate instead of delete
            cursor.execute("""
                UPDATE users 
                SET is_active = 0, updated_at = ?
                WHERE username = ?
            """, (datetime.now().isoformat(), username))

            if cursor.rowcount == 0:
                conn.close()
                return False, f"User '{username}' not found"

            conn.commit()
            conn.close()

            logger.info(f"Deactivated user: {username}")
            return True, f"User '{username}' deactivated"

        except Exception as e:
            logger.error(f"Error deleting user {username}: {e}")
            return False, str(e)

    def list_users(self) -> List[Dict]:
        """List all database users"""
        if not self._db_auth_available:
            return []

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, username, email, is_active, is_admin, 
                       display_name, groups_json, created_at, last_login, auth_backend
                FROM users
                ORDER BY username
            """)

            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row['id'],
                    'username': row['username'],
                    'email': row['email'],
                    'is_active': bool(row['is_active']),
                    'is_admin': bool(row['is_admin']),
                    'display_name': row['display_name'],
                    'groups': json.loads(row['groups_json'] or '[]'),
                    'created_at': row['created_at'],
                    'last_login': row['last_login'],
                    'auth_backend': row['auth_backend']
                })

            conn.close()
            return users

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []

    def get_available_methods(self) -> Dict:
        """Get information about available authentication methods"""
        return {
            'available_methods': self.available_methods,
            'default_method': self.config.get('default_method', 'local'),
            'system_info': {
                'system': self.system,
                'windows_auth_available': self._windows_auth_available if self.system == "Windows" else False,
                'pam_auth_available': getattr(self, '_pam_auth_available', False),
                'ssh_fallback_available': getattr(self, '_ssh_available', False),
                'ldap_available': self._ldap_available,
                'ldap_configured': self.config.get('ldap', {}).get('enabled', False),
                'database_available': getattr(self, '_db_auth_available', False),
                'database_configured': self.config.get('database', {}).get('enabled', False)
            }
        }