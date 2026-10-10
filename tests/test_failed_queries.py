from biletbot.storage import Storage


def test_failed_queries_preserve_text_without_adding_broadcast_recipient(tmp_path):
    store = Storage(str(tmp_path / "failed.sqlite3"))
    try:
        store.save_failed_query(123, "bot", "Из Казани за границу 29–30 октября", "Укажите направление")
        row = store.db.execute("SELECT * FROM failed_queries").fetchone()
        assert row["query"] == "Из Казани за границу 29–30 октября"
        assert row["user_id"] == 123 and row["source"] == "bot"
        assert row["error"] == "Укажите направление" and row["created_at"]
        assert store.broadcast_users() == []
    finally:
        store.db.close()
