from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    flash,
    redirect,
    session,
    url_for,
)

from train_app.models import Order
from train_app.utils.permissions import perm_tree

main_bp = Blueprint("main", __name__)


def get_user_orders(user_id):
    return (
        Order.query.filter_by(user_id=user_id).order_by(Order.booking_time.desc()).all()
    )


def get_active_orders(user_id):
    return Order.query.filter(
        Order.user_id == user_id,
        Order.status.in_(["已出票", "已改签"]),
        Order.dep_time > datetime.now(),
    ).all()


def is_departed(dep_time):
    return dep_time <= datetime.now()


def permission_required(module, function):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("main.login_page"))
            if not perm_tree.check_permission(
                session.get("role", "user"), module, function
            ):
                flash("当前账号暂无该功能权限", "error")
                return redirect(url_for("main.index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


# Register account routes from a dedicated module.
from train_app.route_modules import account as _account_routes  # noqa: F401
from train_app.route_modules import admin_trains as _admin_train_routes  # noqa: F401
from train_app.route_modules import admin_users as _admin_user_routes  # noqa: F401
from train_app.route_modules import orders as _orders_routes  # noqa: F401
from train_app.route_modules import profile as _profile_routes  # noqa: F401
from train_app.route_modules import ticketing as _ticketing_routes  # noqa: F401
