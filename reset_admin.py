import os
from flask import Flask
from models import db, User
from app import app

def reset_admin():
    with app.app_context():
        u = User.query.filter_by(username='admin').first()
        if u:
            print(f"Resetting password for admin (ID: {u.id})...")
            # Directly set password via models' set_password
            u.set_password('123')
            db.session.commit()
            print("[OK] Admin password reset to: 123")
        else:
            print("[ERROR] Admin user not found!")

if __name__ == '__main__':
    reset_admin()
