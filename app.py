from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from datetime import datetime
from flask import session
import re
from datetime import date

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hostel.db'
app.config['SECRET_KEY'] = 'secretkey'
db = SQLAlchemy(app)


# --------------------- CONFIG ---------------------
def get_rent():
    s = Setting.query.first()
    if not s:
        return 3000
    try:
        return int(float(s.monthly_rent))   # ⭐ ALWAYS CLEAN VALUE
    except:
        return 3000

def get_join_fee():
    setting = Setting.query.first()
    return setting.join_fee




# --------------------- MODELS ---------------------




class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(20), unique=True)
    total_beds = db.Column(db.Integer, default=0)
    occupied_beds = db.Column(db.Integer, default=0)
    beds = db.relationship("Bed", backref="room", lazy=True)

    @property
    def available_beds(self):
        return (self.total_beds or 0) - (self.occupied_beds or 0)


class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    mobile = db.Column(db.String(20))
    emergency_contact = db.Column(db.String(10), nullable=False)

    join_fee = db.Column(db.Integer)       # FIXED NAME
    join_date = db.Column(db.Date) 
    fees = db.relationship("Fee", backref="student", lazy=True)  # YYYY-MM-DD

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
        return sum(f.months_paid_for for f in self.fees)
    
    @property
    def total_due(self):
        if not self.join_date:
           return 0
        # kitne mahine ho chuke join date se
        today = date.today()
        months = (today.year - self.join_date.year) * 12 + (today.month - self.join_date.month) + 1
        return months * (self.rent or 0)

    @property
    def pending_amount(self):
        pending = self.total_due - self.total_paid
        return pending if pending > 0 else 0

    @property
    def payment_status(self):
        return "Paid" if self.pending_amount == 0 else "Pending"



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
    password = db.Column(db.String(50))


class Fee(db.Model):
    __tablename__ = "fees"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    month = db.Column(db.Date, nullable=False)           
    amount_paid = db.Column(db.Float, default=0)
    payment_date = db.Column(db.Date)
    months_paid_for = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    


Student.fees = db.relationship("Fee", backref="student", lazy=True)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monthly_rent= db.Column(db.Integer, default=3000)
    join_fee = db.Column(db.Integer, default=5000)

class PaymentLog(db.Model):
    __tablename__ = "payment_logs"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    student_name = db.Column(db.String(200))
    month = db.Column(db.String(50))
    amount_paid = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.now)


# --------------------- HELPERS ---------------------
def create_beds_for_room(room_number, total_beds):
    room = Room.query.filter_by(room_number=room_number).first()
    for i in range(1, total_beds + 1):
        bed_id = f"{room_number}-B{i}"
        if not Bed.query.filter_by(bed_id=bed_id).first():
            b = Bed(
                bed_id=bed_id,
                room_number=room_number,
                bed_label=f"B{i}",
                bed_rent=0,  #Admin will set later
                status="Available",
                room_id=room.id
            )
            db.session.add(b)
    db.session.commit()


@app.before_request
def setup():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        db.session.add(User(username="admin", password="admin123"))
        db.session.commit()
    if not Setting.query.first():
        default = Setting(monthly_rent=3000, join_fee=5000)
        db.session.add(default)
        db.session.commit()

def get_floor(room_number):
            try:
                return int(str(room_number)[0])
            except:
                return None
            

# --------------------- LOGIN ---------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if 'user'  in session:
       
       return redirect(url_for("dashboard"))

    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        user = User.query.filter_by(username=u, password=p).first()
        if user:
            session['user'] = user.username 
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


