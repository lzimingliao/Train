from datetime import timedelta


def quota_key(start_station, end_station):
    return f"{start_station}->{end_station}"


def get_route_stations(train):
    if getattr(train, "route_template", None) and train.route_template.stops:
        stops = sorted(train.route_template.stops, key=lambda x: x.stop_order)
        return [s.station for s in stops]
    return [train.dep_station, train.arr_station]


def get_station_index(stations, station):
    try:
        return stations.index(station)
    except ValueError:
        return -1


def is_valid_interval(train, start_station, end_station):
    stations = get_route_stations(train)
    start_idx = get_station_index(stations, start_station)
    end_idx = get_station_index(stations, end_station)
    return start_idx >= 0 and end_idx > start_idx


def interval_length(train, start_station, end_station):
    stations = get_route_stations(train)
    start_idx = get_station_index(stations, start_station)
    end_idx = get_station_index(stations, end_station)
    if start_idx < 0 or end_idx <= start_idx:
        return 0
    return end_idx - start_idx


def expand_interval_segments(train, start_station, end_station):
    stations = get_route_stations(train)
    start_idx = get_station_index(stations, start_station)
    end_idx = get_station_index(stations, end_station)
    if start_idx < 0 or end_idx <= start_idx:
        return []
    return [quota_key(stations[i], stations[i + 1]) for i in range(start_idx, end_idx)]


def all_interval_pairs(train):
    stations = get_route_stations(train)
    pairs = []
    for i in range(len(stations)):
        for j in range(i + 1, len(stations)):
            pairs.append((stations[i], stations[j]))
    return pairs


def intervals_overlap(train, a_start, a_end, b_start, b_end):
    stations = get_route_stations(train)
    a1 = get_station_index(stations, a_start)
    a2 = get_station_index(stations, a_end)
    b1 = get_station_index(stations, b_start)
    b2 = get_station_index(stations, b_end)
    if min(a1, a2, b1, b2) < 0:
        return False
    if a2 <= a1 or b2 <= b1:
        return False
    return not (a2 <= b1 or b2 <= a1)


def estimate_station_time(train, station, is_departure=True):
    stations = getattr(train, "route_stations", None) or get_route_stations(train)
    idx = get_station_index(stations, station)
    if idx < 0:
        return None
    if len(stations) == 1:
        return train.dep_time
    ratio = idx / (len(stations) - 1)
    total_seconds = (train.arr_time - train.dep_time).total_seconds()
    offset_seconds = int(total_seconds * ratio)
    estimated = train.dep_time + timedelta(seconds=offset_seconds)
    return estimated + timedelta(minutes=2) if is_departure else estimated


def recommend_transfer_plans(
    raw_trains, start_station, end_station, min_transfer_minutes=30
):
    plans = []
    first_legs = []
    second_legs = []

    for train in raw_trains:
        stations = get_route_stations(train)
        train.route_stations = stations
        if start_station in stations:
            start_idx = get_station_index(stations, start_station)
            for i in range(start_idx + 1, len(stations)):
                first_legs.append((train, stations[i]))
        if end_station in stations:
            end_idx = get_station_index(stations, end_station)
            for i in range(0, end_idx):
                second_legs.append((train, stations[i]))

    for t1, transfer_station in first_legs:
        arr_time_1 = estimate_station_time(t1, transfer_station, is_departure=False)
        if not arr_time_1:
            continue
        for t2, candidate_transfer in second_legs:
            if candidate_transfer != transfer_station:
                continue
            if t1.train_id == t2.train_id:
                continue
            dep_time_2 = estimate_station_time(t2, transfer_station, is_departure=True)
            if not dep_time_2:
                continue
            if dep_time_2 < arr_time_1 + timedelta(minutes=min_transfer_minutes):
                continue
            total_minutes = int((t2.arr_time - t1.dep_time).total_seconds() / 60)
            plans.append(
                {
                    "first_train": t1,
                    "second_train": t2,
                    "transfer_station": transfer_station,
                    "transfer_wait_minutes": int(
                        (dep_time_2 - arr_time_1).total_seconds() / 60
                    ),
                    "total_minutes": total_minutes,
                    "start_station": start_station,
                    "end_station": end_station,
                }
            )

    plans.sort(key=lambda p: p["total_minutes"])
    return plans
