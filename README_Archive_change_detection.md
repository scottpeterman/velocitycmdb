```markdown
# Network Capture Archive and Change Detection System

## Overview

A snapshot-based archive system for tracking intentional configuration changes on network devices. Focuses on deliberate human actions (configs, version upgrades, hardware changes) rather than transient operational state.

## Design Philosophy

**Problem Statement**: In environments where multiple people have network access (contractors, distributed teams, startups), you need evidence of what changed, when it changed, and how significant the change was - without being buried in noise from normal network operations.

**Solution**: Selective archiving with automatic change detection. Only track capture types that represent intentional actions, generate diffs automatically, and classify change severity.

## Architecture

### Database Schema

```sql
-- Timestamped content snapshots
CREATE TABLE capture_snapshots (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL,
    capture_type TEXT NOT NULL,
    captured_at TIMESTAMP NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

-- Detected changes between snapshots
CREATE TABLE capture_changes (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL,
    capture_type TEXT NOT NULL,
    detected_at TIMESTAMP NOT NULL,
    previous_snapshot_id INTEGER,
    current_snapshot_id INTEGER NOT NULL,
    lines_added INTEGER,
    lines_removed INTEGER,
    diff_path TEXT,
    severity TEXT CHECK(severity IN ('minor', 'moderate', 'critical'))
);

-- Full-text search across archived content
CREATE VIRTUAL TABLE capture_fts USING fts5(
    content,
    content=capture_snapshots,
    content_rowid=id
);
```

### Change-Tracked Capture Types

Only three types get full snapshot/change tracking:

| Type | Why Track | Change Significance |
|------|-----------|---------------------|
| **configs** | Running configuration changes | Someone modified device config |
| **version** | Software/firmware version | Upgrade or device replacement |
| **inventory** | Hardware components | Hardware added/removed/swapped |

**Not tracked**: ARP, MAC tables, interface status, routing tables, neighbor relationships - these change constantly due to normal network operation, not human action.

### Data Flow

```
Capture File → db_load_captures.py
                    ↓
            Is it tracked type?
           /                    \
        YES                      NO
         ↓                        ↓
   load_with_snapshots()    load_current_only()
         ↓                        ↓
   1. Read content          Update device_captures_current
   2. Hash content          (no history)
   3. Check for previous
   4. If unchanged: skip
   5. If changed:
      - Insert snapshot
      - Generate diff
      - Save diff file
      - Log change record
```

## Implementation Status

### ✅ Completed (Current State)

**Database Schema**:
- `capture_snapshots` table with content storage and hashing
- `capture_changes` table with diff metadata
- `capture_fts` full-text search index
- Indexes on device_id, capture_type, timestamps

**Loader Script** (`db_load_captures.py`):
- Dual-mode loading (snapshot vs current-only)
- Content hashing for duplicate detection
- Unified diff generation
- Change severity classification
- Diff file storage in `diffs/device_id/capture_type/` hierarchy
- Statistics tracking (changes detected, files processed)

**CLI Options**:
```bash
# Load all captures with change detection
python db_load_captures.py --captures-dir capture

# Show recent changes after loading
python db_load_captures.py --show-changes --changes-hours 24

# Process single file
python db_load_captures.py --single-file capture/configs/device.txt

# Custom diff output directory
python db_load_captures.py --diff-dir /path/to/diffs
```

### 🚧 In Progress

**Web UI Integration**:
- [ ] `/changes/recent` - Recent changes dashboard
- [ ] `/changes/device/<id>` - Per-device change history
- [ ] `/changes/diff/<id>` - Diff viewer with syntax highlighting
- [ ] Change notifications (email/Slack)

**Search Enhancement**:
- [ ] Historical search across snapshots (not just current)
- [ ] Time-range filtering for searches
- [ ] "Show me when this line appeared" queries

**Reporting**:
- [ ] Daily change summary reports
- [ ] Change frequency heatmaps (which devices change most)
- [ ] Automated change digest emails

## Usage Examples

### Initial Baseline Capture

```bash
# First run establishes baseline - no changes detected
python db_load_captures.py --captures-dir capture --verbose

# Output:
# INFO - Found 456 capture files to process
# INFO - Initial snapshot: core-01 configs
# INFO - Initial snapshot: core-01 version
# INFO - Initial snapshot: core-01 inventory
# ...
# INFO - Successfully loaded: 456
# INFO - Changes detected: 0
```

### Detecting Changes

```bash
# After 4 hours, run again with new captures
python db_load_captures.py --captures-dir capture --show-changes

# Output:
# INFO - CHANGE DETECTED: dist-sw-03 configs (+23/-5 lines, moderate)
# INFO - CHANGE DETECTED: core-01 version (+1/-1 lines, critical)
# INFO - Successfully loaded: 456
# INFO - Changes detected: 2
#
# RECENT CHANGES (Last 24 hours)
# 2025-09-30T14:23:15 | dist-sw-03 (Datacenter) | configs | +23/-5 | MODERATE
# 2025-09-30T14:21:33 | core-01 (Datacenter) | version | +1/-1 | CRITICAL
```

### Querying Changes Programmatically

```python
import sqlite3

conn = sqlite3.connect('assets.db')
conn.row_factory = sqlite3.Row

# Get all critical changes in last week
cursor = conn.execute("""
    SELECT 
        cc.detected_at,
        d.name as device,
        cc.capture_type,
        cc.diff_path,
        cc.lines_added,
        cc.lines_removed
    FROM capture_changes cc
    JOIN devices d ON cc.device_id = d.id
    WHERE cc.severity = 'critical'
    AND cc.detected_at > datetime('now', '-7 days')
    ORDER BY cc.detected_at DESC
""")

for change in cursor:
    print(f"{change['detected_at']}: {change['device']} {change['capture_type']}")
    print(f"  Diff: {change['diff_path']}")
    print(f"  Changes: +{change['lines_added']}/-{change['lines_removed']}")
```

### Viewing Diffs

```bash
# Diff files are stored hierarchically
diffs/
├── 404/              # device_id
│   ├── configs/
│   │   ├── 20250930_142315.diff
│   │   └── 20250930_180412.diff
│   └── version/
│       └── 20250930_142133.diff
└── 412/
    └── inventory/
        └── 20250929_063022.diff

# View a specific diff
cat diffs/404/configs/20250930_142315.diff
```

## Change Severity Classification

The system automatically classifies change severity:

**Critical**:
- Config changes > 50 lines
- Any version change (firmware upgrades are high-risk)
- Inventory changes > 5 lines (major hardware work)

**Moderate**:
- Any config change (someone modified something)
- Moderate inventory changes

**Minor**:
- Small, routine changes

## Performance Characteristics

**Storage Impact**:
- Tracked types: ~3 types × 456 devices = ~1,368 snapshots per capture run
- Untracked types: 26 types remain in `device_captures_current` only
- Archive growth: ~1,368 snapshots per 4-hour cycle = ~8,208 daily
- Typical snapshot size: 5-50KB (configs), 1-5KB (version/inventory)
- Deduplication: Unchanged content skipped automatically via hash comparison

**Processing Speed**:
- Content hashing: ~1ms per file
- Diff generation: ~10-50ms per changed file
- Database insertion: ~2-5ms per record
- Full batch (456 devices): ~2-3 minutes with change detection

## Operational Value

### For New Environment Onboarding

When joining a new company/role:

1. **Day 1**: Run first capture to establish baseline
2. **Day 2**: Already detecting changes made by others
3. **Week 1**: Historical record of all config/version/hardware changes
4. **Week 2**: Pattern analysis - which devices change frequently, who's working on what

### For Accountability

When working alongside contractors or distributed teams:

- Evidence of what changed and when
- No reliance on memory or documentation
- Clear audit trail for troubleshooting incidents
- Protection when "nobody touched anything" but logs show otherwise

### For Incident Response

When something breaks:

```sql
-- What changed in the 24 hours before the incident?
SELECT * FROM capture_changes 
WHERE detected_at BETWEEN '2025-09-29 18:00' AND '2025-09-30 18:00'
ORDER BY severity DESC;
```

## Future Enhancements

### Short-term (Next 2 weeks)
- Web UI for viewing changes and diffs
- Email notifications for critical changes
- Change summary dashboard

### Medium-term (Next month)
- Historical search across archived snapshots
- Change approval workflow (flag/acknowledge changes)
- Integration with ticketing systems

### Long-term (Quarter)
- Compliance checking (detect unauthorized changes)
- Rollback suggestions (revert to previous snapshot)
- AI-powered change impact analysis

## Files Modified/Created

```
Database:
  assets.db
    - capture_snapshots (new table)
    - capture_changes (new table)
    - capture_fts (new FTS5 index)

Python Scripts:
  db_load_captures.py (refactored)
    - Added load_with_snapshots()
    - Added load_current_only()
    - Added diff generation
    - Added severity classification

Output:
  diffs/                    (new directory)
    └── {device_id}/
        └── {capture_type}/
            └── {timestamp}.diff
```

## Migration from Old System

**Removed**:
- `device_captures_archive` table (unused)
- `tr_captures_archive_on_update` trigger (replaced by explicit archiving)

**Preserved**:
- `device_captures_current` (still used for operational data)
- All existing capture files (unchanged)
- Device fingerprinting workflow (unchanged)

The new system coexists with existing infrastructure - no breaking changes to capture pipeline.

## Success Metrics

After 1 week of operation, you should have:
- Baseline snapshots for all tracked devices
- Change history showing actual configuration modifications
- Diff files for investigation
- Evidence trail for accountability

After 1 month:
- Pattern recognition (change frequency per device)
- Historical search capability
- Incident correlation (changes → outages)

---

**Current Status**: ✅ Core functionality operational  
**Next Priority**: Web UI for change visualization  
**Documentation**: This file  
**Contact**: Network automation team
```

This captures your current implementation state and provides a roadmap for the remaining work. The key insight - tracking only intentional changes rather than operational noise - is now documented for future reference.