"""Прогон 8 сценариев приёмки на чистой БД: python acceptance_test.py"""
import os
from datetime import date, timedelta

import app as backend

if os.path.exists(backend.DB):
    os.remove(backend.DB)
backend.init_db()
c = backend.app.test_client()
tomorrow = (date.today() + timedelta(days=1)).isoformat()


def auth(login):
    return {"Authorization": "Bearer mock-token-" + login}


def check(name, cond):
    print(("OK   " if cond else "FAIL ") + name)
    assert cond, name


r = c.get("/api/rooms?building=B&minCapacity=20&equipment=projector")
check("1. фильтры: только B-101 и B-204", [x["name"] for x in r.get_json()] == ["B-101", "B-204"])

r = c.get(f"/api/rooms/4/free-slots?date={tomorrow}")
check("2. слот 14:00-15:00 свободен", any(s["startTime"] <= "14:00" and s["endTime"] >= "15:00" for s in r.get_json()["freeSlots"]))

body = {"roomId": 4, "date": tomorrow, "startTime": "14:00", "endTime": "15:00", "comment": "тест"}
r = c.post("/api/bookings", json=body, headers=auth("student1"))
booking_id = r.get_json()["id"]
mine = c.get("/api/bookings/my", headers=auth("student1")).get_json()
check("3. бронь создана (201) и видна в /my", r.status_code == 201 and any(b["id"] == booking_id for b in mine))

r = c.post("/api/bookings", json=body, headers=auth("student2"))
check("4. повторная бронь -> 409 BOOKING_CONFLICT", r.status_code == 409 and r.get_json()["code"] == "BOOKING_CONFLICT")
body2 = dict(body, startTime="15:00", endTime="16:00")
check("4a. касание границ не конфликт", c.post("/api/bookings", json=body2, headers=auth("student2")).status_code == 201)

r = c.delete(f"/api/bookings/{booking_id}", headers=auth("student2"))
check("6. чужая бронь -> 403", r.status_code == 403)
check("6a. бронь осталась активной", any(b["id"] == booking_id for b in c.get("/api/bookings/my?status=active", headers=auth("student1")).get_json()))

r = c.delete(f"/api/bookings/{booking_id}", headers=auth("student1"))
slots = c.get(f"/api/rooms/4/free-slots?date={tomorrow}").get_json()["freeSlots"]
check("5. своя отмена -> 200, слот снова свободен", r.status_code == 200 and any(s["startTime"] <= "14:00" and s["endTime"] >= "15:00" for s in slots))
check("5a. повторная отмена -> 409", c.delete(f"/api/bookings/{booking_id}", headers=auth("student1")).status_code == 409)

check("7. студент не видит admin/bookings (403)", c.get("/api/admin/bookings", headers=auth("student1")).status_code == 403)
all_b = c.get("/api/admin/bookings", headers=auth("admin")).get_json()
other = [b for b in all_b if b["userId"] == 2 and b["status"] == "active"][0]
check("7a. админ видит все брони", len(all_b) >= 7)
check("7b. админ отменяет бронь student2", c.delete(f"/api/admin/bookings/{other['id']}", headers=auth("admin")).status_code == 200)

check("валидация: прошлая дата -> 400", c.get("/api/rooms/1/free-slots?date=2020-01-01").status_code == 400)
check("валидация: 09:15 -> 400", c.post("/api/bookings", json=dict(body, startTime="09:15"), headers=auth("student1")).status_code == 400)
check("валидация: 17:30-18:30 -> 400", c.post("/api/bookings", json=dict(body, startTime="17:30", endTime="18:30"), headers=auth("student1")).status_code == 400)
check("нет токена -> 401", c.post("/api/bookings", json=body).status_code == 401)
check("нет аудитории -> 404", c.get("/api/rooms/999").status_code == 404)
print("\nВсе проверки пройдены")
