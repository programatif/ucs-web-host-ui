from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    # Role-based access: "admin" or "user"
    role = db.Column(db.String(20), default="user", nullable=False)

    # Resource Limits for each user
    max_containers = db.Column(db.Integer, default=5)
    max_cpus = db.Column(db.Float, default=2.0)
    max_ram_mb = db.Column(db.Integer, default=1024)
    max_storage_gb = db.Column(db.Integer, default=10)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Deployment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stack_name = db.Column(db.String(100), unique=True, nullable=False)
    domain = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class AvailableDomain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    domain_name = db.Column(db.String(255), unique=True, nullable=False)