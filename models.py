import uuid

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class TrainRouteTemplate(db.Model):
    template_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "TPL" + uuid.uuid4().hex[:12].upper(),
    )
    train_no = db.Column(db.String(20), unique=True, nullable=False)
    long_haul_reserved_ratio = db.Column(db.Float, default=0.5, nullable=False)


class RouteStop(db.Model):
    stop_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "STP" + uuid.uuid4().hex[:12].upper(),
    )
    template_id = db.Column(
        db.String(50), db.ForeignKey("train_route_template.template_id"), nullable=False
    )
    station = db.Column(db.String(50), nullable=False)
    stop_order = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint("template_id", "stop_order"),)


class RouteQuota(db.Model):
    quota_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "QTA" + uuid.uuid4().hex[:12].upper(),
    )
    template_id = db.Column(
        db.String(50), db.ForeignKey("train_route_template.template_id"), nullable=False
    )
    start_station = db.Column(db.String(50), nullable=False)
    end_station = db.Column(db.String(50), nullable=False)
    quota = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("template_id", "start_station", "end_station"),
    )


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
    train_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "TRN" + uuid.uuid4().hex[:12].upper(),
    )
    train_no = db.Column(db.String(20), nullable=False)
    dep_station = db.Column(db.String(50), nullable=False)
    arr_station = db.Column(db.String(50), nullable=False)
    dep_time = db.Column(db.DateTime, nullable=False)
    arr_time = db.Column(db.DateTime, nullable=False)
    price = db.Column(db.Float, nullable=False)
    total_seats = db.Column(db.Integer, nullable=False)
    rem_seats = db.Column(db.Integer, nullable=False)
    carriage_count = db.Column(db.Integer, default=5, nullable=False)
    seat_map = db.Column(db.Text, nullable=False)
    route_template_id = db.Column(
        db.String(50), db.ForeignKey("train_route_template.template_id"), nullable=True
    )
    dynamic_alloc_state = db.Column(db.Text, default="{}", nullable=False)
    dynamic_alloc_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint("train_no", "dep_time"),)


class TransferBundle(db.Model):
    bundle_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "BND" + uuid.uuid4().hex[:12].upper(),
    )
    user_id = db.Column(db.String(50), db.ForeignKey("user.user_id"), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    status = db.Column(db.String(20), default="已出票", nullable=False)


class Order(db.Model):
    order_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "ORD" + uuid.uuid4().hex[:12].upper(),
    )
    user_id = db.Column(db.String(50), db.ForeignKey("user.user_id"), nullable=False)
    train_id = db.Column(db.String(50), db.ForeignKey("train.train_id"), nullable=False)
    train_no = db.Column(db.String(20), nullable=False)
    dep_station = db.Column(db.String(50), nullable=False)
    arr_station = db.Column(db.String(50), nullable=False)
    dep_time = db.Column(db.DateTime, nullable=False)
    booking_time = db.Column(db.DateTime, default=db.func.now())
    seat_no = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="已出票")
    board_stop = db.Column(db.String(50), nullable=True)
    alight_stop = db.Column(db.String(50), nullable=True)
    segment_span = db.Column(db.Text, nullable=True)
    is_transfer_leg = db.Column(db.Boolean, default=False, nullable=False)
    bundle_id = db.Column(
        db.String(50), db.ForeignKey("transfer_bundle.bundle_id"), nullable=True
    )

    user = db.relationship("User", backref=db.backref("orders", lazy=True))
    train = db.relationship("Train", backref=db.backref("orders", lazy=True))


class WaitlistOrder(db.Model):
    wait_id = db.Column(
        db.String(50),
        primary_key=True,
        default=lambda: "WLT" + uuid.uuid4().hex[:12].upper(),
    )
    user_id = db.Column(db.String(50), db.ForeignKey("user.user_id"), nullable=False)
    train_id = db.Column(db.String(50), db.ForeignKey("train.train_id"), nullable=False)
    train_no = db.Column(db.String(20), nullable=False)
    start_station = db.Column(db.String(50), nullable=False)
    end_station = db.Column(db.String(50), nullable=False)
    interval_len = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="候补中", nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    fulfilled_order_id = db.Column(
        db.String(50), db.ForeignKey("order.order_id"), nullable=True
    )


TrainRouteTemplate.stops = db.relationship(
    "RouteStop",
    backref=db.backref("template", lazy=True),
    lazy=True,
    cascade="all, delete-orphan",
)
TrainRouteTemplate.quotas = db.relationship(
    "RouteQuota",
    backref=db.backref("template", lazy=True),
    lazy=True,
    cascade="all, delete-orphan",
)
Train.route_template = db.relationship(
    "TrainRouteTemplate", backref=db.backref("trains", lazy=True)
)
TransferBundle.user = db.relationship(
    "User", backref=db.backref("transfer_bundles", lazy=True)
)
Order.bundle = db.relationship(
    "TransferBundle", backref=db.backref("orders", lazy=True)
)
WaitlistOrder.user = db.relationship("User", backref=db.backref("waitlists", lazy=True))
WaitlistOrder.train = db.relationship(
    "Train", backref=db.backref("waitlists", lazy=True)
)
