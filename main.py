from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
import random
from collections import defaultdict

app = Flask(__name__, static_folder='Static', template_folder='Templates')
app.secret_key = "timetable_secret_2024"

# ─── DB CONNECTION ────────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="timetable_db"
    )

# ══════════════════════════════════════════════════════════════════
#  COLLEGE SCHEDULE CONSTANTS
# ══════════════════════════════════════════════════════════════════

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]

ALL_PERIODS = [
    "8:45-9:45",
    "9:45-10:45",
    "10:45-11:00",    # BREAK
    "11:00-12:00",
    "12:00-1:00",
    "1:00-1:45",      # LUNCH BREAK
    "1:45-2:45",
    "2:45-3:45"
]

# Consecutive 2-period pairs valid for lab blocks
LAB_PERIOD_PAIRS = [
    ("8:45-9:45",   "9:45-10:45"),
    ("11:00-12:00", "12:00-1:00"),
    ("1:45-2:45",   "2:45-3:45"),
]

TEACHING_PERIODS = [
    "8:45-9:45",
    "9:45-10:45",
    "11:00-12:00",
    "12:00-1:00",
    "1:45-2:45",
    "2:45-3:45"
]

FIXED_SLOTS = {
    ("MON", "10:45-11:00"): {"subject": "BREAK",       "type": "break"},
    ("TUE", "10:45-11:00"): {"subject": "BREAK",       "type": "break"},
    ("WED", "10:45-11:00"): {"subject": "BREAK",       "type": "break"},
    ("THU", "10:45-11:00"): {"subject": "BREAK",       "type": "break"},
    ("FRI", "10:45-11:00"): {"subject": "BREAK",       "type": "break"},
    ("SAT", "10:45-11:00"): {"subject": "BREAK",       "type": "break"},
    ("MON", "1:00-1:45"):   {"subject": "LUNCH BREAK", "type": "lunch"},
    ("TUE", "1:00-1:45"):   {"subject": "LUNCH BREAK", "type": "lunch"},
    ("WED", "1:00-1:45"):   {"subject": "LUNCH BREAK", "type": "lunch"},
    ("THU", "1:00-1:45"):   {"subject": "LUNCH BREAK", "type": "lunch"},
    ("FRI", "1:00-1:45"):   {"subject": "LUNCH BREAK", "type": "lunch"},
    ("SAT", "1:00-1:45"):   {"subject": "LUNCH BREAK", "type": "lunch"},
    ("SAT", "11:00-12:00"): {"subject": "IIILP",       "type": "activity"},
    ("SAT", "12:00-1:00"):  {"subject": "IIILP",       "type": "activity"},
    ("SAT", "1:45-2:45"):   {"subject": "NSS/YOGA/PE", "type": "activity"},
    ("SAT", "2:45-3:45"):   {"subject": "NSS/YOGA/PE", "type": "activity"},
}

# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def is_lab_subject(name):
    return name.strip().lower().endswith("_lab")

def display_name(name):
    if is_lab_subject(name):
        return name.strip()[:-4]
    return name.strip()

# ══════════════════════════════════════════════════════════════════
#  TIMETABLE GENERATOR CLASS
# ══════════════════════════════════════════════════════════════════

