import sqlite3
from config import DB_NAME
from werkzeug.security import generate_password_hash

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def get_next_daily_order_number(cursor, booking_date):
    """Return the lowest unused order number for one booking date."""
    used_numbers = {
        row['daily_order_number']
        for row in cursor.execute(
            'SELECT daily_order_number FROM bookings WHERE booking_date = ?',
            (booking_date,)
        ).fetchall()
        if row['daily_order_number'] is not None
    }
    number = 1
    while number in used_numbers:
        number += 1
    return number

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Bảng quản lý bàn ăn
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_number TEXT NOT NULL UNIQUE,
            capacity INTEGER NOT NULL,
            area TEXT NOT NULL
        )
    ''')
    
    # 2. Bảng quản lý đơn đặt bàn
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            num_people INTEGER NOT NULL,
            area TEXT NOT NULL,
            table_id INTEGER,
            note TEXT,
            status TEXT DEFAULT 'Chờ xác nhận',
            booking_code TEXT,
            daily_order_number INTEGER,
            deleted_at TEXT,
            FOREIGN KEY (table_id) REFERENCES tables (id)
        )
    ''')

    # 3. Bảng tài khoản theo cấu trúc hiện tại của luồng đăng nhập và quản trị.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'customer',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Nâng cấp bảng users được tạo bởi phiên bản cũ, vốn lưu mật khẩu trong
    # cột `password` và chưa có thông tin tên/ ngày tạo tài khoản.
    user_columns = {
        row['name'] for row in cursor.execute('PRAGMA table_info(users)').fetchall()
    }
    if 'password_hash' not in user_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN password_hash TEXT')
    if 'full_name' not in user_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN full_name TEXT')
    if 'role' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'customer'")
    if 'created_at' not in user_columns:
        cursor.execute('ALTER TABLE users ADD COLUMN created_at TEXT')

    user_columns = {
        row['name'] for row in cursor.execute('PRAGMA table_info(users)').fetchall()
    }
    has_legacy_password = 'password' in user_columns
    select_columns = 'id, username, password_hash, full_name, role, created_at'
    if has_legacy_password:
        select_columns += ', password'

    for user in cursor.execute(f'SELECT {select_columns} FROM users').fetchall():
        password_hash = user['password_hash']
        if has_legacy_password and not password_hash and user['password']:
            password_hash = generate_password_hash(user['password'])

        full_name = (user['full_name'] or '').strip() or user['username']
        role = user['role'] or 'customer'
        if role == 'user':
            role = 'customer'

        if has_legacy_password:
            cursor.execute(
                '''UPDATE users
                   SET password_hash = ?, full_name = ?, role = ?,
                       created_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP),
                       password = ''
                   WHERE id = ?''',
                (password_hash, full_name, role, user['id'])
            )
        else:
            cursor.execute(
                '''UPDATE users
                   SET password_hash = ?, full_name = ?, role = ?,
                       created_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP)
                   WHERE id = ?''',
                (password_hash, full_name, role, user['id'])
            )

    # Tạo tài khoản admin mặc định nếu chưa có admin. Nếu tài khoản `admin` đã
    # tồn tại trong DB cũ, giữ nguyên mật khẩu của tài khoản đó và cấp role admin.
    admin = cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if admin is None:
        existing_admin = cursor.execute(
            "SELECT id FROM users WHERE username = 'admin'"
        ).fetchone()
        if existing_admin:
            cursor.execute(
                "UPDATE users SET role = 'admin' WHERE id = ?",
                (existing_admin['id'],)
            )
        else:
            cursor.execute(
                '''INSERT INTO users (username, password_hash, full_name, role, created_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                ('admin', generate_password_hash('admin123'), 'Quản trị viên', 'admin')
            )

    # Đảm bảo thêm cột booking_code nếu database cũ chưa có
    try:
        cursor.execute('ALTER TABLE bookings ADD COLUMN booking_code TEXT')
    except sqlite3.OperationalError:
        pass

    booking_columns = {
        row['name'] for row in cursor.execute('PRAGMA table_info(bookings)').fetchall()
    }
    if 'daily_order_number' not in booking_columns:
        cursor.execute('ALTER TABLE bookings ADD COLUMN daily_order_number INTEGER')
    if 'deleted_at' not in booking_columns:
        cursor.execute('ALTER TABLE bookings ADD COLUMN deleted_at TEXT')

    # Gán số thứ tự theo ngày cho các đơn đã có trong cơ sở dữ liệu cũ.
    unnumbered_dates = cursor.execute('''
        SELECT DISTINCT booking_date
        FROM bookings
        WHERE daily_order_number IS NULL
        ORDER BY booking_date
    ''').fetchall()
    for date_row in unnumbered_dates:
        booking_date = date_row['booking_date']
        next_number = cursor.execute(
            'SELECT COALESCE(MAX(daily_order_number), 0) FROM bookings WHERE booking_date = ?',
            (booking_date,)
        ).fetchone()[0]
        old_bookings = cursor.execute('''
            SELECT id FROM bookings
            WHERE booking_date = ? AND daily_order_number IS NULL
            ORDER BY id ASC
        ''', (booking_date,)).fetchall()
        for booking in old_bookings:
            next_number += 1
            cursor.execute(
                'UPDATE bookings SET daily_order_number = ? WHERE id = ?',
                (next_number, booking['id'])
            )

    # Thêm dữ liệu mẫu các bàn ăn nếu bảng đang trống
    cursor.execute('SELECT COUNT(*) FROM tables')
    if cursor.fetchone()[0] == 0:
        sample_tables = [
            # Gần cửa sổ
            ('W-01', 2, 'Gần cửa sổ'), ('W-02', 2, 'Gần cửa sổ'),
            ('W-03', 4, 'Gần cửa sổ'), ('W-04', 4, 'Gần cửa sổ'),
            ('W-05', 8, 'Gần cửa sổ'), ('W-06', 8, 'Gần cửa sổ'),

            # Khu vực tiêu chuẩn
            ('S-01', 8, 'Khu vực tiêu chuẩn'), ('S-02', 8, 'Khu vực tiêu chuẩn'),
            ('S-09', 8, 'Khu vực tiêu chuẩn'), ('S-10', 8, 'Khu vực tiêu chuẩn'),
            ('S-03', 4, 'Khu vực tiêu chuẩn'), ('S-04', 4, 'Khu vực tiêu chuẩn'), ('S-05', 4, 'Khu vực tiêu chuẩn'),
            ('S-06', 2, 'Khu vực tiêu chuẩn'), ('S-07', 2, 'Khu vực tiêu chuẩn'), ('S-08', 2, 'Khu vực tiêu chuẩn'),

            # Gần quầy buffet
            ('T-01', 4, 'Gần quầy buffet'), ('T-02', 4, 'Gần quầy buffet'), ('T-03', 4, 'Gần quầy buffet'), ('T-10', 4, 'Gần quầy buffet'),
            ('T-04', 8, 'Gần quầy buffet'), ('T-05', 8, 'Gần quầy buffet'),
            ('T-06', 2, 'Gần quầy buffet'), ('T-07', 2, 'Gần quầy buffet'), ('T-08', 2, 'Gần quầy buffet'), ('T-09', 2, 'Gần quầy buffet'),

            # Phòng VIP
            ('VIP-01', 16, 'Phòng VIP'),
            ('VIP-02', 16, 'Phòng VIP')
        ]
        cursor.executemany('INSERT INTO tables (table_number, capacity, area) VALUES (?, ?, ?)', sample_tables)
    
    conn.commit()
    conn.close()
