# app/blueprints/assets/__init__.py
from flask import Blueprint

assets_bp = Blueprint('assets', __name__, url_prefix='/assets')

# Import routes after blueprint creation to avoid circular imports
from . import routes