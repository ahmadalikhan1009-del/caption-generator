import os
import subprocess
import shutil
import tempfile

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Directories to search for ffmpeg/ffprobe on Windows (in addition to PATH)
_FFMPEG_SEARCH_DIRS = [
    r"D:\project 3",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\Program Files (x86)\ffmpeg\bin",
    r"C:\ProgramData\chocolatey\bin",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg_bin"),
]


def _add_to_path_if_exists(dir_path: str) -> None:
    """Prepend dir_path to the process PATH if it exists and is not already there."""
    if os.path.isdir(dir_path) and dir_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = dir_path + os.pathsep + os.environ.get("PATH", "")


def _find_ffmpeg_exe(exe_name: str) -> str | None:
    """
    Return the full path to exe_name (e.g. 'ffmpeg.exe') by:
    1. Checking the current PATH via shutil.which.
    2. Scanning _FFMPEG_SEARCH_DIRS.
    If found in a search dir, that directory is prepended to PATH so all
    subsequent subprocess calls can use the bare command name.
    """
    found = shutil.which(exe_name)
    if found:
        return found
    for d in _FFMPEG_SEARCH_DIRS:
        candidate = os.path.join(d, exe_name)
        if os.path.isfile(candidate):
            _add_to_path_if_exists(d)
            return candidate
    return None


def is_ffmpeg_available() -> bool:
    """Return True if ffmpeg is reachable; also adds its folder to PATH."""
    return _find_ffmpeg_exe("ffmpeg.exe") is not None


def is_ffprobe_available() -> bool:
    """Return True if ffprobe is reachable; also adds its folder to PATH."""
    return _find_ffmpeg_exe("ffprobe.exe") is not None




def extract_audio_fast(video_path, audio_path):
    """Extracts 16kHz mono audio from video using FFmpeg for ultra-fast processing."""
    ffmpeg_exe = _find_ffmpeg_exe("ffmpeg.exe")
    if ffmpeg_exe:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", video_path,
            "-vn",
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            audio_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0 and os.path.exists(audio_path):
            return audio_path
    return video_path

def hex_to_ass_color(hex_str, opacity_alpha=0):
    """
    Converts CSS hex color (#RRGGBB) to ASS color format (&HAABBGGRR).
    opacity_alpha: 0 (opaque) to 255 (fully transparent).
    """
    if not hex_str or not hex_str.startswith("#"):
        return "&H00FFFFFF"
    hex_clean = hex_str.lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join([c*2 for c in hex_clean])
    if len(hex_clean) != 6:
        return "&H00FFFFFF"
    
    r = hex_clean[0:2]
    g = hex_clean[2:4]
    b = hex_clean[4:6]
    alpha_hex = f"{int(opacity_alpha):02X}"
    return f"&H{alpha_hex}{b}{g}{r}"

