import html
import logging
from urllib.parse import urlparse

from .api import ApiError


log = logging.getLogger(__name__)


def safe_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname in {"max.ru", "www.max.ru"} else None


def comment_from_update(update):
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}
    body = message.get("body") or {}
    chat_id = recipient.get("chat_id")
    post_id = recipient.get("post_id")
    comment_id = body.get("mid")
    author_id = sender.get("user_id")
    if not all((chat_id, post_id, comment_id, author_id)):
        return None
    return {"chat_id": int(chat_id), "post_id": post_id, "comment_id": comment_id,
            "author_id": int(author_id), "sender": sender, "text": body.get("text") or "(без текста)"}


def preview(value, limit):
    """Collapse whitespace, cut to `limit` characters and HTML-escape the result."""
    value = " ".join(str(value or "").split())
    if len(value) > limit:
        value = value[:limit - 1].rstrip() + "…"
    return html.escape(value)


def post_preview(post, limit=80):
    body = post.get("body") or {}
    text = body.get("text") if isinstance(body.get("text"), str) else ""
    if text.strip():
        return f"«{preview(text, limit)}»"
    return "пост с вложением" if body.get("attachments") else ""


def keyboard(notification_id, post_url, expanded=False, status="new"):
    buttons = []
    first_row = []
    if post_url:
        first_row.append({"type": "link", "text": "Перейти", "url": post_url})
    if expanded:
        if first_row:
            buttons.append(first_row)
        if status == "new":
            buttons.append([{"type": "callback", "text": "Удалить", "payload": f"delete:{notification_id}"}])
        buttons.append([{"type": "callback", "text": "Блокировать комментарии", "payload": f"ban:{notification_id}"}])
        buttons.append([{"type": "callback", "text": "Отмена", "payload": f"cancel:{notification_id}"}])
    else:
        first_row.append({"type": "callback", "text": "Действия", "payload": f"expand:{notification_id}"})
        buttons.append(first_row)
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}] if buttons else []


