# auth/routes.py
from . import auth_bp
from flask import request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity,
    get_jwt, unset_jwt_cookies
)
from werkzeug.utils import secure_filename
from bson import ObjectId
from datetime import datetime
import os
import logging

# Import shared mongo
from extensions import mongo

# Import model functions
from models.users import (
    create_user, verify_login_by_identifier,
    get_user_by_identifier, update_profile
)

# Avatar config
UPLOAD_FOLDER = 'static/avatars'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper: get db collections safely
def get_users():
    return mongo.db.users

def get_blacklist():
    return mongo.db.blacklist

# -------------------------------------------------
# Setup Logging
# -------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('auth')

# -------------------------------------------------
# Helper: Log request start
# -------------------------------------------------
def log_request_start():
    client_ip = request.remote_addr
    method = request.method
    path = request.path
    user_agent = request.headers.get('User-Agent', 'Unknown')
    logger.info(f"REQUEST START → {method} {path} | IP: {client_ip} | UA: {user_agent}")

# -------------------------------------------------
# Helper: Log response
# -------------------------------------------------
def log_response(status_code, data=None, error=None):
    method = request.method
    path = request.path
    log_msg = f"RESPONSE → {method} {path} | Status: {status_code}"
    if error:
        log_msg += f" | Error: {error}"
    if data:
        log_msg += f" | Data: {data}"
    logger.info(log_msg)

# -------------------------------------------------
# 1. Register → POST /auth/register
# -------------------------------------------------
@auth_bp.route('/auth/register', methods=['POST'])
def register():
    log_request_start()
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not all([username, email, password]):
        error = "All fields are required"
        log_response(400, error=error)
        return jsonify({"error": error}), 400

    try:
        create_user(username, email, password)
        log_response(201, data={"message": "User created successfully"})
        return jsonify({"message": "User created successfully"}), 201
    except ValueError as e:
        error = str(e)
        log_response(400, error=error)
        return jsonify({"error": error}), 400
    except Exception as e:
        error = f"Unexpected error: {str(e)}"
        logger.error(error)
        log_response(500, error=error)
        return jsonify({"error": "Internal server error"}), 500


# In auth/routes.py - Update the login route
@auth_bp.route('/auth/login', methods=['POST'])
def login():
    log_request_start()
    
    data = request.get_json(force=True, silent=True)
    if data is None:
        data = {}
    
    logger.info(f"Login attempt - Received data: {data}")
    
    # ACCEPT MULTIPLE FIELD NAME VARIATIONS
    identifier = (
        data.get('username_or_email') or 
        data.get('identifier') or 
        data.get('username') or 
        data.get('email')
    )
    password = data.get('password')

    if not identifier or not password:
        error = "Identifier and password are required"
        logger.warning(f"Login failed - Missing fields. Identifier: {bool(identifier)}, Password: {bool(password)}")
        log_response(400, error=error)
        return jsonify({"error": error}), 400

    try:
        if verify_login_by_identifier(identifier, password):
            user = get_user_by_identifier(identifier)
            token = create_access_token(identity=str(user["_id"]))
            log_response(200, data={"message": "Login successful", "user_id": str(user["_id"])})
            return jsonify({
                "access_token": token,
                "message": "Login successful"
            }), 200

        error = "Invalid credentials"
        log_response(401, error=error)
        return jsonify({"error": error}), 401
        
    except Exception as e:
        error = f"Login error: {str(e)}"
        logger.error(error)
        log_response(500, error=error)
        return jsonify({"error": "Internal server error"}), 500
# -------------------------------------------------
# 3. Logout → POST /auth/logout
# -------------------------------------------------
@auth_bp.route('/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    log_request_start()
    try:
        jti = get_jwt()["jti"]
        exp = get_jwt()["exp"]
        user_id = get_jwt_identity()

        get_blacklist().insert_one({
            "jti": jti,
            "expires_at": datetime.fromtimestamp(exp),
            "revoked_at": datetime.utcnow(),
            "user_id": user_id
        })

        response = jsonify({"message": "Logout successful"})
        unset_jwt_cookies(response)
        log_response(200, data={"message": "Logout successful", "user_id": user_id})
        return response, 200

    except Exception as e:
        error = f"Logout failed: {str(e)}"
        logger.error(error)
        log_response(500, error=error)
        return jsonify({"error": "Logout failed"}), 500


# -------------------------------------------------
# 4. Get Profile → GET /auth/profile
# -------------------------------------------------
@auth_bp.route('/auth/profile', methods=['GET'])
@jwt_required()
def get_profile():
    log_request_start()
    try:
        user_id = get_jwt_identity()
        user = get_users().find_one({"_id": ObjectId(user_id)})

        if not user:
            error = "User not found"
            log_response(404, error=error)
            return jsonify({"error": error}), 404

        user["_id"] = str(user["_id"])
        user.pop("password_hash", None)
        log_response(200, data={"user_id": user["_id"], "username": user.get("username")})
        return jsonify(user), 200

    except Exception as e:
        error = f"Profile fetch failed: {str(e)}"
        logger.error(error)
        log_response(500, error=error)
        return jsonify({"error": "Internal server error"}), 500


# -------------------------------------------------
# 5. Edit Profile → PUT /auth/profile
# -------------------------------------------------
@auth_bp.route('/auth/profile', methods=['PUT'])
@jwt_required()
def edit_profile():
    log_request_start()
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    email = data.get("email")

    try:
        update_profile(user_id, username=username, email=email)
        log_response(200, data={"message": "Profile updated", "user_id": user_id})
        return jsonify({"message": "Profile updated successfully"}), 200
    except ValueError as e:
        error = str(e)
        log_response(400, error=error)
        return jsonify({"error": error}), 400
    except Exception as e:
        error = f"Profile update failed: {str(e)}"
        logger.error(error)
        log_response(500, error=error)
        return jsonify({"error": "Internal server error"}), 500


# -------------------------------------------------
# 6. Upload Avatar → POST /auth/profile/avatar
# -------------------------------------------------
@auth_bp.route('/auth/profile/avatar', methods=['POST'])
@jwt_required()
def upload_avatar():
    log_request_start()
    user_id = get_jwt_identity()

    if 'avatar' not in request.files:
        error = "No file part"
        log_response(400, error=error)
        return jsonify({"error": error}), 400

    file = request.files['avatar']
    if file.filename == '' or not allowed_file(file.filename):
        error = "Invalid file"
        log_response(400, error=error)
        return jsonify({"error": error}), 400

    try:
        filename = secure_filename(f"{user_id}_{file.filename}")
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        avatar_url = f"/static/avatars/{filename}"
        get_users().update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"avatar_url": avatar_url, "updated_at": datetime.utcnow()}}
        )

        log_response(200, data={"avatar_url": avatar_url, "user_id": user_id})
        return jsonify({"avatar_url": avatar_url}), 200

    except Exception as e:
        error = f"Avatar upload failed: {str(e)}"
        logger.error(error)
        log_response(500, error=error)
        return jsonify({"error": "Upload failed"}), 500