# --------------------- DASHBOARD ---------------------
@app.route("/dashboard")
def dashboard():

    if 'user' not in session:
       flash("Please login first", "warning")
       return redirect(url_for("login"))
    students = Student.query.all()


    total_students = Student.query.count()
    total_rooms = Room.query.count()
    total_fees = sum(s.total_due for s in students)

    paid_fees = sum(s.total_paid for s in students)
    pending_fees = sum(s.pending_amount for s in students)
    total_beds = db.session.query(func.sum(Room.total_beds)).scalar() or 0
    occupied_beds = db.session.query(func.sum(Room.occupied_beds)).scalar() or 0

    return render_template(
        "dashboard.html",active_page='dashboard',
        total_students=total_students,
        total_rooms=total_rooms,
        total_beds=total_beds,
        available_beds=total_beds - occupied_beds,
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


@app.route("/students-list")
def students_list():
    students = Student.query.all()
    total_students = Student.query.count()
    return render_template("students_list.html", students=students, total_students=total_students)

@app.route("/rooms-list")
def rooms_list():
    rooms = Room.query.all()
    return render_template("rooms_list.html", rooms=rooms)


@app.route("/available_beds")
def available_beds():
    beds = Bed.query.filter_by(is_available=True).all()

    # Group by room_number
    rooms = {}
    for bed in beds:
        if bed.room_number not in rooms:
            rooms[bed.room_number] = []
        rooms[bed.room_number].append(bed.bed_label)

    return render_template("available_beds.html", rooms=rooms)



@app.route("/total_fees")
def total_fees():
    students = Student.query.all()

    data = []
    for s in students:
        data.append({
            "name": s.name,
            "total_fees": s.total_due # Make sure this column exists OR calculate it
        })

    return render_template("total_fees.html", data=data)



@app.route("/paid-fees")
def paid_fees_list():
    students = [s for s in Student.query.all() if s.total_paid > 0]
    return render_template("paid_fees.html", students=students)

@app.route("/pending-fees")
def pending_fees_list():
    students = [s for s in Student.query.all() if s.pending_amount > 0]
    return render_template("pending_fees.html", students=students)
    
# --------------------- STUDENTS ---------------------
@app.route("/students", methods=["GET", "POST"])
def students():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    # ---------- SEARCH LOGIC ----------
    search_name = request.args.get("search_name")
    student_profile = None

    if search_name:
        student_profile = Student.query.filter(
            Student.name.ilike(f"%{search_name}%")
        ).first()

    # ---------- ADD STUDENT ----------
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        mobile = request.form.get("mobile")
        emergency_contact = request.form.get("emergency_contact")
        join_date = datetime.strptime(
    request.form.get("join_date"), "%Y-%m-%d"
).date()


        if not emergency_contact or not re.fullmatch(r"\d{10}", emergency_contact):
            flash("Emergency contact must be exactly 10 digits", "danger")
            return redirect(url_for("students"))
        new_student = Student(
            name=name,
            email=email,
            mobile=mobile,
            emergency_contact=emergency_contact,
            join_date=join_date
        )

        db.session.add(new_student)
        db.session.commit()

        flash("Student added successfully!", "success")
        return redirect(url_for("students", page=1))
    # ---------- PAGINATION ----------
    page = request.args.get("page", 1, type=int)
    students = Student.query.paginate(page=page, per_page=6)

    return render_template(
        "students.html",active_page='students',
        students=students,
        student_profile=student_profile
    )

@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
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

    return render_template(
        'edit_student.html',
        student=student,
        beds=beds
    )



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



@app.route('/add_student', methods=['POST'])
def add_student():
    name = request.form.get("name")
    email = request.form.get("email")
    mobile = request.form.get("mobile")
    if not mobile.isdigit() or len(mobile) != 10:
        flash("Mobile number must be exactly 10 digits", "danger")
        return redirect(url_for("students"))
    emergency_contact = request.form.get('emergency_contact')
    join_date = request.form.get("join_date")
   

    if not re.fullmatch(r'\d{10}', emergency_contact):
        flash("Emergency contact must be 10 digits", "error")
        return redirect(url_for('students'))

    # ⭐ GET JOIN FEE FROM SETTINGS TABLE
    join_fee = get_join_fee()

    new_student = Student(
        name=name,
        email=email,
        mobile=mobile,
        emergency_contact=emergency_contact,
        join_date=join_date,
        join_fee=join_fee
    )

    db.session.add(new_student)
    db.session.commit()

    flash("Student added successfully!", "success")
    return redirect('/students')
    

@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    student = Student.query.get(student_id)
    if not student:
        return redirect('/students')

    # Get room number & bed label
    room_number = student.room
    bed_label = student.bed

    # 1️⃣ FREE the bed
    bed = Bed.query.filter_by(room_number=room_number, bed_label=bed_label).first()
    if bed:
        bed.status = "Available"      # bed becomes green
        bed.allocated_to = None       # clear student id

    # 2️⃣ DELETE student's fee records
    Fee.query.filter_by(student_id=student_id).delete()

    # 3️⃣ DELETE the student
    db.session.delete(student)

    # 4️⃣ Save all updates
    db.session.commit()

    return redirect('/students')


# --------------------- ROOMS ---------------------
@app.route("/rooms", methods=["GET", "POST"])
def rooms():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    # ---------------- ADD ROOM ----------------
    if request.method == "POST":
        room_number = request.form["room_number"]
        total_beds = int(request.form["total_beds"])
        

        if Room.query.filter_by(room_number=room_number).first():
            flash("❌ Room number already exists!", "danger")
            return redirect(url_for("rooms"))

        new_room = Room(
            room_number=room_number,
            total_beds=total_beds,
            occupied_beds=0
        
        )
        db.session.add(new_room)
        db.session.commit()

        create_beds_for_room(room_number, total_beds)

        flash("✅ Room created & beds added", "success")
        return redirect(url_for("rooms"))

    # ---------------- FLOOR PAGINATION ----------------
    page = request.args.get("page", 1, type=int)

    all_rooms = Room.query.order_by(Room.room_number).all()

    # Collect unique floors
    floors = sorted(set(get_floor(r.room_number) for r in all_rooms if get_floor(r.room_number) > 0))

    total_pages = len(floors)
    if total_pages == 0:
        return render_template(
            "rooms.html",
            rooms=[],
            current_floor=None,
            page=1,
            total_pages=1,
            active_page="rooms"

        )
    page = max(1, min(page, total_pages))
    current_floor = floors[page - 1]

    # Rooms of selected floor
    floor_rooms = [r for r in all_rooms if get_floor(r.room_number) == current_floor]

    rooms_data = []
    for room in floor_rooms:
        total_beds = Bed.query.filter_by(room_number=room.room_number).count()
        occupied_beds = Bed.query.filter_by(room_number=room.room_number, status="Occupied").count()
        available_beds = total_beds - occupied_beds

        rooms_data.append({
            "room_number": room.room_number,
            "total_beds": total_beds,
            "occupied_beds": occupied_beds,
            "available_beds": available_beds,
        
        })

    return render_template(
        "rooms.html",
        rooms=rooms_data,
        current_floor=current_floor,
        page=page,
        total_pages=total_pages,
        active_page='rooms'
    )

@app.route('/change_room/<int:student_id>', methods=['GET'])
def change_room(student_id):
    student = Student.query.get_or_404(student_id)

    # Only available beds
    beds = Bed.query.filter_by(status="Available").all()

    return render_template("change_room.html", student=student, beds=beds)

@app.route('/change_room/<int:student_id>', methods=['POST'])
def update_room(student_id):
    student = Student.query.get_or_404(student_id)
    new_bed_id = request.form.get("bed_id")

    new_bed = Bed.query.get_or_404(new_bed_id)
    old_bed = Bed.query.filter_by(allocated_to=student.id).first()

    # 1) Free old bed
    if old_bed:
        old_bed.status = "Available"
        old_bed.allocated_to = None

        # reduce occupied count
        old_room = Room.query.filter_by(room_number=old_bed.room_number).first()
        if old_room and old_room.occupied_beds > 0:
            old_room.occupied_beds -= 1

    # 2) Assign new bed
    new_bed.status = "Occupied"
    new_bed.allocated_to = student.id

    # 3) Update student table
    student.room = new_bed.room_number
    student.bed = new_bed.bed_label
    student.bed_no = new_bed.bed_id

    # 4) Increase occupied count
    new_room = Room.query.filter_by(room_number=new_bed.room_number).first()
    if new_room:
        new_room.occupied_beds += 1

    db.session.commit()

    flash("Room & Bed updated successfully!", "success")
    return redirect(url_for("students"))



# --------------------- GET BEDS API ---------------------

@app.route("/beds")
def beds_page():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    # -------- PAGE NUMBER --------
    page = request.args.get("page", 1, type=int)

    # -------- GET ALL BEDS (ORDERED) --------
    all_beds = Bed.query.order_by(Bed.room_number, Bed.bed_label).all()

    # -------- FIND UNIQUE FLOORS --------
    floors = sorted(
        set(get_floor(b.room_number) for b in all_beds if get_floor(b.room_number) > 0)
    )

    total_pages = len(floors)

    if total_pages == 0:
        return render_template(
            "beds.html",
            beds=[],
            page=1,
            total_pages=1,
            current_floor=None,
            active_page="beds"
        )

    page = max(1, min(page, total_pages))
    current_floor = floors[page - 1]

    # -------- FILTER BEDS BY FLOOR --------
    floor_beds = [
        b for b in all_beds
        if get_floor(b.room_number) == current_floor
    ]

    return render_template(
        "beds.html",
        beds=floor_beds,
        page=page,
        total_pages=total_pages,
        current_floor=current_floor,
        active_page="beds"
    )


@app.route("/get_beds/<int:room_id>")
def get_beds(room_id):
    room = Room.query.get(room_id)
    beds = Bed.query.filter_by(room_number=room.room_number).all()

    return jsonify([
        {"id": b.id, "bed_id": b.bed_id, "label": b.bed_label, "status": b.status}
        for b in beds
    ])


# --------------------- AVAILABILITY ---------------------
@app.route("/availability")
def availability():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    rooms_data = []
    rooms = Room.query.all()

    for r in rooms:
        
        rooms_data.append({
            "room_number": r.room_number,
            "total_beds": r.total_beds,
        
        })

    beds = Bed.query.all()

    unassigned = Student.query.filter(
        or_(Student.bed_no == None, Student.bed_no == "")
    ).all()

    return render_template(
        "availability.html",
        rooms=rooms_data,
        beds=beds,
        unassigned_students=unassigned
    )


@app.route("/assign_bed", methods=["POST"])
def assign_bed():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    bed_id = request.form["bed_id"]
    student_id = request.form["student_id"]

    bed = Bed.query.get(bed_id)
    student = Student.query.get(student_id)

    # If bed is already occupied → show name
    if bed.status == "Occupied":
        occupied_student = Student.query.get(bed.allocated_to)
        student_name = occupied_student.name if occupied_student else "Unknown Student"
        
        flash(f"This bed is already occupied by {student_name}", "danger")
        return redirect(url_for("availability"))
    room = Room.query.filter_by(room_number=bed.room_number).first()
    
    # Assign bed
    bed.status = "Occupied"
    bed.allocated_to = student.id

    student.bed_no = bed.bed_id
    student.room = bed.room_number
    student.bed = bed.bed_label
    student.rent = bed.bed_rent
    room.occupied_beds += 1

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
# --------------------- FEES ---------------------
@app.route("/fees")
def fees_page():
    students = Student.query.all()
    fees = Fee.query.order_by(Fee.id.desc()).all()
    return render_template("fees.html", students=students, fees=fees, active_page='fees')


@app.route("/api/student_info/<int:student_id>")
def api_student_info(student_id):
    s = Student.query.get(student_id)
    if not s:
        return jsonify({"error": "Student not found"}), 404

    # Ensure join_date exists and is a proper YYYY-MM-DD string
    month_formatted = ""
    try:
        if s.join_date:
            dt = datetime.strptime(s.join_date, "%Y-%m-%d")
            month_formatted = dt.strftime("%B %Y")   # e.g. "March 2025"
    except Exception:
        month_formatted = s.join_date or ""

    return jsonify({
        "id": s.id,
        "name": s.name,
        "join_date": s.join_date,
        "join_fee": s.join_fee or 0,
        "monthly_rent": get_rent(),
        "month_display": month_formatted
    })

@app.route("/add_fee", methods=["POST"])
def add_fee():
    student_id = request.form["student_id"]
    amount = int(request.form["amount"])
    month_str = request.form["month"]   # "2025-02"
    month_date = datetime.strptime(month_str, "%Y-%m").date()

    fee = Fee(
        student_id=student_id,
        amount_paid=amount,
        months_paid_for=month_date.month,
        payment_date=date.today()
    )

    db.session.add(fee)
    db.session.commit()

    flash("Fee recorded successfully", "success")
    return redirect(url_for("fees"))



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

@app.route("/fees/create", methods=["POST"])
def create_fee():
    if 'user' not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    data = request.get_json() or {}
    student_id = data.get("student_id")
    month = data.get("month")
    amount = float(data.get("amount") or 0)

    if not student_id:
        return {"error": "student_id missing"}, 400

    # Compute paid/pending/status relative to MONTHLY_RENT
    monthly = get_rent()
    amount_paid = min(amount, monthly)
    pending_amount = monthly - amount_paid
    status = "Paid" if pending_amount <= 0 else "Pending"


    fee = Fee(
        student_id=student_id,
        month=month or datetime.now().strftime("%B %Y"),
        amount_paid=amount_paid,
        pending_date=date.today(),
        months_paid_for=1
    )
    db.session.add(fee)
    db.session.commit()

    return {"success": True}, 200

@app.route("/logs")
def logs():
    if "user" not in session:
        flash("Please login first", "warning")
        return redirect(url_for("login"))

    logs = PaymentLog.query.order_by(PaymentLog.timestamp.desc()).all()
    return render_template("logs.html", logs=logs)



# --------------------- LOGOUT ---------------------
@app.route("/logout")
def logout():
    session.clear() 
    flash("Logged out", "info")
    return redirect(url_for("login"))

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response



# --------------------- RUN ---------------------
if __name__ == "__main__":
    app.run(debug=True)
