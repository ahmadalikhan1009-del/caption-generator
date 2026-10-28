import os
import sqlite3
import hashlib
import secrets
import re
from typing import Optional, Dict, Any, Tuple, List
import json
import supabase_db

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_DIR, "app.db")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_db_type() -> str:
    """Returns 'supabase' if Supabase credentials are configured, otherwise 'sqlite'."""
    return "supabase" if supabase_db.is_ready() else "sqlite"


def get_db_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database with row factory enabled."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes users and reviews database tables."""
    if supabase_db.is_ready():
        ok, msg = supabase_db.test_connection()
        if ok:
            print("[Database] Active: Supabase Cloud Database.")
        else:
            print(f"[Database] Notice: Supabase configured, status: {msg}")
        return

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                clips_count INTEGER DEFAULT 0,
                has_reviewed INTEGER DEFAULT 0,
                auth_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_email TEXT NOT NULL,
                rating INTEGER NOT NULL,
                review_text TEXT NOT NULL,
                owner_email TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _hash_password(password: str, salt: str) -> str:
    """Hashes password using PBKDF2 with SHA-256 and salt."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100000
    ).hex()


def signup_user(email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Registers a new user with email and password without requiring OTP.
    Returns (success, message, user_data).
    """
    if supabase_db.is_ready():
        return supabase_db.signup_user(email, password)

    clean_email = (email or "").strip().lower()
    if not clean_email or not EMAIL_REGEX.match(clean_email) or any(ch in clean_email for ch in "<>\'\""):
        return False, "Please enter a valid email address.", None

    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long.", None

    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    token = secrets.token_hex(24)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (clean_email,))
        if cursor.fetchone():
            return False, "An account with this email already exists. Please log in.", None

        cursor.execute(
            "INSERT INTO users (email, password_hash, salt, clips_count, has_reviewed, auth_token) VALUES (?, ?, ?, 0, 0, ?)",
            (clean_email, pwd_hash, salt, token)
        )
        conn.commit()
        user_id = cursor.lastrowid
        user_data = {
            "id": user_id,
            "email": clean_email,
            "clips_count": 0,
            "has_reviewed": False,
            "token": token
        }
        return True, "Account created successfully!", user_data
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists. Please log in.", None
    finally:
        conn.close()


def login_user(email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Authenticates user and returns refreshed auth token and profile.
    """
    if supabase_db.is_ready():
        return supabase_db.login_user(email, password)

    clean_email = (email or "").strip().lower()
    if not clean_email or not password:
        return False, "Email and password are required.", None

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (clean_email,))
        row = cursor.fetchone()
        if not row:
            return False, "No account found with this email. Please sign up.", None

        expected_hash = _hash_password(password, row["salt"])
        if expected_hash != row["password_hash"]:
            return False, "Incorrect password. Please try again.", None

        # Refresh auth token
        token = secrets.token_hex(24)
        cursor.execute("UPDATE users SET auth_token = ? WHERE id = ?", (token, row["id"]))
        conn.commit()

        user_data = {
            "id": row["id"],
            "email": row["email"],
            "clips_count": row["clips_count"],
            "has_reviewed": bool(row["has_reviewed"]),
            "token": token
        }
        return True, "Logged in successfully!", user_data
    finally:
        conn.close()


def logout_user(token: Optional[str]) -> bool:
    """Invalidates user session auth token in active database."""
    if not token or not str(token).strip():
        return False
    if supabase_db.is_ready():
        return supabase_db.logout_user(token)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET auth_token = NULL WHERE auth_token = ?", (str(token).strip(),))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_user_by_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrieves user by session auth token."""
    if not token or not token.strip():
        return None

    if supabase_db.is_ready():
        return supabase_db.get_user_by_token(token)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE auth_token = ?", (token.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "clips_count": row["clips_count"],
            "has_reviewed": bool(row["has_reviewed"]),
            "token": row["auth_token"],
            "created_at": row["created_at"]
        }
    finally:
        conn.close()