class TimetableGenerator:

    def __init__(self, subjects, teachers, rooms):
        self.subjects = subjects
        self.teachers = teachers
        self.theory_rooms = [r for r in rooms if "lab" not in r["name"].lower()]
        self.lab_rooms    = [r for r in rooms if "lab"     in r["name"].lower()]
        if not self.theory_rooms:
            self.theory_rooms = rooms
        if not self.lab_rooms:
            self.lab_rooms = rooms

        # Available slots for theory
        self.theory_slots = []
        for day in ["MON", "TUE", "WED", "THU", "FRI"]:
            for p in TEACHING_PERIODS:
                self.theory_slots.append((day, p))
        for p in ["8:45-9:45", "9:45-10:45"]:
            self.theory_slots.append(("SAT", p))

        # Available (day, pair) blocks for labs — MON to FRI only
        self.lab_blocks = []
        for day in ["MON", "TUE", "WED", "THU", "FRI"]:
            for pair in LAB_PERIOD_PAIRS:
                self.lab_blocks.append((day, pair))

        # Graph coloring conflict graph
        self.conflict_graph = defaultdict(set)
        for s1 in self.subjects:
            for s2 in self.subjects:
                if s1["id"] != s2["id"] and s1["teacher_id"] == s2["teacher_id"]:
                    self.conflict_graph[s1["id"]].add(s2["id"])

        # Tracking
        self.timetable    = {}
        self.teacher_slot = defaultdict(set)
        self.room_slot    = defaultdict(set)

    # ── THEORY CONSTRAINT CHECK ──────────────────────────────────
    def _theory_valid(self, subj_id, teacher_id, room_id, slot):
        if slot in self.teacher_slot[teacher_id]:
            return False
        if slot in self.room_slot[room_id]:
            return False
        if slot in FIXED_SLOTS:
            return False
        if slot in self.timetable:
            if self.timetable[slot]["subject_id"] in self.conflict_graph[subj_id]:
                return False
        # Same subject max once per day — only check 2-tuple theory keys
        day = slot[0]
        for key, info in self.timetable.items():
            if len(key) == 2 and key[0] == day and info["subject_id"] == subj_id:
                return False
        return True

    # ── LAB SCHEDULING: ROUND-ROBIN PAIRING ─────────────────────
    def _schedule_labs(self, lab_subjects, index):
        """
        Round-robin pairing across lab subjects:
          3 labs → 3 slots:
            slot 0: A1=lab[0], A2=lab[1]
            slot 1: A1=lab[1], A2=lab[2]
            slot 2: A1=lab[2], A2=lab[0]
        Each lab appears once as A1 and once as A2.
        For 2 labs: slot 0: A1=lab[0], A2=lab[1]
                    slot 1: A1=lab[1], A2=lab[0]
        """
        n = len(lab_subjects)
        if n == 0:
            return True
        # Build round-robin pairs
        pairs = []
        for i in range(n):
            pairs.append((lab_subjects[i], lab_subjects[(i + 1) % n]))

        shuffled_blocks = random.sample(self.lab_blocks, len(self.lab_blocks))
        return self._assign_lab_pairs(pairs, 0, shuffled_blocks, set())

    def _assign_lab_pairs(self, pairs, index, blocks, used_blocks):
        """Backtrack over lab blocks to assign each round-robin pair."""
        if index == len(pairs):
            return True

        subj_a1, subj_a2 = pairs[index]
        tid_a1 = subj_a1["teacher_id"]
        tid_a2 = subj_a2["teacher_id"]

        for i, (day, pair) in enumerate(blocks):
            if i in used_blocks:
                continue

            p1, p2 = pair

            # Check both teachers free for both periods
            valid = True
            for p in (p1, p2):
                slot = (day, p)
                if slot in FIXED_SLOTS:
                    valid = False; break
                if slot in self.teacher_slot[tid_a1]:
                    valid = False; break
                if slot in self.teacher_slot[tid_a2]:
                    valid = False; break
            if not valid:
                continue

            # Need 2 different lab rooms
            if len(self.lab_rooms) < 2:
                continue
            room_a1 = self.lab_rooms[0]
            room_a2 = self.lab_rooms[1]

            # Check rooms free
            room_ok = True
            for p in (p1, p2):
                slot = (day, p)
                if slot in self.room_slot[room_a1["id"]]:
                    room_ok = False; break
                if slot in self.room_slot[room_a2["id"]]:
                    room_ok = False; break
            if not room_ok:
                continue

            # Assign
            base_a1 = display_name(subj_a1["name"])
            base_a2 = display_name(subj_a2["name"])

            for p in (p1, p2):
                slot = (day, p)
                self.timetable[(day, p, "A1")] = {
                    "subject_id":   subj_a1["id"],
                    "subject_name": f"{base_a1} (A1)",
                    "teacher_id":   tid_a1,
                    "room_id":      room_a1["id"],
                    "room_name":    room_a1["name"],
                    "batch":        "A1",
                    "is_lab":       True,
                }
                self.timetable[(day, p, "A2")] = {
                    "subject_id":   subj_a2["id"],
                    "subject_name": f"{base_a2} (A2)",
                    "teacher_id":   tid_a2,
                    "room_id":      room_a2["id"],
                    "room_name":    room_a2["name"],
                    "batch":        "A2",
                    "is_lab":       True,
                }
                self.teacher_slot[tid_a1].add(slot)
                self.teacher_slot[tid_a2].add(slot)
                self.room_slot[room_a1["id"]].add(slot)
                self.room_slot[room_a2["id"]].add(slot)

            used_blocks.add(i)

            if self._assign_lab_pairs(pairs, index + 1, blocks, used_blocks):
                return True

            # Undo
            for p in (p1, p2):
                slot = (day, p)
                self.timetable.pop((day, p, "A1"), None)
                self.timetable.pop((day, p, "A2"), None)
                self.teacher_slot[tid_a1].discard(slot)
                self.teacher_slot[tid_a2].discard(slot)
                self.room_slot[room_a1["id"]].discard(slot)
                self.room_slot[room_a2["id"]].discard(slot)

            used_blocks.discard(i)

        return False

    # ── THEORY BACKTRACKING ──────────────────────────────────────
    def _backtrack_theory(self, assignments, index):
        if index == len(assignments):
            return True

        subj = assignments[index]
        sid  = subj["id"]
        tid  = subj["teacher_id"]

        shuffled = random.sample(self.theory_slots, len(self.theory_slots))

        for slot in shuffled:
            for room in self.theory_rooms:
                if self._theory_valid(sid, tid, room["id"], slot):
                    day, period = slot
                    self.timetable[slot] = {
                        "subject_id":   sid,
                        "subject_name": subj["name"],
                        "teacher_id":   tid,
                        "room_id":      room["id"],
                        "room_name":    room["name"],
                        "is_lab":       False,
                    }
                    self.teacher_slot[tid].add(slot)
                    self.room_slot[room["id"]].add(slot)

                    if self._backtrack_theory(assignments, index + 1):
                        return True

                    del self.timetable[slot]
                    self.teacher_slot[tid].discard(slot)
                    self.room_slot[room["id"]].discard(slot)

        return False

    # ── MAIN GENERATE ────────────────────────────────────────────
    def generate(self):
        lab_subjects    = [s for s in self.subjects if is_lab_subject(s["name"])]
        theory_subjects = [s for s in self.subjects if not is_lab_subject(s["name"])]

        # Step 1: schedule labs first (harder constraint)
        if not self._schedule_labs(lab_subjects, 0):
            return None

        # Step 2: schedule theory
        assignments = []
        for subj in theory_subjects:
            for _ in range(min(subj["hours_per_week"], 5)):
                assignments.append(subj)
        random.shuffle(assignments)

        if not self._backtrack_theory(assignments, 0):
            return None

        return self._format_timetable()

    # ── FORMAT FOR TEMPLATE ──────────────────────────────────────
    def _format_timetable(self):
        teacher_map = {t["id"]: t["name"] for t in self.teachers}
        grid = {day: {p: None for p in ALL_PERIODS} for day in DAYS}

        # Fixed slots
        for (day, period), info in FIXED_SLOTS.items():
            grid[day][period] = info

        # Lab slots — collect then fill BOTH periods of each pair
        lab_cells = {}
        for key, info in self.timetable.items():
            if len(key) == 3:
                day, period, batch = key
                k = (day, period)
                if k not in lab_cells:
                    lab_cells[k] = {"type": "lab_split", "a1": None, "a2": None}
                lab_cells[k][batch.lower()] = {
                    "subject_name": info["subject_name"],
                    "teacher":      teacher_map.get(info["teacher_id"], ""),
                    "room_name":    info["room_name"],
                }

        for (day, period), cell in lab_cells.items():
            for pair in LAB_PERIOD_PAIRS:
                if period in pair:
                    grid[day][pair[0]] = cell
                    grid[day][pair[1]] = cell
                    break

        # Theory slots
        for key, info in self.timetable.items():
            if len(key) == 2:
                day, period = key
                grid[day][period] = {
                    "type":         "theory",
                    "subject_name": info["subject_name"],
                    "teacher":      teacher_map.get(info["teacher_id"], ""),
                    "room_name":    info["room_name"],
                    "is_lab":       False,
                    "subject_id":   info["subject_id"],
                    "teacher_id":   info["teacher_id"],
                    "room_id":      info["room_id"],
                }

        return grid


