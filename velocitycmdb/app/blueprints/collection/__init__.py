from flask import Blueprint

collection_bp = Blueprint('collection', __name__)

from . import routes