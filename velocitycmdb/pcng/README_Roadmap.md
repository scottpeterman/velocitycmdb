# VelocityCMDB Roadmap: From Fingerprinting to Production

## Current Status (November 2024)

### ✅ Phase 1: Foundation Complete
- Discovery pipeline (CDP/LLDP crawl)
- Topology visualization (multiple formats)
- Inventory generation (sessions.yaml)
- Material Design 3 UI
- Native Windows support
- CLI commands (init, start, discover, status)

### 🚧 Phase 2: Fingerprinting (In Progress)
- Device SSH fingerprinting
- TextFSM parsing
- Database population (assets.db)
- Real-time progress updates
- **Status:** Integration ready, testing pending

### 📅 Phase 3-5: Remaining Work
This document outlines the path from fingerprinted devices to a complete, production-ready CMDB.

---

## Phase 3: Wizard Completion (Week 1-2)

### Goal
Complete the discovery wizard with full automation from seed IP to populated database.

### Current Wizard Flow
```
Step 1: Discovery (✅ Done)
  └─> Find devices via CDP/LLDP
  └─> Output: sessions.yaml, topology maps

Step 2: Fingerprinting (🚧 In Progress)
  └─> SSH to each device
  └─> Identify exact platform (cisco_ios, arista_eos, etc.)
  └─> Output: JSON files, populated assets.db

Step 3: Data Collection (📅 To Build)
  └─> Capture operational data from devices
  └─> Output: configs, ARP tables, MAC tables, etc.
```

### 3.1: Add Collection Step to Wizard

**What to Build:**
1. `velocitycmdb/services/collection.py` - Collection orchestrator
2. UI section in wizard after fingerprinting
3. Route handler for `/discovery/collect/<job_id>`

**User Experience:**
```
Fingerprinting Complete! ✓
  ↓
[Capture Device Data] button
  ↓
Select capture types:
  [✓] Configurations
  [✓] ARP Tables  
  [✓] MAC Tables
  [✓] LLDP Neighbors
  [✓] Hardware Inventory
  [✓] NTP Configuration
  [✓] SNMP Configuration
  [ ] Interface Details
  [ ] Routing Tables
  [ ] BGP Neighbors
  
[Start Capture]
  ↓
"Capturing from 12 devices..."
Progress: [████████░░] 80% (device 10/12)
  ↓
"✓ Captured data from 12 devices"
[View Devices] [View Reports]
```

**Implementation:**
```python
# velocitycmdb/services/collection.py
class CollectionOrchestrator:
    """
    Orchestrates data capture from devices
    
    Wraps existing capture scripts:
    - generate_capture_jobs.py
    - run_jobs_batch.py (or run_jobs_batch_concurrent.py)
    - db_load_capture.py
    """
    
    def run_collection(self,
                      capture_types: List[str],
                      progress_callback: Callable) -> Dict:
        """
        1. Query devices from assets.db (populated by fingerprinting)
        2. Generate capture job configs for each type
        3. Execute jobs (sequential or concurrent)
        4. Load captured data into database
        5. Update device records with last_captured timestamp
        """
```

**Capture Types Mapping:**
```python
CAPTURE_TYPES = {
    'configs': {
        'display_name': 'Running Configurations',
        'description': 'Full device configuration backup',
        'commands': {
            'cisco_ios': 'show running-config',
            'arista_eos': 'show running-config',
            'juniper_junos': 'show configuration'
        },
        'output_dir': 'configs',
        'requires_enable': True,  # For Cisco
        'estimated_time': 30  # seconds per device
    },
    'arp': {
        'display_name': 'ARP Tables',
        'description': 'IP to MAC address mappings',
        'commands': {
            'cisco_ios': 'show ip arp',
            'arista_eos': 'show ip arp',
            'juniper_junos': 'show arp no-resolve'
        },
        'output_dir': 'arp',
        'requires_enable': False,
        'estimated_time': 5
    },
    'mac': {
        'display_name': 'MAC Address Tables',
        'description': 'MAC address to port mappings',
        'commands': {
            'cisco_ios': 'show mac address-table',
            'arista_eos': 'show mac address-table',
            'juniper_junos': 'show ethernet-switching table'
        },
        'output_dir': 'mac',
        'estimated_time': 5
    },
    'lldp': {
        'display_name': 'LLDP Neighbors',
        'description': 'Directly connected devices',
        'commands': {
            'cisco_ios': 'show lldp neighbors detail',
            'arista_eos': 'show lldp neighbors detail',
            'juniper_junos': 'show lldp neighbors detail'
        },
        'output_dir': 'lldp',
        'estimated_time': 10
    },
    'inventory': {
        'display_name': 'Hardware Inventory',
        'description': 'Modules, power supplies, fans',
        'commands': {
            'cisco_ios': 'show inventory',
            'arista_eos': 'show inventory',
            'juniper_junos': 'show chassis hardware'
        },
        'output_dir': 'inventory',
        'estimated_time': 5
    },
    'ntp': {
        'display_name': 'NTP Configuration',
        'description': 'Time sync settings',
        'commands': {
            'cisco_ios': 'show ntp associations',
            'arista_eos': 'show ntp associations',
            'juniper_junos': 'show ntp associations'
        },
        'output_dir': 'ntp',
        'estimated_time': 3
    },
    'snmp': {
        'display_name': 'SNMP Configuration',
        'description': 'SNMP communities and settings',
        'commands': {
            'cisco_ios': 'show snmp',
            'arista_eos': 'show snmp',
            'juniper_junos': 'show snmp'
        },
        'output_dir': 'snmp',
        'estimated_time': 3
    }
}
```

**Time Estimate:** 3-4 days
- Day 1: Build `collection.py` service wrapper
- Day 2: Add UI components to wizard
- Day 3: Add route handlers and SocketIO
- Day 4: Testing and refinement

---

## Phase 4: Job-Based Capture System (Week 3-4)

### Goal
Move from wizard-based "capture now" to a flexible job-based system for scheduled and ad-hoc captures.

### 4.1: Capture Job Management

**Database Schema:**
```sql
-- Capture job definitions
CREATE TABLE capture_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    capture_types TEXT,  -- JSON array: ["configs", "arp", "mac"]
    
    -- Targeting
    device_filter TEXT,  -- JSON: {"vendor": "Cisco", "site": "USA"}
    device_count INTEGER,  -- How many devices match filter
    
    -- Scheduling
    schedule_type TEXT,  -- 'once', 'hourly', 'daily', 'weekly', 'monthly'
    schedule_cron TEXT,  -- Cron expression if complex
    next_run DATETIME,
    
    -- Status
    enabled BOOLEAN DEFAULT 1,
    last_run DATETIME,
    last_status TEXT,  -- 'success', 'partial', 'failed'
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT
);

-- Capture job execution history
CREATE TABLE capture_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    
    -- Execution details
    started_at DATETIME,
    completed_at DATETIME,
    status TEXT,  -- 'running', 'success', 'failed', 'cancelled'
    
    -- Results
    devices_total INTEGER,
    devices_success INTEGER,
    devices_failed INTEGER,
    
    -- Output
    output_dir TEXT,  -- Where captured files are stored
    error_log TEXT,
    
    FOREIGN KEY (job_id) REFERENCES capture_jobs(id)
);

-- Per-device capture results
CREATE TABLE capture_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER,
    device_id INTEGER,
    
    capture_type TEXT,  -- 'configs', 'arp', etc.
    status TEXT,  -- 'success', 'failed'
    output_file TEXT,
    error_message TEXT,
    
    started_at DATETIME,
    completed_at DATETIME,
    duration_seconds INTEGER,
    
    FOREIGN KEY (execution_id) REFERENCES capture_executions(id),
    FOREIGN KEY (device_id) REFERENCES devices(id)
);
```