class Bot:
    def __init__(self, api, store, bot_username):
        self.api = api
        self.store = store
        self.bot_username = bot_username.lstrip("@")

    def handle(self, update):
        kind = update.get("update_type")
        if kind == "bot_started":
            user_id = (update.get("user") or {}).get("user_id")
            if user_id:
                self.store.start_user(user_id)
                self.api.send_message(user_id, {"text": self.welcome_text()})
        elif kind == "bot_stopped":
            user_id = (update.get("user") or {}).get("user_id")
            if user_id:
                self.store.stop_user(user_id)
        elif kind == "message_created":
            message = update.get("message") or {}
            recipient = message.get("recipient") or {}
            sender = message.get("sender") or {}
            if recipient.get("chat_type") == "dialog" and (message.get("body") or {}).get("text", "").strip().lower() in {"/start", "start"}:
                user_id = sender.get("user_id")
                if user_id and not self.store.is_started(user_id):
                    self.store.start_user(user_id)
                    self.api.send_message(user_id, {"text": self.welcome_text()})
        elif kind == "comment_created":
            self._comment(update)
        elif kind == "message_callback":
            self._callback(update)

    def welcome_text(self):
        return ("👋 Привет! Я сообщаю администраторам о новых комментариях к постам канала.\n\n"
                "Как подключить:\n"
                f"1. Добавьте меня в канал: https://max.ru/{self.bot_username}\n"
                "2. Назначьте администратором с правами читать сообщения и удалять комментарии.\n"
                "3. Включите комментарии в настройках канала.\n"
                "4. Каждый администратор, которому нужны уведомления, должен нажать «Начать» в этом боте.\n\n"
                "В каждом уведомлении видно канал, пост, автора и текст комментария. "
                "Кнопки позволяют перейти к посту, удалить комментарий или включить автоудаление новых комментариев автора.")

    def _comment(self, update):
        comment = comment_from_update(update)
        if not comment:
            return
        chat_id = comment["chat_id"]
        admins = self.api.get_admins(chat_id)
        if comment["author_id"] in {int(a["user_id"]) for a in admins if a.get("user_id")}:
            return
        if self.store.is_banned(chat_id, comment["author_id"]):
            self.api.delete_comment(comment["post_id"], comment["comment_id"])
            return
        recipients = sorted({int(a["user_id"]) for a in admins if a.get("user_id") and not a.get("is_bot") and self.store.is_started(int(a["user_id"]))})
        if not recipients:
            return
        chat = self.api.get_chat(chat_id)
        post = self.api.get_message(comment["post_id"])
        post_url = safe_url(post.get("url")) or safe_url(chat.get("link"))
        name = comment["sender"].get("name") or comment["sender"].get("first_name") or str(comment["author_id"])
        username = comment["sender"].get("username")
        author = html.escape(name)
        if username and username.replace("_", "").isalnum():
            author = f'<a href="https://max.ru/{html.escape(username, quote=True)}">{author}</a>'
        title = html.escape(chat.get("title") or str(chat_id))
        if safe_url(chat.get("link")):
            title = f'<a href="{html.escape(chat["link"], quote=True)}">{title}</a>'
        snippet = post_preview(post)
        post_label = snippet or "пост"
        if post_url:
            post_label = f'<a href="{html.escape(post_url, quote=True)}">{post_label}</a>'
        text = (f"💬 <b>Новый комментарий</b>\n\n"
                f"📢 Канал: <b>{title}</b>\n"
                f"📝 Пост: {post_label}\n"
                f"👤 Автор: {author}\n\n"
                f"{html.escape(comment['text'][:3000])}")
        for user_id in recipients:
            note = self.store.add_notification(chat_id, user_id, comment["author_id"], comment["post_id"], comment["comment_id"], text, post_url)
            if note["message_id"]:
                continue
            result = self.api.send_message(user_id, {"text": text, "format": "html", "attachments": keyboard(note["id"], post_url)})
            message_id = ((result.get("message") or {}).get("body") or {}).get("mid")
            if not message_id:
                raise ValueError("MAX did not return sent message ID")
            self.store.mark_sent(note["id"], message_id)

    def _callback(self, update):
        callback = update.get("callback") or {}
        callback_id = callback.get("callback_id")
        payload = callback.get("payload") or ""
        user_id = (callback.get("user") or {}).get("user_id")
        message_id = (((update.get("message") or {}).get("body") or {}).get("mid"))
        try:
            action, raw_id = payload.split(":", 1)
            notification_id = int(raw_id)
        except (ValueError, TypeError):
            return
        if action not in {"expand", "cancel", "delete", "ban"} or not user_id or not callback_id:
            return
        note = self.store.get_notification(notification_id)
        if not note or note["user_id"] != int(user_id) or note["message_id"] != message_id:
            self._answer_safely(callback_id, "Действие недоступно")
            return
        admins = self.api.get_admins(note["chat_id"])
        if int(user_id) not in {int(a["user_id"]) for a in admins if a.get("user_id") and not a.get("is_bot")}:
            self._answer_safely(callback_id, "Нет прав администратора")
            return
        if note["status"] == "banned":
            self._answer_safely(callback_id, "Автоудаление уже включено")
            return
        if action in {"expand", "cancel"}:
            suffix = "\n\n🗑 Комментарий удалён." if note["status"] == "deleted" else ""
            body = {"text": note["text"] + suffix, "format": "html", "attachments": keyboard(notification_id, note["post_url"], expanded=action == "expand", status=note["status"])}
            self.api.edit_message(note["message_id"], body)
            self._answer_safely(callback_id, "Действия открыты" if action == "expand" else "Действия свернуты")
        else:
            if action == "delete" and note["status"] == "deleted":
                self._answer_safely(callback_id, "Комментарий уже удалён")
                return
            if note["status"] == "new":
                try:
                    self.api.delete_comment(note["post_id"], note["comment_id"])
                except ApiError:
                    log.exception("Could not delete comment %s", note["comment_id"])
                    self._answer_safely(callback_id, "Не удалось удалить комментарий")
                    return
            if action == "ban":
                self.store.ban(note["chat_id"], note["author_id"])
            status = "banned" if action == "ban" else "deleted"
            self.store.set_comment_status(note["comment_id"], status)
            suffix = "\n\n⛔ Автор в списке автоудаления." if action == "ban" else "\n\n🗑 Комментарий удалён."
            try:
                self.api.edit_message(note["message_id"], {"text": note["text"] + suffix, "format": "html", "attachments": keyboard(notification_id, note["post_url"])})
            except ApiError:
                log.exception("Comment deleted but notification could not be updated")
            self._answer_safely(callback_id, "Включено автоудаление комментариев автора" if action == "ban" else "Комментарий удалён")

    def _answer_safely(self, callback_id, message):
        try:
            self.api.answer_callback(callback_id, message)
        except ApiError:
            log.warning("Could not answer callback; continuing polling", exc_info=True)
