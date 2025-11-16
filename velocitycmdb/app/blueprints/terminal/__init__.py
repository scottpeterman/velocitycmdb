# app/blueprints/terminal/__init__.py
from flask import Blueprint

terminal_bp = Blueprint('terminal', __name__, url_prefix='/terminal')

from . import routes