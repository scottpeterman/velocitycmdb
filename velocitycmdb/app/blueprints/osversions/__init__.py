# app/blueprints/osversions/__init__.py
from flask import Blueprint

osversions_bp = Blueprint('osversions', __name__, url_prefix='/osversions')

from . import routes