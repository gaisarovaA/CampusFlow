# CampusFlow — MVP бронирования аудиторий

Flask + SQLite (backend), один HTML-файл с JS без сборки (frontend), REST API с base URL `/api`.

## Запуск

```bash
pip install -r requirements.txt
python app.py
```

Открыть: http://127.0.0.1:8000 — интерфейс, http://127.0.0.1:8000/docs — Swagger UI
(Swagger подтягивается с CDN, нужен интернет; список endpoints есть ниже).

База `campusflow.db` создаётся и заполняется seed-данными **автоматически при первом запуске**.
Даты в seed считаются от сегодняшнего дня (0 = сегодня, +1 = завтра). Чтобы пересоздать данные перед демо —
остановить сервер, удалить `campusflow.db`, запустить снова.

## Тесты

```bash
pip install pytest
python -m pytest -q
```

15 тестов: сценарии приёмки 1–8, граничные случаи конфликта (касание границ, вложенный интервал), валидация, роли, рекомендация, статистика, CSV. Каждый тест работает на своей временной базе, рабочий `campusflow.db` не затрагивается.

## Git

```bash
git init && git add . && git commit -m "CampusFlow MVP"
```

`.gitignore` уже есть (база, кэши).

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
| GET | /api/rooms/recommend?date=&startTime=&endTime=&minCapacity=&building=&equipment= | все — до 3 свободных аудиторий |
| GET | /api/rooms/{id} | все |
| GET | /api/rooms/{id}/free-slots?date=YYYY-MM-DD | все |
| POST | /api/bookings | student |
| GET | /api/bookings/my?status= | авторизованный |
| DELETE | /api/bookings/{id} | владелец брони (или admin) |
| GET | /api/admin/bookings?date=&roomId=&userId=&status= | admin |
| GET | /api/admin/bookings/export.csv | admin — экспорт CSV (те же фильтры) |
| GET | /api/admin/stats | admin — загрузка по дням и корпусам |
| DELETE | /api/admin/bookings/{id} | admin |
| POST | /api/admin/rooms | admin |
| PUT | /api/admin/rooms/{id} | admin |
| DELETE | /api/admin/rooms/{id} | admin (409, если есть активные брони) |

Формат ошибок: `{"code": "...", "message": "...", "details": {...}}`.
Коды: VALIDATION_ERROR 400, UNAUTHORIZED 401, FORBIDDEN 403, ROOM_NOT_FOUND / BOOKING_NOT_FOUND 404,
BOOKING_CONFLICT / ALREADY_CANCELLED 409.

## Интерфейс

- **Поиск и бронь** — фильтры, свободные слоты на карточках, клик по слоту открывает форму; кнопка «Подобрать 3 аудитории».
- **Карта** — план помещения с зонами аудиторий (зелёная — свободна на выбранный интервал, красная — занята), клик по зелёной зоне открывает бронь.
  Зоны привязаны к аудиториям по названию в словаре `ZONES` в `static/index.html`; у аудиторий, добавленных админом, зоны на карте нет, в поиске они доступны.
- **Мои брони** (студент), **Все брони + CSV**, **Статистика**, **Управление аудиториями** (админ).

## Правила

Рабочий день 09:00–18:00, шаг 30 минут, дата не в прошлом. Конфликт: для комнаты и даты нет активной брони,
пересекающейся с `[start, end)`; касание границ (15:00/15:00) — не конфликт. Отменённые брони слот не занимают.

## Ограничения MVP

- mock-авторизация (без JWT), пароль не хранится — равен логину;
- админ не создаёт брони (по матрице прав); Docker Compose и JWT нет;
- на карте 12 seed-аудиторий условно размещены на одном плане этажа (в seed они находятся в разных корпусах);
- удаление аудитории возможно только без активных броней (расширение к контракту);
- запуск встроенным сервером Flask — для демо, не для production.
