import os
import shutil
import tempfile
import uuid
import subprocess
import zipfile
import json
import time
import asyncio
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from faster_whisper import WhisperModel

from clipper import analyze_viral_clips
from video_utils import trim_video_clip, is_ffmpeg_available, extract_audio_fast, burn_full_video_captions
from full_captions import process_full_video_captions
import auth_db
import email_service
import custom_clipper
import re

# Load environment configuration from .env
load_dotenv()

app = FastAPI(title="AI Viral Shorts & Caption Studio (Ultra Fast)")

# Static directory for generated video clips
CLIPS_DIR = os.path.join(os.path.dirname(__file__), "generated_clips")
os.makedirs(CLIPS_DIR, exist_ok=True)

def cleanup_old_generated_clips(max_age_seconds: int = 3600) -> int:
    """
    Prevents server disk exhaustion by purging generated clips, temporary archives,
    and subtitle files older than max_age_seconds (default: 1 hour).
    Safe against active operations; silently skips locked or in-use files.
    """
    now = time.time()
    if not os.path.isdir(CLIPS_DIR):
        return 0
    deleted_count = 0
    try:
        for entry in os.scandir(CLIPS_DIR):
            try:
                if entry.is_file():
                    if (now - entry.stat().st_mtime) > max_age_seconds:
                        os.remove(entry.path)
                        deleted_count += 1
                elif entry.is_dir() and entry.name.startswith("custom_"):
                    if (now - entry.stat().st_mtime) > max_age_seconds:
                        shutil.rmtree(entry.path, ignore_errors=True)
                        deleted_count += 1
            except Exception:
                pass
    except Exception as e:
        print(f"[Disk Cleanup Notice] Error scanning clips dir: {e}")
    return deleted_count

@app.on_event("startup")
async def on_startup():
    """Initializes database and purges stale temporary video files on startup."""
    try:
        auth_db.init_db()
    except Exception as e:
        print(f"[Startup Notice] DB init: {e}")
    cleaned = cleanup_old_generated_clips(max_age_seconds=1800)
    if cleaned > 0:
        print(f"[Disk Cleanup] Purged {cleaned} stale files/directories from generated_clips.")

# Active analysis jobs tracker for graceful per-job cancellation
active_analysis_jobs: Dict[str, Dict[str, Any]] = {}
active_custom_clip_jobs: Dict[str, Dict[str, Any]] = {}

