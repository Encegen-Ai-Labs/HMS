from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_, text
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
import re
import io
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hostel.db'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(24)
db = SQLAlchemy(app)

DEFAULT_BED_RENT = 4000   # ⭐ Spec: every bed defaults to ₹4000 unless admin changes it


# --------------------- CONFIG ---------------------
def get_rent():
    s = Setting.query.first()
    if not s:
        return DEFAULT_BED_RENT
    try:
        return int(float(s.monthly_rent))
    except Exception:
        return DEFAULT_BED_RENT


def get_join_fee():
    setting = Setting.query.first()
    return setting.join_fee if setting else 0


def verify_password(stored, plain):
    """Supports legacy plaintext passwords as well as new hashed ones."""
    if not stored:
        return False
    if stored.startswith("pbkdf2:") or stored.startswith("scrypt:"):
        return check_password_hash(stored, plain)
    return stored == plain


# --------------------- MODELS ---------------------

class Floor(db.Model):
    __tablename__ = "floors"
    id = db.Column(db.Integer, primary_key=True)
    floor_number = db.Column(db.Integer, unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)

    rooms = db.relationship("Room", backref="floor", lazy=True)

    @property
    def total_rooms(self):
        return len(self.rooms)

    @property
    def total_beds(self):
        return sum(r.total_beds or 0 for r in self.rooms)

    @property
    def occupied_beds(self):
        return sum(r.occupied_beds or 0 for r in self.rooms)

    @property
    def is_fully_occupied(self):
        return self.total_beds > 0 and self.occupied_beds >= self.total_beds


class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(20), unique=True)
    total_beds = db.Column(db.Integer, default=0)
    occupied_beds = db.Column(db.Integer, default=0)
    floor_id = db.Column(db.Integer, db.ForeignKey("floors.id"))
    beds = db.relationship("Bed", backref="room", lazy=True)

    @property
    def available_beds(self):
        return (self.total_beds or 0) - (self.occupied_beds or 0)

    @property
    def is_fully_occupied(self):
        return (self.total_beds or 0) > 0 and self.available_beds <= 0


class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    mobile = db.Column(db.String(20))
    emergency_contact = db.Column(db.String(10), nullable=False)

    password = db.Column(db.String(255))          # ⭐ Student portal login
    join_fee = db.Column(db.Integer)
    join_date = db.Column(db.Date)
    checkout_date = db.Column(db.Date)             # ⭐ Reports: check-out tracking

    room = db.Column(db.String(10))
    bed = db.Column(db.String(10))
    rent = db.Column(db.Integer)

    room_id = db.Column(db.Integer)
    bed_no = db.Column(db.String(20))
    photo = db.Column(db.String(200))

    @property
    def total_fees(self):
        return self.total_due

    @property
    def total_paid(self):
        return sum(f.amount_paid for f in self.fees)

    @property
    def total_months_paid(self):
        return sum(f.months_paid_for or 0 for f in self.fees)

    @property
    def total_due(self):
        if not self.join_date:
            return 0
        end = self.checkout_date or date.today()
        months = (end.year - self.join_date.year) * 12 + (end.month - self.join_date.month) + 1
        return max(months, 0) * (self.rent or 0)

    @property
    def pending_amount(self):
        total = 0
        rent = self.rent or 0
        for f in self.fees:
            shortfall = rent - (f.amount_paid or 0)
            if shortfall > 0:
                total += shortfall
        return total

    @property
    def payment_status(self):
        return "Paid" if self.pending_amount == 0 else "Pending"

    @property
    def is_checked_out(self):
        return self.checkout_date is not None


class Bed(db.Model):
    __tablename__ = "beds"
    id = db.Column(db.Integer, primary_key=True)
    bed_id = db.Column(db.String(20), unique=True)
    room_number = db.Column(db.String(20))
    bed_label = db.Column(db.String(10))
    status = db.Column(db.String(20), default="Available")
    bed_rent = db.Column(db.Integer)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    allocated_to = db.Column(db.Integer, db.ForeignKey("students.id"))
    student = db.relationship("Student", backref="allocated_beds")
    is_available = db.Column(db.Boolean, default=True)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    email = db.Column(db.String(120), unique=True)     # ⭐ Admin now logs in via email
    password = db.Column(db.String(255))


