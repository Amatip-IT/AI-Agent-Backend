from datetime import datetime
from . import db

messages = db.messages

def add_message(chat_id: str, role: str, content: str):
    doc = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "created_at": datetime.utcnow()
    }
    result = messages.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc

def get_history(chat_id: str):
    cursor = messages.find({"chat_id": chat_id}).sort("created_at", 1)
    return [{"role": m["role"], "content": m["content"]} for m in cursor]

def get_messages(chat_id: str):
    cursor = messages.find({"chat_id": chat_id}).sort("created_at", 1)
    return [{
        "id": str(m["_id"]),
        "role": m["role"],
        "content": m["content"],
        "created_at": m["created_at"].isoformat()
    } for m in cursor]