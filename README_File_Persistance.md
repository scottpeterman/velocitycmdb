# VelocityCMDB File Persistence Strategy

## Directory Structure

VelocityCMDB uses a clean separation between **databases/captures** (in `data/`) and **discovery output** (parallel to `data/`):

```
~/.velocitycmdb/                    # Base directory
├── data/                           # All databases and persistent files
│   ├── assets.db                   # Device inventory, sites, components
│   ├── arp_cat.db                  # ARP table data
│   ├── users.db                    # User authentication
│   ├── fingerprints/               # Device fingerprint results
│   ├── jobs/                       # Job definition files (JSON)
│   ├── logs/                       # Application logs
│   └── capture/                    # All CLI output captures
│       ├── arp/
│       ├── authentication/
│       ├── authorization/
│       ├── bgp-neighbor/
│       ├── bgp-summary/
│       ├── configs/
│       ├── interfaces/
│       ├── inventory/
│       ├── lldp/
│       ├── lldp-detail/
│       ├── mac/
│       ├── routes/
│       ├── version/
│       ├── vlans/
│       └── [20+ more subdirectories]
└── discovery/                      # Network topology discovery output
    ├── maps/
    ├── network_topology.json
    ├── network_topology.graphml
    ├── network_topology.svg
    └── sessions.yaml
```

## Key Design Decisions

### 1. **Data vs Discovery Separation**

**Why `discovery/` is parallel to `data/` (not inside it):**
- Discovery files are **temporary/regeneratable** - you can rediscover anytime
- Database files are **persistent/precious** - contain historical data, changes, users
- Backup strategy differs: Always backup `data/`, optionally backup `discovery/`
- Clean separation makes `velocitycmdb clean` vs `velocitycmdb reset` clear

### 2. **Single Data Directory**

**Why everything persistent is in `data/`:**
- Simple backup: `tar -czf backup.tar.gz ~/.velocitycmdb/data/`
- Easy Docker volume: Single mount point
- Clear ownership: Everything in `data/` is important
- Consistent paths: All Flask config points to subdirectories of `data/`

### 3. **Capture Subdirectories**

**Why 25+ capture type folders:**
- Organized by CLI command type (configs, arp, lldp, etc.)
- Easy to find specific capture types
- Supports selective cleanup ("delete all ARP captures")
- Mirrors the collection wizard's capture type selection

---

## Initialization

The `DatabaseInitializer` creates this entire structure:

```python
# velocitycmdb/db/initializer.py
def _create_directory_structure(self):
    """Create complete directory structure for VelocityCMDB"""
    
    # Core directories
    core_dirs = [
        self.data_dir / 'fingerprints',
        self.data_dir / 'logs',
        self.data_dir / 'jobs',
    ]
    
    # All capture type subdirectories
    capture_types = [
        'arp', 'authentication', 'authorization', 'bgp-neighbor',
        'bgp-summary', 'configs', 'cdp', 'cdp-detail', 'environment',
        'flash', 'interfaces', 'inventory', 'ip-route', 'lldp',
        'lldp-detail', 'mac', 'mac-address-table', 'neighbors',
        'ospf', 'power', 'routes', 'spanning-tree', 'stp',
        'transceivers', 'version', 'vlans', 'vrf'
    ]
    
    capture_dirs = [
        self.data_dir / 'capture' / capture_type 
        for capture_type in capture_types
    ]
    
    # Discovery directory (parallel to data/)
    discovery_dir = self.data_dir.parent / 'discovery'
    
    # Create all directories
    all_dirs = core_dirs + capture_dirs + [discovery_dir]
    for directory in all_dirs:
        directory.mkdir(parents=True, exist_ok=True)
```

**Called automatically by `python -m velocitycmdb.cli init`.**

---

## Flask Configuration

All paths are configured in `app/__init__.py`:

```python
def create_app():
    app = Flask(__name__)
    
    # Get base data directory
    data_dir = os.environ.get('VELOCITYCMDB_DATA_DIR') or \
               os.path.join(Path.home(), '.velocitycmdb', 'data')
    
    # Configure all paths
    app.config['DATA_DIR'] = data_dir
    app.config['DATABASE'] = os.path.join(data_dir, 'assets.db')
    app.config['ARP_DATABASE'] = os.path.join(data_dir, 'arp_cat.db')
    app.config['USERS_DATABASE'] = os.path.join(data_dir, 'users.db')
    
    # Data subdirectories
    app.config['CAPTURE_DIR'] = os.path.join(data_dir, 'capture')
    app.config['JOBS_DIR'] = os.path.join(data_dir, 'jobs')
    app.config['FINGERPRINTS_DIR'] = os.path.join(data_dir, 'fingerprints')
    app.config['LOGS_DIR'] = os.path.join(data_dir, 'logs')
    
    # Discovery directory (parallel to data/)
    base_dir = os.path.dirname(data_dir)
    app.config['DISCOVERY_DIR'] = os.path.join(base_dir, 'discovery')
```

---

## CLI Commands

### Path Detection

The CLI automatically finds the correct structure:

```python
def find_data_path(base_dir: Path) -> Path:
    """
    Standard structure (production):
      ~/.velocitycmdb/
      ├── data/          <- databases and captures here
      └── discovery/     <- discovery output here
    
    Returns: Path to data/ directory
    """
    if (base_dir / 'data' / 'assets.db').exists():
        return base_dir / 'data'
    return base_dir / 'data'  # Default even if doesn't exist yet
```

### Init Command

```bash
python -m velocitycmdb.cli init
# Creates:
#   ~/.velocitycmdb/data/ (with all subdirectories)
#   ~/.velocitycmdb/discovery/
#   Empty databases in data/
```

### Reset Command

