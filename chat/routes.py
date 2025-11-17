# routes/chats.py
from flask import request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity
from openai import OpenAI, APIError, AuthenticationError, RateLimitError
from config import Config
from . import chat_bp
from models.chat import create_chat, get_user_chats, get_chat, delete_chat, update_chat_title as db_update_title
from models.message import add_message, get_history, get_messages, update_message_content
import json
import re
import uuid
from datetime import datetime
from bson import ObjectId

# Global dictionary to store active streams
active_streams = {}

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

def extract_sources_from_response(content):
    """Extract potential sources and links from AI response"""
    sources = []
    
    # Look for markdown links [text](url)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    links = re.findall(link_pattern, content)
    
    for text, url in links:
        if url.startswith(('http://', 'https://')):
            sources.append({
                "title": text,
                "url": url,
                "type": "website"
            })
    
    # Look for standalone URLs
    url_pattern = r'https?://[^\s\)]+'
    urls = re.findall(url_pattern, content)
    for url in urls:
        if url not in [s['url'] for s in sources]:
            sources.append({
                "title": "Related Resource",
                "url": url,
                "type": "website"
            })
    
    # Look for citations [1], [2], etc.
    citation_pattern = r'\[\d+\]'
    if re.search(citation_pattern, content):
        sources.append({
            "title": "Academic References",
            "url": "#citations",
            "type": "citation"
        })
    
    return sources
# routes/chats.py - Update the system message for better source generation
def get_enhanced_system_message():
    return {
        "role": "system", 
        "content": """You are a helpful AI assistant that provides comprehensive, well-researched responses. 

CRITICAL: For EVERY response, you MUST include relevant sources, references, and links to help users explore topics further. 

SOURCE REQUIREMENTS:
1. Include at least 3-5 relevant sources for comprehensive topics
2. Include official documentation links for technical topics
3. Include academic papers or research for scientific topics
4. Include tutorial links for learning resources
5. Include news articles for current events
6. Always use proper markdown formatting: [Link Text](URL)

FORMAT GUIDELINES:
- Place sources in a dedicated "## References" or "## Sources" section at the END
- Use clear, descriptive link text
- Prioritize authoritative sources (official docs, academic journals, reputable news)
- Include diverse types of sources (documentation, tutorials, research, news)
- For technical topics, include both official documentation and practical tutorials

EXAMPLE SOURCE SECTION:
## References
- [Official Python Documentation](https://docs.python.org/3/)
- [Real Python Tutorial](https://realpython.com)
- [Stack Overflow Discussion](https://stackoverflow.com)
- [Academic Paper on Topic](https://arxiv.org)
- [GitHub Repository](https://github.com)

Always provide comprehensive information with proper sources to help users learn and verify information."""
    }