**UI Components:**

1. **Capture Jobs List** (`/capture/jobs`)
```
┌─────────────────────────────────────────────────────────────┐
│ Capture Jobs                               [+ New Job]       │
├─────────────────────────────────────────────────────────────┤
│ Name              | Devices | Schedule    | Last Run | Status│
├─────────────────────────────────────────────────────────────┤
│ Daily Config      | 12      | Daily 2 AM  | 2h ago   | ✓     │
│ Hourly ARP        | 12      | Hourly      | 15m ago  | ✓     │
│ Weekly Inventory  | 12      | Weekly Mon  | 2d ago   | ✓     │
│ USA Site Backup   | 6       | Daily 3 AM  | 2h ago   | ✓     │
└─────────────────────────────────────────────────────────────┘
```

2. **Job Creation Form** (`/capture/jobs/new`)
```
Create Capture Job

Name: [Daily Config Backup                    ]

Description:
[Backup configurations from all devices daily  ]

Capture Types:
  [✓] Configurations
  [✓] Hardware Inventory
  [ ] ARP Tables
  [ ] MAC Tables

Target Devices:
  (•) All devices (12)
  ( ) Filtered:
      Vendor: [Any ▼]
      Site: [Any ▼]
      Device Type: [Any ▼]

Schedule:
  (•) Daily at [02:00]
  ( ) Weekly on [Monday ▼] at [02:00]
  ( ) Custom cron: [                    ]

[Save Job] [Cancel]
```

3. **Job Execution View** (`/capture/jobs/<job_id>/executions`)
```
Daily Config Backup - Execution History

┌─────────────────────────────────────────────────────────────┐
│ Date              | Status  | Devices      | Duration       │
├─────────────────────────────────────────────────────────────┤
│ Nov 10, 02:00 AM  | Success | 12/12 (100%) | 6m 23s        │
│ Nov 09, 02:00 AM  | Success | 12/12 (100%) | 6m 15s        │
│ Nov 08, 02:00 AM  | Partial | 11/12 (92%)  | 6m 42s        │
│ Nov 07, 02:00 AM  | Success | 12/12 (100%) | 6m 18s        │
└─────────────────────────────────────────────────────────────┘
```

4. **Execution Detail** (`/capture/executions/<execution_id>`)
```
Execution #1234 - Nov 10, 02:00 AM

Status: Success
Duration: 6m 23s
Devices: 12/12 successful

Device Results:
┌─────────────────────────────────────────────────────────────┐
│ Device        | Capture Types     | Status | Duration       │
├─────────────────────────────────────────────────────────────┤
│ usa-rtr-1     | config, inventory | ✓      | 34s           │
│ usa-spine-1   | config, inventory | ✓      | 28s           │
│ eng-leaf-1    | config, inventory | ✓      | 31s           │
│ ...           |                   |        |               │
└─────────────────────────────────────────────────────────────┘

[View Captured Files] [Download Archive]
```

**Time Estimate:** 5-7 days
- Day 1: Database schema and models
- Day 2: Job CRUD operations (Create, Read, Update, Delete)
- Day 3: Job listing and detail UI
- Day 4: Job execution engine
- Day 5: Execution history UI
- Day 6-7: Testing and refinement

### 4.2: Job Scheduler Integration

**Options:**

**Option A: Built-in Python Scheduler (Recommended for MVP)**
```python
# velocitycmdb/services/scheduler.py
import schedule
import threading
import time

class CaptureScheduler:
    """
    Simple built-in scheduler using schedule library
    
    Pros:
    - No external dependencies
    - Easy to integrate
    - Works on Windows/Linux
    
    Cons:
    - Runs in-process (stops when app stops)
    - Not suitable for distributed systems
    """
    
    def __init__(self):
        self.jobs = {}
        self.running = False
    
    def start(self):
        """Start scheduler in background thread"""
        self.running = True
        thread = threading.Thread(target=self._run_scheduler)
        thread.daemon = True
        thread.start()
    
    def _run_scheduler(self):
        """Main scheduler loop"""
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    def add_job(self, job_id, schedule_type, time_str, callback):
        """Add a scheduled job"""
        if schedule_type == 'daily':
            schedule.every().day.at(time_str).do(callback)
        elif schedule_type == 'hourly':
            schedule.every().hour.do(callback)
        # etc...
```

