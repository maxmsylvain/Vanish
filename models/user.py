from flask_login import UserMixin
from datetime import datetime, timezone
from app import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.String(200), default='default.jpg')
    bio = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    posts = db.relationship('Post', backref='author', lazy=True, cascade="all, delete-orphan")
    def __repr__(self):
        return f"User('{self.username}', '{self.email}')"