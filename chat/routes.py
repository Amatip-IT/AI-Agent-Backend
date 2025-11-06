# chat/routes.py
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from openai import OpenAI, APIError, AuthenticationError, RateLimitError
from config import Config
from . import chat_bp
from models.chat import create_chat, get_user_chats, get_chat, delete_chat, update_message_role_content
from models.message import add_message, get_history, get_messages

# ----------------------------------------------------------------------
# DeepSeek client – one instance for the whole module
# ----------------------------------------------------------------------
client = OpenAI(
    api_key=Config.DEEPSEEK_API_KEY,
    base_url=Config.DEEPSEEK_BASE_URL,
    timeout=30,                 # prevent hanging forever
    max_retries=2               # retry on transient network errors
)
MODEL = "deepseek-chat"


# ----------------------------------]------------------------------------
# CREATE CHAT
# ----------------------------------------------------------------------
# chat/routes.py
@chat_bp.route('/api/chats', methods=['POST'])
@jwt_required()
def new_chat():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    title = data.get('title', 'New Chat')
    initial_message = data.get('message')  
    
    chat = create_chat(user_id, title)
    chat_id = chat["_id"]
    
    # NEW: If initial message provided, send it and get AI response
    if initial_message:
        # Store user message
        add_message(chat_id, "user", initial_message)
        
        # Build conversation history
        history = get_history(chat_id)
        
        # Call DeepSeek
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."}
                ] + history,
                max_tokens=1000,
                temperature=0.7,
                stream=False
            )
            reply = completion.choices[0].message.content.strip()
            
            # Store assistant reply
            add_message(chat_id, "assistant", reply)
            
            return jsonify({
                "id": chat_id,
                "title": chat["title"],
                "initial_response": reply  # Include AI response
            }), 201
            
        except AuthenticationError:
            return jsonify({"error": "Invalid DeepSeek API key"}), 401
        except RateLimitError:
            return jsonify({"error": "DeepSeek rate-limit exceeded"}), 429
        except APIError as e:
            return jsonify({"error": f"DeepSeek API error: {e}"}), 502
        except Exception as e:
            return jsonify({"error": f"Unexpected error: {e}"}), 500
    
    # No initial message - just return the chat
    return jsonify({"id": chat_id, "title": chat["title"]}), 201

# ----------------------------------------------------------------------
# LIST CHATS
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats', methods=['GET'])
@jwt_required()
def list_chats():
    user_id = get_jwt_identity()
    return jsonify(get_user_chats(user_id))


# ----------------------------------------------------------------------
# SEND MESSAGE (talk to DeepSeek)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>/messages', methods=['POST'])
@jwt_required()
def send_message(chat_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    content = payload.get('content')

    if not content:
        return jsonify({"error": "Field `content` is required"}), 400

    # ---- verify ownership ------------------------------------------------
    if not get_chat(chat_id, user_id):
        return jsonify({"error": "Chat not found or not owned by you"}), 404

    # ---- store user message ---------------------------------------------
    add_message(chat_id, "user", content)

    # ---- build conversation history --------------------------------------
    history = get_history(chat_id)

    # ---- call DeepSeek ----------------------------------------------------
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."}
            ] + history,
            max_tokens=1000,
            temperature=0.7,
            stream=False          # set True later if you want streaming
        )
        # DeepSeek follows the OpenAI schema → choices[0].message.content
        reply = completion.choices[0].message.content.strip()

    except AuthenticationError:
        return jsonify({"error": "Invalid DeepSeek API key"}), 401
    except RateLimitError:
        return jsonify({"error": "DeepSeek rate-limit exceeded"}), 429
    except APIError as e:
        return jsonify({"error": f"DeepSeek API error: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    # ---- store assistant reply -------------------------------------------
    add_message(chat_id, "assistant", reply)

    return jsonify({"content": reply}), 200


# ----------------------------------------------------------------------
# GET MESSAGES (conversation history)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>/messages', methods=['GET'])
@jwt_required()
def list_messages(chat_id):
    user_id = get_jwt_identity()
    if not get_chat(chat_id, user_id):
        return jsonify({"error": "Chat not found or not owned by you"}), 404
    return jsonify(get_messages(chat_id))



# ----------------------------------------------------------------------
# DELETE CHAT (and cascade its messages)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>', methods=['DELETE'])
@jwt_required()
def delete_chat_endpoint(chat_id):
    user_id = get_jwt_identity()

    # Verify ownership & delete
    if not delete_chat(chat_id, user_id):
        return jsonify({"error": "Chat not found or not owned by you"}), 404

    return jsonify({"message": "Chat deleted"}), 200


# ----------------------------------------------------------------------
# EDIT MESSAGE (only user messages)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>/messages/<message_id>', methods=['PATCH'])
@jwt_required()
def edit_message(chat_id, message_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    content = payload.get('content')      # new text (optional)
    role    = payload.get('role')         # usually stays "user" (optional)

    if content is None and role is None:
        return jsonify({"error": "Nothing to update"}), 400

    if not update_message_role_content(message_id, chat_id, user_id, role, content):
        return jsonify({"error": "Message not found, not a user message, or not owned by you"}), 404

    return jsonify({"message": "Message updated"}), 200