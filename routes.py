import json
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy.exc import OperationalError

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
                flash("当前账号暂无该功能权限", "error")
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
        flash("日期格式不正确，请按 YYYY-MM-DD 输入", "error")
        return redirect(url_for("main.index"))

    if search_type == "interval":
        start_station = request.args.get("start_station", "").strip()
        end_station = request.args.get("end_station", "").strip()
        if not validate_station_name(start_station) or not validate_station_name(
            end_station
        ):
            flash(
                "站名格式不正确（支持中英文、数字、空格、短横线，最多30字）",
                "error",
            )
            return redirect(url_for("main.index"))
        if start_station == end_station:
            flash("出发站与到达站不能相同", "error")
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
                "站名格式不正确（支持中英文、数字、空格、短横线，最多30字）",
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
        flash("查询参数无效，请重新选择查询方式", "error")
        return redirect(url_for("main.index"))

    source_tab = request.args.get("source_tab", "book")
    reschedule_order_id = request.args.get("reschedule_order_id")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template(
            "dashboard/sections/search_results.html",
            active_tab=source_tab,
            search_results=search_results,
            reschedule_order_id=reschedule_order_id,
            searched=True,
        )

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
    train_id = request.form.get("train_id", "").strip()
    train_no = request.form.get("train_no", "").strip().upper()
    dep_time_str = request.form.get("dep_time", "").strip()
    seat_type = request.form.get("seat_type")
    train = None

    if train_id:
        train = Train.query.get(train_id)

    # 兼容旧页面或缓存页面提交 train_no 的情况。
    if not train and train_no:
        q = Train.query.filter_by(train_no=train_no)
        if dep_time_str:
            try:
                dep_time = datetime.strptime(dep_time_str, "%Y-%m-%d %H:%M:%S")
                q = q.filter(Train.dep_time == dep_time)
            except ValueError:
                pass
        train = q.order_by(Train.dep_time.asc()).first()

    if not train or train.rem_seats <= 0:
        flash("当前车次余票不足，请选择其他车次", "error")
        return redirect(url_for("main.index"))

    if is_departed(train.dep_time):
        flash("该车次已发车，暂不支持订票", "error")
        return redirect(url_for("main.index"))

    new_seat_map, seat = allocate_seat_by_type(train.seat_map, seat_type)
    if not seat:
        flash("当前席别余票不足，请重新选择", "error")
        return redirect(url_for("main.index"))

    try:
        train.seat_map = new_seat_map
        train.rem_seats -= 1

        new_order = Order(
            user_id=session.get("user_id"),
            train_id=train.train_id,
            train_no=train.train_no,
            dep_station=train.dep_station,
            arr_station=train.arr_station,
            dep_time=train.dep_time,
            seat_no=seat,
            price=train.price,
        )
        db.session.add(new_order)
        db.session.commit()
        flash("订票成功，订单已生成", "success")

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("book_ticket failed: %s", exc)
        if isinstance(exc, OperationalError) and (
            "order.train_id" in str(exc).lower()
            or "no column named train_id" in str(exc).lower()
        ):
            flash(
                "订票失败：数据库结构尚未更新。请执行 RESET_DB=1 conda run -n train python app.py 后重试",
                "error",
            )
            return redirect(url_for("main.index"))
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
            flash("该订单对应车次已发车，暂不支持退票", "error")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(
                    {"success": False, "message": "该订单对应车次已发车，暂不支持退票"}
                )
            return redirect(url_for("main.orders_ui"))
        try:
            train = Train.query.get(order.train_id)
            if train:
                train.seat_map = free_seat(train.seat_map, order.seat_no)
                train.rem_seats += 1

            refund_success_message = (
                "退票成功："
                f"订单 {order.order_id}（{order.train_no} 次，"
                f"{order.dep_time.strftime('%Y-%m-%d %H:%M')}，"
                f"{order.dep_station}→{order.arr_station}）已关闭"
            )

            db.session.delete(order)
            db.session.commit()
            flash(refund_success_message, "success")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "message": refund_success_message})
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("delete_order failed: %s", exc)
            flash("退票未成功，请稍后重试", "error")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "message": "退票未成功，请稍后重试"})
    else:
        flash("订单不存在或无操作权限", "error")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": "订单不存在或无操作权限"})

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})

    return redirect(url_for("main.orders_ui"))


