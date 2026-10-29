from flask import Flask
from database import init_db
from routes.customer_routes import customer_bp
from routes.admin_routes import admin_bp
from routes.auth_routes import auth_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object('config')

    # Khởi tạo cơ sở dữ liệu SQLite tự động
    init_db()

    # Đăng ký Blueprints (Gắn kết các module route vào ứng dụng)
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    return app


app = create_app()


if __name__ == '__main__':
    print('\n=== DOOKKI BOOKING ===')
    print('Trang khách hàng: http://127.0.0.1:5000/booking')
    print('Trang đăng nhập: http://127.0.0.1:5000/auth/login')
    print('Trang quản trị Admin: http://127.0.0.1:5000/admin/dashboard')
    print('Lưu ý: cần đăng nhập bằng tài khoản có quyền admin để mở trang quản trị.\n')
    app.run(debug=True)
