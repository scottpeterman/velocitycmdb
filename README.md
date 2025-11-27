# VelocityCMDB

**Tactical, highly portable network CMDB with automated discovery, change detection, and operational intelligence for Windows, Mac or Linux**

## Important Notice
VelocityCMDB is currently in Proof of Concept (POC) stage and is under active development. While functional, it is not yet recommended for production environments. The codebase and features are subject to significant changes. Feel free to test, contribute, and provide feedback, but please exercise caution in production or security-critical environments.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPLv3-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/velocitycmdb)](https://pypi.org/project/velocitycmdb/)

> **New site onboarded in under 1 hour** - Automated discovery, configuration capture, and topology visualization out of the box.

![Secure Cartography Visualization](https://raw.githubusercontent.com/scottpeterman/velocitycmdb/main/screenshots/slides1.gif)

---

## What is VelocityCMDB?

VelocityCMDB is a **pip-installable network CMDB** that combines asset management, automated discovery, configuration tracking, and operational intelligence in a unified platform.

**Key Features:**
- **Automated Discovery** - LLDP/CDP-based topology mapping
- **Device Inventory** - Complete asset tracking with components, sites, vendors, roles
- **Change Detection** - Real-time configuration and other CLI captured information monitoring with severity classification
- **Topology Visualization** - Interactive maps with export to GraphML/DrawIO/PNG
- **Map Library** - Import existing Visio/DrawIO diagrams organized by folder
- **Operational Search** - Full-text search across 8,891+ captures (Config, ARP, MAC, Inventory and more)
- **Integrated Documentation** - Wiki-style notes linked to devices
- **Web SSH Terminal** - Browser-based device access with authentication
- **Multi-Auth** - LDAP, local database, and OS authentication

**Why VelocityCMDB?**
- **Fast Setup** - `pip install velocitycmdb && velocitycmdb init && velocitycmdb run`
- **Wizard-Driven** - Discovery and collection wizards guide deployment
- **Enterprise Friendly** - Basic role-based access, audit logging, backup/restore
- **Engineer-Focused** - CLI tools, REST API, and scriptable workflows, run locally or on a server

---

## Quick Start

### Installation

```bash
# Install from PyPI
pip install velocitycmdb

# Initialize databases, directories, config, and admin user
velocitycmdb init

# Start the web server
velocitycmdb run
```

Access the dashboard at `http://localhost:8086`

Default credentials: **admin / admin** (change after first login)

### Onboard Your First Site

**Step 1: Run Discovery Wizard** (15 minutes)
- Navigate to Discovery > Wizard
- Enter seed device credentials
- Let LLDP/CDP discover your network
- Review topology map

**Step 2: Run Collection Wizard** (30 minutes)
- Select discovered devices
- Choose capture types (configs, routes, MACs, etc.)
- Execute concurrent collection
- Review capture status

**Total Time: ~45 minutes**

---

## Architecture

VelocityCMDB is built on proven open-source components:

**Foundation:**
- [Secure Cartography](https://github.com/scottpeterman/secure_cartography) - Network discovery (134+ stars, 21 forks)
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
- **Components** - Hardware inventory (1,684 components tracked)
- **Sites/Vendors/Roles** - Complete taxonomy management
- **Bulk Operations** - Preview-commit workflow for batch changes

### Discovery and Topology
- **Automated Discovery** - LLDP/CDP-based network mapping
- **Topology Maps** - Interactive visualization with export
- **Secure Cartography** - Enhanced topology with vendor icons
- **Multiple Formats** - GraphML (yEd), DrawIO, PNG, SVG

### Network Map Library

Centralize your network documentation alongside CMDB data - no discovery required.

- **Bring Your Own Diagrams** - Import SVG exports from Visio, DrawIO, Lucidchart, or any diagramming tool
- **Flexible Organization** - Group by site, region, project, technology, or any folder structure
- **Automatic Thumbnails** - Preview images generated on first view
- **Multiple Formats** - Store companion files (.json, .graphml, .drawio) alongside SVGs
- **In-App Help** - Built-in guidance shows directory structure and setup

**Use Cases:**
- Legacy Visio diagrams maintained over years
- Compliance and audit documentation that must remain static
- Reference architectures and design templates
- Vendor-provided network diagrams
- Hand-crafted documentation for specific systems

**Directory Structure:**
```
~/.velocitycmdb/data/maps/
├── datacenter-east/        # Any folder name becomes a group
│   ├── core-topology.svg
│   └── wan-design.svg
├── compliance-docs/        # Organize however you want
│   └── pci-network.svg
└── projects/
    └── 2025-refresh.svg
```

Maps with an SVG file appear automatically in the UI. Optional companion files (.json, .graphml, .drawio) are available for download when present.


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

### Security and Administration
- **Multi-Auth Backend** - LDAP, database, OS authentication
- **Role-Based Access** - Admin, operator, viewer groups
- **Audit Logging** - Track all administrative actions
- **Backup/Restore** - Complete system lifecycle management
- **User Management** - Full CRUD with password policies

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
*33 configuration changes with severity*

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
- 357 devices managed
- 53 sites across infrastructure  
- 126 switch stacks tracked
- 1,684 hardware components
- 8,891 successful captures
- 99.3% device classification accuracy

**Performance:**
- Discovery: 45-60 min for 295 devices
- Fingerprinting: 60-90 min (8 concurrent processes)
- Full onboarding cycle: ~4 hours (manual)
- Dashboard response: <500ms
- Backup: 15-30 sec (58 MB compressed)

**Vendor Support:**
- Cisco IOS/IOS-XE/NX-OS
- Arista EOS
- HPE ProCurve/Aruba
- Juniper Junos (beta)

---

## Documentation

Comprehensive guides for every component:

**Getting Started:**
- [Quick Start Guide](QUICKSTART.md)
- [Authentication Configuration](README_Auth_Config.md)
- [Shadow Users Guide](SHADOW_USERS_GUIDE.md)

**Core Workflows:**
- Network Discovery - See Quick Start
- Data Collection - See Quick Start
- Change Detection - Built-in, automatic

**Administration:**
- User Management - Admin > User Management
- Backup/Restore - Admin > Maintenance

---

## CLI Reference

```bash
# Initialize system (first time setup)
velocitycmdb init

# Re-initialize and overwrite config
velocitycmdb init --force

# Start web server (default: port 8086)
velocitycmdb run

# Start with SSL enabled
velocitycmdb run --ssl

# Start on custom port
velocitycmdb run -p 8443

# Start on custom host and port
velocitycmdb run --host 127.0.0.1 --port 5000

# Disable debug mode (for production)
velocitycmdb run --no-debug

# Show help
velocitycmdb --help
velocitycmdb init --help
velocitycmdb run --help
```

---

## Roadmap

### v1.0 - Foundation (Current)
- [x] Pip-installable package
- [x] Wizard-driven workflows
- [x] 13+ feature modules
- [x] Multi-auth backend
- [x] Material Design 3 UI

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

## Community and Support

**Resources:**
- [Documentation](QUICKSTART.md)
- [Discussions](https://github.com/scottpeterman/velocitycmdb/discussions)
- [Issue Tracker](https://github.com/scottpeterman/velocitycmdb/issues)

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

GPLv3 License - See [LICENSE](LICENSE) for details.

---

## Credits

Created by [Scott Peterman](https://github.com/scottpeterman)

Built with:
- Flask and SocketIO
- Cytoscape.js
- Material Design 3
- TextFSM and Paramiko
- NetworkX and SQLite

**Acknowledgments:**
- NetBox Labs for community support
- Network automation community for feedback
- Contributors and early adopters

---

*VelocityCMDB v1.0 - Production Ready | November 2025*
