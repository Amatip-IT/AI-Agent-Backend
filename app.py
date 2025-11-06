# app.py
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_swagger_ui import get_swaggerui_blueprint
from config import Config

# Extensions
from extensions import mongo


from auth import auth_bp
from chat import chat_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ---------- CORS: Allow all origins (dev) ----------
    CORS(
        app,
        origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Accept"],
        supports_credentials=True,
        expose_headers=["Content-Type", "Authorization"]
    )

    # ---------- Extensions ----------
    mongo.init_app(app)
    jwt = JWTManager(app)

    # JWT Blacklist in MongoDB
    app.config["JWT_BLACKLIST_ENABLED"] = True
    app.config["JWT_BLACKLIST_TOKEN_CHECKS"] = ["access"]

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        return mongo.db.blacklist.find_one({"jti": jti}) is not None

    # ---------- Blueprints: NO /api prefix ----------
    app.register_blueprint(auth_bp)        # → /auth/login, /auth/register
    app.register_blueprint(chat_bp)        # → /chat/...

    # ---------- Swagger (now at /docs) ----------
    SWAGGER_URL = '/docs'
    API_URL = '/openapi.yaml'
    swagger_ui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={'app_name': "Chatter API"}
    )
    app.register_blueprint(swagger_ui_blueprint, url_prefix=SWAGGER_URL)

    @app.route('/openapi.yaml')
    def serve_openapi():
        return send_from_directory('.', 'openapi.yaml')

    # ---------- Serve avatars ----------
    @app.route('/static/avatars/<filename>')
    def serve_avatar(filename):
        return send_from_directory('static/avatars', filename)

    # ---------- Health check ----------
    @app.route('/')
    def home():
        return jsonify({
            "message": "Chatter API Running!",
            "docs": "http://localhost:5000/docs"
        })

    return app


# Create app
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)