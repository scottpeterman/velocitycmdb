# app/blueprints/capture/__init__.py
from flask import Blueprint

capture_bp = Blueprint('capture', __name__, url_prefix='/capture')

from . import routes