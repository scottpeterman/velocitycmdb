#!/usr/bin/env python3
"""
AngusNMS Assets Database Recovery Script
Performs integrity checks, backup, and recovery of corrupted SQLite database
"""

import sqlite3
import subprocess
import shutil
import sys
from pathlib import Path
from datetime import datetime
import hashlib
import json


class DatabaseRecovery:
    def __init__(self, db_path="assets.db"):
        self.db_path = Path(db_path)
        self.backup_dir = Path("db_backups")
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.recovery_log = []

    def log(self, message, level="INFO"):
        """Log messages with timestamp"""
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {level} - {message}"
        print(log_entry)
        self.recovery_log.append(log_entry)

    def check_file_exists(self):
        """Verify database file exists"""
        if not self.db_path.exists():
            self.log(f"Database file not found: {self.db_path}", "ERROR")
            return False
        self.log(f"Database file found: {self.db_path} ({self.db_path.stat().st_size} bytes)")
        return True

    def calculate_checksum(self, file_path):
        """Calculate MD5 checksum of file"""
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()

    def run_integrity_check(self, db_path=None):
        """Run SQLite integrity check"""
        if db_path is None:
            db_path = self.db_path

        self.log(f"Running integrity check on {db_path}...")
        results = {
            "integrity_check": None,
            "foreign_key_check": None,
            "quick_check": None,
            "table_counts": {},
            "errors": []
        }

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # PRAGMA integrity_check
            try:
                cursor.execute("PRAGMA integrity_check;")
                integrity_result = cursor.fetchall()
                results["integrity_check"] = integrity_result
                if integrity_result == [('ok',)]:
                    self.log("✓ Integrity check: PASSED", "SUCCESS")
                else:
                    self.log(f"✗ Integrity check: FAILED - {integrity_result}", "ERROR")
                    results["errors"].extend([str(r) for r in integrity_result])
            except Exception as e:
                self.log(f"✗ Integrity check failed: {e}", "ERROR")
                results["errors"].append(f"Integrity check error: {str(e)}")

            # PRAGMA quick_check
            try:
                cursor.execute("PRAGMA quick_check;")
                quick_result = cursor.fetchall()
                results["quick_check"] = quick_result
                if quick_result == [('ok',)]:
                    self.log("✓ Quick check: PASSED", "SUCCESS")
                else:
                    self.log(f"✗ Quick check: FAILED - {quick_result}", "WARNING")
            except Exception as e:
                self.log(f"✗ Quick check failed: {e}", "ERROR")
                results["errors"].append(f"Quick check error: {str(e)}")

            # PRAGMA foreign_key_check
            try:
                cursor.execute("PRAGMA foreign_key_check;")
                fk_result = cursor.fetchall()
                results["foreign_key_check"] = fk_result
                if not fk_result:
                    self.log("✓ Foreign key check: PASSED", "SUCCESS")
                else:
                    self.log(f"✗ Foreign key check: {len(fk_result)} violations found", "WARNING")
            except Exception as e:
                self.log(f"✗ Foreign key check failed: {e}", "ERROR")

            # Count rows in major tables
            important_tables = [
                'devices', 'sites', 'vendors', 'device_types', 'device_roles',
                'device_captures_current', 'capture_snapshots', 'components',
                'notes', 'fingerprint_extractions'
            ]

            for table in important_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table};")
                    count = cursor.fetchone()[0]
                    results["table_counts"][table] = count
                    self.log(f"  {table}: {count} rows")
                except Exception as e:
                    self.log(f"  {table}: ERROR - {e}", "WARNING")
                    results["table_counts"][table] = f"ERROR: {str(e)}"

            conn.close()

        except sqlite3.DatabaseError as e:
            self.log(f"Database error during integrity check: {e}", "ERROR")
            results["errors"].append(f"Database error: {str(e)}")
            return results
        except Exception as e:
            self.log(f"Unexpected error during integrity check: {e}", "ERROR")
            results["errors"].append(f"Unexpected error: {str(e)}")
            return results

        return results

    def create_backup(self):
        """Create backup of corrupted database"""
        self.backup_dir.mkdir(exist_ok=True)
        backup_path = self.backup_dir / f"assets_corrupted_{self.timestamp}.db"

        self.log(f"Creating backup: {backup_path}")
        try:
            shutil.copy2(self.db_path, backup_path)
            checksum = self.calculate_checksum(backup_path)
            self.log(f"✓ Backup created successfully (MD5: {checksum})", "SUCCESS")
            return backup_path
        except Exception as e:
            self.log(f"✗ Failed to create backup: {e}", "ERROR")
            return None

    def recover_via_dump(self):
        """Attempt recovery using SQLite dump and restore"""
        self.log("Attempting recovery via dump/restore method...")
        recovered_path = Path(f"assets_recovered_{self.timestamp}.db")

        try:
            # Dump database to SQL
            self.log("Dumping database to SQL...")
            dump_cmd = ["sqlite3", str(self.db_path), ".dump"]
            dump_result = subprocess.run(
                dump_cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if dump_result.returncode != 0:
                self.log(f"✗ Dump failed: {dump_result.stderr}", "ERROR")
                return None

            sql_dump = dump_result.stdout
            self.log(f"✓ Database dumped ({len(sql_dump)} bytes of SQL)")

            # Create new database from dump
            self.log("Creating recovered database from dump...")
            restore_cmd = ["sqlite3", str(recovered_path)]
            restore_result = subprocess.run(
                restore_cmd,
                input=sql_dump,
                capture_output=True,
                text=True,
                timeout=300
            )

            if restore_result.returncode != 0:
                self.log(f"✗ Restore failed: {restore_result.stderr}", "ERROR")
                return None

            self.log(f"✓ Database restored to {recovered_path}", "SUCCESS")
            return recovered_path

        except subprocess.TimeoutExpired:
            self.log("✗ Recovery timed out", "ERROR")
            return None
        except Exception as e:
            self.log(f"✗ Recovery failed: {e}", "ERROR")
            return None

    def recover_via_python(self):
        """Attempt recovery using Python sqlite3 iterdump"""
        self.log("Attempting recovery via Python iterdump method...")
        recovered_path = Path(f"assets_recovered_python_{self.timestamp}.db")

        try:
            # Connect to corrupted database
            self.log("Opening corrupted database...")
            old_conn = sqlite3.connect(str(self.db_path))

            # Create new database
            self.log("Creating new database...")
            new_conn = sqlite3.connect(str(recovered_path))

            # Dump and restore
            self.log("Dumping and restoring data...")
            for line in old_conn.iterdump():
                if line not in ('BEGIN;', 'COMMIT;'):
                    try:
                        new_conn.execute(line)
                    except sqlite3.Error as e:
                        self.log(f"Warning: Skipped line due to error: {e}", "WARNING")

            new_conn.commit()
            new_conn.close()
            old_conn.close()

            self.log(f"✓ Database recovered to {recovered_path}", "SUCCESS")
            return recovered_path

        except Exception as e:
            self.log(f"✗ Python recovery failed: {e}", "ERROR")
            return None

    def optimize_database(self, db_path):
        """Optimize recovered database"""
        self.log(f"Optimizing database: {db_path}...")
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Vacuum
            self.log("Running VACUUM...")
            cursor.execute("VACUUM;")

            # Analyze
            self.log("Running ANALYZE...")
            cursor.execute("ANALYZE;")

            # Reindex
            self.log("Running REINDEX...")
            cursor.execute("REINDEX;")

            conn.commit()
            conn.close()

            self.log("✓ Database optimized", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"✗ Optimization failed: {e}", "ERROR")
            return False

    def compare_databases(self, original_check, recovered_check):
        """Compare table counts between original and recovered"""
        self.log("\n" + "=" * 80)
        self.log("DATABASE COMPARISON")
        self.log("=" * 80)

        orig_counts = original_check.get("table_counts", {})
        rec_counts = recovered_check.get("table_counts", {})

        all_tables = set(list(orig_counts.keys()) + list(rec_counts.keys()))

        differences = []
        for table in sorted(all_tables):
            orig_count = orig_counts.get(table, "N/A")
            rec_count = rec_counts.get(table, "N/A")

            status = "✓" if orig_count == rec_count else "✗"
            self.log(f"{status} {table:30} Original: {str(orig_count):10} | Recovered: {str(rec_count):10}")

            if orig_count != rec_count:
                differences.append({
                    "table": table,
                    "original": orig_count,
                    "recovered": rec_count
                })

        if differences:
            self.log(f"\n⚠ {len(differences)} table(s) have different row counts", "WARNING")
        else:
            self.log("\n✓ All table counts match!", "SUCCESS")

        return differences

    def save_recovery_report(self, original_check, recovered_check, differences):
        """Save detailed recovery report"""
        report_path = self.backup_dir / f"recovery_report_{self.timestamp}.json"

        report = {
            "timestamp": self.timestamp,
            "original_database": str(self.db_path),
            "original_checks": original_check,
            "recovered_checks": recovered_check,
            "differences": differences,
            "recovery_log": self.recovery_log
        }

        try:
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            self.log(f"✓ Recovery report saved: {report_path}", "SUCCESS")
        except Exception as e:
            self.log(f"✗ Failed to save report: {e}", "ERROR")

    def run_recovery(self):
        """Main recovery workflow"""
        self.log("=" * 80)
        self.log("ANGUS NMS DATABASE RECOVERY")
        self.log("=" * 80)
        self.log(f"Target database: {self.db_path}")
        self.log(f"Timestamp: {self.timestamp}\n")

        # Step 1: Check file exists
        if not self.check_file_exists():
            return False

        # Step 2: Pre-recovery integrity check
        self.log("\n" + "=" * 80)
        self.log("PRE-RECOVERY INTEGRITY CHECK")
        self.log("=" * 80)
        original_check = self.run_integrity_check()

        # Step 3: Create backup
        self.log("\n" + "=" * 80)
        self.log("CREATING BACKUP")
        self.log("=" * 80)
        backup_path = self.create_backup()
        if not backup_path:
            self.log("Cannot proceed without backup", "ERROR")
            return False

        # Step 4: Attempt recovery
        self.log("\n" + "=" * 80)
        self.log("ATTEMPTING RECOVERY")
        self.log("=" * 80)

        recovered_path = self.recover_via_dump()
        if not recovered_path:
            self.log("Dump method failed, trying Python method...")
            recovered_path = self.recover_via_python()

        if not recovered_path:
            self.log("✗ All recovery methods failed", "ERROR")
            return False

        # Step 5: Post-recovery integrity check
        self.log("\n" + "=" * 80)
        self.log("POST-RECOVERY INTEGRITY CHECK")
        self.log("=" * 80)
        recovered_check = self.run_integrity_check(recovered_path)

        # Step 6: Compare databases
        differences = self.compare_databases(original_check, recovered_check)

        # Step 7: Optimize recovered database
        if recovered_check.get("integrity_check") == [('ok',)]:
            self.log("\n" + "=" * 80)
            self.log("OPTIMIZING RECOVERED DATABASE")
            self.log("=" * 80)
            self.optimize_database(recovered_path)

        # Step 8: Save report
        self.log("\n" + "=" * 80)
        self.log("SAVING RECOVERY REPORT")
        self.log("=" * 80)
        self.save_recovery_report(original_check, recovered_check, differences)

        # Step 9: Final instructions
        self.log("\n" + "=" * 80)
        self.log("RECOVERY COMPLETE")
        self.log("=" * 80)
        self.log(f"Recovered database: {recovered_path}")
        self.log(f"Original backup: {backup_path}")
        self.log(f"\nTo use the recovered database, run:")
        self.log(f"  mv {self.db_path} {self.db_path}.old")
        self.log(f"  mv {recovered_path} {self.db_path}")

        if differences:
            self.log(f"\n⚠ WARNING: {len(differences)} table(s) have different row counts", "WARNING")
            self.log("Please review the recovery report before replacing the database")
        else:
            self.log("\n✓ All data appears to be intact!", "SUCCESS")

        return True


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Recover corrupted AngusNMS assets.db SQLite database"
    )
    parser.add_argument(
        "--db",
        default="assets.db",
        help="Path to database file (default: assets.db)"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only run integrity checks without recovery"
    )

    args = parser.parse_args()

    recovery = DatabaseRecovery(args.db)

    if args.check_only:
        print("Running integrity checks only...\n")
        if not recovery.check_file_exists():
            sys.exit(1)
        results = recovery.run_integrity_check()

        if results.get("integrity_check") == [('ok',)] and \
                results.get("quick_check") == [('ok',)]:
            print("\n✓ Database is healthy!")
            sys.exit(0)
        else:
            print("\n✗ Database has issues!")
            sys.exit(1)
    else:
        success = recovery.run_recovery()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()