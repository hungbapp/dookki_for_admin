import random
import string
from datetime import datetime, timedelta

from database import get_db_connection, get_next_daily_order_number


BOOKING_DURATION_MINUTES = 105

class BookingModel:
    @staticmethod
    def get_available_tables(date, time, area=None, num_people=None):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM tables WHERE 1=1'
        params = []
        
        if area:
            query += ' AND area = ?'
            params.append(area)
            
        # Tự động lọc bàn có sức chứa >= số lượng khách
        if num_people:
            if area == 'Phòng VIP':
                query += ' AND capacity = 16'
            else:
                query += ' AND capacity >= ?'
                params.append(num_people)

        query += ' ORDER BY capacity ASC, table_number ASC'
        
        cursor.execute(query, params)
        tables = [dict(row) for row in cursor.fetchall()]

        try:
            req_start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except:
            req_start_dt = datetime.now()

        results = []
        now = datetime.now()

        for t in tables:
            req_end_dt = req_start_dt + timedelta(minutes=BOOKING_DURATION_MINUTES)

            cursor.execute('''
                SELECT id, customer_name, booking_date, booking_time, area, status 
                FROM bookings 
                WHERE table_id = ? AND booking_date = ? AND deleted_at IS NULL
                  AND TRIM(COALESCE(status, '')) NOT IN ('Đã hủy', 'đã hủy', 'cancelled')
            ''', (t['id'], date))
            
            booked_list = cursor.fetchall()
            is_booked = False
            booking_info = None

            for b in booked_list:
                try:
                    b_start_dt = datetime.strptime(f"{b['booking_date']} {b['booking_time']}", "%Y-%m-%d %H:%M")
                except:
                    continue

                b_end_dt = b_start_dt + timedelta(minutes=BOOKING_DURATION_MINUTES)

                # Quá 15 phút so với giờ đặt mà khách chưa đến -> Tự động hủy đơn, giải phóng bàn
                if now > b_start_dt + timedelta(minutes=15) and b['status'] == 'Chờ xác nhận':
                    cursor.execute('UPDATE bookings SET status = "Đã hủy" WHERE id = ?', (b['id'],))
                    conn.commit()
                    continue

                if max(req_start_dt, b_start_dt) < min(req_end_dt, b_end_dt):
                    is_booked = True
                    remaining_mins = int((b_end_dt - req_start_dt).total_seconds() / 60)
                    booking_info = {
                        'customer_name': b['customer_name'],
                        'booking_time': b['booking_time'],
                        'status': b['status'],
                        'remaining_mins': max(0, remaining_mins)
                    }
                    break

            table_data = dict(t)
            table_data['is_booked'] = is_booked
            if is_booked and booking_info:
                table_data['booked_by'] = booking_info['customer_name']
                table_data['booking_time'] = booking_info['booking_time']
                table_data['status'] = booking_info['status']
                table_data['remaining_mins'] = booking_info['remaining_mins']
            
            results.append(table_data)

        conn.close()
        return results

    @staticmethod
    def create_booking(data):
        conn = get_db_connection()
        cursor = conn.cursor()
        conn.execute('BEGIN IMMEDIATE')
        daily_order_number = get_next_daily_order_number(cursor, data['booking_date'])
        booking_code = ''.join(random.choices(string.digits, k=6))
        cursor.execute('''
            INSERT INTO bookings (
                customer_name, phone, booking_date, booking_time, num_people,
                area, table_id, note, status, booking_code, daily_order_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['customer_name'],
            data['phone'],
            data['booking_date'],
            data['booking_time'],
            data['num_people'],
            data['area'],
            data.get('table_id'),
            data.get('note', ''),
            'Chờ xác nhận',
            booking_code,
            daily_order_number
        ))
        conn.commit()
        booking_id = cursor.lastrowid
        conn.close()
        return booking_id

    @staticmethod
    def get_booking_by_id(booking_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT b.*, t.table_number 
            FROM bookings b
            LEFT JOIN tables t ON b.table_id = t.id
            WHERE b.id = ?
        ''', (booking_id,))
        booking = cursor.fetchone()
        conn.close()
        return booking
