import json
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

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
    validate_date_string,
    validate_id,
    validate_password,
    validate_phone,
    validate_station_name,
)

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


def resize_seat_map(seat_map_json, new_total):
    seats = json.loads(seat_map_json)
    if new_total <= len(seats):
        return json.dumps(seats[:new_total])
    seats.extend([False] * (new_total - len(seats)))
    return json.dumps(seats)


def permission_required(module, function):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("main.login_page"))
            if not perm_tree.check_permission(
                session.get("role", "user"), module, function
            ):
                flash("无权限访问该功能", "error")
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
        flash("请完整填写注册信息", "error")
        return redirect(url_for("main.register_page"))

    if user_cache.is_username_exist(username):
        flash("用户名已存在", "error")
        return redirect(url_for("main.register_page"))

    if user_cache.is_id_num_exist(id_num):
        flash("身份证号已存在", "error")
        return redirect(url_for("main.register_page"))

    if not validate_id(id_num):
        flash("身份证号格式错误（18位，末位可为X）", "error")
        return redirect(url_for("main.register_page"))

    if phone and not validate_phone(phone):
        flash("手机号格式错误（11位数字）", "error")
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
        flash("注册成功，请登录", "success")
        return redirect(url_for("main.login_page"))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("register_page failed: %s", exc)
        flash("注册失败，请稍后重试", "error")
        return redirect(url_for("main.register_page"))


@main_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")
    if not all([username, password]):
        flash("请输入用户名和密码", "error")
        return redirect(url_for("main.login_page"))

    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        session["user_id"] = user.user_id
        session["username"] = user.username
        session["role"] = user.role
        session["name"] = user.name
        session["id_num"] = user.id_num
        return redirect(url_for("main.index"))

    flash("登录失败：用户名或密码错误", "error")
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
    date_str = request.args.get("date", "").strip()
    search_results = []

    if not validate_date_string(date_str):
        flash("日期格式错误（YYYY-MM-DD）", "error")
        return redirect(url_for("main.index"))

    if search_type == "interval":
        start_station = request.args.get("start_station", "").strip()
        end_station = request.args.get("end_station", "").strip()
        if not validate_station_name(start_station) or not validate_station_name(
            end_station
        ):
            flash(
                "站名格式错误（仅限中英文、数字、空格、短横线，最长30）",
                "error",
            )
            return redirect(url_for("main.index"))
        if start_station == end_station:
            flash("出发站和到达站不能相同", "error")
            return redirect(url_for("main.index"))
        raw_trains = Train.query.filter(
            db.func.date(Train.dep_time) == date_str,
            Train.dep_station == start_station,
            Train.arr_station == end_station,
        ).all()
        search_results = quick_sort_trains(raw_trains)

    elif search_type == "station":
        station = request.args.get("station", "").strip()
        if not validate_station_name(station):
            flash(
                "站名格式错误（仅限中英文、数字、空格、短横线，最长30）",
                "error",
            )
            return redirect(url_for("main.index"))
        raw_trains = Train.query.filter(
            db.func.date(Train.dep_time) == date_str,
            db.or_(
                Train.dep_station == station,
                Train.arr_station == station,
            ),
        ).all()
        search_results = bubble_sort_by_time(raw_trains)
    else:
        flash("查询类型无效", "error")
        return redirect(url_for("main.index"))

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
        flash("该车次无余票", "error")
        return redirect(url_for("main.index"))

    if is_departed(train.dep_time):
        flash("该车次已发车，无法订票", "error")
        return redirect(url_for("main.index"))

    new_seat_map, seat = allocate_seat_by_type(train.seat_map, seat_type)
    if not seat:
        flash("选座失败：该座位类型已无票", "error")
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
        flash("订票成功", "success")

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("book_ticket failed: %s", exc)
        flash("订票失败，请稍后重试", "error")
        return redirect(url_for("main.index"))

    user_id = session.get("user_id")
    orders = get_user_orders(user_id)
    active_orders = get_active_orders(user_id)
    return render_template(
        "index.html",
        active_tab="orders",
        latest_order=new_order,
        orders=orders,
        active_orders=active_orders,
        now_time=datetime.now(),
    )


