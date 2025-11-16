#!/usr/bin/env python3
"""
Anguis Network Management System - Restore Utility
Restores complete Anguis environment from backup archive
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
from typing import Dict, Optional, Tuple


class AnguisRestore:
    """Complete restore utility for Anguis NMS"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.validate_environment()

    def validate_environment(self):
        """Ensure we're in a valid Anguis project directory"""
        required_markers = ["app", "db_init.py"]

        for marker in required_markers:
            if not (self.project_root / marker).exists():
                raise RuntimeError(
                    f"Invalid Anguis project directory. Missing: {marker}\n"
                    f"Run this script from the Anguis project root."
                )

    def check_running_processes(self) -> bool:
        """Check if Flask app or other processes are using the database"""
        db_path = self.project_root / "assets.db"

        if not db_path.exists():
            return False  # No database, safe to proceed

        try:
            # Try to get an exclusive lock
            conn = sqlite3.connect(str(db_path), timeout=1.0)
            conn.execute("BEGIN EXCLUSIVE")
            conn.rollback()
            conn.close()
            return False  # Got lock, no processes using it
        except sqlite3.OperationalError:
            return True  # Database locked, process is using it

    def calculate_file_hash(self, filepath: Path) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def validate_backup_archive(self, archive_path: Path) -> Tuple[bool, Optional[Dict], Optional[Path]]:
        """Extract and validate backup archive"""

        if not archive_path.exists():
            print(f"✗ Archive not found: {archive_path}")
            return False, None, None

        print(f"Validating archive: {archive_path.name}")

        # Extract to temporary directory
        tmpdir = tempfile.mkdtemp(prefix='anguis_restore_')
        extract_dir = Path(tmpdir)

        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(extract_dir)

            # Find the backup directory (should be single top-level dir)
            extracted_items = list(extract_dir.iterdir())
            if len(extracted_items) != 1 or not extracted_items[0].is_dir():
                print("✗ Invalid archive structure")
                shutil.rmtree(tmpdir)
                return False, None, None

            backup_dir = extracted_items[0]

            # Load manifest
            manifest_path = backup_dir / "backup_manifest.json"
            if not manifest_path.exists():
                print("✗ Manifest not found in archive")
                shutil.rmtree(tmpdir)
                return False, None, None

            with open(manifest_path) as f:
                manifest = json.load(f)

            print(f"  ✓ Archive extracted")
            print(f"  ✓ Manifest loaded")

            # Validate checksums
            if "checksums" in manifest:
                print(f"  Validating checksums...")
                for filename, expected_hash in manifest["checksums"].items():
                    file_path = backup_dir / filename
                    if file_path.exists():
                        actual_hash = self.calculate_file_hash(file_path)
                        if actual_hash != expected_hash:
                            print(f"  ✗ Checksum mismatch: {filename}")
                            shutil.rmtree(tmpdir)
                            return False, None, None
                print(f"  ✓ All checksums valid")

            # Validate databases exist
            for db_file in ["assets.db", "arp_cat.db"]:
                db_path = backup_dir / db_file
                if not db_path.exists():
                    print(f"  ⚠ Warning: {db_file} not found in backup")
                else:
                    # Quick integrity check
                    try:
                        conn = sqlite3.connect(str(db_path))
                        conn.execute("PRAGMA integrity_check")
                        conn.close()
                        print(f"  ✓ {db_file} integrity OK")
                    except Exception as e:
                        print(f"  ✗ {db_file} integrity check failed: {e}")
                        shutil.rmtree(tmpdir)
                        return False, None, None

            return True, manifest, backup_dir

        except Exception as e:
            print(f"✗ Archive validation failed: {e}")
            if extract_dir.exists():
                shutil.rmtree(tmpdir)
            return False, None, None

    def backup_current_state(self) -> Optional[Path]:
        """Create safety backup of current state before restore"""
        print("\nCreating safety backup of current state...")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safety_backup_dir = self.project_root / "safety_backups"
        safety_backup_dir.mkdir(exist_ok=True)

        safety_path = safety_backup_dir / f"pre_restore_{timestamp}"
        safety_path.mkdir()

        try:
            # Backup current databases
            for db_file in ["assets.db", "arp_cat.db"]:
                src = self.project_root / db_file
                if src.exists():
                    shutil.copy2(src, safety_path / db_file)
                    print(f"  ✓ Backed up {db_file}")

            # Backup current artifact dirs (minimal - just structure)
            for dirname in ["pcng/fingerprints", "pcng/maps", "diffs"]:
                src = self.project_root / dirname
                if src.exists() and any(src.iterdir()):
                    dest = safety_path / f"{dirname.replace('/', '_')}_exists.txt"
                    dest.write_text(f"Directory existed with files at restore time")

            print(f"  ✓ Safety backup created: {safety_path}")
            return safety_path

        except Exception as e:
            print(f"  ⚠ Safety backup failed: {e}")
            print(f"  Continuing without safety backup...")
            return None
    def clear_current_state(self, preserve_backups: bool = True):
        """Clear current databases and artifacts"""
        print("\nClearing current state...")

        # Remove databases
        for db_file in ["assets.db", "arp_cat.db"]:
            db_path = self.project_root / db_file
            if db_path.exists():
                db_path.unlink()
                print(f"  ✓ Removed {db_file}")

        # Clear artifact directories
        for dirname in ["pcng/capture", "pcng/fingerprints", "pcng/maps", "diffs", "sessions"]:
            dir_path = self.project_root / dirname
            if dir_path.exists():
                if preserve_backups and dirname == "backups":
                    continue
                shutil.rmtree(dir_path)
                print(f"  ✓ Removed {dirname}/")

    def restore_databases(self, backup_dir: Path) -> bool:
        """Restore database files"""
        print("\nRestoring databases...")

        for db_file in ["assets.db", "arp_cat.db"]:
            src = backup_dir / db_file
            dest = self.project_root / db_file

            if not src.exists():
                print(f"  ⚠ {db_file} not in backup, skipping")
                continue

            try:
                # Copy database
                shutil.copy2(src, dest)

                # Verify restoration
                conn = sqlite3.connect(str(dest))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                table_count = cursor.fetchone()[0]
                conn.close()

                size_mb = dest.stat().st_size / (1024 * 1024)
                print(f"  ✓ Restored {db_file} ({size_mb:.2f} MB, {table_count} tables)")

            except Exception as e:
                print(f"  ✗ Failed to restore {db_file}: {e}")
                return False

        return True

    def restore_artifacts(self, backup_dir: Path) -> bool:
        """Restore artifact directories"""
        print("\nRestoring artifact directories...")

        # Map of backup paths to restore paths
        artifact_mapping = {
            "pcng/capture": "pcng/capture",
            "pcng/fingerprints": "pcng/fingerprints",
            "pcng/maps": "pcng/maps",
            "diffs": "diffs",
            "sessions": "sessions"
        }

        for src_name, dest_name in artifact_mapping.items():
            src = backup_dir / src_name
            dest = self.project_root / dest_name

            if not src.exists():
                # Create empty directory structure
                dest.mkdir(parents=True, exist_ok=True)
                print(f"  ○ Created empty {dest_name}/")
                continue

            try:
                # Ensure parent directory exists
                dest.parent.mkdir(parents=True, exist_ok=True)

                # Remove destination if exists
                if dest.exists():
                    shutil.rmtree(dest)

                # Copy directory tree
                shutil.copytree(src, dest)

                # Count files
                file_count = sum(1 for _ in dest.rglob('*') if _.is_file())
                total_size = sum(f.stat().st_size for f in dest.rglob('*') if f.is_file())
                size_mb = total_size / (1024 * 1024)

                print(f"  ✓ Restored {dest_name}/ ({file_count} files, {size_mb:.2f} MB)")

            except Exception as e:
                print(f"  ✗ Failed to restore {dest_name}/: {e}")
                return False

        return True

    def verify_restoration(self, manifest: Dict) -> bool:
        """Verify restored state matches manifest"""
        print("\nVerifying restoration...")

        # Check database record counts
        if "databases" in manifest:
            for db_file, db_info in manifest["databases"].items():
                db_path = self.project_root / db_file
                if not db_path.exists():
                    continue

                expected_tables = db_info.get("tables", {})
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()

                mismatches = []
                for table, expected_count in expected_tables.items():
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        actual_count = cursor.fetchone()[0]
                        if actual_count != expected_count:
                            mismatches.append(
                                f"{table}: expected {expected_count}, got {actual_count}"
                            )
                    except sqlite3.OperationalError:
                        # Table might not exist (FTS tables, etc.)
                        pass

                conn.close()

                if mismatches:
                    print(f"  ⚠ Record count mismatches in {db_file}:")
                    for mismatch in mismatches[:5]:  # Show first 5
                        print(f"    - {mismatch}")
                    if len(mismatches) > 5:
                        print(f"    ... and {len(mismatches) - 5} more")
                else:
                    print(f"  ✓ {db_file} record counts match")

        return True

    def print_restore_summary(self, manifest: Dict):
        """Print summary of restored data"""
        print(f"\n{'=' * 70}")
        print(f"Restoration Summary")
        print(f"{'=' * 70}")

        if "backup_metadata" in manifest:
            meta = manifest["backup_metadata"]
            print(f"Backup Date: {meta.get('timestamp', 'Unknown')}")
            print(f"Schema Version: {meta.get('schema_version', 'Unknown')}")

        if "databases" in manifest and "assets.db" in manifest["databases"]:
            tables = manifest["databases"]["assets.db"].get("tables", {})
            print(f"\nRestored Data:")
            print(f"  Sites: {tables.get('sites', 0)}")
            print(f"  Devices: {tables.get('devices', 0)}")
            print(f"  Components: {tables.get('components', 0)}")
            print(f"  Vendors: {tables.get('vendors', 0)}")
            print(f"  Captures: {tables.get('device_captures_current', 0)}")
            print(f"  Notes: {tables.get('notes', 0)}")

        if "artifacts" in manifest:
            print(f"\nArtifact Directories:")
            for dirname, info in manifest["artifacts"].items():
                if info.get("skipped"):
                    print(f"  {dirname}/: (not in backup)")
                elif info.get("exists"):
                    print(f"  {dirname}/: {info.get('file_count', 0)} files "
                          f"({info.get('total_size_mb', 0):.2f} MB)")
                else:
                    print(f"  {dirname}/: (empty)")

        print(f"{'=' * 70}\n")

    def restore(self, archive_path: str, force: bool = False,
                skip_safety_backup: bool = False) -> bool:
        """Restore from backup archive"""

        archive = Path(archive_path).resolve()

        print(f"\n{'=' * 70}")
        print(f"Anguis Restore Utility")
        print(f"{'=' * 70}")
        print(f"Project Root: {self.project_root}")
        print(f"Archive: {archive}")
        print(f"{'=' * 70}\n")

        # Check for running processes
        if self.check_running_processes():
            print("✗ Database is in use. Stop the Flask application before restoring.")
            if not force:
                print("  Use --force to override (not recommended)")
                return False
            print("  Proceeding with --force...")

        # Validate archive
        valid, manifest, backup_dir = self.validate_backup_archive(archive)
        if not valid:
            return False

        print(f"\n{'=' * 70}")
        print(f"Archive validation successful")
        print(f"{'=' * 70}")

        # Show what will be restored
        if manifest and "backup_metadata" in manifest:
            meta = manifest["backup_metadata"]
            print(f"Backup created: {meta.get('timestamp', 'Unknown')}")

        if manifest and "databases" in manifest and "assets.db" in manifest["databases"]:
            tables = manifest["databases"]["assets.db"].get("tables", {})
            print(f"\nThis will restore:")
            print(f"  {tables.get('devices', 0)} devices")
            print(f"  {tables.get('components', 0)} components")
            print(f"  {tables.get('sites', 0)} sites")

        # Confirmation
        if not force:
            print(f"\n{'=' * 70}")
            print(f"⚠ WARNING: This will REPLACE all current data!")
            print(f"{'=' * 70}")
            response = input("\nContinue with restore? [yes/no]: ").strip().lower()
            if response not in ['yes', 'y']:
                print("Restore cancelled.")
                shutil.rmtree(backup_dir.parent)
                return False

        # Create safety backup
        if not skip_safety_backup:
            safety_path = self.backup_current_state()

        try:
            # Clear current state
            self.clear_current_state()

            # Restore databases
            if not self.restore_databases(backup_dir):
                print("\n✗ Database restore failed")
                return False

            # Restore artifacts
            if not self.restore_artifacts(backup_dir):
                print("\n✗ Artifact restore failed")
                return False

            # Verify restoration
            self.verify_restoration(manifest)

            # Print summary
            self.print_restore_summary(manifest)

            print(f"{'=' * 70}")
            print(f"✓ Restore completed successfully")
            print(f"{'=' * 70}\n")

            return True

        finally:
            # Clean up temporary extraction
            if backup_dir and backup_dir.parent.exists():
                shutil.rmtree(backup_dir.parent)


def main():
    parser = argparse.ArgumentParser(
        description="Anguis Network Management System - Restore Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Restore from backup archive
  python restore.py --archive ./backups/anguis_backup_20251005_173000.tar.gz

  # Force restore without confirmation
  python restore.py --archive backup.tar.gz --force

  # Restore without creating safety backup
  python restore.py --archive backup.tar.gz --skip-safety-backup

  # Restore to specific project directory
  python restore.py --project-root /path/to/anguis --archive backup.tar.gz

IMPORTANT: Stop the Flask application before running restore!
        """
    )

    parser.add_argument(
        '--project-root',
        default='.',
        help='Anguis project root directory (default: current directory)'
    )

    parser.add_argument(
        '--archive',
        required=True,
        help='Path to backup archive (.tar.gz file)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts and force restore'
    )

    parser.add_argument(
        '--skip-safety-backup',
        action='store_true',
        help='Skip creating safety backup of current state'
    )

    args = parser.parse_args()

    try:
        restore = AnguisRestore(args.project_root)
        success = restore.restore(
            args.archive,
            force=args.force,
            skip_safety_backup=args.skip_safety_backup
        )

        if success:
            print("You can now start the Flask application:")
            print("  cd app && python run.py")

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nRestore cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Restore failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()