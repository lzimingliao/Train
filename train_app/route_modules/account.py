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
from train_app.routes import main_bp
from train_app.utils.cache import user_cache
from train_app.utils.validators import validate_id, validate_password, validate_phone


@main_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username")
    password = request.form.get("password")
    name = request.form.get("name")
    id_num = request.form.get("id_num")
    phone = request.form.get("phone")

    if not all([username, password, name, id_num]):
        flash("请完整填写注册信息后再提交", "error")
        return redirect(url_for("main.register_page"))

    if user_cache.is_username_exist(username):
        flash("该用户名已被占用，请更换后重试", "error")
        return redirect(url_for("main.register_page"))

    if user_cache.is_id_num_exist(id_num):
        flash("该身份证号已注册，请直接登录或找回账号", "error")
        return redirect(url_for("main.register_page"))

    if not validate_id(id_num):
        flash("身份证号格式不正确，请输入18位身份证号（末位可为X）", "error")
        return redirect(url_for("main.register_page"))

    if phone and not validate_phone(phone):
        flash("手机号格式不正确，请输入11位手机号", "error")
        return redirect(url_for("main.register_page"))

    is_valid, msg = validate_password(password)
    if not is_valid:
        flash(msg, "error")
        return redirect(url_for("main.register_page"))

    new_user = User(username=username, name=name, id_num=id_num, phone=phone)
    new_user.set_password(password)

    try:
        db.session.add(new_user)
        db.session.commit()
        user_cache.add_user(username, id_num)
        flash("注册成功，欢迎使用。请先登录", "success")
        return redirect(url_for("main.login_page"))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("register_page failed: %s", exc)
        flash("注册未成功，请稍后再试", "error")
        return redirect(url_for("main.register_page"))


@main_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")
    if not all([username, password]):
        flash("请输入用户名和密码后再登录", "error")
        return redirect(url_for("main.login_page"))

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        session["user_id"] = user.user_id
        session["username"] = user.username
        session["role"] = user.role
        session["name"] = user.name
        session["id_num"] = user.id_num
        return redirect(url_for("main.index"))

    flash("登录失败，用户名或密码不正确", "error")
    return redirect(url_for("main.login_page"))


@main_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login_page"))
