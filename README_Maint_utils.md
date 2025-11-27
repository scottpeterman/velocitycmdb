# VelocityCMDB Maintenance Utilities - Design Pattern Guide

## Overview

This guide documents the design patterns used in VelocityCMDB maintenance utilities, covering the architecture that connects CLI scripts, Flask routes, SocketIO handlers, and the service layer. Use this as a template for converting the remaining 4 maintenance utilities.

---

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                        User Interface                        │
│  (Browser-based Material Design 3 UI + Operation Log)       │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                    SocketIO Event Layer                      │
│    (maintenance_socketio.py - Real-time progress)           │
│    • Emits progress updates                                  │
│    • Handles user events                                     │
│    • Requires admin privileges                               │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                  Flask Routes (Optional)                     │
│        (maintenance_routes.py - REST endpoints)              │
│    • Non-real-time operations                                │
│    • File downloads                                          │
│    • Stats/inspection endpoints                              │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                      Service Layer                           │
│    (maintenance.py - MaintenanceOrchestrator)                │
│    • Business logic                                          │
│    • Path management                                         │
│    • Subprocess execution                                    │
│    • Progress callbacks                                      │
│    • Error handling                                          │
└─────────────────────────────────────────────────────────────┘
                              ↕
┌─────────────────────────────────────────────────────────────┐
│                     CLI Scripts Layer                        │
│    (fix_fts.py, backup.py, restore.py, etc.)               │
│    • Standalone Python scripts                               │
│    • Accept command-line arguments                           │
│    • Print status to stdout                                  │
│    • Return exit codes                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Design Patterns

### 1. Path Management Strategy

The `MaintenanceOrchestrator` manages three critical path types:

```python
class MaintenanceOrchestrator:
    def __init__(self, project_root: Path = None, data_dir: Path = None):
        """
        Initialize with flexible path discovery
        
        project_root: Where VelocityCMDB code lives
        data_dir: Where databases and user data live
        """
        # Project root discovery (code location)
        if project_root:
            self.project_root = Path(project_root)
        else:
            # Try to find project root from this file's location
            self.project_root = Path(__file__).parent.parent.parent
        
        # Data directory discovery (user data)
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path.home() / '.velocitycmdb' / 'data'
        
        # Backup directory (derived)
        self.backup_dir = self.project_root / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Database paths (derived)
        self.assets_db = self.data_dir / 'assets.db'
        self.arp_db = self.data_dir / 'arp.db'
        self.notes_db = self.data_dir / 'notes.db'
```

**Key Principles**:
- **Separation of concerns**: Code (project_root) vs Data (data_dir)
- **Flexible initialization**: Accept paths or auto-discover
- **Derived paths**: Calculate dependent paths from base paths
- **Create on demand**: `mkdir(parents=True, exist_ok=True)`

### 2. CLI Script Integration Pattern

**How to wrap existing CLI scripts as service methods:**

