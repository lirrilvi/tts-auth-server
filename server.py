"""
TTS Auth Server v2
"""
import sqlite3, secrets, string, time, os
from flask import Flask, request, jsonify, send_file, abort
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

BOT_SECRET = os.getenv("BOT_SECRET", "change_me")
DB_PATH    = "tokens.db"

# ─── DB ───────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id          TEXT PRIMARY KEY,
                username         TEXT,
                first_name       TEXT,
                is_blocked       INTEGER DEFAULT 0,
                subscription_end INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                token      TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                shift      TEXT
            );
            CREATE TABLE IF NOT EXISTS downloads (
                user_id      TEXT PRIMARY KEY,
                dl_token     TEXT UNIQUE,
                created_at   INTEGER,
                downloaded   INTEGER DEFAULT 0,
                downloaded_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS sub_requests (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL,
                username   TEXT,
                first_name TEXT,
                requested_at INTEGER NOT NULL,
                status     TEXT DEFAULT 'pending'
            );
        """)
        db.commit()

def make_token(length=8):
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id    = str(data.get("user_id", "")).strip()
    expires_at = int(data.get("expires_at", 0))
    shift      = data.get("shift", "")
    username   = data.get("username", "")
    first_name = data.get("first_name", "")

    if not user_id or not expires_at:
        return jsonify({"ok": False, "error": "missing params"}), 400

    now = int(time.time())

    with get_db() as db:
        # Upsert user info
        db.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
        """, (user_id, username, first_name))

        # Remove old tokens for this user
        db.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))

        token = make_token()
        while db.execute("SELECT 1 FROM tokens WHERE token=?", (token,)).fetchone():
            token = make_token()

        db.execute(
            "INSERT INTO tokens (user_id, token, created_at, expires_at, shift) VALUES (?,?,?,?,?)",
            (user_id, token, now, expires_at, shift)
        )
        db.commit()

    return jsonify({"ok": True, "token": token})