class Fee(db.Model):
    __tablename__ = "fees"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    month = db.Column(db.Date, nullable=False)
    amount_paid = db.Column(db.Float, default=0)
    payment_date = db.Column(db.Date)
    months_paid_for = db.Column(db.Integer)
    payment_mode = db.Column(db.String(30), default="Manual")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


Student.fees = db.relationship("Fee", backref="student", lazy=True)


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monthly_rent = db.Column(db.Integer, default=DEFAULT_BED_RENT)
    join_fee = db.Column(db.Integer, default=5000)


class PaymentLog(db.Model):
    __tablename__ = "payment_logs"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    student_name = db.Column(db.String(200))
    month = db.Column(db.String(50))
    amount_paid = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.now)


class StudentRequest(db.Model):
    """⭐ Lets a student raise a case / request (maintenance, complaint,
    fee query, etc.) that the Admin can view and respond to."""
    __tablename__ = "student_requests"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    category = db.Column(db.String(50), default="General")
    subject = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Open")   # Open / In Progress / Resolved
    admin_response = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    student = db.relationship("Student", backref="requests")


# --------------------- HELPERS ---------------------
def get_floor_number(room_number):
    try:
        return int(str(room_number)[0])
    except Exception:
        return None


def get_or_create_floor(floor_number):
    floor = Floor.query.filter_by(floor_number=floor_number).first()
    if not floor:
        floor = Floor(floor_number=floor_number, name=f"Floor {floor_number}")
        db.session.add(floor)
        db.session.commit()
    return floor


def create_beds_for_room(room_number, total_beds):
    room = Room.query.filter_by(room_number=room_number).first()
    for i in range(1, total_beds + 1):
        bed_id = f"{room_number}-B{i}"
        if not Bed.query.filter_by(bed_id=bed_id).first():
            b = Bed(
                bed_id=bed_id,
                room_number=room_number,
                bed_label=f"B{i}",
                bed_rent=DEFAULT_BED_RENT,
                status="Available",
                room_id=room.id,
                is_available=True,
            )
            db.session.add(b)
    db.session.commit()


def assign_bed_to_student(bed, student):
    """Shared assignment logic used both at registration and from the
    Availability page, so bed/room occupancy stays consistent everywhere."""
    room = Room.query.filter_by(room_number=bed.room_number).first()

    bed.status = "Occupied"
    bed.is_available = False
    bed.allocated_to = student.id

    student.bed_no = bed.bed_id
    student.room = bed.room_number
    student.bed = bed.bed_label
    student.rent = bed.bed_rent or DEFAULT_BED_RENT

    if room:
        room.occupied_beds = (room.occupied_beds or 0) + 1


def _column_exists(table, column):
    rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def run_migrations():
    """Lightweight, idempotent migrations so existing hostel.db files pick
    up the new columns/tables without losing data."""
    db.create_all()

    # ---- rooms.floor_id ----
    if not _column_exists("rooms", "floor_id"):
        db.session.execute(text("ALTER TABLE rooms ADD COLUMN floor_id INTEGER"))
        db.session.commit()

    # ---- students.password / checkout_date ----
    if not _column_exists("students", "password"):
        db.session.execute(text("ALTER TABLE students ADD COLUMN password VARCHAR(255)"))
        db.session.commit()
    if not _column_exists("students", "checkout_date"):
        db.session.execute(text("ALTER TABLE students ADD COLUMN checkout_date DATE"))
        db.session.commit()

    # ---- fees.payment_mode ----
    if not _column_exists("fees", "payment_mode"):
        db.session.execute(text("ALTER TABLE fees ADD COLUMN payment_mode VARCHAR(30)"))
        db.session.commit()

    # ---- users.email ----
    if not _column_exists("users", "email"):
        db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(120)"))
        db.session.commit()

    # ---- Seed default admin ----
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(
            username="admin",
            email="admin@hostel.com",
            password=generate_password_hash("admin123"),
        )
        db.session.add(admin)
        db.session.commit()
    elif not admin.email:
        admin.email = "admin@hostel.com"
        db.session.commit()

    # ---- Seed default settings ----
    if not Setting.query.first():
        db.session.add(Setting(monthly_rent=DEFAULT_BED_RENT, join_fee=5000))
        db.session.commit()

    # ---- Seed predefined floors ----
    if not Floor.query.first():
        for num, name in [(0, "Ground Floor"), (1, "1st Floor"),
                           (2, "2nd Floor"), (3, "3rd Floor")]:
            db.session.add(Floor(floor_number=num, name=name))
        db.session.commit()

    # ---- Backfill floor_id for any legacy rooms ----
    for room in Room.query.filter(Room.floor_id.is_(None)).all():
        fnum = get_floor_number(room.room_number)
        if fnum is not None:
            floor = get_or_create_floor(fnum)
            room.floor_id = floor.id
    db.session.commit()

    # ---- Backfill student portal passwords (default = mobile number) ----
    for s in Student.query.filter(Student.password.is_(None)).all():
        s.password = generate_password_hash(s.mobile or "student123")
    db.session.commit()


