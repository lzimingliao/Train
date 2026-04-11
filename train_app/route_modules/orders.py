from datetime import datetime

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from train_app.extensions import db
from train_app.models import Order, Train
from train_app.routes import (
    get_active_orders,
    get_user_orders,
    is_departed,
    main_bp,
    permission_required,
)
from utils import (
    allocate_reusable_seat,
    evaluate_dynamic_allocation_if_needed,
    free_seat,
    fulfill_waitlists_after_refund,
    get_interval_available,
    is_valid_interval,
    refresh_train_remaining_seats,
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
                evaluate_dynamic_allocation_if_needed(train)
                train.seat_map = free_seat(train.seat_map, order.seat_no)

            refund_success_message = (
                "退票成功："
                f"订单 {order.order_id}（{order.train_no} 次，"
                f"{order.dep_time.strftime('%Y-%m-%d %H:%M')}，"
                f"{order.dep_station}→{order.arr_station}）已关闭"
            )

            db.session.delete(order)
            wait_messages = []
            if train:
                wait_messages = fulfill_waitlists_after_refund(train, db)
                refresh_train_remaining_seats(train)
            db.session.commit()
            flash(refund_success_message, "success")
            for msg in wait_messages:
                flash(msg, "success")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                merged = [refund_success_message] + wait_messages
                return jsonify({"success": True, "message": "；".join(merged)})
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

    if not new_train:
        flash("改签失败：目标车次不存在", "error")
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
    order_start = order.board_stop or order.dep_station
    order_end = order.alight_stop or order.arr_station
    same_interval = is_valid_interval(new_train, order_start, order_end)
    same_day_same_interval = same_interval and new_date == old_date
    same_train_diff_day = (
        new_train.train_no == old_train.train_no and new_date != old_date
    )

    is_valid_rule = same_day_same_interval or same_train_diff_day

    if not is_valid_rule:
        flash("改签失败：仅支持同日同区间改签或同车次改期", "error")
        return redirect(url_for("main.orders_ui"))

    evaluate_dynamic_allocation_if_needed(new_train)
    if get_interval_available(new_train, order_start, order_end) <= 0:
        flash("改签失败：目标车次该区间无票", "error")
        return redirect(url_for("main.orders_ui"))

    new_map, new_seat = allocate_reusable_seat(
        new_train,
        seat_type,
        order_start,
        order_end,
    )
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
        order.board_stop = order_start
        order.alight_stop = order_end

        refresh_train_remaining_seats(old_train)
        refresh_train_remaining_seats(new_train)
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
