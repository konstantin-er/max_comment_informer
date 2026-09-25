import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS started (user_id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS bans (chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id));
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL, post_id TEXT NOT NULL, comment_id TEXT NOT NULL,
                text TEXT NOT NULL, post_url TEXT, message_id TEXT, status TEXT NOT NULL DEFAULT 'new',
                UNIQUE (user_id, comment_id));
        """)

    def close(self):
        self.db.close()

    def get_marker(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='marker'").fetchone()
        return int(row[0]) if row else None

    def set_marker(self, marker):
        if marker is None:
            return
        with self.db:
            self.db.execute("INSERT INTO settings VALUES ('marker', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(marker),))

    def start_user(self, user_id):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO started VALUES (?)", (user_id,))

    def stop_user(self, user_id):
        with self.db:
            self.db.execute("DELETE FROM started WHERE user_id=?", (user_id,))

    def is_started(self, user_id):
        return self.db.execute("SELECT 1 FROM started WHERE user_id=?", (user_id,)).fetchone() is not None

    def ban(self, chat_id, user_id):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO bans VALUES (?, ?)", (chat_id, user_id))

    def is_banned(self, chat_id, user_id):
        return self.db.execute("SELECT 1 FROM bans WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone() is not None

    def add_notification(self, chat_id, user_id, author_id, post_id, comment_id, text, post_url):
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO notifications
                (chat_id,user_id,author_id,post_id,comment_id,text,post_url)
                VALUES (?,?,?,?,?,?,?)""", (chat_id,user_id,author_id,post_id,comment_id,text,post_url))
        row = self.db.execute("SELECT * FROM notifications WHERE user_id=? AND comment_id=?", (user_id,comment_id)).fetchone()
        return dict(row)

    def get_notification(self, notification_id):
        row = self.db.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone()
        return dict(row) if row else None

    def mark_sent(self, notification_id, message_id):
        with self.db:
            self.db.execute("UPDATE notifications SET message_id=? WHERE id=?", (message_id, notification_id))

    def set_status(self, notification_id, status):
        with self.db:
            self.db.execute("UPDATE notifications SET status=? WHERE id=?", (status, notification_id))

    def set_comment_status(self, comment_id, status):
        with self.db:
            self.db.execute("UPDATE notifications SET status=? WHERE comment_id=?", (status, comment_id))