@app.before_request
def setup():
    run_migrations()


# --------------------- ADMIN LOGIN ---------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if 'user' in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and verify_password(user.password, password):
            session['user'] = user.username
            return redirect(url_for("dashboard"))
        flash("Invalid email or password", "danger")
    return render_template("login.html")


# --------------------- DASHBOARD ---------------------
@app.route("/dashboard")
def dashboard():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    students = Student.query.all()

    total_floors = Floor.query.count()
    total_students = Student.query.count()
    total_rooms = Room.query.count()
    total_fees = sum(s.total_due for s in students)

    paid_fees = sum(s.total_paid for s in students)
    pending_fees = sum(s.pending_amount for s in students)
    total_beds = db.session.query(func.sum(Room.total_beds)).scalar() or 0
    occupied_beds = db.session.query(func.sum(Room.occupied_beds)).scalar() or 0

    fully_occupied_rooms = Room.query.filter(
        Room.total_beds > 0, Room.occupied_beds >= Room.total_beds
    ).count()

    return render_template(
        "dashboard.html", active_page='dashboard',
        total_floors=total_floors,
        total_students=total_students,
        total_rooms=total_rooms,
        total_beds=total_beds,
        available_beds=total_beds - occupied_beds,
        occupied_beds=occupied_beds,
        fully_occupied_rooms=fully_occupied_rooms,
        total_fees=total_fees,
        pending_fees=pending_fees,
        paid_fees=paid_fees,
    )


@app.route("/admin/profile")
def admin_profile():
    if 'user' not in session:
        return redirect(url_for("login"))

    admin = User.query.filter_by(username=session['user']).first()

    total_students = Student.query.count()
    total_rooms = Room.query.count()
    total_beds = Bed.query.count()
    students = Student.query.all()
    pending_fees = sum(s.pending_amount for s in students)

    return render_template(
        "admin_profile.html",
        admin=admin,
        total_students=total_students,
        total_rooms=total_rooms,
        total_beds=total_beds,
        pending_fees=pending_fees,
        active_page="profile"
    )


# --------------------- FLOORS ---------------------
@app.route("/floors", methods=["GET", "POST"])
def floors():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        floor_number = request.form.get("floor_number", type=int)
        name = request.form.get("name", "").strip()

        if floor_number is None or not name:
            flash("Floor number and name are required", "danger")
            return redirect(url_for("floors"))

        if Floor.query.filter_by(floor_number=floor_number).first():
            flash("This floor number already exists", "danger")
            return redirect(url_for("floors"))

        db.session.add(Floor(floor_number=floor_number, name=name))
        db.session.commit()
        flash("Floor added successfully", "success")
        return redirect(url_for("floors"))

    all_floors = Floor.query.order_by(Floor.floor_number).all()
    return render_template("floors.html", floors=all_floors, active_page="floors")


@app.route("/floors/edit/<int:floor_id>", methods=["POST"])
def edit_floor(floor_id):
    if 'user' not in session:
        return redirect(url_for("login"))

    floor = Floor.query.get_or_404(floor_id)
    name = request.form.get("name", "").strip()
    if name:
        floor.name = name
        db.session.commit()
        flash("Floor updated", "success")
    return redirect(url_for("floors"))


@app.route("/floors/delete/<int:floor_id>", methods=["POST"])
def delete_floor(floor_id):
    if 'user' not in session:
        return redirect(url_for("login"))

    floor = Floor.query.get_or_404(floor_id)
    if floor.rooms:
        flash("Cannot delete a floor that still has rooms on it", "danger")
        return redirect(url_for("floors"))

    db.session.delete(floor)
    db.session.commit()
    flash("Floor deleted", "success")
    return redirect(url_for("floors"))


