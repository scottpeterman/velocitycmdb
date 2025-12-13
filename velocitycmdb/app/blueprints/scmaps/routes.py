# velocitycmdb/app/blueprints/scmaps/routes.py

from flask import render_template, request, jsonify, current_app, send_file, url_for
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import json
import tempfile
import re
from . import scmaps_bp

try:
    from secure_cartography.graphml_mapper4 import NetworkGraphMLExporter
    from velocitycmdb.app.blueprints.scmaps.drawio_mapper2 import NetworkDrawioExporter
except ImportError:
    NetworkGraphMLExporter = None
    NetworkDrawioExporter = None


def get_maps_dir():
    maps_dir = current_app.config.get('SCMAPS_DIR') or os.path.join(
        current_app.config.get('DISCOVERY_DIR', 'discovery'), 'maps'
    )
    current_app.logger.debug(f"[SCMAPS DEBUG] get_maps_dir() returning: {maps_dir}")
    return maps_dir


def get_icon_map_file():
    return os.path.join(os.path.dirname(__file__), 'data', 'platform_icon_map.json')


def get_icons_dir():
    """Returns the path to the icons directory.

    Priority order:
    1. Blueprint's own static/icons_lib directory
    2. Application's static/icons_lib directory
    """
    # Try blueprint-specific icons first
    blueprint_icons = os.path.join(os.path.dirname(__file__), 'static', 'icons_lib')
    if os.path.exists(blueprint_icons):
        return blueprint_icons

    # Fall back to app-level static
    return os.path.join(current_app.root_path, 'static', 'icons_lib')


def get_icon_url(icon_filename):
    """Generate the correct URL for an icon file.

    Checks if icon exists in blueprint static folder first, then falls back to app static.
    """
    blueprint_icons = os.path.join(os.path.dirname(__file__), 'static', 'icons_lib')

    if os.path.exists(os.path.join(blueprint_icons, icon_filename)):
        # Use blueprint static URL
        return url_for('scmaps.static', filename=f'icons_lib/{icon_filename}')
    else:
        # Fall back to app static URL
        return f'/static/icons_lib/{icon_filename}'


def validate_map_name(map_name):
    if not map_name or '..' in map_name or '/' in map_name or '\\' in map_name:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', map_name))


def list_available_maps():
    maps_dir = get_maps_dir()
    os.makedirs(maps_dir, exist_ok=True)
    maps = []

    current_app.logger.info(f"[SCMAPS DEBUG] Scanning {maps_dir} for maps...")

    for item in os.listdir(maps_dir):
        map_path = os.path.join(maps_dir, item)
        current_app.logger.debug(f"[SCMAPS DEBUG] Checking: {item} (is_dir: {os.path.isdir(map_path)})")

        if os.path.isdir(map_path):
            topology_file = os.path.join(map_path, 'topology.json')
            current_app.logger.debug(
                f"[SCMAPS DEBUG]   Topology file: {topology_file} (exists: {os.path.exists(topology_file)})")

            if os.path.exists(topology_file):
                try:
                    # Get file stats
                    stat = os.stat(topology_file)

                    # Load topology to count nodes
                    with open(topology_file, 'r') as f:
                        topo_data = json.load(f)
                    node_count = len(topo_data) if isinstance(topo_data, dict) else 0

                    maps.append({
                        'name': item,
                        'has_layout': os.path.exists(os.path.join(map_path, 'layout.json')),
                        'topology_size': stat.st_size,
                        'node_count': node_count,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'created': datetime.fromtimestamp(stat.st_ctime).isoformat()
                    })
                    current_app.logger.info(f"[SCMAPS DEBUG]   ✓ Added map: {item} ({node_count} nodes)")
                except Exception as e:
                    current_app.logger.warning(f"[SCMAPS DEBUG]   ✗ Error reading map {item}: {e}")

    current_app.logger.info(f"[SCMAPS DEBUG] Total maps found: {len(maps)}")
    return sorted(maps, key=lambda x: x['modified'], reverse=True)


def load_topology(map_name):
    if not validate_map_name(map_name):
        raise ValueError(f"Invalid map name: {map_name}")

    topology_file = os.path.join(get_maps_dir(), map_name, 'topology.json')
    with open(topology_file, 'r') as f:
        return json.load(f)