def get_user_by_id(user_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Retrieves user by user ID."""
    if not user_id:
        return None

    if supabase_db.is_ready():
        return supabase_db.get_user_by_id(user_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "email": row["email"],
            "clips_count": row["clips_count"],
            "has_reviewed": bool(row["has_reviewed"]),
            "token": row["auth_token"],
            "created_at": row["created_at"]
        }
    finally:
        conn.close()


def increment_user_clips(user_id: int, count: int = 1) -> int:
    """Increments the clips_count of a user and returns new count."""
    if supabase_db.is_ready():
        return supabase_db.increment_user_clips(user_id, count)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET clips_count = clips_count + ? WHERE id = ?",
            (max(1, count), user_id)
        )
        conn.commit()
        cursor.execute("SELECT clips_count FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return row["clips_count"] if row else 0
    finally:
        conn.close()


# Backward compatibility alias for clip counting
increment_clips_count = increment_user_clips


def save_user_review(user_id: int, user_email: str, rating: int, review_text: str, owner_email: str) -> Dict[str, Any]:
    """
    Saves user review and marks has_reviewed = 1 for the user so they can continue generating clips.
    """
    if supabase_db.is_ready():
        return supabase_db.save_user_review(user_id, user_email, rating, review_text, owner_email)

    clean_rating = max(1, min(5, int(rating or 5)))
    clean_review = (review_text or "").strip()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reviews (user_id, user_email, rating, review_text, owner_email) VALUES (?, ?, ?, ?, ?)",
            (user_id, user_email, clean_rating, clean_review, owner_email)
        )
        cursor.execute(
            "UPDATE users SET has_reviewed = 1 WHERE id = ?",
            (user_id,)
        )
        conn.commit()
        review_id = cursor.lastrowid
        return {
            "id": review_id,
            "user_id": user_id,
            "user_email": user_email,
            "rating": clean_rating,
            "review_text": clean_review,
            "owner_email": owner_email
        }
    finally:
        conn.close()


# ================= ADMIN SYSTEM HELPERS & QUERIES =================
READ_STATE_FILE = os.path.join(DB_DIR, "reviews_read_state.json")


def get_admin_emails() -> set:
    """Gets the set of emails authorized for administrator access from environment."""
    from dotenv import load_dotenv
    load_dotenv(override=False)
    admin_env = (
        os.getenv("ADMIN_EMAILS")
        or os.getenv("OWNER_EMAIL")
        or os.getenv("ADMIN_EMAIL")
        or "ahmadalikhan1009@gmail.com,owner@example.com"
    )
    return {e.strip().lower() for e in admin_env.split(",") if e.strip()}


def is_admin_email(email: Optional[str]) -> bool:
    """Returns True if the given email is an authorized administrator."""
    if not email:
        return False
    return email.strip().lower() in get_admin_emails()


def get_read_review_ids() -> set:
    """Returns the set of review IDs marked as read."""
    if not os.path.exists(READ_STATE_FILE):
        return set()
    try:
        with open(READ_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("read_ids", []))
    except Exception:
        return set()


def set_review_read_status(review_id: int, is_read: bool = True) -> bool:
    """Updates the read/unread state for a review without altering database schema."""
    try:
        os.makedirs(DB_DIR, exist_ok=True)
        read_ids = get_read_review_ids()
        r_id = int(review_id)
        if is_read:
            read_ids.add(r_id)
        else:
            read_ids.discard(r_id)
        with open(READ_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"read_ids": sorted(list(read_ids))}, f)
        return True
    except Exception as e:
        print(f"[Admin] Error saving review read status: {e}")
        return False


COMPLETED_VIDEOS_FILE = os.path.join(DB_DIR, "user_completed_videos.json")

def get_all_completed_videos_map() -> Dict[str, List[str]]:
    """Returns the map of user_id to list of completed video keys."""
    if not os.path.exists(COMPLETED_VIDEOS_FILE):
        return {}
    try:
        with open(COMPLETED_VIDEOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_all_completed_videos_map(data: Dict[str, List[str]]):
    """Saves the completed videos map to disk."""
    os.makedirs(DB_DIR, exist_ok=True)
    try:
        with open(COMPLETED_VIDEOS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Completed Videos] Error saving: {e}")

def _normalize_video_key(video_key: str) -> str:
    """Normalizes video key by matching source video filename and size to prevent double-counting."""
    if not video_key:
        return ""
    v_str = str(video_key).strip()
    match = re.search(r'^(.*?\.(?:mp4|mov|mkv|avi|webm|m4v))', v_str, re.IGNORECASE)
    if match:
        base_name = match.group(1).lower()
        remainder = v_str[match.end():]
        nums = [int(n) for n in re.findall(r'\d+', remainder)]
        valid_sizes = [n for n in nums if n < 100000000000]
        if valid_sizes:
            return f"{base_name}_{max(valid_sizes)}"
        return base_name
    return v_str


def get_completed_videos_for_user(user_id: Optional[int]) -> List[str]:
    """Retrieves unique completed video keys for a user."""
    if not user_id:
        return []
    data = get_all_completed_videos_map()
    raw_list = data.get(str(user_id), [])
    unique_keys = []
    for k in raw_list:
        norm = _normalize_video_key(k)
        if norm and norm not in unique_keys:
            unique_keys.append(norm)
    return unique_keys


def record_completed_video_for_user(user_id: Optional[int], video_key: str) -> Tuple[int, bool]:
    """Records a unique completed video for a user without duplicates."""
    if not user_id or not video_key:
        return (0, False)
    data = get_all_completed_videos_map()
    uid_str = str(user_id)
    user_list = data.get(uid_str, [])
    norm_key = _normalize_video_key(video_key)
    existing_normalized = {_normalize_video_key(k) for k in user_list}
    is_new = False
    if norm_key not in existing_normalized:
        user_list.append(norm_key)
        data[uid_str] = user_list
        save_all_completed_videos_map(data)
        is_new = True
    unique_count = len({_normalize_video_key(k) for k in user_list})
    return (unique_count, is_new)


def is_test_record(email: Optional[str], text: Optional[str] = None) -> bool:
    """Detects automated test run artifacts to keep the owner dashboard clean and trustworthy."""
    em = (email or "").strip().lower()
    tx = (text or "").strip().lower()
    test_prefixes = (
        "test_admin_",
        "regular_user_",
        "creator_",
        "creator@",
        "videomaker_",
        "videomaker@",
        "gating_",
        "review_clipping_",
        "cliptester@",
        "owner@example.com"
    )
    if any(em.startswith(p) for p in test_prefixes) or em.endswith("@test.com"):
        return True
    if "automated test feedback" in tx or tx == "custom clipping works great!" or tx == "super fast and wonderful tool! absolutely love the clipping.":
        return True
    return False


def get_all_users(include_test: bool = False) -> List[Dict[str, Any]]:
    """Retrieves registered users for the owner dashboard (passwords excluded)."""
    if supabase_db.is_ready():
        users = supabase_db.get_all_users()
    else:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, clips_count, has_reviewed, created_at FROM users ORDER BY id DESC")
            rows = cursor.fetchall()
            users = [
                {
                    "id": r["id"],
                    "email": r["email"],
                    "clips_count": r["clips_count"],
                    "has_reviewed": bool(r["has_reviewed"]),
                    "created_at": r["created_at"]
                }
                for r in rows
            ]
        finally:
            conn.close()

    if not include_test:
        users = [u for u in users if not is_test_record(u.get("email"))]

    for u in users:
        completed = get_completed_videos_for_user(u.get("id"))
        u["videos_count"] = len(completed)
        u["completed_videos_count"] = len(completed)

    return users


def get_all_reviews(include_test: bool = False) -> List[Dict[str, Any]]:
    """Retrieves user reviews with read/unread status merged."""
    if supabase_db.is_ready():
        raw_reviews = supabase_db.get_all_reviews()
    else:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, user_email, rating, review_text, owner_email, created_at FROM reviews ORDER BY id DESC")
            rows = cursor.fetchall()
            raw_reviews = [dict(r) for r in rows]
        finally:
            conn.close()

    read_ids = get_read_review_ids()
    for rev in raw_reviews:
        r_id = rev.get("id")
        rev["is_read"] = (r_id in read_ids) if r_id is not None else False

    if not include_test:
        raw_reviews = [r for r in raw_reviews if not is_test_record(r.get("user_email"), r.get("review_text"))]

    return raw_reviews


# Initialize database automatically when imported
init_db()

