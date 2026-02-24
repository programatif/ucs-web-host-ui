from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_required, current_user
from models import db, User, Deployment, AvailableDomain
from auth import auth_bp
from functools import wraps
import requests
import os
import random
import string

app = Flask(__name__)
app.secret_key = "drftgyhujiokpiugyft4567789ij!!#e5"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

app.register_blueprint(auth_bp)

# --- Create DB and Default User (Run once) ---
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin', 
            full_name='System Administrator', 
            role='admin'
        )
        admin.set_password('password123')
        db.session.add(admin)
        db.session.commit()

# Configuration: Point this to your existing Docker Swarm API
API_BASE_URL = "https://swarm-controller.harrys-cv.me" 

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403) # Forbidden
        return f(*args, **kwargs)
    return decorated_function

def fetch_api(endpoint, method='GET', data=None):
    try:
        url = f"{API_BASE_URL}{endpoint}"
        if method == 'GET':
            response = requests.get(url, timeout=5)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=10)
        elif method == 'DELETE':
            response = requests.delete(url, timeout=10)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


@app.route('/')
@login_required
def index():
    stats = fetch_api('/stats')
    init_containers = fetch_api('/containers')
    
    # Fetch all deployments for the current user (or all if admin)
    if current_user.role == "admin":
        deployments = Deployment.query.all()
    else:
        deployments = Deployment.query.filter_by(user_id=current_user.id).all()
    
    # Create a lookup dictionary: {stack_name: domain}
    domain_map = {d.stack_name: d.domain for d in deployments}

    

    containers = []
    user_id = current_user.id
    for c in init_containers:
        # Add the domain from our DB to the container object
        c['custom_domain'] = domain_map.get(c['stack_name'])
        print(c["stack_name"])
        
        if current_user.role == "admin" or str(c.get("account")) == str(user_id):
            containers.append(c)

    return render_template('dashboard.html', stats=stats, containers=containers, max_containers=current_user.max_containers)


@app.route('/deploy', methods=['GET', 'POST'])
@login_required
def deploy():
    containers = [c for c in fetch_api('/containers') if str(c["account"]) == str(current_user.id)]
    if len(containers) >= current_user.max_containers:
        flash("You have reached your container limit", "error")
        return redirect(url_for("index"))

    if request.method == 'POST':
        user = current_user
        template = request.form.get('template').removesuffix(".yml")
        stack_name = request.form.get('stack_name')
        root_domain = request.form.get('root_domain') # Selected from dropdown
        
        # 1. Generate Base Subdomain: username-stackname
        clean_username = "".join(filter(str.isalnum, user.username.lower()))
        clean_stack = "".join(filter(str.isalnum, stack_name.lower()))
        base_subdomain = f"{clean_username}-{clean_stack}"
        
        # 2. Check for uniqueness and append random string if exists
        final_domain = f"{base_subdomain}.{root_domain}"
        exists = Deployment.query.filter_by(domain=final_domain).first()
        
        if exists:
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
            final_domain = f"{base_subdomain}-{suffix}.{root_domain}"

        print(final_domain)

        payload = {
            "stack_name": stack_name,
            "domain": final_domain,
            "cpus": request.form.get('cpus', '0.5'),
            "ram": request.form.get('ram', '512M'),
            "account_id": user.id
        }
        result = fetch_api(f'/deploy/{template}', method='POST', data=payload)
        print(result)
        if "error" in result:
            flash(f"Error: {result['error']}", "error")
        else:
            safe_name = "".join([c for c in stack_name if c.isalnum() or c in "-_"]).lower()
            new_deployment = Deployment(
                stack_name=safe_name,
                domain=final_domain,
                user_id=current_user.id
            )
            db.session.add(new_deployment)
            db.session.commit()
            flash(f"Deployed {result['stack']} successfully!", "success")
        return redirect(url_for('index'))

    templates_data = fetch_api('/templates-list')
    templates = templates_data[0].get('templates', []) if isinstance(templates_data, list) else []
    available_domains = AvailableDomain.query.all()
    return render_template('deploy.html', templates=templates, available_domains=available_domains)

