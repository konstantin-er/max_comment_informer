import json
import urllib.error
import urllib.parse
import urllib.request


class ApiError(RuntimeError):
    pass


class MaxApi:
    BASE = "https://platform-api2.max.ru"

    def __init__(self, token):
        self.token = token

    def request(self, method, path, params=None, body=None, timeout=20):
        query = urllib.parse.urlencode(params or {})
        url = self.BASE + path + ("?" + query if query else "")
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Authorization": self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raw = exc.read(512).decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("message", raw)
            except ValueError:
                detail = raw
            raise ApiError(f"MAX API {method} {path}: HTTP {exc.code}: {detail or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise ApiError(f"MAX API {method} {path}: {exc}") from exc
        if isinstance(result, dict) and result.get("success") is False:
            raise ApiError(f"MAX API {method} {path}: {result.get('message', 'success=false')}")
        return result

    def get_updates(self, marker):
        params = {"timeout": 30, "limit": 100, "types": "bot_started,bot_stopped,comment_created,message_callback,message_created"}
        if marker is not None:
            params["marker"] = marker
        return self.request("GET", "/updates", params, timeout=40)

    def get_admins(self, chat_id):
        return self.request("GET", f"/chats/{chat_id}/members/admins")["members"]

    def get_chat(self, chat_id):
        return self.request("GET", f"/chats/{chat_id}")

    def get_message(self, message_id):
        return self.request("GET", f"/messages/{urllib.parse.quote(message_id, safe='')}")

    def send_message(self, user_id, body):
        return self.request("POST", "/messages", {"user_id": user_id}, body)

    def edit_message(self, message_id, body):
        return self.request("PUT", "/messages", {"message_id": message_id}, body)

    def answer_callback(self, callback_id, text=None):
        return self.request("POST", "/answers", {"callback_id": callback_id}, {"notification": text or "Готово"})

    def delete_comment(self, post_id, comment_id):
        return self.request("DELETE", f"/messages/{urllib.parse.quote(post_id, safe='')}/comments", {"comment_id": comment_id})
