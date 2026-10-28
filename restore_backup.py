import os
import json
import glob
import requests
import auth_db
import supabase_db

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "data", "backups")

def restore_latest_backup():
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_full_*.json")), reverse=True)
    if not files:
        print("[Restore] No backup files found in data/backups/")
        return False

    latest = files[0]
    print(f"[Restore] Restoring from latest backup: {latest}")

    with open(latest, "r", encoding="utf-8") as f:
        data = json.load(f)

    sb_users = data.get("supabase_users", [])
    sb_reviews = data.get("supabase_reviews", [])

    headers = supabase_db._get_headers()
    sb_url = supabase_db.get_supabase_url()

    # Restore users to Supabase
    user_inserted = 0
    for u in sb_users:
        res = requests.post(f"{sb_url}/rest/v1/users", headers=headers, json=u)
        if res.status_code in (200, 201):
            user_inserted += 1

    # Restore reviews to Supabase
    rev_inserted = 0
    for r in sb_reviews:
        res = requests.post(f"{sb_url}/rest/v1/reviews", headers=headers, json=r)
        if res.status_code in (200, 201):
            rev_inserted += 1

    print(f"[Restore] Successfully restored {user_inserted} users and {rev_inserted} reviews to Supabase.")
    return True

if __name__ == "__main__":
    restore_latest_backup()