**Option B: Windows Task Scheduler / Linux Cron (Recommended for Production)**
```python
# velocitycmdb/services/scheduler.py

class SystemScheduler:
    """
    Use OS-native schedulers
    
    Pros:
    - Survives app restarts
    - Robust and reliable
    - System-level monitoring
    
    Cons:
    - Platform-specific code
    - More complex to manage
    """
    
    def create_windows_task(self, job_name, schedule, command):
        """Create Windows Task Scheduler entry"""
        import subprocess
        
        # Use schtasks.exe
        cmd = f'schtasks /create /tn "{job_name}" /tr "{command}" /sc {schedule}'
        subprocess.run(cmd, shell=True)
    
    def create_linux_cron(self, job_name, schedule, command):
        """Add to crontab"""
        from crontab import CronTab
        
        cron = CronTab(user=True)
        job = cron.new(command=command, comment=job_name)
        job.setall(schedule)
        cron.write()
```

**Option C: CLI-Based Scheduling (Simplest)**
```bash
# Windows
velocitycmdb schedule-job daily-backup --daily --time 02:00

# Linux
velocitycmdb schedule-job daily-backup --daily --time 02:00
```

**Recommendation:** Start with Option A for MVP, migrate to Option B for production.

**Time Estimate:** 2-3 days
- Day 1: Choose scheduler, implement basic scheduling
- Day 2: Add job enable/disable, next-run calculation
- Day 3: Testing across Windows/Linux

### 4.3: Capture Orchestration Service

