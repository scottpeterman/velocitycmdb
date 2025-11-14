#!/usr/bin/env python3
"""
SQLite Database Documentation Script
Generates SQL documentation for tables, views, and triggers in a SQLite database.
"""

import sqlite3
import sys
import os
from datetime import datetime
from pathlib import Path


class SQLiteDocumenter:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Connect to the SQLite database."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row  # Enable column access by name
            return True
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
            return False

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def get_tables(self):
        """Get all tables in the database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, sql 
            FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        return cursor.fetchall()

    def get_views(self):
        """Get all views in the database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, sql 
            FROM sqlite_master 
            WHERE type='view'
            ORDER BY name
        """)
        return cursor.fetchall()

    def get_triggers(self):
        """Get all triggers in the database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, sql, tbl_name
            FROM sqlite_master 
            WHERE type='trigger'
            ORDER BY tbl_name, name
        """)
        return cursor.fetchall()

    def get_indexes(self):
        """Get all indexes in the database."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name, sql, tbl_name
            FROM sqlite_master 
            WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%'
            ORDER BY tbl_name, name
        """)
        return cursor.fetchall()

    def get_table_info(self, table_name):
        """Get detailed column information for a table."""
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        return cursor.fetchall()

    def get_foreign_keys(self, table_name):
        """Get foreign key information for a table."""
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        return cursor.fetchall()

    def format_sql(self, sql):
        """Format SQL statement for better readability."""
        if not sql:
            return "-- No SQL definition available"

        # Add semicolon if missing
        sql = sql.strip()
        if not sql.endswith(';'):
            sql += ';'

        return sql

    def generate_documentation(self, output_file=None):
        """Generate complete database documentation."""
        if not self.connect():
            return False

        try:
            # Prepare output
            if output_file:
                output = open(output_file, 'w', encoding='utf-8')
            else:
                output = sys.stdout

            # Header
            db_name = Path(self.db_path).name
            output.write(f"-- SQLite Database Documentation\n")
            output.write(f"-- Database: {db_name}\n")
            output.write(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            output.write(f"-- Path: {self.db_path}\n")
            output.write("=" * 80 + "\n\n")

            # Database schema info
            cursor = self.conn.cursor()
            cursor.execute("SELECT sqlite_version()")
            sqlite_version = cursor.fetchone()[0]
            output.write(f"-- SQLite Version: {sqlite_version}\n\n")

            # Tables
            tables = self.get_tables()
            if tables:
                output.write("-- TABLES\n")
                output.write("-" * 80 + "\n\n")

                for table in tables:
                    table_name = table['name']
                    output.write(f"-- Table: {table_name}\n")
                    output.write("-" * 40 + "\n")

                    # Table structure
                    table_info = self.get_table_info(table_name)
                    if table_info:
                        output.write("-- Columns:\n")
                        for col in table_info:
                            pk_marker = " (PRIMARY KEY)" if col['pk'] else ""
                            null_marker = " NOT NULL" if col['notnull'] else ""
                            default = f" DEFAULT {col['dflt_value']}" if col['dflt_value'] else ""
                            output.write(f"--   {col['name']}: {col['type']}{null_marker}{default}{pk_marker}\n")
                        output.write("\n")

                    # Foreign keys
                    fks = self.get_foreign_keys(table_name)
                    if fks:
                        output.write("-- Foreign Keys:\n")
                        for fk in fks:
                            output.write(f"--   {fk['from']} -> {fk['table']}.{fk['to']}\n")
                        output.write("\n")

                    # Table SQL
                    output.write(self.format_sql(table['sql']) + "\n\n")

            # Views
            views = self.get_views()
            if views:
                output.write("-- VIEWS\n")
                output.write("-" * 80 + "\n\n")

                for view in views:
                    output.write(f"-- View: {view['name']}\n")
                    output.write("-" * 40 + "\n")
                    output.write(self.format_sql(view['sql']) + "\n\n")

            # Indexes
            indexes = self.get_indexes()
            if indexes:
                output.write("-- INDEXES\n")
                output.write("-" * 80 + "\n\n")

                current_table = None
                for index in indexes:
                    if index['tbl_name'] != current_table:
                        current_table = index['tbl_name']
                        output.write(f"-- Indexes for table: {current_table}\n")
                        output.write("-" * 40 + "\n")

                    output.write(f"-- Index: {index['name']}\n")
                    if index['sql']:
                        output.write(self.format_sql(index['sql']) + "\n\n")
                    else:
                        output.write("-- (Auto-generated index)\n\n")

            # Triggers
            triggers = self.get_triggers()
            if triggers:
                output.write("-- TRIGGERS\n")
                output.write("-" * 80 + "\n\n")

                current_table = None
                for trigger in triggers:
                    if trigger['tbl_name'] != current_table:
                        current_table = trigger['tbl_name']
                        output.write(f"-- Triggers for table: {current_table}\n")
                        output.write("-" * 40 + "\n")

                    output.write(f"-- Trigger: {trigger['name']}\n")
                    output.write(self.format_sql(trigger['sql']) + "\n\n")

            # Summary
            output.write("-- SUMMARY\n")
            output.write("-" * 80 + "\n")
            output.write(f"-- Tables: {len(tables)}\n")
            output.write(f"-- Views: {len(views)}\n")
            output.write(f"-- Indexes: {len(indexes)}\n")
            output.write(f"-- Triggers: {len(triggers)}\n")

            if output_file:
                output.close()
                print(f"Documentation generated successfully: {output_file}")

            return True

        except Exception as e:
            print(f"Error generating documentation: {e}")
            return False
        finally:
            self.close()


def main():
    """Main function to handle command line arguments."""
    if len(sys.argv) < 2:
        print("Usage: python sqlite_documenter.py <database_path> [output_file]")
        print("Example: python sqlite_documenter.py assets.db assets_schema.sql")
        sys.exit(1)

    db_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    # Check if database file exists
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)

    # Generate documentation
    documenter = SQLiteDocumenter(db_path)
    success = documenter.generate_documentation(output_file)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()