```python
def operation_name(self, 
                   arg1: type,
                   arg2: type = default,
                   progress_callback: Optional[Callable] = None) -> Dict:
    """
    Description of what this operation does
    
    Args:
        arg1: Description
        arg2: Description
        progress_callback: Function to call with progress updates
    
    Returns:
        {
            'success': bool,
            'key_results': values,
            'error': str (if failed)
        }
    """
    # 1. VALIDATE INPUTS AND PATHS
    if progress_callback:
        progress_callback({
            'stage': 'operation',
            'message': 'Starting operation...',
            'progress': 5
        })
    
    try:
        # 2. LOCATE CLI SCRIPT (multiple paths)
        script_paths = [
            self.project_root / 'script_name.py',
            self.project_root / 'velocitycmdb' / 'script_name.py',
            Path(__file__).parent / 'script_name.py',
        ]
        
        script = None
        for path in script_paths:
            if path.exists():
                script = path
                break
        
        if not script:
            return {
                'success': False,
                'error': f"Script not found in:\n" + 
                        "\n".join(f"  - {p}" for p in script_paths)
            }
        
        # 3. VALIDATE REQUIRED RESOURCES
        if not self.some_required_file.exists():
            return {
                'success': False,
                'error': f"Required file not found: {self.some_required_file}"
            }
        
        # 4. BUILD COMMAND
        logger.info(f"Using script: {script}")
        logger.info(f"Arguments: arg1={arg1}, arg2={arg2}")
        
        cmd = [
            'python', str(script),
            '--arg1', str(arg1),
            '--arg2', str(arg2),
        ]
        
        if progress_callback:
            progress_callback({
                'stage': 'operation',
                'message': 'Executing operation...',
                'progress': 20
            })
        
        # 5. EXECUTE WITH LOGGING
        logger.info(f"Executing: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.project_root)
        )
        
        # 6. LOG ALL OUTPUT
        if result.stdout:
            logger.info(f"Script stdout:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"Script stderr:\n{result.stderr}")
        
        # 7. HANDLE SUCCESS
        if result.returncode == 0:
            # Parse output for results
            parsed_results = self._parse_output(result.stdout)
            
            if progress_callback:
                progress_callback({
                    'stage': 'operation',
                    'message': 'Operation completed successfully',
                    'progress': 100
                })
            
            logger.info("Operation completed successfully")
            return {
                'success': True,
                'key_results': parsed_results,
                'statistics': {}  # If applicable
            }
        
        # 8. HANDLE FAILURE (DETAILED)
        error_msg = result.stderr or result.stdout or 'Operation failed'
        
        # Extract specific errors if possible
        if 'Error:' in error_msg:
            error_lines = [line for line in error_msg.split('\n') 
                          if 'Error' in line or 'error' in line.lower()]
            if error_lines:
                error_msg = '\n'.join(error_lines)
        
        logger.error(f"Operation failed with return code {result.returncode}")
        logger.error(f"Error: {error_msg}")
        
        return {
            'success': False,
            'error': error_msg,
            'return_code': result.returncode,
            'full_output': result.stdout
        }
    
    except FileNotFoundError as e:
        error_msg = f"File not found: {str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    
    except Exception as e:
        error_msg = f"Operation error: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'error': error_msg,
            'traceback': traceback.format_exc()
        }

def _parse_output(self, output: str) -> Dict:
    """Helper to extract structured data from CLI script output"""
    results = {}
    try:
        for line in output.split('\n'):
            if 'key metric:' in line.lower():
                results['key_metric'] = int(line.split(':')[1].strip())
            # Add more parsing as needed
    except Exception as e:
        logger.warning(f"Error parsing output: {e}")
    return results
```

### 3. SocketIO Event Handler Pattern

**How to create real-time WebSocket handlers:**

```python
# In maintenance_socketio.py

def register_maintenance_socketio_handlers(socketio, app):
    """Register all maintenance-related SocketIO handlers"""
    
    def require_admin():
        """Check if user is admin"""
        if not session.get('is_admin'):
            emit('maintenance_error', {'error': 'Admin privileges required'})
            return False
        return True
    
    def progress_callback(update):
        """Emit progress updates to client"""
        emit('maintenance_progress', {
            'stage': update['stage'],
            'message': update['message'],
            'progress': update['progress']
        })
    
    @socketio.on('maintenance_operation_name')
    def handle_operation(data):
        """Handle operation with real-time progress"""
        if not require_admin():
            return
        
        try:
            # Extract parameters from client
            param1 = data.get('param1')
            param2 = data.get('param2', default_value)
            
            logger.info(f"Starting operation (param1={param1}, param2={param2})")
            
            # Get service instance
            service = get_maintenance_service(app)
            
            # Call service method with progress callback
            result = service.operation_name(
                param1=param1,
                param2=param2,
                progress_callback=progress_callback
            )
            
            # Handle success
            if result['success']:
                emit('maintenance_complete', {
                    'success': True,
                    'operation': 'operation_name',
                    'key_results': result.get('key_results'),
                    'statistics': result.get('statistics', {})
                })
                logger.info(f"Operation completed: {result}")
            
            # Handle failure with details
            else:
                error_msg = result.get('error', 'Unknown error')
                emit('maintenance_error', {
                    'error': error_msg,
                    'statistics': result.get('statistics', {}),
                    'return_code': result.get('return_code'),
                    'full_output': result.get('full_output')
                })
                logger.error(f"Operation failed: {error_msg}")
        
        except Exception as e:
            logger.error(f"Operation error: {e}")
            import traceback
            error_trace = traceback.format_exc()
            logger.error(error_trace)
            
            emit('maintenance_error', {
                'error': str(e),
                'traceback': error_trace if app.debug else None
            })
    
    logger.info("Operation handlers registered")
```