@main_bp.route("/do_reschedule", methods=["POST"])
@permission_required("ticket_module", "reschedule")
def do_reschedule():
    order = Order.query.get(request.form.get("order_id"))
    new_train_id = request.form.get("new_train_id", "").strip()
    seat_type = request.form.get("seat_type")

    new_train = Train.query.get(new_train_id)

    if not order or order.user_id != session.get("user_id"):
        flash("改签请求无效，请刷新页面后重试", "error")
        return redirect(url_for("main.orders_ui"))

    if not new_train or new_train.rem_seats <= 0:
        flash("改签失败：目标车次不存在或余票不足", "error")
        return redirect(url_for("main.orders_ui"))

    old_train = Train.query.get(order.train_id)
    if not old_train:
        flash("改签失败：原订单车次不存在", "error")
        return redirect(url_for("main.orders_ui"))

    if is_departed(order.dep_time) or is_departed(old_train.dep_time):
        flash("改签失败：原订单车次已发车", "error")
        return redirect(url_for("main.orders_ui"))

    if is_departed(new_train.dep_time):
        flash("改签失败：目标车次已发车", "error")
        return redirect(url_for("main.orders_ui"))

    if (
        new_train.train_no == old_train.train_no
        and new_train.dep_time == old_train.dep_time
    ):
        flash("改签失败：目标车次与原车次相同，无需改签", "error")
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
        flash("改签失败：仅支持同日同区间改签或同车次改期", "error")
        return redirect(url_for("main.orders_ui"))

    new_map, new_seat = allocate_seat_by_type(new_train.seat_map, seat_type)
    if not new_seat:
        flash("改签失败：目标车次席位不足", "error")
        return redirect(url_for("main.orders_ui"))

    try:
        old_train.seat_map = free_seat(old_train.seat_map, order.seat_no)
        old_train.rem_seats += 1

        new_train.seat_map = new_map
        new_train.rem_seats -= 1

        order.train_id = new_train.train_id
        order.train_no = new_train.train_no
        order.seat_no = new_seat
        order.status = "已改签"
        order.booking_time = db.func.now()
        order.price = new_train.price
        order.dep_station = new_train.dep_station
        order.arr_station = new_train.arr_station
        order.dep_time = new_train.dep_time

        db.session.commit()
        flash(
            "改签成功："
            f"已改签至 {new_train.train_no} 次（{new_train.dep_time.strftime('%Y-%m-%d %H:%M')}，"
            f"{new_train.dep_station}→{new_train.arr_station}），"
            f"新席位：{new_seat}",
            "success",
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("do_reschedule failed: %s", exc)
        flash("改签未成功，请稍后重试", "error")
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


@main_bp.route("/trains")
@permission_required("train_module", "manage")
def trains_page():
    return render_template(
        "index.html",
        active_tab="trains",
        trains=Train.query.order_by(Train.train_no.asc(), Train.dep_time.asc()).all(),
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
    train_id = request.form.get("train_id", "").strip()

    if action == "delete":
        train = Train.query.get(train_id)
        if not train:
            flash("未找到该车次", "error")
            return redirect(url_for("main.trains_page"))

        if Order.query.filter(
            Order.train_id == train.train_id,
            Order.status.in_(["已出票", "已改签"]),
            Order.dep_time > datetime.now(),
        ).first():
            flash("删除失败：该车次仍有关联有效订单", "error")
        else:
            try:
                # 清理该车次实例全部历史订单，避免外键约束阻止删除车次。
                historical_orders = Order.query.filter_by(train_id=train.train_id).all()
                for order in historical_orders:
                    db.session.delete(order)

                db.session.delete(train)
                db.session.commit()
                flash(
                    f"车次 {train.train_no}（{train.dep_time.strftime('%Y-%m-%d %H:%M')}）已删除",
                    "success",
                )
            except Exception as exc:
                db.session.rollback()
                current_app.logger.exception(
                    "admin_manage_train delete failed: %s", exc
                )
                flash("删除失败：仍存在关联数据", "error")

    elif action == "add":
        dep_station = request.form.get("dep_station", "").strip()
        arr_station = request.form.get("arr_station", "").strip()
        if not validate_station_name(dep_station) or not validate_station_name(
            arr_station
        ):
            flash(
                "站名格式不正确（支持中英文、数字、空格、短横线，最多30字）",
                "error",
            )
            return redirect(url_for("main.trains_page"))
        if dep_station == arr_station:
            flash("出发站与到达站不能相同", "error")
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
            flash("时间或数值格式不正确，请检查后重试", "error")
            return redirect(url_for("main.trains_page"))

        if dep_time >= arr_time:
            flash("时间设置有误：到达时间需晚于出发时间", "error")
            return redirect(url_for("main.trains_page"))
        if price < 0 or total_seats < 0 or carriage_count <= 0:
            flash("参数设置有误：票价/座位数不能为负，车厢数需大于0", "error")
            return redirect(url_for("main.trains_page"))

        if Train.query.filter_by(train_no=train_no, dep_time=dep_time).first():
            flash("新增失败：该车次在该发车时间已存在", "error")
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
            flash("新增车次失败，请稍后重试", "error")

    elif action == "edit":
        train = Train.query.get(train_id)
        if not train:
            flash("未找到该车次", "error")
            return redirect(url_for("main.trains_page"))

        dep_station = request.form.get("dep_station", "").strip()
        arr_station = request.form.get("arr_station", "").strip()
        if not validate_station_name(dep_station) or not validate_station_name(
            arr_station
        ):
            flash(
                "站名格式不正确（支持中英文、数字、空格、短横线，最多30字）",
                "error",
            )
            return redirect(url_for("main.trains_page"))
        if dep_station == arr_station:
            flash("出发站与到达站不能相同", "error")
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
            flash("时间或数值格式不正确，请检查后重试", "error")
            return redirect(url_for("main.trains_page"))

        if dep_time >= arr_time:
            flash("时间设置有误：到达时间需晚于出发时间", "error")
            return redirect(url_for("main.trains_page"))

        if price < 0 or total_seats < 0 or carriage_count <= 0:
            flash("参数设置有误：票价/座位数不能为负，车厢数需大于0", "error")
            return redirect(url_for("main.trains_page"))

        booked_count = train.total_seats - train.rem_seats
        if total_seats < booked_count:
            flash("修改失败：总座位数不能小于已售座位数", "error")
            return redirect(url_for("main.trains_page"))

        conflict_train = Train.query.filter(
            Train.train_no == train_no,
            Train.dep_time == dep_time,
            Train.train_id != train.train_id,
        ).first()
        if conflict_train:
            flash("修改失败：该车次在该发车时间已存在", "error")
            return redirect(url_for("main.trains_page"))

        try:
            train.train_no = train_no
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
            flash(f"车次 {train_no} 信息已更新", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("admin_manage_train edit failed: %s", exc)
            flash("更新车次失败，请稍后重试", "error")

    return redirect(url_for("main.trains_page"))


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
