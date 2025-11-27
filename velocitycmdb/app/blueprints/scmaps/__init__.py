# velocitycmdb/app/blueprints/scmaps/__init__.py

from flask import Blueprint

scmaps_bp = Blueprint(
    'scmaps',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/scmaps/static'
)

# Add route for data files
from flask import send_from_directory
import os

@scmaps_bp.route('/data/<path:filename>')
def serve_data(filename):
    """Serve data files like platform_icon_map.json"""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    return send_from_directory(data_dir, filename)

from . import routes