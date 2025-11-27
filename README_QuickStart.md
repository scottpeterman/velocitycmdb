# VelocityCMDB Quick Start Guide

**From zero to complete network CMDB in 3 commands and 5 minutes.**

---

## Installation

### Step 1: Install via pip

```bash
pip install velocitycmdb
```

That's it. No Docker, no PostgreSQL, no Redis, no Kubernetes.

---

## Step 2: Initialize

```bash
velocitycmdb init
```

**What happens:**
- Creates `~/.velocitycmdb/` directory
- Creates `config.yaml` with database authentication enabled
- Initializes SQLite databases (assets, users, ARP catalog)
- Creates default admin user

**Output:**
```
============================================================
VelocityCMDB Initialization
============================================================

Set VELOCITYCMDB_DATA_DIR to: /home/you/.velocitycmdb/data
Created config file: /home/you/.velocitycmdb/config.yaml

Initializing databases in: /home/you/.velocitycmdb/data
Creating directory structure...
Initializing assets database...
Initializing ARP database...
Initializing users database...
Default admin user created (admin/admin)

------------------------------------------------------------
Verification:
------------------------------------------------------------
  Config file: /home/you/.velocitycmdb/config.yaml (1847 bytes)
  Users database: /home/you/.velocitycmdb/data/users.db (20480 bytes)
  Assets database: /home/you/.velocitycmdb/data/assets.db (53248 bytes)
  ARP database: /home/you/.velocitycmdb/data/arp_cat.db (16384 bytes)

============================================================
Initialization complete!
============================================================

Default admin credentials:
  Username: admin
  Password: admin
  IMPORTANT: Change this password after first login!

Next step:
  velocitycmdb run

Config file: ~/.velocitycmdb/config.yaml
============================================================
```

---

## Step 3: Configure Authentication (Optional)

**Default**: VelocityCMDB uses local database authentication with admin/admin.

**For Enterprise/Teams**: Set up LDAP or Local OS authentication.

### Quick Setup - LDAP Authentication

Edit `~/.velocitycmdb/config.yaml`:

```yaml
authentication:
  default_method: "ldap"
  
  ldap:
    enabled: true
    server: "ldap.company.com"
    port: 389
    use_ssl: false
    base_dn: "dc=company,dc=com"
    user_dn_template: "{username}@company.com"
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
```

**How it works:**
1. Users authenticate via your LDAP/Active Directory
2. On first login, VelocityCMDB auto-creates a user account (non-admin)
3. Admin promotes users to admin via **Admin > User Management**
4. All permissions managed in VelocityCMDB database

### Quick Setup - Windows/Linux Local Authentication

```yaml
authentication:
  default_method: "local"
  
  local:
    enabled: true
  
  database:
    enabled: true
    path: "~/.velocitycmdb/data/users.db"
```

Users log in with their Windows/Linux credentials. Admin rights controlled via VelocityCMDB UI.

### Multi-User Workflow

```
1. Enable LDAP or Local auth in config.yaml
2. Restart VelocityCMDB
3. Users log in with their LDAP/OS credentials
4. System auto-creates user accounts (non-admin)
5. Admin logs in, goes to Admin > User Management
6. Admin promotes specific users to admin role
7. Promoted users get full admin access on next login
```

**Full Documentation**: See [Authentication Configuration Guide](README_Auth_Config.md) for complete setup including:
- LDAP/Active Directory configuration
- Windows domain authentication
- Linux/Unix PAM authentication
- SSH fallback options
- Shadow user management
- Security best practices

**For single-user/lab use**: Skip this step and use admin/admin (just change the password).

---

## Step 4: Launch

```bash
velocitycmdb run
```

**What happens:**
- Flask web server starts on http://localhost:8086
- Browser opens automatically (or visit manually)
- Login with admin/admin (or your LDAP/Local credentials)

**Options:**
```bash
velocitycmdb run                      # Default: port 8086, no SSL
velocitycmdb run -p 8443 --ssl        # Port 8443 with self-signed SSL
velocitycmdb run --port 5000          # Port 5000, no SSL
velocitycmdb run --host 127.0.0.1     # Bind to localhost only
```

