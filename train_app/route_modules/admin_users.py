from flask import current_app, flash, redirect, render_template, request, url_for

from train_app.extensions import db
from train_app.models import Order, User
from train_app.routes import main_bp, permission_required
from train_app.utils.cache import user_cache
from train_app.utils.validators import validate_phone


@main_bp.route("/users")
@permission_required("user_module", "manage")
def users_page():
    return render_template(
        "index.html",
        active_tab="users",
        users=User.query.order_by(User.id_num.asc()).all(),
    )


@main_bp.route("/admin_manage_user", methods=["POST"])
@permission_required("user_module", "manage")
def admin_manage_user():
    action = request.form.get("action")
    id_num = request.form.get("id_num")
    user = User.query.filter_by(id_num=id_num).first()

    if not user:
        flash("未找到该用户", "error")
        return redirect(url_for("main.users_page"))

    if action == "edit":
        phone = request.form.get("phone")
        if phone and not validate_phone(phone):
            flash("手机号格式不正确，请输入11位手机号", "error")
            return redirect(url_for("main.users_page"))

        user.name = request.form.get("name")
        user.phone = phone
        try:
            db.session.commit()
            flash("用户信息已更新", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("admin_manage_user edit failed: %s", exc)
            flash("更新失败，请稍后重试", "error")

    elif action == "delete" and user.role != "admin":
        active_order = Order.query.filter(
            Order.user_id == user.user_id,
            Order.status.in_(["已出票", "已改签"]),
        ).first()
        if active_order:
            flash("删除失败：该用户仍存在有效订单，请先退票", "error")
            return redirect(url_for("main.users_page"))

        try:
            username_to_remove = user.username
            id_num_to_remove = user.id_num
            db.session.delete(user)
            db.session.commit()
            user_cache.remove_user(username_to_remove, id_num_to_remove)
            flash("用户已删除", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("admin_manage_user delete failed: %s", exc)
            flash("删除失败：仍存在关联订单", "error")

    elif action == "delete" and user.role == "admin":
        flash("管理员账号不支持删除", "error")

    return redirect(url_for("main.users_page"))
