from database import get_db_connection


def get_all_bookings(search_term=None):
    conn = get_db_connection()
    cur = conn.cursor()
    query = '''SELECT bookings.*, tables.table_number
               FROM bookings LEFT JOIN tables ON bookings.table_id = tables.id'''
    conditions = ['bookings.deleted_at IS NULL']
    params = []
    if search_term:
        conditions.append('(bookings.phone LIKE ? OR bookings.booking_code LIKE ?)')
        keyword = f'%{search_term}%'
        params.extend([keyword, keyword])
    query += ' WHERE ' + ' AND '.join(conditions)
    query += ' ORDER BY bookings.booking_date DESC, bookings.daily_order_number DESC, bookings.id DESC'
    cur.execute(query, params)
    bookings = cur.fetchall()
    conn.close()
    return bookings


def get_booking_count_for_date(booking_date):
    conn = get_db_connection()
    count = conn.execute(
        'SELECT COUNT(*) FROM bookings WHERE booking_date = ?',
        (booking_date,)
    ).fetchone()[0]
    conn.close()
    return count


def update_booking_status(booking_id, status):
    allowed_statuses = {'Chờ xác nhận', 'Đã xếp bàn', 'Đã đến', 'Đã hủy'}
    if status not in allowed_statuses:
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        UPDATE bookings SET status = ?
        WHERE id = ? AND deleted_at IS NULL
    ''', (status, booking_id))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def delete_booking(booking_id):
    conn = get_db_connection()
    cur = conn.cursor()
    conn.execute('BEGIN IMMEDIATE')
    booking = cur.execute('''
        SELECT status
        FROM bookings
        WHERE id = ? AND deleted_at IS NULL
    ''', (booking_id,)).fetchone()

    if booking is None:
        conn.close()
        return False

    if booking['status'] in {'Đã đến', 'Đã xếp bàn'}:
        # Ẩn đơn đã phục vụ nhưng giữ số thứ tự trong tổng ngày.
        cur.execute('''
            UPDATE bookings
            SET status = 'Đã hủy', deleted_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (booking_id,))
    else:
        # Xóa đơn chưa phục vụ để số của đơn đó được dùng lại.
        cur.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))

    conn.commit()
    conn.close()
    return True


def get_all_users(search_text=None):
    """Return account details without exposing password hashes."""
    conn = get_db_connection()
    query = '''SELECT id, username, full_name, role, created_at
               FROM users'''
    params = []
    if search_text:
        query += ' WHERE username LIKE ? OR full_name LIKE ?'
        keyword = f'%{search_text}%'
        params.extend([keyword, keyword])
    query += " ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, id DESC"
    users = conn.execute(query, params).fetchall()
    conn.close()
    return users


def update_user_role(user_id, new_role, current_admin_id):
    """Update a user's role with safeguards against self-lockout."""
    if new_role not in {'customer', 'admin'}:
        return False, 'Vai trò không hợp lệ.'
    if user_id == current_admin_id:
        return False, 'Không thể tự thay đổi quyền của tài khoản đang đăng nhập.'

    conn = get_db_connection()
    try:
        target = conn.execute('SELECT id, role FROM users WHERE id = ?', (user_id,)).fetchone()
        if target is None:
            return False, 'Không tìm thấy tài khoản.'
        if target['role'] == new_role:
            return True, 'Vai trò tài khoản không thay đổi.'
        if target['role'] == 'admin' and new_role != 'admin':
            admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            if admin_count <= 1:
                return False, 'Không thể hạ quyền quản trị viên cuối cùng của hệ thống.'
        conn.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))
        conn.commit()
        return True, 'Đã cập nhật quyền tài khoản.'
    finally:
        conn.close()
