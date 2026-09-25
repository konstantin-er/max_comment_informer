import logging
import os
import time
from pathlib import Path

from .api import MaxApi
from .bot import Bot
from .store import Store


log = logging.getLogger(__name__)


def process_batch(bot, store, batch):
    for update in batch.get("updates", []):
        bot.handle(update)
    store.set_marker(batch.get("marker"))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("BOT_TOKEN", "").strip()
    username = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
    if not token or not username:
        raise SystemExit("Set BOT_TOKEN and BOT_USERNAME in .env")
    store = Store(Path(os.environ.get("DATABASE_PATH", "/data/state.db")))
    api = MaxApi(token)
    bot = Bot(api, store, username)
    log.info("Starting MAX comment polling")
    try:
        while True:
            try:
                batch = api.get_updates(store.get_marker())
                process_batch(bot, store, batch)
            except Exception:
                log.exception("Polling or update processing failed; retrying in 5 seconds")
                time.sleep(5)
    finally:
        store.close()


if __name__ == "__main__":
    main()