# ══════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        db  = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = cur.fetchone()
        db.close()
        if user:
            session["user"] = user["username"]
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT COUNT(*) as c FROM subjects");   sub_count  = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM teachers");   tea_count  = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM rooms");      room_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM timetables"); tt_count   = cur.fetchone()["c"]
    db.close()
    stats = {"subjects": sub_count, "teachers": tea_count,
             "rooms": room_count, "timetables": tt_count}
    return render_template("dashboard.html", stats=stats, user=session["user"])

@app.route("/manage", methods=["GET", "POST"])
def manage():
    if "user" not in session:
        return redirect(url_for("login"))
    db  = get_db()
    cur = db.cursor(dictionary=True)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_teacher":
            cur.execute("INSERT INTO teachers (name) VALUES (%s)", (request.form["teacher_name"],))
            db.commit(); flash("Teacher added.", "success")
        elif action == "add_room":
            cur.execute("INSERT INTO rooms (name, capacity) VALUES (%s,%s)",
                        (request.form["room_name"], request.form["capacity"]))
            db.commit(); flash("Room added.", "success")
        elif action == "add_subject":
            cur.execute(
                "INSERT INTO subjects (name, teacher_id, hours_per_week) VALUES (%s,%s,%s)",
                (request.form["subject_name"], request.form["teacher_id"], request.form["hours_per_week"])
            )
            db.commit(); flash("Subject added.", "success")
        elif action == "delete_teacher":
            cur.execute("DELETE FROM teachers WHERE id=%s", (request.form["id"],))
            db.commit(); flash("Teacher deleted.", "info")
        elif action == "delete_subject":
            cur.execute("DELETE FROM subjects WHERE id=%s", (request.form["id"],))
            db.commit(); flash("Subject deleted.", "info")
        elif action == "delete_room":
            cur.execute("DELETE FROM rooms WHERE id=%s", (request.form["id"],))
            db.commit(); flash("Room deleted.", "info")
        return redirect(url_for("manage"))

    cur.execute("SELECT * FROM teachers ORDER BY name")
    teachers = cur.fetchall()
    cur.execute("SELECT s.*, t.name as teacher_name FROM subjects s JOIN teachers t ON s.teacher_id=t.id")
    subjects = cur.fetchall()
    cur.execute("SELECT * FROM rooms ORDER BY name")
    rooms = cur.fetchall()
    db.close()
    return render_template("manage.html", teachers=teachers, subjects=subjects,
                           rooms=rooms, is_lab_subject=is_lab_subject)

