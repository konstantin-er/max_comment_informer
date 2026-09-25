import unittest
import io
import urllib.error
from unittest.mock import patch

from maxnotify.api import ApiError, MaxApi


class ApiTests(unittest.TestCase):
    def test_callback_answer_contains_notification(self):
        class RecordingApi(MaxApi):
            def request(self, method, path, params=None, body=None, timeout=20):
                return method, path, params, body

        result = RecordingApi("token").answer_callback("callback-1", "Комментарий удалён")
        self.assertEqual(result, ("POST", "/answers", {"callback_id": "callback-1"}, {"notification": "Комментарий удалён"}))

    def test_http_error_includes_api_message(self):
        error = urllib.error.HTTPError("https://platform-api2.max.ru/answers", 400, "Bad Request", {}, io.BytesIO(b'{"message":"invalid callback answer"}'))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(ApiError, "invalid callback answer"):
                MaxApi("token").answer_callback("callback-1", "ok")


if __name__ == "__main__":
    unittest.main()