**Core Service:**
```python
# velocitycmdb/services/collection.py (extended)

class CollectionOrchestrator:
    """
    Extended with job-based execution
    """
    
    def execute_capture_job(self, 
                           job_id: int,
                           progress_callback: Optional[Callable] = None) -> Dict:
        """
        Execute a capture job
        
        Workflow:
        1. Load job definition from database
        2. Query matching devices
        3. Generate capture job configs
        4. Execute via run_jobs_batch.py
        5. Load captured data via db_load_capture.py
        6. Record execution results
        7. Update device last_captured timestamps
        """
        
        # Load job
        job = self._load_job_definition(job_id)
        
        # Create execution record
        execution_id = self._create_execution_record(job_id)
        
        # Query devices
        devices = self._query_devices(job['device_filter'])
        
        # Generate job configs (using your existing script)
        jobs_dir = self._generate_job_configs(
            devices=devices,
            capture_types=job['capture_types'],
            output_dir=self.data_dir / 'captures' / f'exec_{execution_id}'
        )
        
        # Execute (using your existing script)
        results = self._execute_capture_jobs(
            jobs_dir=jobs_dir,
            progress_callback=progress_callback
        )
        
        # Load into database (using your existing script)
        self._load_captured_data(
            capture_dir=jobs_dir.parent,
            execution_id=execution_id
        )
        
        # Update execution record
        self._complete_execution(execution_id, results)
        
        return {
            'execution_id': execution_id,
            'status': 'success',
            'devices_total': len(devices),
            'devices_success': results['success'],
            'devices_failed': results['failed']
        }
    
    def _generate_job_configs(self, devices, capture_types, output_dir):
        """
        Wrapper for generate_capture_jobs.py
        
        Your script already does:
        - Read sessions.yaml
        - Generate job configs per vendor/capture type
        - Output to jobs/ directory
        
        We need to:
        - Query devices from database instead of sessions.yaml
        - Create temporary sessions.yaml from database
        - Call your existing script
        """
        
        # Create temporary sessions.yaml from database
        sessions_data = self._devices_to_sessions_yaml(devices)
        temp_sessions = output_dir / 'sessions.yaml'
        
        with open(temp_sessions, 'w') as f:
            yaml.dump(sessions_data, f)
        
        # Call your existing script
        subprocess.run([
            sys.executable,
            str(Path(__file__).parent.parent / 'generate_capture_jobs.py'),
            '--sessions', str(temp_sessions),
            '--output-dir', str(output_dir / 'jobs'),
            '--capture-types', ','.join(capture_types)
        ])
        
        return output_dir / 'jobs'
    
    def _execute_capture_jobs(self, jobs_dir, progress_callback):
        """
        Wrapper for run_jobs_batch.py
        
        Your script already does:
        - Read job list
        - Execute batch_spn.py for each job
        - Handle failures gracefully
        
        We need to:
        - Capture output/progress
        - Report back via callback
        """
        
        # Find job batch list
        job_list = jobs_dir / 'job_batch_list_generated.txt'
        
        # Execute your existing script
        # TODO: Enhance run_jobs_batch.py to support progress callbacks
        process = subprocess.Popen([
            sys.executable, '-u',  # Unbuffered
            str(Path(__file__).parent.parent / 'pcng' / 'run_jobs_batch.py'),
            str(job_list),
            '--verbose'
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Stream output
        for line in process.stdout:
            if progress_callback:
                # Parse progress from output
                progress_callback({
                    'message': line.strip()
                })
        
        process.wait()
        
        # Parse results (would need enhancement to run_jobs_batch.py)
        return {
            'success': 12,
            'failed': 0
        }
    
    def _load_captured_data(self, capture_dir, execution_id):
        """
        Wrapper for db_load_capture.py
        
        Your script already does:
        - Parse captured files
        - Update database with configs, components, etc.
        
        We need to:
        - Link to execution_id
        - Track which files were loaded
        """
        
        subprocess.run([
            sys.executable,
            str(Path(__file__).parent.parent / 'pcng' / 'db_load_capture.py'),
            '--capture-dir', str(capture_dir),
            '--db-path', str(self.db_path)
        ])
```

**Time Estimate:** 4-5 days
- Day 1: Extend collection.py with job execution
- Day 2: Wrapper functions for existing scripts
- Day 3: Progress tracking and error handling
- Day 4: Execution recording to database
- Day 5: Testing end-to-end

---

## Phase 5: Data Loading & Enrichment (Week 5)

### Goal
Ensure captured data is properly loaded and indexed in the database for search, reporting, and change tracking.

### 5.1: Enhanced Database Loaders

**Current State:**
- `db_load_capture.py` exists and loads configs

