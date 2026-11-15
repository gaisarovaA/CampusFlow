"""CampusFlow MVP: бронирование аудиторий. Flask + SQLite, весь backend в одном файле."""
import os
import re
import sqlite3
import threading
from datetime import date, timedelta

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campusflow.db")
BUILDINGS = {"A", "B", "C", "D"}
EQUIPMENT = {"projector", "whiteboard", "computers", "audio", "video"}
DAY_START, DAY_END, STEP = 9 * 60, 18 * 60, 30  # рабочий день 09:00-18:00, сетка 30 минут
lock = threading.Lock()  # чтобы две брони не прошли проверку конфликта одновременно

app = Flask(__name__, static_folder="static", static_url_path="")


# ---------- Ошибки: единый формат {code, message, details} ----------
class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status = status
        self.body = {"code": code, "message": message, "details": details or {}}


def bad(message, details=None):
    return ApiError(400, "VALIDATION_ERROR", message, details)


@app.errorhandler(ApiError)
def on_api_error(e):
    return jsonify(e.body), e.status


@app.errorhandler(HTTPException)  # 404/405 от самого Flask тоже отдаём в нашем формате
def on_http_error(e):
    return jsonify({"code": e.name.upper().replace(" ", "_"), "message": e.description, "details": {}}), e.code


# ---------- Работа с БД ----------
def q(sql, *args):
    """SELECT -> список словарей."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def run(sql, *args):
    """INSERT/UPDATE/DELETE -> id последней вставленной строки."""
    conn = sqlite3.connect(DB)
    cur = conn.execute(sql, args)
    conn.commit()
    conn.close()
    return cur.lastrowid


def init_db():
    conn = sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, login TEXT UNIQUE, display_name TEXT, role TEXT);
        CREATE TABLE IF NOT EXISTS rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, building TEXT,
                                          floor INTEGER, capacity INTEGER, equipment TEXT);
        CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id INTEGER, user_id INTEGER,
                                             date TEXT, start_time TEXT, end_time TEXT, status TEXT, comment TEXT);
    """)
    if not conn.execute("SELECT 1 FROM users").fetchone():  # seed только в пустую БД
        conn.executemany("INSERT INTO users VALUES (?,?,?,?)", [
            (1, "student1", "Иван Студентов", "student"),
            (2, "student2", "Мария Студентова", "student"),
            (3, "admin", "Администратор Пупкин", "admin"),
        ])
        conn.executemany("INSERT INTO rooms (id,name,building,floor,capacity,equipment) VALUES (?,?,?,?,?,?)", [
            (1, "A-101", "A", 1, 30, "projector,whiteboard"),
            (2, "A-102", "A", 1, 20, "whiteboard"),
            (3, "A-203", "A", 2, 15, "computers,projector"),
            (4, "B-101", "B", 1, 40, "projector,audio"),
            (5, "B-204", "B", 2, 25, "projector,whiteboard,audio"),
            (6, "B-305", "B", 3, 10, "whiteboard"),
            (7, "C-110", "C", 1, 50, "projector,audio,video"),
            (8, "C-210", "C", 2, 35, "computers"),
            (9, "C-301", "C", 3, 12, "whiteboard,projector"),
            (10, "D-101", "D", 1, 60, "projector,audio,video"),
            (11, "D-202", "D", 2, 18, "whiteboard"),
            (12, "D-303", "D", 3, 24, "projector,computers"),
        ])
        # (id, room, user, смещение в днях от сегодня, начало, конец, статус, комментарий)
        seed = [
            (1, 1, 1, 1, "10:00", "11:30", "active", "Консультация"),
            (2, 1, 2, 1, "14:00", "15:30", "active", "Подготовка к семинару"),
            (3, 4, 2, 1, "09:00", "10:30", "active", "Собрание группы"),
            (4, 7, 3, 1, "12:00", "14:00", "active", "Встреча с деканом"),
            (5, 1, 1, 0, "15:00", "16:00", "cancelled", "Отменили"),
            (6, 10, 2, 2, "13:00", "15:00", "active", "Лекция"),
            (7, 5, 1, 1, "16:00", "17:30", "active", "Кружок"),
        ]
        for i, room, user, off, start, end, status, comment in seed:
            day = (date.today() + timedelta(days=off)).isoformat()
            conn.execute("INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?)", (i, room, user, day, start, end, status, comment))
        conn.commit()
    conn.close()


