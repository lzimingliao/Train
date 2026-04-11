import os
import secrets
from datetime import datetime

from flask import Flask, abort, request, session
from sqlalchemy import text

from models import Train, User
from train_app.extensions import db
from train_app.routes import main_bp
from train_app.utils.cache import user_cache
from utils import ensure_route_template, refresh_train_remaining_seats


def create_app(test_config=None):
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(basedir, "templates"),
        static_folder=os.path.join(basedir, "static"),
    )
    db_path = os.path.join(basedir, "tickets.db")
    reset_db = os.getenv("RESET_DB", "0") == "1"
    database_uri = os.getenv("DATABASE_URL")

    app.config["SEED_DATA"] = os.getenv("SEED_DATA", "1") == "1"

    if reset_db and not database_uri and os.path.exists(db_path):
        os.remove(db_path)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri or (
        "sqlite:///" + os.path.join(basedir, "tickets.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    if test_config:
        app.config.update(test_config)

    seed_enabled = app.config.get("SEED_DATA", True)

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

        def has_column(table_name, col_name):
            rows = db.session.execute(
                text(f'PRAGMA table_info("{table_name}")')
            ).fetchall()
            return any(row[1] == col_name for row in rows)

        def apply_lightweight_migrations():
            # SQLite compatibility migrations for existing local DB files.
            if not has_column("train", "route_template_id"):
                db.session.execute(
                    text("ALTER TABLE train ADD COLUMN route_template_id VARCHAR(50)")
                )
            if not has_column("train", "dynamic_alloc_state"):
                db.session.execute(
                    text(
                        "ALTER TABLE train ADD COLUMN dynamic_alloc_state TEXT DEFAULT '{}'"
                    )
                )
            if not has_column("train", "dynamic_alloc_at"):
                db.session.execute(
                    text("ALTER TABLE train ADD COLUMN dynamic_alloc_at DATETIME")
                )

            if not has_column("order", "board_stop"):
                db.session.execute(
                    text('ALTER TABLE "order" ADD COLUMN board_stop VARCHAR(50)')
                )
            if not has_column("order", "alight_stop"):
                db.session.execute(
                    text('ALTER TABLE "order" ADD COLUMN alight_stop VARCHAR(50)')
                )
            if not has_column("order", "segment_span"):
                db.session.execute(
                    text('ALTER TABLE "order" ADD COLUMN segment_span TEXT')
                )
            if not has_column("order", "is_transfer_leg"):
                db.session.execute(
                    text(
                        'ALTER TABLE "order" ADD COLUMN is_transfer_leg BOOLEAN DEFAULT 0'
                    )
                )
            if not has_column("order", "bundle_id"):
                db.session.execute(
                    text('ALTER TABLE "order" ADD COLUMN bundle_id VARCHAR(50)')
                )

            db.session.commit()

        apply_lightweight_migrations()

        if seed_enabled and not User.query.first():
            admin = User(
                username="admin",
                name="超级管理员",
                id_num="000000000000000000",
                role="admin",
            )
            admin.set_password("Admin123_")
            db.session.add(admin)
            db.session.commit()
            print("初始化完成：仅创建管理员账号。")

        all_trains = Train.query.all()
        for train in all_trains:
            ensure_route_template(train, db)
            refresh_train_remaining_seats(train)
        db.session.commit()
        print(f"初始化完成：已为 {len(all_trains)} 个班次补齐经停模板与区间配额。")

        all_users = User.query.all()
        user_cache.usernames.clear()
        user_cache.id_nums.clear()
        user_cache.load_data(all_users)
        print(f"初始化完成：已加载 {len(all_users)} 个用户到哈希查重缓存。")

    return app


__all__ = ["create_app"]
