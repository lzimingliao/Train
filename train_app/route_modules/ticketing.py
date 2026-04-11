import json
from datetime import datetime, timedelta

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy.exc import OperationalError

from train_app.extensions import db
from train_app.models import Order, Train, TransferBundle
from train_app.routes import (
    get_active_orders,
    get_user_orders,
    is_departed,
    main_bp,
    permission_required,
)
from train_app.utils.validators import validate_date_string, validate_station_name
from utils import (
    allocate_reusable_seat,
    bubble_sort_by_time,
    enqueue_waitlist_if_needed,
    estimate_station_time,
    evaluate_dynamic_allocation_if_needed,
    expand_interval_segments,
    find_interval_trains,
    get_interval_available,
    get_route_stations,
    is_valid_interval,
    recommend_transfer_plans,
    refresh_train_remaining_seats,
)


@main_bp.route("/")
@permission_required("ticket_module", "query")
def index():
    return render_template(
        "index.html",
        active_tab="book",
        search_results=[],
        transfer_plans=[],
    )


@main_bp.route("/do_query")
@permission_required("ticket_module", "query")
def do_query():
    search_type = request.args.get("search_type")
    date_str = request.args.get("date", "").strip()
    search_results = []
    transfer_plans = []

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
        raw_trains = Train.query.filter(db.func.date(Train.dep_time) == date_str).all()
        search_results = find_interval_trains(raw_trains, start_station, end_station)
        if not search_results:
            transfer_plans = recommend_transfer_plans(
                raw_trains,
                start_station,
                end_station,
                min_transfer_minutes=30,
            )

    elif search_type == "station":
        station = request.args.get("station", "").strip()
        if not validate_station_name(station):
            flash(
                "站名格式不正确（支持中英文、数字、空格、短横线，最多30字）",
                "error",
            )
            return redirect(url_for("main.index"))
        raw_trains = Train.query.filter(db.func.date(Train.dep_time) == date_str).all()
        station_matches = []
        for train in raw_trains:
            stations = get_route_stations(train)
            if station in stations:
                train.route_stations = stations
                evaluate_dynamic_allocation_if_needed(train)
                refresh_train_remaining_seats(train)
                station_matches.append(train)
        search_results = bubble_sort_by_time(station_matches)
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
            transfer_plans=transfer_plans,
            reschedule_order_id=reschedule_order_id,
            searched=True,
        )

    return render_template(
        "index.html",
        active_tab=source_tab,
        search_results=search_results,
        transfer_plans=transfer_plans,
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
    board_stop = request.form.get("board_stop", "").strip()
    alight_stop = request.form.get("alight_stop", "").strip()
    train = None

    if train_id:
        train = Train.query.get(train_id)

    # Support legacy pages posting train_no instead of train_id.
    if not train and train_no:
        q = Train.query.filter_by(train_no=train_no)
        if dep_time_str:
            try:
                dep_time = datetime.strptime(dep_time_str, "%Y-%m-%d %H:%M:%S")
                q = q.filter(Train.dep_time == dep_time)
            except ValueError:
                pass
        train = q.order_by(Train.dep_time.asc()).first()

    if not train:
        flash("未找到目标车次，请重新查询", "error")
        return redirect(url_for("main.index"))

    if is_departed(train.dep_time):
        flash("该车次已发车，暂不支持订票", "error")
        return redirect(url_for("main.index"))

    evaluate_dynamic_allocation_if_needed(train)

    if not board_stop:
        board_stop = train.dep_station
    if not alight_stop:
        alight_stop = train.arr_station

    if not is_valid_interval(train, board_stop, alight_stop):
        flash("订票失败：请选择有效的经停区间", "error")
        return redirect(url_for("main.index"))

    if get_interval_available(train, board_stop, alight_stop) <= 0:
        flash("当前区间无票，可加入候补", "error")
        return redirect(url_for("main.index"))

    new_seat_map, seat = allocate_reusable_seat(
        train,
        seat_type,
        board_stop,
        alight_stop,
    )
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
            board_stop=board_stop,
            alight_stop=alight_stop,
        )
        db.session.add(new_order)
        refresh_train_remaining_seats(train)
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