---

## Step 5: Discover Your Network

### In the Web Interface:

1. **Navigate to "Discovery" > "Coverage"**

2. **Click "Network Discovery Wizard"**

3. **Enter Discovery Details:**
   - **Seed IP**: Any device IP on your network (router, switch, firewall)
   - **Username**: SSH/CLI username
   - **Password**: SSH/CLI password
   - **Site Name**: e.g., "HQ", "Lab", "Datacenter"

4. **Click "Start Discovery"**

### What Happens:

**Phase 1: Network Discovery (2-3 minutes)**
- Connects to seed device via SSH
- Runs `show cdp neighbors` / `show lldp neighbors`
- Builds network topology map
- Discovers all connected devices
- **Result**: Complete device list with IPs and connections

**Phase 2: Device Fingerprinting (3-5 minutes)**
- SSH to each discovered device
- Runs `show version`, `show inventory`
- Identifies platform, OS version, model, serial numbers
- Classifies device types (router, switch, firewall, etc.)
- **Result**: Full device inventory with hardware details

**Phase 3: Complete! (instant)**
- All devices loaded to database
- Topology map generated
- Ready to explore

---

## You Now Have:

### Complete Device Inventory
- All devices discovered via CDP/LLDP
- Device names, IPs, management addresses
- Sites automatically organized
- Vendor information

### Hardware Details
- Exact models (Cisco 9300, Arista 7050, etc.)
- OS versions (IOS-XE 17.x, EOS 4.x, etc.)
- Serial numbers
- Component inventory (line cards, power supplies, transceivers)

### Network Topology
- Visual network diagram
- Device connections and interfaces
- Hierarchical layout (core > distribution > access)
- Interactive map

### Operational Intelligence
- Device roles (core, distribution, access, unknown)
- Stack members identified
- Change tracking ready
- Configuration baselines

---

## What You Can Do Now

### Browse Your Network
```
Dashboard > View Devices
```
See all discovered devices

### View Topology
```
Network Maps > Secure Cartography
```
Interactive network diagram with all connections

### Search Devices
```
Search & Analysis > Device Search
```
Find devices by name, IP, model, vendor, site

### Track Changes
```
Discovery > Changes
```
See what changed since last discovery

### Explore Components
```
Assets > Components
```
Browse transceivers, power supplies, line cards

### SSH to Devices
```
Devices > [Select Device] > SSH button
```
Browser-based terminal - no PuTTY needed!

### Manage Users (Admin Only)
```
Admin > User Management
```
Create users, promote to admin, manage permissions

---

## Built-in SSH Terminal

VelocityCMDB includes a **jump host** right in the browser!

### How to Use:

1. **Navigate to Device Inventory**
   ```
   Assets > Devices
   ```

2. **Select Any Device**
   - Click the device name or IP

3. **Click "SSH" Button**
   - Opens terminal in browser
   - Connects using stored credentials
   - Or enter credentials on the fly

4. **Multiple Sessions**
   - Open multiple terminals
   - Switch between devices
   - All in browser tabs

### Perfect For:

- **Quick troubleshooting** - See issue in CMDB, SSH immediately
- **No external tools** - No PuTTY, SecureCRT, or terminal needed
- **Centralized access** - All device access through one interface
- **Credential management** - Credentials tied to your CMDB
- **Session logging** - All access through one controlled point

### Example Workflow:

```
1. Discovery finds device with old IOS version
2. Click device in inventory
3. Click "SSH" button
4. Terminal opens, already connected
5. Run upgrade commands
6. Next discovery detects version change
```

**CMDB + Jump Host + CLI = One Tool**

---

## Real-World Example

Here's what happened in our lab test:

```bash
# Installed
$ pip install velocitycmdb

# Initialized
$ velocitycmdb init
VelocityCMDB initialized successfully!

# Launched
$ velocitycmdb run
* Running on http://127.0.0.1:8086

# In browser: Started discovery with seed IP 172.16.10.21
# 5 minutes later:
```

