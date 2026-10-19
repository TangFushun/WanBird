import os
import sys

# 让 Vercel 的函数入口能导入项目根目录的 app.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402  (Flask 的 WSGI 应用)
