from flask import render_template, request, redirect, url_for, flash, jsonify, Response
from velocitycmdb.app.blueprints.auth.routes import login_required
from velocitycmdb.app.blueprints.notes import notes_bp
from velocitycmdb.app.blueprints.notes.models import Note, NoteAssociation, NoteAttachment
from velocitycmdb.app.blueprints.notes.utils import process_internal_links, sanitize_svg
import json

from velocitycmdb.app.utils.database import get_db_connection


@notes_bp.route('/')
@login_required
def index():
    """List all notes with filtering"""
    note_type = request.args.get('type')
    tag = request.args.get('tag')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 25))

    offset = (page - 1) * per_page

    if tag:
        notes = Note.list_by_tag(tag, limit=per_page, offset=offset)
    else:
        notes = Note.list_all(note_type=note_type, limit=per_page, offset=offset)

    # Get counts for stats
    total_notes = Note.count(note_type=note_type)

    return render_template('notes/index.html',
                           notes=notes,
                           total=total_notes,
                           page=page,
                           per_page=per_page)


@notes_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create new note"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '')
        note_type = request.form.get('note_type', 'general')
        tags_str = request.form.get('tags', '')

        # Parse tags (comma-separated)
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]

        if not title:
            flash('Note title is required', 'error')
            return render_template('notes/form.html',
                                   note=None,
                                   form_data=request.form)

        # Process internal links
        content = process_internal_links(content)

        # Create note
        note_id = Note.create(
            title=title,
            content=content,
            note_type=note_type,
            created_by=getattr(request, 'user', {}).get('username') if hasattr(request, 'user') else None,
            tags=tags
        )

        # Handle associations
        device_id = request.form.get('device_id')
        site_code = request.form.get('site_code')

        if device_id:
            NoteAssociation.add(note_id, 'device', device_id)
        if site_code:
            NoteAssociation.add(note_id, 'site', site_code)

        flash(f'Note "{title}" created successfully', 'success')
        return redirect(url_for('notes.detail', note_id=note_id))

    # Pre-populate associations from query params
    device_id = request.args.get('device_id')
    site_code = request.args.get('site_code')

    return render_template('notes/form.html',
                           note=None,
                           device_id=device_id,
                           site_code=site_code)


@notes_bp.route('/<int:note_id>')
@login_required
def detail(note_id):
    """View note detail"""
    note = Note.get_by_id(note_id)

    if not note:
        flash('Note not found', 'error')
        return redirect(url_for('notes.index'))

    # Get associations with names
    associations = []
    raw_associations = NoteAssociation.get_for_note(note_id)

    with get_db_connection() as conn:
        for assoc in raw_associations:
            assoc_dict = dict(assoc)

            if assoc['entity_type'] == 'device':
                device = conn.execute(
                    'SELECT id, name FROM devices WHERE id = ?',
                    (assoc['entity_id'],)
                ).fetchone()
                if device:
                    assoc_dict['entity_name'] = device['name']
                    assoc_dict['entity_id'] = device['id']

            elif assoc['entity_type'] == 'site':
                site = conn.execute(
                    'SELECT code, name FROM sites WHERE code = ?',
                    (assoc['entity_id'],)
                ).fetchone()
                if site:
                    assoc_dict['entity_name'] = site['name']
                    assoc_dict['entity_id'] = site['code']

            associations.append(assoc_dict)

    # Get attachments
    attachments = NoteAttachment.list_for_note(note_id)

    # Parse tags
    tags = json.loads(note['tags']) if note['tags'] else []

    return render_template('notes/detail.html',
                           note=note,
                           associations=associations,
                           attachments=attachments,
                           tags=tags)
@notes_bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(note_id):
    """Edit existing note"""
    note = Note.get_by_id(note_id)

    if not note:
        flash('Note not found', 'error')
        return redirect(url_for('notes.index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '')
        tags_str = request.form.get('tags', '')

        tags = [t.strip() for t in tags_str.split(',') if t.strip()]

        if not title:
            flash('Note title is required', 'error')
            return render_template('notes/form.html',
                                   note=note,
                                   form_data=request.form)

        # Process internal links
        content = process_internal_links(content)

        Note.update(note_id, title=title, content=content, tags=tags)

        flash(f'Note "{title}" updated successfully', 'success')
        return redirect(url_for('notes.detail', note_id=note_id))

    # Parse tags for display
    tags = json.loads(note['tags']) if note['tags'] else []

    return render_template('notes/form.html',
                           note=note,
                           tags=tags,
                           tags_str=', '.join(tags))


@notes_bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required
def delete(note_id):
    """Delete note"""
    note = Note.get_by_id(note_id)

    if not note:
        flash('Note not found', 'error')
        return redirect(url_for('notes.index'))

    Note.delete(note_id)
    flash(f'Note "{note["title"]}" deleted successfully', 'success')
    return redirect(url_for('notes.index'))


@notes_bp.route('/search')
@login_required
def search():
    """Full-text search"""
    query = request.args.get('q', '').strip()

    if not query:
        return render_template('notes/search.html', notes=[], query='')

    notes = Note.search(query)

    return render_template('notes/search.html', notes=notes, query=query)


@notes_bp.route('/<int:note_id>/upload', methods=['POST'])
@login_required
def upload_attachment(note_id):
    """Upload SVG or image attachment"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate content type
    if not file.content_type.startswith(('image/', 'image/svg+xml')):
        return jsonify({'error': 'Only images and SVG files allowed'}), 400

    # Read file content
    content = file.read()

    # Sanitize if SVG
    if file.content_type == 'image/svg+xml':
        content = sanitize_svg(content.decode('utf-8')).encode('utf-8')

    # Check size (1MB limit)
    if len(content) > 1024 * 1024:
        return jsonify({'error': 'File too large (max 1MB)'}), 400

    # Save attachment
    attachment_id = NoteAttachment.create(
        note_id=note_id,
        filename=file.filename,
        content_type=file.content_type,
        data=content,
        file_size=len(content)
    )

    return jsonify({
        'success': True,
        'id': attachment_id,
        'url': url_for('notes.serve_attachment', attachment_id=attachment_id)
    })


@notes_bp.route('/attachments/<int:attachment_id>')
@login_required
def serve_attachment(attachment_id):
    """Serve attachment (SVG/image)"""
    attachment = NoteAttachment.get_by_id(attachment_id)

    if not attachment:
        return 'Not found', 404

    return Response(
        attachment['data'],
        mimetype=attachment['content_type'],
        headers={'Content-Disposition': f'inline; filename="{attachment["filename"]}"'}
    )


@notes_bp.route('/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    """Delete attachment"""
    attachment = NoteAttachment.get_by_id(attachment_id)

    if not attachment:
        return jsonify({'error': 'Not found'}), 404

    NoteAttachment.delete(attachment_id)

    return jsonify({'success': True})


@notes_bp.route('/api/link-suggestions')
@login_required
def link_suggestions():
    """API endpoint for autocomplete when typing [["""
    query = request.args.get('q', '').strip()

    if len(query) < 2:
        return jsonify([])

    suggestions = Note.search_titles(query, limit=10)

    return jsonify([
        {'id': note['id'], 'title': note['title']}
        for note in suggestions
    ])