import json
import sqlite3
from datetime import datetime
from velocitycmdb.app.utils.database import get_db_connection


class Note:
    @staticmethod
    def create(title, content, note_type='general', created_by=None, tags=None):
        """Create a new note"""
        with get_db_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO notes (title, content, note_type, created_by, tags)
                VALUES (?, ?, ?, ?, ?)
            ''', (title, content, note_type, created_by,
                  json.dumps(tags) if tags else None))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(note_id):
        """Fetch note by ID"""
        with get_db_connection() as conn:
            return conn.execute(
                'SELECT * FROM notes WHERE id = ?',
                (note_id,)
            ).fetchone()

    @staticmethod
    def update(note_id, title=None, content=None, tags=None):
        """Update existing note"""
        updates = []
        params = []

        if title is not None:
            updates.append('title = ?')
            params.append(title)
        if content is not None:
            updates.append('content = ?')
            params.append(content)
        if tags is not None:
            updates.append('tags = ?')
            params.append(json.dumps(tags) if tags else None)

        if not updates:
            return False

        params.append(note_id)
        query = f"UPDATE notes SET {', '.join(updates)} WHERE id = ?"

        with get_db_connection() as conn:
            conn.execute(query, params)
            conn.commit()
            return True

    @staticmethod
    def delete(note_id):
        """Delete note and cascading associations/attachments"""
        with get_db_connection() as conn:
            conn.execute('DELETE FROM notes WHERE id = ?', (note_id,))
            conn.commit()

    @staticmethod
    def list_all(note_type=None, limit=50, offset=0):
        """List notes with optional filtering"""
        query = 'SELECT * FROM notes'
        params = []

        if note_type:
            query += ' WHERE note_type = ?'
            params.append(note_type)

        query += ' ORDER BY updated_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        with get_db_connection() as conn:
            return conn.execute(query, params).fetchall()

    @staticmethod
    def search(query_text):
        """Full-text search"""
        with get_db_connection() as conn:
            results = conn.execute('''
                SELECT n.* FROM notes n
                JOIN note_fts ON n.id = note_fts.rowid
                WHERE note_fts MATCH ?
                ORDER BY rank
            ''', (query_text,)).fetchall()
            return results

    @staticmethod
    def find_by_title(title):
        """Find note by exact title match"""
        with get_db_connection() as conn:
            return conn.execute(
                'SELECT * FROM notes WHERE title = ?',
                (title,)
            ).fetchone()

    @staticmethod
    def search_titles(query, limit=10):
        """Search note titles for autocomplete"""
        with get_db_connection() as conn:
            return conn.execute('''
                SELECT id, title FROM notes 
                WHERE title LIKE ? 
                ORDER BY title 
                LIMIT ?
            ''', (f'%{query}%', limit)).fetchall()

    @staticmethod
    def count(note_type=None):
        """Count total notes"""
        query = 'SELECT COUNT(*) as count FROM notes'
        params = []

        if note_type:
            query += ' WHERE note_type = ?'
            params.append(note_type)

        with get_db_connection() as conn:
            return conn.execute(query, params).fetchone()['count']

    @staticmethod
    def list_by_tag(tag, limit=50, offset=0):
        """List notes by tag"""
        with get_db_connection() as conn:
            return conn.execute('''
                SELECT * FROM notes 
                WHERE tags LIKE ? 
                ORDER BY updated_at DESC 
                LIMIT ? OFFSET ?
            ''', (f'%"{tag}"%', limit, offset)).fetchall()


class NoteAssociation:
    @staticmethod
    def add(note_id, entity_type, entity_id):
        """Associate note with entity"""
        with get_db_connection() as conn:
            try:
                conn.execute('''
                    INSERT INTO note_associations (note_id, entity_type, entity_id)
                    VALUES (?, ?, ?)
                ''', (note_id, entity_type, entity_id))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # Already exists

    @staticmethod
    def remove(association_id):
        """Remove association"""
        with get_db_connection() as conn:
            conn.execute('DELETE FROM note_associations WHERE id = ?', (association_id,))
            conn.commit()

    @staticmethod
    def get_for_entity(entity_type, entity_id):
        """Get all notes for an entity"""
        with get_db_connection() as conn:
            return conn.execute('''
                SELECT n.* FROM notes n
                JOIN note_associations na ON n.id = na.note_id
                WHERE na.entity_type = ? AND na.entity_id = ?
                ORDER BY n.updated_at DESC
            ''', (entity_type, entity_id)).fetchall()

    @staticmethod
    def get_for_note(note_id):
        """Get all associations for a note"""
        with get_db_connection() as conn:
            return conn.execute('''
                SELECT * FROM note_associations WHERE note_id = ?
            ''', (note_id,)).fetchall()


class NoteAttachment:
    @staticmethod
    def create(note_id, filename, content_type, data, file_size):
        """Create attachment"""
        with get_db_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO note_attachments 
                (note_id, filename, content_type, data, file_size)
                VALUES (?, ?, ?, ?, ?)
            ''', (note_id, filename, content_type, data, file_size))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(attachment_id):
        """Get attachment by ID"""
        with get_db_connection() as conn:
            return conn.execute(
                'SELECT * FROM note_attachments WHERE id = ?',
                (attachment_id,)
            ).fetchone()

    @staticmethod
    def list_for_note(note_id):
        """List all attachments for a note"""
        with get_db_connection() as conn:
            return conn.execute('''
                SELECT * FROM note_attachments 
                WHERE note_id = ? 
                ORDER BY created_at DESC
            ''', (note_id,)).fetchall()

    @staticmethod
    def delete(attachment_id):
        """Delete attachment"""
        with get_db_connection() as conn:
            conn.execute('DELETE FROM note_attachments WHERE id = ?', (attachment_id,))
            conn.commit()