# --------------------- OCCUPANCY OVERVIEW ---------------------
@app.route("/occupancy")
def occupancy():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    all_floors = Floor.query.order_by(Floor.floor_number).all()
    return render_template("occupancy.html", floors=all_floors, active_page="occupancy")


# --------------------- LISTS FOR DASHBOARD DRILL-DOWNS ---------------------
@app.route("/students-list")
def students_list():
    if 'user' not in session:
        return redirect(url_for("login"))
    students = Student.query.all()
    total_students = Student.query.count()
    return render_template("students_list.html", students=students, total_students=total_students)


@app.route("/rooms-list")
def rooms_list():
    if 'user' not in session:
        return redirect(url_for("login"))
    rooms = Room.query.order_by(Room.room_number).all()
    return render_template("rooms_list.html", rooms=rooms)


@app.route("/available_beds")
def available_beds():
    if 'user' not in session:
        return redirect(url_for("login"))
    beds = Bed.query.filter_by(is_available=True).all()

    rooms = {}
    for bed in beds:
        rooms.setdefault(bed.room_number, []).append(bed.bed_label)

    return render_template("available_beds.html", rooms=rooms)


@app.route("/total_fees")
def total_fees():
    if 'user' not in session:
        return redirect(url_for("login"))
    students = Student.query.all()
    data = [{"name": s.name, "total_fees": s.total_due} for s in students]
    return render_template("total_fees.html", data=data)


@app.route("/paid-fees")
def paid_fees_list():
    if 'user' not in session:
        return redirect(url_for("login"))
    students = [s for s in Student.query.all() if s.total_paid > 0]
    return render_template("paid_fees.html", students=students)


@app.route("/pending-fees")
def pending_fees_list():
    if 'user' not in session:
        return redirect(url_for("login"))
    students = [s for s in Student.query.all() if s.pending_amount > 0]
    return render_template("pending_fees.html", students=students)


# --------------------- STUDENTS (ADMIN SIDE) ---------------------
@app.route("/students", methods=["GET", "POST"])
def students():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    search_name = request.args.get("search_name")
    student_profile = None
    if search_name:
        student_profile = Student.query.filter(
            Student.name.ilike(f"%{search_name}%")
        ).first()

    # ---------- ADD STUDENT (with mandatory floor -> room -> bed) ----------
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        mobile = request.form.get("mobile")
        emergency_contact = request.form.get("emergency_contact")
        bed_id = request.form.get("bed_id", type=int)
        join_date_raw = request.form.get("join_date")

        if not emergency_contact or not re.fullmatch(r"\d{10}", emergency_contact):
            flash("Emergency contact must be exactly 10 digits", "danger")
            return redirect(url_for("students"))

        if not mobile or not re.fullmatch(r"\d{10}", mobile):
            flash("Mobile number must be exactly 10 digits", "danger")
            return redirect(url_for("students"))

        if not bed_id:
            flash("Please select a floor, room and bed for the student", "danger")
            return redirect(url_for("students"))

        bed = Bed.query.get(bed_id)
        if not bed or bed.status == "Occupied":
            flash("Selected bed is no longer available. Please pick another.", "danger")
            return redirect(url_for("students"))

        join_date = datetime.strptime(join_date_raw, "%Y-%m-%d").date() if join_date_raw else date.today()

        new_student = Student(
            name=name,
            email=email,
            mobile=mobile,
            emergency_contact=emergency_contact,
            join_date=join_date,
            join_fee=get_join_fee(),
            password=generate_password_hash(mobile),
        )
        db.session.add(new_student)
        db.session.flush()   # get new_student.id before commit

        assign_bed_to_student(bed, new_student)

        db.session.commit()

        flash(
            f"Student added & assigned to Room {bed.room_number} / Bed {bed.bed_label}! "
            f"Fee Management login → Email: {email} | Password: {mobile} (their mobile number)",
            "success"
        )
        return redirect(url_for("students", page=1))

    page = request.args.get("page", 1, type=int)
    students_page = Student.query.paginate(page=page, per_page=6)
    all_floors = Floor.query.order_by(Floor.floor_number).all()

    return render_template(
        "students.html", active_page='students',
        students=students_page,
        student_profile=student_profile,
        floors=all_floors,
    )


@app.route("/get_rooms_by_floor/<int:floor_number>")
def get_rooms_by_floor(floor_number):
    rooms = [r for r in Room.query.all() if get_floor_number(r.room_number) == floor_number]

    return jsonify([
        {
            "id": r.id,
            "room_number": r.room_number,
            "available_beds": r.available_beds,
        }
        for r in rooms if r.available_beds > 0
    ])


