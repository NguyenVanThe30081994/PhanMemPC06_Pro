import os
from flask import Flask, render_template, session
from routes.chat import chat_bp
from models import db, User

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pc06_system.db'
app.config['SECRET_KEY'] = 'test'
db.init_app(app)

with app.app_context():
    try:
        # Giả lập context cho template
        users = User.query.all()
        rendered = render_template('chat.html', users=users, perms={}, session={}, request=type('obj', (object,), {'endpoint': 'chat_bp.chat', 'path': '/chat'})())
        print("Template 'chat.html' rendered successfully!")
    except Exception as e:
        print(f"Error rendering 'chat.html': {e}")

with app.app_context():
    try:
        rendered = render_template('base.html', perms={}, session={}, request=type('obj', (object,), {'endpoint': 'admin_bp.index', 'path': '/admin'})())
        print("Template 'base.html' rendered successfully!")
    except Exception as e:
        print(f"Error rendering 'base.html': {e}")
