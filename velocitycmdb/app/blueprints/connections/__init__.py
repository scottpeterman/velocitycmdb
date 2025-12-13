# app/blueprints/connections/__init__.py
from flask import Blueprint

connections_bp = Blueprint('connections', __name__, url_prefix='/connections')

from . import routes
