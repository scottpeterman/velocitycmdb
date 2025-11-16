# VelocityCMDB: Easiest Install in the Industry

## Current Status (November 2024)

### ✅ **ACHIEVED - Core Discovery Pipeline**

**Working End-to-End:**
1. ✅ Web UI with Material Design 3 dark theme
2. ✅ Network discovery (CDP/LLDP) - 12 devices in 3 minutes
3. ✅ Real-time progress via SocketIO
4. ✅ Multi-vendor support (Cisco IOS, Arista, Juniper)
5. ✅ Topology visualization (HTML, SVG, GraphML, DrawIO)
6. ✅ **Inventory generation (`sessions.yaml`)** ← NEW!
7. ✅ Native Windows support (no WSL)
8. ✅ CLI commands (`init`, `start`, `discover`, `status`, `reset`)

**Discovery Output:**
```
C:\Users\[User]\.velocitycmdb\discovery\
├── network.json          # Topology (device relationships)
├── sessions.yaml         # Inventory (12 devices, 5 sites) ✓
├── network.svg           # Visual map
├── network.html
├── network.graphml
└── network.drawio
```

### 🚧 **IN PROGRESS - Data Collection Pipeline**

**Next Phase: Device Fingerprinting & Data Capture**

The discovery created `sessions.yaml` with device inventory. Now we need to:

1. **Fingerprint devices** (determine exact device_type for netmiko)
2. **Capture configuration data** (configs, version, ARP, etc.)
3. **Load into database** (assets.db)
4. **Display in UI** (device details, search, changes)

---

## The Complete Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│             VelocityCMDB Automated Pipeline                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  PHASE 1: Discovery (✅ DONE)                                │
│    User fills form → CDP/LLDP crawl → sessions.yaml          │
│    Output: 12 devices, 5 sites, topology map                 │
│                                                               │
│  PHASE 2: Fingerprinting (🚧 NEXT)                           │
│    sessions.yaml → device_fingerprint.py → updated inventory │
│    Determines: cisco_ios vs cisco_nxos vs arista_eos         │
│                                                               │
│  PHASE 3: Data Collection (📅 FUTURE)                        │
│    generate_capture_jobs.py → batch execution                │
│    Captures: configs, version, ARP, routes, etc.             │
│                                                               │
│  PHASE 4: Database Loading (📅 FUTURE)                       │
│    Captured data → assets.db → Web UI display                │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 2: Device Fingerprinting

### Problem Statement

**Discovery output (`sessions.yaml`) has generic device info:**
```yaml
- folder_name: USA Site
  sessions:
    - display_name: usa-rtr-1
      host: 172.16.100.2
      Model: IOSv              # Generic model
      Vendor: ""               # Empty!
      DeviceType: Network      # Too generic
```

**What we need for data collection:**
```yaml
- folder_name: USA Site
  sessions:
    - display_name: usa-rtr-1
      host: 172.16.100.2
      device_type: cisco_ios   # Specific netmiko type
      vendor: Cisco
      Model: IOSv
      platform: cisco_ios
```

### Solution: Device Fingerprinting

**Purpose:** Connect to each device and determine exact device type

**Input:** `sessions.yaml` (from discovery)

**Process:**
1. SSH to each device
2. Run minimal commands (`show version`)
3. Parse output to determine platform
4. Update inventory with correct `device_type`

**Output:** `sessions_fingerprinted.yaml` (ready for capture pipeline)

### Integration Points

**Option A: Automatic After Discovery** (Recommended)
```
Discovery Complete!
  ↓
[Start Fingerprinting] button
  ↓
Real-time progress (like discovery)
  ↓
"✓ Identified 12 devices"
  ↓
[Start Data Collection]
```

**Option B: CLI Command**
```bash
velocitycmdb fingerprint --inventory sessions.yaml
```

**Option C: Combined**
```bash
# Discovery + Fingerprinting in one step
velocitycmdb discover --seed-ip 10.0.0.1 --fingerprint
```

---

## Updated Architecture

### File Flow
```
1. Discovery Phase
   └─> secure_cartography → network.json (topology)
   └─> map_to_session.py → sessions.yaml (inventory)

2. Fingerprinting Phase (NEW)
   └─> device_fingerprint.py → sessions_fingerprinted.yaml
       ├─ Adds: device_type (cisco_ios, arista_eos, etc.)
       ├─ Adds: vendor (Cisco, Arista, Juniper)
       ├─ Adds: platform details
       └─ Validates: SSH connectivity

3. Collection Phase
   └─> generate_capture_jobs.py → job configs
   └─> run_jobs_batch.py → captured data
   └─> db_load_capture.py → assets.db

4. Display Phase
   └─> Web UI → Device search, configs, changes
```

