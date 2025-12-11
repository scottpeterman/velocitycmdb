from flask import Blueprint

ip_locator_bp = Blueprint('ip_locator', __name__,
                          template_folder='templates',
                          url_prefix='/ip-locator')

from . import routes
