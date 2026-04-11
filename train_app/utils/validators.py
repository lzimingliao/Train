import re
import string


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


__all__ = [
    "validate_id",
    "validate_phone",
    "validate_station_name",
    "validate_date_string",
    "validate_password",
]