@app.route("/get_available_beds/<int:room_id>")
def get_available_beds(room_id):
    room = Room.query.get_or_404(room_id)
    beds = Bed.query.filter_by(room_number=room.room_number, status="Available").all()
    return jsonify([
        {"id": b.id, "bed_id": b.bed_id, "label": b.bed_label, "bed_rent": b.bed_rent or DEFAULT_BED_RENT}
        for b in beds
    ])


@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
    if 'user' not in session:
        return redirect(url_for("login"))

    student = Student.query.get_or_404(id)
    beds = Bed.query.all()

    if request.method == 'POST':
        student.name = request.form['name']
        student.email = request.form['email']
        student.mobile = request.form['mobile']
        student.emergency_contact = request.form['emergency_contact']
        date_str = request.form.get('join_date')
        if date_str:
            student.join_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        db.session.commit()
        flash('Student updated successfully', 'success')
        return redirect(url_for('students'))

    return render_template('edit_student.html', student=student, beds=beds)


@app.route("/get_student/<int:id>")
def get_student(id):
    student = Student.query.get_or_404(id)
    return jsonify({
        "id": student.id,
        "name": student.name,
        "email": student.email,
        "mobile": student.mobile,
        "emergency_contact": student.emergency_contact,
        "join_date": student.join_date or "",
        "room": student.room if student.room else "-",
        "bed": student.bed if student.bed else "-",
        "photo": student.photo or "image.png"
    })


@app.route("/search_student")
def search_student():
    name = request.args.get("name", "")
    student = Student.query.filter(Student.name.ilike(f"%{name}%")).first()
    if student:
        return {
            "found": True,
            "id": student.id,
            "name": student.name,
            "email": student.email,
            "mobile": student.mobile,
            "join_date": student.join_date,
            "room": student.room,
            "bed": student.bed
        }
    return {"found": False}


@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'user' not in session:
        return redirect(url_for("login"))

    student = Student.query.get(student_id)
    if not student:
        return redirect('/students')

    room_number = student.room
    bed_label = student.bed

    bed = Bed.query.filter_by(room_number=room_number, bed_label=bed_label).first()
    if bed:
        bed.status = "Available"
        bed.is_available = True
        bed.allocated_to = None

        room = Room.query.filter_by(room_number=room_number).first()
        if room and room.occupied_beds > 0:
            room.occupied_beds -= 1

    Fee.query.filter_by(student_id=student_id).delete()
    db.session.delete(student)
    db.session.commit()

    flash("Student removed and bed freed up", "success")
    return redirect('/students')


# --------------------- CHECK-OUT (Reports) ---------------------
@app.route('/checkout/<int:student_id>', methods=['POST'])
def checkout_student(student_id):
    if 'user' not in session:
        return redirect(url_for("login"))

    student = Student.query.get_or_404(student_id)

    if student.pending_amount > 0:
        flash(f"{student.name} still has ₹{student.pending_amount} pending. Clear dues before checkout.", "danger")
        return redirect(url_for("reports"))

    student.checkout_date = date.today()

    bed = Bed.query.filter_by(room_number=student.room, bed_label=student.bed).first()
    if bed:
        bed.status = "Available"
        bed.is_available = True
        bed.allocated_to = None
        room = Room.query.filter_by(room_number=student.room).first()
        if room and room.occupied_beds > 0:
            room.occupied_beds -= 1

    db.session.commit()
    flash(f"{student.name} checked out successfully", "success")
    return redirect(url_for("reports"))


