import uuid

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(db.Model):
    user_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "UID" + uuid.uuid4().hex[:8].upper(),
    )
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    id_num = db.Column(db.String(18), unique=True, nullable=False)
    phone = db.Column(db.String(11), nullable=True)
    role = db.Column(db.String(20), default="user", nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Train(db.Model):
    train_no = db.Column(db.String(20), primary_key=True)
    dep_station = db.Column(db.String(50), nullable=False)
    arr_station = db.Column(db.String(50), nullable=False)
    dep_time = db.Column(db.DateTime, nullable=False)
    arr_time = db.Column(db.DateTime, nullable=False)
    price = db.Column(db.Float, nullable=False)
    total_seats = db.Column(db.Integer, nullable=False)
    rem_seats = db.Column(db.Integer, nullable=False)
    carriage_count = db.Column(db.Integer, default=5, nullable=False)
    seat_map = db.Column(db.Text, nullable=False)


class Order(db.Model):
    order_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "ORD" + uuid.uuid4().hex[:12].upper(),
    )
    user_id = db.Column(db.String(50), db.ForeignKey("user.user_id"), nullable=False)
    train_no = db.Column(db.String(20), db.ForeignKey("train.train_no"), nullable=False)
    dep_station = db.Column(db.String(50), nullable=False)
    arr_station = db.Column(db.String(50), nullable=False)
    dep_time = db.Column(db.DateTime, nullable=False)
    booking_time = db.Column(db.DateTime, default=db.func.now())
    seat_no = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="已出票")

    user = db.relationship("User", backref=db.backref("orders", lazy=True))
    train = db.relationship("Train", backref=db.backref("orders", lazy=True))
