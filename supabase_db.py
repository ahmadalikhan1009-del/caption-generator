import os
import re
import secrets
import hashlib
from typing import Optional, Dict, Any, Tuple
import requests
from dotenv import load_dotenv

load_dotenv()

def get_supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def get_supabase_key() -> str:
    return (
        os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
    )


import time

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REQUEST_TIMEOUT = 10  # seconds

_supabase_verified = None
_last_check_time = 0.0


def is_ready(force_check: bool = False) -> bool:
    """Checks whether Supabase is configured AND the database tables are live and accessible."""
    global _supabase_verified, _last_check_time
    if not is_configured():
        _supabase_verified = False
        return False

    now = time.time()
    if not force_check:
        if _supabase_verified is True and (now - _last_check_time < 60.0):
            return True
        if _supabase_verified is False and (now - _last_check_time < 10.0):
            return False

    ok, _ = test_connection()
    _supabase_verified = ok
    _last_check_time = now
    return ok


def is_configured() -> bool:
    """Returns True if Supabase credentials are validly configured in environment."""
    url = get_supabase_url()
    key = get_supabase_key()
    if not url or not key:
        return False
    if "your-project" in url.lower() or "your_supabase" in url.lower() or "your_supabase" in key.lower():
        return False
    return url.startswith("http://") or url.startswith("https://")


