-- SQLite Database Documentation
-- Database: users.db
-- Generated: 2025-11-13 19:38:32
-- Path: c:\Users\admin\.velocitycmdb\data\users.db
================================================================================

-- SQLite Version: 3.45.3

-- TABLES
--------------------------------------------------------------------------------

-- Table: users
----------------------------------------
-- Columns:
--   id: INTEGER (PRIMARY KEY)
--   username: TEXT NOT NULL
--   email: TEXT NOT NULL
--   password_hash: TEXT NOT NULL
--   is_active: INTEGER DEFAULT 1
--   is_admin: INTEGER DEFAULT 0
--   display_name: TEXT
--   groups_json: TEXT DEFAULT '[]'
--   created_at: TEXT NOT NULL
--   updated_at: TEXT
--   last_login: TEXT
--   auth_backend: TEXT DEFAULT 'database'

CREATE TABLE users (
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
            );

-- SUMMARY
--------------------------------------------------------------------------------
-- Tables: 1
-- Views: 0
-- Indexes: 0
-- Triggers: 0