**Results:**
- **12 devices** discovered automatically
- **3 Cisco routers** (eng-rtr-1, usa-rtr-1, wan-core-1)
- **6 Cisco switches** (eng-leaf-1/2/3, eng-spine-1/2, usa-spine-1/2)
- **3 Arista switches** (usa-leaf-1/2/3)
- **Complete topology** mapped with all connections
- **All hardware details** collected (models, versions, serials)

**Time:** 5 minutes from seed IP to complete inventory.

---

## Pro Tips

### 1. Credentials Matter
- Use a read-only account (privilege level 1-7)
- Account needs SSH access
- Must be able to run `show` commands

### 2. Seed Device Selection
- Pick a device connected to many others
- Core switch or distribution router works best
- Device must have CDP or LLDP enabled

### 3. Multi-Site Discovery
- Run discovery once per site
- Use descriptive site names ("HQ", "Branch-NYC", "DC1")
- Devices auto-organize by site

### 4. Re-Discovery
- Run discovery again anytime
- Updates existing devices
- Detects changes
- Finds new devices

### 5. Data Location
- **Linux/Mac**: `~/.velocitycmdb/data/`
- **Windows**: `C:\Users\<you>\.velocitycmdb\data\`
- Contains all databases and captured data
- Backup this directory to preserve everything

### 6. Authentication Setup
- Change default admin password immediately
- Use LDAP/Local auth for teams
- Auto-create users on first login
- Promote users to admin via UI

---

## Command Reference

```bash
# Initialize system (first time setup)
velocitycmdb init

# Re-initialize and overwrite config
velocitycmdb init --force

# Start web interface (default: port 8086)
velocitycmdb run

# Start with SSL enabled
velocitycmdb run --ssl

# Start on custom port
velocitycmdb run -p 8443

# Start on custom host and port
velocitycmdb run --host 127.0.0.1 --port 5000

# Disable debug mode (for production)
velocitycmdb run --no-debug

# Show help
velocitycmdb --help
velocitycmdb init --help
velocitycmdb run --help
```

---

## Common First-Time Workflows

### Workflow 1: Lab Environment Discovery

```bash
# Install and setup
pip install velocitycmdb
velocitycmdb init
velocitycmdb run

# In browser:
# 1. Login (admin/admin)
# 2. Navigate to Discovery
# 3. Enter seed IP: 192.168.1.1
# 4. Enter lab credentials
# 5. Site name: "Lab"
# 6. Click Start Discovery
# 7. Wait 5 minutes
# 8. Browse discovered devices
```

**Result**: Complete lab network inventory

### Workflow 2: Multi-Site Assessment

```bash
# Install once
pip install velocitycmdb
velocitycmdb init
velocitycmdb run

# In browser (repeat for each site):
# Site 1: HQ
#   - Seed: 10.1.1.1
#   - Site: "HQ"
#   - Discover
#
# Site 2: Branch
#   - Seed: 10.2.1.1  
#   - Site: "Branch-NYC"
#   - Discover
#
# Site 3: Datacenter
#   - Seed: 10.3.1.1
#   - Site: "DC1"
#   - Discover
```

**Result**: Multi-site inventory, organized by location

### Workflow 3: Change Detection

```bash
# Initial discovery
# (discover network as above)

# Make some changes on network:
# - Add devices
# - Change configurations
# - Upgrade firmware

# Re-run discovery (same seed IP)
# VelocityCMDB detects:
# - New devices
# - Version changes
# - Configuration diffs
# - Topology changes
```

**Result**: Track what changed since last run

### Workflow 4: Team Setup with LDAP

```bash
# 1. Install and initialize
pip install velocitycmdb
velocitycmdb init

# 2. Edit ~/.velocitycmdb/config.yaml with LDAP settings
# (see Step 3 above)

# 3. Launch
velocitycmdb run

# 4. Users log in with LDAP credentials
# System auto-creates their accounts

# 5. Admin promotes specific users:
# Admin > User Management > Edit user > Check "Administrator"

