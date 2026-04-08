import json
import re
import string


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
    except:
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


def validate_id(id_number):
    return bool(re.match(r"^\d{17}[\dXx]$", id_number))


def validate_phone(phone):
    return not phone or (len(phone) == 11 and phone.isdigit())


def validate_password(password):
    if len(password) < 6:
        return False, "密码长度必须至少为6位"

    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(c in string.punctuation for c in password)

    types_count = sum([has_letter, has_digit, has_symbol])
    if types_count < 2:
        return False, "密码过于简单：必须包含字母、数字、符号中的至少两种"

    weak_passwords = ["123456", "12345678", "password", "111111"]
    if password in weak_passwords:
        return False, "密码属常见弱密码，请强制修改为更复杂的组合"

    return True, "校验通过"


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
