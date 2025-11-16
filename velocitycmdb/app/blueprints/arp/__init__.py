# app/blueprints/arp/__init__.py
from flask import Blueprint

arp_bp = Blueprint('arp', __name__, url_prefix='/arp')

from . import routes