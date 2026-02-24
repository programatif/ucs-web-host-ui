from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required
from models import db, User
from ldap3 import Server, Connection, ALL, SIMPLE

auth_bp = Blueprint('auth', __name__)

# --- LDAP Configuration ---
LDAP_SERVER = 'ldap://your-ldap-server.com'
LDAP_USER_DN_TEMPLATE = 'uid={username},ou=users,dc=example,dc=com'

def authenticate_ldap(username, password):
    try:
        server = Server(LDAP_SERVER, get_info=ALL)
        user_dn = LDAP_USER_DN_TEMPLATE.format(username=username)
        conn = Connection(server, user=user_dn, password=password, authentication=SIMPLE)
        if conn.bind():
            conn.unbind()
            return True
        return False
    except Exception as e:
        print(f"LDAP Error: {e}")
        return False


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 1. Try LDAP First
        if authenticate_ldap(username, password):
            user = User.query.filter_by(username=username).first()
            if not user:
                # Create local record so the user has a unique ID for container binding
                user = User(username=username, role='user')
                db.session.add(user)
                db.session.commit()
            login_user(user)
            return redirect(url_for('index'))

        # 2. Fallback to Local DB (Admin)
        user = User.query.filter_by(username=username).first()
        if user and user.password_hash and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
            
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))