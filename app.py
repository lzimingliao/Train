import os
from datetime import datetime

from flask import Flask

from extensions import db
from models import Train, User
from routes import main_bp
from utils import init_seats, user_cache


def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        basedir, "tickets.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    seed_enabled = os.getenv("SEED_DATA", "1") == "1"

    db.init_app(app)

    app.register_blueprint(main_bp)

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
                name="张三",
                id_num="110105199001011234",
                phone="13800138000",
                role="user",
            )
            u1.set_password("Pass1234!")
            db.session.add(u1)

            t1 = Train(
                train_no="G101",
                dep_station="北京",
                arr_station="上海",
                dep_time=datetime(2026, 3, 1, 8, 0),
                arr_time=datetime(2026, 3, 1, 13, 0),
                price=55.0,
                total_seats=50,
                rem_seats=50,
                carriage_count=5,
                seat_map=init_seats(50),
            )
            t2 = Train(
                train_no="G102",
                dep_station="北京",
                arr_station="上海",
                dep_time=datetime(2026, 3, 1, 9, 30),
                arr_time=datetime(2026, 3, 1, 14, 30),
                price=55.20,
                total_seats=100,
                rem_seats=100,
                carriage_count=5,
                seat_map=init_seats(100),
            )
            t3 = Train(
                train_no="G103",
                dep_station="北京",
                arr_station="上海",
                dep_time=datetime(2026, 3, 1, 10, 30),
                arr_time=datetime(2026, 3, 1, 15, 30),
                price=55.20,
                total_seats=100,
                rem_seats=100,
                carriage_count=5,
                seat_map=init_seats(100),
            )
            t4 = Train(
                train_no="G201",
                dep_station="南京",
                arr_station="上海",
                dep_time=datetime(2026, 3, 1, 9, 30),
                arr_time=datetime(2026, 3, 1, 11, 30),
                price=55.20,
                total_seats=100,
                rem_seats=100,
                carriage_count=5,
                seat_map=init_seats(100),
            )

            db.session.add_all([t1, t2, t3, t4])
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
