# VelocityCMDB

**Tactical, highly portable network CMDB with automated discovery, change detection, and operational intelligence for Windows, Mac or Linux**

## ⚠️ Important Notice
VelocityCMDB is currently in Proof of Concept (POC) stage and is under active development. While functional, it is not yet recommended for production environments. The codebase and features are subject to significant changes. Feel free to test, contribute, and provide feedback, but please exercise caution in production or security-critical environments.

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPLv3-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-coming%20soon-orange)](https://pypi.org/project/velocitycmdb/)

> **New site onboarded in under 1 hour** - Automated discovery, configuration capture, and topology visualization out of the box.

![Secure Cartography Visualization](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/slides1.gif)

---

## What is VelocityCMDB?

VelocityCMDB is a **pip-installable network CMDB** that combines asset management, automated discovery, configuration tracking, and operational intelligence in a unified platform.

**Key Features:**
- **Automated Discovery** - LLDP/CDP-based topology mapping
- **Device Inventory** - Complete asset tracking with components, sites, vendors, roles
- **Change Detection** - Real-time configuration and other cli captured information monitoring with severity classification
- **Topology Visualization** - Interactive maps with export to GraphML/DrawIO/PNG
- **Operational Search** - Full-text search across 8k+ captures (Config, Arp, Mac, Inventory and more)
- **Integrated Documentation** - Wiki-style notes linked to devices
- **Web SSH Terminal** - Browser-based device access with authentication
- **Multi-Auth** - LDAP, local database, and OS authentication

**Why VelocityCMDB?**
- **Fast Setup** - `pip install velocitycmdb && init command, then start the app`
- **Wizard-Driven** - Discovery and collection wizards guide deployment
- **Enterprise Friendly** - Basic Role-based access, audit logging, backup/restore
- **Engineer-Focused** - CLI tools, REST API, and scriptable workflows, run locally or on a server

---

## Quick Start

### Installation

```bash
# Install from PyPI (coming soon)
pip install velocitycmdb

# Initialize databases and directories
python -m velocitycmdb.cli init

# Create first admin user
python -m velocitycmdb.cli create-admin

# Start the web server
python -m velocitycmdb.app.run
```

Access the dashboard at `http://localhost:8086`

### Onboard Your First Site

**Step 1: Run Discovery Wizard** (15 minutes)
- Navigate to Discovery → Wizard
- Enter seed device credentials
- Let LLDP/CDP discover your network
- Review topology map

**Step 2: Run Collection Wizard** (30 minutes)
- Select discovered devices
- Choose capture types (configs, routes, MACs, etc.)
- Execute concurrent collection
- Review capture status

**Total Time: ~45 minutes** ✅

---

## Architecture

VelocityCMDB is built on proven open-source components:

**Foundation:**
- [Secure Cartography](https://github.com/scottpeterman/secure_cartography) - Network discovery (149⭐)
- Paramiko - SSH automation
- TextFSM - Multi-vendor parsing (100+ templates)
- Flask + SocketIO - Real-time web interface
- SQLite FTS5 - Full-text search

**Novel Contributions:**
- Pip-installable packaging with CLI entry points
- Wizard-driven workflows for discovery and collection
- Component-level hardware tracking with normalization
- Integrated knowledge system with device associations
- Dual-database architecture (assets + ARP tracking)
- Configuration change detection with content hashing

**Structure:**
```
velocitycmdb/
├── cli.py                 # Command-line interface
├── app/                   # Flask web application
│   ├── blueprints/       # 13+ modular features
│   └── templates/        # Material Design 3 UI
├── services/             # Business logic
│   ├── discovery.py      # LLDP-based topology
│   ├── collection.py     # Data capture orchestration
│   └── fingerprint.py    # Device classification
├── db/                   # Database management
└── pcng/                 # Capture engine (100+ job templates)
```

---

## Features

### Asset Management
- **Devices** - Full CRUD with sites, vendors, roles, stacks
- **Components** - Hardware inventory (1.5k+ components tracked), may include optics, fans, power, stack info etc
- **Sites/Vendors/Roles** - Complete taxonomy management
- **Bulk Operations** - Preview-commit workflow for batch changes

### Discovery & Topology
- **Automated Discovery** - LLDP/CDP-based network mapping
- **Topology Maps** - Interactive visualization with export
- **Secure Cartography** - Enhanced topology with vendor icons
- **Multiple Formats** - GraphML (yEd), DrawIO, PNG, SVG

### Operational Intelligence
- **Capture Search** - Full-text search across configurations
- **Change Detection** - Real-time config monitoring with diffs
- **Coverage Analysis** - Gap identification and success metrics
- **OS Version Tracking** - Compliance monitoring
- **ARP Search** - MAC address lookup with vendor OUI

### Collaboration
- **Notes System** - Wiki-style documentation with rich text
- **Device Associations** - Link notes to devices and sites
- **Internal Linking** - `[[Note Title]]` syntax for knowledge graphs
- **Full-Text Search** - Unified search across notes + captures

### Security & Administration
- **Multi-Auth Backend** - LDAP, database, OS authentication
- **Role-Based Access** - Admin, operator, viewer groups
- **Audit Logging** - Track all administrative actions
- **Backup/Restore** - Complete system lifecycle management
- **User Management** - Full Admin CRUD UI with password policies when auth using DB

### Automation
- **SSH Terminal** - WebSocket-based browser access
- **Collection Wizard** - Concurrent capture execution
- **100+ Job Templates** - Pre-built for Cisco, Arista, Juniper, HPE
- **REST API** - Programmatic access to all features

---

## Screenshots

<table>
<tr>
<td width="50%">

### Device Inventory
![Device List](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/devices_light.png)
*12 devices across sites with vendor/role filtering*

</td>
<td width="50%">

### Device Detail
![Device Detail](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/device_detail_light.png)
*Hardware components with capture status*

</td>
</tr>
<tr>
<td width="50%">

### Change Tracking
![Changes](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/changes_light.png)
*configuration changes with severity*

</td>
<td width="50%">

### Collection Wizard
![Collection](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/collection_running_light.png)
*Real-time concurrent capture execution*

</td>
</tr>
<tr>
<td width="50%">

### Capture Search
![Search](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/capture_search_light.png)
*Full-text search across operational data*

</td>
<td width="50%">

### SSH Terminal
![SSH](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/ssh_light.png)
*Web-based device access with credentials*

</td>
</tr>
</table>

---

## Proven at Scale

**Production Deployment Stats:**
- ✅ 300+ devices managed
- ✅ 50+ sites across infrastructure  
- ✅ 120+ switch stacks tracked
- ✅ 1,6k hardware components
- ✅ 8.9k successful CLI captures
- ✅ 90% device classification accuracy, depending on platform. 

**Performance:**
- Discovery: 45-60 min for 300 devices
- Fingerprinting: 60-90 min (8 concurrent processes)
- Full onboarding cycle: ~4 hours (manual)
- Dashboard response: <500ms
- Backup: 15-30 sec (58 MB compressed)

**Vendor Support:**
- Cisco IOS/IOS-XE/NX-OS
- Arista EOS
- HPE ProCurve/Aruba .. limited
- Juniper Junos (beta) ... limited

---

## Documentation

Comprehensive guides for every component:

**Getting Started:**
- [Installation Guide](docs/installation.md)
- [Quick Start Tutorial](docs/quickstart.md)
- [Configuration Guide](docs/configuration.md)

**Core Workflows:**
- [Network Discovery](docs/discovery.md)
- [Data Collection](docs/collection.md)
- [Change Detection](docs/changes.md)
- [Topology Visualization](docs/topology.md)

**Administration:**
- [User Management](docs/admin.md)
- [Authentication Setup](docs/authentication.md)
- [Backup & Restore](docs/backup.md)
- [Database Management](docs/database.md)

**Development:**
- [API Documentation](docs/api.md)
- [Plugin Development](docs/plugins.md)
- [Contributing Guide](CONTRIBUTING.md)

---

## CLI Reference

```bash
# Initialize system
velocitycmdb init                    # Create databases and directories
velocitycmdb create-admin            # Create first admin user

# Server management  
velocitycmdb run                     # Start web server (port 8086)
velocitycmdb run --port 5000        # Custom port

# Database operations
velocitycmdb backup                  # Create system backup
velocitycmdb restore backup.zip      # Restore from backup
velocitycmdb db-check               # Validate database health

# Discovery operations
velocitycmdb discover --seed 10.0.1.1 --username admin

# Bulk operations
velocitycmdb collect --site "ENG Site" --capture configs
```

---

## Roadmap

### v1.0 - Foundation (Current)
- ✅ Pip-installable package
- ✅ Wizard-driven workflows
- ✅ 13+ feature modules
- ✅ Multi-auth backend
- ✅ Material Design 3 UI

### v1.1 - Enhanced Automation (Q1 2026)
- [ ] Job scheduler UI
- [ ] Webhook notifications
- [ ] Prometheus exporter
- [ ] Advanced search filters

### v1.2 - Integration (Q2 2026)
- [ ] NetBox plugin/sync
- [ ] REST API expansion
- [ ] Custom collection jobs
- [ ] Device driver plugins

### v2.0 - Enterprise (Q3 2026)
- [ ] Multi-tenancy
- [ ] SSO integration
- [ ] Distributed monitoring
- [ ] GitOps workflows

---

## Community & Support

**Resources:**
- 📖 [Documentation](https://velocitycmdb.readthedocs.io)
- 💬 [Discussions](https://github.com/scottpeterman/velocitycmdb/discussions)
- 🐛 [Issue Tracker](https://github.com/scottpeterman/velocitycmdb/issues)
- 📧 [Mailing List](https://groups.google.com/g/velocitycmdb)

**Contributing:**
We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Professional Support:**
Enterprise support and training available - contact via GitHub.

---

## Related Projects

Part of the VelociTerm ecosystem:

- [VelociTerm](https://github.com/scottpeterman/velociterm) - Web SSH terminal framework
- [Secure Cartography](https://github.com/scottpeterman/secure_cartography) - Network discovery engine
- [TerminalTelemetry](https://github.com/scottpeterman/terminaltelemetry) - SSH automation patterns
- [PyCorpus](https://github.com/scottpeterman/pycorpus) - Knowledge management (coming soon)

---

## License

MIT License - See [LICENSE](LICENSE) for details.

---

## Credits

Created by [Scott Peterman](https://github.com/scottpeterman)

Built with:
- Flask & SocketIO
- Cytoscape.js
- Material Design 3
- TextFSM & Paramiko
- NetworkX & SQLite

**Acknowledgments:**
- NetBox Labs for community support
- Network automation community for feedback
- Contributors and early adopters

---

*VelocityCMDB v1.0 - Production Ready | November 2025*

---
