import json
import re
import string
from datetime import datetime, timedelta

from utils_intervals import (
    expand_interval_segments,
    get_route_stations,
    interval_length,
    intervals_overlap,
    is_valid_interval,
    quota_key,
)


def quick_sort_trains(trains):
    if len(trains) <= 1:
        return trains
    pivot = trains[len(trains) // 2]
    left = [
        x
        for x in trains
        if x.rem_seats > pivot.rem_seats
        or (x.rem_seats == pivot.rem_seats and x.dep_time < pivot.dep_time)
    ]
    middle = [
        x
        for x in trains
        if x.rem_seats == pivot.rem_seats and x.dep_time == pivot.dep_time
    ]
    right = [
        x
        for x in trains
        if x.rem_seats < pivot.rem_seats
        or (x.rem_seats == pivot.rem_seats and x.dep_time > pivot.dep_time)
    ]
    return quick_sort_trains(left) + middle + quick_sort_trains(right)


def bubble_sort_by_time(trains):
    n = len(trains)
    arr = list(trains)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j].dep_time > arr[j + 1].dep_time:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr


def init_seats(total_seats):
    return json.dumps([False] * total_seats)


def index_to_seat(index):
    carriage = (index // 20) + 1
    rem = index % 20
    row = (rem // 5) + 1
    col = ["A", "B", "C", "D", "F"][rem % 5]
    return f"{carriage:02d}车厢{row:02d}{col}"


def seat_to_index(seat_str):
    try:
        carriage = int(seat_str[:2])
        row = int(seat_str[4:6])
        col_char = seat_str[-1].upper()
        col_map = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
        return (carriage - 1) * 20 + (row - 1) * 5 + col_map[col_char]
    except (ValueError, KeyError, TypeError):
        return -1


def allocate_seat_by_type(seat_map_json, seat_type=None):
    seats = json.loads(seat_map_json)
    cols = ["A", "B", "C", "D", "F"]

    if seat_type and seat_type.upper() in cols:
        target_col_idx = cols.index(seat_type.upper())
        for i in range(len(seats)):
            if i % 5 == target_col_idx and not seats[i]:
                seats[i] = True
                return json.dumps(seats), index_to_seat(i)
        return seat_map_json, None

    for i in range(len(seats)):
        if not seats[i]:
            seats[i] = True
            return json.dumps(seats), index_to_seat(i)

    return seat_map_json, None


def free_seat(seat_map_json, seat_name):
    seats = json.loads(seat_map_json)
    idx = seat_to_index(seat_name)
    if 0 <= idx < len(seats):
        seats[idx] = False
    return json.dumps(seats)


class O1HashCache:
    def __init__(self):
        self.usernames = set()
        self.id_nums = set()

    def load_data(self, users):
        for u in users:
            self.usernames.add(u.username)
            self.id_nums.add(u.id_num)

    def is_username_exist(self, username):
        return username in self.usernames

    def is_id_num_exist(self, id_num):
        return id_num in self.id_nums

    def add_user(self, username, id_num):
        self.usernames.add(username)
        self.id_nums.add(id_num)

    def update_username(self, old_name, new_name):
        if old_name in self.usernames:
            self.usernames.discard(old_name)
        self.usernames.add(new_name)

    def remove_user(self, username, id_num):
        self.usernames.discard(username)
        self.id_nums.discard(id_num)


user_cache = O1HashCache()

LONG_HAUL_RESERVED_RATIO = 0.5
DYNAMIC_ALLOC_WINDOW_HOURS = 24


def ensure_route_template(train, db):
    from models import RouteQuota, RouteStop, TrainRouteTemplate

    template = TrainRouteTemplate.query.filter_by(train_no=train.train_no).first()
    if not template:
        template = TrainRouteTemplate(
            train_no=train.train_no,
            long_haul_reserved_ratio=LONG_HAUL_RESERVED_RATIO,
        )
        db.session.add(template)
        db.session.flush()

    if not template.stops:
        db.session.add_all(
            [
                RouteStop(
                    template_id=template.template_id,
                    station=train.dep_station,
                    stop_order=1,
                ),
                RouteStop(
                    template_id=template.template_id,
                    station=train.arr_station,
                    stop_order=2,
                ),
            ]
        )

    if not template.quotas:
        db.session.add(
            RouteQuota(
                template_id=template.template_id,
                start_station=train.dep_station,
                end_station=train.arr_station,
                quota=train.total_seats,
            )
        )

    if not train.route_template_id:
        train.route_template_id = template.template_id

    return template


def parse_stops_text(stops_text, dep_station, arr_station):
    if not stops_text:
        return [dep_station, arr_station]

    normalized = stops_text.replace("->", ",").replace("，", ",")
    parts = [x.strip() for x in normalized.split(",") if x.strip()]
    if len(parts) < 2:
        return [dep_station, arr_station]
    if parts[0] != dep_station:
        parts.insert(0, dep_station)
    if parts[-1] != arr_station:
        parts.append(arr_station)

    deduped = []
    for p in parts:
        if not deduped or deduped[-1] != p:
            deduped.append(p)
    return deduped


def upsert_route_template(
    train_no, dep_station, arr_station, total_seats, db, stops_text=""
):
    from models import RouteQuota, RouteStop, TrainRouteTemplate

    template = TrainRouteTemplate.query.filter_by(train_no=train_no).first()
    if not template:
        template = TrainRouteTemplate(
            train_no=train_no,
            long_haul_reserved_ratio=LONG_HAUL_RESERVED_RATIO,
        )
        db.session.add(template)
        db.session.flush()

    stations = parse_stops_text(stops_text, dep_station, arr_station)

    for stop in list(template.stops):
        db.session.delete(stop)
    for quota in list(template.quotas):
        db.session.delete(quota)
    db.session.flush()

    for idx, station in enumerate(stations, start=1):
        db.session.add(
            RouteStop(
                template_id=template.template_id,
                station=station,
                stop_order=idx,
            )
        )

    reserved = int(total_seats * template.long_haul_reserved_ratio)
    short_quota = max(1, total_seats - reserved)
    for i in range(len(stations)):
        for j in range(i + 1, len(stations)):
            start_station = stations[i]
            end_station = stations[j]
            is_full = i == 0 and j == len(stations) - 1
            quota = total_seats if is_full else short_quota
            db.session.add(
                RouteQuota(
                    template_id=template.template_id,
                    start_station=start_station,
                    end_station=end_station,
                    quota=quota,
                )
            )

    return template


def get_train_quota_map(train):
    quota_map = {}
    if getattr(train, "route_template", None):
        for q in train.route_template.quotas:
            quota_map[quota_key(q.start_station, q.end_station)] = q.quota

    stations = get_route_stations(train)
    if not quota_map:
        for i in range(len(stations)):
            for j in range(i + 1, len(stations)):
                quota_map[quota_key(stations[i], stations[j])] = train.total_seats

    try:
        state = json.loads(train.dynamic_alloc_state or "{}")
        overrides = state.get("quota_overrides", {})
        for k, v in overrides.items():
            quota_map[k] = v
    except (TypeError, json.JSONDecodeError):
        pass

    return quota_map


def parse_dynamic_state(train):
    try:
        return json.loads(train.dynamic_alloc_state or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def build_allocation_report(train):
    from models import WaitlistOrder

    state = parse_dynamic_state(train)
    waitlists = WaitlistOrder.query.filter_by(
        train_id=train.train_id,
        status="候补中",
    ).all()
    wait_heat = {}
    for w in waitlists:
        k = quota_key(w.start_station, w.end_station)
        wait_heat[k] = wait_heat.get(k, 0) + 1

    quota_map = get_train_quota_map(train)
    availability = {}
    for k in quota_map.keys():
        s, e = _parse_quota_key(k)
        if not s:
            continue
        availability[k] = get_interval_available(train, s, e)

    hot_intervals = sorted(wait_heat.items(), key=lambda x: x[1], reverse=True)
    return {
        "rebalanced": bool(state.get("rebalanced")),
        "rebalanced_at": train.dynamic_alloc_at.strftime("%Y-%m-%d %H:%M")
        if train.dynamic_alloc_at
        else "-",
        "override_count": len(state.get("quota_overrides", {})),
        "waitlist_count": len(waitlists),
        "top_wait_intervals": hot_intervals[:3],
        "interval_availability": availability,
    }


def _parse_quota_key(key):
    parts = (key or "").split("->")
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


def _fission_quota_overrides(train, quota_map):
    sold_intervals = []
    for order in _active_orders_for_train(train.train_id):
        sold_intervals.append(
            (
                order.board_stop or order.dep_station,
                order.alight_stop or order.arr_station,
            )
        )

    if not sold_intervals:
        return {}

    overrides = {}
    for key, base_quota in quota_map.items():
        start_station, end_station = _parse_quota_key(key)
        if not start_station:
            continue

        release_gain = 0
        for sold_start, sold_end in sold_intervals:
            if not intervals_overlap(
                train,
                start_station,
                end_station,
                sold_start,
                sold_end,
            ):
                # Seat sold on a disjoint interval can be reused here.
                release_gain += 1

        if release_gain > 0:
            overrides[key] = min(train.total_seats, base_quota + release_gain)

    return overrides


def _active_orders_for_train(train_id):
    from models import Order

    return Order.query.filter(
        Order.train_id == train_id,
        Order.status.in_(["已出票", "已改签"]),
        Order.dep_time > datetime.now(),
    ).all()


def count_conflicting_orders(train, start_station, end_station):
    count = 0
    for order in _active_orders_for_train(train.train_id):
        order_start = order.board_stop or order.dep_station
        order_end = order.alight_stop or order.arr_station
        if intervals_overlap(train, start_station, end_station, order_start, order_end):
            count += 1
    return count


def get_interval_available(train, start_station, end_station):
    if not is_valid_interval(train, start_station, end_station):
        return 0

    quota_map = get_train_quota_map(train)
    quota = quota_map.get(quota_key(start_station, end_station), train.total_seats)
    occupied = count_conflicting_orders(train, start_station, end_station)
    return max(0, min(quota, train.total_seats) - occupied)


def refresh_train_remaining_seats(train):
    train.rem_seats = get_interval_available(
        train, train.dep_station, train.arr_station
    )


def allocate_reusable_seat(train, seat_type, start_station, end_station):
    seats = json.loads(train.seat_map)
    unavailable = {i for i, occupied in enumerate(seats) if occupied}

    for order in _active_orders_for_train(train.train_id):
        order_start = order.board_stop or order.dep_station
        order_end = order.alight_stop or order.arr_station
        if not intervals_overlap(
            train, start_station, end_station, order_start, order_end
        ):
            continue
        seat_idx = seat_to_index(order.seat_no)
        if seat_idx >= 0:
            unavailable.add(seat_idx)

    target_col_idx = None
    cols = ["A", "B", "C", "D", "F"]
    if seat_type and seat_type.upper() in cols:
        target_col_idx = cols.index(seat_type.upper())

    if target_col_idx is not None:
        for i in range(len(seats)):
            if i in unavailable:
                continue
            if i % 5 == target_col_idx:
                return train.seat_map, index_to_seat(i)

    for i in range(len(seats)):
        if i not in unavailable:
            return train.seat_map, index_to_seat(i)

    return train.seat_map, None


def evaluate_dynamic_allocation_if_needed(train):
    if not train.dep_time:
        return
    now = datetime.now()
    if now < train.dep_time - timedelta(hours=DYNAMIC_ALLOC_WINDOW_HOURS):
        return

    state = parse_dynamic_state(train)

    if state.get("rebalanced"):
        return

    from models import WaitlistOrder

    waitlists = WaitlistOrder.query.filter_by(
        train_id=train.train_id, status="候补中"
    ).all()
    heat = {}
    for w in waitlists:
        k = quota_key(w.start_station, w.end_station)
        heat[k] = heat.get(k, 0) + 1

    quota_map = get_train_quota_map(train)
    overrides = _fission_quota_overrides(train, quota_map)
    for k, count in heat.items():
        base = quota_map.get(k, train.total_seats)
        current = overrides.get(k, base)
        # Greedy expansion by waitlist demand heat in D-1 window.
        overrides[k] = min(train.total_seats, current + count)

    state["rebalanced"] = True
    state["quota_overrides"] = overrides
    train.dynamic_alloc_state = json.dumps(state, ensure_ascii=False)
    train.dynamic_alloc_at = now


def enqueue_waitlist_if_needed(user_id, train, start_station, end_station):
    from models import WaitlistOrder

    existing = WaitlistOrder.query.filter_by(
        user_id=user_id,
        train_id=train.train_id,
        start_station=start_station,
        end_station=end_station,
        status="候补中",
    ).first()
    if existing:
        return existing, False

    wait = WaitlistOrder(
        user_id=user_id,
        train_id=train.train_id,
        train_no=train.train_no,
        start_station=start_station,
        end_station=end_station,
        interval_len=interval_length(train, start_station, end_station),
        status="候补中",
    )
    return wait, True


def fulfill_waitlists_after_refund(train, db):
    from models import Order, WaitlistOrder

    evaluate_dynamic_allocation_if_needed(train)
    candidates = WaitlistOrder.query.filter_by(
        train_id=train.train_id,
        status="候补中",
    ).all()
    candidates.sort(key=lambda x: (-x.interval_len, x.created_at))

    fulfilled_messages = []
    for wait in candidates:
        if get_interval_available(train, wait.start_station, wait.end_station) <= 0:
            continue
        _, seat = allocate_reusable_seat(
            train,
            None,
            wait.start_station,
            wait.end_station,
        )
        if not seat:
            continue

        order = Order(
            user_id=wait.user_id,
            train_id=train.train_id,
            train_no=train.train_no,
            dep_station=train.dep_station,
            arr_station=train.arr_station,
            dep_time=train.dep_time,
            seat_no=seat,
            price=train.price,
            board_stop=wait.start_station,
            alight_stop=wait.end_station,
            segment_span=json.dumps(
                expand_interval_segments(train, wait.start_station, wait.end_station),
                ensure_ascii=False,
            ),
            status="已出票",
        )
        db.session.add(order)
        db.session.flush()

        wait.status = "已兑现"
        wait.fulfilled_order_id = order.order_id
        refresh_train_remaining_seats(train)

        fulfilled_messages.append(
            f"候补兑现成功：{wait.train_no} {wait.start_station}->{wait.end_station}"
        )

    return fulfilled_messages


def find_interval_trains(raw_trains, start_station, end_station):
    matched = []
    for train in raw_trains:
        evaluate_dynamic_allocation_if_needed(train)
        if not is_valid_interval(train, start_station, end_station):
            continue
        train.query_start_station = start_station
        train.query_end_station = end_station
        train.interval_available = get_interval_available(
            train, start_station, end_station
        )
        train.route_stations = get_route_stations(train)
        matched.append(train)
    return sorted(
        matched,
        key=lambda t: (-t.interval_available, t.dep_time),
    )


def validate_id(id_number):
    return bool(re.match(r"^\d{17}[\dXx]$", id_number))


def validate_phone(phone):
    return not phone or (len(phone) == 11 and phone.isdigit())


def validate_station_name(name):
    if not name:
        return False
    station = name.strip()
    if not station or len(station) > 30:
        return False
    return bool(re.match(r"^[\u4e00-\u9fffA-Za-z0-9\-\s]+$", station))


def validate_date_string(date_str):
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str or ""))


def validate_password(password):
    if len(password) < 6:
        return False, "密码长度至少6位"

    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(c in string.punctuation for c in password)

    types_count = sum([has_letter, has_digit, has_symbol])
    if types_count < 2:
        return False, "密码需包含字母、数字、符号中的至少两种"

    weak_passwords = ["123456", "12345678", "password", "111111"]
    if password.lower() in weak_passwords:
        return False, "密码过于常见，请更换"

    return True, "通过"


class PermissionNode:
    def __init__(self, name):
        self.name = name
        self.children = {}


class PermissionTree:
    def __init__(self):
        self.root = PermissionNode("Root")

    def add_permission(self, role, module, function):
        current = self.root
        for node in [role, module, function]:
            if node not in current.children:
                current.children[node] = PermissionNode(node)
            current = current.children[node]

    def check_permission(self, role, module, function):
        current = self.root
        for node in [role, module, function]:
            if node not in current.children:
                return False
            current = current.children[node]
        return True


perm_tree = PermissionTree()
perm_tree.add_permission("admin", "ticket_module", "query")
perm_tree.add_permission("admin", "train_module", "manage")
perm_tree.add_permission("admin", "user_module", "manage")
perm_tree.add_permission("user", "ticket_module", "query")
perm_tree.add_permission("user", "ticket_module", "book")
perm_tree.add_permission("user", "ticket_module", "refund")
perm_tree.add_permission("user", "ticket_module", "reschedule")
perm_tree.add_permission("user", "user_module", "info")

# Compatibility re-exports for callers importing from root utils.py.
from utils_intervals import (
    all_interval_pairs,  # noqa: E402,F401
    estimate_station_time,  # noqa: E402,F401
    get_station_index,  # noqa: E402,F401
    recommend_transfer_plans,  # noqa: E402,F401
)
