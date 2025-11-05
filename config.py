# config.py
import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-jwt')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)   # <-- ADD THIS

    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', 'sk-f19f5e9b50ae4d9c8f47dd9995312668')
    DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://chatter:EBste4Biqob7tnBZ@cluster0.ujjvtgc.mongodb.net/chatter')