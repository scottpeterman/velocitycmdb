# app/utils/database.py
import sqlite3
from contextlib import contextmanager
from flask import current_app

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    # FIX: Use 'DATABASE' not 'DATABASE_PATH' to match app config in __init__.py
    # app.config['DATABASE'] = os.path.join(data_dir, 'assets.db')
    db_path = current_app.config.get('DATABASE', 'assets.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()