def load_layout(map_name):
    if not validate_map_name(map_name):
        raise ValueError(f"Invalid map name: {map_name}")

    layout_file = os.path.join(get_maps_dir(), map_name, 'layout.json')
    if os.path.exists(layout_file):
        try:
            with open(layout_file, 'r') as f:
                return json.load(f)
        except:
            return None
    return None


def save_layout(map_name, layout_data):
    if not validate_map_name(map_name):
        raise ValueError(f"Invalid map name: {map_name}")

    map_dir = os.path.join(get_maps_dir(), map_name)
    os.makedirs(map_dir, exist_ok=True)

    layout_file = os.path.join(map_dir, 'layout.json')
    layout_data['map_name'] = map_name
    layout_data['server_timestamp'] = datetime.now().isoformat()

    with open(layout_file, 'w') as f:
        json.dump(layout_data, f, indent=2)
    return True


def load_icon_map():
    icon_map_file = get_icon_map_file()
    try:
        with open(icon_map_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            'defaults': {'default_unknown': 'cloud_(4).jpg'},
            'platform_patterns': {},
            'fallback_patterns': {}
        }


def get_icon_for_platform(platform, icon_map, device_name=''):
    if not platform:
        return icon_map['defaults']['default_unknown']

    for pattern, icon in icon_map.get('platform_patterns', {}).items():
        if pattern.lower() in platform.lower():
            return icon

    platform_lower = platform.lower()
    device_name_lower = device_name.lower() if device_name else ''

    for device_type, rules in icon_map.get('fallback_patterns', {}).items():
        for pattern in rules.get('platform_patterns', []):
            if pattern.lower() in platform_lower:
                icon_key = rules.get('icon', 'default_unknown')
                return icon_map['defaults'].get(icon_key, 'cloud_(4).jpg')

        if device_name_lower:
            for pattern in rules.get('name_patterns', []):
                if pattern.lower() in device_name_lower:
                    icon_key = rules.get('icon', 'default_unknown')
                    return icon_map['defaults'].get(icon_key, 'cloud_(4).jpg')

    return icon_map['defaults'].get('default_unknown', 'cloud_(4).jpg')


def convert_to_cytoscape(topology_data, icon_map):
    """Convert topology data to Cytoscape format.

    Supports both SecureCartography format (with 'node_details' and 'peers')
    and simpler formats with direct device properties.
    """
    nodes = []
    edges = []
    edge_set = set()
    node_set = set()

    # First pass: create nodes from main devices
    for device_name, device_data in topology_data.items():
        # Handle SecureCartography format
        if 'node_details' in device_data:
            node_details = device_data['node_details']
            platform = node_details.get('platform', 'Unknown')
            ip = node_details.get('ip', '')
        else:
            # Handle simpler format
            platform = device_data.get('platform', 'Unknown')
            ip = device_data.get('ip', '')

        icon_file = get_icon_for_platform(platform, icon_map, device_name)
        icon_url = get_icon_url(icon_file)

        nodes.append({
            'data': {
                'id': device_name,
                'label': device_name,
                'ip': ip,
                'platform': platform,
                'icon': icon_url
            }
        })
        node_set.add(device_name)

    # Second pass: create edges and missing peer nodes
    for device_name, device_data in topology_data.items():
        peers = device_data.get('peers', {})

        for peer_name, peer_info in peers.items():
            # Skip empty or invalid peer names
            if not peer_name or not peer_name.strip():
                current_app.logger.warning(f"Skipping peer with empty name for device {device_name}")
                continue

            # Add peer node if not already present
            if peer_name not in node_set:
                peer_platform = peer_info.get('platform', 'Unknown')
                peer_ip = peer_info.get('ip', '')
                icon_file = get_icon_for_platform(peer_platform, icon_map, peer_name)
                icon_url = get_icon_url(icon_file)

                nodes.append({
                    'data': {
                        'id': peer_name,
                        'label': peer_name,
                        'ip': peer_ip,
                        'platform': peer_platform,
                        'icon': icon_url
                    }
                })
                node_set.add(peer_name)

            # Create edges
            connections = peer_info.get('connections', [])

            if connections:
                # SecureCartography format with connections array
                for connection in connections:
                    local_int = connection[0] if len(connection) > 0 else ''
                    remote_int = connection[1] if len(connection) > 1 else ''

                    edge_id = f"{device_name}--{peer_name}--{local_int}--{remote_int}"
                    reverse_edge_id = f"{peer_name}--{device_name}--{remote_int}--{local_int}"

                    if edge_id not in edge_set and reverse_edge_id not in edge_set:
                        # ✅ FIX: Added label property here
                        edges.append({
                            'data': {
                                'id': edge_id,
                                'source': device_name,
                                'target': peer_name,
                                'local_interface': local_int,
                                'remote_interface': remote_int,
                                'label': f"{local_int} ↔ {remote_int}" if local_int and remote_int else ''
                            }
                        })
                        edge_set.add(edge_id)
            else:
                # Simple format - just create edge without interface details
                local_int = peer_info.get('local_interface', '')
                remote_int = peer_info.get('remote_interface', '')

                edge_id = f"{device_name}--{peer_name}"
                reverse_edge_id = f"{peer_name}--{device_name}"

                if edge_id not in edge_set and reverse_edge_id not in edge_set:
                    # ✅ FIX: Added label property here too
                    edges.append({
                        'data': {
                            'id': edge_id,
                            'source': device_name,
                            'target': peer_name,
                            'local_interface': local_int,
                            'remote_interface': remote_int,
                            'label': f"{local_int} ↔ {remote_int}" if local_int and remote_int else ''
                        }
                    })
                    edge_set.add(edge_id)

    return {'nodes': nodes, 'edges': edges}


