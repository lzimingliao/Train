import json
from datetime import datetime

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from train_app.extensions import db
from train_app.models import Order, Train
from train_app.routes import main_bp, permission_required
from train_app.utils.validators import validate_station_name
from utils import (
    build_allocation_report,
    evaluate_dynamic_allocation_if_needed,
    get_route_stations,
    init_seats,
    refresh_train_remaining_seats,
    upsert_route_template,
)


def resize_seat_map(seat_map_json, new_total):
    seats = json.loads(seat_map_json)
    if new_total <= len(seats):
        return json.dumps(seats[:new_total])
    seats.extend([False] * (new_total - len(seats)))
    return json.dumps(seats)


@main_bp.route("/trains")
@permission_required("train_module", "manage")
def trains_page():
    trains = Train.query.order_by(Train.train_no.asc(), Train.dep_time.asc()).all()
    for train in trains:
        evaluate_dynamic_allocation_if_needed(train)
        refresh_train_remaining_seats(train)
        train.route_stations = get_route_stations(train)
        train.allocation_report = build_allocation_report(train)
    db.session.commit()
    return render_template(
        "index.html",
        active_tab="trains",
        trains=trains,
    )


@main_bp.route("/admin_allocation_report/<train_id>")
@permission_required("train_module", "manage")
def admin_allocation_report(train_id):
    train = Train.query.get(train_id)
    if not train:
        return jsonify({"success": False, "message": "未找到该车次"}), 404

    evaluate_dynamic_allocation_if_needed(train)
    refresh_train_remaining_seats(train)
    report = build_allocation_report(train)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "train_id": train.train_id,
            "train_no": train.train_no,
            "dep_time": train.dep_time.strftime("%Y-%m-%d %H:%M"),
            "report": report,
        }
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
            stops_text = request.form.get("stop_stations", "").strip()
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
            db.session.flush()
            template = upsert_route_template(
                train_no=train_no,
                dep_station=dep_station,
                arr_station=arr_station,
                total_seats=total_seats,
                db=db,
                stops_text=stops_text,
            )
            t.route_template_id = template.template_id
            refresh_train_remaining_seats(t)
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
            stops_text = request.form.get("stop_stations", "").strip()
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
            template = upsert_route_template(
                train_no=train_no,
                dep_station=dep_station,
                arr_station=arr_station,
                total_seats=total_seats,
                db=db,
                stops_text=stops_text,
            )
            train.route_template_id = template.template_id
            refresh_train_remaining_seats(train)

            db.session.commit()
            flash(f"车次 {train_no} 信息已更新", "success")
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("admin_manage_train edit failed: %s", exc)
            flash("更新车次失败，请稍后重试", "error")

    return redirect(url_for("main.trains_page"))
