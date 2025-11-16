# Notes System Design Documentation

## Overview

The Notes system is a comprehensive documentation and knowledge management feature integrated into the Network Management System. It provides rich-text note creation with associations to network assets (devices and sites).

## Architecture

### Database Schema

```sql
-- Core notes table
notes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    note_type TEXT DEFAULT 'general',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,
    tags TEXT  -- JSON array stored as text
)

-- Full-text search virtual table
note_fts (VIRTUAL TABLE using FTS5)

-- Associations to devices/sites
note_associations (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,  -- 'device' or 'site'
    entity_id TEXT NOT NULL,     -- device.id or site.code
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
)

-- File attachments
note_attachments (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    file_size INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
)
```

### Note Types

| Type | Purpose | Color Scheme |
|------|---------|--------------|
| `general` | General documentation | Gray |
| `site` | Site-specific notes | Primary (Purple) |
| `device` | Device-specific notes | Secondary (Blue) |
| `kb` | Knowledge base articles | Tertiary (Teal) |
| `incident` | Incident reports | Yellow |
| `maintenance` | Maintenance activities | Light Blue |

## Features

### 1. Rich Text Editing (TinyMCE)

**Implementation:**
- Self-hosted TinyMCE v7 (GPL licensed)
- Location: `app/static/tinymce/js/tinymce/`
- License key: `'gpl'` (open source)

**Capabilities:**
- Full WYSIWYG editing
- Headers, bold, italic, lists
- Tables
- Code blocks with syntax highlighting
- Image uploads (via attachment system)
- Links (internal and external)

**Configuration:**
```javascript
tinymce.init({
    selector: '#content',
    license_key: 'gpl',
    height: 500,
    plugins: ['advlist', 'autolink', 'lists', 'link', 'image', 
              'charmap', 'preview', 'anchor', 'searchreplace', 
              'visualblocks', 'code', 'fullscreen', 'insertdatetime', 
              'media', 'table', 'help', 'wordcount', 'codesample'],
    // ... additional config
})
```

### 2. Internal Linking

**Syntax:** `[[Note Title]]`

**Processing Flow:**
1. User types `[[Note Title]]` in content
2. Server-side processing via `process_internal_links()` in `utils.py`
3. Converts to: `<a href="/notes/{id}" class="internal-link">Note Title</a>`
4. Broken links show as: `<span class="broken-link">Note Title</span>`

**Autocomplete:**
- API endpoint: `/notes/api/link-suggestions?q=<query>`
- Returns matching note titles for autocomplete (planned feature)

### 3. Attachments

**Supported Types:**
- Images: `image/*`
- SVG: `image/svg+xml` (sanitized)
- Future: PDFs, documents

**Storage:**
- Stored as BLOBs in `note_attachments` table
- Max size: 1MB per file
- SVG files are sanitized to remove dangerous elements

**Security:**
- SVG sanitization via `bleach` library
- Only safe elements/attributes allowed
- No JavaScript execution

### 4. Full-Text Search

**Implementation:**
- SQLite FTS5 virtual table (`note_fts`)
- Indexes: title, content, tags

**Usage:**
```python
Note.search("network troubleshooting")
```

### 5. Tagging System

**Format:**
- Comma-separated tags
- Stored as JSON array in database
- Example: `["network", "cisco", "troubleshooting"]`

**Features:**
- Filter notes by tag: `/notes?tag=network`
- Tag cloud/filtering in UI
- Multiple tags per note

### 6. Asset Associations

**Device Notes:**
- Link notes to specific devices
- View from device detail page (Notes tab)
- Create from device: `/notes/create?device_id=123`

**Site Notes:**
- Link notes to sites
- View from site detail page
- Create from site: `/notes/create?site_code=NYC01`

**Association Resolution:**
- Fetches actual device names (not just IDs)
- Displays: "Device: ush-a1-sml-01 (469)"
- Clickable links to asset detail pages

## User Interface

### Views

#### 1. Notes Index (`/notes`)
- **Layout:** Sortable data table
- **Features:**
  - Client-side column sorting (Title, Type, Updated)
  - Type filtering (All, Site, Device, KB, Incident, Maintenance)
  - Search box
  - Pagination (25 per page)
  - Note count display
- **Performance:** Scales to 300+ notes

#### 2. Note Detail (`/notes/{id}`)
- **Layout:** Single-column centered (max-width: 1000px)
- **Sections:**
  - Header (title, type badge, tags)
  - Metadata (created, updated, author)
  - Content (rich text rendered)
  - Attachments (grid view)
  - Associations (linked devices/sites)
- **Actions:**
  - Edit button
  - Export to Markdown
  - Delete (with confirmation)

#### 3. Note Form (`/notes/create`, `/notes/{id}/edit`)
- **Editor:** TinyMCE rich text editor
- **Fields:**
  - Title (required)
  - Type (dropdown)
  - Tags (comma-separated)
  - Content (rich text)
  - Auto-populated associations from query params

#### 4. Device Integration
- **Location:** Device detail page → Notes tab
- **Display:** Table format (5 columns)
- **Actions:**
  - "Add Note" button (pre-fills device_id)
  - "All Device Notes" filter link
  - Click row to view note

#### 5. Site Integration
- **Location:** Site detail page → Notes section
- **Display:** Table format
- **Actions:**
  - "Add Note" button (pre-fills site_code)
  - "All Site Notes" filter link
  - Click row to view note

## Code Organization