# --------------------- ROOMS ---------------------
@app.route("/rooms", methods=["GET", "POST"])
def rooms():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        room_number = request.form["room_number"]
        total_beds = int(request.form["total_beds"])

        if Room.query.filter_by(room_number=room_number).first():
            flash("Room number already exists!", "danger")
            return redirect(url_for("rooms"))

        floor_number = get_floor_number(room_number)
        floor = get_or_create_floor(floor_number) if floor_number is not None else None

        new_room = Room(
            room_number=room_number,
            total_beds=total_beds,
            occupied_beds=0,
            floor_id=floor.id if floor else None,
        )
        db.session.add(new_room)
        db.session.commit()

        create_beds_for_room(room_number, total_beds)

        flash("Room created & beds added (₹4000 default rent each)", "success")
        return redirect(url_for("rooms"))

    page = request.args.get("page", 1, type=int)
    all_rooms = Room.query.order_by(Room.room_number).all()
    floors_present = sorted(set(get_floor_number(r.room_number) for r in all_rooms if get_floor_number(r.room_number) is not None))

    total_pages = len(floors_present)
    if total_pages == 0:
        return render_template(
            "rooms.html", rooms=[], current_floor=None, page=1, total_pages=1, active_page="rooms"
        )

    page = max(1, min(page, total_pages))
    current_floor = floors_present[page - 1]
    floor_rooms = [r for r in all_rooms if get_floor_number(r.room_number) == current_floor]

    rooms_data = []
    for room in floor_rooms:
        total_beds = Bed.query.filter_by(room_number=room.room_number).count()
        occupied_beds = Bed.query.filter_by(room_number=room.room_number, status="Occupied").count()
        rooms_data.append({
            "room_number": room.room_number,
            "total_beds": total_beds,
            "occupied_beds": occupied_beds,
            "available_beds": total_beds - occupied_beds,
        })

    return render_template(
        "rooms.html", rooms=rooms_data, current_floor=current_floor,
        page=page, total_pages=total_pages, active_page='rooms'
    )


@app.route('/change_room/<int:student_id>', methods=['GET'])
def change_room(student_id):
    if 'user' not in session:
        return redirect(url_for("login"))
    student = Student.query.get_or_404(student_id)
    beds = Bed.query.filter_by(status="Available").all()
    return render_template("change_room.html", student=student, beds=beds)


@app.route('/change_room/<int:student_id>', methods=['POST'])
def update_room(student_id):
    if 'user' not in session:
        return redirect(url_for("login"))

    student = Student.query.get_or_404(student_id)
    new_bed_id = request.form.get("bed_id")
    new_bed = Bed.query.get_or_404(new_bed_id)
    old_bed = Bed.query.filter_by(allocated_to=student.id).first()

    if old_bed:
        old_bed.status = "Available"
        old_bed.is_available = True
        old_bed.allocated_to = None
        old_room = Room.query.filter_by(room_number=old_bed.room_number).first()
        if old_room and old_room.occupied_beds > 0:
            old_room.occupied_beds -= 1

    assign_bed_to_student(new_bed, student)

    db.session.commit()
    flash("Room & Bed updated successfully!", "success")
    return redirect(url_for("students"))


@app.route("/get_beds/<int:room_id>")
def get_beds(room_id):
    room = Room.query.get(room_id)
    beds = Bed.query.filter_by(room_number=room.room_number).all()
    return jsonify([
        {"id": b.id, "bed_id": b.bed_id, "label": b.bed_label, "status": b.status}
        for b in beds
    ])


# --------------------- BEDS ---------------------
@app.route("/beds")
def beds_page():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    page = request.args.get("page", 1, type=int)
    all_beds = Bed.query.order_by(Bed.room_number, Bed.bed_label).all()
    floors_present = sorted(set(get_floor_number(b.room_number) for b in all_beds if get_floor_number(b.room_number) is not None))

    total_pages = len(floors_present)
    if total_pages == 0:
        return render_template("beds.html", beds=[], page=1, total_pages=1, current_floor=None, active_page="beds")

    page = max(1, min(page, total_pages))
    current_floor = floors_present[page - 1]
    floor_beds = [b for b in all_beds if get_floor_number(b.room_number) == current_floor]

    return render_template(
        "beds.html", beds=floor_beds, page=page, total_pages=total_pages,
        current_floor=current_floor, active_page="beds"
    )


# --------------------- AVAILABILITY ---------------------
@app.route("/availability")
def availability():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    rooms_data = [{"room_number": r.room_number, "total_beds": r.total_beds} for r in Room.query.all()]
    beds = Bed.query.all()
    unassigned = Student.query.filter(or_(Student.bed_no == None, Student.bed_no == "")).all()

    return render_template("availability.html", rooms=rooms_data, beds=beds, unassigned_students=unassigned)