def prune_completed_jobs(jobs_dict: dict, max_keep: int = 150):
    """
    Prevents memory leaks by evicting stale completed/failed/cancelled jobs from memory.
    """
    if len(jobs_dict) <= max_keep:
        return
    stale_keys = [
        k for k, v in list(jobs_dict.items())
        if isinstance(v, dict) and v.get("status") in ("completed", "cancelled", "failed")
    ]
    for k in stale_keys[:max(1, len(stale_keys) // 2)]:
        jobs_dict.pop(k, None)

# Production-ready Secure CORS Configuration
raw_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
if raw_origins:
    cors_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
else:
    cors_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    Applies security headers to defend against clickjacking (X-Frame-Options),
    MIME-type sniffing (X-Content-Type-Options), and cross-site leaks.
    """
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = str(min(4, os.cpu_count() or 4))

# CTranslate2 / Faster-Whisper Model Cache (Runs in INT8 on CPU for 8x speedup)
loaded_models = {}

# Safe in-memory cache for Whisper transcription segments to eliminate redundant CPU re-processing
TRANSCRIPT_CACHE = {}

def compute_file_fingerprint(filepath: str) -> str:
    """Computes instant collision-free fingerprint from file size and boundary blocks."""
    import hashlib
    try:
        size = os.path.getsize(filepath)
        hasher = hashlib.sha256()
        hasher.update(str(size).encode())
        with open(filepath, "rb") as f:
            hasher.update(f.read(131072))
            if size > 131072:
                f.seek(max(0, size - 131072))
                hasher.update(f.read(131072))
        return hasher.hexdigest()[:16]
    except Exception:
        return f"{os.path.basename(filepath)}_{os.path.getsize(filepath) if os.path.exists(filepath) else 0}"

def get_whisper_engine(model_size="tiny"):
    if model_size not in loaded_models:
        print(f"Loading Ultra-Fast CTranslate2 Whisper Engine ('{model_size}' int8)...")
        loaded_models[model_size] = WhisperModel(
            model_size, 
            device="cpu", 
            compute_type="int8",
            cpu_threads=min(4, os.cpu_count() or 4)
        )
        print(f"Engine '{model_size}' is ready.")
    return loaded_models[model_size]


# extract_audio_fast is imported from video_utils above — do not redefine here.



@app.get("/")
def get_index():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI Viral Shorts Studio API is running."}


@app.get("/favicon.ico")
def get_favicon():
    return {}


@app.post("/cancel-analysis")
def cancel_analysis(job_id: Optional[str] = Form(None)):
    """
    Cancels an active video analysis job gracefully without affecting other tasks or the server.
    """
    if job_id:
        if job_id not in active_analysis_jobs:
            active_analysis_jobs[job_id] = {"status": "cancelled", "cancelled": True}
        else:
            active_analysis_jobs[job_id]["cancelled"] = True
            active_analysis_jobs[job_id]["status"] = "cancelled"
        print(f"[AI Studio] Cancellation requested for analysis job: {job_id}")
        return {"status": "cancelled", "job_id": job_id}
    return {"status": "ignored", "job_id": job_id}


@app.get("/api/analysis-status/{job_id}")
def get_analysis_status(job_id: str):
    """
    Returns the live processing status of an analysis job (Modules 1, 2, 3).
    Allows the frontend to poll for long-running jobs without socket timeouts.
    """
    job = active_analysis_jobs.get(job_id)
    if not job:
        return {"status": "unknown", "job_id": job_id}
    return {
        "status": job.get("status", "processing"),
        "stage": job.get("stage", "processing"),
        "progress": job.get("progress", 0),
        "job_id": job_id,
        "result": job.get("result"),
        "error": job.get("error")
    }


REVIEW_THRESHOLD = int(os.getenv("REVIEW_THRESHOLD_CLIPS", "15"))

class SignupPayload(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None

class LoginPayload(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None

class ReviewPayload(BaseModel):
    rating: int = 5
    review_text: str = ""
    auth_token: Optional[str] = None
    email: Optional[str] = None


def verify_generation_access(
    auth_token: Optional[str] = None,
    authorization: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validates user authentication and review requirements before generating clips.
    Enforces strict access control: unauthenticated or expired requests are rejected with HTTP 401.
    Users who have completed 5 or more videos without submitting a review are rejected with HTTP 403.
    """
    token = (auth_token or "").strip()
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
        else:
            token = authorization.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: Please sign in or create an account to process videos."
        )

    user = auth_db.get_user_by_token(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Session expired or invalid login. Please sign in again."
        )

    completed_videos = auth_db.get_completed_videos_for_user(user.get("id"))
    if len(completed_videos) >= 5 and not user.get("has_reviewed", False):
        raise HTTPException(
            status_code=403,
            detail="Review required: You have successfully completed 5 videos! Please submit a quick review to continue creating new clips."
        )
    return user


async def _extract_request_data(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            return await request.json()
        except Exception:
            return {}
    else:
        try:
            form = await request.form()
            return dict(form)
        except Exception:
            return {}


@app.post("/api/auth/signup")
async def auth_signup(request: Request):
    data = await _extract_request_data(request)
    user_email = data.get("email")
    user_password = data.get("password")
    success, msg, user_data = auth_db.signup_user(user_email, user_password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    user_data["videos_count"] = 0
    user_data["completed_videos_count"] = 0
    return {
        "success": True,
        "message": msg,
        "user": user_data,
        "token": user_data["token"],
        "videos_count": 0,
        "completed_videos_count": 0
    }


@app.post("/api/auth/login")
async def auth_login(request: Request):
    data = await _extract_request_data(request)
    user_email = data.get("email")
    user_password = data.get("password")
    success, msg, user_data = auth_db.login_user(user_email, user_password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    completed_videos = auth_db.get_completed_videos_for_user(user_data.get("id"))
    completed_count = len(completed_videos)
    user_data["videos_count"] = completed_count
    user_data["completed_videos_count"] = completed_count
    review_popup_eligible = (completed_count >= 5 and not user_data.get("has_reviewed", False))

    return {
        "success": True,
        "message": msg,
        "user": user_data,
        "token": user_data["token"],
        "review_eligible": review_popup_eligible,
        "review_popup_eligible": review_popup_eligible,
        "completed_videos_count": completed_count,
        "videos_count": completed_count,
        "is_admin": auth_db.is_admin_email(user_email)
    }


@app.get("/api/auth/me")
def auth_me(
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    auth_token = token
    if not auth_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            auth_token = parts[1]
        else:
            auth_token = authorization

    user = auth_db.get_user_by_token(auth_token)
    if not user:
        return {
            "authenticated": False,
            "user": None,
            "is_admin": False,
            "review_eligible": False,
            "review_popup_eligible": False,
            "completed_videos_count": 0,
            "videos_count": 0,
            "review_required": False
        }

    is_admin = auth_db.is_admin_email(user.get("email"))
    completed_videos = auth_db.get_completed_videos_for_user(user.get("id"))
    completed_count = len(completed_videos)
    user["videos_count"] = completed_count
    user["completed_videos_count"] = completed_count
    review_popup_eligible = (completed_count >= 5 and not user.get("has_reviewed", False))

    return {
        "authenticated": True,
        "user": user,
        "is_admin": is_admin,
        "review_eligible": review_popup_eligible,
        "review_popup_eligible": review_popup_eligible,
        "completed_videos_count": completed_count,
        "videos_count": completed_count,
        "review_required": False
    }


@app.get("/api/user-status")
def get_user_status(
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    return auth_me(token=token, authorization=authorization)


@app.post("/api/user/record-video-completed")
def record_video_completed_endpoint(
    payload: dict,
    authorization: Optional[str] = Header(None)
):
    token = None
    if authorization:
        parts = authorization.split()
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else authorization
    user = auth_db.get_user_by_token(token) if token else None
    if not user:
        return {"success": False, "detail": "Unauthenticated"}
    video_key = payload.get("video_key")
    if not video_key:
        return {"success": False, "detail": "Missing video_key"}
    count, is_new = auth_db.record_completed_video_for_user(user["id"], video_key)
    return {
        "success": True,
        "completed_videos_count": count,
        "videos_count": count,
        "is_new": is_new,
        "review_popup_eligible": (count >= 5 and not user.get("has_reviewed", False))
    }


@app.post("/api/auth/logout")
async def auth_logout(
    request: Request,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """
    Securely invalidates the session authentication token in the database upon logout.
    """
    auth_token = token
    if not auth_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            auth_token = parts[1]
        else:
            auth_token = authorization

    if not auth_token:
        try:
            data = await request.json()
            auth_token = data.get("token") or data.get("auth_token")
        except Exception:
            pass

    if auth_token:
        auth_db.logout_user(str(auth_token).strip())

    return {"success": True, "message": "Logged out successfully"}


@app.get("/api/auth/db-status")
def get_db_status():
    """Returns whether the active database is Supabase or local SQLite."""
    import supabase_db
    is_sb = supabase_db.is_configured()
    if is_sb:
        ok, msg = supabase_db.test_connection()
        detail = msg
    else:
        detail = "Using local SQLite database (data/app.db). To switch to Supabase cloud, configure SUPABASE_URL and SUPABASE_KEY in .env."

    return {
        "active_database": "supabase" if is_sb else "sqlite",
        "supabase_configured": is_sb,
        "detail": detail
    }


# =============================================================
# ADMIN PANEL AUTHORIZATION & MANAGEMENT ENDPOINTS
# =============================================================

def verify_admin_user(token: Optional[str] = None, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Verifies that the incoming request is authenticated and belongs to an authorized administrator.
    Rejects unauthorized requests with HTTP 401 or HTTP 403.
    """
    auth_token = token
    if not auth_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            auth_token = parts[1]
        else:
            auth_token = authorization

    if not auth_token or not str(auth_token).strip():
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please sign in as an administrator."
        )

    user = auth_db.get_user_by_token(str(auth_token).strip())
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please sign in again."
        )

    user_email = (user.get("email") or "").strip().lower()
    if not auth_db.is_admin_email(user_email):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: '{user_email}' does not have administrator privileges."
        )

    return user


@app.get("/admin")
@app.get("/admin.html")
def serve_admin():
    """Serves the secure Admin Panel interface."""
    admin_path = os.path.join(os.path.dirname(__file__), "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    raise HTTPException(status_code=404, detail="Admin panel page not found")


@app.get("/api/admin/check")
def admin_check(
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Verifies whether the current user is an authorized administrator."""
    user = verify_admin_user(token=token, authorization=authorization)
    return {
        "is_admin": True,
        "email": user["email"],
        "user_id": user["id"]
    }


@app.get("/api/admin/users")
def admin_get_users(
    q: Optional[str] = None,
    include_test: bool = False,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Lists registered users for authorized administrator, with optional search and test-data filter."""
    verify_admin_user(token=token, authorization=authorization)
    all_users = auth_db.get_all_users(include_test=include_test)

    # Filter by email if search query provided
    if q and q.strip():
        search_term = q.strip().lower()
        all_users = [u for u in all_users if search_term in (u.get("email") or "").lower()]

    return {
        "success": True,
        "users": all_users,
        "total": len(all_users)
    }


@app.get("/api/admin/reviews")
def admin_get_reviews(
    q: Optional[str] = None,
    filter_status: Optional[str] = None,
    include_test: bool = False,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Lists genuine user reviews with read/unread status and optional search/status filter."""
    verify_admin_user(token=token, authorization=authorization)
    reviews = auth_db.get_all_reviews(include_test=include_test)

    # Search filter by email or review text
    if q and q.strip():
        search_term = q.strip().lower()
        reviews = [
            r for r in reviews
            if search_term in (r.get("user_email") or "").lower()
            or search_term in (r.get("review_text") or "").lower()
        ]

    # Status filter: read, unread
    if filter_status and filter_status.strip().lower() in ("read", "unread"):
        target_read = (filter_status.strip().lower() == "read")
        reviews = [r for r in reviews if bool(r.get("is_read")) == target_read]

    return {
        "success": True,
        "reviews": reviews,
        "total": len(reviews)
    }


@app.post("/api/admin/reviews/{review_id}/read")
async def admin_set_review_read(
    review_id: int,
    request: Request,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Marks a review as read or unread."""
    verify_admin_user(token=token, authorization=authorization)
    data = await _extract_request_data(request)
    is_read = data.get("is_read", True)
    if isinstance(is_read, str):
        is_read = is_read.lower() in ("true", "1", "yes")

    success = auth_db.set_review_read_status(review_id, bool(is_read))
    return {
        "success": success,
        "review_id": review_id,
        "is_read": bool(is_read)
    }



@app.post("/api/submit-review")
async def submit_review_endpoint(request: Request, authorization: Optional[str] = Header(None)):
    data = await _extract_request_data(request)
    r_rating = int(data.get("rating") or 5)
    r_text = (data.get("review_text") or "").strip()
    r_token = data.get("auth_token")
    if not r_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            r_token = parts[1]
        else:
            r_token = authorization

    if not r_text:
        raise HTTPException(status_code=400, detail="Please write a few words in your review.")

    user = auth_db.get_user_by_token(r_token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required to submit a review. Please sign in.")

    owner_email = email_service.get_owner_email()
    user_id = user["id"]
    user_email = user["email"]
    clips_count = user["clips_count"]

    # Mark user reviewed in DB so they are unblocked
    auth_db.save_user_review(user_id, user_email, r_rating, r_text, owner_email)

    # Deliver directly to owner email via SMTP / logging
    email_result = email_service.send_review_email_to_owner(
        user_email=user_email,
        rating=r_rating,
        review_text=r_text,
        clips_count=clips_count
    )

    return {
        "success": True,
        "message": f"Review submitted and sent to {owner_email}! You can now generate further clips.",
        "has_reviewed": True,
        "email_delivery": email_result.get("status")
    }



@app.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    speed_mode: str = Form("tiny"),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """Ultra-fast word-level caption generation."""
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)
    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = temp_file.name
        try:
            shutil.copyfileobj(file.file, temp_file)
        finally:
            file.file.close()

    audio_temp = temp_path + ".wav"
    try:
        proc_path = extract_audio_fast(temp_path, audio_temp)
        model_name = speed_mode if speed_mode in ["tiny", "base"] else "tiny"
        engine = get_whisper_engine(model_name)
        
        print(f"\n[AI Studio] Transcribing '{file.filename}' with {model_name} (INT8)...")
        segments_generator, info = engine.transcribe(
            proc_path,
            word_timestamps=True,
            beam_size=1,
            vad_filter=True
        )
        
        words = []
        for segment in segments_generator:
            print(f" -> [{segment.start:.1f}s - {segment.end:.1f}s]: {segment.text}")
            seg_words = []
            if segment.words:
                for w in segment.words:
                    clean_w = w.word.strip()
                    if clean_w:
                        seg_words.append({
                            "word": clean_w,
                            "start": round(w.start, 3),
                            "end": round(w.end, 3)
                        })
            if not seg_words and segment.text.strip():
                text_words = segment.text.strip().split()
                if text_words:
                    seg_dur = max(0.1, segment.end - segment.start)
                    w_dur = seg_dur / len(text_words)
                    for i, tw in enumerate(text_words):
                        seg_words.append({
                            "word": tw.strip(),
                            "start": round(segment.start + i * w_dur, 3),
                            "end": round(segment.start + (i + 1) * w_dur, 3)
                        })
            words.extend(seg_words)

        print(f"[AI Studio] Finished! Extracted {len(words)} words.\n")
        return {"words": words}
    except Exception as e:
        print(f"[Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        if os.path.exists(audio_temp):
            try:
                os.remove(audio_temp)
            except Exception:
                pass


@app.post("/extract-clips")
def extract_clips(
    file: UploadFile = File(...),
    speed_mode: str = Form("tiny"),
    language: str = Form("en"),
    script_mode: str = Form("original"),
    job_id: Optional[str] = Form(None),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """
    Ultra-fast dynamic AI extraction of ALL viral moments from long videos.
    Supports English, Hindi, Urdu, Mixed languages, and Roman Urdu script.
    Includes cooperative per-job cancellation support.
    """
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)

    if job_id:
        is_already_cancelled = active_analysis_jobs.get(job_id, {}).get("cancelled", False)
        active_analysis_jobs[job_id] = {
            "status": "cancelled" if is_already_cancelled else "processing",
            "stage": "uploading",
            "progress": 0,
            "cancelled": is_already_cancelled,
            "result": None,
            "error": None
        }
        if is_already_cancelled:
            raise HTTPException(status_code=499, detail="Analysis cancelled.")

    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = temp_file.name
        try:
            shutil.copyfileobj(file.file, temp_file)
        finally:
            file.file.close()

    audio_temp = temp_path + ".wav"
    try:
        if job_id and active_analysis_jobs.get(job_id, {}).get("cancelled"):
            if job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["status"] = "cancelled"
            raise HTTPException(status_code=499, detail="Analysis cancelled.")

        t_job_start = time.time()
        model_name = speed_mode if speed_mode in ["tiny", "base"] else "tiny"
        
        # Configure Whisper language
        whisper_lang = None
        if language in ["hi", "hindi"]:
            whisper_lang = "hi"
        elif language in ["ur", "urdu"]:
            whisper_lang = "ur"
        elif language in ["en", "english"]:
            whisper_lang = "en"
        # If 'auto' or 'mixed', whisper_lang is None for auto-detection
        
        # Module 2 (Urdu / Hindi) extracts clean clips without captions/subtitles.
        need_word_timestamps = (language not in ["ur", "urdu", "hi", "hindi"])

        # Check in-memory transcript cache to avoid redundant CPU transcription
        file_fingerprint = compute_file_fingerprint(temp_path)
        transcript_cache_key = f"{file_fingerprint}_{model_name}_{whisper_lang}_{need_word_timestamps}"

        if transcript_cache_key in TRANSCRIPT_CACHE:
            segments_list, detected_lang, video_duration = TRANSCRIPT_CACHE[transcript_cache_key]
            print(f"[AI Studio] Reusing cached transcription for '{file.filename}' ({len(segments_list)} segments) - zero CPU transcription delay!")
            if job_id and job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["stage"] = "transcription_cached"
                active_analysis_jobs[job_id]["progress"] = 80
        else:
            if job_id and job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["stage"] = "extracting_audio"
                active_analysis_jobs[job_id]["progress"] = 2
            proc_path = extract_audio_fast(temp_path, audio_temp)
            t_audio_done = time.time()
            print(f"[AI Studio] Audio extracted in {t_audio_done - t_job_start:.1f}s")

            engine = get_whisper_engine(model_name)
            print(f"\n[AI Studio] Scanning & Slicing viral moments for '{file.filename}' ({model_name} INT8, lang={whisper_lang or 'auto'}, word_timestamps={need_word_timestamps})...")
            if job_id and job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["stage"] = "transcribing"
                active_analysis_jobs[job_id]["progress"] = 5
            t_transcribe_start = time.time()
            # For English (Module 1), use vad_filter=False (matching proven Module 3 pipeline)
            # so Silero VAD does not silence speech during background music, intro sound, or quiet dialogue.
            use_vad = (whisper_lang in ["ur", "urdu", "hi", "hindi"])
            segments_generator, info = engine.transcribe(
                proc_path,
                language=whisper_lang,
                word_timestamps=need_word_timestamps,
                beam_size=1,
                vad_filter=use_vad,
                condition_on_previous_text=False
            )
            video_duration = getattr(info, "duration", 0) or 0
            detected_lang = getattr(info, "language", whisper_lang or "en")
            
            segments_list = []
            for segment in segments_generator:
                if job_id and active_analysis_jobs.get(job_id, {}).get("cancelled"):
                    print(f"[AI Studio] Analysis job '{job_id}' cancelled during transcription.")
                    if job_id in active_analysis_jobs:
                        active_analysis_jobs[job_id]["status"] = "cancelled"
                    raise HTTPException(status_code=499, detail="Analysis cancelled.")

                # Update transcription progress so the status endpoint shows a live %
                if job_id and job_id in active_analysis_jobs and video_duration > 0:
                    pct = min(80, 5 + int((segment.end / video_duration) * 75))
                    active_analysis_jobs[job_id]["progress"] = pct

                print(f" -> [{segment.start:.1f}s - {segment.end:.1f}s]: {segment.text}")
                seg_words = []
                if segment.words:
                    for w in segment.words:
                        clean_w = w.word.strip()
                        if clean_w:
                            seg_words.append({
                                "word": clean_w,
                                "start": round(w.start, 3),
                                "end": round(w.end, 3)
                            })
                if not seg_words and segment.text.strip():
                    text_words = segment.text.strip().split()
                    if text_words:
                        seg_dur = max(0.1, segment.end - segment.start)
                        w_dur = seg_dur / len(text_words)
                        for i, tw in enumerate(text_words):
                            seg_words.append({
                                "word": tw.strip(),
                                "start": round(segment.start + i * w_dur, 3),
                                "end": round(segment.start + (i + 1) * w_dur, 3)
                            })
                segments_list.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": seg_words
                })
            
            t_transcribe_done = time.time()
            print(f"[AI Studio] Transcription complete: {len(segments_list)} segments in {t_transcribe_done - t_transcribe_start:.1f}s")
            # Store in cache
            TRANSCRIPT_CACHE[transcript_cache_key] = (segments_list, detected_lang, video_duration)

        if job_id and active_analysis_jobs.get(job_id, {}).get("cancelled"):
            if job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["status"] = "cancelled"
            raise HTTPException(status_code=499, detail="Analysis cancelled.")

        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["stage"] = "analyzing"
            active_analysis_jobs[job_id]["progress"] = 82

        def on_gemini_progress(chunk_idx, total_chunks):
            if job_id and job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["stage"] = f"analyzing_chunk_{chunk_idx}_of_{total_chunks}"
                pct = min(98, 80 + int((chunk_idx / total_chunks) * 18))
                active_analysis_jobs[job_id]["progress"] = pct

        t_clip_start = time.time()
        viral_clips = analyze_viral_clips(
            segments_list,
            language=language,
            script_mode=script_mode,
            progress_callback=on_gemini_progress
        )
        t_clip_done = time.time()
        print(f"[AI Studio] Clip analysis complete in {t_clip_done - t_clip_start:.1f}s — {len(viral_clips)} viral moments found")
        print(f"[AI Studio] Total job time: {t_clip_done - t_job_start:.1f}s\n")

        user_clips_count = None
        completed_videos_count = 0
        review_popup_eligible = False
        if user:
            added = max(1, len(viral_clips))
            user_clips_count = auth_db.increment_user_clips(user["id"], added)
            if len(viral_clips) > 0:
                file_size = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
                video_key = f"{file.filename}_{file_size}"
                count, is_new = auth_db.record_completed_video_for_user(user["id"], video_key)
                completed_videos_count = count
                review_popup_eligible = (count >= 5 and not user.get("has_reviewed", False))
            else:
                completed_videos = auth_db.get_completed_videos_for_user(user["id"])
                completed_videos_count = len(completed_videos)
                review_popup_eligible = (completed_videos_count >= 5 and not user.get("has_reviewed", False))

        final_result = {
            "total_segments": len(segments_list),
            "detected_language": detected_lang,
            "clips": viral_clips,
            "clips_count": user_clips_count,
            "completed_videos_count": completed_videos_count,
            "videos_count": completed_videos_count,
            "review_popup_eligible": review_popup_eligible,
            "review_threshold": REVIEW_THRESHOLD,
            "has_reviewed": user["has_reviewed"] if user else False
        }
        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "completed"
            active_analysis_jobs[job_id]["result"] = final_result
        return final_result
    except HTTPException as he:
        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "cancelled" if he.status_code == 499 else "failed"
            active_analysis_jobs[job_id]["error"] = str(he.detail)
        raise
    except Exception as e:
        print(f"[Error] {e}")
        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "failed"
            active_analysis_jobs[job_id]["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        if os.path.exists(audio_temp):
            try:
                os.remove(audio_temp)
            except Exception:
                pass


@app.post("/slice-clip")
def slice_clip(
    file: UploadFile = File(...),
    start_time: float = Form(...),
    duration: float = Form(...),
    aspect_ratio: str = Form("9:16"),
    fit_mode: str = Form("fit"),
    pad_color: str = Form("black"),
    words_json: str = Form(None),
    style_json: str = Form(None),
    overlay_json: Optional[str] = Form(None),
    burn_captions: bool = Form(True),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)
    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_in:
        temp_in_path = temp_in.name
        try:
            shutil.copyfileobj(file.file, temp_in)
        finally:
            file.file.close()

    prefix = "clip" if burn_captions else "clean_clip"
    out_filename = f"{prefix}_{uuid.uuid4().hex[:8]}.mp4"
    out_path = os.path.join(CLIPS_DIR, out_filename)

    try:
        words = json.loads(words_json) if (words_json and burn_captions) else None
        style_opt = json.loads(style_json) if style_json else {}
        if overlay_json:
            try:
                style_opt["overlay"] = json.loads(overlay_json)
            except Exception:
                pass

        print(f"[Slice Request] start={start_time}, dur={duration}, fit={fit_mode}, pad={pad_color}, burn_captions={burn_captions}, words_count={len(words) if words else 0}")

        trim_video_clip(
            input_path=temp_in_path,
            output_path=out_path,
            start_time=start_time,
            duration=duration,
            aspect_ratio=aspect_ratio,
            fit_mode=fit_mode,
            pad_color=pad_color,
            words=words,
            style_options=style_opt,
            burn_captions=burn_captions
        )
        return FileResponse(out_path, media_type="video/mp4", filename=out_filename)
    except Exception as e:
        print(f"[Slice Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_in_path):
            try:
                os.remove(temp_in_path)
            except Exception:
                pass


@app.post("/batch-slice-clips")
def batch_slice_clips(
    file: UploadFile = File(...),
    clips_json: str = Form(...),
    aspect_ratio: str = Form("9:16"),
    fit_mode: str = Form("fit"),
    pad_color: str = Form("black"),
    style_json: str = Form(None),
    burn_captions: bool = Form(True),
    auth_token: Optional[str] = Form(None),
    overlay_json: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """
    Slices all detected viral clips (captioned or clean) and bundles into a ZIP file.
    """
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)
    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_in:
        temp_in_path = temp_in.name
        try:
            shutil.copyfileobj(file.file, temp_in)
        finally:
            file.file.close()

    temp_batch_dir = tempfile.mkdtemp()
    zip_type = "All_Viral_Shorts" if burn_captions else "All_Clean_Shorts"
    zip_filename = f"{zip_type}_{uuid.uuid4().hex[:6]}.zip"
    zip_path = os.path.join(CLIPS_DIR, zip_filename)

    try:
        clips_data = json.loads(clips_json)
        style_opt = json.loads(style_json) if style_json else {}
        if overlay_json:
            try:
                style_opt["overlay"] = json.loads(overlay_json)
            except Exception:
                pass
        
        mode_label = "with burned-in captions" if burn_captions else "clean (without captions)"
        print(f"\n[Batch Export] Slicing {len(clips_data)} viral clips {mode_label} into ZIP...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for idx, c in enumerate(clips_data):
                clean_title = "".join(ch if ch.isalnum() else "_" for ch in c.get('title', f"Clip_{idx+1}")[:25])
                prefix = "Short" if burn_captions else "Clean_Short"
                clip_name = f"{prefix}_{c.get('id', idx+1)}_{clean_title}.mp4"
                clip_file_path = os.path.join(temp_batch_dir, clip_name)
                
                print(f" -> Exporting {idx+1}/{len(clips_data)}: {clip_name}...")
                clip_style_opt = dict(style_opt)
                if "overlay" in c:
                    if c["overlay"]:
                        clip_style_opt["overlay"] = c["overlay"]
                    else:
                        clip_style_opt.pop("overlay", None)
                elif "overlays" in c:
                    if c["overlays"]:
                        clip_style_opt["overlay"] = c["overlays"]
                    else:
                        clip_style_opt.pop("overlay", None)

                trim_video_clip(
                    input_path=temp_in_path,
                    output_path=clip_file_path,
                    start_time=c["start"],
                    duration=c["duration"],
                    aspect_ratio=aspect_ratio,
                    fit_mode=fit_mode,
                    pad_color=pad_color,
                    words=c.get("words") if burn_captions else None,
                    style_options=clip_style_opt,
                    burn_captions=burn_captions
                )
                if os.path.exists(clip_file_path):
                    zipf.write(clip_file_path, arcname=clip_name)

        print(f"[Batch Export] Finished ZIP packaging!\n")
        return FileResponse(zip_path, media_type="application/zip", filename=f"{zip_type}.zip")
    except Exception as e:
        print(f"[Batch Export Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_in_path):
            try:
                os.remove(temp_in_path)
            except Exception:
                pass
        shutil.rmtree(temp_batch_dir, ignore_errors=True)


@app.post("/full-captions")
def full_video_captions(
    file: UploadFile = File(...),
    speed_mode: str = Form("tiny"),
    language: str = Form("en"),
    script_mode: str = Form("original"),
    job_id: Optional[str] = Form(None),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """
    Dedicated endpoint for Module 3: Full English Video Captions.
    Generates word and sentence timestamps for the full video duration without ANY clipping or viral scoring.
    Includes cooperative per-job cancellation support.
    """
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)

    if job_id:
        active_analysis_jobs[job_id] = {"status": "processing", "cancelled": False, "result": None, "error": None}

    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = temp_file.name
        try:
            shutil.copyfileobj(file.file, temp_file)
        finally:
            file.file.close()

    try:
        if job_id and active_analysis_jobs.get(job_id, {}).get("cancelled"):
            if job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["status"] = "cancelled"
            raise HTTPException(status_code=499, detail="Analysis cancelled.")

        model_name = speed_mode if speed_mode in ["tiny", "base"] else "tiny"
        engine = get_whisper_engine(model_name)
        result = process_full_video_captions(
            video_path=temp_path,
            whisper_engine=engine,
            language=language or "en",
            script_mode=script_mode,
            cancel_check=lambda: bool(job_id and active_analysis_jobs.get(job_id, {}).get("cancelled"))
        )
        if user:
            new_count = auth_db.increment_user_clips(user["id"], 1)
            result["clips_count"] = new_count
            result["review_threshold"] = REVIEW_THRESHOLD
            result["has_reviewed"] = user["has_reviewed"]
            if result.get("speech_detected", False) and result.get("total_segments", 0) > 0:
                file_size = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
                video_key = f"{file.filename}_{file_size}"
                count, is_new = auth_db.record_completed_video_for_user(user["id"], video_key)
                result["completed_videos_count"] = count
                result["videos_count"] = count
                result["review_popup_eligible"] = (count >= 5 and not user.get("has_reviewed", False))
            else:
                completed_videos = auth_db.get_completed_videos_for_user(user["id"])
                result["completed_videos_count"] = len(completed_videos)
                result["videos_count"] = len(completed_videos)
                result["review_popup_eligible"] = (len(completed_videos) >= 5 and not user.get("has_reviewed", False))

        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "completed"
            active_analysis_jobs[job_id]["result"] = result
        return result
    except HTTPException as he:
        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "cancelled" if he.status_code == 499 else "failed"
            active_analysis_jobs[job_id]["error"] = str(he.detail)
        raise
    except RuntimeError as re:
        if "Analysis cancelled" in str(re):
            if job_id and job_id in active_analysis_jobs:
                active_analysis_jobs[job_id]["status"] = "cancelled"
            raise HTTPException(status_code=499, detail="Analysis cancelled.")
        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "failed"
            active_analysis_jobs[job_id]["error"] = str(re)
        raise HTTPException(status_code=500, detail=str(re))
    except Exception as e:
        print(f"[Full Captions Error] {e}")
        if job_id and job_id in active_analysis_jobs:
            active_analysis_jobs[job_id]["status"] = "failed"
            active_analysis_jobs[job_id]["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.post("/burn-full-video-captions")
def burn_full_video_captions_endpoint(
    file: UploadFile = File(...),
    words_json: str = Form(...),
    style_json: str = Form(None),
    overlay_json: Optional[str] = Form(None),
    aspect_ratio: str = Form("original"),
    fit_mode: str = Form("fit"),
    pad_color: str = Form("black"),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """
    Module 3 dedicated endpoint: Burns synchronized English captions into the complete, full-length video.
    Covers the entire duration with original audio preserved.
    """
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)
    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_in:
        temp_in_path = temp_in.name
        try:
            shutil.copyfileobj(file.file, temp_in)
        finally:
            file.file.close()

    out_filename = f"full_captioned_{uuid.uuid4().hex[:8]}.mp4"
    out_path = os.path.join(CLIPS_DIR, out_filename)

    try:
        words = json.loads(words_json) if words_json else []
        style_opt = json.loads(style_json) if style_json else {}
        if overlay_json:
            try:
                style_opt["overlay"] = json.loads(overlay_json)
            except Exception:
                pass

        print(f"[Burn Full Captions Request] words={len(words)}, ratio={aspect_ratio}, fit={fit_mode}")
        burn_full_video_captions(
            input_path=temp_in_path,
            output_path=out_path,
            words=words,
            style_options=style_opt,
            aspect_ratio=aspect_ratio,
            fit_mode=fit_mode,
            pad_color=pad_color
        )
        return FileResponse(out_path, media_type="video/mp4", filename=out_filename)
    except Exception as e:
        print(f"[Burn Full Captions Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_in_path):
            try:
                os.remove(temp_in_path)
            except Exception:
                pass


@app.post("/download-caption-file")
async def download_caption_file(
    content: str = Form(...),
    file_format: str = Form("srt"),
    filename: str = Form("subtitles"),
    background_tasks: BackgroundTasks = None
):
    """
    Returns text subtitle content as a downloadable file (.srt, .vtt, or .txt).
    """
    ext = file_format.lower().strip(".")
    if ext not in ["srt", "vtt", "txt"]:
        ext = "srt"
    
    clean_base = "".join(c if c.isalnum() or c in "-_" else "_" for c in filename)[:30] or "subtitles"
    out_filename = f"{clean_base}.{ext}"
    out_path = os.path.join(CLIPS_DIR, f"temp_{uuid.uuid4().hex[:6]}_{out_filename}")
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    media_type = "text/vtt" if ext == "vtt" else "text/plain"
    if background_tasks:
        background_tasks.add_task(os.remove, out_path)
    return FileResponse(out_path, media_type=media_type, filename=out_filename)


# =====================================================================
# Dedicated Endpoints for Module 4: Custom Video Clipping
# (Completely independent of smart-clipping AI / Whisper / Gemini)
# =====================================================================

@app.post("/api/custom-clip/preview-segments")
async def preview_custom_clip_segments(
    total_duration: float = Form(...),
    clip_duration_seconds: float = Form(...)
):
    """
    Lightweight endpoint to calculate and preview custom clip segments
    without processing video.
    """
    if total_duration <= 0:
        raise HTTPException(status_code=400, detail="Invalid video duration.")
    if clip_duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="Requested clip duration must be greater than 0.")

    segments = custom_clipper.calculate_custom_clip_segments(total_duration, clip_duration_seconds)
    return {
        "success": True,
        "total_duration": total_duration,
        "total_duration_formatted": custom_clipper.format_seconds_to_hms(total_duration),
        "clip_duration_seconds": clip_duration_seconds,
        "clip_duration_formatted": custom_clipper.format_seconds_to_hms(clip_duration_seconds),
        "total_clips": len(segments),
        "segments": segments
    }


@app.post("/api/custom-clip/split")
async def split_custom_clips(
    file: UploadFile = File(...),
    clip_duration_seconds: float = Form(...),
    job_id: Optional[str] = Form(None),
    auth_token: Optional[str] = Form(None),
    overlay_json: Optional[str] = Form(None),
    aspect_ratio: str = Form("original"),
    fit_mode: str = Form("fit"),
    pad_color: str = Form("black"),
    authorization: Optional[str] = Header(None)
):
    """
    Module 4 Dedicated Endpoint: Instantly calculates clip boundaries (<0.1s)
    without upfront CPU re-encoding lag. Slicing and rendering are performed on-demand
    when individual clips or ZIP archives are exported.
    """
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)

    if not job_id:
        job_id = f"custom_{uuid.uuid4().hex[:8]}"

    active_custom_clip_jobs[job_id] = {
        "status": "processing",
        "cancelled": False,
        "progress": 0,
        "current_clip": 0,
        "total_clips": 0,
        "result": None,
        "error": None
    }

    if clip_duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="Requested clip duration must be greater than 0 seconds.")

    job_output_dir = os.path.join(CLIPS_DIR, f"custom_{job_id}")
    os.makedirs(job_output_dir, exist_ok=True)

    suffix = os.path.splitext(file.filename)[1] or ".mp4"
    source_video_path = os.path.join(job_output_dir, f"source{suffix}")

    try:
        with open(source_video_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)
    except Exception as e:
        if os.path.exists(source_video_path):
            os.remove(source_video_path)
        raise HTTPException(status_code=500, detail=f"Failed to receive video: {e}")

    try:
        # Measure source video duration
        loop = asyncio.get_event_loop()
        total_duration = await loop.run_in_executor(
            None,
            lambda: custom_clipper.get_video_duration(source_video_path)
        )

        segments = custom_clipper.calculate_custom_clip_segments(total_duration, clip_duration_seconds)
        if not segments:
            raise ValueError("Video duration is too short to generate clips with requested duration.")

        pad_digits = max(2, len(str(len(segments))))
        client_clips = []
        user_tok = (user.get("token") if user else "") or (auth_token or "")
        tok_param = f"?token={user_tok}" if user_tok else ""
        for seg in segments:
            idx = seg["index"]
            clip_fn = f"clip_{idx:0{pad_digits}d}.mp4"
            seg["filename"] = clip_fn
            client_clips.append({
                "index": idx,
                "title": f"Clip {idx} ({seg['start_formatted']} - {seg['end_formatted']})",
                "filename": clip_fn,
                "start": seg["start"],
                "end": seg["end"],
                "duration": seg["duration"],
                "start_formatted": seg["start_formatted"],
                "end_formatted": seg["end_formatted"],
                "duration_formatted": seg["duration_formatted"],
                "download_url": f"/api/custom-clip/download/{job_id}/{clip_fn}{tok_param}"
            })

        # Save metadata for on-demand rendering and IDOR security
        user_tok = user.get("token") if user else ""
        meta_data = {
            "job_id": job_id,
            "user_id": user.get("id") if user else None,
            "user_email": user.get("email") if user else None,
            "filename": file.filename,
            "source_video": source_video_path,
            "total_duration": total_duration,
            "clip_duration_seconds": clip_duration_seconds,
            "aspect_ratio": aspect_ratio,
            "fit_mode": fit_mode,
            "pad_color": pad_color,
            "segments": segments
        }
        meta_path = os.path.join(job_output_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f_meta:
            json.dump(meta_data, f_meta, indent=2)

        # Update clips count for logged-in user
        user_clips_count = None
        user_has_reviewed = False
        completed_videos_count = 0
        review_popup_eligible = False
        if user:
            added = max(1, len(client_clips))
            user_clips_count = auth_db.increment_user_clips(user["id"], added)
            user_has_reviewed = bool(user.get("has_reviewed", False))
            if len(client_clips) > 0:
                file_size = os.path.getsize(source_video_path) if os.path.exists(source_video_path) else 0
                video_key = f"{file.filename}_{file_size}"
                count, is_new = auth_db.record_completed_video_for_user(user["id"], video_key)
                completed_videos_count = count
                review_popup_eligible = (count >= 5 and not user_has_reviewed)
            else:
                completed_videos = auth_db.get_completed_videos_for_user(user["id"])
                completed_videos_count = len(completed_videos)
                review_popup_eligible = (completed_videos_count >= 5 and not user_has_reviewed)

        orig_clean_name = os.path.splitext(os.path.basename(file.filename))[0]

        res_data = {
            "success": True,
            "job_id": job_id,
            "filename": file.filename,
            "original_name": orig_clean_name,
            "total_clips": len(client_clips),
            "clip_duration_requested": clip_duration_seconds,
            "clips": client_clips,
            "zip_download_url": f"/api/custom-clip/download-zip/{job_id}{tok_param}",
            "clips_count": user_clips_count,
            "completed_videos_count": completed_videos_count,
            "videos_count": completed_videos_count,
            "review_popup_eligible": review_popup_eligible,
            "has_reviewed": user_has_reviewed
        }

        if job_id in active_custom_clip_jobs:
            active_custom_clip_jobs[job_id]["status"] = "completed"
            active_custom_clip_jobs[job_id]["progress"] = 100
            active_custom_clip_jobs[job_id]["current_clip"] = len(client_clips)
            active_custom_clip_jobs[job_id]["total_clips"] = len(client_clips)
            active_custom_clip_jobs[job_id]["result"] = res_data

        return res_data

    except Exception as e:
        if active_custom_clip_jobs.get(job_id, {}).get("cancelled", False):
            if job_id in active_custom_clip_jobs:
                active_custom_clip_jobs[job_id]["status"] = "cancelled"
            raise HTTPException(status_code=499, detail="Custom clipping cancelled by user.")
        if job_id in active_custom_clip_jobs:
            active_custom_clip_jobs[job_id]["status"] = "failed"
            active_custom_clip_jobs[job_id]["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/custom-clip/download/{job_id}/{filename}")
async def download_custom_clip(
    job_id: str,
    filename: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """
    Downloads an individual generated clip file.
    Renders on-demand if not pre-rendered.
    Verifies authentication and ownership to prevent IDOR vulnerabilities.
    """
    clean_job = re.sub(r"[^a-zA-Z0-9_\-]", "", job_id)
    clean_fn = re.sub(r"[^a-zA-Z0-9_\-\.]", "", filename)
    job_output_dir = os.path.join(CLIPS_DIR, f"custom_{clean_job}")
    file_path = os.path.join(job_output_dir, clean_fn)

    # Validate job ownership
    meta_path = os.path.join(job_output_dir, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f_meta:
                meta = json.load(f_meta)
            expected_user_id = meta.get("user_id")
            if expected_user_id:
                auth_user = verify_generation_access(auth_token=token, authorization=authorization)
                if auth_user.get("id") != expected_user_id and not auth_db.is_admin_email(auth_user.get("email")):
                    raise HTTPException(status_code=403, detail="Access denied: You do not have permission to access this clip.")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[Custom Clip Auth Notice] {e}")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 500:
        media_type = "application/zip" if clean_fn.endswith(".zip") else "video/mp4"
        return FileResponse(file_path, media_type=media_type, filename=clean_fn)

    # Check on-demand metadata
    meta_path = os.path.join(job_output_dir, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f_meta:
                meta = json.load(f_meta)
            source_video = meta.get("source_video")
            seg = next((s for s in meta.get("segments", []) if s.get("filename") == clean_fn), None)
            if seg and source_video and os.path.exists(source_video):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: custom_clipper.render_single_custom_clip(
                        source_video_path=source_video,
                        output_path=file_path,
                        start_time=seg["start"],
                        duration=seg["duration"],
                        aspect_ratio=meta.get("aspect_ratio", "original"),
                        fit_mode=meta.get("fit_mode", "fit"),
                        pad_color=meta.get("pad_color", "black"),
                        overlays=None
                    )
                )
                if os.path.exists(file_path):
                    return FileResponse(file_path, media_type="video/mp4", filename=clean_fn)
        except Exception as e:
            print(f"[Custom Clip] On-demand render error for {clean_fn}: {e}")

    raise HTTPException(status_code=404, detail="Clip file not found or expired.")


@app.get("/api/custom-clip/download-zip/{job_id}")
async def download_custom_clips_zip(
    job_id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """
    Downloads all clips for the given job as a single ZIP archive.
    Renders on-demand if not pre-rendered.
    Verifies authentication and ownership to prevent IDOR vulnerabilities.
    """
    clean_job = re.sub(r"[^a-zA-Z0-9_\-]", "", job_id)
    job_output_dir = os.path.join(CLIPS_DIR, f"custom_{clean_job}")
    zip_path = os.path.join(job_output_dir, "all_clips.zip")

    # Validate job ownership
    meta_path = os.path.join(job_output_dir, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f_meta:
                meta = json.load(f_meta)
            expected_user_id = meta.get("user_id")
            if expected_user_id:
                auth_user = verify_generation_access(auth_token=token, authorization=authorization)
                if auth_user.get("id") != expected_user_id and not auth_db.is_admin_email(auth_user.get("email")):
                    raise HTTPException(status_code=403, detail="Access denied: You do not have permission to access this ZIP archive.")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[Custom Clip Zip Auth Notice] {e}")

    if os.path.exists(zip_path) and os.path.getsize(zip_path) > 500:
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"clips_{clean_job}.zip"
        )

    meta_path = os.path.join(job_output_dir, "metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f_meta:
                meta = json.load(f_meta)
            source_video = meta.get("source_video")
            segments = meta.get("segments", [])
            if source_video and os.path.exists(source_video) and segments:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: custom_clipper.render_batch_custom_clips(
                        source_video_path=source_video,
                        segments=segments,
                        output_dir=job_output_dir,
                        clips_overlays_map={},
                        zip_output_path=zip_path,
                        aspect_ratio=meta.get("aspect_ratio", "original"),
                        fit_mode=meta.get("fit_mode", "fit"),
                        pad_color=meta.get("pad_color", "black")
                    )
                )
                if os.path.exists(zip_path):
                    return FileResponse(
                        zip_path,
                        media_type="application/zip",
                        filename=f"clips_{clean_job}.zip"
                    )
        except Exception as e:
            print(f"[Custom Clip] On-demand ZIP render error: {e}")

    raise HTTPException(status_code=404, detail="ZIP archive not found or expired.")


@app.post("/api/custom-clip/cancel")
async def cancel_custom_clip(job_id: str = Form(...)):
    """
    Cancels an ongoing custom clipping job.
    """
    if job_id in active_custom_clip_jobs:
        active_custom_clip_jobs[job_id]["cancelled"] = True
    return {"success": True, "message": f"Cancellation requested for {job_id}"}


@app.get("/api/custom-clip/status/{job_id}")
def get_custom_clip_status(job_id: str):
    """
    Returns live progress for Module 4 custom clipping jobs.
    Allows frontend to poll continuously without socket timeouts.
    """
    job = active_custom_clip_jobs.get(job_id)
    if not job:
        return {"status": "unknown", "job_id": job_id}
    return {
        "status": job.get("status", "processing"),
        "progress": job.get("progress", 0),
        "current_clip": job.get("current_clip", 0),
        "total_clips": job.get("total_clips", 0),
        "job_id": job_id,
        "result": job.get("result"),
        "error": job.get("error")
    }


@app.post("/api/custom-clip/render-clip")
async def render_custom_clip_endpoint(
    job_id: str = Form(...),
    filename: str = Form(...),
    overlays_json: Optional[str] = Form(None),
    aspect_ratio: Optional[str] = Form(None),
    fit_mode: Optional[str] = Form(None),
    pad_color: Optional[str] = Form(None),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """
    Renders text overlays and framing onto an individual clip on demand.
    Returns the edited clip file response, or the clean clip if no overlays.
    """
    clean_job = re.sub(r"[^a-zA-Z0-9_\-]", "", job_id)
    clean_fn = re.sub(r"[^a-zA-Z0-9_\-\.]", "", filename)
    job_output_dir = os.path.join(CLIPS_DIR, f"custom_{clean_job}")

    overlays = []
    if overlays_json:
        try:
            parsed = json.loads(overlays_json)
            if isinstance(parsed, list):
                overlays = parsed
            elif isinstance(parsed, dict):
                overlays = [parsed]
        except Exception:
            pass

    user = verify_generation_access(auth_token=auth_token, authorization=authorization)
    auth_db.increment_user_clips(user['id'], 1)

    has_text = any(isinstance(o, dict) and str(o.get("text", "")).strip() for o in overlays)

    meta_path = os.path.join(job_output_dir, "metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f_meta:
            meta = json.load(f_meta)
        source_video = meta.get("source_video")
        seg = next((s for s in meta.get("segments", []) if s.get("filename") == clean_fn), None)
        if not seg or not source_video or not os.path.exists(source_video):
            raise HTTPException(status_code=404, detail="Source clip metadata not found.")

        eff_aspect = aspect_ratio or meta.get("aspect_ratio", "original")
        eff_fit = fit_mode or meta.get("fit_mode", "fit")
        eff_pad = pad_color or meta.get("pad_color", "black")

        target_fn = f"edited_{clean_fn}" if has_text else clean_fn
        output_path = os.path.join(job_output_dir, target_fn)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: custom_clipper.render_single_custom_clip(
                source_video_path=source_video,
                output_path=output_path,
                start_time=seg["start"],
                duration=seg["duration"],
                aspect_ratio=eff_aspect,
                fit_mode=eff_fit,
                pad_color=eff_pad,
                overlays=overlays if has_text else None
            )
        )

        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="Failed to render clip.")

        return FileResponse(output_path, media_type="video/mp4", filename=clean_fn)

    # Fallback for pre-sliced clip files
    input_path = os.path.join(job_output_dir, clean_fn)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Clip {clean_fn} not found.")

    if not has_text:
        return FileResponse(input_path, media_type="video/mp4", filename=clean_fn)

    edited_fn = f"edited_{clean_fn}"
    output_path = os.path.join(job_output_dir, edited_fn)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: custom_clipper.render_clip_overlays(
            clip_path=input_path,
            output_path=output_path,
            overlays=overlays
        )
    )

    if not os.path.exists(output_path):
        raise HTTPException(status_code=500, detail="Failed to render edited clip.")

    return FileResponse(output_path, media_type="video/mp4", filename=clean_fn)


@app.post("/api/custom-clip/render-batch-zip")
async def render_batch_zip_endpoint(
    request: Request,
    job_id: str = Form(...),
    clips_overlays_json: str = Form(...),
    aspect_ratio: Optional[str] = Form(None),
    fit_mode: Optional[str] = Form(None),
    pad_color: Optional[str] = Form(None),
    auth_token: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None)
):
    """
    Renders all clips with their individual saved edits and packages them into a downloadable ZIP.
    Supports cancellation and progress reporting.
    """
    user = verify_generation_access(auth_token=auth_token, authorization=authorization)
    clean_job = re.sub(r"[^a-zA-Z0-9_\-]", "", job_id)
    job_output_dir = os.path.join(CLIPS_DIR, f"custom_{clean_job}")

    if not os.path.exists(job_output_dir):
        raise HTTPException(status_code=404, detail=f"Job directory for {clean_job} not found.")

    try:
        clips_overlays_map = json.loads(clips_overlays_json)
        if not isinstance(clips_overlays_map, dict):
            clips_overlays_map = {}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid clips_overlays_json: {e}")

    zip_filename = "edited_all_clips.zip"
    zip_path = os.path.join(job_output_dir, zip_filename)

    meta_path = os.path.join(job_output_dir, "metadata.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f_meta:
            meta = json.load(f_meta)
        source_video = meta.get("source_video")
        segments = meta.get("segments", [])

        eff_aspect = aspect_ratio or meta.get("aspect_ratio", "original")
        eff_fit = fit_mode or meta.get("fit_mode", "fit")
        eff_pad = pad_color or meta.get("pad_color", "black")

        def check_cancelled():
            return active_custom_clip_jobs.get(job_id, {}).get("cancelled", False)

        def on_zip_progress(curr, total, clip_fn):
            if job_id in active_custom_clip_jobs:
                active_custom_clip_jobs[job_id]["current_clip"] = curr
                active_custom_clip_jobs[job_id]["total_clips"] = total
                active_custom_clip_jobs[job_id]["progress"] = int((curr / max(1, total)) * 100)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: custom_clipper.render_batch_custom_clips(
                source_video_path=source_video,
                segments=segments,
                output_dir=job_output_dir,
                clips_overlays_map=clips_overlays_map,
                zip_output_path=zip_path,
                aspect_ratio=eff_aspect,
                fit_mode=eff_fit,
                pad_color=eff_pad,
                cancel_check=check_cancelled,
                progress_callback=on_zip_progress
            )
        )
    else:
        # Fallback for pre-sliced clips
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: custom_clipper.render_batch_edited_clips(
                job_output_dir=job_output_dir,
                clips_overlays_map=clips_overlays_map,
                zip_output_path=zip_path
            )
        )

    if not os.path.exists(zip_path):
        raise HTTPException(status_code=500, detail="Failed to create batch ZIP.")

    user_tok = (user.get("token") if user else "") or (auth_token or "")
    accept_hdr = request.headers.get("accept", "")

    if "application/json" in accept_hdr and "application/zip" not in accept_hdr:
        tok_param = f"?token={user_tok}" if user_tok else ""
        return {
            "success": True,
            "zip_url": f"/api/custom-clip/download/{clean_job}/{zip_filename}{tok_param}"
        }

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"clips_{clean_job}.zip"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
