"""Small standard-library WSGI server for the anger release site."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import unquote, urlsplit
from wsgiref.simple_server import make_server


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "public"
DEFAULT_DB_PATH = BASE_DIR / "data" / "anger.sqlite3"
MAX_BODY_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 5000
PASSWORD_ITERATIONS = 310_000
SESSION_DAYS = 30
VALID_MODES = {"shredder", "blackhole", "fire"}
COOKIE_NAME = "anger_session"
KST = timezone(timedelta(hours=9), name="KST")


def get_db_path(db_path: str | Path | None = None) -> Path:
    configured_path = db_path or os.environ.get("ANGER_APP_DB") or DEFAULT_DB_PATH
    return Path(configured_path).expanduser().resolve()


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database_connection(db_path: str | Path):
    connection = connect_db(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: str | Path) -> None:
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with database_connection(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                mode TEXT NOT NULL,
                anger_level INTEGER,
                char_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date_kst TEXT PRIMARY KEY,
                char_count INTEGER NOT NULL DEFAULT 0,
                shred_count INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        }
        if "username" not in user_columns and "email" in user_columns:
            connection.execute("ALTER TABLE users RENAME COLUMN email TO username")
            user_columns.remove("email")
            user_columns.add("username")
        if "username" not in user_columns:
            raise RuntimeError("The users table has no username column.")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS users_username_nocase_idx "
            "ON users(username COLLATE NOCASE)"
        )
    try:
        path.chmod(0o600)
    except OSError:
        pass


def make_password_hash(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    actual_salt = salt or secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), actual_salt, PASSWORD_ITERATIONS
    )
    return actual_salt, password_hash


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def json_response(
    start_response,
    status: HTTPStatus,
    payload: dict,
    extra_headers: list[tuple[str, str]] | None = None,
):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response(f"{status.value} {status.phrase}", headers)
    return [body]


def read_json_body(environ) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as error:
        raise ValueError("요청 크기를 확인할 수 없습니다.") from error
    if length < 0 or length > MAX_BODY_BYTES:
        raise ValueError("요청이 너무 큽니다.")
    raw_body = environ["wsgi.input"].read(length)
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("JSON 형식의 요청이 필요합니다.") from error
    if not isinstance(payload, dict):
        raise ValueError("요청 본문은 JSON 객체여야 합니다.")
    return payload


def get_request_cookie(environ, cookie_name: str) -> str | None:
    cookie = SimpleCookie()
    cookie.load(environ.get("HTTP_COOKIE", ""))
    morsel = cookie.get(cookie_name)
    return morsel.value if morsel else None


def get_session(environ, db_path: str | Path) -> sqlite3.Row | None:
    token = get_request_cookie(environ, COOKIE_NAME)
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    with database_connection(db_path) as connection:
        return connection.execute(
            """SELECT sessions.user_id, sessions.csrf_token, users.username
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (hash_session_token(token), now),
        ).fetchone()


def validate_origin(environ) -> bool:
    origin = environ.get("HTTP_ORIGIN")
    if not origin:
        return True
    parsed_origin = urlsplit(origin)
    request_host = environ.get("HTTP_HOST", "").lower()
    return parsed_origin.netloc.lower() == request_host and parsed_origin.scheme in {
        "http",
        "https",
    }


def make_session(db_path: str | Path, user_id: int, environ):
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=SESSION_DAYS)
    with database_connection(db_path) as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
            (hash_session_token(raw_token), user_id, csrf_token, expiry.isoformat()),
        )
    cookie_value = f"{COOKIE_NAME}={raw_token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}"
    if environ.get("wsgi.url_scheme") == "https":
        cookie_value += "; Secure"
    return csrf_token, ("Set-Cookie", cookie_value)


def make_expired_cookie(environ) -> tuple[str, str]:
    cookie_value = f"{COOKIE_NAME}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
    if environ.get("wsgi.url_scheme") == "https":
        cookie_value += "; Secure"
    return "Set-Cookie", cookie_value


def create_app(
    db_path: str | Path | None = None,
    static_dir: str | Path | None = None,
):
    database_path = get_db_path(db_path)
    assets_dir = Path(static_dir or STATIC_DIR).resolve()
    initialize_database(database_path)

    def application(environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = unquote(environ.get("PATH_INFO", "/"))
        headers = [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin")]

        if method in {"POST", "PUT", "PATCH", "DELETE"} and not validate_origin(environ):
            return json_response(start_response, HTTPStatus.FORBIDDEN, {"error": "허용되지 않은 요청입니다."}, headers)

        try:
            if path == "/api/register" and method == "POST":
                return register_user(environ, start_response, database_path, headers)
            if path == "/api/login" and method == "POST":
                return login_user(environ, start_response, database_path, headers)
            if path.startswith("/api/"):
                return handle_api_request(
                    environ, start_response, database_path, method, path, headers
                )
            if method == "GET":
                return serve_static(start_response, assets_dir, path, headers)
            return json_response(start_response, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "지원하지 않는 요청입니다."}, headers)
        except ValueError as error:
            return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": str(error)}, headers)
        except sqlite3.IntegrityError:
            return json_response(start_response, HTTPStatus.CONFLICT, {"error": "이미 사용 중인 아이디입니다."}, headers)
        except Exception:
            return json_response(
                start_response,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "요청을 처리하지 못했습니다."},
                headers,
            )

    return application