@app.route("/assign_bed", methods=["POST"])
def assign_bed():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    bed_id = request.form["bed_id"]
    student_id = request.form["student_id"]

    bed = Bed.query.get(bed_id)
    student = Student.query.get(student_id)

    if bed.status == "Occupied":
        occupied_student = Student.query.get(bed.allocated_to)
        student_name = occupied_student.name if occupied_student else "Unknown Student"
        flash(f"This bed is already occupied by {student_name}", "danger")
        return redirect(url_for("availability"))

    assign_bed_to_student(bed, student)
    db.session.commit()

    flash("Bed assigned successfully!", "success")
    return redirect(url_for("availability"))


@app.route("/save_bed_rent_for_room", methods=["POST"])
def save_bed_rent_for_room():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    room_number = request.form.get("room_number")
    bed_rent = request.form.get("bed_rent")

    beds = Bed.query.filter_by(room_number=room_number).all()
    for bed in beds:
        bed.bed_rent = bed_rent
        if bed.allocated_to:
            student = Student.query.get(bed.allocated_to)
            if student:
                student.rent = bed_rent
    db.session.commit()

    flash(f"Bed rent ₹{bed_rent} saved for room {room_number}", "success")
    return redirect(url_for("availability"))


# --------------------- FEES (ADMIN) ---------------------
@app.route("/fees")
def fees_page():
    if 'user' not in session:
        return redirect(url_for("login"))
    students = Student.query.all()
    fees = Fee.query.order_by(Fee.id.desc()).all()
    return render_template("fees.html", students=students, fees=fees, active_page='fees')


@app.route("/api/student_info/<int:student_id>")
def api_student_info(student_id):
    s = Student.query.get(student_id)
    if not s:
        return jsonify({"error": "Student not found"}), 404

    month_formatted = ""
    try:
        if s.join_date:
            dt = s.join_date if not isinstance(s.join_date, str) else datetime.strptime(s.join_date, "%Y-%m-%d").date()
            month_formatted = dt.strftime("%B %Y")
    except Exception:
        month_formatted = str(s.join_date) if s.join_date else ""

    return jsonify({
        "id": s.id, "name": s.name, "join_date": s.join_date,
        "join_fee": s.join_fee or 0, "monthly_rent": s.rent or get_rent(),
        "month_display": month_formatted
    })


@app.route("/add_fee", methods=["POST"])
def add_fee():
    if 'user' not in session:
        return redirect(url_for("login"))

    student_id = request.form["student_id"]
    amount = int(request.form["amount_paid"])
    month_str = request.form.get("selected_month", "").strip()
    month_date = datetime.strptime(month_str, "%Y-%m").date() if month_str else date.today().replace(day=1)

    fee = Fee(
        student_id=student_id, month=month_date, amount_paid=amount,
        months_paid_for=month_date.month, payment_date=date.today(), payment_mode="Manual"
    )
    db.session.add(fee)
    db.session.commit()

    flash("Fee recorded successfully", "success")
    return redirect(url_for("fees_page"))


@app.route("/mark_paid/<int:fee_id>")
def mark_paid(fee_id):
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    fee = Fee.query.get(fee_id)
    fee.amount_paid = get_rent()
    db.session.commit()
    flash("Marked Paid", "success")
    return redirect(url_for("fees_page"))


# --------------------- REPORTS ---------------------
@app.route("/reports")
def reports():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    students = Student.query.order_by(Student.join_date.desc()).all()
    active_count = sum(1 for s in students if not s.is_checked_out)
    checked_out_count = sum(1 for s in students if s.is_checked_out)
    pending_count = sum(1 for s in students if s.pending_amount > 0)

    return render_template(
        "reports.html", students=students,
        active_count=active_count, checked_out_count=checked_out_count,
        pending_count=pending_count, active_page="reports"
    )


@app.route("/logs")
def logs():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    logs = PaymentLog.query.order_by(PaymentLog.timestamp.desc()).all()
    return render_template("logs.html", logs=logs, active_page="logs")


# --------------------- ADMIN LOGOUT ---------------------
@app.route("/logout")
def logout():
    session.pop('user', None)
    flash("Logged out", "info")
    return redirect(url_for("login"))


# =====================================================================
# --------------------- STUDENT PORTAL (SEPARATE LOGIN) --------------
# =====================================================================
@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if 'student_id' in session:
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        student = Student.query.filter_by(email=email).first()

        if student and verify_password(student.password, password):
            session['student_id'] = student.id
            return redirect(url_for("student_dashboard"))
        flash("Invalid email or password", "danger")

    return render_template("student_login.html")