```bash
velocitycmdb reset --yes
# Deletes EVERYTHING:
#   data/assets.db, arp_cat.db, users.db
#   data/capture/* (all captures)
#   data/fingerprints/* (all fingerprints)
#   data/jobs/* (all job files)
#   data/logs/* (all logs)
#   discovery/* (all topology files)
```

### Clean Command

```bash
velocitycmdb clean
# Deletes temporary files, preserves databases:
#   Keeps: data/assets.db, arp_cat.db, users.db
#   Removes: data/capture/*, fingerprints/*, jobs/*, logs/*
#   Removes: discovery/*
```

### Backup Command

```bash
# Standard backup (includes all data)
velocitycmdb backup
# Creates: velocitycmdb-backup-20251111_120000.tar.gz
# Contains: data/ + discovery/

# Custom output path
velocitycmdb backup -o /path/to/backup.tar.gz
```

**Note:** Capture files can be large (multiple GB). The backup command includes them by default since they contain historical configuration data needed for change detection.

### Restore Command

```bash
velocitycmdb restore backup.tar.gz
# Extracts to: ~/.velocitycmdb/
# Restores: data/ and discovery/ directories
```

---

## Docker Strategy

### Single Volume Mount

```yaml
# docker-compose.yml
services:
  velocitycmdb:
    image: velocitycmdb:latest
    volumes:
      - velocitycmdb-data:/app/.velocitycmdb
    ports:
      - "8086:8086"

volumes:
  velocitycmdb-data:
```

**Why single volume:**
- Simple configuration
- Captures entire state (data + discovery)
- Easy backup: `docker run --rm -v velocitycmdb-data:/data -v $(pwd):/backup alpine tar czf /backup/backup.tar.gz /data`

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install VelocityCMDB
COPY . .
RUN pip install -e .

# Set data directory
ENV VELOCITYCMDB_DATA_DIR=/app/.velocitycmdb/data

# Initialize on first run
RUN python -m velocitycmdb.cli init --admin-password=changeme

EXPOSE 8086

CMD ["velocitycmdb", "start", "--host", "0.0.0.0"]
```

---

## Backup Strategies

### Full Backup (Recommended for Production)

```bash
# Includes databases + all captures + discovery
velocitycmdb backup

# Result: ~100MB - 10GB depending on capture count
```

### Database-Only Backup (Quick)

```bash
# Just tar the databases
cd ~/.velocitycmdb/data
tar -czf ~/db-backup.tar.gz *.db

# Result: ~5-50MB
```

### Selective Backup

```bash
# Databases + configs only (skip other captures)
cd ~/.velocitycmdb
tar -czf backup.tar.gz \
    data/*.db \
    data/capture/configs/ \
    data/capture/version/ \
    data/capture/inventory/

# Result: ~50-500MB
```

---

## Migration from Old Structure

If you have an old `pcng/` structure, migrate with:

```bash
# Old structure (pre-v0.9)
~/PycharmProjects/velocitycmdb/
├── pcng/
│   └── data/
│       ├── assets.db
│       └── capture/

# Migrate to new structure
mkdir -p ~/.velocitycmdb/data
cp -r ~/PycharmProjects/velocitycmdb/pcng/data/* ~/.velocitycmdb/data/
cp -r ~/PycharmProjects/velocitycmdb/discovery ~/.velocitycmdb/

# Verify
velocitycmdb status
```

---

## Environment Variables

Override default paths:

```bash
# Set custom data directory
export VELOCITYCMDB_DATA_DIR=/custom/path/data

# Commands use this path
python -m velocitycmdb.cli init
velocitycmdb start
velocitycmdb backup
```

**Use cases:**
- Testing with separate environments
- Multi-tenant deployments
- Custom Docker configurations
- Network shared storage

---

## Size Expectations

After typical production use:

```
~/.velocitycmdb/data/
├── assets.db           ~5-50 MB   (grows with device count)
├── arp_cat.db          ~10-100 MB (grows with ARP entries)
├── users.db            ~50 KB     (small, few users)
├── fingerprints/       ~1-10 MB   (one file per device)
├── jobs/               ~5 MB      (JSON job definitions)
├── logs/               ~10-100 MB (rotate regularly)
└── capture/            ~100 MB - 10 GB (main storage)
    ├── configs/        ~50-500 MB (largest - full configs)
    ├── version/        ~1-10 MB
    ├── inventory/      ~1-10 MB
    ├── arp/            ~5-50 MB
    └── [others]/       ~1-100 MB each

~/.velocitycmdb/discovery/  ~5-50 MB (regeneratable)
```

**Recommendation:** Plan for 1-5 GB storage for typical deployment (100-500 devices).

---

## Cleanup Recommendations

### Regular Cleanup (Weekly/Monthly)

```bash
# Clean temporary files, keep databases
velocitycmdb clean
```

### Rotate Old Captures (Quarterly)

```bash
# Archive old captures
cd ~/.velocitycmdb/data/capture
tar -czf ~/old-captures-$(date +%Y%m%d).tar.gz configs/
rm -rf configs/*

# Or use find to remove captures older than 90 days
find ~/.velocitycmdb/data/capture -type f -mtime +90 -delete
```

### Full Reset (Testing Only)

```bash
# Nuclear option - delete everything
velocitycmdb reset --yes
python -m velocitycmdb.cli init
```

---

## Summary

✅ **All persistent data in `data/`** - databases, captures, jobs  
✅ **Discovery output in `discovery/`** - regeneratable topology files  
✅ **CLI handles paths automatically** - works in dev or production  
✅ **Simple backup strategy** - one directory to protect  
✅ **Docker-friendly** - single volume mount  
✅ **Scales to production** - handles GB of capture data  