@app.route("/api/validate", methods=["POST"])
def validate():
    data  = request.get_json(silent=True) or {}
    token = str(data.get("token", "")).strip().upper()
    if not token:
        return jsonify({"ok": False, "error": "no token"}), 400

    now = int(time.time())
    with get_db() as db:
        row = db.execute(
            "SELECT t.*, u.is_blocked FROM tokens t LEFT JOIN users u ON t.user_id=u.user_id WHERE t.token=?",
            (token,)
        ).fetchone()

        if not row:
            return jsonify({"ok": False, "msg": "Неверный токен"}), 401
        if row["is_blocked"]:
            return jsonify({"ok": False, "error": "blocked", "msg": "Доступ заблокирован"}), 403
        if now > row["expires_at"]:
            return jsonify({"ok": False, "error": "expired", "msg": "Токен истёк — запроси новый у бота"}), 401

        remaining = row["expires_at"] - now
        h, m = divmod(remaining // 60, 60)
        return jsonify({
            "ok": True,
            "shift": row["shift"],
            "expires_msg": f"Действует ещё {h}ч {m}м"
        })


@app.route("/api/revoke", methods=["POST"])
def revoke():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id = str(data.get("user_id", "")).strip()
    with get_db() as db:
        db.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/block", methods=["POST"])
def block_user():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id = str(data.get("user_id", "")).strip()
    blocked = int(data.get("blocked", 1))
    with get_db() as db:
        db.execute(
            "INSERT INTO users (user_id, is_blocked) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET is_blocked=?",
            (user_id, blocked, blocked)
        )
        if blocked:
            db.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/active_tokens", methods=["POST"])
def active_tokens():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    now = int(time.time())
    with get_db() as db:
        rows = db.execute("""
            SELECT t.user_id, t.token, t.expires_at, t.shift,
                   u.username, u.first_name, u.is_blocked
            FROM tokens t
            LEFT JOIN users u ON t.user_id = u.user_id
            WHERE t.expires_at > ?
            ORDER BY t.expires_at DESC
        """, (now,)).fetchall()
    return jsonify({"ok": True, "tokens": [dict(r) for r in rows]})


@app.route("/api/all_users", methods=["POST"])
def all_users():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    with get_db() as db:
        rows = db.execute(
            "SELECT user_id, username, first_name FROM users WHERE is_blocked != 1"
        ).fetchall()
    return jsonify({"ok": True, "users": [dict(r) for r in rows]})


@app.route("/api/sub_request", methods=["POST"])
def sub_request():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id    = str(data.get("user_id", "")).strip()
    username   = data.get("username", "")
    first_name = data.get("first_name", "")
    now        = int(time.time())

    with get_db() as db:
        # Check if already has active subscription
        user = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if user and user["subscription_end"] > now:
            remaining = user["subscription_end"] - now
            d = remaining // 86400
            return jsonify({"ok": False, "error": "already_subscribed", "days_left": d})

        # Check for pending request
        pending = db.execute(
            "SELECT * FROM sub_requests WHERE user_id=? AND status='pending'", (user_id,)
        ).fetchone()
        if pending:
            return jsonify({"ok": False, "error": "pending"})

        db.execute(
            "INSERT INTO sub_requests (user_id, username, first_name, requested_at) VALUES (?,?,?,?)",
            (user_id, username, first_name, now)
        )
        db.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
        """, (user_id, username, first_name))
        db.commit()

    return jsonify({"ok": True})


@app.route("/api/approve_sub", methods=["POST"])
def approve_sub():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id = str(data.get("user_id", "")).strip()
    approve = data.get("approve", True)
    now     = int(time.time())

    with get_db() as db:
        db.execute(
            "UPDATE sub_requests SET status=? WHERE user_id=? AND status='pending'",
            ("approved" if approve else "denied", user_id)
        )
        if approve:
            sub_end = now + 30 * 86400
            db.execute(
                "UPDATE users SET subscription_end=? WHERE user_id=?",
                (sub_end, user_id)
            )
        db.commit()

    return jsonify({"ok": True})


@app.route("/api/pending_subs", methods=["POST"])
def pending_subs():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM sub_requests WHERE status='pending' ORDER BY requested_at DESC"
        ).fetchall()
    return jsonify({"ok": True, "requests": [dict(r) for r in rows]})


@app.route("/api/create_download", methods=["POST"])
def create_download():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id = str(data.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "no user_id"}), 400

    now = int(time.time())
    dl_token = secrets.token_urlsafe(32)

    with get_db() as db:
        db.execute("""
            INSERT INTO downloads (user_id, dl_token, created_at, downloaded)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET dl_token=excluded.dl_token,
            created_at=excluded.created_at, downloaded=0, downloaded_at=NULL
        """, (user_id, dl_token, now))
        db.commit()

    server_url = os.getenv("SERVER_URL", "http://localhost:5055")
    link = f"{server_url}/download/{dl_token}"
    return jsonify({"ok": True, "link": link, "dl_token": dl_token})


@app.route("/download/<dl_token>", methods=["GET"])
def download_file(dl_token):
    zip_path = os.path.join(os.path.dirname(__file__), "extension.zip")
    if not os.path.exists(zip_path):
        abort(404, "Файл расширения не найден на сервере")

    now = int(time.time())
    with get_db() as db:
        row = db.execute("SELECT * FROM downloads WHERE dl_token=?", (dl_token,)).fetchone()
        if not row:
            abort(403, "Недействительная ссылка")
        if row["downloaded"]:
            abort(403, "Ссылка уже была использована")

        db.execute("UPDATE downloads SET downloaded=1, downloaded_at=? WHERE dl_token=?",
                   (now, dl_token))
        db.commit()

    return send_file(zip_path, as_attachment=True, download_name="tts-extension.zip")


@app.route("/api/download_status", methods=["POST"])
def download_status():
    data = request.get_json(silent=True) or {}
    if data.get("bot_secret") != BOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    with get_db() as db:
        rows = db.execute("""
            SELECT d.user_id, d.downloaded, d.downloaded_at,
                   u.username, u.first_name
            FROM downloads d
            LEFT JOIN users u ON d.user_id = u.user_id
            ORDER BY d.created_at DESC
        """).fetchall()
    return jsonify({"ok": True, "downloads": [dict(r) for r in rows]})


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", 5055))
    print(f"✅ Сервер запущен на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