@app.route("/student/dashboard")
def student_dashboard():
    if 'student_id' not in session:
        return redirect(url_for("student_login"))

    student = Student.query.get_or_404(session['student_id'])
    fees = Fee.query.filter_by(student_id=student.id).order_by(Fee.month.desc()).all()

    return render_template("student_dashboard.html", student=student, fees=fees)


@app.route("/student/pay", methods=["GET", "POST"])
def student_pay():
    if 'student_id' not in session:
        return redirect(url_for("student_login"))

    student = Student.query.get_or_404(session['student_id'])

    if request.method == "POST":
        plan = request.form.get("plan", "monthly")
        rent = student.rent or DEFAULT_BED_RENT
        months = 12 if plan == "yearly" else 1
        default_amount = rent * months

        amount = request.form.get("amount", type=float) or default_amount
        month_date = date.today().replace(day=1)

        fee = Fee(
            student_id=student.id, month=month_date, amount_paid=amount,
            months_paid_for=months, payment_date=date.today(), payment_mode="QR / Online"
        )
        db.session.add(fee)

        db.session.add(PaymentLog(
            student_id=student.id, student_name=student.name,
            month=month_date.strftime("%B %Y") + (" (Yearly)" if plan == "yearly" else ""),
            amount_paid=int(amount)
        ))
        db.session.commit()

        flash(f"Payment of ₹{int(amount)} ({plan}) received successfully!", "success")
        return redirect(url_for("student_dashboard"))

    plan = request.args.get("plan", "monthly")
    rent = student.rent or DEFAULT_BED_RENT
    amount_due = rent * 12 if plan == "yearly" else rent
    return render_template("student_pay.html", student=student, amount_due=amount_due, plan=plan)


@app.route("/qr/<int:student_id>")
def payment_qr(student_id):
    """Generates a UPI-style QR code on the fly for the student's due amount."""
    try:
        import qrcode
    except ImportError:
        return Response("qrcode package not installed. Run: pip install qrcode Pillow", status=500)

    student = Student.query.get_or_404(student_id)
    amount = request.args.get("amount", student.rent or DEFAULT_BED_RENT)

    upi_string = (
        f"upi://pay?pa=hostel@upi&pn=HostelAdmin"
        f"&am={amount}&cu=INR&tn=HostelFee-{student.id}"
    )

    img = qrcode.make(upi_string)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/student/logout")
def student_logout():
    session.pop('student_id', None)
    flash("Logged out", "info")
    return redirect(url_for("student_login"))


# --------------------- STUDENT REQUESTS / CASES ---------------------
@app.route("/student/requests", methods=["GET", "POST"])
def student_requests():
    if 'student_id' not in session:
        return redirect(url_for("student_login"))

    student = Student.query.get_or_404(session['student_id'])

    if request.method == "POST":
        category = request.form.get("category", "General")
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()

        if not subject or not description:
            flash("Please fill in both subject and description", "danger")
            return redirect(url_for("student_requests"))

        db.session.add(StudentRequest(
            student_id=student.id, category=category,
            subject=subject, description=description
        ))
        db.session.commit()
        flash("Your request has been submitted to the Admin", "success")
        return redirect(url_for("student_requests"))

    my_requests = StudentRequest.query.filter_by(student_id=student.id) \
        .order_by(StudentRequest.created_at.desc()).all()
    return render_template("student_requests.html", student=student, requests=my_requests)


# --------------------- ADMIN: VIEW / RESOLVE STUDENT REQUESTS ---------------------
@app.route("/requests")
def admin_requests():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    all_requests = StudentRequest.query.order_by(StudentRequest.created_at.desc()).all()
    open_count = sum(1 for r in all_requests if r.status == "Open")
    return render_template(
        "admin_requests.html", requests=all_requests,
        open_count=open_count, active_page="requests"
    )


@app.route("/requests/respond/<int:request_id>", methods=["POST"])
def respond_request(request_id):
    if 'user' not in session:
        return redirect(url_for("login"))

    req = StudentRequest.query.get_or_404(request_id)
    req.admin_response = request.form.get("admin_response", "").strip()
    req.status = request.form.get("status", "In Progress")
    if req.status == "Resolved":
        req.resolved_at = datetime.utcnow()
    db.session.commit()

    flash("Response saved", "success")
    return redirect(url_for("admin_requests"))


@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response


# --------------------- RUN ---------------------
if __name__ == "__main__":
    app.run(debug=True)