# ---------- Преобразование строк БД в JSON контракта ----------
def room_json(r):
    return {"id": r["id"], "name": r["name"], "building": r["building"], "floor": r["floor"],
            "capacity": r["capacity"], "equipment": r["equipment"].split(",") if r["equipment"] else []}


BOOKING_SQL = ("SELECT b.*, r.name AS room_name, u.display_name FROM bookings b "
               "JOIN rooms r ON r.id = b.room_id JOIN users u ON u.id = b.user_id")


def booking_json(b):
    return {"id": b["id"], "roomId": b["room_id"], "roomName": b["room_name"], "userId": b["user_id"],
            "userDisplayName": b["display_name"], "date": b["date"], "startTime": b["start_time"],
            "endTime": b["end_time"], "status": b["status"], "comment": b["comment"]}


def get_room(room_id):
    rows = q("SELECT * FROM rooms WHERE id=?", room_id)
    if not rows:
        raise ApiError(404, "ROOM_NOT_FOUND", "Аудитория не найдена", {"roomId": room_id})
    return rows[0]


# ---------- Авторизация (mock): Bearer mock-token-<login> или X-User-Id ----------
def current_user():
    auth, uid = request.headers.get("Authorization", ""), request.headers.get("X-User-Id", "")
    prefix = "Bearer mock-token-"
    rows = []
    if auth.startswith(prefix):
        rows = q("SELECT * FROM users WHERE login=?", auth[len(prefix):])
    elif uid.isdigit():
        rows = q("SELECT * FROM users WHERE id=?", int(uid))
    if not rows:
        raise ApiError(401, "UNAUTHORIZED", "Требуется авторизация")
    return rows[0]


def admin_user():
    user = current_user()
    if user["role"] != "admin":
        raise ApiError(403, "FORBIDDEN", "Доступно только администратору")
    return user


# ---------- Валидация ----------
def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise bad("Ожидается JSON-объект в теле запроса")
    return body


def to_min(t):
    m = re.fullmatch(r"(\d\d):(\d\d)", t) if isinstance(t, str) else None
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise bad("Время должно быть в формате HH:MM", {"value": t})
    return int(m[1]) * 60 + int(m[2])


