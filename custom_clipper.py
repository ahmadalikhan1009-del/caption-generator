import os
import subprocess
import shutil
import zipfile
import re
from typing import List, Dict, Any, Optional, Callable

# Use the robust FFmpeg detection from video_utils (finds D:\project 3 and other non-PATH locations)
from video_utils import _find_ffmpeg_exe


def _ffmpeg() -> str:
    """Return the full path to ffmpeg.exe, or 'ffmpeg' as fallback."""
    found = _find_ffmpeg_exe("ffmpeg.exe")
    return found if found else "ffmpeg"


def _ffprobe() -> str:
    """Return the full path to ffprobe.exe, or 'ffprobe' as fallback."""
    found = _find_ffmpeg_exe("ffprobe.exe")
    return found if found else "ffprobe"


def is_ffmpeg_available() -> bool:
    return _find_ffmpeg_exe("ffmpeg.exe") is not None and _find_ffmpeg_exe("ffprobe.exe") is not None

def format_seconds_to_hms(seconds: float) -> str:
    """Formats seconds into HH:MM:SS."""
    s = max(0, int(round(seconds)))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"

def get_video_duration(video_path: str) -> float:
    """
    Extracts exact video duration in seconds using ffprobe.
    Falls back to ffmpeg log analysis if ffprobe direct duration is missing.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Primary probe via format duration
    try:
        cmd = [
            _ffprobe(), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            dur = float(res.stdout.strip())
            if dur > 0:
                return dur
    except Exception:
        pass

    # Secondary probe via stream duration
    try:
        cmd2 = [
            _ffprobe(), "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res2.returncode == 0 and res2.stdout.strip() and res2.stdout.strip() != "N/A":
            dur2 = float(res2.stdout.strip())
            if dur2 > 0:
                return dur2
    except Exception:
        pass

    # Tertiary fallback: ffmpeg -i info stderr parsing
    try:
        cmd3 = [_ffmpeg(), "-i", video_path]
        res3 = subprocess.run(cmd3, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res3.stderr)
        if m:
            hours, mins, secs = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return hours * 3600.0 + mins * 60.0 + secs
    except Exception:
        pass

    raise RuntimeError("Could not determine video duration. Please ensure the file is a valid video.")

def calculate_custom_clip_segments(total_duration: float, clip_duration_seconds: float) -> List[Dict[str, Any]]:
    """
    Divides total_duration into consecutive, equal-duration clips without intentional gaps or overlaps.
    If the duration is not evenly divisible, the final clip contains the remaining portion.
    Never discards the final portion.
    """
    if total_duration <= 0:
        return []
    if clip_duration_seconds <= 0:
        raise ValueError("Requested clip duration must be greater than 0 seconds.")

    segments = []
    current_start = 0.0
    index = 1

    while current_start < total_duration:
        current_end = min(current_start + clip_duration_seconds, total_duration)
        dur = current_end - current_start
        # Only add if segment has positive length
        if dur > 0.05:
            segments.append({
                "index": index,
                "title": f"Clip {index}",
                "start": round(current_start, 2),
                "end": round(current_end, 2),
                "duration": round(dur, 2),
                "start_formatted": format_seconds_to_hms(current_start),
                "end_formatted": format_seconds_to_hms(current_end),
                "duration_formatted": format_seconds_to_hms(dur)
            })
            index += 1
        current_start = current_end

    return segments

def slice_custom_clip(input_path: str, output_path: str, start_time: float, duration: float, overlay_params: Optional[Dict[str, Any]] = None) -> bool:
    """
    Slices a clip using FFmpeg.
    If overlay_params with text is provided, burns the custom text overlay.
    Otherwise attempts ultrafast stream copy first (-c copy) and falls back to re-encoding.
    """
    start_time = max(0.0, float(start_time))
    duration = max(0.1, float(duration))

    has_overlay = bool(overlay_params and isinstance(overlay_params, dict) and str(overlay_params.get("text", "")).strip())
    if has_overlay:
        import tempfile
        from video_utils import get_video_dimensions, generate_ass_subtitles, FONTS_DIR
        temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
        temp_ass_path = temp_ass.name
        temp_ass.close()
        try:
            w, h = get_video_dimensions(input_path)
            generate_ass_subtitles(
                words=None,
                ass_file_path=temp_ass_path,
                play_res_x=w,
                play_res_y=h,
                overlay_params=overlay_params,
                clip_duration=duration
            )
            clean_ass = temp_ass_path.replace("\\", "/").replace(":", "\\:")
            clean_fonts = FONTS_DIR.replace("\\", "/").replace(":", "\\:") if os.path.isdir(FONTS_DIR) else ""
            sub_filter = f"ass='{clean_ass}':fontsdir='{clean_fonts}'" if clean_fonts else f"ass='{clean_ass}'"

            cmd_overlay = [
                _ffmpeg(), "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", input_path,
                "-vf", sub_filter,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-threads", "0",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "192k",
                "-avoid_negative_ts", "make_zero",
                output_path
            ]
            res_ov = subprocess.run(cmd_overlay, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res_ov.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True
        finally:
            if os.path.exists(temp_ass_path):
                try:
                    os.remove(temp_ass_path)
                except Exception:
                    pass

    # Stream copy video, but re-encode audio to stereo AAC for browser compatibility.
    # 8-channel / surround audio (common in movies) is not supported by any browser;
    # using -c copy would preserve the multi-channel track and the browser would play silence.
    cmd_copy = [
        _ffmpeg(), "-y",
        "-ss", str(start_time),
        "-t", str(duration),
        "-i", input_path,
        "-c:v", "copy",          # copy video stream losslessly (fast)
        "-c:a", "aac",           # re-encode audio to AAC
        "-ac", "2",              # downmix to stereo (browser-compatible)
        "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        output_path
    ]
    res_copy = subprocess.run(cmd_copy, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res_copy.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return True

    # Fallback: full re-encode if video copy above fails (e.g. incompatible codec)
    cmd_encode = [
        _ffmpeg(), "-y",
        "-ss", str(start_time),
        "-t", str(duration),
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-threads", "0",
        "-crf", "22",
        "-c:a", "aac",
        "-ac", "2",              # stereo downmix
        "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        output_path
    ]
    res_encode = subprocess.run(cmd_encode, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res_encode.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return True

    error_msg = res_encode.stderr.decode("utf-8", errors="ignore")
    raise RuntimeError(f"FFmpeg failed to slice clip at {start_time}s: {error_msg[-300:]}")

def split_video_custom(
    input_path: str,
    output_dir: str,
    clip_duration_seconds: float,
    job_id: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    overlay_params: Optional[Dict[str, Any]] = None,
    aspect_ratio: str = "original",
    fit_mode: str = "fit",
    pad_color: str = "black",
    progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None
) -> List[Dict[str, Any]]:
    """
    Splits video into consecutive equal clips with full aspect-ratio conversion.
    When aspect_ratio is '9:16' or '16:9', uses trim_video_clip to properly
    resize/reframe each segment. Supports cooperative cancellation and optional
    text overlay (burned into each clip).
    """
    if not is_ffmpeg_available():
        raise RuntimeError("FFmpeg/ffprobe is not available on system PATH.")

    # Decide which export path to use
    needs_resize = aspect_ratio in ("9:16", "16:9")
    has_overlay = bool(overlay_params and isinstance(overlay_params, dict) and str(overlay_params.get("text", "")).strip())

    if needs_resize or has_overlay:
        # Full re-encode via trim_video_clip — handles resize, framing, and overlay
        from video_utils import trim_video_clip
        _use_trim = True
    else:
        _use_trim = False

    os.makedirs(output_dir, exist_ok=True)
    total_duration = get_video_duration(input_path)
    segments = calculate_custom_clip_segments(total_duration, clip_duration_seconds)

    if not segments:
        raise ValueError("Video duration is too short to generate clips with requested duration.")

    generated_clips = []
    pad_digits = max(2, len(str(len(segments))))

    for seg in segments:
        if cancel_check and cancel_check():
            raise RuntimeError("Custom clipping was cancelled by the user.")

        idx = seg["index"]
        clip_filename = f"clip_{idx:0{pad_digits}d}.mp4"
        clip_path = os.path.join(output_dir, clip_filename)

        if _use_trim:
            # Use full resize/reframe pipeline with ultrafast preset for maximum throughput
            style_options = {}
            if has_overlay:
                style_options["overlay"] = overlay_params
            trim_video_clip(
                input_path=input_path,
                output_path=clip_path,
                start_time=seg["start"],
                duration=seg["duration"],
                aspect_ratio=aspect_ratio,
                fit_mode=fit_mode,
                pad_color=pad_color,
                words=None,
                style_options=style_options,
                burn_captions=False,
                preset="ultrafast"
            )
        else:
            slice_custom_clip(
                input_path=input_path,
                output_path=clip_path,
                start_time=seg["start"],
                duration=seg["duration"],
                overlay_params=overlay_params
            )

        file_size = os.path.getsize(clip_path) if os.path.exists(clip_path) else 0

        clip_data = {
            "index": idx,
            "title": f"Clip {idx} ({seg['start_formatted']} - {seg['end_formatted']})",
            "filename": clip_filename,
            "filepath": clip_path,
            "start": seg["start"],
            "end": seg["end"],
            "duration": seg["duration"],
            "start_formatted": seg["start_formatted"],
            "end_formatted": seg["end_formatted"],
            "duration_formatted": seg["duration_formatted"],
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2)
        }
        generated_clips.append(clip_data)

        if progress_callback:
            try:
                progress_callback(idx, len(segments), clip_data)
            except Exception:
                pass

    return generated_clips

def create_clips_zip(clip_paths: List[str], zip_output_path: str) -> str:
    """
    Bundles all clip files into a single ZIP file for batch download.
    Uses ZIP_STORED to minimize memory and CPU overhead since MP4 is already compressed.
    """
    os.makedirs(os.path.dirname(os.path.abspath(zip_output_path)), exist_ok=True)
    with zipfile.ZipFile(zip_output_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for p in clip_paths:
            if os.path.exists(p):
                zf.write(p, arcname=os.path.basename(p))
    return zip_output_path


def render_clip_overlays(
    clip_path: str,
    output_path: str,
    overlays: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Renders custom text overlay(s) directly onto an existing clip file.
    Preserves audio, video timing, and dimensions.
    If no overlays or all overlays have empty text, copies the original file to output_path.
    """
    if not os.path.exists(clip_path):
        raise FileNotFoundError(f"Source clip not found: {clip_path}")

    valid_overlays = []
    if overlays:
        if isinstance(overlays, list):
            valid_overlays = [o for o in overlays if isinstance(o, dict) and str(o.get("text", "")).strip()]
        elif isinstance(overlays, dict):
            if "overlays" in overlays and isinstance(overlays["overlays"], list):
                valid_overlays = [o for o in overlays["overlays"] if isinstance(o, dict) and str(o.get("text", "")).strip()]
            elif str(overlays.get("text", "")).strip():
                valid_overlays = [overlays]

    if not valid_overlays:
        if os.path.abspath(clip_path) != os.path.abspath(output_path):
            shutil.copy2(clip_path, output_path)
        return output_path

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    import tempfile
    from video_utils import get_video_dimensions, generate_ass_subtitles, FONTS_DIR

    temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
    temp_ass_path = temp_ass.name
    temp_ass.close()

    try:
        w, h = get_video_dimensions(clip_path)
        duration = get_video_duration(clip_path)

        generate_ass_subtitles(
            words=None,
            ass_file_path=temp_ass_path,
            play_res_x=w,
            play_res_y=h,
            overlay_params=valid_overlays,
            clip_duration=duration
        )

        clean_ass = temp_ass_path.replace("\\", "/").replace(":", "\\:")
        clean_fonts = FONTS_DIR.replace("\\", "/").replace(":", "\\:") if os.path.isdir(FONTS_DIR) else ""
        sub_filter = f"ass='{clean_ass}':fontsdir='{clean_fonts}'" if clean_fonts else f"ass='{clean_ass}'"

        # Try fast stream copy of audio first
        cmd = [
            _ffmpeg(), "-y",
            "-i", clip_path,
            "-vf", sub_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-threads", "0",
            "-crf", "22",
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return output_path

        # Fallback with audio re-encode to aac stereo if stream copy fails
        cmd_fallback = [
            _ffmpeg(), "-y",
            "-i", clip_path,
            "-vf", sub_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-threads", "0",
            "-crf", "22",
            "-c:a", "aac",
            "-ac", "2",
            "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]
        res_fb = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res_fb.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return output_path

        err_msg = res_fb.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"FFmpeg failed to burn overlays into clip: {err_msg[-300:]}")
    finally:
        if os.path.exists(temp_ass_path):
            try:
                os.remove(temp_ass_path)
            except Exception:
                pass



def render_single_custom_clip(
    source_video_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    aspect_ratio: str = "original",
    fit_mode: str = "fit",
    pad_color: str = "black",
    overlays: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Renders a single custom clip on demand with precise start/duration,
    aspect ratio framing (9:16, 16:9, original), fit mode, and text overlays.
    Uses trim_video_clip for aspect conversion and overlays, or ultrafast stream copy if original with no overlays.
    """
    if not os.path.exists(source_video_path):
        raise FileNotFoundError(f"Source video not found: {source_video_path}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    valid_overlays = []
    if overlays:
        if isinstance(overlays, list):
            valid_overlays = [o for o in overlays if isinstance(o, dict) and str(o.get("text", "")).strip()]
        elif isinstance(overlays, dict):
            if "overlays" in overlays and isinstance(overlays["overlays"], list):
                valid_overlays = [o for o in overlays["overlays"] if isinstance(o, dict) and str(o.get("text", "")).strip()]
            elif str(overlays.get("text", "")).strip():
                valid_overlays = [overlays]

    needs_resize = aspect_ratio in ("9:16", "16:9")
    has_overlay = bool(valid_overlays)

    if needs_resize or has_overlay:
        from video_utils import trim_video_clip
        style_options = {}
        if has_overlay:
            style_options["overlay"] = valid_overlays
        trim_video_clip(
            input_path=source_video_path,
            output_path=output_path,
            start_time=start_time,
            duration=duration,
            aspect_ratio=aspect_ratio,
            fit_mode=fit_mode,
            pad_color=pad_color,
            words=None,
            style_options=style_options,
            burn_captions=False,
            preset="ultrafast"
        )
    else:
        slice_custom_clip(
            input_path=source_video_path,
            output_path=output_path,
            start_time=start_time,
            duration=duration,
            overlay_params=None
        )

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 500:
        raise RuntimeError(f"FFmpeg failed to produce clip at {output_path}")

    return output_path


def render_batch_custom_clips(
    source_video_path: str,
    segments: List[Dict[str, Any]],
    output_dir: str,
    clips_overlays_map: Dict[str, Any],
    zip_output_path: str,
    aspect_ratio: str = "original",
    fit_mode: str = "fit",
    pad_color: str = "black",
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> str:
    """
    Renders all segments on demand from source_video_path, applying per-clip overlays where present,
    and packages them into a single ZIP archive.
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(zip_output_path)), exist_ok=True)

    pad_digits = max(2, len(str(len(segments))))
    zip_entries = []

    for idx, seg in enumerate(segments, start=1):
        if cancel_check and cancel_check():
            raise RuntimeError("Batch ZIP rendering was cancelled by user.")

        clip_fn = seg.get("filename") or f"clip_{seg.get('index', idx):0{pad_digits}d}.mp4"
        ovs = clips_overlays_map.get(clip_fn) or []
        has_ovs = False
        if ovs:
            if isinstance(ovs, list):
                has_ovs = any(isinstance(o, dict) and str(o.get("text", "")).strip() for o in ovs)
            elif isinstance(ovs, dict):
                has_ovs = bool(str(ovs.get("text", "")).strip() or ovs.get("overlays"))

        if has_ovs:
            out_fn = f"edited_{clip_fn}"
        else:
            out_fn = clip_fn

        clip_out_path = os.path.join(output_dir, out_fn)

        if not os.path.exists(clip_out_path) or os.path.getsize(clip_out_path) < 500:
            render_single_custom_clip(
                source_video_path=source_video_path,
                output_path=clip_out_path,
                start_time=seg["start"],
                duration=seg["duration"],
                aspect_ratio=aspect_ratio,
                fit_mode=fit_mode,
                pad_color=pad_color,
                overlays=ovs if has_ovs else None
            )

        zip_entries.append((clip_out_path, clip_fn))

        if progress_callback:
            try:
                progress_callback(idx, len(segments), clip_fn)
            except Exception:
                pass

    with zipfile.ZipFile(zip_output_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for file_to_pack, arcname in zip_entries:
            if os.path.exists(file_to_pack):
                zf.write(file_to_pack, arcname=arcname)

    return zip_output_path

def render_batch_edited_clips(
    job_output_dir: str,
    clips_overlays_map: Dict[str, Any],
    zip_output_path: str
) -> str:
    """
    Renders any clips with overlays into edited_{filename}, leaves unedited clips as original,
    and creates a ZIP archive bundling all clips.
    """
    os.makedirs(job_output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(zip_output_path)), exist_ok=True)

    clip_files = sorted([
        f for f in os.listdir(job_output_dir)
        if f.startswith("clip_") and f.endswith(".mp4") and not f.startswith("edited_")
    ])

    if not clip_files:
        clip_files = sorted([
            k for k in clips_overlays_map.keys()
            if os.path.exists(os.path.join(job_output_dir, k))
        ])

    zip_entries = []
    for fn in clip_files:
        orig_clip_path = os.path.join(job_output_dir, fn)
        overlays = clips_overlays_map.get(fn, [])
        has_overlays = False
        if overlays:
            if isinstance(overlays, list):
                has_overlays = any(isinstance(o, dict) and str(o.get("text", "")).strip() for o in overlays)
            elif isinstance(overlays, dict):
                has_overlays = bool(str(overlays.get("text", "")).strip() or overlays.get("overlays"))

        if has_overlays:
            edited_fn = f"edited_{fn}"
            edited_clip_path = os.path.join(job_output_dir, edited_fn)
            render_clip_overlays(orig_clip_path, edited_clip_path, overlays)
            zip_entries.append((edited_clip_path, fn))
        else:
            zip_entries.append((orig_clip_path, fn))

    with zipfile.ZipFile(zip_output_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for file_to_pack, arcname in zip_entries:
            if os.path.exists(file_to_pack):
                zf.write(file_to_pack, arcname=arcname)

    return zip_output_path
