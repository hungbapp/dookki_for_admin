import random
import string
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from database import get_db_connection, get_next_daily_order_number


customer_bp = Blueprint('customer', __name__)
BOOKING_DURATION_MINUTES = 105
CANCELLED_STATUSES = ('Đã hủy', 'đã hủy', 'cancelled')


def get_booking_conflict(cursor, table_id, booking_date, booking_time):
    """Return an active reservation overlapping the requested 105-minute slot."""
    try:
        requested_start = datetime.strptime(
            f"{booking_date} {booking_time}", "%Y-%m-%d %H:%M"
        )
    except (TypeError, ValueError):
        return None

    requested_end = requested_start + timedelta(minutes=BOOKING_DURATION_MINUTES)
    cursor.execute('''
        SELECT id, customer_name, booking_date, booking_time, status
        FROM bookings
        WHERE table_id = ? AND booking_date = ? AND deleted_at IS NULL
          AND TRIM(COALESCE(status, '')) NOT IN (?, ?, ?)
    ''', (table_id, booking_date, *CANCELLED_STATUSES))

    for booking in cursor.fetchall():
        try:
            existing_start = datetime.strptime(
                f"{booking['booking_date']} {booking['booking_time']}",
                "%Y-%m-%d %H:%M"
            )
        except (TypeError, ValueError):
            continue

        existing_end = existing_start + timedelta(minutes=BOOKING_DURATION_MINUTES)
        if requested_start < existing_end and existing_start < requested_end:
            return booking

    return None


def has_phone_booking_on_date(cursor, phone, booking_date):
    """Return whether this phone already has an active reservation that day."""
    cursor.execute('''
        SELECT id
        FROM bookings
        WHERE phone = ? AND booking_date = ?
          AND (deleted_at IS NOT NULL OR TRIM(COALESCE(status, '')) NOT IN (?, ?, ?))
        LIMIT 1
    ''', (phone, booking_date, *CANCELLED_STATUSES))
    return cursor.fetchone() is not None


@customer_bp.route('/', methods=['GET'])
def index():
    return redirect(url_for('customer.booking_form'))


@customer_bp.route('/booking', methods=['GET'])
def booking_form():
    return render_template('booking/index.html')


@customer_bp.route('/book', methods=['POST'])
def book_table():
    customer_name = request.form.get('customer_name')
    phone = request.form.get('phone')
    booking_date = request.form.get('booking_date')
    booking_time = request.form.get('booking_time')
    num_people = request.form.get('num_people')
    table_id = request.form.get('table_id')
    note = request.form.get('note')

    conn = get_db_connection()
    cursor = conn.cursor()
    conn.execute('BEGIN IMMEDIATE')

    try:
        datetime.strptime(f"{booking_date} {booking_time}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        conn.close()
        return jsonify({'success': False, 'message': 'Ngày hoặc giờ đặt bàn không hợp lệ.'})

    cursor.execute('SELECT area, table_number FROM tables WHERE id = ?', (table_id,))
    table_data = cursor.fetchone()
    if not table_data:
        conn.close()
        return jsonify({'success': False, 'message': 'Bàn đã chọn không hợp lệ.'})

    conflict = get_booking_conflict(cursor, table_id, booking_date, booking_time)
    if conflict:
        conn.close()
        return jsonify({
            'success': False,
            'message': f"Bàn {table_data['table_number']} đã được đặt trong khung giờ này. "
                       'Các lượt đặt cùng bàn cần cách nhau ít nhất 1 giờ 45 phút.'
        })

    if has_phone_booking_on_date(cursor, phone, booking_date):
        conn.close()
        return jsonify({
            'success': False,
            'message': f'Số điện thoại {phone} đã đặt bàn trong ngày {booking_date}. '
                       'Mỗi số điện thoại chỉ được đặt một bàn trong một ngày.'
        })

    booking_code = ''.join(random.choices(string.digits, k=6))
    daily_order_number = get_next_daily_order_number(cursor, booking_date)
    cursor.execute('''
        INSERT INTO bookings (
            customer_name, phone, booking_date, booking_time, num_people,
            area, table_id, note, status, booking_code, daily_order_number
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        customer_name, phone, booking_date, booking_time, num_people,
        table_data['area'], table_id, note, 'confirmed', booking_code,
        daily_order_number
    ))

    conn.commit()
    conn.close()
    return jsonify({
        'success': True,
        'code': booking_code,
        'name': customer_name,
        'table': table_data['table_number']
    })


@customer_bp.route('/api/lookup', methods=['GET'])
def lookup_booking():
    query = request.args.get('query', '').strip()
    conn = get_db_connection()
    row = conn.execute('''
        SELECT b.*, t.table_number
        FROM bookings b
        LEFT JOIN tables t ON b.table_id = t.id
        WHERE (b.phone = ? OR b.booking_code = ?)
          AND b.deleted_at IS NULL
        ORDER BY b.id DESC LIMIT 1
    ''', (query, query)).fetchone()
    conn.close()

    if row:
        return jsonify({
            'success': True,
            'data': {
                'code': row['booking_code'],
                'name': row['customer_name'],
                'date': row['booking_date'],
                'time': row['booking_time'],
                'table': row['table_number'],
                'status': row['status']
            }
        })
    return jsonify({'success': False, 'message': 'Không tìm thấy lịch sử đặt bàn với thông tin này!'})


@customer_bp.route('/api/get-tables', methods=['GET'])
def get_tables():
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    try:
        requested_start = datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        )
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Ngày hoặc giờ không hợp lệ.'}), 400

    requested_end = requested_start + timedelta(minutes=BOOKING_DURATION_MINUTES)
    conn = get_db_connection()
    cursor = conn.cursor()
    tables = cursor.execute('SELECT * FROM tables').fetchall()
    bookings = cursor.execute('''
        SELECT * FROM bookings
        WHERE booking_date = ? AND deleted_at IS NULL
          AND TRIM(COALESCE(status, '')) NOT IN (?, ?, ?)
    ''', (date_str, *CANCELLED_STATUSES)).fetchall()
    conn.close()

    bookings_by_table = {}
    for booking in bookings:
        if booking['table_id']:
            bookings_by_table.setdefault(booking['table_id'], []).append(booking)

    result = []
    for table in tables:
        table_status = 'available'
        booked_by = ''
        booking_time_str = ''
        for booking in bookings_by_table.get(table['id'], []):
            try:
                existing_start = datetime.strptime(
                    f"{booking['booking_date']} {booking['booking_time']}",
                    "%Y-%m-%d %H:%M"
                )
            except (TypeError, ValueError):
                continue

            existing_end = existing_start + timedelta(minutes=BOOKING_DURATION_MINUTES)
            if requested_start < existing_end and existing_start < requested_end:
                table_status = 'booked'
                booked_by = booking['customer_name']
                booking_time_str = booking['booking_time']
                break

        result.append({
            'id': table['id'],
            'table_number': table['table_number'],
            'capacity': table['capacity'],
            'area': table['area'],
            'status': table_status,
            'booked_by': booked_by,
            'booking_time': booking_time_str
        })

    return jsonify(result)
