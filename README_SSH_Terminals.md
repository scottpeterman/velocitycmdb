# VelocityCMDB SSH Terminal Architecture

## Overview

The SSH Terminal system provides browser-based terminal access to network devices with encrypted credential management. It integrates with the Connection Manager for saved sessions and supports ad-hoc connections.

## Components

### Blueprints

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `terminal_bp` | `/terminal` | SSH session handling, WebSocket events, credential APIs |
| `connections_bp` | `/connections` | Connection Manager UI, saved connections CRUD |

### Database Schema (users.db)

```
users
  └── user_vault_keys (1:1)     - Per-user encryption key material
  └── user_credentials (1:many) - Encrypted credential sets
  └── saved_connections (1:many)
        └── credential_id → user_credentials (optional FK)
```

## Terminal Modes

### 1. Session Mode (`/terminal/session/<id>`)
- Loads saved connection from `saved_connections` table
- Auto-decrypts credentials from vault on connect
- Auto-connects on page load
- Full SSH key support

**Flow:**
```
saved_connection → credential_id → user_credentials
                                         ↓
                        vault_key (Flask session)
                                         ↓
                        Fernet decrypt → plaintext
                                         ↓
                        WebSocket → paramiko → device
```

### 2. Quick Connect Mode (`/terminal/quick`)
- Ad-hoc connection from Connection Manager
- Credentials stored temporarily in Flask session
- Not persisted to database
- Password-only (no key support)

**Flow:**
```
Connection Manager form → Flask session['quick_connect']
                                    ↓
                          /terminal/quick route
                                    ↓
                          WebSocket → paramiko → device
```

### 3. Direct Mode (`/terminal/direct`) - Legacy
- Device picker dropdown from assets.db
- Manual credential entry in browser
- No vault integration
- Maintained for backward compatibility

## Security Architecture

### Credential Vault

Each user has isolated encryption:

1. **Vault Setup** (first credential save):
   - User enters vault password
   - PBKDF2 derives key from password + random salt
   - Salt stored in `user_vault_keys.key_salt`
   - Check value stored for unlock verification

2. **Vault Unlock** (login or on-demand):
   - User enters vault password
   - Derived key stored in `session['vault_key']` (base64)
   - Key valid for session duration

3. **Credential Storage**:
   - Fernet symmetric encryption
   - Each credential field encrypted separately
   - `password_encrypted`, `ssh_key_encrypted`, `ssh_key_passphrase_encrypted`

4. **Credential Retrieval**:
   - API endpoint decrypts on-demand
   - Plaintext never stored, only transmitted via WebSocket
   - Credentials cleared from memory after SSH connect

### SSH Key Support

The `SSHSession` class supports multiple key types:
- RSA
- Ed25519  
- ECDSA

Key parsing attempts each type in sequence until successful.

## WebSocket Protocol

### Namespace: `/terminal`

### Events (Client → Server)

| Event | Payload | Description |
|-------|---------|-------------|
| `start_session` | `{host, username, password?, port, private_key?, key_passphrase?}` | Initiate SSH connection |
| `input` | `{data}` | Terminal keystrokes |
| `resize` | `{cols, rows}` | Terminal resize |

### Events (Server → Client)

| Event | Payload | Description |
|-------|---------|-------------|
| `connected` | `{message}` | SSH connection established |
| `output` | `{data}` | Terminal output from device |
| `error` | `{message}` | Connection or auth error |
| `server_disconnected` | `{message}` | Remote host closed connection |

### Disconnect Detection

The server detects remote disconnection via:
- `channel.closed` flag
- `channel.exit_status_ready()` (exit command issued)
- Empty `recv()` return (EOF)

When detected, server emits `server_disconnected` and cleans up session.

## API Endpoints

### `POST /terminal/device-connect`

Quick connect from device detail page. Sets up session and redirects.

**Form Data:**
- `device_name`: Display name for terminal header
- `host`: IP address or hostname
- `port`: SSH port (default: 22)
- `auth_mode`: `manual` or `saved`

For `auth_mode=manual`:
- `username`: SSH username
- `password`: SSH password

For `auth_mode=saved`:
- `credential_id`: ID of saved credential from vault

**Response:** Redirect to `/terminal/quick`

**Note:** When using saved credentials, vault must be unlocked. SSH key credentials are fully supported.

### `POST /terminal/api/session-credentials/<connection_id>`

Decrypts and returns credentials for a saved connection.

**Requires:**
- Active login session
- Unlocked vault (`session['vault_key']`)
- Connection ownership (user_id match)

**Returns:**
```json
{
  "status": "success",
  "credentials": {
    "host": "10.0.0.1",
    "port": 22,
    "username": "admin",
    "password": "decrypted_password",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----...",
    "key_passphrase": "optional_passphrase"
  }
}
```

### `POST /terminal/api/quick-credentials`

Returns credentials from Flask session for quick connect.

**Returns:**
```json
{
  "status": "success", 
  "credentials": {
    "host": "10.0.0.1",
    "port": 22,
    "username": "admin",
    "password": "password"
  }
}
```

## Session Management

### Active Sessions

```python
active_sessions = {}  # {socket_id: SSHSession}
```

- Keyed by Socket.IO session ID
- Automatic cleanup on WebSocket disconnect
- Background thread cleans stale sessions every 5 minutes

### SSHSession Class

```python
class SSHSession:
    def __init__(self, host, username, password, port, private_key, key_passphrase)
    def connect() -> bool | tuple[bool, str]
    def write(data) -> bool
    def resize(cols, rows)
    def close()
```

Uses threading:
- Reader thread: `_read_output()` → puts data in queue
- Output thread: Sends queue contents via WebSocket

## File Structure

```
app/blueprints/
├── terminal/
│   ├── __init__.py          # terminal_bp blueprint
│   └── routes.py            # Routes, SSHSession, WebSocket handlers
├── connections/
│   ├── __init__.py          # connections_bp blueprint  
│   └── routes.py            # Connection Manager CRUD
└── templates/
    └── terminal/
        ├── session.html     # Session/Quick connect terminal
        └── direct.html      # Legacy direct terminal
```

## Integration Points

### Device View
- SSH button on device detail page (`/assets/devices/<id>`)
- Opens modal with authentication options:
  - **Manual**: Enter username/password directly
  - **Saved**: Select from user's vault credentials (includes SSH keys)
- POSTs to `/terminal/device-connect`
- Creates quick connect session and redirects to `/terminal/quick`
- Button disabled if device has no `management_ip`
- Vault must be unlocked to use saved credentials

### Connection Manager
- Save connections with credential links
- Quick connect form
- Launch to `/terminal/session/<id>` or `/terminal/quick`

## Dependencies

- **Flask-SocketIO**: WebSocket support
- **Paramiko**: SSH client library
- **Cryptography (Fernet)**: Credential encryption
- **xterm.js**: Browser terminal emulator
- **xterm-addon-fit**: Terminal auto-sizing