# 6. Promoted users get admin access on next login
```

**Result**: Team can access CMDB with their corporate credentials

---

## Supported Platforms

### Automated Discovery (Works Out-of-Box):

**Full Support:**
- **Cisco IOS / IOS-XE** - Routers, switches, complete discovery
- **Arista EOS** - All Arista platforms, complete discovery

**Basic Support:**
- **HP/Aruba ProCurve** - Access switches, basic discovery

### Manual Entry (Add to Inventory):

You can manually add any SSH-capable device:
- **Juniper JunOS** - Routers, switches, firewalls
- **Cisco NX-OS** - Nexus switches  
- **Palo Alto** - Firewalls
- **F5 BIG-IP** - Load balancers
- **Any device with SSH** - Will be inventoried

**How it works:**
- **Discovery** = Automatic CDP/LLDP crawling (Cisco/Arista optimized)
- **Manual devices** = Still get fingerprinting, config capture, change tracking
- **Juniper** = Add manually, everything else works (show commands, configs, etc.)

### Requirements:
- **For Discovery**: CDP or LLDP enabled (Cisco/Arista)
- **For All Devices**: SSH access + read-only credentials
- **Privilege Level**: 1-7 sufficient (read-only access)

---

## Troubleshooting

### "Authentication failed"
- Verify SSH credentials work: `ssh user@device-ip`
- Check privilege level (needs read access)
- Try alternate credentials option

### "Can't login to VelocityCMDB"
- Default credentials: admin/admin
- If LDAP enabled, use your LDAP credentials
- Check logs in terminal output
- See [Authentication Guide](README_Auth_Config.md) for detailed troubleshooting

### "No devices discovered"
- Check CDP/LLDP is enabled on seed device
- Verify seed device has neighbors: `show cdp neighbors`
- Check network connectivity from VelocityCMDB host

### "Fingerprinting failed"
- Some devices may not respond to SSH
- Check SSH is enabled on all devices
- Verify credentials work on all devices
- Some devices will show as "unknown" - that's OK

### "Can't access web interface"
- Check firewall: Port 8086 must be open
- Try: http://127.0.0.1:8086 (not localhost)
- Check terminal output for errors

### "LDAP users can't become admin"
- Users auto-created as non-admin on first login
- Admin must promote them via Admin > User Management
- Edit user > Check "Administrator" > Save
- User gets admin rights on next login
- See [Shadow Users Guide](SHADOW_USERS_GUIDE.md) for details

---

## Next Steps

After your first successful discovery:

1. **Explore the UI**
   - Browse device inventory
   - View topology maps
   - Search for specific devices
   - Check component inventory

2. **Set Up Authentication**
   - Change admin password
   - Configure LDAP/Local auth if needed
   - Create/promote users
   - See [Authentication Guide](README_Auth_Config.md)

3. **Set Up Captures**
   - Collect configurations
   - Enable change detection
   - Schedule regular captures

4. **Regular Operations**
   - Re-run discovery weekly
   - Track changes over time
   - Export device lists
   - Generate reports

---

## The Bottom Line

```bash
pip install velocitycmdb
velocitycmdb init
velocitycmdb run
```

**Three commands. One seed IP. Five minutes.**

You now have a complete network CMDB with:
- Full device inventory
- Network topology
- Hardware details
- Change tracking
- Visual maps
- Multi-user support (optional)
- Browser-based SSH terminal

**No Docker. No PostgreSQL. No complex configuration.**

Just install and discover.

---

## Resources

- **Quick Start**: You're reading it!
- **Authentication Setup**: [README_Auth_Config.md](README_Auth_Config.md)
- **GitHub Repository**: [https://github.com/scottpeterman/velocitycmdb](https://github.com/scottpeterman/velocitycmdb)
- **Issues**: [GitHub Issues](https://github.com/scottpeterman/velocitycmdb/issues)
- **PyPI**: [velocitycmdb on PyPI](https://pypi.org/project/velocitycmdb/)

---

*VelocityCMDB - Because network engineers need answers, not DevOps homework.*