# Update the send_message function - replace the system_message creation
@chat_bp.route('/api/chats/<chat_id>/messages', methods=['POST'])
@jwt_required()
def send_message(chat_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    content = payload.get('content')
    use_streaming = payload.get('stream', True)
    stream_id = payload.get('stream_id')
    
    if not content:
        return jsonify({"error": "Field `content` is required"}), 400

    chat = get_chat(chat_id, user_id)
    if not chat:
        return jsonify({"error": "Chat not found or not owned by you"}), 404

    # Add user message
    add_message(chat_id, "user", content)
    history = get_history(chat_id)

    prompt_length = len(content)
    max_tokens = 2000 if prompt_length > 500 else 1500

    try:
        if use_streaming:
            if not stream_id:
                stream_id = str(uuid.uuid4())
            
            def generate():
                try:
                    full_reply = ""
                    stream_buffer = []
                    sources = []
                    
                    # Store stream state
                    active_streams[stream_id] = {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "content": full_reply,
                        "active": True,
                        "created_at": datetime.utcnow()
                    }
                    
                    # Use enhanced system message
                    system_message = get_enhanced_system_message()
                    
                    stream = client.chat.completions.create(
                        model=MODEL,
                        messages=[system_message] + history,
                        max_tokens=max_tokens,
                        temperature=0.7,
                        stream=True
                    )
                    
                    for chunk in stream:
                        if not active_streams.get(stream_id, {}).get("active", True):
                            yield f"data: {json.dumps({'stopped': True, 'stream_id': stream_id, 'content_so_far': full_reply})}\n\n"
                            break
                            
                        if chunk.choices[0].delta.content:
                            content_piece = chunk.choices[0].delta.content
                            full_reply += content_piece
                            stream_buffer.append(content_piece)
                            
                            # Send chunks more frequently for smoother scrolling
                            if len(stream_buffer) >= 2 or len(content_piece) > 30:
                                yield f"data: {json.dumps({'content': ''.join(stream_buffer), 'stream_id': stream_id})}\n\n"
                                stream_buffer = []
                            
                            # Update active stream
                            if stream_id in active_streams:
                                active_streams[stream_id]["content"] = full_reply
                    
                    # Send remaining buffer
                    if stream_buffer and active_streams.get(stream_id, {}).get("active", True):
                        yield f"data: {json.dumps({'content': ''.join(stream_buffer), 'stream_id': stream_id})}\n\n"
                    
                    if active_streams.get(stream_id, {}).get("active", True):
                        # Extract sources from final content
                        sources = extract_sources_from_response(full_reply)
                        
                        # Auto-generate chat title from first message if it's a new chat
                        if len(history) == 1:  # Only user message + this will be first assistant response
                            auto_title = generate_chat_title(content)
                            if auto_title:
                                update_chat_title(chat_id, auto_title)
                        
                        add_message(chat_id, "assistant", full_reply, sources)
                        yield f"data: {json.dumps({'done': True, 'full_content': full_reply, 'sources': sources, 'stream_id': stream_id})}\n\n"
                    
                    # Clean up
                    if stream_id in active_streams:
                        del active_streams[stream_id]
                        
                except Exception as e:
                    if stream_id in active_streams:
                        del active_streams[stream_id]
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

            return Response(
                stream_with_context(generate()),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache', 
                    'X-Accel-Buffering': 'no',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type, Authorization'
                }
            )
        else:
            # Non-streaming response
            system_message = get_enhanced_system_message()
            
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[system_message] + history,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=False
            )
            reply = completion.choices[0].message.content.strip()
            sources = extract_sources_from_response(reply)
            
            # Auto-generate chat title for new chats
            if len(history) == 1:
                auto_title = generate_chat_title(content)
                if auto_title:
                    update_chat_title(chat_id, auto_title)
            
            add_message(chat_id, "assistant", reply, sources)
            return jsonify({"content": reply, "sources": sources}), 200

    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

# Add this function for auto-generating chat titles
def generate_chat_title(first_message):
    """Generate a contextual title based on the first user message"""
    try:
        # Truncate very long messages
        truncated_message = first_message[:100] + "..." if len(first_message) > 100 else first_message
        
        # Create a prompt for title generation
        title_prompt = f"""Create a very short, descriptive title (max 4-5 words) for a chat that starts with this message: "{truncated_message}"
        
        Return ONLY the title, no other text. Make it concise and descriptive."""
        
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise, descriptive chat titles."},
                {"role": "user", "content": title_prompt}
            ],
            max_tokens=20,
            temperature=0.3
        )
        
        title = completion.choices[0].message.content.strip()
        # Clean up the title (remove quotes, etc.)
        title = title.replace('"', '').replace("'", "").strip()
        return title if title and len(title) > 0 else None
        
    except Exception as e:
        print(f"Title generation failed: {e}")
        return None

# Enhanced source extraction
def extract_sources_from_response(content):
    """Extract potential sources and links from AI response with better detection"""
    sources = []
    
    # Look for markdown links [text](url)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    links = re.findall(link_pattern, content)
    
    for text, url in links:
        if url.startswith(('http://', 'https://')):
            # Categorize the source type
            source_type = categorize_source(url, text)
            sources.append({
                "title": text,
                "url": url,
                "type": source_type
            })
    
    # Look for standalone URLs
    url_pattern = r'https?://[^\s\)\]]+'
    urls = re.findall(url_pattern, content)
    for url in urls:
        if url not in [s['url'] for s in sources]:
            source_type = categorize_source(url, "Related Resource")
            sources.append({
                "title": "Related Resource",
                "url": url,
                "type": source_type
            })
    
    # Remove duplicates
    unique_sources = []
    seen_urls = set()
    for source in sources:
        if source['url'] not in seen_urls:
            unique_sources.append(source)
            seen_urls.add(source['url'])
    
    return unique_sources

