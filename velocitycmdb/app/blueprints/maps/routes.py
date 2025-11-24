# app/blueprints/maps/__init__.py
from flask import Blueprint

maps_bp = Blueprint('maps', __name__, url_prefix='/maps')

from . import routes

# app/blueprints/maps/routes.py
import os
from pathlib import Path
from flask import render_template, send_file, current_app, abort, jsonify
from datetime import datetime
from typing import Dict, List, Any

from . import maps_bp


class MapScanner:
    """Scans and manages network topology maps"""

    def __init__(self, maps_base_dir: str = None):
        """
        Initialize MapScanner with configurable maps directory.

        Priority:
        1. Explicit maps_base_dir parameter
        2. Flask app config DATA_DIR + 'maps'
        3. ~/.velocitycmdb/data/maps (default)
        """
        if maps_base_dir and os.path.isabs(maps_base_dir):
            self.maps_base_dir = Path(maps_base_dir)
        else:
            # Try to get from Flask config first
            try:
                data_dir = current_app.config.get('DATA_DIR')
                if data_dir:
                    self.maps_base_dir = Path(data_dir) / 'maps'
                else:
                    # Fallback to default location
                    self.maps_base_dir = Path.home() / '.velocitycmdb' / 'data' / 'maps'
            except RuntimeError:
                # Outside Flask context, use default
                self.maps_base_dir = Path.home() / '.velocitycmdb' / 'data' / 'maps'

        # Ensure directory exists
        self.maps_base_dir.mkdir(parents=True, exist_ok=True)
        print(f"MAPS BASE: {self.maps_base_dir}")

    def scan_maps(self) -> Dict[str, Any]:
        """Scan maps directory and return organized map data"""
        maps_data = {
            'sites': {},
            'total_maps': 0,
            'last_updated': None
        }

        if not self.maps_base_dir.exists():
            return maps_data

        latest_time = None

        # Scan each site folder
        for site_dir in self.maps_base_dir.iterdir():
            if not site_dir.is_dir():
                continue

            # Skip the thumbnails directory
            if site_dir.name == 'thumbnails':
                continue

            site_name = site_dir.name
            site_maps = self.scan_site_maps(site_dir)

            if site_maps['maps']:
                maps_data['sites'][site_name] = site_maps
                maps_data['total_maps'] += len(site_maps['maps'])

                # Track latest modification time
                if site_maps['last_modified']:
                    if latest_time is None or site_maps['last_modified'] > latest_time:
                        latest_time = site_maps['last_modified']

        maps_data['last_updated'] = latest_time
        return maps_data

    def scan_site_maps(self, site_dir: Path) -> Dict[str, Any]:
        """Scan a single site directory for maps"""
        site_data = {
            'maps': [],
            'last_modified': None
        }

        # Group files by map name (without extension)
        map_groups = {}

        for file_path in site_dir.iterdir():
            if not file_path.is_file():
                continue

            name_without_ext = file_path.stem
            ext = file_path.suffix.lower()

            if ext in ['.svg', '.json', '.graphml', '.drawio']:
                if name_without_ext not in map_groups:
                    map_groups[name_without_ext] = {
                        'name': name_without_ext,
                        'files': {},
                        'created': None,
                        'size_mb': 0
                    }

                # Get file info
                stat = file_path.stat()
                creation_time = datetime.fromtimestamp(stat.st_mtime)
                size_bytes = stat.st_size

                map_groups[name_without_ext]['files'][ext] = {
                    'path': str(file_path),
                    'relative_path': str(file_path.relative_to(self.maps_base_dir)),
                    'size_bytes': size_bytes,
                    'created': creation_time
                }

                # Track total size and latest creation time
                map_groups[name_without_ext]['size_mb'] += size_bytes / (1024 * 1024)

                if (map_groups[name_without_ext]['created'] is None or
                        creation_time > map_groups[name_without_ext]['created']):
                    map_groups[name_without_ext]['created'] = creation_time

                # Track site's latest modification
                if (site_data['last_modified'] is None or
                        creation_time > site_data['last_modified']):
                    site_data['last_modified'] = creation_time

        # FILTER OUT EMPTY MAPS - Only include maps that have files and non-zero size
        valid_maps = [
            map_data for map_data in map_groups.values()
            if (
                    '.svg' in map_data['files'] and
                    map_data['size_mb'] >= 0.01  # Total size must be at least 10KB
            )
        ]

        # Convert to list and sort by creation time
        site_data['maps'] = sorted(valid_maps,
                                   key=lambda x: x['created'] or datetime.min,
                                   reverse=True)

        return site_data

    def get_map_metadata(self, site_name: str, map_name: str) -> Dict[str, Any]:
        """Get detailed metadata for a specific map"""
        site_dir = self.maps_base_dir / site_name
        if not site_dir.exists():
            return None

        site_maps = self.scan_site_maps(site_dir)

        for map_data in site_maps['maps']:
            if map_data['name'] == map_name:
                # Add device count from JSON if available
                json_file = site_dir / f"{map_name}.json"
                if json_file.exists():
                    try:
                        import json
                        with open(json_file, 'r') as f:
                            topology_data = json.load(f)
                        map_data['device_count'] = len(topology_data)
                    except:
                        map_data['device_count'] = 0

                return map_data

        return None