def register_user(environ, start_response, db_path, headers):
    payload = read_json_body(environ)
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "아이디와 비밀번호를 입력해 주세요."}, headers)
    username = username.strip()
    if not username or len(username) > 64:
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "아이디는 1자 이상 64자 이하로 입력해 주세요."}, headers)
    has_english_letter = any("A" <= character <= "Z" or "a" <= character <= "z" for character in password)
    has_number = any("0" <= character <= "9" for character in password)
    if len(password) < 8 or len(password) > 256 or not has_english_letter or not has_number:
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "비밀번호는 영문과 숫자를 포함해 8자 이상이어야 합니다."}, headers)
    salt, password_hash = make_password_hash(password)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with database_connection(db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO users (username, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (username, salt, password_hash, now),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return json_response(start_response, HTTPStatus.CONFLICT, {"error": "이미 사용 중인 아이디입니다."}, headers)
    csrf_token, cookie_header = make_session(db_path, user_id, environ)
    return json_response(
        start_response,
        HTTPStatus.CREATED,
        {"user": {"username": username}, "csrfToken": csrf_token},
        headers + [cookie_header],
    )


def login_user(environ, start_response, db_path, headers):
    payload = read_json_body(environ)
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "아이디와 비밀번호를 입력해 주세요."}, headers)
    with database_connection(db_path) as connection:
        user = connection.execute(
            "SELECT id, username, password_salt, password_hash FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    if user is None:
        return json_response(start_response, HTTPStatus.UNAUTHORIZED, {"error": "아이디 또는 비밀번호를 확인해 주세요."}, headers)
    _, candidate_hash = make_password_hash(password, user["password_salt"])
    if not hmac.compare_digest(candidate_hash, user["password_hash"]):
        return json_response(start_response, HTTPStatus.UNAUTHORIZED, {"error": "아이디 또는 비밀번호를 확인해 주세요."}, headers)
    csrf_token, cookie_header = make_session(db_path, user["id"], environ)
    return json_response(
        start_response,
        HTTPStatus.OK,
        {"user": {"username": user["username"]}, "csrfToken": csrf_token},
        headers + [cookie_header],
    )


def handle_api_request(environ, start_response, db_path, method, path, headers):
    if path == "/api/stats" and method == "GET":
        today_kst = datetime.now(KST).date().isoformat()
        with database_connection(db_path) as connection:
            stats = connection.execute(
                "SELECT char_count, shred_count FROM daily_stats WHERE date_kst = ?",
                (today_kst,),
            ).fetchone()
        return json_response(
            start_response,
            HTTPStatus.OK,
            {
                "date": today_kst,
                "charCount": stats["char_count"] if stats else 0,
                "shredCount": stats["shred_count"] if stats else 0,
            },
            headers,
        )

    session = get_session(environ, db_path)
    if path == "/api/me" and method == "GET":
        if not session:
            return json_response(start_response, HTTPStatus.UNAUTHORIZED, {"error": "로그인이 필요합니다."}, headers)
        return json_response(
            start_response,
            HTTPStatus.OK,
            {"user": {"username": session["username"]}, "csrfToken": session["csrf_token"]},
            headers,
        )

    if path == "/api/logout" and method == "POST":
        if not session:
            return json_response(start_response, HTTPStatus.UNAUTHORIZED, {"error": "로그인이 필요합니다."}, headers)
        if environ.get("HTTP_X_CSRF_TOKEN") != session["csrf_token"]:
            return json_response(start_response, HTTPStatus.FORBIDDEN, {"error": "보안 토큰이 올바르지 않습니다."}, headers)
        token = get_request_cookie(environ, COOKIE_NAME)
        with database_connection(db_path) as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(token),))
        return json_response(
            start_response,
            HTTPStatus.OK,
            {"ok": True},
            headers + [make_expired_cookie(environ)],
        )

    if path.startswith("/api/") and not session:
        return json_response(start_response, HTTPStatus.UNAUTHORIZED, {"error": "로그인이 필요합니다."}, headers)

    if method in {"POST", "DELETE", "PUT", "PATCH"} and path != "/api/login":
        if environ.get("HTTP_X_CSRF_TOKEN") != session["csrf_token"]:
            return json_response(start_response, HTTPStatus.FORBIDDEN, {"error": "보안 토큰이 올바르지 않습니다."}, headers)

    if path == "/api/profile" and method == "PATCH":
        payload = read_json_body(environ)
        username = payload.get("username")
        if not isinstance(username, str):
            return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "아이디를 입력해 주세요."}, headers)
        username = username.strip()
        if not username or len(username) > 64:
            return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "아이디는 1자 이상 64자 이하로 입력해 주세요."}, headers)
        try:
            with database_connection(db_path) as connection:
                connection.execute(
                    "UPDATE users SET username = ? WHERE id = ?",
                    (username, session["user_id"]),
                )
        except sqlite3.IntegrityError:
            return json_response(start_response, HTTPStatus.CONFLICT, {"error": "이미 사용 중인 아이디입니다."}, headers)
        return json_response(start_response, HTTPStatus.OK, {"user": {"username": username}}, headers)

    if path == "/api/entries" and method == "GET":
        with database_connection(db_path) as connection:
            entries = connection.execute(
                """SELECT id, text, mode, char_count AS charCount, created_at AS createdAt
                   FROM entries WHERE user_id = ? ORDER BY id DESC""",
                (session["user_id"],),
            ).fetchall()
        return json_response(start_response, HTTPStatus.OK, {"entries": [dict(row) for row in entries]}, headers)

    if path == "/api/entries" and method == "POST":
        payload = read_json_body(environ)
        text = payload.get("text")
        mode = payload.get("mode")
        if not isinstance(text, str) or not text.strip():
            return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "파쇄할 내용을 입력해 주세요."}, headers)
        char_count = len(text)
        if char_count > MAX_TEXT_LENGTH:
            return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": f"내용은 {MAX_TEXT_LENGTH}자 이내로 입력해 주세요."}, headers)
        if not isinstance(mode, str) or mode not in VALID_MODES:
            return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": "파쇄 모드를 확인해 주세요."}, headers)
        now = datetime.now(timezone.utc)
        date_kst = now.astimezone(KST).date().isoformat()
        with database_connection(db_path) as connection:
            cursor = connection.execute(
                """INSERT INTO entries
                   (user_id, text, mode, char_count, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session["user_id"], text, mode, char_count, now.isoformat()),
            )
            entry_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO daily_stats (date_kst, char_count, shred_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(date_kst) DO UPDATE SET
                     char_count = char_count + excluded.char_count,
                     shred_count = shred_count + 1""",
                (date_kst, char_count),
            )
        return json_response(start_response, HTTPStatus.CREATED, {"id": entry_id, "charCount": char_count}, headers)

    if path == "/api/entries" and method == "DELETE":
        with database_connection(db_path) as connection:
            connection.execute("DELETE FROM entries WHERE user_id = ?", (session["user_id"],))
        return json_response(start_response, HTTPStatus.OK, {"ok": True}, headers)

    if path.startswith("/api/entries/") and method == "DELETE":
        entry_id_text = path.removeprefix("/api/entries/")
        if not entry_id_text.isdigit():
            return json_response(start_response, HTTPStatus.NOT_FOUND, {"error": "기록을 찾을 수 없습니다."}, headers)
        with database_connection(db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM entries WHERE id = ? AND user_id = ?",
                (int(entry_id_text), session["user_id"]),
            )
        if cursor.rowcount == 0:
            return json_response(start_response, HTTPStatus.NOT_FOUND, {"error": "기록을 찾을 수 없습니다."}, headers)
        return json_response(start_response, HTTPStatus.OK, {"ok": True}, headers)

    if path == "/api/account" and method == "DELETE":
        token = get_request_cookie(environ, COOKIE_NAME)
        with database_connection(db_path) as connection:
            connection.execute("DELETE FROM users WHERE id = ?", (session["user_id"],))
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_session_token(token),))
        return json_response(
            start_response,
            HTTPStatus.OK,
            {"ok": True},
            headers + [make_expired_cookie(environ)],
        )

    return json_response(start_response, HTTPStatus.NOT_FOUND, {"error": "요청한 경로를 찾을 수 없습니다."}, headers)


