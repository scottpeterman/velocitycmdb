from flask import Blueprint

dashboard_bp = Blueprint('dashboard', __name__)

# Import routes after blueprint creation to avoid circular imports
from . import routes