def _get_headers() -> Dict[str, str]:
    """Builds standard PostgREST API headers for Supabase."""
    key = get_supabase_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def _hash_password(password: str, salt: str) -> str:
    """Hashes password using PBKDF2 with SHA-256 and salt."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100000
    ).hex()


def test_connection() -> Tuple[bool, str]:
    """Tests connection to the Supabase users table."""
    if not is_configured():
        return False, "Supabase credentials are not set in .env"
    try:
        url = f"{get_supabase_url()}/rest/v1/users?select=id&limit=1"
        res = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return True, "Successfully connected to Supabase database!"
        elif res.status_code == 404 or "PGRST205" in res.text or "not find the table" in res.text or "relation \"public.users\" does not exist" in res.text:
            return False, "Supabase credentials verified successfully, but the 'users' and 'reviews' tables have not been created in Supabase yet. Please run 'supabase_schema.sql' in your Supabase SQL Editor."
        else:
            return False, f"Supabase responded with HTTP {res.status_code}: {res.text}"
    except Exception as e:
        return False, f"Failed to connect to Supabase: {str(e)}"


def signup_user(email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Registers a new user in Supabase without OTP."""
    clean_email = (email or "").strip().lower()
    if not clean_email or not EMAIL_REGEX.match(clean_email) or any(ch in clean_email for ch in "<>\'\""):
        return False, "Please enter a valid email address.", None

    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long.", None

    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    token = secrets.token_hex(24)

    # Check if user exists
    try:
        check_url = f"{get_supabase_url()}/rest/v1/users?email=ilike.{clean_email}&select=id"
        check_res = requests.get(check_url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if check_res.status_code == 404 or "PGRST205" in check_res.text:
            return False, "Database tables not found in Supabase. Please copy and run the SQL from 'supabase_schema.sql' in your Supabase SQL Editor.", None

        if check_res.status_code == 200 and len(check_res.json()) > 0:
            return False, "An account with this email already exists. Please log in.", None

        # Insert user
        insert_url = f"{get_supabase_url()}/rest/v1/users"
        payload = {
            "email": clean_email,
            "password_hash": pwd_hash,
            "salt": salt,
            "clips_count": 0,
            "has_reviewed": False,
            "auth_token": token
        }
        ins_res = requests.post(insert_url, headers=_get_headers(), json=payload, timeout=REQUEST_TIMEOUT)
        if ins_res.status_code in (200, 201):
            created = ins_res.json()
            user_row = created[0] if isinstance(created, list) and len(created) > 0 else payload
            return True, "Account created successfully!", {
                "id": user_row.get("id"),
                "email": clean_email,
                "clips_count": 0,
                "has_reviewed": False,
                "token": token
            }
        return False, f"Failed to create account in Supabase: {ins_res.text}", None
    except Exception as e:
        return False, f"Supabase connection error: {str(e)}", None


def login_user(email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Authenticates user in Supabase and returns refreshed auth token."""
    clean_email = (email or "").strip().lower()
    if not clean_email or not password:
        return False, "Email and password are required.", None

    try:
        url = f"{get_supabase_url()}/rest/v1/users?email=ilike.{clean_email}&select=*"
        res = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if res.status_code == 404 or "PGRST205" in res.text:
            return False, "Database tables not found in Supabase. Please copy and run the SQL from 'supabase_schema.sql' in your Supabase SQL Editor.", None

        if res.status_code != 200 or not res.json():
            return False, "No account found with this email. Please sign up.", None

        row = res.json()[0]
        expected_hash = _hash_password(password, row.get("salt", ""))
        if expected_hash != row.get("password_hash"):
            return False, "Incorrect password. Please try again.", None

        # Refresh auth token
        token = secrets.token_hex(24)
        patch_url = f"{get_supabase_url()}/rest/v1/users?id=eq.{row['id']}"
        requests.patch(patch_url, headers=_get_headers(), json={"auth_token": token}, timeout=REQUEST_TIMEOUT)

        return True, "Logged in successfully!", {
            "id": row["id"],
            "email": row["email"],
            "clips_count": row.get("clips_count", 0),
            "has_reviewed": bool(row.get("has_reviewed", False)),
            "token": token
        }
    except Exception as e:
        return False, f"Supabase authentication error: {str(e)}", None



def logout_user(token: Optional[str]) -> bool:
    """Invalidates the user session auth token by setting it to NULL in Supabase."""
    if not token or not str(token).strip():
        return False
    try:
        clean_token = str(token).strip()
        url = f"{get_supabase_url()}/rest/v1/users?auth_token=eq.{clean_token}"
        res = requests.patch(url, headers=_get_headers(), json={"auth_token": None}, timeout=REQUEST_TIMEOUT)
        return res.status_code in (200, 204)
    except Exception as e:
        print(f"[Supabase Logout Error] {e}")
        return False


def get_user_by_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrieves user from Supabase by auth token."""
    if not token or not str(token).strip():
        return None
    try:
        clean_token = str(token).strip()
        url = f"{get_supabase_url()}/rest/v1/users?auth_token=eq.{clean_token}&select=*"
        res = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if res.status_code == 200 and res.json():
            row = res.json()[0]
            return {
                "id": row["id"],
                "email": row["email"],
                "clips_count": row.get("clips_count", 0),
                "has_reviewed": bool(row.get("has_reviewed", False)),
                "token": row.get("auth_token"),
                "created_at": row.get("created_at")
            }
        return None
    except Exception:
        return None


def get_user_by_id(user_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Retrieves user from Supabase by ID."""
    if not user_id:
        return None
    try:
        url = f"{get_supabase_url()}/rest/v1/users?id=eq.{user_id}&select=*"
        res = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if res.status_code == 200 and res.json():
            row = res.json()[0]
            return {
                "id": row["id"],
                "email": row["email"],
                "clips_count": row.get("clips_count", 0),
                "has_reviewed": bool(row.get("has_reviewed", False)),
                "token": row.get("auth_token"),
                "created_at": row.get("created_at")
            }
        return None
    except Exception:
        return None


def increment_user_clips(user_id: int, count: int = 1) -> int:
    """Increments the clips_count of a user in Supabase and returns new count."""
    if not user_id:
        return 0
    try:
        # Fetch current count
        user = get_user_by_id(user_id)
        if not user:
            return 0
        current_count = int(user.get("clips_count", 0))
        new_count = current_count + max(1, count)

        # Update
        patch_url = f"{get_supabase_url()}/rest/v1/users?id=eq.{user_id}"
        requests.patch(patch_url, headers=_get_headers(), json={"clips_count": new_count}, timeout=REQUEST_TIMEOUT)
        return new_count
    except Exception as e:
        print(f"[Supabase] Error incrementing clips count: {e}")
        return 0


def save_user_review(user_id: int, user_email: str, rating: int, review_text: str, owner_email: str) -> Dict[str, Any]:
    """Saves user review and marks has_reviewed = True in Supabase."""
    clean_rating = max(1, min(5, int(rating or 5)))
    clean_review = (review_text or "").strip()

    try:
        # Insert into reviews table
        insert_url = f"{get_supabase_url()}/rest/v1/reviews"
        payload = {
            "user_id": user_id,
            "user_email": user_email,
            "rating": clean_rating,
            "review_text": clean_review,
            "owner_email": owner_email
        }
        res = requests.post(insert_url, headers=_get_headers(), json=payload, timeout=REQUEST_TIMEOUT)
        review_id = None
        if res.status_code in (200, 201) and res.json():
            review_id = res.json()[0].get("id")

        # Mark user has_reviewed = True
        if user_id:
            patch_url = f"{get_supabase_url()}/rest/v1/users?id=eq.{user_id}"
            requests.patch(patch_url, headers=_get_headers(), json={"has_reviewed": True}, timeout=REQUEST_TIMEOUT)

        return {
            "id": review_id,
            "user_id": user_id,
            "user_email": user_email,
            "rating": clean_rating,
            "review_text": clean_review,
            "owner_email": owner_email
        }
    except Exception as e:
        print(f"[Supabase] Error saving review: {e}")
        return {
            "user_id": user_id,
            "user_email": user_email,
            "rating": clean_rating,
            "review_text": clean_review,
            "owner_email": owner_email
        }


def get_all_users() -> list:
    """Retrieves all registered users from Supabase for admin viewing (passwords excluded)."""
    if not is_ready():
        return []
    try:
        url = f"{get_supabase_url()}/rest/v1/users?select=id,email,clips_count,has_reviewed,created_at&order=id.desc"
        res = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if res.status_code == 200 and isinstance(res.json(), list):
            return res.json()
        return []
    except Exception as e:
        print(f"[Supabase] Error fetching users list: {e}")
        return []


def get_all_reviews() -> list:
    """Retrieves all reviews from Supabase for admin viewing."""
    if not is_ready():
        return []
    try:
        url = f"{get_supabase_url()}/rest/v1/reviews?select=id,user_id,user_email,rating,review_text,owner_email,created_at&order=id.desc"
        res = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        if res.status_code == 200 and isinstance(res.json(), list):
            return res.json()
        return []
    except Exception as e:
        print(f"[Supabase] Error fetching reviews list: {e}")
        return []

