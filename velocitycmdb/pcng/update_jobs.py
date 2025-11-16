#!/usr/bin/env python3
"""
Bulk update job configuration files to add fingerprint_options section
"""

import os
import json
import glob
import argparse
from pathlib import Path


def update_job_file(job_file_path: str, fingerprinted_only: bool = False,
                    fingerprint_base: str = "./fingerprints", backup: bool = True) -> bool:
    """Update a single job file to add fingerprint_options"""
    try:
        # Read existing job file
        with open(job_file_path, 'r', encoding='utf-8') as f:
            job_config = json.load(f)

        # Check if fingerprint_options already exists
        if 'fingerprint_options' in job_config:
            print(f"  Skipping {os.path.basename(job_file_path)} - fingerprint_options already exists")
            return True

        # Create backup if requested
        if backup:
            backup_path = job_file_path + '.bak'
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(job_config, f, indent=2)

        # Add fingerprint_options section
        job_config['fingerprint_options'] = {
            "fingerprinted_only": fingerprinted_only,
            "fingerprint_only": False,
            "fingerprint": False,
            "fingerprint_base": fingerprint_base
        }

        # Write updated job file
        with open(job_file_path, 'w', encoding='utf-8') as f:
            json.dump(job_config, f, indent=2)

        print(f"  Updated {os.path.basename(job_file_path)}")
        return True

    except Exception as e:
        print(f"  ERROR updating {os.path.basename(job_file_path)}: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Bulk update job configuration files to add fingerprint_options support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add fingerprint_options to all job files (default: fingerprinted_only=false)
  python update_jobs.py gnet_jobs/

  # Add fingerprint_options with fingerprinted_only=true for faster execution
  python update_jobs.py gnet_jobs/ --fingerprinted-only

  # Update specific pattern of files
  python update_jobs.py gnet_jobs/ --pattern "job_*cisco*.json"

  # Update without creating backups
  python update_jobs.py gnet_jobs/ --no-backup
        """
    )

    parser.add_argument('directory', help='Directory containing job configuration files')
    parser.add_argument('--pattern', default='job_*.json', help='File pattern to match (default: job_*.json)')
    parser.add_argument('--fingerprinted-only', action='store_true',
                        help='Set fingerprinted_only=true (only run on devices with existing fingerprints)')
    parser.add_argument('--fingerprint-base', default='./fingerprints',
                        help='Fingerprint base directory (default: ./fingerprints)')
    parser.add_argument('--no-backup', action='store_true',
                        help='Do not create backup files (.bak)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be updated without making changes')

    args = parser.parse_args()

    # Find job files
    job_dir = Path(args.directory)
    if not job_dir.exists():
        print(f"Error: Directory '{args.directory}' does not exist")
        return 1

    pattern_path = job_dir / args.pattern
    job_files = glob.glob(str(pattern_path))

    if not job_files:
        print(f"No job files found matching pattern: {pattern_path}")
        return 1

    job_files.sort()
    print(f"Found {len(job_files)} job files matching pattern '{args.pattern}'")

    if args.dry_run:
        print("\nDRY RUN - Would update these files:")
        for job_file in job_files:
            print(f"  {os.path.basename(job_file)}")
        print(f"\nFingerprint options that would be added:")
        print(f"  fingerprinted_only: {args.fingerprinted_only}")
        print(f"  fingerprint_base: {args.fingerprint_base}")
        print(f"  backup files: {'No' if args.no_backup else 'Yes'}")
        return 0

    # Update files
    print(f"\nUpdating job files...")
    print(f"  fingerprinted_only: {args.fingerprinted_only}")
    print(f"  fingerprint_base: {args.fingerprint_base}")
    print(f"  creating backups: {'No' if args.no_backup else 'Yes'}")
    print()

    updated_count = 0
    error_count = 0

    for job_file in job_files:
        success = update_job_file(
            job_file,
            fingerprinted_only=args.fingerprinted_only,
            fingerprint_base=args.fingerprint_base,
            backup=not args.no_backup
        )

        if success:
            updated_count += 1
        else:
            error_count += 1

    print(f"\nSummary:")
    print(f"  Files processed: {len(job_files)}")
    print(f"  Successfully updated: {updated_count}")
    print(f"  Errors: {error_count}")

    if updated_count > 0:
        print(f"\nJob files now support:")
        print(f"  --fingerprinted-only flag in batch runner")
        print(f"  Custom fingerprint base directory")
        print(f"  All fingerprinting modes (fingerprint-only, fingerprint, fingerprinted-only)")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    exit(main())