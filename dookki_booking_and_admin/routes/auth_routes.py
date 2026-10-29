import sqlite3
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db_connection

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        try:
            user = conn.execute(
                'SELECT id, username, password_hash, full_name, role '
                'FROM users WHERE username = ?',
                (username,)
            ).fetchone()
        finally:
            conn.close()

        valid_role = user and user['role'] in {'admin', 'customer'}
        valid_password = (
            user and user['password_hash'] and
            check_password_hash(user['password_hash'], password)
        )
        if valid_role and valid_password:
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            flash('Đăng nhập thành công.', 'success')
            if user['role'] == 'admin':
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('customer.booking_form'))
        flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not full_name or not username or not password:
            flash('Vui lòng nhập đầy đủ thông tin.', 'warning')
        elif len(username) < 3:
            flash('Tên đăng nhập phải có ít nhất 3 ký tự.', 'warning')
        elif len(password) < 6:
            flash('Mật khẩu phải có ít nhất 6 ký tự.', 'warning')
        elif password != confirm_password:
            flash('Mật khẩu xác nhận không khớp.', 'danger')
        else:
            conn = get_db_connection()
            try:
                existing_user = conn.execute(
                    'SELECT 1 FROM users WHERE username = ?', (username,)
                ).fetchone()
                if existing_user:
                    flash(
                        f'Tên đăng nhập “{username}” đã được sử dụng. '
                        'Hãy chọn tên khác hoặc đăng nhập nếu đây là tài khoản của bạn.',
                        'danger'
                    )
                else:
                    # Database phiên bản cũ vẫn còn cột `password` bắt buộc.
                    # Ghi rỗng vào cột cũ; mật khẩu thật chỉ lưu dạng hash.
                    user_columns = {
                        row['name'] for row in conn.execute('PRAGMA table_info(users)')
                    }
                    if 'password' in user_columns:
                        conn.execute(
                            '''INSERT INTO users
                               (username, password_hash, full_name, role, created_at, password)
                               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)''',
                            (username, generate_password_hash(password), full_name, 'customer', '')
                        )
                    else:
                        conn.execute(
                            '''INSERT INTO users (username, password_hash, full_name, role, created_at)
                               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                            (username, generate_password_hash(password), full_name, 'customer')
                        )
                    conn.commit()
                    flash('Đăng ký thành công. Hãy đăng nhập để đặt bàn.', 'success')
                    return redirect(url_for('auth.login'))
            except sqlite3.IntegrityError as error:
                conn.rollback()
                if 'users.username' in str(error):
                    flash(
                        f'Tên đăng nhập “{username}” vừa được tài khoản khác sử dụng. '
                        'Hãy chọn tên khác.',
                        'danger'
                    )
                else:
                    current_app.logger.exception('Không thể lưu tài khoản đăng ký.')
                    flash('Thông tin đăng ký chưa hợp lệ. Vui lòng kiểm tra lại.', 'danger')
            except sqlite3.Error:
                conn.rollback()
                current_app.logger.exception('Lỗi database khi đăng ký tài khoản.')
                flash('Không thể tạo tài khoản lúc này. Vui lòng thử lại.', 'danger')
            finally:
                conn.close()
    return render_template('auth/register.html')


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Bạn đã đăng xuất.', 'success')
    return redirect(url_for('auth.login'))