### 4. Flask Route Pattern (Optional)

**For non-real-time operations (stats, downloads, etc.):**

```python
# In maintenance_routes.py

@admin_bp.route('/maintenance/operation/stats')
@admin_required
def operation_stats():
    """Get operation statistics"""
    try:
        service = get_maintenance_service()
        stats = service.get_operation_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin_bp.route('/maintenance/operation/download/<filename>')
@admin_required
def download_result(filename):
    """Download operation result file"""
    try:
        service = get_maintenance_service()
        result_file = service.results_dir / filename
        
        if not result_file.exists():
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(result_file, as_attachment=True, 
                        download_name=filename)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

---

## CLI Script Requirements

### Scripts Must Follow These Conventions

1. **Accept arguments via command line**:
   ```python
   import sys
   import argparse
   
   def main():
       parser = argparse.ArgumentParser(description='Operation description')
       parser.add_argument('database', help='Path to database')
       parser.add_argument('--option', default='value', help='Optional parameter')
       args = parser.parse_args()
       
       # Use args.database, args.option
   ```

2. **Print progress to stdout**:
   ```python
   print("Starting operation...")
   print(f"Processing {count} items...")
   print(f"Completed: {count} items processed")
   ```

3. **Print errors to stderr**:
   ```python
   import sys
   
   if error_condition:
       print(f"Error: {error_message}", file=sys.stderr)
       sys.exit(1)
   ```

4. **Use exit codes**:
   ```python
   # Success
   sys.exit(0)
   
   # Failure
   sys.exit(1)
   
   # Specific error codes
   sys.exit(2)  # Configuration error
   sys.exit(3)  # Data error
   ```

5. **Output parseable statistics**:
   ```python
   print("=== Statistics ===")
   print(f"Items processed: {count}")
   print(f"Success rate: {success_rate}%")
   print(f"Duration: {duration} seconds")
   ```

---

## Data Directory Management

### Directory Structure

```
~/.velocitycmdb/
├── data/                    # Main data directory
│   ├── assets.db           # Main database
│   ├── arp.db              # ARP cache database
│   ├── notes.db            # Notes database
│   └── captures/           # Captured data
│       ├── configs/
│       ├── inventory/
│       ├── routes/
│       └── mac/
├── logs/                   # Application logs
│   ├── velocitycmdb.log
│   └── maintenance.log
└── temp/                   # Temporary files
```

### Access Patterns

```python
class MaintenanceOrchestrator:
    def __init__(self, project_root: Path = None, data_dir: Path = None):
        # Data directory can come from:
        # 1. Constructor argument (highest priority)
        # 2. Environment variable
        # 3. Flask config
        # 4. Default location
        
        if data_dir:
            self.data_dir = Path(data_dir)
        elif os.getenv('VELOCITYCMDB_DATA_DIR'):
            self.data_dir = Path(os.getenv('VELOCITYCMDB_DATA_DIR'))
        else:
            self.data_dir = Path.home() / '.velocitycmdb' / 'data'
        
        # Always ensure directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate critical files
        self._validate_data_dir()
    
    def _validate_data_dir(self):
        """Ensure required files and directories exist"""
        required_dirs = [
            self.data_dir / 'captures',
            self.data_dir / 'captures' / 'configs',
            self.data_dir / 'captures' / 'inventory',
        ]
        
        for dir_path in required_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        required_files = [
            self.data_dir / 'assets.db',
        ]
        
        for file_path in required_files:
            if not file_path.exists():
                logger.warning(f"Expected file not found: {file_path}")
```

### Flask Integration

```python
# How Flask app passes data_dir to service

