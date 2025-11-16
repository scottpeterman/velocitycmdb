#!/usr/bin/env python3
"""
Anguis Network Management System - Reset Utility
Resets environment to fresh installation state
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path
from datetime import datetime


class AnguisReset:
    """Reset Anguis environment to clean state"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        print(f"DEBUG: Resolved project root to: {self.project_root}")
        self.validate_environment()

    def validate_environment(self):
        """Ensure we're in a valid Anguis project directory"""
        required_markers = ["app", "db_init.py"]

        for marker in required_markers:
            marker_path = self.project_root / marker
            print(f"DEBUG: Checking for {marker} at {marker_path}: {marker_path.exists()}")
            if not marker_path.exists():
                raise RuntimeError(
                    f"Invalid Anguis project directory. Missing: {marker}\n"
                    f"Run this script from the Anguis project root."
                )

    def check_running_processes(self) -> bool:
        """Check if Flask app is running"""
        db_path = self.project_root / "assets.db"

        if not db_path.exists():
            print("DEBUG: No database found, safe to proceed")
            return False

        try:
            conn = sqlite3.connect(str(db_path), timeout=1.0)
            conn.execute("BEGIN EXCLUSIVE")
            conn.rollback()
            conn.close()
            print("DEBUG: Database not locked")
            return False
        except sqlite3.OperationalError:
            print("DEBUG: Database is locked")
            return True

    def create_safety_backup(self) -> bool:
        """Create a safety backup before reset"""
        print("\nCreating safety backup...")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safety_dir = self.project_root / "safety_backups"
        safety_dir.mkdir(exist_ok=True)

        backup_path = safety_dir / f"pre_reset_{timestamp}"
        backup_path.mkdir()

        try:
            # Backup databases
            for db_file in ["assets.db", "arp_cat.db"]:
                src = self.project_root / db_file
                if src.exists():
                    shutil.copy2(src, backup_path / db_file)
                    print(f"  Backed up {db_file}")

            # Create marker file with reset info
            info_file = backup_path / "reset_info.txt"
            info_file.write_text(
                f"Pre-reset backup created: {timestamp}\n"
                f"Reset performed by: reset.py\n"
            )

            print(f"  Safety backup: {backup_path}")
            return True

        except Exception as e:
            print(f"  WARNING: Safety backup failed: {e}")
            return False

    def remove_databases(self):
        """Remove database files"""
        print("\nRemoving databases...")

        for db_file in ["assets.db", "arp_cat.db"]:
            db_path = self.project_root / db_file
            print(f"DEBUG: Checking {db_path}, exists={db_path.exists()}")

            if db_path.exists():
                try:
                    db_path.unlink()
                    print(f"  Removed {db_file}")

                    # Verify removal
                    if db_path.exists():
                        print(f"  ERROR: {db_file} still exists after unlink!")
                    else:
                        print(f"  Verified {db_file} is gone")

                except Exception as e:
                    print(f"  ERROR: Failed to remove {db_file}: {e}")
            else:
                print(f"  {db_file} not found")

    def clear_artifacts(self, preserve_maps: bool = False):
        """Clear artifact directories"""
        print("\nClearing artifact directories...")

        # Define all directories to potentially clear
        dirs_to_process = [
            ("pcng/capture", True),
            ("pcng/fingerprints", True),
            ("pcng/maps", not preserve_maps),
            ("diffs", True),
            ("sessions", True)
        ]

        for dirname, should_clear in dirs_to_process:
            dir_path = self.project_root / dirname
            print(f"DEBUG: Processing {dirname} at {dir_path}")
            print(f"DEBUG:   exists={dir_path.exists()}, should_clear={should_clear}")

            if not should_clear:
                print(f"  Skipped {dirname}/ (preserved)")
                continue

            if dir_path.exists():
                try:
                    # Count files before removal
                    file_count = sum(1 for _ in dir_path.rglob('*') if _.is_file())
                    print(f"DEBUG:   Found {file_count} files in {dirname}")

                    # Remove directory
                    shutil.rmtree(dir_path)
                    print(f"  Removed {dirname}/ ({file_count} files)")

                    # Verify removal
                    if dir_path.exists():
                        print(f"  ERROR: {dirname} still exists after rmtree!")
                    else:
                        print(f"  Verified {dirname} is gone")

                except Exception as e:
                    print(f"  ERROR: Failed to remove {dirname}: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"  {dirname}/ did not exist")

            # Recreate empty directory
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"  Created empty {dirname}/")
            except Exception as e:
                print(f"  ERROR: Failed to create {dirname}: {e}")

    def reinitialize_databases(self):
        """Run db_init.py to create fresh database schema"""
        print("\nReinitializing databases...")

        db_init_script = self.project_root / "db_init.py"
        arp_init_script = self.project_root / "arp_cat_init_schema.py"

        if not db_init_script.exists():
            print("  ERROR: db_init.py not found")
            return False

        try:
            # Run db_init.py
            import subprocess
            result = subprocess.run(
                [sys.executable, str(db_init_script)],
                cwd=str(self.project_root),
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                print(f"  Initialized assets.db")
            else:
                print(f"  ERROR: assets.db initialization failed:")
                print(f"    {result.stderr}")
                return False

            # Run arp_cat_init_schema.py if it exists
            if arp_init_script.exists():
                result = subprocess.run(
                    [sys.executable, str(arp_init_script)],
                    cwd=str(self.project_root),
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    print(f"  Initialized arp_cat.db")
                else:
                    print(f"  WARNING: arp_cat.db initialization warning:")
                    print(f"    {result.stderr}")

            return True

        except Exception as e:
            print(f"  ERROR: Database initialization failed: {e}")
            return False

    def verify_reset(self):
        """Verify that reset was successful"""
        print("\nVerifying reset...")

        # Check databases exist and are empty
        for db_file in ["assets.db", "arp_cat.db"]:
            db_path = self.project_root / "assets.db"
            if not db_path.exists():
                print(f"  WARNING: {db_file} not found")
                continue

            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()

                # Check main tables are empty
                test_tables = ["devices", "sites", "vendors"]
                for table in test_tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        if count > 0:
                            print(f"  ERROR: {db_file}:{table} has {count} records (should be 0)")
                        else:
                            print(f"  {db_file}:{table} is empty")
                    except sqlite3.OperationalError:
                        pass  # Table doesn't exist

                conn.close()

            except Exception as e:
                print(f"  ERROR: {db_file} verification failed: {e}")

        # Check directories exist and are empty
        for dirname in ["pcng/capture", "pcng/fingerprints", "pcng/maps", "diffs"]:
            dir_path = self.project_root / dirname
            if dir_path.exists():
                file_count = sum(1 for _ in dir_path.rglob('*') if _.is_file())
                if file_count == 0:
                    print(f"  {dirname}/ is empty")
                else:
                    print(f"  ERROR: {dirname}/ contains {file_count} files (should be 0)")
            else:
                print(f"  WARNING: {dirname}/ not found")

    def reset(self, preserve_maps: bool = False, skip_reinit: bool = False,
              skip_safety_backup: bool = False, force: bool = False) -> bool:
        """Perform complete environment reset"""

        print(f"\n{'=' * 70}")
        print(f"Anguis Environment Reset Utility")
        print(f"{'=' * 70}")
        print(f"Project Root: {self.project_root}")
        print(f"{'=' * 70}\n")

        # Check for running processes
        if self.check_running_processes():
            print("ERROR: Database is in use. Stop the Flask application before resetting.")
            if not force:
                print("  Use --force to override (not recommended)")
                return False
            print("  Proceeding with --force...")

        # Warning and confirmation
        print("WARNING: This will DELETE all data and reset to empty state!")
        print("\nThis will:")
        print("  - Remove all databases (assets.db, arp_cat.db)")
        print("  - Clear all capture files")
        print("  - Clear all fingerprint data")
        print("  - Clear all diff history")
        if not preserve_maps:
            print("  - Clear all network maps")

        if not force:
            print(f"\n{'=' * 70}")
            response = input("\nType 'RESET' to confirm: ").strip()
            if response != 'RESET':
                print("Reset cancelled.")
                return False

        # Create safety backup
        if not skip_safety_backup:
            self.create_safety_backup()

        try:
            # Remove databases
            print("\n" + "=" * 70)
            print("STEP 1: Removing databases")
            print("=" * 70)
            self.remove_databases()

            # Clear artifacts
            print("\n" + "=" * 70)
            print("STEP 2: Clearing artifacts")
            print("=" * 70)
            self.clear_artifacts(preserve_maps=preserve_maps)

            # Reinitialize databases
            if not skip_reinit:
                print("\n" + "=" * 70)
                print("STEP 3: Reinitializing databases")
                print("=" * 70)
                if not self.reinitialize_databases():
                    print("\nWARNING: Database reinitialization failed")
                    print("  You may need to run db_init.py manually")
            else:
                print("\nSkipped database reinitialization (--skip-reinit)")

            # Verify reset
            print("\n" + "=" * 70)
            print("STEP 4: Verification")
            print("=" * 70)
            self.verify_reset()

            print(f"\n{'=' * 70}")
            print(f"Environment reset completed")
            print(f"{'=' * 70}")
            print("\nYou now have a fresh Anguis environment.")
            print("Next steps:")
            print("  1. Run discovery: cd pcng && python sc_run3.py --username ... --password ...")
            print("  2. Generate maps: cd pcng && python sc_enhance_all_maps.py")
            print("  3. Fingerprint devices: cd pcng && python batch_spn_concurrent.py sessions.yaml")
            print("  4. Start web app: cd app && python run.py")
            print(f"{'=' * 70}\n")

            return True

        except Exception as e:
            print(f"\nERROR: Reset failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Anguis Network Management System - Environment Reset Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full reset with confirmation
  python reset.py

  # Force reset without confirmation (dangerous!)
  python reset.py --force

  # Reset but preserve network maps
  python reset.py --preserve-maps

  # Reset without reinitializing databases
  python reset.py --skip-reinit

  # Reset from specific project directory
  python reset.py --project-root /path/to/anguis

WARNING: This will delete all data! Make sure you have backups.
        """
    )

    parser.add_argument(
        '--project-root',
        default='.',
        help='Anguis project root directory (default: current directory)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts (DANGEROUS!)'
    )

    parser.add_argument(
        '--preserve-maps',
        action='store_true',
        help='Keep existing network maps during reset'
    )

    parser.add_argument(
        '--skip-reinit',
        action='store_true',
        help='Skip database reinitialization (you will need to run db_init.py manually)'
    )

    parser.add_argument(
        '--skip-safety-backup',
        action='store_true',
        help='Skip creating safety backup before reset'
    )

    args = parser.parse_args()

    try:
        reset = AnguisReset(args.project_root)
        success = reset.reset(
            preserve_maps=args.preserve_maps,
            skip_reinit=args.skip_reinit,
            skip_safety_backup=args.skip_safety_backup,
            force=args.force
        )

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nReset cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: Reset failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()