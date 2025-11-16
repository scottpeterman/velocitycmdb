# app/blueprints/maps/__init__.py
from flask import Blueprint

maps_bp = Blueprint('maps', __name__, url_prefix='/maps')

from . import routes