def get_maintenance_service():
    """Get configured maintenance service"""
    from flask import current_app
    
    project_root = Path(current_app.root_path).parent
    data_dir = Path(current_app.config.get('VELOCITYCMDB_DATA_DIR', '.'))
    
    return MaintenanceOrchestrator(
        project_root=project_root,
        data_dir=data_dir
    )
```

---

## Progress Callback Pattern

### How Progress Updates Work

```python
# 1. Service method accepts optional callback
def some_operation(self, progress_callback: Optional[Callable] = None):
    
    # 2. Service calls callback at key stages
    if progress_callback:
        progress_callback({
            'stage': 'initialization',  # Current stage
            'message': 'Starting up...',  # User-facing message
            'progress': 10  # Percentage (0-100)
        })
    
    # Do work...
    
    if progress_callback:
        progress_callback({
            'stage': 'processing',
            'message': 'Processing 100 items...',
            'progress': 50
        })
    
    # More work...
    
    if progress_callback:
        progress_callback({
            'stage': 'complete',
            'message': 'Operation completed',
            'progress': 100
        })

# 3. SocketIO handler provides the callback
@socketio.on('maintenance_some_operation')
def handle_operation(data):
    def progress_callback(update):
        emit('maintenance_progress', {
            'stage': update['stage'],
            'message': update['message'],
            'progress': update['progress']
        })
    
    result = service.some_operation(progress_callback=progress_callback)
```

### Progress Guidelines

- **Start at 5-10%** (never 0%, shows activity started)
- **End at 100%** (always emit completion)
- **Use meaningful stages**: 'initialization', 'processing', 'cleanup', 'complete'
- **Scale appropriately**: If subprocess does work, reserve 20-80% for it
- **Update regularly**: Every 10-20% or on state changes

---

## Error Handling Strategy

### Three-Tier Error Handling

```python
def operation(self):
    try:
        # Main logic
        result = subprocess.run(cmd, ...)
        
        if result.returncode == 0:
            return {'success': True, ...}
        
        # Tier 1: Process-level failure
        error_msg = result.stderr or result.stdout
        return {
            'success': False,
            'error': error_msg,
            'return_code': result.returncode
        }
    
    except FileNotFoundError as e:
        # Tier 2: Specific exceptions
        return {
            'success': False,
            'error': f"Required file not found: {e}"
        }
    
    except Exception as e:
        # Tier 3: Catch-all with traceback
        import traceback
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }
```

### Error Message Best Practices

```python
# ❌ Bad: Generic error
return {'success': False, 'error': 'Operation failed'}

# ✅ Good: Specific error
return {
    'success': False,
    'error': f'Database not found: {db_path}\n\nRun "velocitycmdb init" to create it.'
}

# ✅ Best: Actionable error with context
return {
    'success': False,
    'error': f'Cannot access database: {db_path}',
    'details': {
        'path_exists': db_path.exists(),
        'path_readable': os.access(db_path, os.R_OK),
        'path_writable': os.access(db_path, os.W_OK)
    },
    'suggested_action': 'Check file permissions or run "velocitycmdb init"'
}
```

---

## Return Value Standard

### All Service Methods Return This Structure

```python
{
    # REQUIRED
    'success': bool,  # True if operation succeeded
    
    # ON SUCCESS (include relevant fields)
    'operation_specific_data': value,
    'statistics': {
        'items_processed': int,
        'duration': float,
        'success_rate': float
    },
    
    # ON FAILURE (include error info)
    'error': str,  # User-facing error message
    'return_code': int,  # Process exit code (if applicable)
    'full_output': str,  # Complete output for debugging
    'traceback': str,  # Python traceback (if exception)
    
    # OPTIONAL CONTEXT
    'warnings': [str],  # Non-fatal issues
    'details': dict,  # Additional context
}
```

---

## Conversion Checklist

Use this checklist when converting remaining utilities:

### 1. Service Method Creation
- [ ] Add method to `MaintenanceOrchestrator` class
- [ ] Accept `progress_callback: Optional[Callable]` parameter
- [ ] Multi-path script discovery
- [ ] Validate required paths/files
- [ ] Build command with all arguments
- [ ] Pass data_dir-relative paths to script
- [ ] Execute with comprehensive logging
- [ ] Parse output for statistics
- [ ] Handle both success and failure cases
- [ ] Return structured result dict

### 2. SocketIO Handler Creation
- [ ] Add `@socketio.on('maintenance_operation_name')` handler
- [ ] Check admin privileges with `require_admin()`
- [ ] Extract parameters from `data` dict
- [ ] Get service instance via `get_maintenance_service(app)`
- [ ] Call service method with progress callback
- [ ] Emit `maintenance_complete` on success
- [ ] Emit `maintenance_error` on failure with details
- [ ] Emit `maintenance_progress` during execution
- [ ] Log all steps

### 3. Flask Route Creation (if needed)
- [ ] Add route to `admin_bp`
- [ ] Use `@admin_required` decorator
- [ ] Call service method (no progress callback)
- [ ] Return `jsonify(result)`
- [ ] Handle exceptions with 500 status

### 4. Testing
- [ ] Test with correct inputs (success case)
- [ ] Test with missing files (error case)
- [ ] Test with invalid data (error case)
- [ ] Verify progress updates appear in UI
- [ ] Check server logs for detailed output
- [ ] Test error messages are clear and actionable
- [ ] Verify statistics display correctly

---

## Example: Complete Utility Conversion

Let's say you're converting `reclassify_components`:

### 1. Create Service Method

```python
# In maintenance.py

