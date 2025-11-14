from flask import Blueprint

vendors_bp = Blueprint('vendors', __name__)

from velocitycmdb.app.blueprints.vendors import routes