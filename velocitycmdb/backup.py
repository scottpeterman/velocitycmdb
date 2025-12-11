#!/usr/bin/env python3
"""
VelocityCMDB - Backup Utility
Creates complete backup archives including databases and filesystem artifacts
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Consistent default paths
DEFAULT_DATA_DIR = '~/.velocitycmdb/data'
DEFAULT_BACKUP_DIR = '~/.velocitycmdb/data/backups'


class VelocityCMDBBackup:
    """Complete backup utility for VelocityCMDB"""

    SCHEMA_VERSION = "1.0.0"

    def __init__(self, data_dir: str = None):
        """
        Initialize backup utility

        Args:
            data_dir: Data directory containing databases (defaults to ~/.velocitycmdb/data)
        """
        if data_dir:
            self.data_dir = Path(data_dir).expanduser().resolve()
            self._validate_data_dir(self.data_dir)
        else:
            self.data_dir = Path(DEFAULT_DATA_DIR).expanduser().resolve()

        self.base_dir = self.data_dir.parent  # ~/.velocitycmdb

        # Default backup directory inside data dir
        self.backup_dir = self.data_dir / 'backups'

        # Database files in data directory
        self.db_files = {
            'assets.db': self.data_dir / 'assets.db',
            'arp_cat.db': self.data_dir / 'arp_cat.db',
            'users.db': self.data_dir / 'users.db'
        }

        # Artifact directories
        self.artifact_dirs = {
            'capture': self.data_dir / 'capture',
            'fingerprints': self.data_dir / 'fingerprints',
            'jobs': self.data_dir / 'jobs'
        }

        # Discovery directory (one level up from data)
        discovery_dir = self.base_dir / 'discovery'
        if discovery_dir.exists():
            self.artifact_dirs['discovery_maps'] = discovery_dir / 'maps'

        self.validate_environment()

    def _validate_data_dir(self, data_dir: Path):
        """
        Validate that provided data_dir is not a project/venv folder.
        Prevents accidentally using the installed package location.
        """
        # Check for common project/venv indicators
        invalid_indicators = [
            'site-packages',
            'dist-packages',
            'venv',
            '.venv',
            'lib/python',
            '__pycache__',
            '.egg-info',
        ]

        data_dir_str = str(data_dir).lower()

        for indicator in invalid_indicators:
            if indicator in data_dir_str:
                raise RuntimeError(
                    f"Invalid data directory: {data_dir}\n"
                    f"This appears to be a Python package/venv location.\n"
                    f"Use the default (~/.velocitycmdb/data) or specify a valid data directory."
                )

        # Also check if it looks like a package directory (has __init__.py or setup.py nearby)
        if (data_dir / '__init__.py').exists() or (data_dir / 'setup.py').exists():
            raise RuntimeError(
                f"Invalid data directory: {data_dir}\n"
                f"This appears to be a Python project directory.\n"
                f"Use the default (~/.velocitycmdb/data) or specify a valid data directory."
            )

    def validate_environment(self):
        """Ensure data directory exists"""
        if not self.data_dir.exists():
            raise RuntimeError(
                f"Data directory not found: {self.data_dir}\n"
                f"Run 'python -m velocitycmdb.cli init' to initialize the system."
            )

    def get_table_counts(self, db_path: Path) -> Dict[str, int]:
        """Get record counts for all tables"""
        if not db_path.exists():
            return {}

        counts = {}
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Get all table names
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
            )
            tables = [row[0] for row in cursor.fetchall()]

            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]

            conn.close()
        except Exception as e:
            print(f"  [WARNING] Could not read table counts from {db_path.name}: {e}")

        return counts

    def calculate_file_hash(self, filepath: Path) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def get_directory_stats(self, dirpath: Path) -> Dict:
        """Get statistics about a directory"""
        if not dirpath.exists():
            return {"exists": False, "file_count": 0, "total_size": 0}

        file_count = 0
        total_size = 0

        for root, dirs, files in os.walk(dirpath):
            file_count += len(files)
            total_size += sum(
                os.path.getsize(os.path.join(root, f))
                for f in files
            )

        return {
            "exists": True,
            "file_count": file_count,
            "total_size": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }

    def create_manifest(self, backup_dir: Path, include_captures: bool) -> Dict:
        """Create backup manifest with metadata and checksums"""
        manifest = {
            "backup_metadata": {
                "timestamp": datetime.now().isoformat(),
                "schema_version": self.SCHEMA_VERSION,
                "velocitycmdb_version": "1.0.0",
                "include_captures": include_captures,
                "data_dir": str(self.data_dir)
            },
            "databases": {},
            "artifacts": {},
            "checksums": {}
        }

        # Database info
        for db_name, db_path in self.db_files.items():
            if db_path.exists():
                manifest["databases"][db_name] = {
                    "size_bytes": db_path.stat().st_size,
                    "size_mb": round(db_path.stat().st_size / (1024 * 1024), 2),
                    "tables": self.get_table_counts(db_path)
                }

                # Calculate checksum
                backup_db_path = backup_dir / 'data' / db_name
                if backup_db_path.exists():
                    manifest["checksums"][db_name] = self.calculate_file_hash(backup_db_path)

        # Artifact directory stats
        for artifact_name, artifact_path in self.artifact_dirs.items():
            if not include_captures and artifact_name == "capture":
                manifest["artifacts"][artifact_name] = {"skipped": True}
                continue

            manifest["artifacts"][artifact_name] = self.get_directory_stats(artifact_path)

        return manifest

    def copy_database_safely(self, db_name: str, db_path: Path, dest_dir: Path) -> bool:
        """Copy SQLite database using backup API to handle locks"""
        if not db_path.exists():
            print(f"  [WARNING] Database not found: {db_name}")
            return False

        dest_path = dest_dir / db_name

        try:
            # Use SQLite's backup API for safe copying
            src_conn = sqlite3.connect(str(db_path))
            dest_conn = sqlite3.connect(str(dest_path))

            src_conn.backup(dest_conn)

            src_conn.close()
            dest_conn.close()

            size_mb = dest_path.stat().st_size / (1024 * 1024)
            print(f"  [OK] Backed up {db_name} ({size_mb:.2f} MB)")
            return True

        except Exception as e:
            print(f"  [ERROR] Error backing up {db_name}: {e}")
            return False

    def copy_directory_tree(self, src_path: Path, dest_path: Path,
                            skip_patterns: Optional[List[str]] = None) -> bool:
        """Copy directory tree with optional exclusions"""
        if not src_path.exists():
            print(f"  [WARNING] Directory not found: {src_path.name} (skipping)")
            return True

        try:
            def ignore_patterns(directory, files):
                if skip_patterns:
                    return [f for f in files if any(p in f for p in skip_patterns)]
                return []

            shutil.copytree(src_path, dest_path, ignore=ignore_patterns)

            stats = self.get_directory_stats(dest_path)
            print(f"  [OK] Backed up {src_path.name}/ ({stats['file_count']} files, "
                  f"{stats['total_size_mb']:.2f} MB)")
            return True

        except Exception as e:
            print(f"  [ERROR] Error backing up {src_path.name}/: {e}")
            return False

    def create_backup(self, output_dir: str = None, include_captures: bool = True,
                      include_logs: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Create a complete backup archive

        Args:
            output_dir: Where to save backup (defaults to ~/.velocitycmdb/data/backups)
            include_captures: Include capture files in backup
            include_logs: Include log files in backup
        """

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'velocitycmdb_backup_{timestamp}'

        # Use provided output_dir or default to backup_dir
        if output_dir:
            output_path = Path(output_dir).expanduser().resolve()
        else:
            output_path = self.backup_dir

        output_path.mkdir(parents=True, exist_ok=True)

        archive_path = output_path / f"{backup_name}.tar.gz"

        print(f"\n{'=' * 70}")
        print(f"VelocityCMDB Backup Utility")
        print(f"{'=' * 70}")
        print(f"Data Directory: {self.data_dir}")
        print(f"Output: {archive_path}")
        print(f"Include Captures: {include_captures}")
        print(f"Include Logs: {include_logs}")
        print(f"{'=' * 70}\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / backup_name
            backup_dir.mkdir()

            # Create data subdirectory in backup
            data_backup_dir = backup_dir / 'data'
            data_backup_dir.mkdir()

            print("Stage 1: Backing up databases...")
            db_success = True
            for db_name, db_path in self.db_files.items():
                if not self.copy_database_safely(db_name, db_path, data_backup_dir):
                    if db_name == 'assets.db':  # Critical database
                        db_success = False

            if not db_success:
                print("\n[ERROR] Critical database backup failed")
                return False, None

            print("\nStage 2: Backing up artifact directories...")

            # Backup artifact directories
            for artifact_name, artifact_path in self.artifact_dirs.items():
                if not include_captures and artifact_name == "capture":
                    print(f"  [SKIP] Skipping {artifact_name}/ (--no-captures specified)")
                    continue

                if artifact_path.exists():
                    dest_path = backup_dir / 'data' / artifact_name
                    self.copy_directory_tree(artifact_path, dest_path)

            print("\nStage 3: Generating manifest...")
            manifest = self.create_manifest(backup_dir, include_captures)

            manifest_path = backup_dir / "backup_manifest.json"
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            print(f"  [OK] Created manifest")

            print("\nStage 4: Creating compressed archive...")
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(backup_dir, arcname=backup_name)

            archive_size = archive_path.stat().st_size / (1024 * 1024)
            print(f"  [OK] Archive created ({archive_size:.2f} MB)")

        print(f"\n{'=' * 70}")
        print(f"[SUCCESS] Backup completed successfully")
        print(f"{'=' * 70}")
        print(f"Archive: {archive_path}")
        print(f"Size: {archive_size:.2f} MB")

        # Print summary
        if "databases" in manifest:
            assets_db = manifest["databases"].get("assets.db", {})
            if assets_db:
                tables = assets_db.get("tables", {})
                total_devices = tables.get("devices", 0)
                total_components = tables.get("components", 0)
                print(f"\nBackup Contents:")
                print(f"  Devices: {total_devices}")
                print(f"  Components: {total_components}")

            if "artifacts" in manifest and "capture" in manifest["artifacts"]:
                captures = manifest["artifacts"]["capture"]
                if captures.get("exists"):
                    print(f"  Capture Files: {captures['file_count']} "
                          f"({captures['total_size_mb']:.2f} MB)")

        print(f"{'=' * 70}\n")

        return True, str(archive_path)


def main():
    parser = argparse.ArgumentParser(
        description="VelocityCMDB - Backup Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full backup with everything (saves to ~/.velocitycmdb/data/backups/)
  python backup.py

  # Metadata-only backup (excludes large capture files)
  python backup.py --no-captures

  # Backup to specific output directory
  python backup.py --output ~/my-backups

  # Backup from specific data directory
  python backup.py --data-dir /path/to/data --output ~/my-backups
        """
    )

    parser.add_argument(
        '--data-dir',
        default=None,
        help='VelocityCMDB data directory (default: ~/.velocitycmdb/data)'
    )

    parser.add_argument(
        '--output',
        default=None,
        help='Output directory for backup archive (default: ~/.velocitycmdb/data/backups)'
    )

    parser.add_argument(
        '--no-captures',
        action='store_true',
        help='Exclude capture files (creates smaller metadata-only backup)'
    )

    parser.add_argument(
        '--include-logs',
        action='store_true',
        help='Include log files in backup'
    )

    args = parser.parse_args()

    try:
        backup = VelocityCMDBBackup(args.data_dir)
        success, archive_path = backup.create_backup(
            args.output,
            include_captures=not args.no_captures,
            include_logs=args.include_logs
        )

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"\n[ERROR] Backup failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()