@scmaps_bp.route('/')
def index():
    return render_template('scmaps/index.html')


@scmaps_bp.route('/api/maps')
def api_list_maps():
    try:
        maps_dir = get_maps_dir()
        current_app.logger.info(f"[SCMAPS DEBUG] Maps directory: {maps_dir}")
        current_app.logger.info(f"[SCMAPS DEBUG] Directory exists: {os.path.exists(maps_dir)}")

        if os.path.exists(maps_dir):
            contents = os.listdir(maps_dir)
            current_app.logger.info(f"[SCMAPS DEBUG] Directory contents: {contents}")

        maps = list_available_maps()
        current_app.logger.info(f"[SCMAPS DEBUG] Found {len(maps)} maps: {[m['name'] for m in maps]}")

        return jsonify({
            'success': True,
            'maps': maps
        })
    except Exception as e:
        current_app.logger.error(f"Error listing maps: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@scmaps_bp.route('/api/maps/<map_name>')
def api_get_map(map_name):
    try:
        topology = load_topology(map_name)
        layout = load_layout(map_name)
        icon_map = load_icon_map()
        cytoscape_data = convert_to_cytoscape(topology, icon_map)

        return jsonify({
            'success': True,
            'map_name': map_name,
            'data': cytoscape_data,
            'saved_layout': layout,
            'topology': topology
        })
    except FileNotFoundError:
        return jsonify({
            'success': False,
            'error': 'Map not found'
        }), 404
    except Exception as e:
        current_app.logger.error(f"Error loading map {map_name}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@scmaps_bp.route('/api/maps/<map_name>/layout', methods=['POST'])
def api_save_layout(map_name):
    try:
        layout_data = request.json
        save_layout(map_name, layout_data)
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error saving layout for {map_name}: {e}")
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/maps/<map_name>/layout', methods=['DELETE'])
def api_delete_layout(map_name):
    try:
        if not validate_map_name(map_name):
            return jsonify({'error': 'Invalid map name'}), 400

        layout_file = os.path.join(get_maps_dir(), map_name, 'layout.json')
        if os.path.exists(layout_file):
            os.remove(layout_file)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/maps/<map_name>/topology', methods=['POST'])
def api_save_topology(map_name):
    try:
        if not validate_map_name(map_name):
            return jsonify({'error': 'Invalid map name'}), 400

        topology_data = request.json
        map_dir = os.path.join(get_maps_dir(), map_name)
        os.makedirs(map_dir, exist_ok=True)

        topology_file = os.path.join(map_dir, 'topology.json')
        with open(topology_file, 'w') as f:
            json.dump(topology_data, f, indent=2)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/maps/upload', methods=['POST'])
def api_upload_map():
    """Upload a new topology file or JSON data"""
    try:
        current_app.logger.info(f"[SCMAPS DEBUG] Upload request received")
        current_app.logger.info(f"[SCMAPS DEBUG] Content-Type: {request.content_type}")
        current_app.logger.info(f"[SCMAPS DEBUG] Has files: {bool(request.files)}")
        current_app.logger.info(f"[SCMAPS DEBUG] Is JSON: {request.is_json}")

        # Check if it's a file upload or JSON data
        if request.files and 'file' in request.files:
            # Handle file upload
            file = request.files['file']
            map_name = request.form.get('map_name', '')

            current_app.logger.info(f"[SCMAPS DEBUG] File upload: {file.filename}, map_name: {map_name}")

            if not map_name:
                # Generate map name from filename
                map_name = os.path.splitext(secure_filename(file.filename))[0]
                current_app.logger.info(f"[SCMAPS DEBUG] Generated map_name: {map_name}")

            if not validate_map_name(map_name):
                return jsonify({'success': False, 'error': 'Invalid map name'}), 400

            # Read and parse the file
            try:
                content = file.read().decode('utf-8')
                topology = json.loads(content)
            except json.JSONDecodeError as e:
                return jsonify({'error': f'Invalid JSON file: {str(e)}'}), 400
            except UnicodeDecodeError:
                return jsonify({'error': 'File must be UTF-8 encoded'}), 400

        elif request.is_json:
            # Handle JSON POST data
            data = request.json
            map_name = data.get('map_name')
            topology = data.get('topology')

            if not map_name or not topology:
                return jsonify({'error': 'Missing map_name or topology'}), 400

            if not validate_map_name(map_name):
                return jsonify({'error': 'Invalid map name'}), 400
        else:
            return jsonify({'error': 'No file or JSON data provided'}), 400

        # Save the topology
        map_dir = os.path.join(get_maps_dir(), map_name)
        os.makedirs(map_dir, exist_ok=True)

        topology_file = os.path.join(map_dir, 'topology.json')
        with open(topology_file, 'w') as f:
            json.dump(topology, f, indent=2)

        # Count devices
        device_count = len(topology) if isinstance(topology, dict) else 0

        current_app.logger.info(f"[SCMAPS DEBUG] Uploaded map: {map_name} with {device_count} devices")
        return jsonify({
            'success': True,
            'map_name': map_name,
            'device_count': device_count,
            'message': f'Map "{map_name}" uploaded successfully'
        })

    except Exception as e:
        current_app.logger.error(f"[SCMAPS DEBUG] Error uploading map: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@scmaps_bp.route('/api/maps/<map_name>', methods=['DELETE'])
def api_delete_map(map_name):
    try:
        if not validate_map_name(map_name):
            return jsonify({'error': 'Invalid map name'}), 400

        map_dir = os.path.join(get_maps_dir(), map_name)
        if os.path.exists(map_dir):
            import shutil
            shutil.rmtree(map_dir)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/maps/<map_name>/rename', methods=['PUT'])
def api_rename_map(map_name):
    try:
        new_name = request.json.get('new_name')
        if not validate_map_name(map_name) or not validate_map_name(new_name):
            return jsonify({'error': 'Invalid map name'}), 400

        old_dir = os.path.join(get_maps_dir(), map_name)
        new_dir = os.path.join(get_maps_dir(), new_name)

        if os.path.exists(new_dir):
            return jsonify({'error': 'Map already exists'}), 400

        os.rename(old_dir, new_dir)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/maps/<map_name>/copy', methods=['POST'])
def api_copy_map(map_name):
    try:
        new_name = request.json.get('new_name')
        if not validate_map_name(map_name) or not validate_map_name(new_name):
            return jsonify({'error': 'Invalid map name'}), 400

        old_dir = os.path.join(get_maps_dir(), map_name)
        new_dir = os.path.join(get_maps_dir(), new_name)

        if os.path.exists(new_dir):
            return jsonify({'error': 'Map already exists'}), 400

        import shutil
        shutil.copytree(old_dir, new_dir)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/maps/<map_name>/export')
def api_export_topology(map_name):
    try:
        topology = load_topology(map_name)
        return jsonify(topology)
    except FileNotFoundError:
        return jsonify({'error': 'Map not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@scmaps_bp.route('/api/export/graphml', methods=['POST'])
def export_graphml():
    try:
        current_app.logger.info("[EXPORT] GraphML export request received")

        # Check if exporter is available
        if not NetworkGraphMLExporter:
            current_app.logger.error("[EXPORT] NetworkGraphMLExporter not available")
            return jsonify({'error': 'GraphML exporter not available'}), 500

        # Get request data
        data = request.json
        if not data:
            current_app.logger.error("[EXPORT] No JSON data in request")
            return jsonify({'error': 'No data provided'}), 400

        current_app.logger.info(f"[EXPORT] Request data: {data}")

        map_name = data.get('map_name')
        if not map_name:
            current_app.logger.error("[EXPORT] No map_name provided")
            return jsonify({'error': 'map_name is required'}), 400

        layout = data.get('layout', 'tree')
        include_endpoints = data.get('include_endpoints', True)

        current_app.logger.info(f"[EXPORT] Loading topology for map: {map_name}")

        # Load topology data
        try:
            network_data = load_topology(map_name)
            current_app.logger.info(f"[EXPORT] Loaded topology with {len(network_data)} devices")
        except FileNotFoundError as e:
            current_app.logger.error(f"[EXPORT] Map not found: {map_name}")
            return jsonify({'error': f'Map "{map_name}" not found'}), 404
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error loading topology: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            return jsonify({'error': f'Error loading topology: {str(e)}'}), 500

        # Create temp file
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.graphml', delete=False) as tmp:
                tmp_path = tmp.name
            current_app.logger.info(f"[EXPORT] Created temp file: {tmp_path}")
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error creating temp file: {e}")
            return jsonify({'error': f'Error creating temp file: {str(e)}'}), 500

        # Initialize exporter
        try:
            icons_dir = get_icons_dir()
            current_app.logger.info(f"[EXPORT] Icons directory: {icons_dir}")

            exporter = NetworkGraphMLExporter(
                include_endpoints=include_endpoints,
                use_icons=True,
                layout_type=layout,
                icons_dir=icons_dir
            )
            current_app.logger.info("[EXPORT] Exporter initialized")
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error initializing exporter: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            try:
                os.unlink(tmp_path)
            except:
                pass
            return jsonify({'error': f'Error initializing exporter: {str(e)}'}), 500

        # Export to GraphML
        try:
            current_app.logger.info("[EXPORT] Starting GraphML export")
            exporter.export_to_graphml(network_data, tmp_path)
            current_app.logger.info("[EXPORT] GraphML export completed")
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error during export: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            try:
                os.unlink(tmp_path)
            except:
                pass
            return jsonify({'error': f'Error during export: {str(e)}'}), 500

        # Send file
        try:
            current_app.logger.info(f"[EXPORT] Sending file: {tmp_path}")
            response = send_file(
                tmp_path,
                mimetype='application/xml',
                as_attachment=True,
                download_name=f'{map_name}.graphml'
            )

            @response.call_on_close
            def cleanup():
                try:
                    os.unlink(tmp_path)
                    current_app.logger.info(f"[EXPORT] Cleaned up temp file: {tmp_path}")
                except Exception as e:
                    current_app.logger.warning(f"[EXPORT] Error cleaning up temp file: {e}")

            current_app.logger.info("[EXPORT] GraphML export successful")
            return response

        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error sending file: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            try:
                os.unlink(tmp_path)
            except:
                pass
            return jsonify({'error': f'Error sending file: {str(e)}'}), 500

    except Exception as e:
        current_app.logger.error(f"[EXPORT] Unexpected error in export_graphml: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@scmaps_bp.route('/api/export/drawio', methods=['POST'])
def export_drawio():
    try:
        current_app.logger.info("[EXPORT] DrawIO export request received")

        # Check if exporter is available
        if not NetworkDrawioExporter:
            current_app.logger.error("[EXPORT] NetworkDrawioExporter not available")
            return jsonify({'error': 'DrawIO exporter not available'}), 500

        # Get request data
        data = request.json
        if not data:
            current_app.logger.error("[EXPORT] No JSON data in request")
            return jsonify({'error': 'No data provided'}), 400

        current_app.logger.info(f"[EXPORT] Request data: {data}")

        map_name = data.get('map_name')
        if not map_name:
            current_app.logger.error("[EXPORT] No map_name provided")
            return jsonify({'error': 'map_name is required'}), 400

        layout = data.get('layout', 'tree')
        include_endpoints = data.get('include_endpoints', True)

        current_app.logger.info(f"[EXPORT] Loading topology for map: {map_name}")

        # Load topology data
        try:
            network_data = load_topology(map_name)
            current_app.logger.info(f"[EXPORT] Loaded topology with {len(network_data)} devices")
        except FileNotFoundError as e:
            current_app.logger.error(f"[EXPORT] Map not found: {map_name}")
            return jsonify({'error': f'Map "{map_name}" not found'}), 404
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error loading topology: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            return jsonify({'error': f'Error loading topology: {str(e)}'}), 500

        # Create temp file
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.drawio', delete=False) as tmp:
                tmp_path = tmp.name
            current_app.logger.info(f"[EXPORT] Created temp file: {tmp_path}")
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error creating temp file: {e}")
            return jsonify({'error': f'Error creating temp file: {str(e)}'}), 500

        # Initialize exporter
        try:
            icons_dir = get_icons_dir()
            current_app.logger.info(f"[EXPORT] Icons directory: {icons_dir}")

            exporter = NetworkDrawioExporter(
                include_endpoints=include_endpoints,
                use_icons=True,
                layout_type=layout,
                icons_dir=icons_dir
            )
            current_app.logger.info("[EXPORT] Exporter initialized")
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error initializing exporter: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            try:
                os.unlink(tmp_path)
            except:
                pass
            return jsonify({'error': f'Error initializing exporter: {str(e)}'}), 500

        # Export to DrawIO
        try:
            current_app.logger.info("[EXPORT] Starting DrawIO export")
            exporter.export_to_drawio(network_data, tmp_path)
            current_app.logger.info("[EXPORT] DrawIO export completed")
        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error during export: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            try:
                os.unlink(tmp_path)
            except:
                pass
            return jsonify({'error': f'Error during export: {str(e)}'}), 500

        # Send file
        try:
            current_app.logger.info(f"[EXPORT] Sending file: {tmp_path}")
            response = send_file(
                tmp_path,
                mimetype='application/xml',
                as_attachment=True,
                download_name=f'{map_name}.drawio'
            )

            @response.call_on_close
            def cleanup():
                try:
                    os.unlink(tmp_path)
                    current_app.logger.info(f"[EXPORT] Cleaned up temp file: {tmp_path}")
                except Exception as e:
                    current_app.logger.warning(f"[EXPORT] Error cleaning up temp file: {e}")

            current_app.logger.info("[EXPORT] DrawIO export successful")
            return response

        except Exception as e:
            current_app.logger.error(f"[EXPORT] Error sending file: {e}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            try:
                os.unlink(tmp_path)
            except:
                pass
            return jsonify({'error': f'Error sending file: {str(e)}'}), 500

    except Exception as e:
        current_app.logger.error(f"[EXPORT] Unexpected error in export_drawio: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@scmaps_bp.route('/api/diagnostics')
def api_diagnostics():
    maps_dir = get_maps_dir()
    icons_dir = get_icons_dir()

    diagnostics = {
        'workspace': {
            'path': maps_dir,
            'exists': os.path.exists(maps_dir),
            'map_count': 0,
            'maps': []
        },
        'icons_directory': {
            'path': icons_dir,
            'exists': os.path.exists(icons_dir),
            'icon_count': 0
        }
    }

    if os.path.exists(maps_dir):
        maps = list_available_maps()
        diagnostics['workspace']['map_count'] = len(maps)
        diagnostics['workspace']['maps'] = maps

    if os.path.exists(icons_dir):
        icon_files = [f for f in os.listdir(icons_dir) if f.endswith(('.jpg', '.png', '.gif', '.svg'))]
        diagnostics['icons_directory']['icon_count'] = len(icon_files)

    return jsonify(diagnostics)