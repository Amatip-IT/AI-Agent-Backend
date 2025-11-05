from datetime import datetime
from . import db

chats = db.chats

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
    return [{**c, "_id": str(c["_id"]), "created_at": c["created_at"].isoformat()} for c in cursor]

def get_chat(chat_id: str, user_id: str):
    doc = chats.find_one({"_id": chat_id, "user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc