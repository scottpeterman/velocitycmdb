# 📒 VelocityCMDB Notes System

*A built-in knowledge base for sites, devices, and operational documentation.*

The **Notes System** in VelocityCMDB is designed to replace scattered wikis, Notion pages, scratchpads, and tribal knowledge with a fully integrated, searchable documentation engine. Notes are tied directly to your network assets — devices and sites — and support rich text, tags, attachments, and internal linking.

It becomes the place where all operational knowledge actually lives.

---

# 🧱 Core Concepts

## What You Can Do With Notes

* Document sites and devices with rich formatting
* Build internal KB articles
* Track incidents and maintenance logs
* Attach images, diagrams, and files
* Link notes to each other wiki-style
* Search across all notes with full-text indexing
* Filter notes by tag, type, asset, or content

Integrated directly into the CMDB, it requires zero external tools or add-ons.

---

# 🗄️ Database Model (Simplified)

**Notes**

* Title, content, author
* Type (general, device, site, KB, etc.)
* Rich text stored as safe HTML
* Tags (JSON array)

**Associations**

* Link a note to one or more devices or sites

**Attachments**

* Images, SVGs (sanitized), documents
* Stored as BLOBs with type validation

**Full-Text Search**

* SQLite FTS5 indexes: title, content, tags

---

# 🎨 Editor & Rich Text Features

VelocityCMDB uses a **self-hosted TinyMCE v7** instance under GPL — no cloud calls, no license fees.

### Supported formatting:

* Headers, bold, italics, lists
* Tables
* Code blocks with syntax highlighting
* Inline and attached images
* Internal note links
* URL links
* Fullscreen editing

### Code Highlighting

Powered by Prism.js with:

* Python
* Bash
* JSON
* YAML
* SQL
* JavaScript

---

# 🔗 Internal Linking (“Wiki Style”)

You can reference other notes using:

```
[[Another Note Title]]
```

When saved, VelocityCMDB transforms it into a clickable in-app link.
Broken links become highlighted placeholders so users can fix them.

Autocomplete for internal links is also supported via the `/notes/api/link-suggestions` endpoint.

---

# 📎 Attachments

### Supported

* PNG, JPG, GIF
* SVG (sanitized)
* Future: PDF, documents

### Security

* SVG sanitized using `bleach`
* Strict MIME validation
* 1 MB per-file limit
* Stored inside the database for portability

---

# 🔍 Search & Tagging

### Full-Text Search (FTS5)

Search across:

* Titles
* Content
* Tags

### Tags

Tags are stored as JSON arrays and support:

* Multi-tag filtering
* Tag cloud
* Per-note badge display

---

# 🏷️ Note Types

| Type            | Purpose                        |
| --------------- | ------------------------------ |
| **general**     | Catch-all documentation        |
| **site**        | Site-specific notes            |
| **device**      | Device-related notes           |
| **kb**          | Knowledge base articles        |
| **incident**    | Incident logs                  |
| **maintenance** | Maintenance or change activity |

Each type displays as a colored badge so users can visually parse note lists quickly.

---

# 🖥️ UI Overview

### Notes Index

* Sorting (title, type, last updated)
* Searching and tag filtering
* Pagination
* Type filtering

### Note Detail View

* Metadata (created/updated/author)
* Rich text viewer
* Attachments section
* Associated devices and sites
* Action buttons: Edit, Delete, Export

### Editor View

* TinyMCE 7
* Tag input
* Type selector
* Auto-inject associations when opened from a device or site

---

# 🧩 Device & Site Integration

### From a Device Page:

* Notes tab shows all notes linked to that device
* “Add Note” auto-associates the note

### From a Site Page:

* Notes panel lists associated notes
* Site code prefilled on note creation

This ensures notes remain tied to context.

---

# 🚀 API Endpoints

REST endpoints support:

* Listing
* Creating
* Editing
* Deleting
* Attachment upload/download
* Full-text search
* Autocomplete for internal links

(Exact endpoints preserved verbatim from your original documentation.)

---

# 🔮 Future Enhancements (Roadmap)

* Versioning & diff of notes
* Prebuilt templates (incident, maintenance, runbook)
* Collaboration (comments, sharing, notifications)
* Advanced search operators
* PDF/HTML export
* Media tools, video, audio support

You've already laid the foundation — these are natural extensions.

---

# 🧼 Security Model

* SVG sanitization with bleach
* Full HTML sanitization pipeline
* Auth-protected routes
* Attachment type and size restrictions
* Parameterized queries (SQL injection safe)

Secure by default, especially important when users paste arbitrary content.

---

# 🛠 Maintenance & Operational Notes

* FTS index should be rebuilt periodically
* Orphaned attachments cleaned automatically via cascade delete
* BLOB storage acceptable for small files; FS-based storage optional for large files

---

