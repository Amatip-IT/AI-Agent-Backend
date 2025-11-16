# chat/routes.py
from flask import request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity
from openai import OpenAI, APIError, AuthenticationError, RateLimitError
from config import Config
from . import chat_bp
from models.chat import create_chat, get_user_chats, get_chat, delete_chat, update_chat_title as db_update_title
from models.message import add_message, get_history, get_messages
import json

# ----------------------------------------------------------------------
# DeepSeek client with increased timeout
# ----------------------------------------------------------------------
client = OpenAI(
    api_key=Config.DEEPSEEK_API_KEY,
    base_url=Config.DEEPSEEK_BASE_URL,
    timeout=120,
    max_retries=3
)

MODEL = "deepseek-chat"

# ----------------------------------------------------------------------
# SEND MESSAGE (with streaming support)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>/messages', methods=['POST'])
@jwt_required()
def send_message(chat_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    content = payload.get('content')
    use_streaming = payload.get('stream', False)
    
    if not content:
        return jsonify({"error": "Field `content` is required"}), 400

    if not get_chat(chat_id, user_id):
        return jsonify({"error": "Chat not found or not owned by you"}), 404

    add_message(chat_id, "user", content)
    history = get_history(chat_id)

    prompt_length = len(content)
    max_tokens = 2000 if prompt_length > 500 else 1500

    try:
        if use_streaming:
            def generate():
                try:
                    stream = client.chat.completions.create(
                        model=MODEL,
                        messages=[{"role": "system", "content": "You are a helpful assistant."}] + history,
                        max_tokens=max_tokens,
                        temperature=0.7,
                        stream=True
                    )
                    full_reply = ""
                    for chunk in stream:
                        if chunk.choices[0].delta.content:
                            content_piece = chunk.choices[0].delta.content
                            full_reply += content_piece
                            yield f"data: {json.dumps({'content': content_piece})}\n\n"
                    add_message(chat_id, "assistant", full_reply)
                    yield f"data: {json.dumps({'done': True, 'full_content': full_reply})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            return Response(
                stream_with_context(generate()),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
            )
        else:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": "You are a helpful assistant."}] + history,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=False
            )
            reply = completion.choices[0].message.content.strip()
            add_message(chat_id, "assistant", reply)
            return jsonify({"content": reply}), 200

    except AuthenticationError:
        return jsonify({"error": "Invalid DeepSeek API key"}), 401
    except RateLimitError:
        return jsonify({"error": "DeepSeek rate-limit exceeded"}), 429
    except APIError as e:
        return jsonify({"error": f"DeepSeek API error: {str(e)}"}), 502
    except TimeoutError:
        return jsonify({"error": "Request timed out. Try a shorter prompt or enable streaming."}), 504
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


# ----------------------------------------------------------------------
# CREATE CHAT (with optional initial message)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats', methods=['POST'])
@jwt_required()
def new_chat():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    title = data.get('title', 'New Chat')
    initial_message = data.get('message')
    
    chat = create_chat(user_id, title)
    chat_id = chat["_id"]
    
    if initial_message:
        add_message(chat_id, "user", initial_message)
        history = get_history(chat_id)
        prompt_length = len(initial_message)
        max_tokens = 2000 if prompt_length > 500 else 1500
        
        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": "You are a helpful assistant."}] + history,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=False
            )
            reply = completion.choices[0].message.content.strip()
            add_message(chat_id, "assistant", reply)
            return jsonify({
                "id": chat_id,
                "title": title,
                "initial_response": reply
            }), 201
        except Exception as e:
            return jsonify({
                "id": chat_id,
                "title": title,
                "error": f"Error: {str(e)}"
            }), 201
    
    return jsonify({"id": chat_id, "title": title}), 201


# ----------------------------------------------------------------------
# UPDATE CHAT TITLE (NEW ENDPOINT)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>', methods=['PUT'])
@jwt_required()
def update_chat_title(chat_id):
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    new_title = data.get('title')
    if not new_title:
        return jsonify({"error": "Field `title` is required"}), 400

    chat = get_chat(chat_id, user_id)
    if not chat:
        return jsonify({"error": "Chat not found or not owned by you"}), 404

    if not db_update_title(chat_id, new_title):
        return jsonify({"error": "Failed to update title"}), 500

    return jsonify({"title": new_title}), 200


# ----------------------------------------------------------------------
# OTHER ROUTES (unchanged)
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats', methods=['GET'])
@jwt_required()
def list_chats():
    user_id = get_jwt_identity()
    return jsonify(get_user_chats(user_id))

@chat_bp.route('/api/chats/<chat_id>/messages', methods=['GET'])
@jwt_required()
def list_messages(chat_id):
    user_id = get_jwt_identity()
    if not get_chat(chat_id, user_id):
        return jsonify({"error": "Chat not found or not owned by you"}), 404
    return jsonify(get_messages(chat_id))

@chat_bp.route('/api/chats/<chat_id>', methods=['DELETE'])
@jwt_required()
def delete_chat_endpoint(chat_id):
    user_id = get_jwt_identity()
    if not delete_chat(chat_id, user_id):
        return jsonify({"error": "Chat not found or not owned by you"}), 404
    return jsonify({"message": "Chat deleted"}), 200

@chat_bp.route('/api/chats/<chat_id>/messages/<message_id>', methods=['PATCH'])
@jwt_required()
def edit_message(chat_id, message_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    content = payload.get('content')
    role = payload.get('role')
    
    if content is None and role is None:
        return jsonify({"error": "Nothing to update"}), 400
    
    if not update_message_role_content(message_id, chat_id, user_id, role, content):
        return jsonify({"error": "Message not found, not a user message, or not owned by you"}), 404
    
    return jsonify({"message": "Message updated"}), 200