def reclassify_components(self, progress_callback: Optional[Callable] = None) -> Dict:
    """
    Reclassify hardware components from inventory captures
    
    Args:
        progress_callback: Function to call with progress updates
    
    Returns:
        {
            'success': bool,
            'components_processed': int,
            'reclassified': int,
            'error': str (if failed)
        }
    """
    if progress_callback:
        progress_callback({
            'stage': 'reclassify',
            'message': 'Starting component reclassification...',
            'progress': 5
        })
    
    try:
        # Locate script
        script_paths = [
            self.project_root / 'velocitycmdb' / 'pcng' / 'reclassify_components.py',
            self.project_root / 'reclassify_components.py',
        ]
        
        script = None
        for path in script_paths:
            if path.exists():
                script = path
                break
        
        if not script:
            return {
                'success': False,
                'error': f"Reclassification script not found in:\n" +
                        "\n".join(f"  - {p}" for p in script_paths)
            }
        
        # Validate database
        if not self.assets_db.exists():
            return {
                'success': False,
                'error': f"Assets database not found: {self.assets_db}"
            }
        
        if progress_callback:
            progress_callback({
                'stage': 'reclassify',
                'message': 'Reading inventory data...',
                'progress': 20
            })
        
        # Build command
        cmd = ['python', str(script), '--database', str(self.assets_db)]
        logger.info(f"Executing: {' '.join(cmd)}")
        
        # Execute
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.project_root)
        )
        
        # Log output
        if result.stdout:
            logger.info(f"Reclassify stdout:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"Reclassify stderr:\n{result.stderr}")
        
        # Handle success
        if result.returncode == 0:
            stats = self._parse_reclassify_output(result.stdout)
            
            if progress_callback:
                progress_callback({
                    'stage': 'reclassify',
                    'message': f'Reclassified {stats.get("reclassified", 0)} components',
                    'progress': 100
                })
            
            return {
                'success': True,
                'components_processed': stats.get('processed', 0),
                'reclassified': stats.get('reclassified', 0),
                'statistics': stats
            }
        
        # Handle failure
        error_msg = result.stderr or result.stdout or 'Reclassification failed'
        logger.error(f"Reclassification failed: {error_msg}")
        
        return {
            'success': False,
            'error': error_msg,
            'return_code': result.returncode
        }
    
    except Exception as e:
        logger.error(f"Reclassification error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }

def _parse_reclassify_output(self, output: str) -> Dict:
    """Parse reclassification output for statistics"""
    stats = {}
    try:
        for line in output.split('\n'):
            if 'Processed:' in line:
                stats['processed'] = int(line.split(':')[1].strip())
            if 'Reclassified:' in line:
                stats['reclassified'] = int(line.split(':')[1].strip())
    except Exception as e:
        logger.warning(f"Error parsing reclassify output: {e}")
    return stats
```

### 2. Create SocketIO Handler

```python
# In maintenance_socketio.py

@socketio.on('maintenance_reclassify_components')
def handle_reclassify_components(data):
    """Handle component reclassification with progress"""
    if not require_admin():
        return
    
    try:
        logger.info("Starting component reclassification")
        
        service = get_maintenance_service(app)
        result = service.reclassify_components(progress_callback=progress_callback)
        
        if result['success']:
            emit('maintenance_complete', {
                'success': True,
                'operation': 'reclassify_components',
                'components_processed': result['components_processed'],
                'reclassified': result['reclassified'],
                'statistics': result.get('statistics', {})
            })
            logger.info(f"Reclassified {result['reclassified']} components")
        else:
            emit('maintenance_error', {
                'error': result.get('error', 'Unknown error'),
                'return_code': result.get('return_code')
            })
            logger.error(f"Reclassification failed: {result['error']}")
    
    except Exception as e:
        logger.error(f"Reclassification error: {e}")
        import traceback
        emit('maintenance_error', {
            'error': str(e),
            'traceback': traceback.format_exc() if app.debug else None
        })
```

---

## Remaining Utilities to Convert

Based on your maintenance panel, here are the 4 remaining utilities:

### 1. Component Processing (`reclassify_components`)
- **Script**: Probably in `velocitycmdb/pcng/` or similar
- **Purpose**: Parse inventory captures and extract hardware components
- **Arguments**: Database path
- **Output**: Component count, classification stats

### 2. ARP Database (`load_arp_data`)
- **Script**: Likely processes ARP/MAC captures
- **Purpose**: Build ARP/MAC address lookup database
- **Arguments**: Data directory, capture types
- **Output**: Entries loaded, unique MACs

### 3. Capture Data Loading (`load_capture_data`)
- **Script**: Probably `db_load_capture.py`
- **Purpose**: Manually load specific capture types into database
- **Arguments**: Capture types (configs, inventory, routes, mac)
- **Output**: Files processed, entries created

### 4. Topology Generation (`generate_topology`)
- **Script**: Likely `map_from_lldp_v2.py`
- **Purpose**: Generate network topology from LLDP/CDP data
- **Arguments**: Source type (lldp, cdp, both)
- **Output**: Device count, link count, map name

---

## Quick Reference Card

```python
# SERVICE METHOD TEMPLATE
def operation(self, param: type, progress_callback: Optional[Callable] = None) -> Dict:
    # 1. Progress: Start
    # 2. Validate: paths, files, params
    # 3. Discover: script location
    # 4. Build: command with args
    # 5. Execute: subprocess.run()
    # 6. Log: stdout, stderr
    # 7. Parse: output for stats
    # 8. Progress: Complete
    # 9. Return: structured dict

# SOCKETIO HANDLER TEMPLATE
@socketio.on('maintenance_operation')
def handle_operation(data):
    # 1. Check: admin privileges
    # 2. Extract: parameters from data
    # 3. Call: service method with progress
    # 4. Emit: maintenance_complete or maintenance_error
    # 5. Log: all steps

# RETURN DICT TEMPLATE
{
    'success': bool,
    'operation_results': values,
    'error': str,  # if failed
    'statistics': dict,  # if available
}
```

---

## Best Practices Summary

1. **Always validate paths** before executing
2. **Use multi-path discovery** for scripts
3. **Log everything** - command, stdout, stderr
4. **Parse output** for structured data
5. **Provide detailed errors** with context
6. **Use progress callbacks** for user feedback
7. **Return consistent structures** (success dict)
8. **Handle exceptions** at multiple levels
9. **Test both success and failure** paths
10. **Document expected output** formats

---

## Need Help?

When converting a utility, refer to:
- `maintenance.py::rebuild_search_indexes()` - Complete working example
- `maintenance.py::create_backup()` - Shows file path handling
- `maintenance_socketio.py::handle_rebuild_indexes()` - SocketIO pattern
- This guide - Design patterns and checklists