@app.route("/generate")
def generate():
    if "user" not in session:
        return redirect(url_for("login"))
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM subjects")
    subjects = cur.fetchall()
    cur.execute("SELECT * FROM teachers")
    teachers = cur.fetchall()
    cur.execute("SELECT * FROM rooms")
    rooms = cur.fetchall()

    if not subjects or not teachers or not rooms:
        flash("Please add subjects, teachers and rooms first!", "warning")
        db.close()
        return redirect(url_for("manage"))

    gen       = TimetableGenerator(subjects, teachers, rooms)
    timetable = gen.generate()

    if timetable is None:
        flash("Could not generate a clash-free timetable. Try reducing hours or adding more rooms.", "danger")
        db.close()
        return redirect(url_for("dashboard"))

    cur.execute("DELETE FROM timetables")
    for day in DAYS:
        for period in ALL_PERIODS:
            cell = timetable[day][period]
            if not cell:
                continue
            ctype = cell.get("type")
            if ctype == "theory":
                cur.execute(
                    "INSERT INTO timetables (day, period, subject_id, teacher_id, room_id, batch) VALUES (%s,%s,%s,%s,%s,%s)",
                    (day, period, cell["subject_id"], cell["teacher_id"], cell["room_id"], "")
                )
            elif ctype == "lab_split":
                for bkey in ("a1", "a2"):
                    b = cell.get(bkey)
                    if b:
                        cur.execute("SELECT id FROM rooms WHERE name=%s",    (b["room_name"],))
                        r = cur.fetchone()
                        cur.execute("SELECT id FROM teachers WHERE name=%s", (b["teacher"],))
                        t = cur.fetchone()
                        # find lab subject: display name + _lab
                        base = b["subject_name"].split(" (")[0]
                        cur.execute("SELECT id FROM subjects WHERE name=%s", (base + "_lab",))
                        s = cur.fetchone()
                        if r and s and t:
                            cur.execute(
                                "INSERT INTO timetables (day, period, subject_id, teacher_id, room_id, batch) VALUES (%s,%s,%s,%s,%s,%s)",
                                (day, period, s["id"], t["id"], r["id"], bkey.upper())
                            )
    db.commit()
    db.close()
    flash("Timetable generated successfully!", "success")
    return redirect(url_for("result"))