@main_bp.route("/orders_ui")
@permission_required("ticket_module", "refund")
def orders_ui():
    orders = get_user_orders(session.get("user_id"))
    active_orders = get_active_orders(session.get("user_id"))
    return render_template(
        "index.html",
        active_tab="orders",
        orders=orders,
        active_orders=active_orders,
        now_time=datetime.now(),
    )


@main_bp.route("/delete_order/<order_id>", methods=["POST"])
@permission_required("ticket_module", "refund")
def delete_order(order_id):
    order = Order.query.get(order_id)
    if order and order.user_id == session.get("user_id"):
        if is_departed(order.dep_time):
            flash("该车票已发车，无法退票", "error")
            return redirect(url_for("main.orders_ui"))
        try:
            train = Train.query.get(order.train_no)
            if train:
                train.seat_map = free_seat(train.seat_map, order.seat_no)
                train.rem_seats += 1
            db.session.delete(order)
            db.session.commit()
            flash("退票成功", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("delete_order failed: %s", exc)
            flash("退票失败，请稍后重试", "error")
    else:
        flash("订单不存在或无权限", "error")
    return redirect(url_for("main.orders_ui"))


@main_bp.route("/do_reschedule", methods=["POST"])
@permission_required("ticket_module", "reschedule")
def do_reschedule():
    order = Order.query.get(request.form.get("order_id"))
    new_train_no = request.form.get("new_train_no", "").strip().upper()
    seat_type = request.form.get("seat_type")

    new_train = Train.query.get(new_train_no)

    if not order or order.user_id != session.get("user_id"):
        flash("请求无效", "error")
        return redirect(url_for("main.orders_ui"))

    if not new_train or new_train.rem_seats <= 0:
        flash("改签失败：目标车次不存在或无余票", "error")
        return redirect(url_for("main.orders_ui"))

    old_train = Train.query.get(order.train_no)
    if not old_train:
        flash("改签失败：原车次不存在", "error")
        return redirect(url_for("main.orders_ui"))

    if is_departed(order.dep_time) or is_departed(old_train.dep_time):
        flash("改签失败：原车次已发车", "error")
        return redirect(url_for("main.orders_ui"))

    if is_departed(new_train.dep_time):
        flash("改签失败：目标车次已发车", "error")
        return redirect(url_for("main.orders_ui"))

    if (
        new_train.train_no == old_train.train_no
        and new_train.dep_time == old_train.dep_time
    ):
        flash("改签失败：新车次与原车次相同", "error")
        return redirect(url_for("main.orders_ui"))

    old_date = old_train.dep_time.date()
    new_date = new_train.dep_time.date()
    same_interval = (
        new_train.dep_station == old_train.dep_station
        and new_train.arr_station == old_train.arr_station
    )
    same_day_same_interval = same_interval and new_date == old_date
    same_train_diff_day = (
        new_train.train_no == old_train.train_no and new_date != old_date
    )

    is_valid_rule = same_day_same_interval or same_train_diff_day

    if not is_valid_rule:
        flash("改签失败：仅支持同日同区间或同车次改期", "error")
        return redirect(url_for("main.orders_ui"))

    new_map, new_seat = allocate_seat_by_type(new_train.seat_map, seat_type)
    if not new_seat:
        flash("改签失败：目标车次座位不足", "error")
        return redirect(url_for("main.orders_ui"))

    try:
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
        flash(f"改签成功，新座位：{new_seat}", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("do_reschedule failed: %s", exc)
        flash("改签失败，请稍后重试", "error")
        return redirect(url_for("main.orders_ui"))

    user_id = session.get("user_id")
    orders = get_user_orders(user_id)
    active_orders = get_active_orders(user_id)
    return render_template(
        "index.html",
        active_tab="orders",
        latest_order=order,
        orders=orders,
        active_orders=active_orders,
        now_time=datetime.now(),
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
        flash("用户名和姓名不能为空", "error")
        return redirect(url_for("main.profile_page"))

    if phone and not validate_phone(phone):
        flash("手机号格式错误（11位数字）", "error")
        return redirect(url_for("main.profile_page"))

    if new_username != user.username:
        if user_cache.is_username_exist(new_username):
            flash("用户名已存在", "error")
            return redirect(url_for("main.profile_page"))
        user_cache.update_username(user.username, new_username)
        user.username = new_username

    user.name = name
    user.phone = phone

    try:
        db.session.commit()
        session["username"] = user.username
        session["name"] = user.name
        flash("保存成功", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("update_profile failed: %s", exc)
        flash("保存失败，请稍后重试", "error")

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
            flash("删除失败：该车次存在有效订单", "error")
        else:
            try:
                Train.query.filter_by(train_no=train_no).delete()
                db.session.commit()
                flash(f"车次 {train_no} 已删除", "success")
            except Exception as exc:
                db.session.rollback()
                current_app.logger.exception(
                    "admin_manage_train delete failed: %s", exc
                )
                flash("删除失败：存在关联数据", "error")

    elif action == "add":
        if Train.query.get(train_no):
            flash("车次编号已存在", "error")
            return redirect(url_for("main.trains_page"))

        dep_station = request.form.get("dep_station", "").strip()
        arr_station = request.form.get("arr_station", "").strip()
        if not validate_station_name(dep_station) or not validate_station_name(
            arr_station
        ):
            flash(
                "站名格式错误（仅限中英文、数字、空格、短横线，最长30）",
                "error",
            )
            return redirect(url_for("main.trains_page"))
        if dep_station == arr_station:
            flash("出发站和到达站不能相同", "error")
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
            flash("时间或数值格式错误", "error")
            return redirect(url_for("main.trains_page"))

        if dep_time >= arr_time:
            flash("时间错误：到达时间必须晚于出发时间", "error")
            return redirect(url_for("main.trains_page"))
        if price < 0 or total_seats < 0 or carriage_count <= 0:
            flash("票价不能为负，座位数不能为负，车厢数必须大于0", "error")
            return redirect(url_for("main.trains_page"))

        t = Train(
            train_no=train_no,
            dep_station=dep_station,
            arr_station=arr_station,
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
            flash(f"车次 {train_no} 新增成功", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("admin_manage_train add failed: %s", exc)
            flash("新增车次失败", "error")

    elif action == "edit":
        train = Train.query.get(train_no)
        if not train:
            flash("车次不存在", "error")
            return redirect(url_for("main.trains_page"))

        dep_station = request.form.get("dep_station", "").strip()
        arr_station = request.form.get("arr_station", "").strip()
        if not validate_station_name(dep_station) or not validate_station_name(
            arr_station
        ):
            flash(
                "站名格式错误（仅限中英文、数字、空格、短横线，最长30）",
                "error",
            )
            return redirect(url_for("main.trains_page"))
        if dep_station == arr_station:
            flash("出发站和到达站不能相同", "error")
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
            flash("时间或数值格式错误", "error")
            return redirect(url_for("main.trains_page"))

        if dep_time >= arr_time:
            flash("时间错误：到达时间必须晚于出发时间", "error")
            return redirect(url_for("main.trains_page"))

        if price < 0 or total_seats < 0 or carriage_count <= 0:
            flash("票价不能为负，座位数不能为负，车厢数必须大于0", "error")
            return redirect(url_for("main.trains_page"))

        booked_count = train.total_seats - train.rem_seats
        if total_seats < booked_count:
            flash("修改失败：总座位数不能小于已售座位数", "error")
            return redirect(url_for("main.trains_page"))

        try:
            train.dep_station = dep_station
            train.arr_station = arr_station
            train.dep_time = dep_time
            train.arr_time = arr_time
            train.price = price
            train.carriage_count = carriage_count
            train.seat_map = resize_seat_map(train.seat_map, total_seats)
            train.total_seats = total_seats
            train.rem_seats = total_seats - booked_count

            db.session.commit()
            flash(f"车次 {train_no} 已更新", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("admin_manage_train edit failed: %s", exc)
            flash("更新车次失败", "error")

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
            flash("手机号格式错误（11位数字）", "error")
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
            flash("删除失败：该用户存在有效订单，请先退票", "error")
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
            flash("删除失败：存在关联订单", "error")

    elif action == "delete" and user.role == "admin":
        flash("不允许删除管理员账号", "error")

    return redirect(url_for("main.users_page"))
