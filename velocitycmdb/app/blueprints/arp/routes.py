# app/blueprints/arp/routes.py
"""
ARP Search API - Self-contained with minimal dependencies
Direct SQL queries against arp_cat.db
OUI vendor lookup via mac-vendor-lookup library
"""

from flask import render_template, jsonify, request, current_app, g
import sqlite3
import re
from functools import wraps

# OUI Vendor Lookup - pip install mac-vendor-lookup
try:
    from mac_vendor_lookup import MacLookup

    MAC_LOOKUP = MacLookup()
    OUI_AVAILABLE = True
except ImportError:
    MAC_LOOKUP = None
    OUI_AVAILABLE = False


def get_arp_db_path():
    """Get ARP database path from Flask config"""
    return current_app.config.get('ARP_DATABASE')


def get_db():
    """Get database connection with row factory, stored in Flask g object"""
    if 'arp_db' not in g:
        db_path = get_arp_db_path()
        g.arp_db = sqlite3.connect(db_path)
        g.arp_db.row_factory = sqlite3.Row
    return g.arp_db


def close_db(e=None):
    """Close database connection"""
    db = g.pop('arp_db', None)
    if db is not None:
        db.close()


def init_app(app):
    """Register teardown function with Flask app"""
    app.teardown_appcontext(close_db)


# =============================================================================
# MAC Address Normalization
# =============================================================================

def normalize_mac(mac: str) -> str:
    """
    Normalize MAC address to lowercase colon-separated format.
    Accepts: aa:bb:cc:dd:ee:ff, AA-BB-CC-DD-EE-FF, aabb.ccdd.eeff, aabbccddeeff
    Returns: aa:bb:cc:dd:ee:ff or empty string if invalid
    """
    if not mac:
        return ""

    # Strip and remove all separators
    clean = re.sub(r'[^a-fA-F0-9]', '', mac.strip())

    # Must be exactly 12 hex characters
    if len(clean) != 12:
        return ""

    # Convert to lowercase colon format
    return ':'.join(clean[i:i + 2] for i in range(0, 12, 2)).lower()


def is_partial_mac(mac: str) -> bool:
    """Check if this looks like a partial MAC (for wildcard search)"""
    clean = re.sub(r'[^a-fA-F0-9]', '', mac.strip())
    return 0 < len(clean) < 12


def mac_to_search_pattern(mac: str) -> str:
    """
    Convert MAC input to SQL LIKE pattern for partial matching.
    Handles partial MACs and OUI prefixes.
    """
    # Remove separators but keep the hex chars
    clean = re.sub(r'[^a-fA-F0-9]', '', mac.strip()).lower()

    if not clean:
        return ""

    # Build pattern with colons inserted
    # For partial, we match the beginning
    parts = [clean[i:i + 2] for i in range(0, len(clean), 2)]

    # Handle odd-length input (partial last octet)
    if len(clean) % 2 == 1:
        parts[-1] = clean[-1]

    pattern = ':'.join(parts)
    return f"{pattern}%"


# =============================================================================
# OUI Vendor Lookup
# =============================================================================

def lookup_vendor(mac: str) -> str:
    """
    Look up vendor name for a MAC address using mac-vendor-lookup library.
    Returns vendor name or empty string if not found/unavailable.
    """
    if not OUI_AVAILABLE or not MAC_LOOKUP or not mac:
        return ""

    try:
        return MAC_LOOKUP.lookup(mac)
    except Exception:
        return ""


def enrich_with_vendor(results: list) -> list:
    """
    Add vendor information to search results based on MAC address OUI.
    Adds 'oui_vendor' field to each result.
    """
    if not OUI_AVAILABLE:
        return results

    # Cache lookups to avoid redundant queries for same OUI
    oui_cache = {}

    for result in results:
        mac = result.get('mac_address', '')
        if mac:
            # Get OUI (first 6 chars normalized)
            oui = mac[:8] if ':' in mac else mac[:6]  # aa:bb:cc or aabbcc

            if oui not in oui_cache:
                oui_cache[oui] = lookup_vendor(mac)

            result['oui_vendor'] = oui_cache[oui]
        else:
            result['oui_vendor'] = ''

    return results