@maps_bp.route('/')
def index():
    """Maps overview page"""
    scanner = MapScanner()
    maps_data = scanner.scan_maps()

    return render_template('maps/index.html',
                           maps_data=maps_data,
                           maps_base_dir=str(scanner.maps_base_dir),
                           title="Network Maps")


@maps_bp.route('/site/<site_name>')
def site_maps(site_name):
    """Show maps for a specific site"""
    scanner = MapScanner()
    site_dir = scanner.maps_base_dir / site_name

    if not site_dir.exists():
        abort(404, f"Site '{site_name}' not found")

    site_data = scanner.scan_site_maps(site_dir)

    if not site_data['maps']:
        abort(404, f"No maps found for site '{site_name}'")

    return render_template('maps/site.html',
                           site_name=site_name,
                           site_data=site_data,
                           maps_base_dir=str(scanner.maps_base_dir),
                           title=f"Maps - {site_name}")


@maps_bp.route('/view/<site_name>/<map_name>')
def view_map(site_name, map_name):
    """View a specific map"""
    scanner = MapScanner()
    map_data = scanner.get_map_metadata(site_name, map_name)

    if not map_data:
        abort(404, f"Map '{map_name}' not found in site '{site_name}'")

    return render_template('maps/view.html',
                           site_name=site_name,
                           map_name=map_name,
                           map_data=map_data,
                           maps_base_dir=str(scanner.maps_base_dir),
                           title=f"Map - {site_name}/{map_name}")


@maps_bp.route('/svg/<site_name>/<map_name>')
def serve_svg(site_name, map_name):
    """Serve SVG file directly"""
    scanner = MapScanner()
    svg_path = scanner.maps_base_dir / site_name / f"{map_name}.svg"

    if not svg_path.exists():
        abort(404, "SVG file not found")

    return send_file(svg_path, mimetype='image/svg+xml')


@maps_bp.route('/download/<site_name>/<map_name>/<format>')
def download_map(site_name, map_name, format):
    """Download map in specified format"""
    scanner = MapScanner()

    format_map = {
        'svg': '.svg',
        'json': '.json',
        'graphml': '.graphml',
        'drawio': '.drawio'
    }

    if format not in format_map:
        abort(400, "Invalid format")

    file_path = scanner.maps_base_dir / site_name / f"{map_name}{format_map[format]}"

    if not file_path.exists():
        abort(404, f"{format.upper()} file not found")

    # Set appropriate mimetype
    mimetypes = {
        '.svg': 'image/svg+xml',
        '.json': 'application/json',
        '.graphml': 'application/xml',
        '.drawio': 'application/xml'
    }

    return send_file(file_path,
                     mimetype=mimetypes.get(format_map[format], 'application/octet-stream'),
                     as_attachment=True,
                     download_name=f"{map_name}{format_map[format]}")


@maps_bp.route('/api/maps')
def api_maps():
    """JSON API for maps data"""
    scanner = MapScanner()
    maps_data = scanner.scan_maps()

    # Convert datetime objects to ISO format for JSON serialization
    def convert_dates(obj):
        if isinstance(obj, dict):
            return {k: convert_dates(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_dates(item) for item in obj]
        elif isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    return jsonify(convert_dates(maps_data))


@maps_bp.route('/api/thumbnail/<site_name>/<map_name>')
def api_thumbnail(site_name, map_name):
    """Generate/serve thumbnail for SVG map with caching"""
    scanner = MapScanner()
    svg_path = scanner.maps_base_dir / site_name / f"{map_name}.svg"

    if not svg_path.exists():
        abort(404, "SVG file not found")

    # Create thumbnails directory if it doesn't exist
    thumbnails_dir = scanner.maps_base_dir / 'thumbnails' / site_name
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    thumbnail_path = thumbnails_dir / f"{map_name}_thumb.png"

    # Check if thumbnail exists and is newer than SVG
    if (thumbnail_path.exists() and
            thumbnail_path.stat().st_mtime > svg_path.stat().st_mtime):
        return send_file(thumbnail_path, mimetype='image/png')

    # Generate thumbnail
    try:
        from PIL import Image
        import cairosvg
        import io

        # Convert SVG to PNG in memory
        png_data = cairosvg.svg2png(url=str(svg_path), output_width=300, output_height=200)

        # Use PIL to create thumbnail
        img = Image.open(io.BytesIO(png_data))
        img.thumbnail((300, 200), Image.Resampling.LANCZOS)

        # Save thumbnail to cache
        img.save(thumbnail_path, 'PNG', optimize=True)

        return send_file(thumbnail_path, mimetype='image/png')

    except ImportError:
        # Fallback to serving SVG directly if PIL/cairosvg not available
        current_app.logger.warning("PIL or cairosvg not installed - serving SVG instead of thumbnail")
        return serve_svg(site_name, map_name)
    except Exception as e:
        current_app.logger.error(f"Error generating thumbnail: {str(e)}")
        # Fallback to serving SVG directly
        return serve_svg(site_name, map_name)


# Template context processor for maps
@maps_bp.app_context_processor
def inject_maps_data():
    """Make maps data available to all templates"""
    scanner = MapScanner()
    maps_data = scanner.scan_maps()

    return {
        'maps_summary': {
            'total_sites': len(maps_data['sites']),
            'total_maps': maps_data['total_maps'],
            'last_updated': maps_data['last_updated']
        }
    }