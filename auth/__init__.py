# auth/__init__.py
from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

# Import routes to register them with blueprint
from . import routes  # This applies decorators