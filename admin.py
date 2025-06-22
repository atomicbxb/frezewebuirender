from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from functools import wraps
import os
from datetime import date, timedelta

# Impor model dan form yang diperlukan
from models import db, User, AdminSetting, PlanType
from forms import AdminLoginForm, UserForm, AdminSettingsForm

admin_bp = Blueprint('admin_bp', __name__,
                     template_folder='templates/admin',
                     # Jika Anda memiliki file statis khusus untuk admin (misal, admin_style_override.css)
                     # dan menyimpannya di dalam folder blueprint (misal, /admin/static/), maka gunakan ini:
                     # static_folder='static',
                     # static_url_path='/admin/assets' # Path URL unik untuk static admin
                     )

# Load admin credentials langsung dari environment
ADMIN_USERNAME_ENV = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD_ENV = os.getenv("ADMIN_PASSWORD")

# Decorator untuk melindungi rute admin
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Admin access required.', 'danger')
            return redirect(url_for('admin_bp.admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    # Debug print bisa diaktifkan jika perlu
    # print(f"Accessing /admin/login. Method: {request.method}. Current session 'is_admin': {session.get('is_admin')}")
    # print(f"Env ADMIN_USERNAME: '{ADMIN_USERNAME_ENV}'") # Hati-hati dengan info sensitif di log produksi

    if session.get('is_admin'): # Jika sudah login sebagai admin, redirect ke dashboard
        return redirect(url_for('admin_bp.admin_dashboard'))

    form = AdminLoginForm()
    if form.validate_on_submit():
        submitted_username = form.username.data
        submitted_password = form.password.data

        if ADMIN_USERNAME_ENV is None or ADMIN_PASSWORD_ENV is None:
            print("CRITICAL ERROR (admin.py): Admin credentials (ADMIN_USERNAME_ENV or ADMIN_PASSWORD_ENV) are not configured on the server.")
            flash('Admin credentials not configured on the server. Critical error.', 'danger')
            # Tetap render halaman login, tapi dengan pesan error yang jelas
            return render_template('admin_login.html', form=form, title="Admin Login - Config Error")

        if submitted_username == ADMIN_USERNAME_ENV and submitted_password == ADMIN_PASSWORD_ENV:
            session['is_admin'] = True
            session['admin_username'] = submitted_username # Simpan username admin di session
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_bp.admin_dashboard'))
        else:
            flash('Invalid admin credentials.', 'danger')
            # print(f"DEBUG (admin.py): Invalid admin credentials attempt for user: {submitted_username}")
    
    # Render template admin_login.html yang standar
    return render_template('admin_login.html', form=form, title="Admin Login")


@admin_bp.route('/logout')
@admin_required
def admin_logout():
    admin_username_display = session.get('admin_username', 'Admin') # Ambil username untuk pesan flash
    session.pop('is_admin', None)
    session.pop('admin_username', None)
    flash(f'{admin_username_display} logged out from admin panel.', 'info')
    return redirect(url_for('admin_bp.admin_login'))

@admin_bp.route('/') # Default route untuk /admin akan ke dashboard
@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    try:
        total_users = User.query.count()
        active_users = User.query.filter(User.is_active==True, (User.expiry_date >= date.today()) | (User.expiry_date == None)).count()
        trial_users = User.query.filter_by(plan=PlanType.TRIAL).count()
        maintenance_mode = AdminSetting.get("maintenance_mode", False)
    except Exception as e:
        print(f"ERROR (admin.py - dashboard): Error fetching dashboard data: {e}")
        flash("Error fetching dashboard data. Please check server logs.", "danger")
        # Sediakan nilai default jika query gagal agar template tidak error
        total_users, active_users, trial_users, maintenance_mode = 0, 0, 0, False
        
    return render_template('admin_dashboard.html', title="Admin Dashboard",
                           total_users=total_users, active_users=active_users,
                           trial_users=trial_users, maintenance_mode=maintenance_mode)

@admin_bp.route('/users')
@admin_required
def list_users():
    page = request.args.get('page', 1, type=int)
    per_page = 15 # Jumlah item per halaman
    users_pagination = None # Inisialisasi
    try:
        users_pagination = User.query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    except Exception as e:
        print(f"ERROR (admin.py - list_users): Error fetching users list: {e}")
        flash("Error fetching user list. Please check server logs.", "danger")
        # Anda bisa membuat objek Paginate kosong jika diperlukan oleh template, atau handle None di template
    return render_template('users.html', users=users_pagination, title="Manage Users")

@admin_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def create_user():
    form = UserForm()
    if form.validate_on_submit(): # WTForms validation akan jalan dulu
        # Validasi unik manual tambahan (double check)
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already exists.', 'danger')
        elif form.email.data and User.query.filter_by(email=form.email.data).first(): # Hanya cek email jika ada
            flash('Email already registered.', 'danger')
        elif not form.password.data: # Password wajib untuk user baru
             flash("Password is required for new users.", "danger")
        else:
            # Lanjutkan jika semua validasi lolos
            new_user = User(username=form.username.data, email=form.email.data or None, plan=PlanType[form.plan.data])
            new_user.set_password(form.password.data)

            if form.expiry_days.data is not None and form.expiry_days.data > 0:
                new_user.expiry_date = date.today() + timedelta(days=form.expiry_days.data)
            elif new_user.plan == PlanType.TRIAL: # Default expiry untuk trial jika tidak diisi
                trial_duration = AdminSetting.get("trial_duration_days", 3)
                new_user.expiry_date = date.today() + timedelta(days=trial_duration)
            # Untuk plan lain, jika expiry_days tidak diisi, expiry_date akan NULL (tidak ada batas waktu)

            new_user.is_active = form.is_active.data
            try:
                db.session.add(new_user)
                db.session.commit()
                flash(f'User {new_user.username} created successfully!', 'success')
                return redirect(url_for('admin_bp.list_users'))
            except Exception as e:
                db.session.rollback() # Penting untuk rollback jika commit gagal
                print(f"ERROR (admin.py - create_user): Error creating user: {e}")
                flash(f"Error creating user: {str(e)}", 'danger') # Tampilkan pesan error
                
    return render_template('create_edit_user.html', form=form, title="Create New User", legend="New User")

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserForm(obj=user) # Pre-fill form dengan data user saat GET
    
    if request.method == 'GET':
        form.plan.data = user.plan.name # Set plan dengan benar untuk SelectField
        # expiry_days tidak di-prefill karena ini untuk ekstensi dari hari ini

    if form.validate_on_submit():
        # Simpan nilai original untuk perbandingan
        original_username = user.username
        original_email = user.email

        # Validasi unik jika username atau email diubah
        username_changed = user.username != form.username.data
        email_changed = (user.email or "") != (form.email.data or "") # Handle None

        if username_changed and User.query.filter(User.id != user.id, User.username == form.username.data).first():
            form.username.errors.append("Username already taken by another user.")
        if form.email.data and email_changed and User.query.filter(User.id != user.id, User.email == form.email.data).first():
            form.email.errors.append("Email already registered by another user.")
        
        if not form.errors: # Lanjutkan jika tidak ada error validasi dari WTForms atau manual
            user.username = form.username.data
            user.email = form.email.data or None # Simpan None jika kosong
            user.plan = PlanType[form.plan.data]

            if form.password.data: # Hanya update password jika diisi
                user.set_password(form.password.data)

            if form.expiry_days.data is not None: # Jika expiry_days diisi
                if form.expiry_days.data > 0:
                    user.expiry_date = date.today() + timedelta(days=form.expiry_days.data)
                elif form.expiry_days.data == 0: # Set expiry ke hari ini
                    user.expiry_date = date.today()
                elif form.expiry_days.data < 0: # Angka negatif bisa berarti "hapus expiry"
                    user.expiry_date = None
            # Jika expiry_days kosong, expiry_date user yang sudah ada tidak diubah

            user.is_active = form.is_active.data
            try:
                db.session.commit()
                flash(f'User {user.username} updated successfully!', 'success')
                return redirect(url_for('admin_bp.list_users'))
            except Exception as e:
                db.session.rollback()
                print(f"ERROR (admin.py - edit_user) updating user {user_id}: {e}")
                flash(f"Error updating user: {str(e)}", 'danger')
    
    # Render lagi formnya jika ada error validasi atau ini adalah request GET
    return render_template('create_edit_user.html', form=form, title=f"Edit User: {user.username}", legend=f"Edit User: {user.username}", user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST']) # Sebaiknya POST untuk aksi delete
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    try:
        user.is_active = False # Soft delete
        db.session.commit()
        flash(f'User {user.username} has been deactivated (soft delete).', 'warning') # Pesan diubah
    except Exception as e:
        db.session.rollback()
        print(f"ERROR (admin.py - delete_user) deactivating user {user_id}: {e}")
        flash(f"Error deactivating user: {str(e)}", 'danger')
    return redirect(url_for('admin_bp.list_users'))

# >>> PERUBAHAN DIMULAI: Menambahkan Rute dan Fungsi untuk Hard Delete <<<
@admin_bp.route('/users/<int:user_id>/hard_delete', methods=['POST'])
@admin_required
def hard_delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    
    # Keamanan tambahan: jangan izinkan admin menghapus akunnya sendiri dengan cara ini
    # Jika Anda memiliki ID admin tetap atau cara lain untuk mengidentifikasi admin super, tambahkan cek itu di sini.
    # Untuk sekarang, kita asumsikan admin tidak akan mencoba menghapus dirinya dari UI ini.
    
    username_deleted = user_to_delete.username # Simpan untuk pesan flash
    try:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'User {username_deleted} (ID: {user_id}) has been PERMANENTLY DELETED from the database.', 'danger')
    except Exception as e:
        db.session.rollback()
        print(f"ERROR (admin.py - hard_delete_user) for user {user_id}: {e}")
        flash(f"Error PERMANENTLY DELETING user {username_deleted}: {str(e)}", 'danger')
    return redirect(url_for('admin_bp.list_users'))
# >>> PERUBAHAN SELESAI <<<

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    form = AdminSettingsForm()
    if form.validate_on_submit():
        try:
            AdminSetting.set("maintenance_mode", form.maintenance_mode.data)
            AdminSetting.set("trial_duration_days", form.trial_duration_days.data)
            AdminSetting.set("trial_daily_limit", form.trial_daily_limit.data)
            flash('Settings updated successfully!', 'success')
            return redirect(url_for('admin_bp.admin_settings')) # Redirect untuk mencegah resubmit
        except Exception as e:
            print(f"ERROR (admin.py - admin_settings POST): Error updating admin settings: {e}")
            flash(f"Error updating settings: {str(e)}", 'danger')

    # Populate form dengan settings saat ini pada request GET
    try:
        form.maintenance_mode.data = AdminSetting.get("maintenance_mode", False)
        form.trial_duration_days.data = AdminSetting.get("trial_duration_days", 3)
        form.trial_daily_limit.data = AdminSetting.get("trial_daily_limit", 10)
    except Exception as e:
        print(f"ERROR (admin.py - admin_settings GET): Error fetching admin settings for form: {e}")
        flash("Error fetching current settings. Using defaults for display.", "warning")
        # Jika get gagal, form akan menggunakan defaultnya jika ada, atau kosong

    return render_template('admin_settings.html', form=form, title="Admin Settings")