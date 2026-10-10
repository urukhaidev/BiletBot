import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from telegram import Bot

from biletbot.api import API
from biletbot.config import Config
from biletbot.messages import baggage_text, duration_text, human_date, select_tickets, transfer_text, price_keyboard
from biletbot.models import Search
from biletbot.rich_messages import send_search_results, ticket_url
from biletbot.storage import Storage
from .auth import authenticate

STATIC = Path(__file__).parent / "static"


class SearchForm(BaseModel):
    origin: str = Field(min_length=2, max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    date_mode: Literal["months", "dates", "range"] = "months"
    months: list[date] = Field(default_factory=list, max_length=6)
    departure: date | None = None
    returning: date | None = None
    range_end: date | None = None
    trip_type: Literal["both", "OW", "RT"] = "both"
    direct: bool = False
    max_changes: int | None = Field(default=None, ge=0, le=10)
    baggage: bool = False
    duration_min: int = Field(default=7, ge=1, le=365)
    duration_max: int = Field(default=10, ge=1, le=365)

    @model_validator(mode="after")
    def valid(self):
        if self.duration_min > self.duration_max:
            raise ValueError("Минимальная длительность больше максимальной")
        if self.date_mode == "months" and (not self.months or any(m.day != 1 for m in self.months)):
            raise ValueError("Выберите хотя бы один месяц")
        if self.date_mode != "months" and not self.departure:
            raise ValueError("Укажите дату вылета")
        if self.date_mode == "range" and (not self.range_end or self.range_end < self.departure):
            raise ValueError("Укажите корректный диапазон вылета")
        if self.returning and (self.date_mode != "dates" or self.trip_type != "RT" or self.returning <= self.departure):
            raise ValueError("Возврат должен быть после вылета в режиме туда-обратно")
        return self


def build_searches(form, origin, destination, today):
    periods = sorted(set(form.months)) if form.date_mode == "months" else [form.departure]
    searches = []
    for period in periods:
        for trip_type in (["OW", "RT"] if form.trip_type == "both" else [form.trip_type]):
            dates = {"month": period} if form.date_mode == "months" else (
                {"depart_date_min": period, "depart_date_max": form.range_end} if form.date_mode == "range"
                else {"date_from": period, "date_to": form.returning if trip_type == "RT" else None})
            s = Search(origin=origin[0], origin_name=origin[1], destination=destination[0], destination_name=destination[1],
                       trip_type=trip_type, direct=form.direct, baggage=form.baggage, max_changes=form.max_changes,
                       duration_min=form.duration_min, duration_max=form.duration_max, **dates)
            if s.last_departure() < today:
                raise ValueError("Выберите будущие даты")
            when = human_date(period.isoformat()) if form.date_mode != "months" else "месяц " + period.isoformat()[:7]
            s.query = f"{s.origin_name} {s.destination_name} {when} " + ("в одну сторону" if trip_type == "OW" else
                (f"туда-обратно возврат {human_date(form.returning.isoformat())}" if form.returning else f"на {form.duration_min}–{form.duration_max} дней"))
            if form.date_mode == "range":
                s.query = s.query.replace(when, f"вылет с {when} по {human_date(form.range_end.isoformat())}")
            if form.direct:
                s.query += " прямой"
            elif form.max_changes is not None:
                s.query += f" не больше {form.max_changes} пересадок"
            if form.baggage:
                s.query += " с багажом"
            searches.append(s)
    return searches


@asynccontextmanager
async def lifespan(app):
    app.state.config = Config.load()
    app.state.api = API(app.state.config)
    app.state.storage = Storage(app.state.config.database)
    app.state.storage.db.execute("""CREATE TABLE IF NOT EXISTS mini_history (
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, form TEXT NOT NULL,
        result TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    app.state.storage.db.commit()
    app.state.jobs = {}
    app.state.tasks = set()
    app.state.semaphore = asyncio.Semaphore(3)
    from telegram.request import HTTPXRequest
    bot = Bot(app.state.config.telegram_token, request=HTTPXRequest(proxy=app.state.config.telegram_proxy or None))
    await bot.initialize()
    app.state.bot = bot
    app.state.bot_username = (await bot.get_me()).username
    yield
    for task in app.state.tasks:
        task.cancel()
    await asyncio.gather(*app.state.tasks, return_exceptions=True)
    await bot.shutdown()
    await app.state.api.http.aclose()
    if app.state.api.telegram_http is not app.state.api.http:
        await app.state.api.telegram_http.aclose()
    app.state.storage.db.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def user(authorization: str = Header(default="")):
    try:
        return authenticate(authorization.removeprefix("tma "), app.state.config.telegram_token)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Откройте мини-апп из Telegram или перезапустите его") from None


@app.get("/mini-app")
@app.get("/mini-app/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/mini-app/api/config")
async def config():
    return {"bot_username": app.state.bot_username, "today": app.state.api.today().isoformat()}


@app.get("/mini-app/api/places")
async def places(term: str, me=Depends(user)):
    if not 2 <= len(term) <= 100:
        return []
    response = await app.state.api.http.get("https://autocomplete.travelpayouts.com/places2",
        params={"locale": "ru", "types[]": "city", "term": term})
    if response.is_error:
        raise HTTPException(502, "Не удалось загрузить города")
    return [{"code": p["code"], "name": p["name"], "country": p.get("country_name", "")} for p in response.json()[:6]]


@app.get("/mini-app/api/place-suggestions")
async def place_suggestions(field: Literal["origin", "destination"], me=Depends(user)):
    suggestions = app.state.storage.place_suggestions(me["id"], field)
    defaults = {
        "origin": [("MOW", "Москва"), ("LED", "Санкт-Петербург"), ("AER", "Сочи"),
                   ("SVX", "Екатеринбург"), ("KZN", "Казань")],
        "destination": [("AER", "Сочи"), ("IST", "Стамбул"), ("DXB", "Дубай"),
                        ("HKT", "Пхукет"), ("BKK", "Бангкок")],
    }
    codes = {p["code"] for p in suggestions["popular"]}
    for code, name in defaults[field]:
        if len(suggestions["popular"]) >= 5:
            break
        if code not in codes:
            suggestions["popular"].append({"code": code, "name": name})
            codes.add(code)
    return suggestions


async def perform_search(job, form, uid, parsed=None):
    api, store = app.state.api, app.state.storage
    try:
        async with app.state.semaphore:
            if parsed is not None:
                searches = parsed.variants()
            else:
                origin, destination = await asyncio.gather(api.resolve(form.origin), api.resolve(form.destination))
                searches = build_searches(form, origin, destination, api.today())
            results, groups = [], []
            for search in searches:
                sid = store.save_search(uid, uid, search)
                flights = await api.search_flights(search, all_pages=False)
                results.append((search, flights, sid))
                groups.append({"search_id": sid, "trip_type": search.trip_type, "query": search.query,
                    "origin_name": search.origin_name, "destination_name": search.destination_name,
                    "month": search.month.isoformat() if search.month else None,
                    "tickets": [{"departure": human_date(t["departure_at"]),
                                 "returning": human_date(t["return_at"]) if t.get("return_at") else None,
                                 "price": int(float(t["value"]) + .5), "baggage": baggage_text(t.get("baggage_code")),
                                  "duration": duration_text(t), "transfers": transfer_text(t),
                                  "direct": int(t["number_of_changes"]) == 0,
                                 "url": ticket_url(search, t, app.state.config.marker)} for t in select_tickets(search, flights)]})
            delivered = True
            try:
                # One message per selected month, each with its OW and RT groups.
                for i in range(0, len(results), 2 if form.trip_type == "both" else 1):
                    await send_search_results(api, uid, results[i:i + (2 if form.trip_type == "both" else 1)])
            except Exception:
                delivered = False
                logging.warning("Mini-app Telegram delivery failed")
            job.update(status="done", groups=groups, delivered=delivered)
            import json
            with store.db:
                store.db.execute("INSERT INTO mini_history(id,user_id,form,result) VALUES (?,?,?,?)",
                                 (uuid.uuid4().hex, uid, form.model_dump_json(), json.dumps(groups, ensure_ascii=False)))
    except ValueError as exc:
        job.update(status="error", error=str(exc)[:500])
    except Exception as exc:
        logging.warning("Mini-app search failed: %s", type(exc).__name__)
        job.update(status="error", error="Сервис поиска временно недоступен. Попробуйте ещё раз.")


@app.post("/mini-app/api/search")
async def search(form: SearchForm, me=Depends(user)):
    uid = me["id"]
    jobs = app.state.jobs
    for key in list(jobs):
        if jobs[key]["created"] < time.time() - 3600 and jobs[key]["status"] != "running":
            del jobs[key]
    if any(j["user_id"] == uid and j["status"] == "running" for j in jobs.values()):
        raise HTTPException(409, "Ваш поиск уже выполняется")
    if sum(j["status"] == "running" for j in jobs.values()) >= 30:
        raise HTTPException(429, "Сервис занят. Попробуйте чуть позже")
    jid = uuid.uuid4().hex
    job = jobs[jid] = {"user_id": uid, "created": time.time(), "status": "running"}
    task = asyncio.create_task(perform_search(job, form, uid))
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return {"job_id": jid}


class AIQuery(BaseModel):
    query: str = Field(min_length=3, max_length=1000)


class AlertForm(BaseModel):
    search_id: int = Field(gt=0)
    price: int = Field(gt=0, lt=1000000)


@app.post("/mini-app/api/alerts")
async def create_alert(body: AlertForm, me=Depends(user)):
    try:
        app.state.storage.subscribe(body.search_id, me["id"], me["id"], body.price)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True}


async def perform_ai(job, query, uid):
    try:
        parsed = await app.state.api.parse(query)
        form = SearchForm(origin=parsed.origin_name, destination=parsed.destination_name,
            trip_type=parsed.trip_type if parsed.trip_type_explicit else "both",
            date_mode="months" if parsed.month else "dates" if parsed.date_from else "range",
            months=[parsed.month] if parsed.month else [], departure=parsed.date_from or parsed.depart_date_min,
            returning=parsed.date_to, range_end=parsed.depart_date_max,
            duration_min=parsed.duration_min, duration_max=parsed.duration_max,
            direct=parsed.direct, baggage=parsed.baggage, max_changes=parsed.max_changes)
        await perform_search(job, form, uid, parsed=parsed)
    except Exception:
        job.update(status="error", error="Не удалось разобрать запрос. Укажите откуда, куда и когда лететь.")


@app.post("/mini-app/api/ai-search")
async def ai_search(body: AIQuery, me=Depends(user)):
    uid = me["id"]
    if any(j["user_id"] == uid and j["status"] == "running" for j in app.state.jobs.values()):
        raise HTTPException(409, "Ваш поиск уже выполняется")
    if sum(j["status"] == "running" for j in app.state.jobs.values()) >= 30:
        raise HTTPException(429, "Сервис занят. Попробуйте позже")
    jid = uuid.uuid4().hex
    job = app.state.jobs[jid] = {"user_id": uid, "created": time.time(), "status": "running"}
    task = asyncio.create_task(perform_ai(job, body.query, uid))
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return {"job_id": jid}


@app.get("/mini-app/api/search/{jid}")
async def result(jid: str, me=Depends(user)):
    job = app.state.jobs.get(jid)
    if not job or job["user_id"] != me["id"]:
        raise HTTPException(404, "Поиск не найден")
    return {k: v for k, v in job.items() if k not in ("user_id", "created")}


@app.get("/mini-app/api/alerts")
async def alerts(me=Depends(user)):
    result = []
    for row in app.state.storage.alerts(me["id"]):
        s = Search.model_validate_json(row["params"])
        result.append({"id": row["id"], "query": s.query, "threshold": row["threshold"],
                       "checked_at": row["checked_at"], "route": f"{s.origin_name} — {s.destination_name}"})
    return result


@app.delete("/mini-app/api/alerts/{aid}")
async def stop_alert(aid: int, me=Depends(user)):
    if not app.state.storage.stop(aid, me["id"]):
        raise HTTPException(404, "Подписка не найдена")
    return {"ok": True}


@app.get("/mini-app/api/profile")
async def profile(me=Depends(user)):
    store = app.state.storage
    count = store.db.execute("SELECT COUNT(*) FROM searches WHERE user_id=?", (me["id"],)).fetchone()[0]
    return {"user": {k: me.get(k) for k in ("first_name", "last_name", "username")},
            "searches": count, "alerts": len(store.alerts(me["id"])),
            "history": [Search.model_validate_json(r["params"]).query for r in store.history(me["id"])]}


@app.get("/mini-app/api/history")
async def history(me=Depends(user)):
    import json
    store = app.state.storage
    rows = store.db.execute("SELECT * FROM mini_history WHERE user_id=? ORDER BY created_at DESC LIMIT 30", (me["id"],)).fetchall()
    entries = [{"id": r["id"], "form": json.loads(r["form"]), "groups": json.loads(r["result"]),
                "created_at": r["created_at"], "source": "mini-app"} for r in rows]
    included = {g["search_id"] for entry in entries for g in entry["groups"] if "search_id" in g}
    bot_rows = store.db.execute("SELECT * FROM searches WHERE user_id=? ORDER BY id DESC LIMIT 100", (me["id"],)).fetchall()
    seen = set()
    for row in bot_rows:
        if row["id"] in included:
            continue
        s = Search.model_validate_json(row["params"])
        key = (s.query, row["created_at"][:16])
        if key in seen:
            continue
        seen.add(key)
        form = {"origin": s.origin_name, "destination": s.destination_name,
                "trip_type": s.trip_type, "direct": s.direct, "baggage": s.baggage, "max_changes": s.max_changes,
                "duration_min": s.duration_min, "duration_max": s.duration_max,
                "date_mode": "months" if s.month else "dates" if s.date_from else "range",
                "months": [s.month.isoformat()] if s.month else [],
                "departure": (s.date_from or s.depart_date_min).isoformat() if (s.date_from or s.depart_date_min) else None,
                "returning": s.date_to.isoformat() if s.date_to else None,
                "range_end": s.depart_date_max.isoformat() if s.depart_date_max else None}
        entries.append({"id": f"bot-{row['id']}", "form": form, "groups": [], "query": s.query,
                        "created_at": row["created_at"], "source": "bot"})
    return sorted(entries, key=lambda e: e["created_at"], reverse=True)[:50]


app.mount("/mini-app/static", StaticFiles(directory=STATIC), name="static")


@app.post("/mini-app/api/track/{sid}")
async def track(sid: int, me=Depends(user)):
    store = app.state.storage
    try:
        search = store.get_search(sid, me["id"], me["id"])
    except ValueError:
        raise HTTPException(404, "Поиск не найден") from None
    price = None
    import json
    rows = store.db.execute("SELECT result FROM mini_history WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (me["id"],)).fetchall()
    for row in rows:
        group = next((g for g in json.loads(row[0]) if g["search_id"] == sid), None)
        if group and group["tickets"]:
            price = min(t["price"] for t in group["tickets"])
            break
    try:
        if price is not None:
            await app.state.bot.send_message(me["id"], f"Отслеживание: {search.query}\n\nВыберите цену, ниже которой прислать уведомление:", reply_markup=price_keyboard(sid, price))
        else:
            store.set_pending(sid, me["id"], me["id"])
            await app.state.bot.send_message(me["id"], f"Отслеживание: {search.query}\n\nВведите желаемую цену в рублях. Отмена: /cancel")
    except Exception:
        raise HTTPException(502, "Не удалось отправить сообщение. Откройте бота, нажмите /start и попробуйте снова.") from None
    return {"ok": True}


@app.post("/mini-app/api/help")
async def help_message(me=Depends(user)):
    from biletbot.__main__ import HELP
    try:
        await app.state.bot.send_message(me["id"], HELP)
    except Exception:
        raise HTTPException(502, "Откройте бота и нажмите /start для получения инструкции") from None
    return {"ok": True}
