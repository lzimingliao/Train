import os
import secrets
from datetime import datetime

from flask import Flask, abort, request, session

from extensions import db
from models import Train, User
from routes import main_bp
from utils import init_seats, user_cache


def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(basedir, "tickets.db")
    reset_db = os.getenv("RESET_DB", "0") == "1"

    if reset_db and os.path.exists(db_path):
        os.remove(db_path)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        basedir, "tickets.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    seed_enabled = os.getenv("SEED_DATA", "1") == "1"

    db.init_app(app)

    app.register_blueprint(main_bp)

    def get_or_create_csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(24)
            session["_csrf_token"] = token
        return token

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            sent_token = request.form.get("csrf_token", "")
            expected_token = session.get("_csrf_token", "")
            if not expected_token or sent_token != expected_token:
                abort(400, description="CSRF token invalid")

    @app.context_processor
    def inject_template_context():
        return {
            "now_time": datetime.now(),
            "csrf_token": get_or_create_csrf_token(),
        }

    with app.app_context():
        db.create_all()

        if seed_enabled and not User.query.first():
            admin = User(
                username="admin",
                name="超级管理员",
                id_num="000000000000000000",
                role="admin",
            )
            admin.set_password("Admin123!")
            db.session.add(admin)

            u1 = User(
                username="testuser",
                name="廖子明",
                id_num="110105199001011234",
                phone="15310627180",
                role="user",
            )
            u1.set_password("Pass1234!")
            db.session.add(u1)

            t1 = Train(
                train_no="C901",
                dep_station="重庆",
                arr_station="成都",
                dep_time=datetime(2026, 4, 19, 13, 30),
                arr_time=datetime(2026, 4, 19, 15, 10),
                price=96.0,
                total_seats=120,
                rem_seats=120,
                carriage_count=8,
                seat_map=init_seats(120),
            )
            t2 = Train(
                train_no="C901",
                dep_station="重庆",
                arr_station="成都",
                dep_time=datetime(2026, 4, 20, 13, 30),
                arr_time=datetime(2026, 4, 20, 15, 10),
                price=96.0,
                total_seats=120,
                rem_seats=120,
                carriage_count=8,
                seat_map=init_seats(120),
            )
            t3 = Train(
                train_no="G711",
                dep_station="武汉",
                arr_station="重庆",
                dep_time=datetime(2026, 4, 19, 14, 0),
                arr_time=datetime(2026, 4, 19, 18, 40),
                price=238.0,
                total_seats=100,
                rem_seats=100,
                carriage_count=8,
                seat_map=init_seats(100),
            )
            t4 = Train(
                train_no="G711",
                dep_station="武汉",
                arr_station="重庆",
                dep_time=datetime(2026, 4, 20, 14, 0),
                arr_time=datetime(2026, 4, 20, 18, 40),
                price=238.0,
                total_seats=100,
                rem_seats=100,
                carriage_count=8,
                seat_map=init_seats(100),
            )
            t5 = Train(
                train_no="D532",
                dep_station="成都",
                arr_station="武汉",
                dep_time=datetime(2026, 4, 19, 15, 20),
                arr_time=datetime(2026, 4, 19, 21, 5),
                price=264.0,
                total_seats=110,
                rem_seats=110,
                carriage_count=8,
                seat_map=init_seats(110),
            )

            db.session.add_all([t1, t2, t3, t4, t5])
            db.session.commit()
            print("初始化测试数据已插入！")

        all_users = User.query.all()
        user_cache.load_data(all_users)
        print(f"初始化完成：已加载 {len(all_users)} 个用户到哈希查重缓存。")

    return app


if __name__ == "__main__":
    app = create_app()
    print("🚀 系统已启动！请在浏览器访问: http://127.0.0.1:8080")
    app.run(debug=True, port=8080)
