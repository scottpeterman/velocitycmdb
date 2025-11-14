from flask import Blueprint

notes_bp = Blueprint('notes', __name__)

from velocitycmdb.app.blueprints.notes import routes