# models/users.py
import bcrypt
from datetime import datetime
from typing import Optional, Dict, Any
from bson import ObjectId
from . import db

users = db.users


def hash_password(pw: str) -> bytes:
    """
    Hash a password using bcrypt.
    Returns bytes, which MongoDB stores as Binary.
    """
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12))


def check_password(stored_hash: bytes, provided_pw: str) -> bool:
    """Verify a password against a stored bcrypt hash."""
    return bcrypt.checkpw(provided_pw.encode("utf-8"), stored_hash)


def _convert_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert ObjectId to string in-place for any user document."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def create_user(username: str, email: str, password: str) -> Dict[str, Any]:
    """Create a new user with hashed password and timestamps."""
    if users.find_one({"$or": [{"username": username}, {"email": email}]}):
        raise ValueError("Username or email already exists")

    user_doc = {
        "username": username,
        "email": email,
        "password_hash": hash_password(password),
        "avatar_url": None,  # optional
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = users.insert_one(user_doc)
    user_doc["_id"] = str(result.inserted_id)
    return user_doc


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve user by string _id."""
    try:
        doc = users.find_one({"_id": ObjectId(user_id)})
        return _convert_id(doc)
    except Exception:
        return None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Retrieve user by username."""
    doc = users.find_one({"username": username})
    return _convert_id(doc)


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieve user by email."""
    doc = users.find_one({"email": email})
    return _convert_id(doc)


def get_user_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    """
    Find user by either username or email in a single query.
    """
    doc = users.find_one(
        {"$or": [{"username": identifier}, {"email": identifier}]}
    )
    return _convert_id(doc)


def verify_login(username: str, password: str) -> bool:
    """Legacy: verify by username only."""
    user = get_user_by_username(username)
    if not user:
        return False
    return check_password(user["password_hash"], password)


def verify_login_by_identifier(identifier: str, password: str) -> bool:
    """Verify login using either username or email."""
    user = get_user_by_identifier(identifier)
    if not user:
        return False
    return check_password(user["password_hash"], password)


def update_profile(
    user_id: str,
    username: Optional[str] = None,
    email: Optional[str] = None,
    avatar_url: Optional[str] = None
) -> bool:
    """
    Update user profile fields.
    Returns True if update was successful.
    """
    update_fields = {"updated_at": datetime.utcnow()}
    if username is not None:
        if users.find_one({"username": username, "_id": {"$ne": ObjectId(user_id)}}):
            raise ValueError("Username already taken")
        update_fields["username"] = username

    if email is not None:
        if users.find_one({"email": email, "_id": {"$ne": ObjectId(user_id)}}):
            raise ValueError("Email already in use")
        update_fields["email"] = email

    if avatar_url is not None:
        update_fields["avatar_url"] = avatar_url

    if len(update_fields) == 1:  # only updated_at
        return True

    result = users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_fields}
    )
    return result.modified_count > 0


def change_password(user_id: str, new_password: str) -> bool:
    """
    Change user password (must be authenticated first).
    Returns True on success.
    """
    hashed = hash_password(new_password)
    result = users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": hashed, "updated_at": datetime.utcnow()}}
    )
    return result.modified_count > 0


def set_avatar_url(user_id: str, avatar_url: Optional[str]) -> bool:
    """
    Set or remove avatar URL.
    Pass None to remove.
    """
    result = users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"avatar_url": avatar_url, "updated_at": datetime.utcnow()}}
    )
    return result.modified_count > 0


def delete_avatar(user_id: str) -> bool:
    """
    Remove avatar URL from user profile.
    """
    return set_avatar_url(user_id, None)