def serve_static(start_response, static_dir: Path, request_path: str, headers):
    route_files = {
        "/": "index.html",
        "/index.html": "index.html",
        "/styles.css": "styles.css",
        "/animations.css": "animations.css",
        "/app.js": "app.js",
        "/assets/nasa-carina-nebula.jpg": "assets/nasa-carina-nebula.jpg",
        "/assets/paper-grain.svg": "assets/paper-grain.svg",
        "/assets/paper-creases.svg": "assets/paper-creases.svg",
    }
    file_name = route_files.get(request_path)
    if not file_name:
        return json_response(start_response, HTTPStatus.NOT_FOUND, {"error": "페이지를 찾을 수 없습니다."}, headers)
    file_path = static_dir / file_name
    try:
        body = file_path.read_bytes()
    except OSError:
        return json_response(start_response, HTTPStatus.NOT_FOUND, {"error": "페이지를 찾을 수 없습니다."}, headers)
    if file_name.endswith(".html"):
        content_type = "text/html; charset=utf-8"
    elif file_name.endswith(".css"):
        content_type = "text/css; charset=utf-8"
    elif file_name.endswith(".js"):
        content_type = "text/javascript; charset=utf-8"
    elif file_name.endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    elif file_name.endswith(".png"):
        content_type = "image/png"
    elif file_name.endswith(".svg"):
        content_type = "image/svg+xml"
    else:
        content_type = "application/octet-stream"
    response_headers = headers + [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache"),
        ("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"),
    ]
    start_response("200 OK", response_headers)
    return [body]


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    app = create_app()
    with make_server("127.0.0.1", port, app) as server:
        print(f"Anger release site listening on http://127.0.0.1:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Server stopped.")


if __name__ == "__main__":
    main()