def categorize_source(url, title):
    """Categorize the source type based on URL and title"""
    url_lower = url.lower()
    title_lower = title.lower()
    
    if any(domain in url_lower for domain in ['docs.', 'documentation', 'developer.', 'api.']):
        return "documentation"
    elif any(domain in url_lower for domain in ['github.com', 'gitlab.com', 'bitbucket.org']):
        return "code_repository"
    elif any(domain in url_lower for domain in ['stackoverflow.com', 'stackexchange.com', 'reddit.com']):
        return "discussion"
    elif any(domain in url_lower for domain in ['wikipedia.org', 'britannica.com']):
        return "encyclopedia"
    elif any(domain in url_lower for domain in ['arxiv.org', 'researchgate.net', 'scholar.google']):
        return "academic"
    elif any(domain in url_lower for domain in ['medium.com', 'dev.to', 'tutorial', 'guide']):
        return "tutorial"
    elif any(domain in url_lower for domain in ['news.', 'reuters.com', 'bbc.com', 'cnn.com']):
        return "news"
    elif any(word in title_lower for word in ['paper', 'research', 'study', 'journal']):
        return "academic"
    else:
        return "website"

        
# ----------------------------------------------------------------------
# STOP STREAM ENDPOINT
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>/stop', methods=['POST'])
@jwt_required()
def stop_stream(chat_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    stream_id = payload.get('stream_id')
    
    if not stream_id:
        return jsonify({"error": "stream_id is required"}), 400
    
    if stream_id in active_streams:
        if active_streams[stream_id]["user_id"] == user_id and active_streams[stream_id]["chat_id"] == chat_id:
            active_streams[stream_id]["active"] = False
            content_so_far = active_streams[stream_id]["content"]
            
            # Save the partial response
            if content_so_far.strip():
                sources = extract_sources_from_response(content_so_far)
                add_message(chat_id, "assistant", content_so_far, sources)
            
            del active_streams[stream_id]
            return jsonify({"stopped": True, "content_so_far": content_so_far}), 200
    
    return jsonify({"error": "Stream not found or already stopped"}), 404

# ----------------------------------------------------------------------
# CONTINUE STREAM ENDPOINT - FIXED
# ----------------------------------------------------------------------
@chat_bp.route('/api/chats/<chat_id>/continue', methods=['POST'])
@jwt_required()
def continue_stream(chat_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    previous_content = payload.get('previous_content', '')
    
    if not previous_content:
        return jsonify({"error": "previous_content is required"}), 400

    chat = get_chat(chat_id, user_id)
    if not chat:
        return jsonify({"error": "Chat not found or not owned by you"}), 404

    # Get history (excluding the last partial message we're continuing from)
    history = get_history(chat_id)
    
    # Remove the last assistant message if it's the one we're continuing
    if history and history[-1]["role"] == "assistant":
        history = history[:-1]
    
    continue_prompt = f"Continue this response exactly from where it left off. Maintain the same style, tone, and depth. Here's what was written so far: {previous_content}"
    
    try:
        system_message = {
            "role": "system", 
            "content": "You are a helpful assistant. Continue the response naturally from where it was left off. Maintain the exact same style, tone, and level of detail. Continue providing helpful information with sources where appropriate."
        }
        
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[system_message] + history + [{"role": "user", "content": continue_prompt}],
            max_tokens=1500,
            temperature=0.7,
            stream=False
        )
        continued_reply = completion.choices[0].message.content.strip()
        
        # Combine with previous content
        full_content = previous_content + continued_reply
        sources = extract_sources_from_response(full_content)
        
        # Add as a new message instead of updating the existing one
        # This keeps the conversation history cleaner
        add_message(chat_id, "assistant", full_content, sources)
        
        return jsonify({
            "continued_content": continued_reply,
            "full_content": full_content,
            "sources": sources
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Failed to continue: {str(e)}"}), 500

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
            system_message = {
                "role": "system", 
                "content": "You are a helpful assistant. Provide comprehensive responses with relevant sources and links when appropriate."
            }
            
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[system_message] + history,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=False
            )
            reply = completion.choices[0].message.content.strip()
            sources = extract_sources_from_response(reply)
            add_message(chat_id, "assistant", reply, sources)
            return jsonify({
                "id": chat_id,
                "title": title,
                "initial_response": reply,
                "sources": sources
            }), 201
        except Exception as e:
            return jsonify({
                "id": chat_id,
                "title": title,
                "error": f"Error: {str(e)}"
            }), 201
    
    return jsonify({"id": chat_id, "title": title}), 201

# ----------------------------------------------------------------------
# UPDATE CHAT TITLE
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
# OTHER ROUTES
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