@app.route("/result")
def result():
    if "user" not in session:
        return redirect(url_for("login"))
    db  = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT t.day, t.period, t.batch,
               s.name as subject, te.name as teacher, r.name as room
        FROM timetables t
        JOIN subjects s  ON t.subject_id = s.id
        JOIN teachers te ON t.teacher_id = te.id
        JOIN rooms r     ON t.room_id    = r.id
        ORDER BY t.day, t.period, t.batch
    """)
    rows = cur.fetchall()
    db.close()

    grid = {day: {p: None for p in ALL_PERIODS} for day in DAYS}
    for (day, period), info in FIXED_SLOTS.items():
        grid[day][period] = info

    # First pass: collect lab cells
    lab_cells = {}
    for row in rows:
        day, period = row["day"], row["period"]
        batch = (row["batch"] or "").upper()
        subj_name = display_name(row["subject"])

        if batch in ("A1", "A2"):
            k = (day, period)
            if k not in lab_cells:
                lab_cells[k] = {"type": "lab_split", "a1": None, "a2": None}
            bkey = "a1" if batch == "A1" else "a2"
            lab_cells[k][bkey] = {
                "subject_name": f"{subj_name} ({batch})",
                "teacher":      row["teacher"],
                "room_name":    row["room"],
            }
        else:
            grid[day][period] = {
                "type":         "theory",
                "subject_name": row["subject"],
                "teacher":      row["teacher"],
                "room_name":    row["room"],
            }

    # Second pass: fill BOTH periods of each lab pair
    for (day, period), cell in lab_cells.items():
        for pair in LAB_PERIOD_PAIRS:
            if period in pair:
                grid[day][pair[0]] = cell
                grid[day][pair[1]] = cell
                break

    return render_template("result.html", grid=grid, days=DAYS, periods=ALL_PERIODS)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/index")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)