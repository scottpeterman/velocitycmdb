#!/usr/bin/env python3
"""
Script to find and delete 0-byte files in current directory and subdirectories.
Works on both Windows and Linux.
"""

import os
import sys
from pathlib import Path


def find_and_delete_zero_byte_files(directory='.', dry_run=False):
    """
    Find and delete 0-byte files in the specified directory and subdirectories.

    Args:
        directory (str): Directory to search (default: current directory)
        dry_run (bool): If True, only show what would be deleted without actually deleting

    Returns:
        tuple: (count_found, count_deleted, errors)
    """
    directory_path = Path(directory).resolve()
    zero_byte_files = []
    deleted_files = []
    errors = []

    print(f"Searching for 0-byte files in: {directory_path}")
    print("-" * 50)

    # Walk through directory tree
    try:
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                file_path = Path(root) / file
                try:
                    # Check if file exists and has 0 bytes
                    if file_path.exists() and file_path.stat().st_size == 0:
                        zero_byte_files.append(file_path)
                        print(f"Found 0-byte file: {file_path}")

                        if not dry_run:
                            try:
                                file_path.unlink()  # Delete the file
                                deleted_files.append(file_path)
                                print(f"  ✓ Deleted: {file_path}")
                            except OSError as e:
                                error_msg = f"Failed to delete {file_path}: {e}"
                                errors.append(error_msg)
                                print(f"  ✗ {error_msg}")
                        else:
                            print(f"  [DRY RUN] Would delete: {file_path}")

                except (OSError, PermissionError) as e:
                    error_msg = f"Error accessing {file_path}: {e}"
                    errors.append(error_msg)
                    print(f"  ✗ {error_msg}")

    except (OSError, PermissionError) as e:
        error_msg = f"Error accessing directory {directory_path}: {e}"
        errors.append(error_msg)
        print(f"✗ {error_msg}")
        return 0, 0, errors

    return len(zero_byte_files), len(deleted_files), errors


def main():
    """Main function with command line argument handling."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Find and delete 0-byte files in current directory and subdirectories"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting files"
    )
    parser.add_argument(
        "--directory",
        default=".",
        help="Directory to search (default: current directory)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt"
    )

    args = parser.parse_args()

    # Confirmation prompt (unless dry run or --confirm used)
    if not args.dry_run and not args.confirm:
        response = input("\nThis will permanently delete 0-byte files. Continue? (y/N): ")
        if response.lower() not in ['y', 'yes']:
            print("Operation cancelled.")
            return

    # Run the deletion
    found_count, deleted_count, errors = find_and_delete_zero_byte_files(
        args.directory,
        args.dry_run
    )

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"0-byte files found: {found_count}")

    if args.dry_run:
        print(f"Files that would be deleted: {found_count}")
        print("\nRun without --dry-run to actually delete the files.")
    else:
        print(f"Files successfully deleted: {deleted_count}")
        if errors:
            print(f"Errors encountered: {len(errors)}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  - {error}")

    # Exit with error code if there were errors
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()