@main_bp.route("/book_transfer", methods=["POST"])
@permission_required("ticket_module", "book")
def book_transfer():
    first_train_id = request.form.get("first_train_id", "").strip()
    second_train_id = request.form.get("second_train_id", "").strip()
    start_station = request.form.get("start_station", "").strip()
    transfer_station = request.form.get("transfer_station", "").strip()
    end_station = request.form.get("end_station", "").strip()
    seat_type = request.form.get("seat_type")

    if not all(
        [first_train_id, second_train_id, start_station, transfer_station, end_station]
    ):
        flash("中转下单失败：参数不完整", "error")
        return redirect(url_for("main.index"))

    first_train = Train.query.get(first_train_id)
    second_train = Train.query.get(second_train_id)
    if not first_train or not second_train:
        flash("中转下单失败：未找到对应车次", "error")
        return redirect(url_for("main.index"))
    if first_train.train_id == second_train.train_id:
        flash("中转下单失败：两段车次不能相同", "error")
        return redirect(url_for("main.index"))

    evaluate_dynamic_allocation_if_needed(first_train)
    evaluate_dynamic_allocation_if_needed(second_train)

    if is_departed(first_train.dep_time) or is_departed(second_train.dep_time):
        flash("中转下单失败：存在已发车车次", "error")
        return redirect(url_for("main.index"))

    if not is_valid_interval(first_train, start_station, transfer_station):
        flash("中转下单失败：第一程区间无效", "error")
        return redirect(url_for("main.index"))
    if not is_valid_interval(second_train, transfer_station, end_station):
        flash("中转下单失败：第二程区间无效", "error")
        return redirect(url_for("main.index"))

    arr_time_first = estimate_station_time(
        first_train, transfer_station, is_departure=False
    )
    dep_time_second = estimate_station_time(
        second_train, transfer_station, is_departure=True
    )
    if not arr_time_first or not dep_time_second:
        flash("中转下单失败：换乘时间计算异常", "error")
        return redirect(url_for("main.index"))
    if dep_time_second < arr_time_first + timedelta(minutes=30):
        flash("中转下单失败：换乘时间不足30分钟", "error")
        return redirect(url_for("main.index"))

    first_available = get_interval_available(
        first_train, start_station, transfer_station
    )
    second_available = get_interval_available(
        second_train, transfer_station, end_station
    )
    if first_available <= 0 or second_available <= 0:
        flash(
            "中转下单失败：两段车票需同时有票（"
            f"第一程余票 {first_available}，第二程余票 {second_available}）",
            "error",
        )
        return redirect(url_for("main.index"))

    _, seat_one = allocate_reusable_seat(
        first_train,
        seat_type,
        start_station,
        transfer_station,
    )
    _, seat_two = allocate_reusable_seat(
        second_train,
        seat_type,
        transfer_station,
        end_station,
    )
    if not seat_one or not seat_two:
        if not seat_one and not seat_two:
            flash("中转下单失败：两段席位分配均失败", "error")
        elif not seat_one:
            flash("中转下单失败：第一程席位分配失败", "error")
        else:
            flash("中转下单失败：第二程席位分配失败", "error")
        return redirect(url_for("main.index"))

    try:
        bundle = TransferBundle(user_id=session.get("user_id"), status="已出票")
        db.session.add(bundle)
        db.session.flush()

        order1 = Order(
            user_id=session.get("user_id"),
            train_id=first_train.train_id,
            train_no=first_train.train_no,
            dep_station=first_train.dep_station,
            arr_station=first_train.arr_station,
            dep_time=first_train.dep_time,
            seat_no=seat_one,
            price=first_train.price,
            board_stop=start_station,
            alight_stop=transfer_station,
            segment_span=json.dumps(
                expand_interval_segments(first_train, start_station, transfer_station),
                ensure_ascii=False,
            ),
            is_transfer_leg=True,
            bundle_id=bundle.bundle_id,
            status="已出票",
        )
        order2 = Order(
            user_id=session.get("user_id"),
            train_id=second_train.train_id,
            train_no=second_train.train_no,
            dep_station=second_train.dep_station,
            arr_station=second_train.arr_station,
            dep_time=second_train.dep_time,
            seat_no=seat_two,
            price=second_train.price,
            board_stop=transfer_station,
            alight_stop=end_station,
            segment_span=json.dumps(
                expand_interval_segments(second_train, transfer_station, end_station),
                ensure_ascii=False,
            ),
            is_transfer_leg=True,
            bundle_id=bundle.bundle_id,
            status="已出票",
        )
        db.session.add_all([order1, order2])

        refresh_train_remaining_seats(first_train)
        refresh_train_remaining_seats(second_train)
        db.session.commit()
        flash(
            "中转预订成功："
            f"{first_train.train_no}({start_station}->{transfer_station}) + "
            f"{second_train.train_no}({transfer_station}->{end_station})",
            "success",
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("book_transfer failed: %s", exc)
        flash("中转下单失败，请稍后重试", "error")
        return redirect(url_for("main.index"))

    orders = get_user_orders(session.get("user_id"))
    active_orders = get_active_orders(session.get("user_id"))
    return render_template(
        "index.html",
        active_tab="orders",
        latest_order=order2,
        orders=orders,
        active_orders=active_orders,
        now_time=datetime.now(),
    )


@main_bp.route("/join_waitlist", methods=["POST"])
@permission_required("ticket_module", "book")
def join_waitlist():
    train_id = request.form.get("train_id", "").strip()
    start_station = request.form.get("start_station", "").strip()
    end_station = request.form.get("end_station", "").strip()

    train = Train.query.get(train_id)
    if not train:
        flash("候补提交失败：未找到对应车次", "error")
        return redirect(url_for("main.index"))

    evaluate_dynamic_allocation_if_needed(train)
    if not is_valid_interval(train, start_station, end_station):
        flash("候补提交失败：区间无效", "error")
        return redirect(url_for("main.index"))

    if get_interval_available(train, start_station, end_station) > 0:
        flash("该区间当前有票，请直接购票", "success")
        return redirect(url_for("main.index"))

    wait, created = enqueue_waitlist_if_needed(
        session.get("user_id"),
        train,
        start_station,
        end_station,
    )
    if created:
        db.session.add(wait)
        db.session.commit()
        flash("候补提交成功，系统将按先卖长后卖短+提交时间兑现", "success")
    else:
        flash("该区间已在候补队列中，请勿重复提交", "error")

    return redirect(url_for("main.index"))
