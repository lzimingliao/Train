from datetime import datetime
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from extensions import db
from models import Order, Train, User
from utils import (
    allocate_seat_by_type,
    bubble_sort_by_time,
    free_seat,
    init_seats,
    perm_tree,
    quick_sort_trains,
    user_cache,
    validate_id,
    validate_password,
    validate_phone,
)

main_bp = Blueprint("main", __name__)


def permission_required(module, function):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("main.login_page"))
            if not perm_tree.check_permission(
                session.get("role", "user"), module, function
            ):
                flash("权限不足，已被安全系统拦截", "error")
                return redirect(url_for("main.index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator


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
        flash("注册失败：请填写所有必填信息", "error")
        return redirect(url_for("main.register_page"))

    if user_cache.is_username_exist(username):
        flash("注册失败：该用户名已被注册", "error")
        return redirect(url_for("main.register_page"))

    if user_cache.is_id_num_exist(id_num):
        flash("注册失败：该身份证号已被注册", "error")
        return redirect(url_for("main.register_page"))

    if not validate_id(id_num):
        flash("身份证号格式无效（需18位，最后一位支持X）", "error")
        return redirect(url_for("main.register_page"))

    if phone and not validate_phone(phone):
        flash("手机号格式无效（必须为11位数字）", "error")
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
        flash(
            f"实名档案建立成功！您的系统分配唯一ID为：{new_user.user_id}，请登录使用系统。",
            "success",
        )
        return redirect(url_for("main.login_page"))
    except Exception:
        db.session.rollback()
        flash("服务器繁忙，注册失败请重试", "error")
        return redirect(url_for("main.register_page"))


@main_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role")

    if not all([username, password]):
        flash("请输入用户名和密码", "error")
        return redirect(url_for("main.login_page"))

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password) and user.role == role:
        session["user_id"] = user.user_id
        session["username"] = user.username
        session["role"] = user.role
        session["name"] = user.name
        session["id_num"] = user.id_num
        return redirect(url_for("main.index"))

    flash("身份鉴权失败，请检查填写或身份切换", "error")
    return redirect(url_for("main.login_page"))


@main_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login_page"))


@main_bp.route("/")
@permission_required("ticket_module", "query")
def index():
    return render_template("index.html", active_tab="book", search_results=[])


@main_bp.route("/do_query")
@permission_required("ticket_module", "query")
def do_query():
    search_type = request.args.get("search_type")
    date_str = request.args.get("date")
    search_results = []

    if search_type == "interval":
        start_station = request.args.get("start_station", "")
        end_station = request.args.get("end_station", "")
        raw_trains = Train.query.filter(
            db.func.date(Train.dep_time) == date_str,
            Train.dep_station.ilike(f"%{start_station}%"),
            Train.arr_station.ilike(f"%{end_station}%"),
        ).all()
        search_results = quick_sort_trains(raw_trains)

    elif search_type == "station":
        station = request.args.get("station", "")
        raw_trains = Train.query.filter(
            db.func.date(Train.dep_time) == date_str,
            db.or_(
                Train.dep_station.ilike(f"%{station}%"),
                Train.arr_station.ilike(f"%{station}%"),
            ),
        ).all()
        search_results = bubble_sort_by_time(raw_trains)

    source_tab = request.args.get("source_tab", "book")
    reschedule_order_id = request.args.get("reschedule_order_id")

    return render_template(
        "index.html",
        active_tab=source_tab,
        search_results=search_results,
        reschedule_order_id=reschedule_order_id,
        searched=True,
    )


@main_bp.route("/book_ticket", methods=["POST"])
@permission_required("ticket_module", "book")
def book_ticket():
    train_no = request.form.get("train_no")
    seat_type = request.form.get("seat_type")
    train = Train.query.get(train_no)

    if not train or train.rem_seats <= 0:
        flash("票源紧张，该车次已无座", "error")
        return redirect(url_for("main.index"))

    new_seat_map, seat = allocate_seat_by_type(train.seat_map, seat_type)
    if not seat:
        flash("您偏好的位置或该车次已售罄", "error")
        return redirect(url_for("main.index"))

    try:
        train.seat_map = new_seat_map
        train.rem_seats -= 1

        new_order = Order(
            user_id=session.get("user_id"),
            train_no=train.train_no,
            dep_station=train.dep_station,
            arr_station=train.arr_station,
            dep_time=train.dep_time,
            seat_no=seat,
            price=train.price,
        )
        db.session.add(new_order)
        db.session.commit()
        flash("🎉 出票成功！", "success")

    except Exception:
        db.session.rollback()
        flash("系统繁忙，出票失败请重试", "error")
        return redirect(url_for("main.index"))

    orders = (
        Order.query.filter_by(user_id=session.get("user_id"))
        .order_by(Order.booking_time.desc())
        .all()
    )
    return render_template(
        "index.html", active_tab="refund", latest_order=new_order, orders=orders
    )


@main_bp.route("/refund_ui")
@permission_required("ticket_module", "refund")
def refund_ui():
    orders = (
        Order.query.filter_by(user_id=session.get("user_id"))
        .order_by(Order.booking_time.desc())
        .all()
    )
    return render_template("index.html", active_tab="refund", orders=orders)


@main_bp.route("/delete_order/<order_id>", methods=["POST"])
@permission_required("ticket_module", "refund")
def delete_order(order_id):
    order = Order.query.get(order_id)
    if order and order.user_id == session.get("user_id") and order.status != "已退票":
        try:
            train = Train.query.get(order.train_no)
            if train:
                train.seat_map = free_seat(train.seat_map, order.seat_no)
                train.rem_seats += 1
            order.status = "已退票"
            db.session.commit()
            flash("退票成功，资金已原路返回，座位已释放", "success")
        except Exception:
            db.session.rollback()
            flash("系统繁忙，退票失败请重试", "error")
    return redirect(url_for("main.refund_ui"))


@main_bp.route("/reschedule_ui")
@permission_required("ticket_module", "reschedule")
def reschedule_ui():
    active_orders = Order.query.filter(
        Order.user_id == session.get("user_id"), Order.status.in_(["已出票", "已改签"])
    ).all()
    return render_template(
        "index.html", active_tab="reschedule", active_orders=active_orders
    )


@main_bp.route("/do_reschedule", methods=["POST"])
@permission_required("ticket_module", "reschedule")
def do_reschedule():
    order = Order.query.get(request.form.get("order_id"))
    new_train_no = request.form.get("new_train_no", "").strip().upper()
    seat_type = request.form.get("seat_type")

    new_train = Train.query.get(new_train_no)

    if not order or order.user_id != session.get("user_id"):
        flash("非法操作", "error")
        return redirect(url_for("main.reschedule_ui"))

    if not new_train or new_train.rem_seats <= 0:
        flash("改签失败：目标车次不存在或已无票", "error")
        return redirect(url_for("main.reschedule_ui"))

    old_train = Train.query.get(order.train_no)

    is_valid_rule = (
        new_train.dep_station == old_train.dep_station
        and new_train.arr_station == old_train.arr_station
    )

    if not is_valid_rule:
        flash("改签失败：不符合同区间或同日期的改签规则", "error")
        return redirect(url_for("main.reschedule_ui"))

    new_map, new_seat = allocate_seat_by_type(new_train.seat_map, seat_type)
    if not new_seat:
        flash("改签失败：目标车次所需座位已售罄", "error")
        return redirect(url_for("main.reschedule_ui"))

    try:
        if old_train:
            old_train.seat_map = free_seat(old_train.seat_map, order.seat_no)
            old_train.rem_seats += 1

        new_train.seat_map = new_map
        new_train.rem_seats -= 1

        order.train_no = new_train.train_no
        order.seat_no = new_seat
        order.status = "已改签"
        order.booking_time = db.func.now()
        order.price = new_train.price
        order.dep_station = new_train.dep_station
        order.arr_station = new_train.arr_station
        order.dep_time = new_train.dep_time

        db.session.commit()
        flash(f"🔄 改签成功！您的新座位是 {new_seat}", "success")
    except Exception:
        db.session.rollback()
        flash("系统繁忙，改签失败请重试", "error")
        return redirect(url_for("main.reschedule_ui"))

    orders = (
        Order.query.filter_by(user_id=session.get("user_id"))
        .order_by(Order.booking_time.desc())
        .all()
    )
    return render_template(
        "index.html", active_tab="refund", latest_order=order, orders=orders
    )


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
        flash("保存失败：用户名和姓名不能为空", "error")
        return redirect(url_for("main.profile_page"))

    if new_username != user.username:
        if user_cache.is_username_exist(new_username):
            flash("保存失败：该登录名已被他人使用", "error")
            return redirect(url_for("main.profile_page"))
        user_cache.update_username(user.username, new_username)
        user.username = new_username

    user.name = name
    user.phone = phone

    try:
        db.session.commit()
        session["username"] = user.username
        session["name"] = user.name
        flash("个人资料已永久保存并生效！", "success")
    except Exception:
        db.session.rollback()
        flash("系统繁忙，保存失败", "error")

    return redirect(url_for("main.profile_page"))


@main_bp.route("/trains")
@permission_required("train_module", "manage")
def trains_page():
    return render_template(
        "index.html",
        active_tab="trains",
        trains=Train.query.order_by(Train.dep_time.asc()).all(),
    )


@main_bp.route("/users")
@permission_required("user_module", "manage")
def users_page():
    return render_template(
        "index.html",
        active_tab="users",
        users=User.query.order_by(User.id_num.asc()).all(),
    )


@main_bp.route("/admin_manage_train", methods=["POST"])
@permission_required("train_module", "manage")
def admin_manage_train():
    action = request.form.get("action")
    train_no = request.form.get("train_no", "").strip().upper()

    if action == "delete":
        if Order.query.filter(
            Order.train_no == train_no, Order.status.in_(["已出票", "已改签"])
        ).first():
            flash("无法删除：该车次正在承运中", "error")
        else:
            try:
                Train.query.filter_by(train_no=train_no).delete()
                db.session.commit()
                flash(f"已注销车次 {train_no}", "success")
            except Exception:
                db.session.rollback()
                flash("注销失败：可能存在关联的历史退票订单记录，受外键保护", "error")

    elif action == "add":
        if Train.query.get(train_no):
            flash("车次编号冲突", "error")
            return redirect(url_for("main.trains_page"))

        dep_time_str = request.form.get("dep_time", "").replace("T", " ")
        arr_time_str = request.form.get("arr_time", "").replace("T", " ")

        try:
            dep_time = datetime.strptime(dep_time_str, "%Y-%m-%d %H:%M")
            arr_time = datetime.strptime(arr_time_str, "%Y-%m-%d %H:%M")
            price = float(request.form.get("price", 0))
            total_seats = int(request.form.get("total_seats", 0))
            carriage_count = int(request.form.get("carriage_count", 5))
        except ValueError:
            flash("时间或数值格式填写错误", "error")
            return redirect(url_for("main.trains_page"))

        if dep_time >= arr_time:
            flash("逻辑错误：到达时间必须晚于出发时间", "error")
            return redirect(url_for("main.trains_page"))
        if price < 0 or total_seats < 0:
            flash("逻辑错误：票价和总座位数不能为负", "error")
            return redirect(url_for("main.trains_page"))

        t = Train(
            train_no=train_no,
            dep_station=request.form.get("dep_station"),
            arr_station=request.form.get("arr_station"),
            dep_time=dep_time,
            arr_time=arr_time,
            price=price,
            total_seats=total_seats,
            rem_seats=total_seats,
            carriage_count=carriage_count,
            seat_map=init_seats(total_seats),
        )
        try:
            db.session.add(t)
            db.session.commit()
            flash(f"已新增发布车次 {train_no}", "success")
        except Exception:
            db.session.rollback()
            flash("保存车次失败，数据库异常", "error")

    return redirect(url_for("main.trains_page"))


@main_bp.route("/admin_manage_user", methods=["POST"])
@permission_required("user_module", "manage")
def admin_manage_user():
    action = request.form.get("action")
    id_num = request.form.get("id_num")
    user = User.query.filter_by(id_num=id_num).first()

    if not user:
        flash("用户不存在", "error")
        return redirect(url_for("main.users_page"))

    if action == "edit":
        phone = request.form.get("phone")
        if phone and not validate_phone(phone):
            flash("手机号格式无效（必须为11位数字）", "error")
            return redirect(url_for("main.users_page"))

        user.name = request.form.get("name")
        user.phone = phone
        try:
            db.session.commit()
            flash("用户资料已强制更新", "success")
        except Exception:
            db.session.rollback()
            flash("更新失败", "error")

    elif action == "delete" and user.role != "admin":
        try:
            username_to_remove = user.username
            id_num_to_remove = user.id_num
            db.session.delete(user)
            db.session.commit()
            user_cache.remove_user(username_to_remove, id_num_to_remove)
            flash("用户档案已彻底销毁", "success")
        except Exception:
            db.session.rollback()
            flash("销毁失败：可能存在关联的历史订单数据，受外键保护", "error")

    return redirect(url_for("main.users_page"))
