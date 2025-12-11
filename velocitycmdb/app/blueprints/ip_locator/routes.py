"""
IP Locator Blueprint Routes
Find where IPs live in the network
"""

import traceback
from flask import render_template, request, jsonify, current_app
from pathlib import Path

from . import ip_locator_bp


def get_data_dir():
    """Get configured data directory from app config"""
    return Path(current_app.config.get('VELOCITYCMDB_DATA_DIR', 
                                        '~/.velocitycmdb/data')).expanduser()


def get_locator_service():
    """Get IP locator service instance"""
    from velocitycmdb.services.ip_locator import IPLocatorService
    
    data_dir = get_data_dir()
    return IPLocatorService(
        assets_db_path=str(data_dir / 'assets.db'),
        arp_db_path=str(data_dir / 'arp_cat.db'),
        data_dir=data_dir
    )


@ip_locator_bp.route('/')
def index():
    """IP Locator search page"""
    ip_address = request.args.get('ip', '').strip()
    result = None
    error = None
    
    if ip_address:
        try:
            service = get_locator_service()
            result = service.locate_ip(ip_address)
        except Exception as e:
            traceback.print_exc()
            error = str(e)
    
    return render_template('ip_locator/index.html',
                          ip_address=ip_address,
                          result=result,
                          error=error)


@ip_locator_bp.route('/api/locate')
def api_locate():
    """API endpoint for IP location"""
    ip_address = request.args.get('ip', '').strip()
    
    if not ip_address:
        return jsonify({'error': 'IP address required'}), 400
    
    try:
        service = get_locator_service()
        result = service.locate_ip(ip_address)
        
        # Convert dataclasses to dicts for JSON
        return jsonify({
            'ip_address': result.ip_address,
            'summary': result.summary,
            'access_port': result.access_port,
            'arp_entries': [
                {
                    'ip_address': e.ip_address,
                    'mac_address': e.mac_address,
                    'interface': e.interface,
                    'device_name': e.device_name,
                    'device_id': e.device_id
                } for e in result.arp_entries
            ],
            'mac_entries': [
                {
                    'mac_address': e.mac_address,
                    'vlan': e.vlan,
                    'port': e.port,
                    'device_name': e.device_name,
                    'device_id': e.device_id,
                    'mac_type': e.mac_type
                } for e in result.mac_entries
            ],
            'route_entries': [
                {
                    'prefix': e.prefix,
                    'next_hop': e.next_hop,
                    'protocol': e.protocol,
                    'interface': e.interface,
                    'device_name': e.device_name,
                    'device_id': e.device_id
                } for e in result.route_entries
            ]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@ip_locator_bp.route('/api/bulk', methods=['POST'])
def api_bulk_locate():
    """Bulk IP location - accepts list of IPs"""
    data = request.get_json()
    
    if not data or 'ips' not in data:
        return jsonify({'error': 'List of IPs required'}), 400
    
    ips = data['ips']
    if not isinstance(ips, list):
        return jsonify({'error': 'ips must be a list'}), 400
    
    # Limit to prevent abuse
    if len(ips) > 100:
        return jsonify({'error': 'Maximum 100 IPs per request'}), 400
    
    try:
        service = get_locator_service()
        results = []
        
        for ip in ips:
            ip = ip.strip()
            if ip:
                result = service.locate_ip(ip)
                results.append({
                    'ip_address': result.ip_address,
                    'summary': result.summary,
                    'access_port': result.access_port,
                    'found': bool(result.arp_entries or result.mac_entries)
                })
        
        return jsonify({'results': results})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
