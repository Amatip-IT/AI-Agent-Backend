# models/chat.py
from bson import ObjectId
from datetime import datetime
from typing import Optional, List, Dict, Any
from . import db

# Collections
chats = db.chats
messages = db.messages

# ----------------------------------------------------------------------
# CREATE CHAT
# ----------------------------------------------------------------------
def create_chat(user_id: str, title: str = "New Chat") -> Dict[str, Any]:
    doc = {
        "user_id": user_id,
        "title": title.strip(),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = chats.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc

# ----------------------------------------------------------------------
# LIST USER CHATS
# ----------------------------------------------------------------------
def get_user_chats(user_id: str) -> List[Dict[str, Any]]:
    cursor = chats.find({"user_id": user_id}).sort("updated_at", -1)
    result = []

    for c in cursor:
        c["_id"] = str(c["_id"])
        c["created_at"] = c["created_at"].isoformat()

        # Safe updated_at
        if "updated_at" not in c or c["updated_at"] is None:
            updated_at = c["created_at"]
        else:
            updated_at = c["updated_at"]

        c["updated_at"] = (
            updated_at.isoformat()
            if isinstance(updated_at, datetime)
            else updated_at
        )
        result.append(c)

    return result

# ----------------------------------------------------------------------
# GET SINGLE CHAT
# ----------------------------------------------------------------------
def get_chat(chat_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        return None

    doc = chats.find_one({"_id": chat_oid, "user_id": user_id})
    if not doc:
        return None

    doc["_id"] = str(doc["_id"])
    doc["created_at"] = doc["created_at"].isoformat()

    if "updated_at" not in doc or doc["updated_at"] is None:
        doc["updated_at"] = doc["created_at"]
    else:
        doc["updated_at"] = doc["updated_at"].isoformat()

    return doc

# ----------------------------------------------------------------------
# DELETE CHAT + CASCADE
# ----------------------------------------------------------------------
def delete_chat(chat_id: str, user_id: str) -> bool:
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        return False

    result = chats.delete_one({"_id": chat_oid, "user_id": user_id})
    if result.deleted_count == 0:
        return False

    messages.delete_many({"chat_id": chat_oid})
    return True

# ----------------------------------------------------------------------
# UPDATE CHAT TITLE
# ----------------------------------------------------------------------
def update_chat_title(chat_id: str, new_title: str) -> bool:
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        return False

    result = chats.update_one(
        {"_id": chat_oid},
        {"$set": {"title": new_title.strip(), "updated_at": datetime.utcnow()}}
    )
    return result.modified_count > 0

# ----------------------------------------------------------------------
# EDIT USER MESSAGE
# ----------------------------------------------------------------------
def update_message_role_content(
    message_id: str,
    chat_id: str,
    user_id: str,
    role: Optional[str] = None,
    content: Optional[str] = None,
) -> bool:
    try:
        msg_oid = ObjectId(message_id)
        chat_oid = ObjectId(chat_id)
    except Exception:
        return False

    msg = messages.find_one(
        {"_id": msg_oid, "chat_id": chat_oid, "role": "user"}
    )
    if not msg:
        return False

    chat = chats.find_one({"_id": chat_oid, "user_id": user_id})
    if not chat:
        return False

    update_fields = {}
    if role is not None:
        update_fields["role"] = role
    if content is not None:
        update_fields["content"] = content.strip()

    if not update_fields:
        return True

    result = messages.update_one(
        {"_id": msg_oid},
        {"$set": update_fields}
    )
    return result.modified_count > 0