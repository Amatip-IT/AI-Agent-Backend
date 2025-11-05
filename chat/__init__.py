# chat/__init__.py
from flask import Blueprint

chat_bp = Blueprint('chat', __name__)

# Import routes to register them with blueprint
from . import routes  # This applies decorators