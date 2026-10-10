import sqlite3
from pathlib import Path

from .models import Search


class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                params TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY, search_id INTEGER NOT NULL REFERENCES searches(id),
                user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, threshold INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, last_notified REAL,
                checked_at TEXT, last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, search_id)
            );
            CREATE TABLE IF NOT EXISTS pending (
                user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                search_id INTEGER NOT NULL REFERENCES searches(id),
                PRIMARY KEY(user_id, chat_id)
            );
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(id),
                price REAL, checked_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ticket_cards (
                id INTEGER PRIMARY KEY, search_id INTEGER NOT NULL REFERENCES searches(id),
                ticket TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_edits (
                user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
                search_id INTEGER NOT NULL REFERENCES searches(id),
                PRIMARY KEY(user_id, chat_id)
            );
        """)

    def save_card(self, sid, ticket):
        import json
        with self.db:
            return self.db.execute("INSERT INTO ticket_cards(search_id,ticket) VALUES (?,?)",
                                   (sid, json.dumps(ticket))).lastrowid

    def set_edit(self, sid, uid, cid):
        self.get_search(sid, uid, cid)
        with self.db:
            self.clear_pending(uid, cid)
            self.db.execute("INSERT OR REPLACE INTO pending_edits VALUES (?,?,?)", (uid, cid, sid))

    def pending_edit(self, uid, cid):
        row = self.db.execute("SELECT search_id FROM pending_edits WHERE user_id=? AND chat_id=?", (uid, cid)).fetchone()
        return row[0] if row else None

    def clear_edit(self, uid, cid):
        with self.db:
            self.db.execute("DELETE FROM pending_edits WHERE user_id=? AND chat_id=?", (uid, cid))

    def get_card(self, card_id, uid, cid):
        import json
        row = self.db.execute("SELECT search_id,ticket FROM ticket_cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise ValueError("Билет не найден")
        return self.get_search(row[0], uid, cid), json.loads(row[1])

    def save_search(self, user_id, chat_id, search: Search):
        with self.db:
            return self.db.execute("INSERT INTO searches(user_id,chat_id,params) VALUES (?,?,?)",
                                   (user_id, chat_id, search.model_dump_json())).lastrowid

    def get_search(self, sid, user_id, chat_id):
        row = self.db.execute("SELECT * FROM searches WHERE id=? AND user_id=? AND chat_id=?",
                              (sid, user_id, chat_id)).fetchone()
        if not row:
            raise ValueError("Поиск не найден. Выполните новый поиск.")
        return Search.model_validate_json(row["params"])

    def subscribe(self, sid, user_id, chat_id, price):
        self.get_search(sid, user_id, chat_id)
        if not 0 < price < 1000000:
            raise ValueError("Введите целую цену от 1 до 999999 ₽")
        with self.db:
            self.db.execute("""INSERT INTO alerts(search_id,user_id,chat_id,threshold) VALUES (?,?,?,?)
                ON CONFLICT(user_id,search_id) DO UPDATE SET threshold=excluded.threshold,
                active=1,last_notified=NULL,last_error=NULL""", (sid, user_id, chat_id, price))
            self.clear_pending(user_id, chat_id)

    def set_pending(self, sid, user_id, chat_id):
        self.get_search(sid, user_id, chat_id)
        with self.db:
            self.clear_edit(user_id, chat_id)
            self.db.execute("INSERT OR REPLACE INTO pending VALUES (?,?,?)", (user_id, chat_id, sid))

    def pending(self, user_id, chat_id):
        row = self.db.execute("SELECT search_id FROM pending WHERE user_id=? AND chat_id=?",
                              (user_id, chat_id)).fetchone()
        return row[0] if row else None

    def clear_pending(self, user_id, chat_id):
        self.db.execute("DELETE FROM pending WHERE user_id=? AND chat_id=?", (user_id, chat_id))

    def alerts(self, user_id=None):
        sql = "SELECT a.*, s.params FROM alerts a JOIN searches s ON s.id=a.search_id WHERE active=1"
        return self.db.execute(sql + (" AND a.user_id=?" if user_id is not None else ""),
                               (user_id,) if user_id is not None else ()).fetchall()

    def stop(self, aid, user_id):
        with self.db:
            return self.db.execute("UPDATE alerts SET active=0 WHERE id=? AND user_id=? AND active=1",
                                   (aid, user_id)).rowcount > 0

    def record_check(self, aid, price):
        with self.db:
            self.db.execute("INSERT INTO price_history(alert_id,price) VALUES (?,?)", (aid, price))
            self.db.execute("UPDATE alerts SET checked_at=CURRENT_TIMESTAMP,last_error=NULL WHERE id=?", (aid,))

    def record_notification(self, aid, price):
        with self.db:
            self.db.execute("UPDATE alerts SET last_notified=? WHERE id=? AND active=1", (price, aid))

    def record_error(self, aid, error):
        with self.db:
            self.db.execute("UPDATE alerts SET last_error=? WHERE id=?", (error, aid))

    def history(self, user_id):
        return self.db.execute("SELECT params FROM searches WHERE user_id=? ORDER BY id DESC LIMIT 10",
                               (user_id,)).fetchall()

    def place_suggestions(self, user_id, field):
        if field not in {"origin", "destination"}:
            raise ValueError("Unknown place field")
        code, name = f"$.{field}", f"$.{field}_name"
        recent = self.db.execute("""SELECT json_extract(params, ?) AS code,
            json_extract(params, ?) AS name FROM searches WHERE user_id=?
            GROUP BY code ORDER BY MAX(id) DESC LIMIT 3""", (code, name, user_id)).fetchall()
        popular = self.db.execute("""SELECT json_extract(params, ?) AS code,
            json_extract(params, ?) AS name FROM searches GROUP BY code
            ORDER BY COUNT(DISTINCT user_id) DESC, MAX(id) DESC LIMIT 5""", (code, name)).fetchall()
        return {"recent": [dict(row) for row in recent], "popular": [dict(row) for row in popular]}
