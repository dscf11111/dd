import io
import json
import tempfile
import unittest
from pathlib import Path

from server import create_app


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.app = create_app(database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def request(self, path, method="GET", payload=None, cookie=None, csrf_token=None):
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "HTTP_HOST": "testserver",
            "HTTP_ORIGIN": "http://testserver",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(body),
        }
        if cookie:
            environ["HTTP_COOKIE"] = cookie
        if csrf_token:
            environ["HTTP_X_CSRF_TOKEN"] = csrf_token

        response = {}

        def start_response(status, headers):
            response["status"] = int(status.split(" ", 1)[0])
            response["headers"] = dict(headers)

        response_body = b"".join(self.app(environ, start_response))
        if response_body and response["headers"].get("Content-Type", "").startswith("application/json"):
            response["body"] = json.loads(response_body.decode("utf-8"))
        else:
            response["body"] = response_body.decode("utf-8")
        return response

    def register(self, email="person@example.com"):
        response = self.request(
            "/api/register",
            method="POST",
            payload={"email": email, "password": "a-secure-password"},
        )
        cookie_pair = response["headers"]["Set-Cookie"].split(";", 1)[0]
        return response, cookie_pair, response["body"]["csrfToken"]

    def test_register_save_stats_and_delete_entry(self):
        registered, cookie, csrf_token = self.register()
        self.assertEqual(registered["status"], 201)

        original_text = "오늘 정말 화가 났어요. 그대로 보관해줘요! 😡"
        created = self.request(
            "/api/entries",
            method="POST",
            payload={"text": original_text, "mode": "blackhole", "angerLevel": 4},
            cookie=cookie,
            csrf_token=csrf_token,
        )
        self.assertEqual(created["status"], 201)
        self.assertEqual(created["body"]["charCount"], len(original_text))

        history = self.request("/api/entries", cookie=cookie)
        self.assertEqual(history["status"], 200)
        self.assertEqual(history["body"]["entries"][0]["text"], original_text)
        self.assertEqual(history["body"]["entries"][0]["angerLevel"], 4)

        stats = self.request("/api/stats")
        self.assertEqual(stats["body"]["charCount"], len(original_text))
        self.assertEqual(stats["body"]["shredCount"], 1)

        deleted = self.request(
            "/api/entries/" + str(created["body"]["id"]),
            method="DELETE",
            cookie=cookie,
            csrf_token=csrf_token,
        )
        self.assertEqual(deleted["status"], 200)
        self.assertEqual(self.request("/api/entries", cookie=cookie)["body"]["entries"], [])
        stats_after_delete = self.request("/api/stats")
        self.assertEqual(stats_after_delete["body"], stats["body"])

    def test_records_are_private_to_their_account(self):
        _, first_cookie, first_csrf = self.register("first@example.com")
        _, second_cookie, _ = self.register("second@example.com")
        self.request(
            "/api/entries",
            method="POST",
            payload={"text": "private note", "mode": "fire"},
            cookie=first_cookie,
            csrf_token=first_csrf,
        )
        second_history = self.request("/api/entries", cookie=second_cookie)
        self.assertEqual(second_history["status"], 200)
        self.assertEqual(second_history["body"]["entries"], [])

    def test_mutations_require_csrf_token_and_login(self):
        anonymous = self.request(
            "/api/entries",
            method="POST",
            payload={"text": "test", "mode": "fire"},
        )
        self.assertEqual(anonymous["status"], 401)

        _, cookie, _ = self.register()
        missing_csrf = self.request(
            "/api/entries",
            method="POST",
            payload={"text": "test", "mode": "fire"},
            cookie=cookie,
        )
        self.assertEqual(missing_csrf["status"], 403)

    def test_invalid_entries_are_rejected_without_counting(self):
        _, cookie, csrf_token = self.register()
        invalid = self.request(
            "/api/entries",
            method="POST",
            payload={"text": "text", "mode": "fire", "angerLevel": 8},
            cookie=cookie,
            csrf_token=csrf_token,
        )
        self.assertEqual(invalid["status"], 400)
        self.assertEqual(self.request("/api/stats")["body"]["charCount"], 0)

    def test_login_and_account_deletion_remove_records(self):
        _, cookie, csrf_token = self.register()
        created = self.request(
            "/api/entries",
            method="POST",
            payload={"text": "delete with account", "mode": "shredder"},
            cookie=cookie,
            csrf_token=csrf_token,
        )
        login = self.request(
            "/api/login",
            method="POST",
            payload={"email": "person@example.com", "password": "a-secure-password"},
        )
        self.assertEqual(login["status"], 200)
        login_cookie = login["headers"]["Set-Cookie"].split(";", 1)[0]
        account_deleted = self.request(
            "/api/account",
            method="DELETE",
            cookie=login_cookie,
            csrf_token=login["body"]["csrfToken"],
        )
        self.assertEqual(account_deleted["status"], 200)
        self.assertEqual(self.request("/api/me", cookie=login_cookie)["status"], 401)
        self.assertEqual(self.request("/api/entries", cookie=login_cookie)["status"], 401)
        self.assertEqual(self.request("/api/stats")["body"]["shredCount"], 1)

    def test_static_page_is_served_and_invalid_mode_is_rejected(self):
        page = self.request("/")
        self.assertEqual(page["status"], 200)
        self.assertIn("부숴버려", page["body"])

        _, cookie, csrf_token = self.register()
        invalid_mode = self.request(
            "/api/entries",
            method="POST",
            payload={"text": "text", "mode": ["fire"]},
            cookie=cookie,
            csrf_token=csrf_token,
        )
        self.assertEqual(invalid_mode["status"], 400)


if __name__ == "__main__":
    unittest.main()