@app.route('/admin/users')
@login_required
def manage_users():
    if current_user.role != 'admin':
        abort(403) # Only admins can manage users
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    if current_user.role != 'admin':
        abort(403)
    
    # Get form data for new user and limits
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'user')
    max_containers = request.form.get('max_containers', 5, type=int)
    max_ram = request.form.get('max_ram', 1024, type=int)

    new_user = User(username=username, role=role, max_containers=max_containers, max_ram_mb=max_ram)
    new_user.set_password(password)
    
    db.session.add(new_user)
    db.session.commit()
    flash('User created successfully')
    return redirect(url_for('manage_users'))

@app.route('/admin/users/update/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Update basic info
    user.username = request.form.get('username')
    
    # Update resource limits
    user.max_containers = request.form.get('max_containers', type=int)
    user.max_cpus = request.form.get('max_cpus', type=float)
    user.max_ram_mb = request.form.get('max_ram_mb', type=int)
    
    # Optional: Update password only if provided
    new_password = request.form.get('password')
    if new_password:
        user.set_password(new_password)
        
    db.session.commit()
    flash(f"User {user.username} updated successfully", "success")
    return redirect(url_for('manage_users'))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if current_user.id == user_id:
        flash("You cannot delete your own admin account!", "error")
        return redirect(url_for('manage_users'))
        
    user = User.query.get_or_404(user_id)
    
    # Check if user requested to delete containers
    should_delete_containers = request.form.get('delete_containers') == 'true'
    
    if should_delete_containers:
        # 1. Fetch all containers from the Swarm API
        all_containers = fetch_api('/containers')
        
        # 2. Filter containers belonging to this user and remove their stacks
        # Note: We use list comprehension to avoid mutation issues during iteration
        user_stacks = [c['stack_name'] for c in all_containers if str(c.get('account')) == str(user_id)]
        
        # Remove duplicates (a stack can have multiple containers/services)
        unique_stacks = list(set(user_stacks))
        
        for stack in unique_stacks:
            # Reusing your existing proxy logic to remove stacks
            fetch_api(f'/stack/remove/{stack}', method='DELETE')
            
        flash(f"Deleted {user.username} and removed {len(unique_stacks)} stacks.", "warning")
    else:
        flash(f"User {user.username} deleted. Containers were left running.", "warning")

    # 3. Finally, delete the user from the local DB
    db.session.delete(user)
    db.session.commit()
    
    return redirect(url_for('manage_users'))


@app.route('/admin/domains')
@login_required
@admin_required
def manage_domains():
    domains = AvailableDomain.query.all()
    ips = fetch_api("/system/ip")
    return render_template('admin_domains.html', domains=domains, ips=ips)

@app.route('/admin/domains/add', methods=['POST'])
@login_required
@admin_required
def add_domain():
    domain_name = request.form.get('domain_name').strip().lower()
    if domain_name:
        new_domain = AvailableDomain(domain_name=domain_name)
        db.session.add(new_domain)
        db.session.commit()
        flash(f"Domain {domain_name} added.", "success")
    return redirect(url_for('manage_domains'))

@app.route('/admin/domains/delete/<int:domain_id>', methods=['POST'])
@login_required
@admin_required
def delete_domain(domain_id):
    domain = AvailableDomain.query.get_or_404(domain_id)
    db.session.delete(domain)
    db.session.commit()
    flash("Domain removed.", "warning")
    return redirect(url_for('manage_domains'))









# Hosting API stuff below

@app.route('/action/<service_id>/<action>', methods=['POST'])
@login_required
def service_action(service_id, action):
    result = fetch_api(f'/manage/service/{service_id}', method='POST', data={"action": action})
    return jsonify(result)

# Route for Start, Stop, and Restart
@app.route('/api/manage/<service_id>/<action>', methods=['POST'])
@login_required
def proxy_manage(service_id, action):
    # This calls your backend: @app.route('/manage/service/<service_id_or_name>', methods=['POST'])
    result = fetch_api(f'/manage/service/{service_id}', method='POST', data={"action": action})
    return jsonify(result)

# Route for Full Removal
@app.route('/api/remove/<stack_name>', methods=['DELETE'])
@login_required
def proxy_remove(stack_name):
    # This calls your backend: @app.route('/stack/remove/<stack_name>', methods=['DELETE'])
    result = fetch_api(f'/stack/remove/{stack_name}', method='DELETE')
    return jsonify(result)

# Inside your NEW flask app (app.py)

@app.route('/api/live-stats')
@login_required
def live_stats():
    # Proxies the call to your Backend API
    return fetch_api('/stats')

# --- System Maintenance ---
@app.route('/api/system/prune', methods=['POST'])
@login_required
@admin_required
def system_prune():
    return jsonify(fetch_api('/system/prune', method='POST'))

# --- File Management ---
@app.route('/api/files/<stack>/list')
@login_required
def get_files(stack):
    return jsonify(fetch_api(f'/files/{stack}/list'))

@app.route('/api/files/<stack>/read')
@login_required
def read_file(stack):
    filename = request.args.get('filename')
    # Directly fetch the raw text from the backend
    response = requests.get(f"{API_BASE_URL}/files/{stack}/read?filename={filename}")
    return response.text

@app.route('/api/files/<stack>/edit', methods=['POST'])
@login_required
def edit_file(stack):
    return jsonify(fetch_api(f'/files/{stack}/edit', method='POST', data=request.json))


# --- Proxy File Upload ---
@app.route('/api/files/<stack>/upload', methods=['POST'])
@login_required
def proxy_upload(stack):
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    file = request.files['file']
    files = {'file': (file.filename, file.stream, file.mimetype)}
    
    # Forward the file to your Docker API
    response = requests.post(f"{API_BASE_URL}/files/{stack}/upload", files=files)
    return jsonify(response.json())

# --- Create Empty File ---
@app.route('/api/files/<stack>/create', methods=['POST'])
@login_required
def proxy_create(stack):
    filename = request.json.get('filename') # e.g., "subfolder/newfile.txt"
    
    if not filename:
        return jsonify({"error": "Filename is required"}), 400

    # 1. Handle potential subdirectory creation
    # If filename is "folder/test.txt", we extract "folder"
    if "/" in filename:
        directory = "/".join(filename.split("/")[:-1])
        # Call the backend to ensure this directory exists
        # Assuming you have a /create-dir endpoint or similar
        fetch_api(f'/files/{stack}/mkdir', method='POST', data={"path": directory})

    # 2. Now reuse the edit endpoint with empty content to "create" the actual file
    return jsonify(fetch_api(f'/files/{stack}/edit', method='POST', data={
        "filename": filename,
        "content": ""
    }))

@app.route('/api/files/<stack>/manage', methods=['POST'])
@login_required
def proxy_file_manage(stack):
    # Handles rename and delete actions
    return jsonify(fetch_api(f'/files/{stack}/manage', method='POST', data=request.json))

@app.route('/api/files/<stack>/upload-bulk', methods=['POST'])
@login_required
def proxy_upload_bulk(stack):
    if 'files[]' not in request.files:
        return jsonify({"error": "No files provided"}), 400
    
    uploaded_files = request.files.getlist('files[]')
    results = []
    
    for file in uploaded_files:
        files = {'file': (file.filename, file.stream, file.mimetype)}
        response = requests.post(f"{API_BASE_URL}/files/{stack}/upload", files=files)
        results.append(response.json())
        
    return jsonify({"results": results, "status": "success"})

@app.route('/api/logs/<stack>/<service>')
@login_required
def get_service_logs(stack, service):
    result = fetch_api(f'/logs/{stack}/{service}')
    if "error" in result:
        return jsonify({"logs": f"Error fetching logs: {result['error']}"}), 500
    return jsonify({"logs": result.get('logs', 'No logs found.')})

@app.route('/api/files/<stack>/upload-zip', methods=['POST'])
@login_required
def proxy_upload_zip(stack):
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({"error": "File must be a .zip archive"}), 400

    files = {'file': (file.filename, file.stream, file.mimetype)}
    
    # Forward to the /bulk-upload endpoint specifically for ZIPs
    response = requests.post(f"{API_BASE_URL}/files/{stack}/bulk-upload", files=files)
    return jsonify(response.json())

@app.route('/api/files/<stack>/mkdir', methods=['POST'])
@login_required
def proxy_mkdir(stack):
    # Get the folder name from the frontend request
    folder_name = request.json.get('directory_name')
    
    # Forward to the backend using the 'path' key as required by your API
    return jsonify(fetch_api(f'/files/{stack}/mkdir', method='POST', data={
        "path": folder_name
    }))
if __name__ == '__main__':
    app.run(port=8080, debug=True, host="0.0.0.0")