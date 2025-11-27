# create_users_db.py
import sqlite3
from pathlib import Path


def create_users_database(db_path='app/users.db'):
    """Create the users database with proper schema"""

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            is_admin INTEGER DEFAULT 0,
            display_name TEXT,
            groups_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            last_login TEXT,
            auth_backend TEXT DEFAULT 'database'
        )
    """)

    conn.commit()
    conn.close()

    print(f"✓ Database created at: {db_path}")


if __name__ == '__main__':
    create_users_database()