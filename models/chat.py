# models/chat.py
from bson import ObjectId
from datetime import datetime
from . import db
from typing import Optional
chats = db.chats
messages = db.messages   # <-- add this line (same DB instance you use elsewhere)


# ----------------------------------------------------------------------
# Existing functions (unchanged)
# ----------------------------------------------------------------------
def create_chat(user_id: str, title: str = "New Chat"):
    doc = {
        "user_id": user_id,
        "title": title,
        "created_at": datetime.utcnow()
    }
    result = chats.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


def get_user_chats(user_id: str):
    cursor = chats.find({"user_id": user_id}).sort("created_at", -1)
    return [
        {**c, "_id": str(c["_id"]), "created_at": c["created_at"].isoformat()}
        for c in cursor
    ]


def get_chat(chat_id: str, user_id: str):
    """Return chat document by ID and user, converting ID properly."""
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        return None

    doc = chats.find_one({"_id": chat_oid, "user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ----------------------------------------------------------------------
# NEW: Delete a chat + cascade its messages
# ----------------------------------------------------------------------
def delete_chat(chat_id: str, user_id: str) -> bool:
    """
    Remove the chat if it belongs to the user.
    All associated messages are also deleted (cascade).
    Returns True on success, False otherwise.
    """
    try:
        chat_oid = ObjectId(chat_id)
    except Exception:
        return False

    # Delete the chat document (owner check)
    result = chats.delete_one({"_id": chat_oid, "user_id": user_id})
    if not result.deleted_count:
        return False

    # Cascade-delete every message in this chat
    messages.delete_many({"chat_id": chat_oid})
    return True


# ----------------------------------------------------------------------
# NEW: Edit a user message (role & content)
# ----------------------------------------------------------------------
def update_message_role_content(
    message_id: str,
    chat_id: str,
    user_id: str,
    role: Optional[str] = None,
    content: Optional[str] = None,
) -> bool:
    """
    Update `role` and/or `content` of a **user** message.
    Only the chat owner can edit a message that belongs to the chat.
    Returns True if the message was modified, False otherwise.
    """
    try:
        msg_oid = ObjectId(message_id)
        chat_oid = ObjectId(chat_id)
    except Exception:
        return False

    # 1. Verify the message exists, is a user message, and belongs to the chat
    msg = messages.find_one(
        {"_id": msg_oid, "chat_id": chat_oid, "role": "user"}
    )
    if not msg:
        return False

    # 2. Verify the chat belongs to the requesting user
    chat = chats.find_one({"_id": chat_oid, "user_id": user_id})
    if not chat:
        return False

    # Build update payload
    update_fields = {}
    if role is not None:
        update_fields["role"] = role
    if content is not None:
        update_fields["content"] = content

    if not update_fields:
        return True  # nothing to change

    # Apply update
    result = messages.update_one(
        {"_id": msg_oid},
        {"$set": update_fields}
    )
    return result.modified_count > 0