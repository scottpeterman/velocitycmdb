# VelocityCMDB Authentication Configuration Guide

## Overview

VelocityCMDB supports three authentication backends with **centralized permission management**:

1. **Database Authentication** - Local SQLite database with bcrypt password hashing
2. **Local OS Authentication** - Windows (via win32security) or Linux/Unix (via PAM/SSH)
3. **LDAP/Active Directory** - Enterprise directory services

**Key Feature**: All user permissions (admin status, groups) are managed in the database, regardless of authentication method. External users (LDAP/Local) authenticate externally but have their permissions controlled locally through "shadow user" records.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Shadow Users Explained](#shadow-users-explained)
3. [Configuration File Location](#configuration-file-location)
4. [Database Authentication](#database-authentication)
5. [Local OS Authentication](#local-os-authentication)
6. [LDAP/Active Directory Authentication](#ldapactive-directory-authentication)
7. [User Management](#user-management)
8. [Advanced Configuration](#advanced-configuration)
9. [Troubleshooting](#troubleshooting)
10. [Security Best Practices](#security-best-practices)

---

## Quick Start

### Minimal Configuration (Database Only)

```yaml
# config.yaml
authentication:
  default_method: "database"
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
```

Create your first user:
```bash
python -m velocitycmdb.cli init            # Creates database structure
velocitycmdb create-admin    # Creates admin user (default: admin/admin)
```

---

## Shadow Users Explained

### What are Shadow Users?

**Shadow users** are database records for LDAP/Local users that store **authorization** (permissions) but not **authentication** (passwords). This allows you to:

- ✅ Authenticate users via LDAP or local OS
- ✅ Control admin rights and groups in the database
- ✅ Deactivate external users locally without touching LDAP/AD
- ✅ Manage all users in one place

### How It Works

**First Login (Auto-Creation)**:
```
1. User "jdoe" logs in via LDAP
2. LDAP authenticates successfully ✓
3. No shadow user exists → Auto-create as non-admin
4. User jdoe logs in with no admin rights
```

**Admin Promotion**:
```
1. Admin goes to User Management
2. Edits user "jdoe"
3. Checks "Administrator" checkbox
4. Saves changes
```

**Subsequent Login (With Permissions)**:
```
1. User "jdoe" logs in via LDAP again
2. LDAP authenticates successfully ✓
3. Shadow user found with is_admin=True
4. User jdoe logs in with admin rights
```

### Shadow User vs Database User

| Feature | Database User | Shadow User (LDAP/Local) |
|---------|---------------|--------------------------|
| **Authenticates via** | Database (password) | LDAP or Local OS |
| **Password stored** | Yes (bcrypt hash) | No (authenticates externally) |
| **Admin flag** | In database | In database |
| **Groups** | In database | In database |
| **Can change password** | Yes (via UI) | No (managed by LDAP/OS) |
| **Auto-created on first login** | No | Yes (as non-admin) |
| **Deactivate locally** | Yes | Yes |

### Example Workflow

```bash
# User logs in via Windows for first time
Username: admin
Auth Method: Local Authentication
→ Creates shadow user: @admin (auth_backend=local, is_admin=False)

# Admin promotes user via UI
Admin → User Management → Edit @admin → Check "Administrator" → Save

# User logs in again via Windows
Username: admin
Auth Method: Local Authentication
→ Loads shadow user: @admin (is_admin=True)
→ User now has admin access!
```

---

## Configuration File Location

Place `config.yaml` in your project root directory:
```
/path/to/velocitycmdb/
├── config.yaml           ← Place here
├── velocitycmdb/
│   ├── app/
│   └── ...
└── ...
```

Or use environment variable:
```bash
export VELOCITYCMDB_CONFIG=/path/to/config.yaml
```

---

## Database Authentication

### Overview
- **Best for**: Small teams, development, simple deployments
- **Storage**: SQLite database with bcrypt password hashing
- **Features**: Full user management via admin UI, self-service password change
- **Python Requirements**: `bcrypt` (installed with velocitycmdb)

### Configuration

```yaml
authentication:
  default_method: "database"
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"  # Recommended: use home directory
```

### Path Resolution
- `~/.velocitycmdb/data/users.db` → Expands to user's home directory
- Relative paths are relative to project root
- Use absolute paths for system deployments

### Initial Setup

```bash
# 1. Initialize database
python -m velocitycmdb.cli init

# 2. Create first admin user
velocitycmdb create-admin    # Default: admin/admin

# 3. Log in via web UI
# Navigate to http://localhost:8086
# Login with admin/admin
```

### Creating Database Users via Admin UI

1. Login as admin
2. Navigate to **Admin → User Management**
3. Click **"Create User"**
4. Fill in form:
   - Username: `jdoe`
   - Email: `jdoe@company.com`
   - Password: `********`
   - Auth Backend: **Database** (default)
   - Check "Administrator" if admin needed
5. Click **"Create User"**

### Self-Service Password Change

Database users can change their own passwords:
1. Go to login page
2. Select "Database Authentication"
3. Check "Change my password"
4. Enter current password + new password
5. Submit to change

---

## Local OS Authentication

### Overview
- **Best for**: Single-server deployments, development environments
- **Windows**: Authenticates against Windows accounts (requires pywin32)
- **Linux/Unix**: Authenticates against system accounts (requires python-pam or SSH fallback)
- **Permissions**: Controlled via shadow users in database (NOT OS groups)

### Windows Configuration

```yaml
authentication:
  default_method: "local"
  
  local:
    enabled: true
    domain_required: false
    use_computer_name_as_domain: true
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
```

**Python Requirements**:
```bash
pip install pywin32
```

**How It Works**:
1. User logs in with Windows username/password
2. System authenticates against Windows
3. Creates username as `COMPUTERNAME@username` (e.g., `WORKSTATION@jdoe`)
4. Checks database for shadow user
5. If not found → auto-creates as non-admin
6. Loads permissions from database

**Admin Promotion**:
1. Admin logs into web UI
2. Goes to User Management
3. Edits `WORKSTATION@jdoe`
4. Checks "Administrator"
5. Saves → User is now admin on next login

### Linux/Unix Configuration

```yaml
authentication:
  default_method: "local"
  use_ssh_fallback: true
  ssh_host: "localhost"
  
  local:
    enabled: true
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
```

**Python Requirements** (choose one):

**Option 1: PAM** (Recommended)
```bash
# Ubuntu/Debian
sudo apt-get install python3-pam
pip install python-pam

# RHEL/CentOS
sudo yum install python3-pam
pip install python-pam
```

**Option 2: SSH Fallback** (if PAM unavailable)
```bash
pip install paramiko
```

**How It Works**:
1. User logs in with Linux username/password
2. System authenticates via PAM or SSH
3. Username stored as-is (e.g., `jdoe`)
4. Checks database for shadow user
5. If not found → auto-creates as non-admin
6. Loads permissions from database

---

## LDAP/Active Directory Authentication

### Overview
- **Best for**: Enterprise deployments, centralized authentication
- **Supports**: OpenLDAP, Active Directory, other LDAP directories
- **Permissions**: Controlled via shadow users in database (NOT LDAP groups)
- **Python Requirements**: `ldap3` (installed with velocitycmdb)

### Basic Configuration

```yaml
authentication:
  default_method: "ldap"
  
  ldap:
    enabled: true
    server: "ldap.company.com"
    port: 389
    use_ssl: false
    base_dn: "dc=company,dc=com"
    user_dn_template: "uid={username},ou=users,dc=company,dc=com"
    timeout: 10
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
```

### User DN Templates

The `user_dn_template` must match your LDAP directory structure.

**OpenLDAP Example**:
```yaml
user_dn_template: "uid={username},ou=users,dc=company,dc=com"
```

**Active Directory (UPN)**:
```yaml
user_dn_template: "{username}@company.com"
```

**Active Directory (DN)**:
```yaml
user_dn_template: "cn={username},ou=Users,dc=company,dc=com"
```

### How It Works

1. User logs in with LDAP username/password
2. System authenticates against LDAP
3. Username stored as provided (e.g., `jdoe` or `jdoe@company.com`)
4. Checks database for shadow user
5. If not found → auto-creates as non-admin
6. Loads permissions from database

### Important Note About Groups

**Previous behavior** (removed): System would query LDAP for groups and determine admin status based on group membership.

**New behavior**: System **does not** query LDAP groups. All permissions come from the database shadow user record. This gives you full control over who has admin access without touching LDAP/AD.

---

## User Management

### Creating Users

#### Via Admin UI - Database Users

1. **Admin → User Management → Create User**
2. Fill in form:
   - Username
   - Email
   - Password (required for database auth)
   - Auth Backend: **Database**
   - Admin checkbox
   - Groups (comma-separated)
3. Click **Create User**

#### Via Admin UI - External Users (LDAP/Local)

**Option 1: Let them auto-create** (Recommended)
1. User logs in via LDAP/Local
2. System auto-creates shadow user as non-admin
3. Admin promotes them via UI

**Option 2: Pre-create shadow user**
1. **Admin → User Management → Create User**
2. Fill in form:
   - Username: `jdoe` (must match LDAP/OS username exactly)
   - Email: `jdoe@company.com`
   - Password: (leave blank)
   - Auth Backend: **LDAP** or **Local**
   - Check "Administrator" if needed
   - Groups (optional)
3. Click **Create User**
4. User can now log in with their LDAP/OS credentials

### Promoting Users to Admin

1. **Admin → User Management**
2. Click **Edit** (pencil icon) on user
3. Check **"Administrator"** checkbox
4. Click **"Save Changes"**
5. User has admin rights on next login

### Managing Groups

Groups are stored as comma-separated values in the database:

1. **Admin → User Management → Edit User**
2. In **Groups** field, enter: `operators, viewers, auditors`
3. Click **"Save Changes"**

These groups are available in `session['groups']` for authorization logic.

### Deactivating Users

To revoke access without deleting:

1. **Admin → User Management → Edit User**
2. Uncheck **"Active"** checkbox
3. Click **"Save Changes"**
4. User cannot log in (even if LDAP/OS auth succeeds)

### Changing Passwords

**Database Users Only**:
1. **Admin → User Management → Edit User**
2. Scroll to **"Change Password"** section
3. Enter new password twice
4. Click **"Update Password"**

**LDAP/Local Users**: Password change section is hidden. Passwords are managed by LDAP/OS.

### Viewing User List

The user list shows:
- **Username**: Login name
- **Display Name**: Full name
- **Email**: Contact email
- **Groups**: Assigned groups (red badges)
- **Auth Backend**: `database`, `ldap`, or `local` (red/blue/orange badge)
- **Status**: Active/Inactive
- **Last Login**: Timestamp or "Never"

---

## Advanced Configuration

### Multiple Authentication Methods

Enable all three methods:

```yaml
authentication:
  default_method: "database"
  use_ssh_fallback: true
  ssh_host: "localhost"
  
  # All users are stored in database for permission management
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
  
  # Windows/Linux local authentication
  local:
    enabled: true
    domain_required: false
    use_computer_name_as_domain: true
  
  # LDAP authentication
  ldap:
    enabled: true
    server: "ldap.company.com"
    port: 389
    use_ssl: false
    base_dn: "dc=company,dc=com"
    user_dn_template: "{username}@company.com"
```

Users see a dropdown at login with three options:
- Database Authentication
- Local Authentication
- LDAP / Active Directory

### LDAPS (Secure LDAP)

```yaml
authentication:
  ldap:
    enabled: true
    server: "ldap.company.com"
    port: 636
    use_ssl: true
    # ... rest of config
```

### Flask Session Settings

```yaml
flask:
  secret_key: null                      # Set FLASK_SECRET_KEY env var in production
  session_timeout_minutes: 120          # 2 hours
```

**Production**: Always set secret key via environment variable:
```bash
export FLASK_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

### Logging Configuration

```yaml
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "logs/velocitycmdb.log"
```

**Debug authentication**:
```yaml
logging:
  level: "DEBUG"
```

Check logs for shadow user lookup:
```bash
tail -f logs/velocitycmdb.log | grep "shadow user"
```

You'll see:
```
INFO: Looking up shadow user: username='@admin', auth_backend='local'
INFO: Found shadow user @admin: is_admin=1, is_active=1, groups=[]
INFO: Loaded permissions for @admin: admin=True, groups=[]
```

---

## Troubleshooting

### Shadow User Issues

**Problem**: External user logs in but isn't admin even though I checked the box

**Solution**: Check the logs to see what username is being looked up:
```bash
tail -f logs/velocitycmdb.log | grep "shadow user"
```

Common issues:
- Windows users: System creates `COMPUTERNAME@username` not just `username`
- Username case sensitivity: Linux usernames are case-sensitive
- Auth backend mismatch: User has `auth_backend='ldap'` but logs in via Local

**Fix**: Edit the user in admin UI and verify:
1. Username matches exactly (including domain prefix for Windows)
2. Auth Backend matches how they're logging in
3. Administrator checkbox is checked
4. Active checkbox is checked

**Problem**: Shadow user auto-created with wrong username format

**Solution**: Delete the auto-created user and manually create one with the correct format:
1. Login as admin
2. User Management → Delete incorrect user
3. User Management → Create User
4. Set Username to match exact login format
5. Set Auth Backend to `local` or `ldap`
6. Check Administrator if needed

### Database Authentication Issues

**Problem**: Can't login with admin/admin
```bash
# Reset admin password
velocitycmdb create-admin

# Or recreate database
rm ~/.velocitycmdb/data/users.db
python -m velocitycmdb.cli init
velocitycmdb create-admin
```

**Problem**: Database not found
```bash
# Verify path expands correctly
echo ~/.velocitycmdb/data/users.db

# Create directory
mkdir -p ~/.velocitycmdb/data

# Check permissions
ls -la ~/.velocitycmdb/data/users.db
```

### Local Authentication Issues

**Windows Problem**: "LogonUser failed"
- Verify user has local login rights
- Check domain is correct
- Ensure pywin32 is installed: `pip show pywin32`
- Check Windows Event Viewer → Security logs

**Linux Problem**: PAM authentication failed
```bash
# Verify PAM module
python3 -c "import pam"

# Check user exists
id yourusername

# Test PAM
pamtester login yourusername authenticate
```

**Linux Problem**: SSH fallback not working
```bash
# Verify SSH daemon
systemctl status sshd

# Verify paramiko
python3 -c "import paramiko"

# Test SSH
ssh localhost
```

### LDAP Authentication Issues

**Problem**: "LDAP authentication not available"
```bash
pip install ldap3
python3 -c "import ldap3; print('LDAP3 available')"
```

**Problem**: "Invalid credentials" but password is correct
- Test `user_dn_template` with ldapsearch
- Common issue: Using `cn={username}` when should be `uid={username}`
- AD issue: Using DN format when should be UPN format

**Problem**: Can't connect to LDAP server
```bash
# Test connectivity
telnet ldap.company.com 389

# Test DNS
nslookup ldap.company.com

# Check firewall
sudo iptables -L | grep 389
```

### General Debugging

**Enable DEBUG logging**:
```yaml
logging:
  level: "DEBUG"
```

**Check application logs**:
```bash
tail -f logs/velocitycmdb.log
```

**Verify shadow user exists**:
```bash
sqlite3 ~/.velocitycmdb/data/users.db
sqlite> SELECT username, auth_backend, is_admin, is_active FROM users;
```

---

## Security Best Practices

### Production Deployment

1. **Use HTTPS**: Never send passwords over unencrypted connections

2. **Set strong secret key**:
   ```bash
   export FLASK_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   ```

3. **Use LDAPS for LDAP authentication**:
   ```yaml
   ldap:
     port: 636
     use_ssl: true
   ```

4. **Restrict file permissions**:
   ```bash
   chmod 600 config.yaml
   chmod 600 ~/.velocitycmdb/data/users.db
   ```

5. **Disable debug mode**:
   ```yaml
   server:
     debug: false
   logging:
     level: "INFO"
   ```

6. **Monitor authentication logs**:
   ```bash
   grep "authentication failed" logs/velocitycmdb.log
   grep "shadow user" logs/velocitycmdb.log
   ```

### User Management Best Practices

1. **Least Privilege**: Don't make all users admins
2. **Regular Audits**: Review admin users monthly
3. **Deactivate, Don't Delete**: Use is_active=False to revoke access
4. **Document Promotions**: Note why users were given admin rights
5. **Shadow User Cleanup**: Periodically review unused shadow users

### Network Security

1. **Bind to specific interface**:
   ```yaml
   server:
     host: "127.0.0.1"    # Local only
   ```

2. **Use firewall rules**:
   ```bash
   sudo ufw allow from 10.0.1.0/24 to any port 8086
   ```

3. **Deploy behind reverse proxy**:
   ```nginx
   server {
       listen 443 ssl;
       server_name velocitycmdb.company.com;
       
       ssl_certificate /path/to/cert.pem;
       ssl_certificate_key /path/to/key.pem;
       
       location / {
           proxy_pass http://127.0.0.1:8086;
       }
   }
   ```

---

## Configuration Examples

### Small Team (Database Only)

```yaml
authentication:
  default_method: "database"
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"

server:
  host: "0.0.0.0"
  port: 8086
  debug: false
```

### Enterprise (LDAP + Database for Permissions)

```yaml
authentication:
  default_method: "ldap"
  
  # LDAP for authentication
  ldap:
    enabled: true
    server: "ad.company.com"
    port: 636
    use_ssl: true
    base_dn: "dc=company,dc=com"
    user_dn_template: "{username}@company.com"
    timeout: 10
  
  # Database for permission management
  database:
    enabled: true
    path: "/var/lib/velocitycmdb/users.db"

server:
  host: "0.0.0.0"
  port: 8086
  debug: false

logging:
  level: "INFO"
  file: "/var/log/velocitycmdb/app.log"
```

### Development (All Methods)

```yaml
authentication:
  default_method: "database"
  use_ssh_fallback: true
  ssh_host: "localhost"
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
  
  local:
    enabled: true
  
  ldap:
    enabled: true
    server: "ldap.dev.local"
    port: 389
    use_ssl: false
    base_dn: "dc=dev,dc=local"
    user_dn_template: "uid={username},ou=users,dc=dev,dc=local"

server:
  host: "127.0.0.1"
  port: 8086
  debug: true

logging:
  level: "DEBUG"
```

---

## Summary

### Key Points

1. **All permissions are managed in the database** - regardless of authentication method
2. **Shadow users** store authorization (admin/groups) for LDAP/Local users
3. **First login auto-creates** shadow users as non-admin
4. **Admins promote users** via the web UI
5. **No external group syncing** - you have full control locally

### Workflow

```
User Logs In → Authenticates Externally → Shadow User Checked → Permissions Loaded → Access Granted
     ↓                                              ↓
External System                           Database (Shadow User)
(LDAP/Windows/Linux)                      (is_admin, groups, is_active)
```

### Benefits

- ✅ Centralized permission management
- ✅ Deactivate external users without touching LDAP/AD
- ✅ Mix database, LDAP, and local users seamlessly
- ✅ Audit all users in one place
- ✅ Simple workflow: auto-create, then promote

---

## Getting Help

If you encounter issues:

1. **Check logs**: `tail -f logs/velocitycmdb.log`
2. **Enable DEBUG logging** in config.yaml
3. **Verify shadow user exists**: Check database directly
4. **File an issue**: [GitHub Issues](https://github.com/scottpeterman/velocitycmdb/issues)

---

*VelocityCMDB Authentication Configuration Guide*  
*Version 2.0 - November 2025*  
*Shadow User System*