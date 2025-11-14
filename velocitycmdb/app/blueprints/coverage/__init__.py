from flask import Blueprint

coverage_bp = Blueprint('coverage', __name__)

from . import routes