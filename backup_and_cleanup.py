import os
import json
import requests
from datetime import datetime
import auth_db
import supabase_db

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "data", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

PROTECTED_EMAILS = {
    "ahmadalikhan1009@gmail.com",
    "auramart1100@gmail.com",
    "ka3143923@gmail.com"
}
PROTECTED_REVIEW_IDS = {16}

def run_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    headers = supabase_db._get_headers()
    sb_url = supabase_db.get_supabase_url()

    # 1. Fetch full Supabase users table
    users_res = requests.get(f"{sb_url}/rest/v1/users?select=*", headers=headers)
    all_users = users_res.json() if users_res.status_code == 200 else []

    # 2. Fetch full Supabase reviews table
    revs_res = requests.get(f"{sb_url}/rest/v1/reviews?select=*", headers=headers)
    all_reviews = revs_res.json() if revs_res.status_code == 200 else []

    # 3. Fetch SQLite records as well
    conn = auth_db.get_db_connection()
    try:
        sql_users = [dict(r) for r in conn.execute("SELECT * FROM users").fetchall()]
        sql_reviews = [dict(r) for r in conn.execute("SELECT * FROM reviews").fetchall()]
    finally:
        conn.close()

    backup_data = {
        "timestamp": timestamp,
        "supabase_users": all_users,
        "supabase_reviews": all_reviews,
        "sqlite_users": sql_users,
        "sqlite_reviews": sql_reviews
    }

    users_backup_file = os.path.join(BACKUP_DIR, f"backup_full_{timestamp}.json")
    with open(users_backup_file, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, default=str)

    print(f"[Backup] Successfully saved complete backup to: {users_backup_file}")
    return users_backup_file, all_users, all_reviews

def run_cleanup(all_users, all_reviews):
    headers = supabase_db._get_headers()
    sb_url = supabase_db.get_supabase_url()

    # Identify test users to delete
    users_to_delete = []
    for u in all_users:
        em = u.get("email", "").strip().lower()
        if em not in PROTECTED_EMAILS:
            users_to_delete.append(u)

    # Identify test reviews to delete
    reviews_to_delete = []
    for r in all_reviews:
        r_id = r.get("id")
        em = r.get("user_email", "").strip().lower()
        if r_id not in PROTECTED_REVIEW_IDS and em not in PROTECTED_EMAILS:
            reviews_to_delete.append(r)

    print(f"[Cleanup] Found {len(users_to_delete)} test users and {len(reviews_to_delete)} test reviews to delete.")

    # Safety check
    for u in users_to_delete:
        if u.get("email", "").strip().lower() in PROTECTED_EMAILS:
            raise RuntimeError(f"ABORT: Protected email {u['email']} found in deletion list!")

    # 1. Delete reviews from Supabase first
    deleted_revs_count = 0
    for r in reviews_to_delete:
        rid = r["id"]
        res = requests.delete(f"{sb_url}/rest/v1/reviews?id=eq.{rid}", headers=headers)
        if res.status_code in (200, 204):
            deleted_revs_count += 1
        else:
            print(f"[Warning] Failed to delete review {rid} from Supabase: {res.status_code} {res.text}")

    # 2. Delete users from Supabase
    deleted_users_count = 0
    for u in users_to_delete:
        uid = u["id"]
        res = requests.delete(f"{sb_url}/rest/v1/users?id=eq.{uid}", headers=headers)
        if res.status_code in (200, 204):
            deleted_users_count += 1
        else:
            print(f"[Warning] Failed to delete user {uid} ({u['email']}) from Supabase: {res.status_code} {res.text}")

    # 3. Clean SQLite test records as well
    conn = auth_db.get_db_connection()
    try:
        cur = conn.cursor()
        for r in reviews_to_delete:
            cur.execute("DELETE FROM reviews WHERE id = ? OR user_email = ?", (r["id"], r.get("user_email")))
        for u in users_to_delete:
            cur.execute("DELETE FROM users WHERE id = ? OR email = ?", (u["id"], u.get("email")))
        conn.commit()
    finally:
        conn.close()

    print(f"[Cleanup] Deleted {deleted_users_count} test users and {deleted_revs_count} test reviews.")

    # 4. Verify post-cleanup state in Supabase
    rem_users_res = requests.get(f"{sb_url}/rest/v1/users?select=id,email,clips_count,has_reviewed", headers=headers)
    rem_users = rem_users_res.json() if rem_users_res.status_code == 200 else []

    rem_revs_res = requests.get(f"{sb_url}/rest/v1/reviews?select=id,user_email,rating,review_text", headers=headers)
    rem_revs = rem_revs_res.json() if rem_revs_res.status_code == 200 else []

    print(f"[Verification] Remaining Supabase users ({len(rem_users)}):")
    for u in rem_users:
        print(f"  User #{u['id']}: {u['email']} (clips: {u['clips_count']})")

    print(f"[Verification] Remaining Supabase reviews ({len(rem_revs)}):")
    for r in rem_revs:
        print(f"  Review #{r['id']}: {r['user_email']} - {r['review_text']}")

if __name__ == "__main__":
    backup_file, users, reviews = run_backup()
    run_cleanup(users, reviews)
