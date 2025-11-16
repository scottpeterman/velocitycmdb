from flask import Blueprint

changes_bp = Blueprint('changes', __name__, template_folder='../../templates/changes')
from . import routes