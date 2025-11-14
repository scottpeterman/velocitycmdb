# app/blueprints/admin/__init__.py
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates')

# Import routes after blueprint creation to avoid circular imports
from . import routes
from .maintenance_routes import *