def format_ass_time(seconds):
    """Formats float seconds into ASS timestamp: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def generate_ass_subtitles(words, ass_file_path, font_family="Montserrat", font_size=32, 
                            text_color="#ffffff", highlight_color="#facc15", stroke_color="#000000",
                            stroke_width=3, box_style="none", bg_color="#000000", bg_opacity=75,
                            pos_y_percent=72, anim_style="hormozi",
                            play_res_x=1080, play_res_y=1920,
                            overlay_params=None, clip_duration=None,
                            pos_x_percent=50.0, box_width_percent=82.0,
                            preview_height=None):
    """
    Generates an Advanced SubStation Alpha (.ass) file with word-by-word active highlight animations
    and optional persistent custom text overlay, with proportional font and margin scaling to match
    the browser preview canvas exactly.
    """
    clean_font = font_family.split(",")[0].replace("'", "").replace('"', "").strip()
    
    # Auto-fallback to Nirmala UI for Hindi/Urdu unicode characters
    has_indic_or_arabic = any(
        any(('\u0900' <= ch <= '\u097F') or ('\u0600' <= ch <= '\u06FF') for ch in w.get("word", ""))
        for w in (words or [])
    )
    if has_indic_or_arabic and "nirmala" not in clean_font.lower():
        clean_font = "Nirmala UI"
        
    ass_primary = hex_to_ass_color(text_color, 0)
    ass_highlight = hex_to_ass_color(highlight_color, 0)
    ass_outline = hex_to_ass_color(stroke_color, 0)
    
    # 0 = opaque, 255 = transparent in ASS
    alpha_val = int((1.0 - (bg_opacity / 100.0)) * 255)
    ass_box_bg = hex_to_ass_color(bg_color, alpha_val)
    border_style = 3 if box_style in ["solid", "pill"] else 1
    
    # Proportional font scaling matching canvas preview dimensions
    ref_preview_h = float(preview_height) if preview_height and float(preview_height) > 0 else (640.0 if play_res_y > play_res_x else 450.0)
    scale_ratio = play_res_y / max(100.0, ref_preview_h)

    scaled_font_size = max(16, int(round(font_size * scale_ratio)))
    scaled_stroke = max(0, int(round(stroke_width * scale_ratio)))

    # Box width & margin boundaries matching preview text box wrapping
    w_box = max(100.0, (float(box_width_percent) / 100.0) * play_res_x)
    margin_side = max(16, int((play_res_x - w_box) / 2.0))
    margin_v = max(10, int((100.0 - float(pos_y_percent)) * 0.01 * play_res_y))

    # Custom Text Overlay(s) (Optional) - Supports single overlay dict or multiple overlay list
    overlay_styles = []
    overlay_events = []
    overlay_items = []
    if overlay_params:
        if isinstance(overlay_params, list):
            overlay_items = [o for o in overlay_params if isinstance(o, dict) and str(o.get("text", "")).strip()]
        elif isinstance(overlay_params, dict):
            if "overlays" in overlay_params and isinstance(overlay_params["overlays"], list):
                overlay_items = [o for o in overlay_params["overlays"] if isinstance(o, dict) and str(o.get("text", "")).strip()]
            elif str(overlay_params.get("text", "")).strip():
                overlay_items = [overlay_params]

    for idx, ov in enumerate(overlay_items, 1):
        ov_text = str(ov.get("text", "")).strip()
        if not ov_text:
            continue
        raw_ov_font = ov.get("font_family") or font_family or "Montserrat"
        ov_font = raw_ov_font.split(",")[0].replace("'", "").replace('"', "").strip()
        if any(('\u0900' <= ch <= '\u097F') or ('\u0600' <= ch <= '\u06FF') for ch in ov_text):
            if "nirmala" not in ov_font.lower():
                ov_font = "Nirmala UI"

        ov_size = float(ov.get("font_size") or 28)
        ov_preview_h = float(ov.get("preview_height") or ref_preview_h)
        ov_scale_ratio = play_res_y / max(100.0, ov_preview_h)
        ov_scaled_font_size = max(14, int(round(ov_size * ov_scale_ratio)))
        ov_color = hex_to_ass_color(ov.get("text_color") or "#ffffff", 0)
        ov_stroke_color = hex_to_ass_color(ov.get("stroke_color") or "#000000", 0)
        ov_stroke_w = max(0, int(round(float(ov.get("stroke_width", 2.5)) * ov_scale_ratio)))

        ov_bg_opacity = float(ov.get("bg_opacity", 0))
        ov_bg_color = ov.get("bg_color") or "#000000"
        ov_bg_alpha = int((1.0 - (ov_bg_opacity / 100.0)) * 255)
        ov_box_bg = hex_to_ass_color(ov_bg_color, ov_bg_alpha)
        ov_border_style = 3 if ov_bg_opacity > 0 or ov.get("box_style") in ["solid", "pill", "box"] else 1

        ov_box_w_pct = float(ov.get("box_width_percent", 75.0))
        ov_w_box = max(100.0, (ov_box_w_pct / 100.0) * play_res_x)
        ov_margin_side = max(16, int((play_res_x - ov_w_box) / 2.0))

        ov_align = (ov.get("align") or "center").lower()
        ass_align_code = 4 if ov_align == "left" else (6 if ov_align == "right" else 5)

        ov_x_pct = float(ov.get("pos_x_percent", 50.0))
        ov_y_pct = float(ov.get("pos_y_percent", 15.0))
        ov_x_px = int((ov_x_pct / 100.0) * play_res_x)
        ov_y_px = int((ov_y_pct / 100.0) * play_res_y)

        # End time for persistent overlay
        if clip_duration:
            end_dur = float(clip_duration)
        elif words:
            end_dur = max([w.get("end", 0.0) for w in words]) + 2.0
        else:
            end_dur = 3600.0
        ov_end_str = format_ass_time(max(0.5, end_dur))

        style_name = f"OverlayStyle_{idx}"
        overlay_styles.append(
            f"Style: {style_name},{ov_font},{ov_scaled_font_size},{ov_color},&H000000FF,{ov_stroke_color},{ov_box_bg},-1,0,0,0,100,100,1,0,{ov_border_style},{ov_stroke_w},1,{ass_align_code},{ov_margin_side},{ov_margin_side},20,1"
        )
        clean_ov_text = ov_text.replace("\r\n", "\\N").replace("\n", "\\N").replace("\r", "\\N")
        overlay_events.append(
            f"Dialogue: 1,0:00:00.00,{ov_end_str},{style_name},,0,0,0,,{{\\an{ass_align_code}\\pos({ov_x_px},{ov_y_px})}}{clean_ov_text}"
        )

    overlay_style_line = ("\n".join(overlay_styles) + "\n") if overlay_styles else ""

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{clean_font},{scaled_font_size},{ass_primary},&H000000FF,{ass_outline},{ass_box_bg},-1,0,0,0,100,100,1,0,{border_style},{scaled_stroke},2,2,{margin_side},{margin_side},{margin_v},1
{overlay_style_line}[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    if overlay_events:
        events.extend(overlay_events)

    if words:
        group_size = 1 if anim_style == "single_word" else 4

        # Clean words to ensure strictly monotonic, non-overlapping timestamps
        # This prevents libass collision resolution from ever stacking dialogue lines on top of each other
        clean_words = []
        last_end = 0.0
        for w in words:
            cw = str(w.get("word", "")).strip()
            if not cw:
                continue
            w_s = max(0.0, float(w.get("start", 0.0)))
            w_e = max(w_s + 0.05, float(w.get("end", w_s + 0.1)))
            if w_s < last_end:
                w_s = last_end
            if w_e <= w_s:
                w_e = w_s + 0.06
            last_end = w_e
            clean_words.append({
                "word": cw,
                "start": round(w_s, 3),
                "end": round(w_e, 3)
            })

        for i in range(len(clean_words)):
            active_word = clean_words[i]
            # Group surrounding words for readability
            if anim_style == "single_word":
                group_words = [active_word]
                active_in_group = 0
            else:
                group_start = max(0, (i // group_size) * group_size)
                group_words = clean_words[group_start:min(len(clean_words), group_start + group_size)]
                active_in_group = i - group_start

            # Calculate smooth end time bridging natural micro-pauses between spoken words
            w_raw_start = active_word["start"]
            w_raw_end = active_word["end"]
            if i + 1 < len(clean_words):
                next_w_start = clean_words[i + 1]["start"]
                gap = next_w_start - w_raw_end
                if 0 <= gap <= 0.35:
                    smooth_end = next_w_start
                elif gap > 0.35:
                    smooth_end = min(w_raw_end + 0.5, next_w_start)
                else:
                    smooth_end = next_w_start
                # Ensure the dialogue never bleeds past next word's start time (prevents line stacking)
                smooth_end = min(smooth_end, next_w_start)
            else:
                smooth_end = w_raw_end + 0.6

            start_t = format_ass_time(w_raw_start)
            end_t = format_ass_time(max(w_raw_start + 0.05, smooth_end))

            # Build line text with active word colored in highlight
            line_parts = []
            for gw_idx, gw in enumerate(group_words):
                raw_w = gw["word"].strip()
                w_text = raw_w.upper() if raw_w.isascii() else raw_w
                if gw == active_word:
                    # Highlight active word
                    if anim_style == "hormozi":
                        line_parts.append(f"{{\\c{ass_highlight}\\fscx120\\fscy120}}{w_text}{{\\r}}")
                    elif anim_style == "bounce":
                        line_parts.append(f"{{\\c{ass_highlight}\\fscx130\\fscy130}}{w_text}{{\\r}}")
                    elif anim_style == "pop":
                        line_parts.append(f"{{\\t(0,80,\\fscx130\\fscy130)\\t(80,180,\\fscx115\\fscy115)\\c{ass_highlight}\\fscx100\\fscy100}}{w_text}{{\\r}}")
                    elif anim_style == "fade":
                        line_parts.append(f"{{\\alpha&H90&\\t(0,100,\\alpha&H00&)\\c{ass_highlight}}}{w_text}{{\\r}}")
                    elif anim_style == "glow":
                        line_parts.append(f"{{\\c{ass_highlight}\\fscx118\\fscy118\\blur3\\3c{ass_highlight}}}{w_text}{{\\r}}")
                    elif anim_style == "cinematic":
                        line_parts.append(f"{{\\c{ass_highlight}\\fsp2}}{w_text}{{\\r}}")
                    elif anim_style == "underline":
                        line_parts.append(f"{{\\c{ass_highlight}\\u1}}{w_text}{{\\r}}")
                    elif anim_style == "social_box":
                        line_parts.append(f"{{\\c{ass_highlight}\\fscx115\\fscy115\\bord4}}{w_text}{{\\r}}")
                    elif anim_style == "typewriter":
                        line_parts.append(f"{{\\c{ass_highlight}\\fscx110\\fscy110}}{w_text}{{\\r}}")
                    elif anim_style == "single_word":
                        line_parts.append(f"{{\\c{ass_highlight}\\fscx125\\fscy125}}{w_text}{{\\r}}")
                    else:
                        # karaoke, clean, or default highlight
                        line_parts.append(f"{{\\c{ass_highlight}}}{w_text}{{\\r}}")
                else:
                    if anim_style == "typewriter" and gw_idx > active_in_group:
                        line_parts.append(f"{{\\c{ass_primary}\\alpha&HCC&}}{w_text}{{\\r}}")
                    elif anim_style == "cinematic":
                        line_parts.append(f"{{\\c{ass_primary}\\fsp2}}{w_text}{{\\r}}")
                    else:
                        line_parts.append(f"{{\\c{ass_primary}}}{w_text}{{\\r}}")

            full_line = " ".join(line_parts)
            events.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{full_line}")

    with open(ass_file_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")

    return ass_file_path


def format_srt_time(seconds: float) -> str:
    """Formats seconds into SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def format_vtt_time(seconds: float) -> str:
    """Formats seconds into WebVTT timestamp: HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def generate_srt_content(segments: list) -> str:
    """Generates standard SubRip (.srt) subtitle string from transcript segments."""
    entries = []
    idx = 1
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        start_t = format_srt_time(max(0.0, float(seg.get("start", 0.0))))
        end_t = format_srt_time(max(0.1, float(seg.get("end", 0.1))))
        entries.append(f"{idx}\n{start_t} --> {end_t}\n{text}\n")
        idx += 1
    return "\n".join(entries).strip() + "\n"

def generate_vtt_content(segments: list) -> str:
    """Generates standard WebVTT (.vtt) subtitle string from transcript segments."""
    entries = ["WEBVTT\n"]
    for idx, seg in enumerate(segments, 1):
        text = seg.get("text", "").strip()
        if not text:
            continue
        start_t = format_vtt_time(max(0.0, float(seg.get("start", 0.0))))
        end_t = format_vtt_time(max(0.1, float(seg.get("end", 0.1))))
        entries.append(f"{idx}\n{start_t} --> {end_t}\n{text}\n")
    return "\n".join(entries).strip() + "\n"

def generate_txt_content(segments: list, include_timestamps: bool = True) -> str:
    """Generates clean readable transcript text file from segments."""
    lines = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        if include_timestamps:
            start_m, start_s = divmod(float(seg.get("start", 0.0)), 60)
            end_m, end_s = divmod(float(seg.get("end", 0.0)), 60)
            time_tag = f"[{int(start_m):02d}:{start_s:04.1f} - {int(end_m):02d}:{end_s:04.1f}]"
            lines.append(f"{time_tag} {text}")
        else:
            lines.append(text)
    return "\n".join(lines).strip() + "\n"


def trim_video_clip(input_path, output_path, start_time, duration, aspect_ratio="9:16", 
                    fit_mode="fit", pad_color="black", words=None, style_options=None, burn_captions=True,
                    preset="veryfast"):
    """
    Cuts video slice and formats to 9:16 Shorts or 16:9, with optional burned-in animated captions.
    When burn_captions=False or words is None/empty, produces a clean video without captions.
    """
    if not is_ffmpeg_available():
        raise RuntimeError("FFmpeg is not installed or not found in PATH. Please install FFmpeg and ensure its 'bin' folder is added to the system PATH.")

    temp_ass_path = None
    subtitles_filter = ""
    
    opt = style_options or {}
    overlay = opt.get("overlay") or opt.get("overlays")
    has_overlay = False
    if overlay:
        if isinstance(overlay, list):
            has_overlay = any(isinstance(o, dict) and str(o.get("text", "")).strip() for o in overlay)
        elif isinstance(overlay, dict):
            if "overlays" in overlay and isinstance(overlay["overlays"], list):
                has_overlay = any(isinstance(o, dict) and str(o.get("text", "")).strip() for o in overlay["overlays"])
            else:
                has_overlay = bool(str(overlay.get("text", "")).strip())
    has_words = bool(burn_captions and words and len(words) > 0)

    # Defensive timestamp normalization for sliced video:
    # Ensures words are strictly relative to clip start [0.0, duration] whether caller sent
    # clip-relative or source-absolute timestamps.
    normalized_words = None
    if has_words:
        is_absolute = False
        first_w_start = float(words[0].get("start", 0.0))
        if start_time > 1.0 and first_w_start >= (start_time - 1.5):
            is_absolute = True

        normalized_words = []
        for w in words:
            w_start = float(w.get("start", 0.0))
            w_end = float(w.get("end", w_start + 0.1))
            if is_absolute:
                w_start = max(0.0, round(w_start - start_time, 3))
                w_end = max(w_start + 0.05, round(w_end - start_time, 3))
            normalized_words.append({
                "word": str(w.get("word", "")).strip(),
                "start": w_start,
                "end": w_end
            })

    if has_words or has_overlay:
        temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
        temp_ass_path = temp_ass.name
        temp_ass.close()

        play_w = 1080 if aspect_ratio == "9:16" else 1920
        play_h = 1920 if aspect_ratio == "9:16" else 1080

        generate_ass_subtitles(
            words=normalized_words if has_words else None,
            ass_file_path=temp_ass_path,
            font_family=opt.get("font_family", "Montserrat"),
            font_size=float(opt.get("font_size", 32)),
            text_color=opt.get("text_color", "#ffffff"),
            highlight_color=opt.get("highlight_color", "#facc15"),
            stroke_color=opt.get("stroke_color", "#000000"),
            stroke_width=float(opt.get("stroke_width", 3)),
            box_style=opt.get("box_style", "none"),
            bg_color=opt.get("bg_color", "#000000"),
            bg_opacity=float(opt.get("bg_opacity", 75)),
            pos_y_percent=float(opt.get("pos_y_percent", 72)),
            pos_x_percent=float(opt.get("pos_x_percent", 50)),
            box_width_percent=float(opt.get("box_width_percent", 82)),
            preview_height=float(opt.get("preview_height", 640 if aspect_ratio == "9:16" else 450)),
            anim_style=opt.get("anim_style", "hormozi"),
            play_res_x=play_w,
            play_res_y=play_h,
            overlay_params=overlay if has_overlay else None,
            clip_duration=duration
        )
        
        # Format escaped path for FFmpeg filter on Windows and Linux
        clean_ass = temp_ass_path.replace("\\", "/").replace(":", "\\:")
        if os.path.isdir(FONTS_DIR):
            clean_fonts_dir = FONTS_DIR.replace("\\", "/").replace(":", "\\:")
            subtitles_filter = f"ass='{clean_ass}':fontsdir='{clean_fonts_dir}'"
        else:
            subtitles_filter = f"ass='{clean_ass}'"

    start_time = max(0.0, float(start_time))
    duration = max(0.1, float(duration))

    try:
        if aspect_ratio == "9:16":
            if fit_mode == "fill":
                # Full Zoom / Crop
                base_vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
                if subtitles_filter:
                    vf_str = f"{base_vf},{subtitles_filter}"
                else:
                    vf_str = base_vf
                cmd = [
                    _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-t", str(duration),
                    "-i", input_path,
                    "-avoid_negative_ts", "make_zero",
                    "-vf", vf_str,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", preset,
                    "-threads", "0",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
            elif fit_mode == "blur":
                # Blurred Background Video
                filter_complex = (
                    "[0:v]split[bg_in][fg_in];"
                    "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    "boxblur=25:5[bg];"
                    "[fg_in]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                    "[bg][fg]overlay=(W-w)/2:(H-h)/2"
                )
                if subtitles_filter:
                    filter_complex += f"[v_out];[v_out]{subtitles_filter}"
                
                cmd = [
                    _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-t", str(duration),
                    "-i", input_path,
                    "-avoid_negative_ts", "make_zero",
                    "-filter_complex", filter_complex,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", preset,
                    "-threads", "0",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
            else:
                # Natural Fit with Solid Color Bars (Black or White)
                clean_color = "white" if pad_color.lower() in ["white", "#ffffff", "#fff"] else "black"
                base_vf = f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color={clean_color}"
                if subtitles_filter:
                    vf_str = f"{base_vf},{subtitles_filter}"
                else:
                    vf_str = base_vf
                cmd = [
                    _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-t", str(duration),
                    "-i", input_path,
                    "-avoid_negative_ts", "make_zero",
                    "-vf", vf_str,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", preset,
                    "-threads", "0",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
        else:
            # Standard Landscape (ensures dimensions are divisible by 2 for x264)
            if subtitles_filter:
                vf_str = f"scale=1920:1080:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,{subtitles_filter}"
            else:
                vf_str = "scale=1920:1080:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
            cmd = [
                _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", input_path,
                "-avoid_negative_ts", "make_zero",
                "-vf", vf_str,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", preset,
                "-threads", "0",
                "-crf", "20",
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", "192k",
                output_path
            ]

        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {process.stderr}")

        return output_path
    finally:
        if temp_ass_path and os.path.exists(temp_ass_path):
            try:
                os.remove(temp_ass_path)
            except Exception:
                pass


def get_video_dimensions(video_path: str):
    """Probes video width and height using ffprobe, fallback to 1920x1080."""
    ffprobe_exe = _find_ffmpeg_exe("ffprobe.exe") or "ffprobe"
    try:
        cmd = [
            ffprobe_exe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            video_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split("x")
            if len(parts) == 2:
                w, h = int(parts[0]), int(parts[1])
                if w > 0 and h > 0:
                    return w, h
        # Fallback: ensure ffprobe is available (may add common PATH)
        if not is_ffprobe_available():
            raise RuntimeError("ffprobe not found. Install FFmpeg which includes ffprobe, and add its 'bin' folder to PATH.")
    except Exception:
        pass
    return 1920, 1080


def burn_full_video_captions(
    input_path: str,
    output_path: str,
    words: list,
    style_options: dict = None,
    aspect_ratio: str = "original",
    fit_mode: str = "fit",
    pad_color: str = "black"
) -> str:
    """
    Burns synchronized captions into the entire full-length video.
    Preserves original audio and full duration without any clipping.
    """
    if not is_ffmpeg_available():
        raise RuntimeError("FFmpeg is not installed or not found in PATH. Please install FFmpeg and ensure its 'bin' folder is added to the system PATH.")

    temp_ass_path = None
    subtitles_filter = ""
    
    orig_w, orig_h = get_video_dimensions(input_path)
    
    if aspect_ratio == "9:16":
        play_w, play_h = 1080, 1920
    elif aspect_ratio == "16:9":
        play_w, play_h = 1920, 1080
    else:
        play_w, play_h = orig_w, orig_h

    opt = style_options or {}
    overlay = opt.get("overlay")
    has_overlay = bool(overlay and isinstance(overlay, dict) and overlay.get("text", "").strip())
    has_words = bool(words and len(words) > 0)

    if has_words or has_overlay:
        temp_ass = tempfile.NamedTemporaryFile(delete=False, suffix=".ass")
        temp_ass_path = temp_ass.name
        temp_ass.close()

        generate_ass_subtitles(
            words=words if has_words else None,
            ass_file_path=temp_ass_path,
            font_family=opt.get("font_family", "Montserrat"),
            font_size=float(opt.get("font_size", 32)),
            text_color=opt.get("text_color", "#ffffff"),
            highlight_color=opt.get("highlight_color", "#facc15"),
            stroke_color=opt.get("stroke_color", "#000000"),
            stroke_width=float(opt.get("stroke_width", 3)),
            box_style=opt.get("box_style", "none"),
            bg_color=opt.get("bg_color", "#000000"),
            bg_opacity=float(opt.get("bg_opacity", 75)),
            pos_y_percent=float(opt.get("pos_y_percent", 72)),
            pos_x_percent=float(opt.get("pos_x_percent", 50)),
            box_width_percent=float(opt.get("box_width_percent", 82)),
            preview_height=float(opt.get("preview_height", 640 if aspect_ratio == "9:16" else 450)),
            anim_style=opt.get("anim_style", "hormozi"),
            play_res_x=play_w,
            play_res_y=play_h,
            overlay_params=overlay if has_overlay else None
        )
        clean_ass = temp_ass_path.replace("\\", "/").replace(":", "\\:")
        if os.path.isdir(FONTS_DIR):
            clean_fonts_dir = FONTS_DIR.replace("\\", "/").replace(":", "\\:")
            subtitles_filter = f"ass='{clean_ass}':fontsdir='{clean_fonts_dir}'"
        else:
            subtitles_filter = f"ass='{clean_ass}'"

    try:
        if aspect_ratio == "9:16":
            if fit_mode == "fill":
                base_vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
                vf_str = f"{base_vf},{subtitles_filter}" if subtitles_filter else base_vf
                cmd = [
                    _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                    "-i", input_path,
                    "-vf", vf_str,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
            elif fit_mode == "blur":
                filter_complex = (
                    "[0:v]split[bg_in][fg_in];"
                    "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    "boxblur=25:5[bg];"
                    "[fg_in]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                    "[bg][fg]overlay=(W-w)/2:(H-h)/2"
                )
                if subtitles_filter:
                    filter_complex += f"[v_out];[v_out]{subtitles_filter}"
                cmd = [
                    _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                    "-i", input_path,
                    "-filter_complex", filter_complex,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
            else:
                clean_color = "white" if pad_color.lower() in ["white", "#ffffff", "#fff"] else "black"
                base_vf = f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color={clean_color}"
                vf_str = f"{base_vf},{subtitles_filter}" if subtitles_filter else base_vf
                cmd = [
                    _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                    "-i", input_path,
                    "-vf", vf_str,
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-ac", "2",
                    "-b:a", "192k",
                    output_path
                ]
        elif aspect_ratio == "16:9":
            base_vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
            vf_str = f"{base_vf},{subtitles_filter}" if subtitles_filter else base_vf
            cmd = [
                _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                "-i", input_path,
                "-vf", vf_str,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-crf", "20",
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", "192k",
                output_path
            ]
        else:
            # Original resolution: pad to even width/height
            pad_filter = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
            vf_str = f"{pad_filter},{subtitles_filter}" if subtitles_filter else pad_filter
            cmd = [
                _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg", "-y",
                "-i", input_path,
                "-vf", vf_str,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-crf", "20",
                "-c:a", "aac",
                "-ac", "2",
                "-b:a", "192k",
                output_path
            ]

        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {process.stderr}")

        return output_path
    finally:
        if temp_ass_path and os.path.exists(temp_ass_path):
            try:
                os.remove(temp_ass_path)
            except Exception:
                pass