```
app/blueprints/notes/
├── __init__.py           # Blueprint registration
├── routes.py             # All view routes
├── models.py             # Database models (Note, NoteAssociation, NoteAttachment)
└── utils.py              # Helper functions (internal links, SVG sanitization)

app/templates/notes/
├── index.html            # Notes list (table view)
├── detail.html           # Note viewer
├── form.html             # Create/edit form (TinyMCE)
└── search.html           # Search results (planned)

app/static/tinymce/       # Self-hosted TinyMCE editor
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/notes` | GET | List all notes (paginated, filtered) |
| `/notes/create` | GET/POST | Create new note |
| `/notes/{id}` | GET | View note detail |
| `/notes/{id}/edit` | GET/POST | Edit note |
| `/notes/{id}/delete` | POST | Delete note |
| `/notes/search` | GET | Full-text search |
| `/notes/{id}/upload` | POST | Upload attachment |
| `/notes/attachments/{id}` | GET | Serve attachment |
| `/notes/attachments/{id}/delete` | POST | Delete attachment |
| `/notes/api/link-suggestions` | GET | Autocomplete for internal links |

## Workflow Examples

### Creating a Device Note

1. Navigate to device detail page
2. Click Notes tab
3. Click "Add Note" button
4. System redirects to: `/notes/create?device_id=469`
5. Form pre-populates device association
6. User enters title, content (with TinyMCE)
7. User optionally adds tags, images
8. Click "Create Note"
9. System creates note with association
10. Redirects to note detail view

### Viewing Notes for a Site

1. Navigate to site detail page
2. Scroll to "Site Notes" section
3. View table of associated notes
4. Click row to view full note
5. Or click "All Site Notes" to filter main list

### Internal Linking

1. Edit note in TinyMCE
2. Type: `[[Device Configuration Guide]]`
3. Save note
4. System converts to clickable link
5. Clicking link navigates to that note

## Future Enhancements

### Planned Features

1. **Note Versioning**
   - Track edit history
   - Show diff between versions
   - Revert to previous version

2. **Note Templates**
   - Predefined templates for common scenarios
   - Incident report template
   - Device configuration template
   - Maintenance log template

3. **Enhanced Search**
   - Advanced filters (date range, author, type)
   - Saved searches
   - Search within note content

4. **Collaborative Features**
   - Note sharing
   - Comments/discussions
   - Edit notifications

5. **Export Options**
   - PDF export (formatted)
   - HTML export
   - Bulk export

6. **Media Enhancements**
   - Video attachments
   - Audio notes
   - Drawing/annotation tools

## Performance Considerations

### Database
- Indexed columns: `id`, `note_type`, `created_at`, `updated_at`
- FTS5 index for full-text search
- Cascade deletes for cleanup

### Pagination
- Default: 25 notes per page
- Prevents loading large datasets
- Client-side sorting within page

### Attachments
- 1MB file size limit
- BLOB storage (suitable for small files)
- Consider file system storage for larger files

## Security

### Input Sanitization
- TinyMCE content: stored as-is, rendered with `|safe` filter
- SVG sanitization: removes scripts, dangerous elements
- SQL injection: prevented by parameterized queries

### Authentication
- All routes protected with `@login_required`
- User tracking via `created_by` field

### File Uploads
- Content-type validation
- File size limits
- SVG sanitization

## Styling

### Design System
- Material Design 3 (MD3) principles
- CSS custom properties for theming
- Dark mode support (via CSS variables)

### Key Components
- Cards: `.note-header`, `.info-card`
- Tables: `.devices-table` (reused from assets)
- Buttons: `.md-button-filled`, `.md-button-outlined`
- Badges: `.note-type-badge`

### Syntax Highlighting
- Library: Prism.js (prism-tomorrow theme)
- Languages: Python, JavaScript, Bash, JSON, YAML, SQL
- Line numbers plugin included

## Testing Checklist

- [ ] Create note (all types)
- [ ] Edit note
- [ ] Delete note
- [ ] Add tags
- [ ] Search notes
- [ ] Filter by type
- [ ] Upload image attachment
- [ ] Upload SVG attachment
- [ ] Create internal link
- [ ] Export to Markdown
- [ ] Associate with device
- [ ] Associate with site
- [ ] View note from device page
- [ ] View note from site page
- [ ] Pagination works
- [ ] Sorting works
- [ ] Code syntax highlighting
- [ ] Tables in content
- [ ] Rich text formatting

## Troubleshooting

### TinyMCE Not Loading
- Check: `/static/tinymce/js/tinymce/tinymce.min.js` exists
- Verify `license_key: 'gpl'` is set
- Check browser console for errors

### Internal Links Not Working
- Verify `process_internal_links()` is called on save
- Check note titles match exactly (case-sensitive)
- Ensure `utils.py` is imported in routes

### Images Not Displaying
- Check attachment exists in database
- Verify `serve_attachment` route is accessible
- Check content type is correct

### Search Not Working
- Verify `note_fts` virtual table exists
- Check FTS5 is enabled in SQLite
- Rebuild FTS index if needed

## Maintenance

### Regular Tasks
- Monitor attachment storage size
- Archive old notes (optional)
- Clean up orphaned attachments
- Rebuild FTS index periodically

### Database Migrations
- Add columns: `ALTER TABLE notes ADD COLUMN ...`
- Update indexes as needed
- Maintain backward compatibility

---

**Last Updated:** 2025-10-02  
**Version:** 1.0  
**Status:** Production Ready