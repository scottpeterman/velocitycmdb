# app/blueprints/components/__init__.py
from flask import Blueprint

components_bp = Blueprint('components', __name__, url_prefix='/components')

# Import routes after blueprint creation to avoid circular imports
from . import routes