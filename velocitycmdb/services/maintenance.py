"""
Maintenance Service - Orchestrates database maintenance operations
Provides service layer for backup, restore, indexing, and data processing
"""
import os
import subprocess
import json
import sqlite3
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Callable, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Import capture type mappings for UI name → directory name translation
try:
    from .capture_job_mappings import CAPTURE_TYPE_MAPPINGS
except ImportError:
    try:
        from velocitycmdb.services.capture_job_mappings import CAPTURE_TYPE_MAPPINGS
    except ImportError:
        # Fallback: empty dict means no translation (pass-through)
        CAPTURE_TYPE_MAPPINGS = {}

# Consistent default paths
DEFAULT_DATA_DIR = '~/.velocitycmdb/data'


class MaintenanceOrchestrator:
    """Orchestrates database maintenance and administrative operations"""

    def __init__(self, project_root: Path = None, data_dir: Path = None):
        """
        Initialize maintenance orchestrator

        Args:
            project_root: VelocityCMDB project root (contains velocitycmdb/ package)
            data_dir: Data directory (defaults to ~/.velocitycmdb/data)
        """
        if project_root:
            self.project_root = Path(project_root)
        else:
            # Try to find project root from this file's location
            self.project_root = Path(__file__).parent.parent.parent

        if data_dir:
            self.data_dir = Path(data_dir).expanduser()
        else:
            self.data_dir = Path(DEFAULT_DATA_DIR).expanduser()

        # Backup directory should be in data_dir, not project_root
        self.backup_dir = self.data_dir / 'backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Maintenance service initialized")
        logger.info(f"  Project root: {self.project_root}")
        logger.info(f"  Data directory: {self.data_dir}")
        logger.info(f"  Backup directory: {self.backup_dir}")
        self.assets_db = self.data_dir / 'assets.db'
        self.arp_db = self.data_dir / 'arp.db'
        self.notes_db = self.data_dir / 'notes.db'

    def create_backup(self,
                     include_captures: bool = True,
                     include_logs: bool = False,
                     progress_callback: Optional[Callable] = None) -> Dict:
        """
        Create system backup

        Args:
            include_captures: Include capture files (can be large)
            include_logs: Include log files
            progress_callback: Function to call with progress updates

        Returns:
            {
                'success': bool,
                'backup_file': Path,
                'size_mb': float,
                'manifest': dict,
                'error': str (if failed)
            }
        """
        if progress_callback:
            progress_callback({
                'stage': 'backup',
                'message': 'Starting backup process...',
                'progress': 0
            })

        try:
            # Try multiple possible backup script locations
            backup_script_paths = [
                self.project_root / 'backup.py',
                self.project_root / 'velocitycmdb' / 'backup.py',
                Path(__file__).parent.parent / 'backup.py',  # velocitycmdb/backup.py
            ]

            backup_script = None
            for path in backup_script_paths:
                if path.exists():
                    backup_script = path
                    break

            if not backup_script:
                raise FileNotFoundError(
                    f"Backup script not found in any of these locations:\n" +
                    "\n".join(f"  - {p}" for p in backup_script_paths)
                )

            logger.info(f"Using backup script: {backup_script}")
            logger.info(f"Data directory: {self.data_dir}")
            logger.info(f"Backup output: {self.backup_dir}")

            cmd = [
                sys.executable, str(backup_script),
                '--data-dir', str(self.data_dir),
                '--output', str(self.backup_dir)
            ]

            if not include_captures:
                cmd.append('--no-captures')

            if include_logs:
                cmd.append('--include-logs')

            logger.info(f"Executing: {' '.join(cmd)}")

            if progress_callback:
                progress_callback({
                    'stage': 'backup',
                    'message': 'Backing up databases...',
                    'progress': 25
                })

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_root))

            # Log output for debugging
            if result.stdout:
                logger.info(f"Backup stdout:\n{result.stdout}")
            if result.stderr:
                logger.warning(f"Backup stderr:\n{result.stderr}")

            if result.returncode == 0:
                # Find the most recent backup
                backups = list(self.backup_dir.glob('velocitycmdb_backup_*.tar.gz'))
                if backups:
                    latest_backup = max(backups, key=lambda p: p.stat().st_mtime)
                    size_mb = latest_backup.stat().st_size / (1024 * 1024)

                    if progress_callback:
                        progress_callback({
                            'stage': 'backup',
                            'message': f'Backup complete: {latest_backup.name}',
                            'progress': 100
                        })

                    logger.info(f"Backup created successfully: {latest_backup} ({size_mb:.2f} MB)")

                    return {
                        'success': True,
                        'backup_file': latest_backup,
                        'filename': latest_backup.name,
                        'size_mb': round(size_mb, 2),
                        'backup_path': str(latest_backup),  # Full path for user
                        'data_dir': str(self.data_dir)  # Show where data came from
                    }
                else:
                    logger.error("No backup files found after successful execution")
                    return {
                        'success': False,
                        'error': 'Backup completed but no archive file was created'
                    }

            logger.error(f"Backup failed with return code {result.returncode}")
            logger.error(f"Stderr: {result.stderr}")
            return {
                'success': False,
                'error': result.stderr or f'Backup process failed (exit code {result.returncode})'
            }

        except Exception as e:
            logger.error(f"Backup error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e)
            }

    def inspect_backup(self, backup_file: Path) -> Dict:
        """
        Inspect backup archive without restoring

        Args:
            backup_file: Path to backup archive

        Returns:
            {
                'success': bool,
                'manifest': dict,
                'error': str (if failed)
            }
        """
        try:
            restore_script = self.project_root / 'velocitycmdb' / 'restore.py'

            if not restore_script.exists():
                raise FileNotFoundError(f"Restore script not found: {restore_script}")

            cmd = [sys.executable, str(restore_script), '--inspect', str(backup_file)]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                return {
                    'success': True,
                    'manifest': {'raw_output': result.stdout}
                }

            return {
                'success': False,
                'error': result.stderr or 'Inspection failed'
            }

        except Exception as e:
            logger.error(f"Backup inspection error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def rebuild_search_indexes(self,
                              progress_callback: Optional[Callable] = None) -> Dict:
        """
        Rebuild FTS5 search indexes

        Args:
            progress_callback: Function to call with progress updates

        Returns:
            {
                'success': bool,
                'indexes_rebuilt': list,
                'statistics': dict,
                'error': str (if failed)
            }
        """
        if progress_callback:
            progress_callback({
                'stage': 'indexes',
                'message': 'Starting search index rebuild...',
                'progress': 5
            })

        try:
            # Try multiple possible locations for fix_fts.py
            fix_fts_paths = [
                self.project_root / 'fix_fts.py',
                self.project_root / 'velocitycmdb' / 'fix_fts.py',
                Path(__file__).parent / 'fix_fts.py',
            ]

            fix_fts_script = None
            for path in fix_fts_paths:
                if path.exists():
                    fix_fts_script = path
                    break

            if not fix_fts_script:
                error_msg = (
                    f"FTS fix script not found in any of these locations:\n" +
                    "\n".join(f"  - {p}" for p in fix_fts_paths)
                )
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg,
                    'indexes_rebuilt': []
                }

            # Determine database path
            assets_db = self.assets_db
            if not assets_db.exists():
                error_msg = f"Assets database not found: {assets_db}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg,
                    'indexes_rebuilt': []
                }

            logger.info(f"Using FTS fix script: {fix_fts_script}")
            logger.info(f"Target database: {assets_db}")

            if progress_callback:
                progress_callback({
                    'stage': 'indexes',
                    'message': 'Rebuilding FTS5 indexes...',
                    'progress': 20
                })

            # Execute fix_fts.py with database path
            cmd = [sys.executable, str(fix_fts_script), str(assets_db)]
            logger.info(f"Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root)
            )

            # Log all output for debugging
            if result.stdout:
                logger.info(f"FTS rebuild stdout:\n{result.stdout}")
            if result.stderr:
                logger.warning(f"FTS rebuild stderr:\n{result.stderr}")

            if result.returncode == 0:
                # Parse output for statistics
                statistics = self._parse_fts_output(result.stdout)

                if progress_callback:
                    progress_callback({
                        'stage': 'indexes',
                        'message': 'Indexes rebuilt successfully',
                        'progress': 100
                    })

                logger.info("Index rebuild completed successfully")
                return {
                    'success': True,
                    'indexes_rebuilt': ['capture_fts'],
                    'statistics': statistics
                }

            # Handle failure - provide detailed error info
            error_msg = result.stderr or result.stdout or 'Index rebuild failed with no error message'

            # Try to extract more specific error from output
            if 'Error:' in error_msg:
                # Extract just the error part
                error_lines = [line for line in error_msg.split('\n') if 'Error' in line or 'error' in line.lower()]
                if error_lines:
                    error_msg = '\n'.join(error_lines)

            logger.error(f"Index rebuild failed with return code {result.returncode}")
            logger.error(f"Error output: {error_msg}")

            return {
                'success': False,
                'error': error_msg,
                'indexes_rebuilt': [],
                'return_code': result.returncode,
                'full_output': result.stdout if result.stdout else None
            }

        except FileNotFoundError as e:
            error_msg = f"Script not found: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'indexes_rebuilt': []
            }

        except Exception as e:
            error_msg = f"Index rebuild error: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': error_msg,
                'indexes_rebuilt': [],
                'traceback': traceback.format_exc()
            }

    def _parse_fts_output(self, output: str) -> Dict:
        """
        Parse fix_fts.py output for statistics

        Args:
            output: Stdout from fix_fts.py

        Returns:
            Dictionary of statistics
        """
        stats = {}

        try:
            for line in output.split('\n'):
                if 'Snapshots in database:' in line:
                    try:
                        stats['snapshots_total'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'FTS entries before:' in line:
                    try:
                        stats['fts_entries_before'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'FTS entries after:' in line:
                    try:
                        stats['fts_entries_after'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'Indexed' in line and 'snapshots' in line:
                    try:
                        stats['indexed_count'] = int(line.split()[1])
                    except:
                        pass

            # Determine integrity status
            if stats.get('snapshots_total') == stats.get('fts_entries_after'):
                stats['integrity_check'] = 'passed'
            elif 'fts_entries_after' in stats:
                stats['integrity_check'] = 'warning'

        except Exception as e:
            logger.warning(f"Error parsing FTS output: {e}")

        return stats


    def load_arp_data(self,
                     progress_callback: Optional[Callable] = None) -> Dict:
        """
        Load ARP data from captures

        Args:
            progress_callback: Function to call with progress updates

        Returns:
            {
                'success': bool,
                'entries_loaded': int,
                'files_processed': int,
                'error': str (if failed)
            }
        """
        if progress_callback:
            progress_callback({
                'stage': 'arp',
                'message': 'Loading ARP data...',
                'progress': 5
            })

        try:
            # Locate ARP loader script - try multiple locations
            loader_paths = [
                self.project_root / 'velocitycmdb' / 'arp_cat_loader.py',
                self.project_root / 'arp_cat_loader.py',
                Path(__file__).parent.parent / 'arp_cat_loader.py',
            ]

            arp_loader_script = None
            for path in loader_paths:
                if path.exists():
                    arp_loader_script = path
                    break

            if not arp_loader_script:
                return {
                    'success': False,
                    'error': f"ARP loader script not found in:\n" +
                             "\n".join(f"  - {p}" for p in loader_paths)
                }

            # Validate assets database
            if not self.assets_db.exists():
                return {
                    'success': False,
                    'error': f"Assets database not found: {self.assets_db}"
                }

            # Validate/create ARP database path
            arp_db = self.data_dir / 'arp_cat.db'

            # Find TextFSM templates database
            textfsm_paths = [
                self.project_root / 'tfsm_templates.db',
                self.project_root / 'velocitycmdb' / 'tfsm_templates.db',
                self.project_root / 'pcng' / 'tfsm_templates.db',
                self.data_dir / 'tfsm_templates.db',
            ]

            textfsm_db = None
            for path in textfsm_paths:
                if path.exists():
                    textfsm_db = path
                    break

            if not textfsm_db:
                return {
                    'success': False,
                    'error': f"TextFSM templates database not found in:\n" +
                             "\n".join(f"  - {p}" for p in textfsm_paths)
                }

            # Validate captures directory
            captures_dir = self.data_dir / 'capture'
            if not captures_dir.exists():
                return {
                    'success': False,
                    'error': f"Captures directory not found: {captures_dir}\n" +
                             "Run collection wizard first to gather capture data."
                }

            logger.info(f"Using ARP loader: {arp_loader_script}")
            logger.info(f"Assets database: {self.assets_db}")
            logger.info(f"ARP database: {arp_db}")
            logger.info(f"TextFSM database: {textfsm_db}")
            logger.info(f"Captures directory: {captures_dir}")

            # Emit resolved paths for troubleshooting
            if progress_callback:
                progress_callback({
                    'stage': 'arp',
                    'message': f'Python: {sys.executable}',
                    'progress': 8
                })
                progress_callback({
                    'stage': 'arp',
                    'message': f'Script: {arp_loader_script}',
                    'progress': 10
                })
                progress_callback({
                    'stage': 'arp',
                    'message': f'Assets DB: {self.assets_db}',
                    'progress': 12
                })
                progress_callback({
                    'stage': 'arp',
                    'message': f'ARP DB: {arp_db}',
                    'progress': 14
                })
                progress_callback({
                    'stage': 'arp',
                    'message': f'TextFSM DB: {textfsm_db}',
                    'progress': 16
                })
                progress_callback({
                    'stage': 'arp',
                    'message': f'Captures dir: {captures_dir}',
                    'progress': 18
                })

            # Build command with correct arguments
            # Expected CLI: python arp_cat_loader.py --assets-db <path> --arp-db <path> --textfsm-db <path> --captures-dir <path> -v
            cmd = [
                sys.executable, str(arp_loader_script),
                '--assets-db', str(self.assets_db),
                '--arp-db', str(arp_db),
                '--textfsm-db', str(textfsm_db),
                '--captures-dir', str(captures_dir),
                '-v'  # Verbose output
            ]

            # Emit full command for troubleshooting
            if progress_callback:
                progress_callback({
                    'stage': 'arp',
                    'message': f'Command: {" ".join(cmd)}',
                    'progress': 20
                })

            logger.info(f"Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root)
            )

            # Log output
            if result.stdout:
                logger.info(f"ARP loader stdout:\n{result.stdout}")
            if result.stderr:
                logger.warning(f"ARP loader stderr:\n{result.stderr}")

            if result.returncode == 0:
                # Parse output for statistics
                stats = self._parse_arp_loader_output(result.stdout)

                if progress_callback:
                    progress_callback({
                        'stage': 'arp',
                        'message': f'Loaded {stats.get("entries_loaded", 0)} ARP entries',
                        'progress': 100
                    })

                logger.info("ARP data loading completed successfully")
                return {
                    'success': True,
                    'entries_loaded': stats.get('entries_loaded', 0),
                    'files_processed': stats.get('files_processed', 0)
                }

            # Handle failure
            error_msg = result.stderr or result.stdout or 'ARP load failed'
            logger.error(f"ARP loading failed: {error_msg}")

            return {
                'success': False,
                'error': error_msg,
                'return_code': result.returncode
            }

        except Exception as e:
            error_msg = f"ARP loading error: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': error_msg
            }

    def get_arp_stats(self) -> Dict:
        """
        Get ARP database statistics

        Returns:
            {
                'total_entries': int,
                'unique_macs': int,
                'last_updated': str
            }
        """
        try:
            arp_db = self.data_dir / 'arp_cat.db'

            if not arp_db.exists():
                return {'total_entries': 0, 'unique_macs': 0, 'last_updated': None}

            conn = sqlite3.connect(str(arp_db))
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM arp_entries")
            total_entries = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT mac_address) FROM arp_entries")
            unique_macs = cursor.fetchone()[0]

            cursor.execute("SELECT MAX(capture_timestamp) FROM arp_entries")
            last_updated = cursor.fetchone()[0]

            conn.close()

            return {
                'total_entries': total_entries,
                'unique_macs': unique_macs,
                'last_updated': last_updated
            }

        except Exception as e:
            logger.error(f"Error getting ARP stats: {e}")
            return {'total_entries': 0, 'unique_macs': 0, 'last_updated': None}

    def load_capture_data(self,
                         capture_types: List[str] = None,
                         progress_callback: Optional[Callable] = None) -> Dict:
        """
        Manually load capture data into database

        Args:
            capture_types: List of capture types to load (configs, inventory, routes, mac, etc.)
                          If None, loads all available capture types
            progress_callback: Function to call with progress updates

        Returns:
            {
                'success': bool,
                'files_processed': int,
                'files_failed': int,
                'error': str (if failed)
            }
        """
        if progress_callback:
            types_msg = ", ".join(capture_types) if capture_types else "all"
            progress_callback({
                'stage': 'captures',
                'message': f'Loading {types_msg} captures...',
                'progress': 5
            })

        try:
            # Locate capture loader script - try multiple locations
            # Note: script was renamed from db_load_capture.py to db_load_capture.py
            loader_paths = [
                self.project_root / 'velocitycmdb' / 'db_load_capture.py',
                self.project_root / 'db_load_capture.py',
                self.project_root / 'velocitycmdb' / 'pcng' / 'db_load_capture.py',
                Path(__file__).parent.parent / 'pcng' / 'db_load_capture.py',
                # Legacy names for backwards compatibility
                self.project_root / 'velocitycmdb' / 'pcng' / 'db_load_capture.py',
                self.project_root / 'db_load_capture.py',
            ]

            load_script = None
            for path in loader_paths:
                if path.exists():
                    load_script = path
                    break

            if not load_script:
                return {
                    'success': False,
                    'error': f"Capture loader script not found in:\n" +
                             "\n".join(f"  - {p}" for p in loader_paths)
                }

            # Validate assets database
            if not self.assets_db.exists():
                return {
                    'success': False,
                    'error': f"Assets database not found: {self.assets_db}"
                }

            # Validate captures directory
            captures_dir = self.data_dir / 'capture'
            if not captures_dir.exists():
                return {
                    'success': False,
                    'error': f"Captures directory not found: {captures_dir}\n" +
                             "Run collection wizard first to gather capture data."
                }

            logger.info(f"Using capture loader: {load_script}")
            logger.info(f"Data directory: {self.data_dir}")
            logger.info(f"Assets database: {self.assets_db}")
            logger.info(f"Captures directory: {captures_dir}")

            # Emit resolved paths for troubleshooting
            if progress_callback:
                progress_callback({
                    'stage': 'captures',
                    'message': f'Python: {sys.executable}',
                    'progress': 8
                })
                progress_callback({
                    'stage': 'captures',
                    'message': f'Script: {load_script}',
                    'progress': 10
                })
                progress_callback({
                    'stage': 'captures',
                    'message': f'Data dir: {self.data_dir}',
                    'progress': 12
                })
                progress_callback({
                    'stage': 'captures',
                    'message': f'Captures dir: {captures_dir}',
                    'progress': 14
                })

            # Build command with --data-dir for proper diff path storage
            # The loader will derive paths from data_dir:
            #   - db_path: {data_dir}/assets.db
            #   - captures_dir: {data_dir}/capture
            #   - diff_output_dir: {data_dir}/diffs
            cmd = [
                sys.executable, str(load_script),
                '-v',  # Verbose output
                '--data-dir', str(self.data_dir),
            ]

            # Add capture type filter if specified
            # Translate UI names (e.g., 'lldp') to actual directory names (e.g., 'lldp-detail')
            if capture_types:
                translated_types = []
                for ct in capture_types:
                    if ct in CAPTURE_TYPE_MAPPINGS:
                        # Use job_suffix which matches the actual capture directory name
                        dir_name = CAPTURE_TYPE_MAPPINGS[ct].get('job_suffix', ct)
                        translated_types.append(dir_name)
                        if dir_name != ct:
                            logger.info(f"Translated capture type: {ct} → {dir_name}")
                            if progress_callback:
                                progress_callback({
                                    'stage': 'captures',
                                    'message': f'Translated: {ct} → {dir_name}',
                                    'progress': 16
                                })
                    else:
                        translated_types.append(ct)  # Pass through unknown types
                cmd.extend(['--capture-types', ','.join(translated_types)])

            # Emit full command for troubleshooting
            if progress_callback:
                progress_callback({
                    'stage': 'captures',
                    'message': f'Command: {" ".join(cmd)}',
                    'progress': 18
                })

            logger.info(f"Executing: {' '.join(cmd)}")

            # Execute capture loader
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root)
            )

            # Log output
            if result.stdout:
                logger.info(f"Capture loader stdout:\n{result.stdout}")
            if result.stderr:
                logger.warning(f"Capture loader stderr:\n{result.stderr}")

            # Check success
            if result.returncode == 0:
                # Parse output for statistics
                stats = self._parse_capture_loader_output(result.stdout)

                if progress_callback:
                    msg = f'Loaded {stats.get("files_processed", 0)} files'
                    if stats.get('changes_detected', 0) > 0:
                        msg += f', {stats["changes_detected"]} changes detected'
                    progress_callback({
                        'stage': 'captures',
                        'message': msg,
                        'progress': 100
                    })

                logger.info("Capture data loading completed successfully")
                return {
                    'success': True,
                    'files_processed': stats.get('files_processed', 0),
                    'files_failed': stats.get('files_failed', 0),
                    'snapshots_created': stats.get('snapshots_created', 0),
                    'changes_detected': stats.get('changes_detected', 0)
                }

            # Handle failure
            error_msg = result.stderr or result.stdout or 'Capture loading failed'
            logger.error(f"Capture loading failed: {error_msg}")

            return {
                'success': False,
                'error': error_msg,
                'return_code': result.returncode
            }

        except Exception as e:
            error_msg = f"Capture loading error: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': error_msg
            }


    def reclassify_components(self,
                              delete_junk: bool = False,
                              progress_callback: Optional[Callable] = None) -> Dict:
        """
        Process components in two steps:
        1. Load inventory data into components table
        2. Reclassify unknown components using pattern matching

        Args:
            delete_junk: Whether to delete junk components after reclassification
            progress_callback: Function to call with progress updates

        Returns:
            {
                'success': bool,
                'step1': {
                    'files_processed': int,
                    'files_failed': int,
                    'components_loaded': int
                },
                'step2': {
                    'components_reclassified': int,
                    'junk_deleted': int,
                    'by_type': dict
                },
                'error': str (if failed)
            }
        """
        if progress_callback:
            progress_callback({
                'stage': 'components',
                'message': 'Starting component processing...',
                'progress': 5
            })

        result = {
            'success': False,
            'step1': {},
            'step2': {},
            'error': None
        }

        try:
            # ===== STEP 1: Load Inventory Data =====
            if progress_callback:
                progress_callback({
                    'stage': 'components',
                    'message': 'Step 1/2: Loading inventory data...',
                    'progress': 10
                })

            # Locate inventory loader script
            loader_paths = [
                self.project_root / 'velocitycmdb' / 'pcng' / 'db_loader_inventory.py',
                self.project_root / 'db_loader_inventory.py',
                Path(__file__).parent.parent / 'pcng' / 'db_loader_inventory.py',
            ]

            loader_script = None
            for path in loader_paths:
                if path.exists():
                    loader_script = path
                    break

            if not loader_script:
                return {
                    'success': False,
                    'error': f"Inventory loader script not found in:\n" +
                             "\n".join(f"  - {p}" for p in loader_paths),
                    'step1': {},
                    'step2': {}
                }

            # Validate assets database
            if not self.assets_db.exists():
                return {
                    'success': False,
                    'error': f"Assets database not found: {self.assets_db}",
                    'step1': {},
                    'step2': {}
                }

            # Check for TextFSM templates database
            textfsm_db_paths = [
                self.project_root / 'tfsm_templates.db',
                self.project_root / 'velocitycmdb' / 'tfsm_templates.db',
                self.project_root / 'pcng' / 'tfsm_templates.db',
                self.data_dir / 'tfsm_templates.db',
            ]

            textfsm_db = None
            for path in textfsm_db_paths:
                if path.exists():
                    textfsm_db = path
                    break

            if not textfsm_db:
                return {
                    'success': False,
                    'error': f"TextFSM templates database not found in:\n" +
                             "\n".join(f"  - {p}" for p in textfsm_db_paths) +
                             "\n\nInstall with: pip install tfsm-fire\n" +
                             "Or download from: https://github.com/scottpeterman/tfsm-fire",
                    'step1': {},
                    'step2': {}
                }

            logger.info(f"Using inventory loader: {loader_script}")
            logger.info(f"Assets database: {self.assets_db}")
            logger.info(f"TextFSM database: {textfsm_db}")

            # Build command for inventory loader
            cmd1 = [
                sys.executable,'-u', str(loader_script),

                '--assets-db', str(self.assets_db),
                '--textfsm-db', str(textfsm_db)
            ]

            logger.info(f"Executing Step 1: {' '.join(cmd1)}")

            if progress_callback:
                progress_callback({
                    'stage': 'components',
                    'message': 'Loading inventory captures...',
                    'progress': 20
                })

            # Execute inventory loader
            result1 = subprocess.run(
                cmd1,
                capture_output=True,
                text=True,
                cwd=str(self.project_root)
            )

            # Log output
            if result1.stdout:
                logger.info(f"Inventory loader stdout:\n{result1.stdout}")
            if result1.stderr:
                logger.warning(f"Inventory loader stderr:\n{result1.stderr}")

            # Check Step 1 success
            if result1.returncode != 0:
                error_msg = result1.stderr or result1.stdout or 'Inventory loading failed'
                logger.error(f"Step 1 failed: {error_msg}")
                return {
                    'success': False,
                    'error': f"Step 1 (Inventory Loading) failed:\n{error_msg}",
                    'step1': {},
                    'step2': {},
                    'return_code': result1.returncode
                }

            # Parse Step 1 output
            step1_stats = self._parse_inventory_loader_output(result1.stdout)
            result['step1'] = step1_stats

            logger.info(f"Step 1 complete: {step1_stats}")

            # ===== STEP 2: Reclassify Components =====
            if progress_callback:
                progress_callback({
                    'stage': 'components',
                    'message': 'Step 2/2: Reclassifying unknown components...',
                    'progress': 60
                })

            # Locate reclassifier script
            reclassifier_paths = [
                self.project_root / 'velocitycmdb' / 'pcng' / 'component_reclassifier_v2.py',
                self.project_root / 'component_reclassifier_v2.py',
                Path(__file__).parent.parent / 'pcng' / 'component_reclassifier_v2.py',
            ]

            reclassifier_script = None
            for path in reclassifier_paths:
                if path.exists():
                    reclassifier_script = path
                    break

            if not reclassifier_script:
                return {
                    'success': False,
                    'error': f"Component reclassifier script not found in:\n" +
                             "\n".join(f"  - {p}" for p in reclassifier_paths),
                    'step1': step1_stats,
                    'step2': {}
                }

            logger.info(f"Using reclassifier: {reclassifier_script}")

            # Build command for reclassifier
            cmd2 = [
                sys.executable, str(reclassifier_script),
                '--db', str(self.assets_db),
                '--delete-junk'
            ]

            # Add delete-junk flag if requested
            if delete_junk:
                cmd2.append('--delete-junk')

            logger.info(f"Executing Step 2: {' '.join(cmd2)}")

            # Execute reclassifier
            result2 = subprocess.run(
                cmd2,
                capture_output=True,
                text=True,
                cwd=str(self.project_root)
            )

            # Log output
            if result2.stdout:
                logger.info(f"Reclassifier stdout:\n{result2.stdout}")
            if result2.stderr:
                logger.warning(f"Reclassifier stderr:\n{result2.stderr}")

            # Check Step 2 success
            if result2.returncode != 0:
                error_msg = result2.stderr or result2.stdout or 'Reclassification failed'
                logger.error(f"Step 2 failed: {error_msg}")
                return {
                    'success': False,
                    'error': f"Step 2 (Reclassification) failed:\n{error_msg}",
                    'step1': step1_stats,
                    'step2': {},
                    'return_code': result2.returncode
                }

            # Parse Step 2 output
            step2_stats = self._parse_reclassifier_output(result2.stdout)
            result['step2'] = step2_stats

            logger.info(f"Step 2 complete: {step2_stats}")

            # ===== SUCCESS =====
            if progress_callback:
                progress_callback({
                    'stage': 'components',
                    'message': 'Component processing complete',
                    'progress': 100
                })

            result['success'] = True
            logger.info("Component processing completed successfully")

            return result

        except FileNotFoundError as e:
            error_msg = f"Required file not found: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'step1': result.get('step1', {}),
                'step2': result.get('step2', {})
            }

        except Exception as e:
            error_msg = f"Component processing error: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': error_msg,
                'step1': result.get('step1', {}),
                'step2': result.get('step2', {}),
                'traceback': traceback.format_exc()
            }

    def _parse_inventory_loader_output(self, output: str) -> Dict:
        """
        Parse db_loader_inventory.py output for statistics

        Example output:
            Inventory Loading Summary:
              Processed: 357
              Failed: 0
              Components: 1684
        """
        stats = {
            'files_processed': 0,
            'files_failed': 0,
            'components_loaded': 0
        }

        try:
            for line in output.split('\n'):
                if 'Processed:' in line:
                    try:
                        stats['files_processed'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'Failed:' in line:
                    try:
                        stats['files_failed'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'Components:' in line:
                    try:
                        stats['components_loaded'] = int(line.split(':')[1].strip())
                    except:
                        pass
        except Exception as e:
            logger.warning(f"Error parsing inventory loader output: {e}")

        return stats

    def _parse_reclassifier_output(self, output: str) -> Dict:
        """
        Parse component_reclassifier_v2.py output for statistics

        Example output:
            FINAL STATE
            =========================================
            Total components: 1684
            Unknown: 45 (2.7%)
            Reclassified: 128

            By Type:
              transceiver        845 (50.2%)
              psu                 42 ( 2.5%)
              ...
        """
        stats = {
            'total_components': 0,
            'unknown_count': 0,
            'unknown_pct': 0.0,
            'reclassified_count': 0,
            'junk_deleted': 0,
            'by_type': {}
        }

        try:
            in_by_type_section = False

            for line in output.split('\n'):
                line = line.strip()

                # Parse header stats
                if 'Total components:' in line:
                    try:
                        stats['total_components'] = int(line.split(':')[1].strip())
                    except:
                        pass

                elif 'Unknown:' in line and '(' in line:
                    try:
                        # "Unknown: 45 (2.7%)"
                        parts = line.split(':')[1].strip().split('(')
                        stats['unknown_count'] = int(parts[0].strip())
                        stats['unknown_pct'] = float(parts[1].rstrip('%)'))
                    except:
                        pass

                elif 'Reclassified:' in line:
                    try:
                        stats['reclassified_count'] = int(line.split(':')[1].strip())
                    except:
                        pass

                elif 'Deleted' in line and 'junk' in line.lower():
                    try:
                        # "✓ Deleted 23 junk components"
                        parts = line.split()
                        for i, word in enumerate(parts):
                            if word.isdigit():
                                stats['junk_deleted'] = int(word)
                                break
                    except:
                        pass

                # Parse by-type section
                elif 'By Type:' in line:
                    in_by_type_section = True
                    continue

                elif in_by_type_section and line:
                    # Parse lines like "  transceiver        845 (50.2%)"
                    try:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            comp_type = parts[0]
                            count = int(parts[1])
                            stats['by_type'][comp_type] = count
                    except:
                        pass

        except Exception as e:
            logger.warning(f"Error parsing reclassifier output: {e}")

        return stats

    def _parse_arp_loader_output(self, output: str) -> Dict:
        """
        Parse arp_cat_loader.py output for statistics

        Expected format:
        Files processed: 30
        Total entries: 1234
        """
        stats = {
            'files_processed': 0,
            'entries_loaded': 0
        }

        try:
            import re
            for line in output.split('\n'):
                line = line.strip()

                # "Files processed: 30"
                if 'files processed:' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['files_processed'] = int(numbers[0])

                # "Total entries: 1234"
                elif 'total entries:' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['entries_loaded'] = int(numbers[0])

        except Exception as e:
            logger.warning(f"Error parsing ARP loader output: {e}")

        return stats

    def get_component_stats(self) -> Dict:
        """Get current component statistics from database"""
        try:
            conn = sqlite3.connect(str(self.assets_db))
            cursor = conn.cursor()

            stats = {}

            # Total components
            cursor.execute("SELECT COUNT(*) FROM components")
            stats['total_components'] = cursor.fetchone()[0]

            # By type
            cursor.execute("""
                SELECT type, COUNT(*) as count
                FROM components
                GROUP BY type
                ORDER BY count DESC
            """)
            stats['by_type'] = dict(cursor.fetchall())

            # Unknown count and percentage
            unknown = stats['by_type'].get('unknown', 0) + stats['by_type'].get(None, 0)
            total = stats['total_components']
            stats['unknown_count'] = unknown
            stats['unknown_pct'] = (unknown / total * 100) if total > 0 else 0

            # Reclassified count
            cursor.execute("""
                SELECT COUNT(*) FROM components 
                WHERE subtype = 'reclassified'
            """)
            stats['reclassified_count'] = cursor.fetchone()[0]

            conn.close()
            return stats

        except Exception as e:
            logger.error(f"Error getting component stats: {e}")
            return {
                'total_components': 0,
                'unknown_count': 0,
                'unknown_pct': 0,
                'reclassified_count': 0,
                'by_type': {}
            }
    def _parse_inventory_loader_output(self, output: str) -> Dict:
        """
        Parse db_loader_inventory.py output for statistics

        Example output:
            Inventory Loading Summary:
              Processed: 357
              Failed: 0
              Components: 1684
        """
        stats = {
            'files_processed': 0,
            'files_failed': 0,
            'components_loaded': 0
        }

        try:
            for line in output.split('\n'):
                if 'Processed:' in line:
                    try:
                        stats['files_processed'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'Failed:' in line:
                    try:
                        stats['files_failed'] = int(line.split(':')[1].strip())
                    except:
                        pass
                elif 'Components:' in line:
                    try:
                        stats['components_loaded'] = int(line.split(':')[1].strip())
                    except:
                        pass
        except Exception as e:
            logger.warning(f"Error parsing inventory loader output: {e}")

        return stats

    def _parse_reclassifier_output(self, output: str) -> Dict:
        """
        Parse component_reclassifier_v2.py output for statistics

        Example output:
            FINAL STATE
            =========================================
            Total components: 1684
            Unknown: 45 (2.7%)
            Reclassified: 128

            By Type:
              transceiver        845 (50.2%)
              psu                 42 ( 2.5%)
              ...
        """
        stats = {
            'total_components': 0,
            'unknown_count': 0,
            'unknown_pct': 0.0,
            'reclassified_count': 0,
            'junk_deleted': 0,
            'by_type': {}
        }

        try:
            in_by_type_section = False

            for line in output.split('\n'):
                line = line.strip()

                # Parse header stats
                if 'Total components:' in line:
                    try:
                        stats['total_components'] = int(line.split(':')[1].strip())
                    except:
                        pass

                elif 'Unknown:' in line and '(' in line:
                    try:
                        # "Unknown: 45 (2.7%)"
                        parts = line.split(':')[1].strip().split('(')
                        stats['unknown_count'] = int(parts[0].strip())
                        stats['unknown_pct'] = float(parts[1].rstrip('%)'))
                    except:
                        pass

                elif 'Reclassified:' in line:
                    try:
                        stats['reclassified_count'] = int(line.split(':')[1].strip())
                    except:
                        pass

                elif 'Deleted' in line and 'junk' in line.lower():
                    try:
                        # "✓ Deleted 23 junk components"
                        parts = line.split()
                        for i, word in enumerate(parts):
                            if word.isdigit():
                                stats['junk_deleted'] = int(word)
                                break
                    except:
                        pass

                # Parse by-type section
                elif 'By Type:' in line:
                    in_by_type_section = True
                    continue

                elif in_by_type_section and line:
                    # Parse lines like "  transceiver        845 (50.2%)"
                    try:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            comp_type = parts[0]
                            count = int(parts[1])
                            stats['by_type'][comp_type] = count
                    except:
                        pass

        except Exception as e:
            logger.warning(f"Error parsing reclassifier output: {e}")

        return stats
    def _parse_capture_loader_output(self, output: str) -> Dict:
        """
        Parse db_load_capture.py output for statistics

        Expected format:
        Total files: 30
        Successfully loaded: 30
        Failed: 0
        Snapshots created/updated: 5
        Changes detected: 2
        """
        stats = {
            'files_processed': 0,
            'files_failed': 0,
            'snapshots_created': 0,
            'changes_detected': 0
        }

        try:
            import re
            for line in output.split('\n'):
                line = line.strip()

                # "Successfully loaded: 30"
                if 'successfully loaded:' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['files_processed'] = int(numbers[0])

                # "Failed: 0"
                elif line.lower().startswith('failed:'):
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['files_failed'] = int(numbers[0])

                # "Snapshots created/updated: 5"
                elif 'snapshots created' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['snapshots_created'] = int(numbers[0])

                # "Changes detected: 2"
                elif 'changes detected:' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['changes_detected'] = int(numbers[0])

        except Exception as e:
            logger.warning(f"Error parsing capture loader output: {e}")

        return stats


    def get_component_stats(self) -> Dict:
        """Get current component statistics from database"""
        try:
            conn = sqlite3.connect(str(self.assets_db))
            cursor = conn.cursor()

            stats = {}

            # Total components
            cursor.execute("SELECT COUNT(*) FROM components")
            stats['total_components'] = cursor.fetchone()[0]

            # By type
            cursor.execute("""
                SELECT type, COUNT(*) as count
                FROM components
                GROUP BY type
                ORDER BY count DESC
            """)
            stats['by_type'] = dict(cursor.fetchall())

            # Unknown count and percentage
            unknown = stats['by_type'].get('unknown', 0) + stats['by_type'].get(None, 0)
            total = stats['total_components']
            stats['unknown_count'] = unknown
            stats['unknown_pct'] = (unknown / total * 100) if total > 0 else 0

            # Reclassified count
            cursor.execute("""
                SELECT COUNT(*) FROM components 
                WHERE subtype = 'reclassified'
            """)
            stats['reclassified_count'] = cursor.fetchone()[0]

            conn.close()
            return stats

        except Exception as e:
            logger.error(f"Error getting component stats: {e}")
            return {
                'total_components': 0,
                'unknown_count': 0,
                'unknown_pct': 0,
                'reclassified_count': 0,
                'by_type': {}
            }

    def reset_database(self,
                      confirm: bool = False,
                      progress_callback: Optional[Callable] = None) -> Dict:
        """
        Reset database to initial state (DANGEROUS)

        Args:
            confirm: Must be True to proceed
            progress_callback: Function to call with progress updates

        Returns:
            {
                'success': bool,
                'error': str (if failed)
            }
        """
        if not confirm:
            return {
                'success': False,
                'error': 'Database reset requires explicit confirmation'
            }

        if progress_callback:
            progress_callback({
                'stage': 'reset',
                'message': 'Resetting database...',
                'progress': 0
            })

        try:
            reset_script = self.project_root / 'velocitycmdb' / 'reset.py'

            if not reset_script.exists():
                raise FileNotFoundError(f"Reset script not found: {reset_script}")

            result = subprocess.run([sys.executable, str(reset_script), '--confirm'],
                                  capture_output=True, text=True,
                                  cwd=str(self.project_root))

            if result.returncode == 0:
                if progress_callback:
                    progress_callback({
                        'stage': 'reset',
                        'message': 'Database reset complete',
                        'progress': 100
                    })

                return {'success': True}

            logger.error(f"Database reset failed: {result.stderr}")
            return {
                'success': False,
                'error': result.stderr or 'Database reset failed'
            }

        except Exception as e:
            logger.error(f"Database reset error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def generate_topology_from_lldp(self,
                                    root_device: str,
                                    max_hops: int = 4,
                                    domain_suffix: str = 'home.com',
                                    filter_platform: List[str] = None,
                                    filter_device: List[str] = None,
                                    progress_callback: Optional[Callable] = None) -> Dict:
        """Generate network topology from LLDP data starting from root device"""

        def emit_progress(message: str, progress: int = None):
            """Helper to emit progress and log"""
            logger.info(message)
            if progress_callback:
                progress_callback({
                    'stage': 'topology',
                    'message': message,
                    'progress': progress or 50
                })

        emit_progress(f'Generating topology from {root_device}...', 5)

        logger.info(f"generate_topology_from_lldp called with root_device='{root_device}', max_hops={max_hops}")

        # Validate root_device
        if not root_device or not str(root_device).strip():
            return {
                'success': False,
                'error': 'Root device name is required and cannot be empty'
            }

        root_device = str(root_device).strip()
        logger.info(f"Validated root_device: '{root_device}'")

        try:
            # Find topology script
            topo_script = self.project_root / 'pcng' / 'map_from_lldp_v2.py'
            if not topo_script.exists():
                return {
                    'success': False,
                    'error': f"Topology generator not found: {topo_script}"
                }

            # Validate assets database
            if not self.assets_db.exists():
                return {
                    'success': False,
                    'error': f"Assets database not found: {self.assets_db}"
                }

            # Find TextFSM database
            textfsm_db = self.project_root / 'pcng' / 'tfsm_templates.db'
            if not textfsm_db.exists():
                textfsm_db = self.project_root / 'tfsm_templates.db'

            if not textfsm_db.exists():
                return {
                    'success': False,
                    'error': f"TextFSM templates database not found"
                }

            # Create output directory
            maps_dir = self.data_dir / 'maps'
            maps_dir.mkdir(parents=True, exist_ok=True)

            # Generate output filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = maps_dir / f'topology_{root_device}_{timestamp}.json'

            # Emit resolved paths for troubleshooting
            emit_progress(f'Python: {sys.executable}', 8)
            emit_progress(f'Script: {topo_script}', 10)
            emit_progress(f'Assets DB: {self.assets_db}', 12)
            emit_progress(f'TextFSM DB: {textfsm_db}', 14)
            emit_progress(f'Output: {output_file}', 16)
            emit_progress('Building topology map...', 20)

            # Build command - POSITIONAL ARGS MUST COME BEFORE FLAGS
            cmd = [
                sys.executable,
                '-u',  # UNBUFFERED OUTPUT
                str(topo_script),
                str(self.assets_db),  # Positional 1
                root_device,  # Positional 2
                '--tfsm-db', str(textfsm_db),
                '--max-hops', str(max_hops),
                '-o', str(output_file),
                '-d', domain_suffix
            ]

            # Add filters
            if filter_platform:
                cmd.extend(['--fp', ','.join(filter_platform)])

            if filter_device:
                cmd.extend(['--fd', ','.join(filter_device)])

            # LOG THE COMMAND
            logger.info("=" * 70)
            logger.info("EXECUTING TOPOLOGY COMMAND")
            logger.info("=" * 70)
            logger.info(f"root_device = {repr(root_device)}")
            logger.info(f"Command as string:\n  {' '.join(cmd)}")
            logger.info("\nCommand as list:")
            for i, arg in enumerate(cmd):
                logger.info(f"  cmd[{i}] = {repr(arg)}")
            logger.info("=" * 70)

            # Emit full command for troubleshooting
            emit_progress(f'Command: {" ".join(cmd)}', 22)

            # Execute and capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root)
            )

            # Log return code
            logger.info(f"Return code: {result.returncode}")
            logger.info("=" * 70)
            logger.info("SCRIPT OUTPUT:")
            logger.info("=" * 70)

            # Parse and emit important lines to browser
            if result.stdout:
                lines = result.stdout.split('\n')

                # Send selected lines to browser
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Log everything server-side
                    logger.info(line)

                    # Send important lines to browser via progress callback
                    if any(keyword in line for keyword in [
                        'Root Device:',
                        'Max Hops:',
                        'Starting BFS',
                        'Devices processed:',
                        'Parse failures:',
                        'Total LLDP neighbors:',
                        'Connections created:',
                        'Final device count:',
                        'Hop Distribution:',
                        'Vendor Distribution:',
                        'Saved:',
                        'COMPLETE'
                    ]):
                        emit_progress(line, 50)

                    # Also emit hop distribution details
                    if line.startswith('Hop ') or line.startswith('- '):
                        emit_progress(f"  {line}", 60)

            logger.info("=" * 70)

            if result.stderr:
                logger.info("SCRIPT STDERR:")
                logger.info("=" * 70)
                for line in result.stderr.split('\n'):
                    if line.strip():
                        logger.error(line)
                        emit_progress(f"ERROR: {line}", 50)
                logger.info("=" * 70)

            if result.returncode == 0:
                # Parse output for statistics
                stats = self._parse_topology_output(result.stdout)

                emit_progress(f'Generated topology with {stats.get("device_count", 0)} devices', 100)

                return {
                    'success': True,
                    'topology_file': output_file,
                    'filename': output_file.name,
                    'device_count': stats.get('device_count', 0),
                    'connection_count': stats.get('connection_count', 0),
                    'size_kb': round(output_file.stat().st_size / 1024, 2)
                }

            # Handle failure
            error_msg = result.stderr or result.stdout or 'Topology generation failed'
            return {
                'success': False,
                'error': error_msg,
                'return_code': result.returncode
            }

        except Exception as e:
            error_msg = f"Topology generation error: {str(e)}"
            logger.error(error_msg)
            emit_progress(f"ERROR: {error_msg}", 0)
            import traceback
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': error_msg
            }

    def _parse_topology_output(self, output: str) -> Dict:
        """Parse topology generator output for statistics"""
        stats = {
            'device_count': 0,
            'connection_count': 0
        }

        try:
            import re

            # Count devices from "Vendor Distribution" section
            # Format: "  - VendorName: N devices"
            device_total = 0
            in_vendor_section = False

            for line in output.split('\n'):
                # Look for vendor distribution section
                if 'vendor distribution:' in line.lower():
                    in_vendor_section = True
                    continue

                # Parse vendor lines: "  - Cisco: 4 devices"
                if in_vendor_section and line.strip().startswith('- '):
                    match = re.search(r':\s*(\d+)\s+device', line, re.I)
                    if match:
                        device_total += int(match.group(1))

                # Stop at next section
                elif in_vendor_section and line.strip() and not line.strip().startswith('-'):
                    in_vendor_section = False

                # Also look for explicit counts
                if 'final device count:' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['device_count'] = int(numbers[0])

                if 'connections created:' in line.lower():
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        stats['connection_count'] = int(numbers[0])

            # Use the vendor distribution total if we found it
            if device_total > 0:
                stats['device_count'] = device_total

        except Exception as e:
            logger.warning(f"Error parsing topology output: {e}")

        return stats