**Enhancements Needed:**
1. **Load all capture types** (not just configs)
2. **Deduplicate data** (don't reload identical configs)
3. **Track changes** (detect when configs change)
4. **Build indexes** (for fast search)
5. **Extract metadata** (from captured data)

**Example Enhancement:**
```python
# velocitycmdb/services/data_loader.py

class DataLoader:
    """
    Enhanced data loading with deduplication and change tracking
    """
    
    def load_capture_directory(self, capture_dir: Path, execution_id: int):
        """
        Load all captured data from a directory
        
        Structure:
        capture_dir/
        ├── configs/
        │   ├── usa-rtr-1.txt
        │   └── eng-leaf-1.txt
        ├── arp/
        │   ├── usa-rtr-1.txt
        │   └── eng-leaf-1.txt
        └── mac/
            ├── usa-rtr-1.txt
            └── eng-leaf-1.txt
        """
        
        # Load configs
        self._load_configs(capture_dir / 'configs', execution_id)
        
        # Load ARP tables
        self._load_arp_tables(capture_dir / 'arp', execution_id)
        
        # Load MAC tables
        self._load_mac_tables(capture_dir / 'mac', execution_id)
        
        # etc...
    
    def _load_configs(self, configs_dir: Path, execution_id: int):
        """Load configurations with change detection"""
        
        for config_file in configs_dir.glob('*.txt'):
            device_name = config_file.stem
            device = self._get_device_by_name(device_name)
            
            if not device:
                continue
            
            # Read config
            with open(config_file, 'r') as f:
                config_text = f.read()
            
            # Calculate hash
            config_hash = hashlib.sha256(config_text.encode()).hexdigest()
            
            # Check if this exact config already exists
            existing = self._get_config_by_hash(device['id'], config_hash)
            
            if existing:
                # Config hasn't changed, just update last_seen
                self._update_config_last_seen(existing['id'])
            else:
                # New config, insert and track change
                self._insert_config(
                    device_id=device['id'],
                    config_text=config_text,
                    config_hash=config_hash,
                    execution_id=execution_id
                )
                
                # Record change event
                self._record_config_change(device['id'])
```

**Database Tables:**
```sql
-- Configuration storage
CREATE TABLE device_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    config_text TEXT NOT NULL,
    config_hash TEXT NOT NULL,  -- SHA256 for deduplication
    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    execution_id INTEGER,  -- Which capture job created this
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (execution_id) REFERENCES capture_executions(id)
);

CREATE INDEX idx_device_configs_hash ON device_configs(device_id, config_hash);

-- Change events
CREATE TABLE config_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    old_config_id INTEGER,
    new_config_id INTEGER NOT NULL,
    change_detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    diff_summary TEXT,  -- Brief summary of changes
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (old_config_id) REFERENCES device_configs(id),
    FOREIGN KEY (new_config_id) REFERENCES device_configs(id)
);

-- ARP entries
CREATE TABLE arp_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    ip_address TEXT NOT NULL,
    mac_address TEXT NOT NULL,
    interface TEXT,
    age TEXT,
    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    execution_id INTEGER,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

CREATE INDEX idx_arp_ip ON arp_entries(ip_address);
CREATE INDEX idx_arp_mac ON arp_entries(mac_address);

-- MAC address table entries
CREATE TABLE mac_table_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    mac_address TEXT NOT NULL,
    vlan INTEGER,
    interface TEXT NOT NULL,
    entry_type TEXT,  -- 'dynamic', 'static'
    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    execution_id INTEGER,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

CREATE INDEX idx_mac_address ON mac_table_entries(mac_address);
```

**Time Estimate:** 5-6 days
- Day 1-2: Enhance db_load_capture.py to handle all types
- Day 3: Add deduplication logic
- Day 4: Add change detection and tracking
- Day 5: Build indexes and optimize queries
- Day 6: Testing with real data

---

## Phase 6: CLI Integration (Week 6)

### Goal
Expose all functionality via CLI for automation and power users.

### CLI Commands

```bash
# Job management
velocitycmdb job create "Daily Backup" --captures configs,inventory --daily --time 02:00
velocitycmdb job list
velocitycmdb job show daily-backup
velocitycmdb job run daily-backup
velocitycmdb job enable daily-backup
velocitycmdb job disable daily-backup
velocitycmdb job delete daily-backup

# Ad-hoc captures
velocitycmdb capture --devices all --types configs,arp,mac
velocitycmdb capture --devices "site=USA" --types configs
velocitycmdb capture --devices "vendor=Cisco" --types inventory

# Data viewing
velocitycmdb devices list
velocitycmdb devices show usa-rtr-1
velocitycmdb configs diff usa-rtr-1 --from "2024-11-09" --to "2024-11-10"
velocitycmdb arp search 10.0.0.1
velocitycmdb mac search aa:bb:cc:dd:ee:ff

# Execution history
velocitycmdb executions list
velocitycmdb executions show 1234
velocitycmdb executions retry 1234  # Retry failed devices

# Export
velocitycmdb export devices --format csv > devices.csv
velocitycmdb export configs --device usa-rtr-1 --output usa-rtr-1-config.txt
velocitycmdb export arp --format csv > arp-table.csv
```

**Time Estimate:** 3-4 days
- Day 1: Job management commands
- Day 2: Capture and data viewing commands
- Day 3: Export commands
- Day 4: Testing and documentation

---

## Phase 7: PyPI Packaging (Week 7-8)

### Goal
Package for `pip install velocitycmdb` distribution.

### 7.1: Package Structure

```
velocitycmdb/
├── setup.py or pyproject.toml
├── MANIFEST.in
├── README.md
├── LICENSE
├── requirements.txt
├── velocitycmdb/
│   ├── __init__.py
│   ├── __main__.py           # Entry point
│   ├── cli.py                # Click CLI
│   ├── app/                  # Flask web app
│   ├── services/             # Business logic
│   ├── scripts/              # Automation scripts
│   ├── db/                   # Database management
│   └── pcng/                 # Legacy scripts
└── tests/
    ├── test_discovery.py
    ├── test_fingerprint.py
    └── test_collection.py
```

### 7.2: Installation Experience

```bash
# Install
pip install velocitycmdb

# Initialize
velocitycmdb init
# Output:
# ✓ Created C:\Users\Scott\.velocitycmdb
# ✓ Initialized databases
# ✓ Created default admin (admin/admin)
# ✓ Ready to start!

# Start
velocitycmdb start
# Output:
# Starting VelocityCMDB...
# ✓ Server running on http://localhost:8086
# ✓ Opening browser...
```

**Time Estimate:** 5-7 days
- Day 1-2: Create setup.py/pyproject.toml
- Day 3: Package data files (templates, static, databases)
- Day 4: Test installation on Windows/Linux/macOS
- Day 5: Publish to TestPyPI
- Day 6: Test from TestPyPI
- Day 7: Publish to PyPI

---

## Complete Timeline

### Week 1-2: Wizard Completion
- [ ] Add collection step to wizard UI
- [ ] Build collection orchestrator service
- [ ] Test end-to-end: discovery → fingerprint → collect

### Week 3-4: Job System
- [ ] Database schema for capture jobs
- [ ] Job CRUD operations and UI
- [ ] Job execution engine
- [ ] Scheduler integration

### Week 5: Data Loading
- [ ] Enhanced loaders for all capture types
- [ ] Deduplication and change detection
- [ ] Database indexing

### Week 6: CLI Integration
- [ ] Job management commands
- [ ] Capture and data commands
- [ ] Export commands

### Week 7-8: PyPI Packaging
- [ ] Package structure
- [ ] Testing across platforms
- [ ] PyPI publishing

### Week 9: Beta Testing
- [ ] Windows users (primary target)
- [ ] Linux users
- [ ] Real network testing
- [ ] Bug fixes and refinement

### Week 10: Documentation & Launch
- [ ] User documentation
- [ ] Video tutorials
- [ ] GitHub README
- [ ] LinkedIn announcement

---

## Success Metrics

### Phase 3 Success (Wizard Complete)
- ✅ Discovery → Fingerprint → Collect works end-to-end
- ✅ All steps have real-time progress updates
- ✅ Database fully populated with device data
- ✅ User never leaves wizard until complete

### Phase 4 Success (Job System)
- ✅ Can create scheduled capture jobs
- ✅ Jobs execute automatically on schedule
- ✅ Execution history is tracked
- ✅ Failed devices can be retried

### Phase 5 Success (Data Loading)
- ✅ All capture types loaded into database
- ✅ Config changes detected automatically
- ✅ Search works across all data types
- ✅ No duplicate data stored

### Phase 6 Success (CLI)
- ✅ All web UI functions available via CLI
- ✅ CLI can be scripted/automated
- ✅ Works on Windows PowerShell and Linux Bash

### Phase 7 Success (PyPI)
- ✅ `pip install velocitycmdb` works
- ✅ Works on Windows/Linux/macOS
- ✅ Total install time: 3 commands, 2 minutes

---

## Risk Mitigation

### Risk 1: Capture Scripts Integration Complexity
**Mitigation:** Your existing scripts are already proven. Just need thin wrappers.

### Risk 2: Platform Compatibility (Windows vs Linux)
**Mitigation:** Using platform-agnostic Python. Test early on both.

### Risk 3: Database Performance with Large Datasets
**Mitigation:** Proper indexing, pagination in UI, background jobs for heavy operations.

### Risk 4: Scheduler Reliability
**Mitigation:** Start with simple in-process scheduler, migrate to system scheduler for production.

### Risk 5: PyPI Package Size
**Mitigation:** Keep TextFSM templates separate download, compress static assets.

---

## Post-Launch Roadmap

### Phase 8: Advanced Features (Month 3-4)
- [ ] Multi-user support with RBAC
- [ ] API for external integrations
- [ ] Custom reports and dashboards
- [ ] Compliance checking (OS versions, config standards)
- [ ] Alerting (config changes, device down)

### Phase 9: Scale Features (Month 5-6)
- [ ] Distributed job execution
- [ ] Redis/PostgreSQL support (beyond SQLite)
- [ ] Kubernetes deployment
- [ ] Multi-tenant support

### Phase 10: Ecosystem (Month 7+)
- [ ] Plugin system for custom capture types
- [ ] Integration with NetBox, ServiceNow, etc.
- [ ] Mobile app (view-only)
- [ ] Cloud-hosted offering

---

## Notes on Orchestration vs Rewriting

### Your Scripts (Keep As-Is)
✅ **These work great, don't rewrite:**
- `device_fingerprint.py` - SSH fingerprinting
- `generate_capture_jobs.py` - Job config generation
- `run_jobs_batch.py` - Batch execution
- `batch_spn.py` - SSH worker
- `db_load_capture.py` - Data loading

### Service Layer (Build New)
✨ **These are thin wrappers:**
- `services/discovery.py` ✅ Done
- `services/fingerprint.py` ✅ Done
- `services/collection.py` 📅 To Build
- `services/scheduler.py` 📅 To Build
- `services/data_loader.py` 📅 To Build

### Integration Pattern
```python
# Service layer just orchestrates existing scripts
class CollectionOrchestrator:
    def run_collection(self):
        # 1. Query database for devices
        devices = self.db.query_devices()
        
        # 2. Create temp sessions.yaml
        self._create_sessions_yaml(devices)
        
        # 3. Call YOUR existing script
        subprocess.run(['python', 'generate_capture_jobs.py', ...])
        
        # 4. Call YOUR existing script
        subprocess.run(['python', 'run_jobs_batch.py', ...])
        
        # 5. Call YOUR existing script
        subprocess.run(['python', 'db_load_capture.py', ...])
        
        # 6. Update database with execution results
        self.db.record_execution(...)
```

**Key Principle:** Your scripts do the heavy lifting. Service layer just:
1. Prepares inputs
2. Calls your scripts
3. Processes outputs
4. Updates UI/database

---

## Bottom Line

**From Richard (fingerprinted devices in DB) to Production:**

1. **Week 1-2:** Add collection to wizard (uses your scripts)
2. **Week 3-4:** Build job system (UI + scheduler)
3. **Week 5:** Enhance data loading (your script + deduplication)
4. **Week 6:** CLI commands (wraps web UI functions)
5. **Week 7-8:** PyPI packaging
6. **Week 9-10:** Beta testing and launch

**Total: 10 weeks to production-ready, pip-installable CMDB**

**Critical Path:** Wizard completion (Phase 3) unblocks everything else.

**Your Role:** Scripts already work! Just need orchestration layer.

🚀 **Let's build this!**