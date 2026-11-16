"""Тесты API. Запуск: python -m pytest -q  (нужен pip install pytest).
Каждый тест работает на своей свежей БД с seed-данными."""
import os
import tempfile
from datetime import date, timedelta

import app as backend

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def client():
    backend.DB = os.path.join(tempfile.mkdtemp(), "test.db")  # чистая БД для теста
    backend.init_db()
    return backend.app.test_client()


def auth(login):
    return {"Authorization": "Bearer mock-token-" + login}


def book(c, who="student1", room=4, start="14:00", end="15:00"):
    body = {"roomId": room, "date": TOMORROW, "startTime": start, "endTime": end, "comment": "тест"}
    return c.post("/api/bookings", json=body, headers=auth(who))


# ---- сценарии приёмки 1-8 ----
def test_1_filters():
    c = client()
    r = c.get("/api/rooms?building=B&minCapacity=20&equipment=projector")
    assert r.status_code == 200
    assert [x["name"] for x in r.get_json()] == ["B-101", "B-204"]


def test_2_free_slots():
    c = client()
    slots = c.get(f"/api/rooms/4/free-slots?date={TOMORROW}").get_json()["freeSlots"]
    assert any(s["startTime"] <= "14:00" and s["endTime"] >= "15:00" for s in slots)


def test_3_booking_created():
    c = client()
    r = book(c)
    assert r.status_code == 201
    mine = c.get("/api/bookings/my", headers=auth("student1")).get_json()
    assert any(b["id"] == r.get_json()["id"] for b in mine)


def test_4_conflict_409():
    c = client()
    book(c)
    r = book(c, who="student2")
    assert r.status_code == 409 and r.get_json()["code"] == "BOOKING_CONFLICT"


def test_4_touching_borders_is_not_conflict():
    c = client()
    book(c, start="14:00", end="15:00")
    assert book(c, who="student2", start="15:00", end="16:00").status_code == 201
    assert book(c, who="student2", start="13:00", end="14:00").status_code == 201


def test_4_overlap_inside_is_conflict():
    c = client()
    book(c, start="14:00", end="16:00")
    assert book(c, who="student2", start="14:30", end="15:00").status_code == 409


def test_5_cancel_own_returns_slot():
    c = client()
    booking_id = book(c).get_json()["id"]
    assert c.delete(f"/api/bookings/{booking_id}", headers=auth("student1")).status_code == 200
    slots = c.get(f"/api/rooms/4/free-slots?date={TOMORROW}").get_json()["freeSlots"]
    assert any(s["startTime"] <= "14:00" and s["endTime"] >= "15:00" for s in slots)
    assert c.delete(f"/api/bookings/{booking_id}", headers=auth("student1")).status_code == 409


def test_6_cancel_foreign_403():
    c = client()
    booking_id = book(c).get_json()["id"]
    assert c.delete(f"/api/bookings/{booking_id}", headers=auth("student2")).status_code == 403
    mine = c.get("/api/bookings/my?status=active", headers=auth("student1")).get_json()
    assert any(b["id"] == booking_id for b in mine)


def test_7_admin_sees_and_cancels_all():
    c = client()
    assert c.get("/api/admin/bookings", headers=auth("student1")).status_code == 403
    all_bookings = c.get("/api/admin/bookings", headers=auth("admin")).get_json()
    foreign = [b for b in all_bookings if b["userId"] == 2 and b["status"] == "active"][0]
    assert c.delete(f"/api/admin/bookings/{foreign['id']}", headers=auth("admin")).status_code == 200


def test_8_seed_loaded():
    c = client()
    assert len(c.get("/api/rooms").get_json()) >= 10
    assert c.post("/api/auth/login", json={"login": "admin", "password": "admin"}).status_code == 200


# ---- валидация и права ----
def test_validation_errors():
    c = client()
    assert c.get("/api/rooms/1/free-slots?date=2020-01-01").status_code == 400
    assert book(c, start="09:15", end="10:00").status_code == 400
    assert book(c, start="17:30", end="18:30").status_code == 400
    assert book(c, start="15:00", end="14:00").status_code == 400
    assert c.get("/api/rooms?building=Z").status_code == 400


def test_auth_and_roles():
    c = client()
    assert c.post("/api/bookings", json={}).status_code == 401
    assert book(c, who="admin").status_code == 403  # админ не создаёт брони
    assert c.get("/api/rooms/999").status_code == 404


# ---- дополнения ----
def test_recommend_returns_free_rooms_only():
    c = client()
    url = f"/api/rooms/recommend?date={TOMORROW}&startTime=10:00&endTime=11:00&minCapacity=15"
    names = [r["name"] for r in c.get(url).get_json()]
    assert len(names) == 3 and "A-101" not in names  # A-101 занята 10:00-11:30
    assert names == ["A-203", "D-202", "A-102"]       # сначала самые маленькие подходящие


def test_admin_stats():
    c = client()
    assert c.get("/api/admin/stats", headers=auth("student1")).status_code == 403
    rows = c.get("/api/admin/stats", headers=auth("admin")).get_json()["rows"]
    a = [r for r in rows if r["date"] == TOMORROW and r["building"] == "A"][0]
    assert a["bookings"] == 2 and a["bookedHours"] == 3.0 and a["loadPercent"] == 11.1


def test_csv_export():
    c = client()
    assert c.get("/api/admin/bookings/export.csv", headers=auth("student1")).status_code == 403
    r = c.get("/api/admin/bookings/export.csv?status=active", headers=auth("admin"))
    lines = r.get_data(as_text=True).strip().splitlines()
    assert r.mimetype == "text/csv" and "id,room,building" in lines[0] and len(lines) == 7