# =============================================================================
# API Routes
# =============================================================================

from . import arp_bp


@arp_bp.route('/search')
def search_page():
    """ARP search interface"""
    return render_template('arp/search.html')


@arp_bp.route('/api/stats')
def api_stats():
    """Get database statistics"""
    try:
        db = get_db()
        cursor = db.cursor()

        stats = {}

        # Total devices
        cursor.execute("SELECT COUNT(*) FROM devices")
        stats['total_devices'] = cursor.fetchone()[0]

        # Total current ARP entries
        cursor.execute("SELECT COUNT(*) FROM arp_entries WHERE is_current = 1")
        stats['total_arp_entries'] = cursor.fetchone()[0]

        # Total historical entries (all)
        cursor.execute("SELECT COUNT(*) FROM arp_entries")
        stats['total_historical_entries'] = cursor.fetchone()[0]

        # Unique MACs (current)
        cursor.execute("SELECT COUNT(DISTINCT mac_address) FROM arp_entries WHERE is_current = 1")
        stats['unique_macs'] = cursor.fetchone()[0]

        # Unique IPs (current)
        cursor.execute("SELECT COUNT(DISTINCT ip_address) FROM arp_entries WHERE is_current = 1")
        stats['unique_ips'] = cursor.fetchone()[0]

        # Latest capture timestamp
        cursor.execute("SELECT MAX(capture_timestamp) FROM arp_entries")
        stats['latest_capture'] = cursor.fetchone()[0]

        # Contexts count
        cursor.execute("SELECT COUNT(*) FROM contexts")
        stats['total_contexts'] = cursor.fetchone()[0]

        # OUI lookup availability
        stats['oui_lookup_available'] = OUI_AVAILABLE

        return jsonify(stats)

    except Exception as e:
        current_app.logger.error(f"Error in api_stats: {e}")
        return jsonify({'error': str(e)}), 500


