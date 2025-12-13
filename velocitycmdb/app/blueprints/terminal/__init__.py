# app/blueprints/terminal/__init__.py
import os

from flask import Blueprint

terminal_bp = Blueprint('terminal', __name__, url_prefix='/terminal')

blueprint_dir = os.path.dirname(os.path.abspath(__file__))
template_folder = os.path.join(blueprint_dir, 'templates')

connections_bp = Blueprint(
    'connections',
    __name__,
    url_prefix='/connections',
    template_folder=template_folder
)

from . import routes