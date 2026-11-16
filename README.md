# CampusFlow — MVP бронирования аудиторий

Flask + SQLite (backend), один HTML-файл с JS без сборки (frontend), REST API с base URL `/api`.

## Запуск (≈2 минуты)

```bash
pip install -r requirements.txt
python app.py
```

Открыть: http://127.0.0.1:8000 — интерфейс, http://127.0.0.1:8000/docs — Swagger UI
(Swagger подтягивается с CDN, нужен интернет; список endpoints есть ниже).

База `campusflow.db` создаётся и заполняется seed-данными **автоматически при первом запуске**.
Даты в seed считаются от сегодняшнего дня (0 = сегодня, +1 = завтра). Чтобы пересоздать данные перед демо —
остановить сервер, удалить `campusflow.db`, запустить снова.

Проверка сценариев приёмки 1–8 одной командой: `python acceptance_test.py`
(она пересоздаёт базу, поэтому запускать при остановленном сервере).

## Пользователи (пароль = логин)

| login | роль |
|---|---|
| student1 | student |
| student2 | student |
| admin | admin |

## Авторизация (mock)

`POST /api/auth/login` возвращает `token` вида `mock-token-<login>`. Дальше заголовок
`Authorization: Bearer <token>`. Дополнительно принимается `X-User-Id: <id>`.
`GET /api/rooms*` — публичные (одинаково для всех rooms-endpoints).

## Endpoints

| Метод | Путь | Доступ |
|---|---|---|
| POST | /api/auth/login | все |
| GET | /api/rooms?building=&minCapacity=&equipment=a,b | все |
| GET | /api/rooms/{id} | все |
| GET | /api/rooms/{id}/free-slots?date=YYYY-MM-DD | все |
| POST | /api/bookings | student |
| GET | /api/bookings/my?status= | авторизованный |
| DELETE | /api/bookings/{id} | владелец брони (или admin) |
| GET | /api/admin/bookings?date=&roomId=&userId=&status= | admin |
| DELETE | /api/admin/bookings/{id} | admin |
| POST | /api/admin/rooms | admin |
| PUT | /api/admin/rooms/{id} | admin |
| DELETE | /api/admin/rooms/{id} | admin (409, если есть активные брони) |

Формат ошибок: `{"code": "...", "message": "...", "details": {...}}`.
Коды: VALIDATION_ERROR 400, UNAUTHORIZED 401, FORBIDDEN 403, ROOM_NOT_FOUND / BOOKING_NOT_FOUND 404,
BOOKING_CONFLICT / ALREADY_CANCELLED 409.

## Правила

Рабочий день 09:00–18:00, шаг 30 минут, дата не в прошлом. Конфликт: для комнаты и даты нет активной брони,
пересекающейся с `[start, end)`; касание границ (15:00/15:00) — не конфликт. Отменённые брони слот не занимают.

## Ограничения MVP

- mock-авторизация (без JWT), пароль не хранится — равен логину;
- админ не создаёт брони (по матрице прав); статистики загрузки, CSV и Docker нет;
- удаление аудитории возможно только без активных броней (расширение к контракту);
- запуск встроенным сервером Flask — для демо, не для production.