@arp_bp.route('/api/search/ip/<path:ip>')
def api_search_ip(ip):
    """
    Search by IP address.
    Supports exact match and prefix/CIDR-style matching.

    Query params:
        history: true/false - include historical entries (default: false)
        exact: true/false - exact match only (default: false for partial matching)
    """
    history = request.args.get('history', 'false').lower() == 'true'
    exact = request.args.get('exact', 'false').lower() == 'true'

    try:
        db = get_db()
        cursor = db.cursor()

        # Build query based on current vs history
        if history:
            base_query = """
                SELECT 
                    ae.id,
                    d.hostname,
                    d.device_type,
                    d.vendor,
                    d.site_code,
                    c.context_name,
                    c.context_type,
                    ae.ip_address,
                    ae.mac_address,
                    ae.mac_address_raw,
                    ae.interface_name,
                    ae.entry_type,
                    ae.age,
                    ae.protocol,
                    ae.capture_timestamp,
                    ae.source_file,
                    ae.is_current
                FROM arp_entries ae
                JOIN devices d ON ae.device_id = d.id
                JOIN contexts c ON ae.context_id = c.id
            """
        else:
            # Use the view for current entries
            base_query = """
                SELECT * FROM v_current_arp
            """

        # Determine match type
        ip_clean = ip.strip()

        if exact or '/' not in ip_clean:
            # Exact or prefix match
            if exact:
                where_clause = "WHERE ip_address = ?"
                params = [ip_clean]
            else:
                # Partial match - treat as prefix
                where_clause = "WHERE ip_address LIKE ?"
                params = [f"{ip_clean}%"]
        else:
            # CIDR notation - would need ipaddress module for proper subnet matching
            # For now, convert to prefix match on the network portion
            network_part = ip_clean.split('/')[0].rsplit('.', 1)[0]
            where_clause = "WHERE ip_address LIKE ?"
            params = [f"{network_part}.%"]

        query = f"{base_query} {where_clause} ORDER BY capture_timestamp DESC LIMIT 500"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = [dict(row) for row in rows]

        # Enrich with OUI vendor info
        results = enrich_with_vendor(results)

        return jsonify({
            'success': True,
            'query': ip,
            'match_type': 'exact' if exact else 'prefix',
            'include_history': history,
            'count': len(results),
            'oui_available': OUI_AVAILABLE,
            'results': results
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_search_ip: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/search/mac/<path:mac>')
def api_search_mac(mac):
    """
    Search by MAC address.
    Handles multiple formats and partial/OUI matching.

    Query params:
        history: true/false - include historical entries (default: false)
        exact: true/false - exact match only (default: auto-detect)
    """
    history = request.args.get('history', 'false').lower() == 'true'
    exact_param = request.args.get('exact', 'auto')

    try:
        # Normalize input
        normalized = normalize_mac(mac)
        is_partial = is_partial_mac(mac)

        # Determine if exact match
        if exact_param == 'auto':
            exact = bool(normalized) and not is_partial
        else:
            exact = exact_param.lower() == 'true'

        db = get_db()
        cursor = db.cursor()

        # Build query
        if history:
            base_query = """
                SELECT 
                    ae.id,
                    d.hostname,
                    d.device_type,
                    d.vendor,
                    d.site_code,
                    c.context_name,
                    c.context_type,
                    ae.ip_address,
                    ae.mac_address,
                    ae.mac_address_raw,
                    ae.interface_name,
                    ae.entry_type,
                    ae.age,
                    ae.protocol,
                    ae.capture_timestamp,
                    ae.source_file,
                    ae.is_current
                FROM arp_entries ae
                JOIN devices d ON ae.device_id = d.id
                JOIN contexts c ON ae.context_id = c.id
            """
        else:
            base_query = "SELECT * FROM v_current_arp"

        if exact and normalized:
            # Exact match on normalized MAC
            where_clause = "WHERE mac_address = ?"
            params = [normalized]
            match_type = 'exact'
        elif is_partial or not normalized:
            # Partial/OUI search
            pattern = mac_to_search_pattern(mac)
            if not pattern:
                return jsonify({
                    'success': False,
                    'error': 'Invalid MAC address format'
                }), 400

            # Search both normalized and raw columns
            where_clause = "WHERE mac_address LIKE ? OR mac_address_raw LIKE ?"
            params = [pattern, f"%{mac.strip()}%"]
            match_type = 'partial'
        else:
            # Full MAC provided but not exact - still do exact on normalized
            where_clause = "WHERE mac_address = ?"
            params = [normalized]
            match_type = 'exact'

        query = f"{base_query} {where_clause} ORDER BY capture_timestamp DESC LIMIT 500"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = [dict(row) for row in rows]

        # Enrich with OUI vendor info
        results = enrich_with_vendor(results)

        return jsonify({
            'success': True,
            'query': mac,
            'normalized_query': normalized if normalized else None,
            'match_type': match_type,
            'include_history': history,
            'count': len(results),
            'oui_available': OUI_AVAILABLE,
            'results': results
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_search_mac: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/search/unified')
def api_search_unified():
    """
    Unified search - auto-detect if input is IP or MAC and search accordingly.

    Query params:
        q: search query (IP or MAC)
        history: true/false
    """
    query = request.args.get('q', '').strip()
    history = request.args.get('history', 'false').lower() == 'true'

    if not query:
        return jsonify({'success': False, 'error': 'No search query provided'}), 400

    # Detect if IP or MAC
    # IP pattern: contains dots and numbers, no hex letters beyond what's in octets
    # MAC pattern: contains hex letters or common MAC separators

    ip_pattern = re.compile(r'^[\d.]+$|^\d+\.\d+\.\d+\.\d+(/\d+)?$')
    mac_chars = re.compile(r'[a-fA-F]|[:\-]')

    if ip_pattern.match(query):
        # Looks like an IP
        search_type = 'ip'
    elif mac_chars.search(query):
        # Has hex letters or MAC separators
        search_type = 'mac'
    elif re.match(r'^[0-9a-fA-F]+$', query):
        # Pure hex - could be MAC without separators
        if len(query) <= 12:
            search_type = 'mac'
        else:
            search_type = 'ip'  # Probably not, but default
    else:
        search_type = 'ip'  # Default

    # Redirect to appropriate search
    if search_type == 'ip':
        return api_search_ip(query)
    else:
        return api_search_mac(query)


@arp_bp.route('/api/device/<hostname>')
def api_device_summary(hostname):
    """Get ARP summary for specific device"""
    try:
        db = get_db()
        cursor = db.cursor()

        # Get device info
        cursor.execute("""
            SELECT * FROM devices 
            WHERE hostname = ? OR normalized_hostname = ?
        """, [hostname, hostname.lower().replace(' ', '_')])

        device_row = cursor.fetchone()

        if not device_row:
            return jsonify({
                'success': False,
                'error': f'Device not found: {hostname}'
            }), 404

        device = dict(device_row)
        device_id = device['id']

        # Get contexts for this device
        cursor.execute("""
            SELECT * FROM contexts WHERE device_id = ?
        """, [device_id])
        contexts = [dict(row) for row in cursor.fetchall()]

        # Get current ARP entries count
        cursor.execute("""
            SELECT COUNT(*) FROM arp_entries 
            WHERE device_id = ? AND is_current = 1
        """, [device_id])
        current_count = cursor.fetchone()[0]

        # Get unique MACs for this device
        cursor.execute("""
            SELECT COUNT(DISTINCT mac_address) FROM arp_entries 
            WHERE device_id = ? AND is_current = 1
        """, [device_id])
        unique_macs = cursor.fetchone()[0]

        # Get snapshot history
        cursor.execute("""
            SELECT * FROM arp_snapshots 
            WHERE device_id = ?
            ORDER BY capture_timestamp DESC
            LIMIT 10
        """, [device_id])
        snapshots = [dict(row) for row in cursor.fetchall()]

        # Get sample of current entries
        cursor.execute("""
            SELECT * FROM v_current_arp 
            WHERE hostname = ?
            ORDER BY ip_address
            LIMIT 50
        """, [device['hostname']])
        sample_entries = [dict(row) for row in cursor.fetchall()]

        return jsonify({
            'success': True,
            'hostname': hostname,
            'device': device,
            'contexts': contexts,
            'stats': {
                'current_entries': current_count,
                'unique_macs': unique_macs,
                'context_count': len(contexts)
            },
            'recent_snapshots': snapshots,
            'sample_entries': sample_entries
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_device_summary: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/devices')
def api_list_devices():
    """List all devices with ARP data"""
    try:
        db = get_db()
        cursor = db.cursor()

        # Use the device summary view
        cursor.execute("SELECT * FROM v_device_summary ORDER BY hostname")
        rows = cursor.fetchall()

        devices = [dict(row) for row in rows]

        return jsonify({
            'success': True,
            'count': len(devices),
            'devices': devices
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_list_devices: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/mac-history/<path:mac>')
def api_mac_history(mac):
    """
    Get full history for a MAC address across all devices and time.
    Shows IP changes, device movements, etc.
    """
    try:
        normalized = normalize_mac(mac)
        if not normalized:
            return jsonify({
                'success': False,
                'error': 'Invalid MAC address format'
            }), 400

        db = get_db()
        cursor = db.cursor()

        # Use the mac history view
        cursor.execute("""
            SELECT * FROM v_mac_history 
            WHERE mac_address = ?
            ORDER BY capture_timestamp DESC
        """, [normalized])

        rows = cursor.fetchall()
        history = [dict(row) for row in rows]

        # Summarize unique IPs seen
        cursor.execute("""
            SELECT DISTINCT ip_address FROM arp_entries 
            WHERE mac_address = ?
        """, [normalized])
        unique_ips = [row[0] for row in cursor.fetchall()]

        # Summarize devices seen on
        cursor.execute("""
            SELECT DISTINCT d.hostname 
            FROM arp_entries ae
            JOIN devices d ON ae.device_id = d.id
            WHERE ae.mac_address = ?
        """, [normalized])
        devices_seen = [row[0] for row in cursor.fetchall()]

        return jsonify({
            'success': True,
            'mac_address': normalized,
            'summary': {
                'total_occurrences': len(history),
                'unique_ips': unique_ips,
                'devices_seen': devices_seen
            },
            'history': history
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_mac_history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/ip-history/<path:ip>')
def api_ip_history(ip):
    """
    Get full history for an IP address.
    Shows MAC changes over time (useful for detecting IP conflicts or DHCP changes).
    """
    try:
        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            SELECT 
                ae.ip_address,
                ae.mac_address,
                d.hostname,
                c.context_name,
                ae.interface_name,
                ae.capture_timestamp,
                ae.is_current
            FROM arp_entries ae
            JOIN devices d ON ae.device_id = d.id
            JOIN contexts c ON ae.context_id = c.id
            WHERE ae.ip_address = ?
            ORDER BY ae.capture_timestamp DESC
        """, [ip.strip()])

        rows = cursor.fetchall()
        history = [dict(row) for row in rows]

        # Get unique MACs for this IP
        cursor.execute("""
            SELECT DISTINCT mac_address FROM arp_entries 
            WHERE ip_address = ?
        """, [ip.strip()])
        unique_macs = [row[0] for row in cursor.fetchall()]

        return jsonify({
            'success': True,
            'ip_address': ip,
            'summary': {
                'total_occurrences': len(history),
                'unique_macs': unique_macs,
                'mac_count': len(unique_macs)
            },
            'history': history
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_ip_history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/oui/<path:mac>')
def api_oui_lookup(mac):
    """
    Look up vendor information for a MAC address or OUI prefix.

    Examples:
        /api/oui/aa:bb:cc:dd:ee:ff  - Full MAC
        /api/oui/aa:bb:cc           - OUI prefix only
        /api/oui/aabbcc             - OUI without separators
    """
    if not OUI_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'OUI lookup not available. Install: pip install mac-vendor-lookup'
        }), 503

    try:
        # Normalize input - we only need first 6 hex chars
        clean = re.sub(r'[^a-fA-F0-9]', '', mac.strip()).lower()

        if len(clean) < 6:
            return jsonify({
                'success': False,
                'error': 'Need at least 6 hex characters (3 octets) for OUI lookup'
            }), 400

        # Format as colon-separated for lookup
        oui = ':'.join(clean[i:i + 2] for i in range(0, 6, 2))

        vendor = lookup_vendor(oui)

        return jsonify({
            'success': True,
            'query': mac,
            'oui': oui,
            'vendor': vendor if vendor else None,
            'found': bool(vendor)
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_oui_lookup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@arp_bp.route('/api/oui/bulk', methods=['POST'])
def api_oui_bulk_lookup():
    """
    Bulk OUI lookup for multiple MAC addresses.

    POST body (JSON):
        { "macs": ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66", ...] }

    Returns:
        { "results": { "aa:bb:cc:dd:ee:ff": "Vendor Name", ... } }
    """
    if not OUI_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'OUI lookup not available. Install: pip install mac-vendor-lookup'
        }), 503

    try:
        data = request.get_json()
        if not data or 'macs' not in data:
            return jsonify({
                'success': False,
                'error': 'Request body must contain "macs" array'
            }), 400

        macs = data['macs']
        if not isinstance(macs, list):
            return jsonify({
                'success': False,
                'error': '"macs" must be an array'
            }), 400

        # Limit to prevent abuse
        if len(macs) > 1000:
            return jsonify({
                'success': False,
                'error': 'Maximum 1000 MACs per request'
            }), 400

        results = {}
        oui_cache = {}

        for mac in macs:
            if not mac:
                continue

            normalized = normalize_mac(mac)
            if not normalized:
                results[mac] = None
                continue

            # Cache by OUI
            oui = normalized[:8]  # aa:bb:cc
            if oui not in oui_cache:
                oui_cache[oui] = lookup_vendor(normalized)

            results[mac] = oui_cache[oui] if oui_cache[oui] else None

        return jsonify({
            'success': True,
            'count': len(results),
            'results': results
        })

    except Exception as e:
        current_app.logger.error(f"Error in api_oui_bulk_lookup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500