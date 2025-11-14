# app/blueprints/auth/__init__.py
from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

# Import routes after blueprint creation to avoid circular imports
from . import routes