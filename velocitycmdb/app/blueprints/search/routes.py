from flask import render_template, request, jsonify, current_app
import sqlite3
import re
import os
from typing import Dict, List, Any
import ipaddress

from . import search_bp


def get_db_connection(db_name='assets.db'):
    """Get database connection from app config"""
    if db_name == 'assets.db':
        db_path = current_app.config['DATABASE']
    elif db_name == 'arp_cat.db':
        db_path = current_app.config['ARP_DATABASE']
    else:
        # Fallback to data directory
        data_dir = current_app.config.get('VELOCITYCMDB_DATA_DIR',
                                          os.path.expanduser('~/.velocitycmdb/data'))
        db_path = os.path.join(data_dir, db_name)

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def deduplicate_by_id(items: List[Dict]) -> List[Dict]:
    """Remove duplicate items based on their 'id' field"""
    seen = set()
    result = []
    for item in items:
        if item.get('id') not in seen:
            seen.add(item['id'])
            result.append(item)
    return result


class UniversalSearch:
    """Universal search engine for network assets"""

    def __init__(self):
        pass

    def reconnaissance_search(self, query: str) -> Dict[str, int]:
        """Quick probe across all tables to see what exists"""
        probe_results = {
            'devices': 0,
            'components': 0,
            'device_serials': 0,
            'stack_serials': 0,
            'arp_entries': 0
        }

        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        # Probe devices (hostname, model, IP)
        cursor.execute("""
            SELECT COUNT(*) FROM devices 
            WHERE name LIKE ? COLLATE NOCASE
               OR normalized_name LIKE ? COLLATE NOCASE
               OR model LIKE ? COLLATE NOCASE
               OR management_ip = ?
               OR ipv4_address = ?
        """, (f'%{query}%', f'%{query}%', f'%{query}%', query, query))
        probe_results['devices'] = cursor.fetchone()[0]

        # Probe components
        cursor.execute("""
            SELECT COUNT(*) FROM components
            WHERE name LIKE ? COLLATE NOCASE
               OR description LIKE ? COLLATE NOCASE
               OR serial LIKE ? COLLATE NOCASE
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))
        probe_results['components'] = cursor.fetchone()[0]

        # Probe device serials
        cursor.execute("""
            SELECT COUNT(*) FROM device_serials
            WHERE serial LIKE ? COLLATE NOCASE
        """, (f'%{query}%',))
        probe_results['device_serials'] = cursor.fetchone()[0]

        # Probe stack member serials
        cursor.execute("""
            SELECT COUNT(*) FROM stack_members
            WHERE serial LIKE ? COLLATE NOCASE
        """, (f'%{query}%',))
        probe_results['stack_serials'] = cursor.fetchone()[0]

        conn.close()

        # Probe ARP database if available
        try:
            arp_conn = get_db_connection('arp_cat.db')
            arp_cursor = arp_conn.cursor()

            # Check for IP
            arp_cursor.execute("""
                SELECT COUNT(*) FROM arp_entries
                WHERE ip_address = ?
            """, (query,))
            ip_count = arp_cursor.fetchone()[0]

            # Check for MAC (normalized)
            normalized_mac = query.replace(':', '').replace('-', '').replace('.', '').upper()
            arp_cursor.execute("""
                SELECT COUNT(*) FROM arp_entries
                WHERE REPLACE(REPLACE(REPLACE(mac_address, ':', ''), '-', ''), '.', '') = ?
            """, (normalized_mac,))
            mac_count = arp_cursor.fetchone()[0]

            probe_results['arp_entries'] = ip_count + mac_count
            arp_conn.close()
        except Exception as e:
            print(f"ARP probe skipped: {e}")
            pass

        return probe_results

    def search_by_ip(self, query: str) -> Dict[str, Any]:
        """Search by IP address across devices, ARP, and captures"""
        results = {
            'type': 'ip',
            'query': query,
            'devices': [],
            'arp_entries': [],
            'config_mentions': []
        }

        # Search devices with matching management IP
        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        cursor.execute("""
            SELECT d.*, v.name as vendor_name, s.name as site_name
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN sites s ON d.site_code = s.code
            WHERE d.management_ip = ? OR d.ipv4_address = ?
        """, (query, query))

        results['devices'] = [dict(row) for row in cursor.fetchall()]

        # Search ARP entries
        try:
            arp_conn = get_db_connection('arp_cat.db')
            arp_cursor = arp_conn.cursor()

            arp_cursor.execute("""
                SELECT ae.*, d.hostname, c.context_name
                FROM arp_entries ae
                JOIN devices d ON ae.device_id = d.id
                JOIN contexts c ON ae.context_id = c.id
                WHERE ae.ip_address = ?
                ORDER BY ae.capture_timestamp DESC
                LIMIT 50
            """, (query,))

            results['arp_entries'] = [dict(row) for row in arp_cursor.fetchall()]
            arp_conn.close()
        except Exception as e:
            print(f"ARP search error: {e}")
            pass

        # Search in capture content (configs, routing tables, etc.)
        # Use DISTINCT to avoid duplicates at DB level
        cursor.execute("""
            SELECT DISTINCT cs.id, cs.*, d.name as device_name, d.management_ip
            FROM capture_snapshots cs
            JOIN devices d ON cs.device_id = d.id
            WHERE cs.content LIKE ?
            ORDER BY cs.captured_at DESC
            LIMIT 20
        """, (f'%{query}%',))

        results['config_mentions'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        conn.close()
        return results

    def search_by_mac(self, query: str) -> Dict[str, Any]:
        """Search by MAC address"""
        results = {
            'type': 'mac',
            'query': query,
            'arp_entries': [],
            'config_mentions': []
        }

        # Normalize MAC address for search
        normalized_mac = query.replace(':', '').replace('-', '').replace('.', '').upper()

        # Search ARP database
        try:
            arp_conn = get_db_connection('arp_cat.db')
            arp_cursor = arp_conn.cursor()

            arp_cursor.execute("""
                SELECT ae.*, d.hostname, d.vendor, c.context_name
                FROM arp_entries ae
                JOIN devices d ON ae.device_id = d.id
                JOIN contexts c ON ae.context_id = c.id
                WHERE REPLACE(REPLACE(REPLACE(ae.mac_address, ':', ''), '-', ''), '.', '') = ?
                ORDER BY ae.capture_timestamp DESC
                LIMIT 100
            """, (normalized_mac,))

            results['arp_entries'] = [dict(row) for row in arp_cursor.fetchall()]
            arp_conn.close()
        except Exception as e:
            print(f"ARP MAC search error: {e}")
            pass

        # Search in captures (MAC tables, etc.)
        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT cs.id, cs.*, d.name as device_name
            FROM capture_snapshots cs
            JOIN devices d ON cs.device_id = d.id
            WHERE cs.capture_type IN ('mac', 'cdp', 'lldp')
            AND cs.content LIKE ?
            LIMIT 20
        """, (f'%{query}%',))

        results['config_mentions'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])
        conn.close()

        return results

    def search_by_serial(self, query: str) -> Dict[str, Any]:
        """Search by serial number"""
        results = {
            'type': 'serial',
            'query': query,
            'devices': [],
            'components': [],
            'stack_members': []
        }

        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        # Search device serials
        cursor.execute("""
            SELECT d.*, ds.serial, v.name as vendor_name, s.name as site_name
            FROM devices d
            JOIN device_serials ds ON d.id = ds.device_id
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN sites s ON d.site_code = s.code
            WHERE ds.serial LIKE ? COLLATE NOCASE
        """, (f'%{query}%',))

        results['devices'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        # Search component serials
        cursor.execute("""
            SELECT c.*, d.name as device_name, d.management_ip
            FROM components c
            JOIN devices d ON c.device_id = d.id
            WHERE c.serial LIKE ? COLLATE NOCASE
        """, (f'%{query}%',))

        results['components'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        # Search stack members
        cursor.execute("""
            SELECT sm.*, d.name as device_name, d.management_ip
            FROM stack_members sm
            JOIN devices d ON sm.device_id = d.id
            WHERE sm.serial LIKE ? COLLATE NOCASE
        """, (f'%{query}%',))

        results['stack_members'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        conn.close()
        return results

    def search_devices(self, query: str) -> Dict[str, Any]:
        """Unified device search (hostname, model, IP)"""
        results = {
            'type': 'devices',
            'query': query,
            'devices': [],
            'captures': []
        }

        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        cursor.execute("""
            SELECT d.*, v.name as vendor_name, s.name as site_name,
                   dt.name as device_type_name,
                   COUNT(DISTINCT c.id) as component_count,
                   COUNT(DISTINCT dcc.capture_type) as capture_types
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN sites s ON d.site_code = s.code
            LEFT JOIN device_types dt ON d.device_type_id = dt.id
            LEFT JOIN components c ON d.id = c.device_id
            LEFT JOIN device_captures_current dcc ON d.id = dcc.device_id
            WHERE d.name LIKE ? COLLATE NOCASE
               OR d.normalized_name LIKE ? COLLATE NOCASE
               OR d.model LIKE ? COLLATE NOCASE
               OR d.management_ip = ?
               OR d.ipv4_address = ?
            GROUP BY d.id
            ORDER BY d.name
        """, (f'%{query}%', f'%{query}%', f'%{query}%', query, query))

        results['devices'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        # Search in capture content where this device name appears
        cursor.execute("""
            SELECT DISTINCT cs.id, cs.*, d.name as device_name, d.management_ip,
                   d.id as device_id
            FROM capture_snapshots cs
            JOIN devices d ON cs.device_id = d.id
            WHERE cs.content LIKE ? COLLATE NOCASE
            ORDER BY cs.captured_at DESC
            LIMIT 50
        """, (f'%{query}%',))

        results['captures'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        conn.close()

        return results

    def search_by_component(self, query: str) -> Dict[str, Any]:
        """Search components by name/description"""
        results = {
            'type': 'component',
            'query': query,
            'components': []
        }

        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        cursor.execute("""
            SELECT c.*, d.name as device_name, d.management_ip, d.id as device_id,
                   d.model as device_model, v.name as vendor_name
            FROM components c
            JOIN devices d ON c.device_id = d.id
            LEFT JOIN vendors v ON d.vendor_id = v.id
            WHERE c.name LIKE ? COLLATE NOCASE 
               OR c.description LIKE ? COLLATE NOCASE 
               OR c.type LIKE ? COLLATE NOCASE
            ORDER BY c.type, d.name
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))

        results['components'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        conn.close()
        return results

    def search_general(self, query: str) -> Dict[str, Any]:
        """General text search across all content"""
        results = {
            'type': 'general',
            'query': query,
            'devices': [],
            'components': [],
            'captures': [],
            'notes': []
        }

        conn = get_db_connection('assets.db')
        cursor = conn.cursor()

        # Search devices
        cursor.execute("""
            SELECT d.*, v.name as vendor_name, s.name as site_name
            FROM devices d
            LEFT JOIN vendors v ON d.vendor_id = v.id
            LEFT JOIN sites s ON d.site_code = s.code
            WHERE d.name LIKE ? COLLATE NOCASE 
               OR d.model LIKE ? COLLATE NOCASE 
               OR d.os_version LIKE ? COLLATE NOCASE
            LIMIT 20
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))

        results['devices'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        # Search components
        cursor.execute("""
            SELECT c.*, d.name as device_name, d.id as device_id
            FROM components c
            JOIN devices d ON c.device_id = d.id
            WHERE c.name LIKE ? COLLATE NOCASE 
               OR c.description LIKE ? COLLATE NOCASE
            LIMIT 20
        """, (f'%{query}%', f'%{query}%'))

        results['components'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        # Search in capture FTS
        try:
            cursor.execute("""
                SELECT DISTINCT cs.id, cs.*, d.name as device_name
                FROM capture_snapshots cs
                JOIN devices d ON cs.device_id = d.id
                WHERE cs.id IN (
                    SELECT rowid FROM capture_fts WHERE content MATCH ?
                )
                LIMIT 20
            """, (query,))

            results['captures'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])
        except:
            # Fallback to LIKE if FTS fails
            cursor.execute("""
                SELECT DISTINCT cs.id, cs.*, d.name as device_name
                FROM capture_snapshots cs
                JOIN devices d ON cs.device_id = d.id
                WHERE cs.content LIKE ?
                LIMIT 20
            """, (f'%{query}%',))

            results['captures'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        # Search notes
        try:
            cursor.execute("""
                SELECT n.*
                FROM notes n
                WHERE n.id IN (
                    SELECT rowid FROM note_fts WHERE note_fts MATCH ?
                )
                LIMIT 10
            """, (query,))

            results['notes'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])
        except:
            # Fallback to LIKE if FTS fails
            cursor.execute("""
                SELECT n.*
                FROM notes n
                WHERE n.title LIKE ? COLLATE NOCASE 
                   OR n.content LIKE ? COLLATE NOCASE
                LIMIT 10
            """, (f'%{query}%', f'%{query}%'))

            results['notes'] = deduplicate_by_id([dict(row) for row in cursor.fetchall()])

        conn.close()
        return results

    def search(self, query: str) -> Dict[str, Any]:
        """Universal search entry point with intelligent query routing"""
        if not query or len(query) < 2:
            return {'error': 'Query too short', 'results': {}}

        # Run reconnaissance to see what exists
        probe = self.reconnaissance_search(query)

        # Build results
        all_results = {
            'query': query,
            'probe_summary': probe,
            'search_types_executed': [],
            'results': {}
        }

        # Execute searches only where data exists
        if probe['devices'] > 0:
            device_results = self.search_devices(query)
            all_results['results']['devices'] = device_results['devices']
            # Add captures separately if they exist
            if device_results.get('captures') and len(device_results['captures']) > 0:
                all_results['results']['device_captures'] = device_results['captures']
            all_results['search_types_executed'].append('devices')

        if probe['components'] > 0:
            component_results = self.search_by_component(query)
            all_results['results']['components'] = component_results['components']
            all_results['search_types_executed'].append('components')

        if probe['device_serials'] > 0 or probe['stack_serials'] > 0:
            serial_results = self.search_by_serial(query)
            # Flatten serial results
            all_results['results']['serial_devices'] = serial_results['devices']
            if serial_results['components']:
                all_results['results']['serial_components'] = serial_results['components']
            if serial_results['stack_members']:
                all_results['results']['serial_stack_members'] = serial_results['stack_members']
            all_results['search_types_executed'].append('serial')

        if probe['arp_entries'] > 0:
            # Determine if IP or MAC
            try:
                ipaddress.IPv4Address(query)
                ip_results = self.search_by_ip(query)
                # Flatten IP results
                if ip_results['devices']:
                    all_results['results']['ip_devices'] = ip_results['devices']
                if ip_results['arp_entries']:
                    all_results['results']['ip_arp_entries'] = ip_results['arp_entries']
                if ip_results['config_mentions']:
                    all_results['results']['ip_config_mentions'] = ip_results['config_mentions']
                all_results['search_types_executed'].append('ip')
            except:
                # Check if MAC pattern
                mac_patterns = [
                    r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',
                    r'^([0-9A-Fa-f]{4}\.){2}([0-9A-Fa-f]{4})$',
                    r'^([0-9A-Fa-f]{12})$'
                ]
                for pattern in mac_patterns:
                    if re.match(pattern, query):
                        mac_results = self.search_by_mac(query)
                        # Flatten MAC results
                        if mac_results['arp_entries']:
                            all_results['results']['mac_arp_entries'] = mac_results['arp_entries']
                        if mac_results['config_mentions']:
                            all_results['results']['mac_config_mentions'] = mac_results['config_mentions']
                        all_results['search_types_executed'].append('mac')
                        break

        # If nothing found in specific searches, do general FTS search
        if not all_results['search_types_executed']:
            general_results = self.search_general(query)
            # Flatten general results
            if general_results['devices']:
                all_results['results']['general_devices'] = general_results['devices']
            if general_results['components']:
                all_results['results']['general_components'] = general_results['components']
            if general_results['captures']:
                all_results['results']['general_captures'] = general_results['captures']
            if general_results['notes']:
                all_results['results']['general_notes'] = general_results['notes']
            all_results['search_types_executed'].append('general')

        return all_results


@search_bp.route('/search')
def index():
    """Universal search page"""
    return render_template('search/index.html')


@search_bp.route('/api/search')
def api_search():
    """API endpoint for universal search"""
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'error': 'No query provided'}), 400

    searcher = UniversalSearch()
    results = searcher.search(query)

    return jsonify(results)