### Directory Structure
```
C:\Users\[User]\.velocitycmdb\
├── config.yaml
├── data\
│   ├── assets.db              # Device database
│   ├── arp_cat.db
│   ├── users.db
│   ├── captures\              # Captured data
│   │   ├── configs\
│   │   ├── version\
│   │   ├── arp\
│   │   └── ...
│   └── fingerprints\          # Fingerprint cache
└── discovery\
    ├── network.json           # Topology
    ├── sessions.yaml          # Raw inventory
    ├── sessions_fingerprinted.yaml  # After fingerprinting
    └── network.svg
```

---

## Phase 2 Implementation Plan

### Step 1: Create `device_fingerprint.py` Service

**File:** `velocitycmdb/services/fingerprint.py`

```python
class DeviceFingerprintOrchestrator:
    """
    Fingerprints devices to determine exact platform type
    
    Takes sessions.yaml and determines:
    - Exact device_type for netmiko
    - Vendor (Cisco, Arista, Juniper)
    - Platform details (IOS, NX-OS, EOS, JunOS)
    - Software version
    """
    
    def fingerprint_inventory(self, 
                             sessions_file: Path,
                             username: str,
                             password: str,
                             **kwargs) -> Dict:
        """
        Fingerprint all devices in inventory
        
        Returns:
            {
                'success': bool,
                'fingerprinted_file': Path,
                'device_count': int,
                'identified': int,
                'failed': int
            }
        """
```

### Step 2: Platform Detection Logic

**Fingerprinting Strategy:**

```python
FINGERPRINT_COMMANDS = {
    'generic': 'show version',  # Works on most platforms
}

PLATFORM_PATTERNS = {
    'cisco_ios': [
        r'Cisco IOS Software',
        r'IOS.*Version \d+\.\d+',
    ],
    'cisco_nxos': [
        r'Cisco Nexus Operating System',
        r'NX-OS',
    ],
    'arista_eos': [
        r'Arista.*EOS',
        r'vEOS',
    ],
    'juniper_junos': [
        r'JUNOS',
        r'Juniper Networks',
    ],
}
```

### Step 3: Update `sessions.yaml` Format

**Add fields needed for capture pipeline:**

```yaml
- folder_name: USA Site
  sessions:
    - name: usa-rtr-1              # For netmiko (not display_name)
      ip: 172.16.100.2             # For netmiko (not host)
      device_type: cisco_ios       # For netmiko (required)
      vendor: Cisco
      platform: ios
      model: IOSv
      software_version: 15.6(2)T
      fingerprinted: true
      fingerprint_timestamp: 2024-11-10T04:41:00
      port: 22
      credsid: 1
```

### Step 4: Web UI Integration

**Add button to discovery success screen:**

```html
<!-- After discovery completes -->
<div class="form-actions-buttons">
    <button id="fingerprintBtn" class="md-button md-button-filled">
        <i data-lucide="fingerprint" size="16"></i>
        Identify Device Types
    </button>
    <a href="/discovery/map/{{job_id}}" class="md-button md-button-outlined">
        <i data-lucide="map" size="16"></i>
        View Topology Map
    </a>
</div>
```

### Step 5: Create New Route

**File:** `velocitycmdb/app/blueprints/discovery/routes.py`

```python
@discovery_bp.route('/fingerprint/<job_id>', methods=['POST'])
def fingerprint_devices(job_id):
    """
    Fingerprint discovered devices
    
    Uses credentials from original discovery job
    """
    # Get original job info
    job_info = session.get(f'job_{job_id}')
    
    # Get sessions.yaml path
    sessions_file = job_info['inventory_file']
    
    # Start fingerprinting
    fingerprint_job_id = start_fingerprint_task(
        sessions_file=sessions_file,
        username=job_info['username'],
        password=job_info['password']
    )
    
    return jsonify({
        'success': True,
        'fingerprint_job_id': fingerprint_job_id
    })
```

### Step 6: CLI Command

```bash
velocitycmdb fingerprint --inventory sessions.yaml --username admin --password cisco
```

---

## Phase 3: Data Collection (Future)

Once fingerprinting is done, the existing capture pipeline works:

```bash
# Generate capture jobs from fingerprinted inventory
python generate_capture_jobs.py \
    --sessions sessions_fingerprinted.yaml \
    --output-dir jobs

# Run captures
python run_jobs_batch.py jobs/job_batch_list.txt --verbose

# Load into database
python db_load_capture.py --capture-dir captures/
```

**Or via Web UI:**
```
Fingerprinting Complete!
  ↓
[Capture Configuration Data] button
  ↓
Select captures: [✓] Configs [✓] Version [✓] ARP
  ↓
Real-time batch progress
  ↓
"✓ Captured 12 device configs"
  ↓
[View Devices]
```

---

## Updated Installation Experience

### The Vision (Post-PyPI)

```bash
# Install
pip install velocitycmdb

# Initialize
velocitycmdb init

# Start
velocitycmdb start
```

