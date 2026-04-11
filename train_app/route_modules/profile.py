from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from train_app.extensions import db
from train_app.models import User
from train_app.routes import main_bp, permission_required
from train_app.utils.cache import user_cache
from train_app.utils.validators import validate_phone


@main_bp.route("/profile")
@permission_required("user_module", "info")
def profile_page():
    user = User.query.get(session.get("user_id"))
    return render_template("index.html", active_tab="profile", user=user)


@main_bp.route("/update_profile", methods=["POST"])
@permission_required("user_module", "info")
def update_profile():
    user = User.query.get(session.get("user_id"))
    new_username = request.form.get("username", "").strip()
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()

    if not new_username or not name:
        flash("用户名和姓名不能为空", "error")
        return redirect(url_for("main.profile_page"))

    if phone and not validate_phone(phone):
        flash("手机号格式不正确，请输入11位手机号", "error")
        return redirect(url_for("main.profile_page"))

    if new_username != user.username:
        if user_cache.is_username_exist(new_username):
            flash("该用户名已被占用，请更换后重试", "error")
            return redirect(url_for("main.profile_page"))
        user_cache.update_username(user.username, new_username)
        user.username = new_username

    user.name = name
    user.phone = phone

    try:
        db.session.commit()
        session["username"] = user.username
        session["name"] = user.name
        flash("个人信息已更新", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("update_profile failed: %s", exc)
        flash("保存未成功，请稍后重试", "error")

    return redirect(url_for("main.profile_page"))
