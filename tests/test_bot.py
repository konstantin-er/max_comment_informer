import tempfile
import unittest
from pathlib import Path

from maxnotify.api import ApiError
from maxnotify.bot import Bot, comment_from_update
from maxnotify.store import Store


COMMENT = {
    "update_type": "comment_created",
    "message": {
        "sender": {"user_id": 11, "name": "Автор", "username": "author"},
        "recipient": {"chat_id": -100, "post_id": "mid.post"},
        "body": {"mid": "mid.comment", "text": "Привет"},
    },
}


class FakeApi:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self.answered = []
        self.admins = [{"user_id": 7, "is_admin": True}, {"user_id": 8, "is_admin": True}]

    def get_admins(self, chat_id):
        return self.admins

    def get_chat(self, chat_id):
        return {"title": "Канал", "link": "https://max.ru/channel"}

    def get_message(self, post_id):
        return {"url": "https://max.ru/post", "body": {"text": "Текст   поста\nс <тегом>"}}

    def send_message(self, user_id, body):
        self.sent.append((user_id, body))
        return {"message": {"body": {"mid": f"mid.sent{len(self.sent)}"}}}

    def answer_callback(self, callback_id, text=None):
        self.answered.append((callback_id, text))

    def edit_message(self, message_id, body):
        self.edited.append((message_id, body))

    def delete_comment(self, post_id, comment_id):
        self.deleted.append((post_id, comment_id))


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.api = FakeApi()
        self.bot = Bot(self.api, self.store, "my_bot")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_comment_routes_only_to_started_admins(self):
        self.store.start_user(7)
        self.store.start_user(99)
        self.bot.handle(COMMENT)
        self.assertEqual([user for user, _ in self.api.sent], [7])
        body = self.api.sent[0][1]
        self.assertEqual(body["format"], "html")
        self.assertEqual(body["text"], (
            "💬 <b>Новый комментарий</b>\n\n"
            '📢 Канал: <b><a href="https://max.ru/channel">Канал</a></b>\n'
            '📝 Пост: <a href="https://max.ru/post">«Текст поста с &lt;тегом&gt;»</a>\n'
            '👤 Автор: <a href="https://max.ru/author">Автор</a>\n\n'
            "Привет"))
        self.assertEqual(body["attachments"][0]["payload"]["buttons"][0][0]["url"], "https://max.ru/post")

    def test_long_post_is_truncated_and_missing_text_has_fallback(self):
        self.store.start_user(7)
        self.api.get_message = lambda post_id: {"url": "https://max.ru/post", "body": {"text": "я" * 200}}
        self.bot.handle(COMMENT)
        self.assertIn("я" * 79 + "…»", self.api.sent[0][1]["text"])
        self.api.get_message = lambda post_id: {"url": "https://max.ru/post", "body": {"attachments": [{}]}}
        comment = {**COMMENT, "message": {**COMMENT["message"], "body": {"mid": "mid.c2", "text": "Ещё"}}}
        self.bot.handle(comment)
        self.assertIn("пост с вложением</a>", self.api.sent[1][1]["text"])

    def test_banned_author_is_deleted_without_notification(self):
        self.store.start_user(7)
        self.store.ban(-100, 11)
        self.bot.handle(COMMENT)
        self.assertEqual(self.api.deleted, [("mid.post", "mid.comment")])
        self.assertEqual(self.api.sent, [])

    def test_admin_comment_is_neither_notified_nor_auto_deleted(self):
        self.store.start_user(7)
        self.store.start_user(8)
        self.store.ban(-100, 7)
        event = {**COMMENT, "message": {**COMMENT["message"], "sender": {"user_id": 7, "name": "Модератор"}}}
        self.bot.handle(event)
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.api.deleted, [])

    def test_callback_requires_recipient_and_current_admin(self):
        self.store.start_user(7)
        self.bot.handle(COMMENT)
        notification = self.store.get_notification(1)
        event = {"update_type": "message_callback", "callback": {"callback_id": "cb", "payload": "delete:1", "user": {"user_id": 8}}, "message": {"body": {"mid": notification["message_id"]}}}
        self.bot.handle(event)
        self.assertEqual(self.api.deleted, [])
        event["callback"]["user"]["user_id"] = 7
        self.api.admins = [{"user_id": 8, "is_admin": True}]
        self.bot.handle(event)
        self.assertEqual(self.api.deleted, [])

    def test_delete_and_ban_callbacks(self):
        self.store.start_user(7)
        self.bot.handle(COMMENT)
        event = {"update_type": "message_callback", "callback": {"callback_id": "cb", "payload": "ban:1", "user": {"user_id": 7}}, "message": {"body": {"mid": "mid.sent1"}}}
        self.bot.handle(event)
        self.assertTrue(self.store.is_banned(-100, 11))
        self.assertEqual(self.api.deleted, [("mid.post", "mid.comment")])
        self.assertEqual(self.store.get_notification(1)["status"], "banned")
        buttons = self.api.edited[-1][1]["attachments"][0]["payload"]["buttons"][0]
        self.assertEqual([button["text"] for button in buttons], ["Перейти", "Действия"])
        self.assertIn("автоудаление", self.api.answered[-1][1])

    def test_callback_answer_failure_does_not_replay_delete(self):
        self.store.start_user(7)
        self.bot.handle(COMMENT)

        def fail_answer(callback_id, text=None):
            raise ApiError("HTTP 400")

        self.api.answer_callback = fail_answer
        event = {"update_type": "message_callback", "callback": {"callback_id": "cb", "payload": "delete:1", "user": {"user_id": 7}}, "message": {"body": {"mid": "mid.sent1"}}}
        with self.assertLogs("maxnotify.bot", level="WARNING"):
            self.bot.handle(event)
            self.bot.handle(event)
        self.assertEqual(self.api.deleted, [("mid.post", "mid.comment")])

    def test_cancel_restores_two_main_buttons(self):
        self.store.start_user(7)
        self.bot.handle(COMMENT)
        event = {"update_type": "message_callback", "callback": {"callback_id": "cb", "payload": "cancel:1", "user": {"user_id": 7}}, "message": {"body": {"mid": "mid.sent1"}}}
        self.bot.handle(event)
        buttons = self.api.edited[-1][1]["attachments"][0]["payload"]["buttons"][0]
        self.assertEqual([button["text"] for button in buttons], ["Перейти", "Действия"])

    def test_ban_can_follow_successful_delete_without_second_delete(self):
        self.store.start_user(7)
        self.bot.handle(COMMENT)
        event = {"update_type": "message_callback", "callback": {"callback_id": "cb", "payload": "delete:1", "user": {"user_id": 7}}, "message": {"body": {"mid": "mid.sent1"}}}
        self.bot.handle(event)
        event["callback"]["payload"] = "expand:1"
        self.bot.handle(event)
        expanded = self.api.edited[-1][1]["attachments"][0]["payload"]["buttons"]
        self.assertIn("Блокировать комментарии", [button["text"] for row in expanded for button in row])
        event["callback"]["payload"] = "ban:1"
        self.bot.handle(event)
        self.assertEqual(self.api.deleted, [("mid.post", "mid.comment")])
        self.assertTrue(self.store.is_banned(-100, 11))
        self.assertEqual(self.store.get_notification(1)["status"], "banned")

    def test_start_sends_simple_onboarding(self):
        self.bot.handle({"update_type": "bot_started", "user": {"user_id": 7}})
        self.assertTrue(self.store.is_started(7))
        self.assertIn("https://max.ru/my_bot", self.api.sent[0][1]["text"])

    def test_comment_requires_identifiers(self):
        self.assertIsNone(comment_from_update({"update_type": "comment_created", "message": {"body": {"text": "x"}}}))


if __name__ == "__main__":
    unittest.main()
