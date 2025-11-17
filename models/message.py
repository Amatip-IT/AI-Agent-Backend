# models/message.py
from datetime import datetime
from . import db

messages = db.messages

def add_message(chat_id: str, role: str, content: str, sources: list = None):
    doc = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "sources": sources or [],
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
        "sources": m.get("sources", []),
        "created_at": m["created_at"].isoformat()
    } for m in cursor]

def update_message_content(message_id: str, content: str, sources: list = None):
    try:
        from bson import ObjectId
        msg_oid = ObjectId(message_id)
    except Exception:
        return False
    
    update_data = {"content": content}
    if sources is not None:
        update_data["sources"] = sources
        
    result = messages.update_one(
        {"_id": msg_oid},
        {"$set": update_data}
    )
    return result.modified_count > 0