def to_str(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def check_date_format(d):
    if not isinstance(d, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
        raise bad("Дата должна быть в формате YYYY-MM-DD", {"date": d})
    try:
        date.fromisoformat(d)
    except ValueError:
        raise bad("Такой даты не существует", {"date": d})


def check_future_date(d):
    check_date_format(d)
    if date.fromisoformat(d) < date.today():
        raise bad("Дата в прошлом", {"date": d})


def check_status(s):
    if s is not None and s not in ("active", "cancelled"):
        raise bad("status должен быть active или cancelled", {"status": s})


def to_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise bad(f"{name} должен быть целым числом", {name: value})


# ---------- Auth ----------
@app.post("/api/auth/login")
def login():
    body = json_body()
    if not isinstance(body.get("login"), str) or not isinstance(body.get("password"), str):
        raise bad("Нужны поля login и password")
    rows = q("SELECT * FROM users WHERE login=?", body["login"])
    if not rows or body["password"] != rows[0]["login"]:  # в seed пароль == логин
        raise ApiError(401, "UNAUTHORIZED", "Неверный логин или пароль")
    u = rows[0]
    return jsonify({"token": "mock-token-" + u["login"],
                    "user": {"id": u["id"], "login": u["login"], "displayName": u["display_name"], "role": u["role"]}})


# ---------- Rooms ----------
@app.get("/api/rooms")
def list_rooms():
    building = request.args.get("building")
    min_cap = request.args.get("minCapacity")
    equipment = [x for x in request.args.get("equipment", "").split(",") if x]
    if building is not None and building not in BUILDINGS:
        raise bad("building должен быть A, B, C или D", {"building": building})
    if min_cap is not None:
        min_cap = to_int(min_cap, "minCapacity")
        if min_cap <= 0:
            raise bad("minCapacity должен быть больше 0", {"minCapacity": min_cap})
    if any(x not in EQUIPMENT for x in equipment):
        raise bad("Неизвестное оборудование", {"allowed": sorted(EQUIPMENT)})
    result = []
    for r in q("SELECT * FROM rooms ORDER BY id"):
        room = room_json(r)
        if building and room["building"] != building:
            continue
        if min_cap and room["capacity"] < min_cap:
            continue
        if not all(x in room["equipment"] for x in equipment):  # должно быть всё оборудование из списка
            continue
        result.append(room)
    return jsonify(result)


@app.get("/api/rooms/<int:room_id>")
def one_room(room_id):
    return jsonify(room_json(get_room(room_id)))


@app.get("/api/rooms/<int:room_id>/free-slots")
def free_slots(room_id):
    get_room(room_id)
    day = request.args.get("date")
    check_future_date(day)
    taken = q("SELECT start_time, end_time FROM bookings WHERE room_id=? AND date=? AND status='active' "
              "ORDER BY start_time", room_id, day)
    free, cursor = [], DAY_START
    for t in taken:  # идём по броням слева направо и собираем промежутки между ними
        start, end = to_min(t["start_time"]), to_min(t["end_time"])
        if start > cursor:
            free.append({"startTime": to_str(cursor), "endTime": to_str(start)})
        cursor = max(cursor, end)
    if cursor < DAY_END:
        free.append({"startTime": to_str(cursor), "endTime": to_str(DAY_END)})
    return jsonify({"roomId": room_id, "date": day, "freeSlots": free})


# ---------- Bookings ----------
@app.post("/api/bookings")
def create_booking():
    user = current_user()
    if user["role"] == "admin":
        raise ApiError(403, "FORBIDDEN", "Администратор не создаёт брони")
    body = json_body()
    for field in ("roomId", "date", "startTime", "endTime"):
        if field not in body:
            raise bad(f"Не заполнено обязательное поле {field}", {"field": field})
    if type(body["roomId"]) is not int:
        raise bad("roomId должен быть целым числом")
    comment = body.get("comment") or ""
    if not isinstance(comment, str):
        raise bad("comment должен быть строкой")

    check_future_date(body["date"])
    start, end = to_min(body["startTime"]), to_min(body["endTime"])
    if start >= end:
        raise bad("Время окончания должно быть позже начала")
    if start % STEP or end % STEP:
        raise bad("Время должно быть кратно 30 минутам")
    if start < DAY_START or end > DAY_END:
        raise bad("Бронировать можно только с 09:00 до 18:00")
    get_room(body["roomId"])

    details = {"roomId": body["roomId"], "date": body["date"], "startTime": body["startTime"], "endTime": body["endTime"]}
    with lock:  # проверка и вставка - одним куском, чтобы не было гонки
        # пересечение интервалов: старт существующей < конец новой И конец существующей > старт новой
        clash = q("SELECT id FROM bookings WHERE room_id=? AND date=? AND status='active' "
                  "AND start_time < ? AND end_time > ?",
                  body["roomId"], body["date"], body["endTime"], body["startTime"])
        if clash:
            raise ApiError(409, "BOOKING_CONFLICT", "Аудитория уже забронирована на это время", details)
        new_id = run("INSERT INTO bookings (room_id,user_id,date,start_time,end_time,status,comment) "
                     "VALUES (?,?,?,?,?,'active',?)",
                     body["roomId"], user["id"], body["date"], body["startTime"], body["endTime"], comment)
    return jsonify(booking_json(q(BOOKING_SQL + " WHERE b.id=?", new_id)[0])), 201


@app.get("/api/bookings/my")
def my_bookings():
    user = current_user()
    status = request.args.get("status")
    check_status(status)
    sql, args = BOOKING_SQL + " WHERE b.user_id=?", [user["id"]]
    if status:
        sql, args = sql + " AND b.status=?", args + [status]
    return jsonify([booking_json(b) for b in q(sql + " ORDER BY b.date, b.start_time", *args)])


def cancel(booking_id, user):
    rows = q(BOOKING_SQL + " WHERE b.id=?", booking_id)
    if not rows:
        raise ApiError(404, "BOOKING_NOT_FOUND", "Бронь не найдена", {"bookingId": booking_id})
    if rows[0]["user_id"] != user["id"] and user["role"] != "admin":
        raise ApiError(403, "FORBIDDEN", "Нельзя отменить чужую бронь")
    if rows[0]["status"] == "cancelled":
        raise ApiError(409, "ALREADY_CANCELLED", "Бронь уже отменена", {"bookingId": booking_id})
    run("UPDATE bookings SET status='cancelled' WHERE id=?", booking_id)
    return jsonify({"id": booking_id, "status": "cancelled"})


@app.delete("/api/bookings/<int:booking_id>")
def cancel_own(booking_id):
    return cancel(booking_id, current_user())


# ---------- Admin ----------
@app.get("/api/admin/bookings")
def admin_bookings():
    admin_user()
    status = request.args.get("status")
    check_status(status)
    sql, args = BOOKING_SQL + " WHERE 1=1", []
    if request.args.get("date"):
        check_date_format(request.args["date"])
        sql, args = sql + " AND b.date=?", args + [request.args["date"]]
    if request.args.get("roomId"):
        sql, args = sql + " AND b.room_id=?", args + [to_int(request.args["roomId"], "roomId")]
    if request.args.get("userId"):
        sql, args = sql + " AND b.user_id=?", args + [to_int(request.args["userId"], "userId")]
    if status:
        sql, args = sql + " AND b.status=?", args + [status]
    return jsonify([booking_json(b) for b in q(sql + " ORDER BY b.date, b.start_time", *args)])


@app.delete("/api/admin/bookings/<int:booking_id>")
def admin_cancel(booking_id):
    return cancel(booking_id, admin_user())


def room_from_body(room_id=None):
    """Проверяет тело POST/PUT для аудитории, возвращает кортеж полей."""
    b = json_body()
    name, building, floor, cap, eq = (b.get(k) for k in ("name", "building", "floor", "capacity", "equipment"))
    if not isinstance(name, str) or not name.strip():
        raise bad("name не может быть пустым")
    if building not in BUILDINGS:
        raise bad("building должен быть A, B, C или D")
    if type(floor) is not int or floor < 1:
        raise bad("floor должен быть целым числом >= 1")
    if type(cap) is not int or cap <= 0:
        raise bad("capacity должен быть целым числом > 0")
    if not isinstance(eq, list) or any(x not in EQUIPMENT for x in eq):
        raise bad("equipment — список из: " + ", ".join(sorted(EQUIPMENT)))
    same = q("SELECT id FROM rooms WHERE name=?", name.strip())
    if same and same[0]["id"] != room_id:
        raise bad("Аудитория с таким name уже существует", {"name": name})
    return name.strip(), building, floor, cap, ",".join(dict.fromkeys(eq))


@app.post("/api/admin/rooms")
def admin_create_room():
    admin_user()
    new_id = run("INSERT INTO rooms (name,building,floor,capacity,equipment) VALUES (?,?,?,?,?)", *room_from_body())
    return jsonify(room_json(get_room(new_id))), 201


@app.put("/api/admin/rooms/<int:room_id>")
def admin_update_room(room_id):
    admin_user()
    get_room(room_id)
    run("UPDATE rooms SET name=?, building=?, floor=?, capacity=?, equipment=? WHERE id=?",
        *room_from_body(room_id), room_id)
    return jsonify(room_json(get_room(room_id)))


@app.delete("/api/admin/rooms/<int:room_id>")
def admin_delete_room(room_id):
    admin_user()
    get_room(room_id)
    if q("SELECT 1 FROM bookings WHERE room_id=? AND status='active'", room_id):
        raise ApiError(409, "ROOM_HAS_ACTIVE_BOOKINGS", "Сначала отмените активные брони этой аудитории")
    run("DELETE FROM bookings WHERE room_id=?", room_id)
    run("DELETE FROM rooms WHERE id=?", room_id)
    return jsonify({"id": room_id, "deleted": True})


# ---------- Страницы ----------
@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/docs")
def docs():
    return app.send_static_file("docs.html")


init_db()

if __name__ == "__main__":
    app.run(port=8000)