**Browser opens → Fill wizard:**
```
Step 1: Network Discovery
  Seed IP: 10.0.0.1
  Credentials: admin / ••••••
  [Discover Network] → 5 minutes

Step 2: Device Identification (automatic)
  [Identifying device types...]
  ✓ Identified 47 devices → 1 minute

Step 3: Data Collection (automatic)
  [Capturing configurations...]
  ✓ Captured 47 configs → 10 minutes

Total: 16 minutes to populated CMDB
```

---

## Current vs Target State

### Current State (Beta)

```bash
# Installation
git clone https://github.com/scottpeterman/velocitycmdb
cd velocitycmdb
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Usage
python -m velocitycmdb.cli init
python -m velocitycmdb.cli start

# Discovery via Web UI
# Results: sessions.yaml with 12 devices
```

**Time: 30 minutes (mostly setup)**

### Target State (Post-PyPI)

```bash
# Installation
pip install velocitycmdb
velocitycmdb init
velocitycmdb start

# Everything else via Web UI wizard
# Results: Fully populated CMDB
```

**Time: 3 minutes install + 15 minutes discovery/collection = 18 minutes total**

---

## Immediate Next Steps (Priority Order)

### This Week

1. **Create `services/fingerprint.py`** (2 days)
   - Wrap existing device_fingerprint logic
   - Add progress callbacks
   - Handle failures gracefully

2. **Update `scripts/map_to_session.py`** (1 day)
   - Output correct field names (`name`, `ip`, `device_type`)
   - Better vendor detection from Model field
   - Add platform mapping

3. **Add fingerprint route** (1 day)
   - `/discovery/fingerprint/<job_id>`
   - SocketIO progress updates
   - Store results

4. **Update discovery success UI** (1 day)
   - Add "Identify Device Types" button
   - Show fingerprint progress
   - Display results

### Next Week

5. **Integrate capture pipeline** (3 days)
   - Wrap `generate_capture_jobs.py`
   - Wrap `run_jobs_batch.py`
   - Add to web UI

6. **Database loading** (2 days)
   - Wrap `db_load_capture.py`
   - Auto-load after capture
   - Update device views

### Following Week

7. **PyPI Packaging** (5 days)
   - Create proper `setup.py`/`pyproject.toml`
   - Package data files
   - Test installation
   - Publish to TestPyPI

---

## Success Metrics

### Beta (Current)
- ✅ Discovery works (12 devices in 3 min)
- ✅ Real-time progress
- ✅ Sessions.yaml created
- ✅ CLI commands working
- 🚧 Fingerprinting
- 📅 Data collection
- 📅 Database population

### v0.9 (End of Month)
- ✅ Complete discovery → fingerprint → capture → database pipeline
- ✅ All via web UI
- ✅ CLI commands for automation
- ✅ Works on Windows/Linux/macOS
- 📅 PyPI package

### v1.0 (December)
- ✅ `pip install velocitycmdb` works
- ✅ 3-command installation
- ✅ 15-minute populated CMDB
- ✅ Beta testers feedback incorporated
- ✅ Documentation complete

---

## Marketing Message (Updated)

### Current Reality

```markdown
# VelocityCMDB - Beta v0.8

Network CMDB for network engineers. Built to be easy.

## What Works Now
✅ Network discovery (CDP/LLDP) - finds devices in minutes
✅ Multi-vendor (Cisco, Arista, Juniper, and more)
✅ Beautiful web UI with real-time updates
✅ Topology maps (HTML, SVG, GraphML, DrawIO)
✅ Inventory generation for automation
✅ Native Windows support (no WSL!)

## Coming Very Soon
🚧 Device fingerprinting (determine exact platform)
🚧 Config capture automation
🚧 Database population
🚧 PyPI package (pip install velocitycmdb)

## Try It Now (Beta)
git clone https://github.com/scottpeterman/velocitycmdb
cd velocitycmdb
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m velocitycmdb.cli init
python -m velocitycmdb.cli start

Beta testers wanted! Especially Windows users.
```

---

## The Bottom Line

**You're 70% there!**

✅ **Hard parts done:**
- Discovery engine
- Web UI
- Real-time updates
- Windows compatibility
- Inventory generation

🚧 **Medium parts in progress:**
- Fingerprinting integration
- Capture pipeline automation
- Database loading

📦 **Easy parts remaining:**
- PyPI packaging
- CLI polish
- Documentation

**Timeline:**
- This week: Fingerprinting working
- Next week: Capture pipeline integrated
- Following week: PyPI package
- Month end: Beta ready for users

**You can legitimately market:** 
"CMDB that discovers your network in minutes, captures configs automatically, runs natively on Windows."

No other CMDB combines all three. 🚀

---

**Last Updated:** November 10, 2024  
**Version:** 0.8 Beta  
**Next Milestone:** Device Fingerprinting (0.9)