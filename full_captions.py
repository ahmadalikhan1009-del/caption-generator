import os
import tempfile
from typing import List, Dict, Any, Optional
from faster_whisper import WhisperModel
from video_utils import (
    extract_audio_fast,
    generate_srt_content,
    generate_vtt_content,
    generate_txt_content
)
from transliteration import (
    convert_text_by_script_mode,
    convert_words_by_script_mode
)

def process_full_video_captions(
    video_path: str,
    whisper_engine: WhisperModel,
    language: Optional[str] = "en",
    script_mode: str = "original",
    cancel_check: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Dedicated workflow for Module 3: Full English Video Captions.
    Generates word and sentence timestamps for the full video duration without ANY clipping.
    Outputs full transcript with words and segments.
    """
    audio_temp = video_path + "_full_audio.wav"
    try:
        proc_audio_path = extract_audio_fast(video_path, audio_temp)
        
        # Module 3 is strictly English audio only
        whisper_lang = "en"
        if language and language.lower() in ["en", "english"]:
            whisper_lang = "en"

        print(f"[Full Captions] Transcribing full audio (lang={whisper_lang or 'auto-detect'})...")
        segments_gen, info = whisper_engine.transcribe(
            proc_audio_path,
            language=whisper_lang,
            word_timestamps=True,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False
        )

        detected_lang = info.language if hasattr(info, "language") else (whisper_lang or "unknown")
        segments_list = []
        all_words = []

        def _collect_segments(gen):
            s_list = []
            w_list = []
            for seg in gen:
                if cancel_check and cancel_check():
                    print("[Full Captions] Analysis cancelled by user request.")
                    raise RuntimeError("Analysis cancelled.")
                clean_text = seg.text.strip()
                if not clean_text:
                    continue

                seg_words = []
                if seg.words:
                    for w in seg.words:
                        cw = w.word.strip()
                        if cw:
                            seg_words.append({
                                "word": cw,
                                "start": round(w.start, 3),
                                "end": round(w.end, 3)
                            })

                if not seg_words and clean_text:
                    text_words = clean_text.split()
                    if text_words:
                        dur = max(0.1, seg.end - seg.start)
                        w_dur = dur / len(text_words)
                        for i, tw in enumerate(text_words):
                            seg_words.append({
                                "word": tw.strip(),
                                "start": round(seg.start + i * w_dur, 3),
                                "end": round(seg.start + (i + 1) * w_dur, 3)
                            })

                s_list.append({
                    "id": len(s_list) + 1,
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "text": clean_text,
                    "words": seg_words
                })
                w_list.extend(seg_words)
            return s_list, w_list

        segments_list, all_words = _collect_segments(segments_gen)

        # Fallback: if VAD filtered out everything on audio with music/intro, retry without VAD
        if not segments_list:
            print("[Full Captions] VAD produced 0 segments. Retrying without VAD filter for maximum speech recovery...")
            fallback_gen, _ = whisper_engine.transcribe(
                proc_audio_path,
                language=whisper_lang,
                word_timestamps=True,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False
            )
            segments_list, all_words = _collect_segments(fallback_gen)

        if not segments_list:
            return {
                "speech_detected": False,
                "message": "No audible speech was detected in this video.",
                "detected_language": detected_lang,
                "segments": [],
                "srt": "",
                "vtt": "",
                "txt": ""
            }

        # Handle script mode conversion (Roman Urdu, Urdu Script, Hindi Devanagari)
        if script_mode and script_mode != "original":
            print(f"[Full Captions] Applying script mode '{script_mode}' to full transcript...")
            for seg in segments_list:
                seg["text"] = convert_text_by_script_mode(seg["text"], script_mode)
                if seg.get("words"):
                    seg["words"] = convert_words_by_script_mode(seg["words"], script_mode)

        # Generate standard subtitle formats
        srt_text = generate_srt_content(segments_list)
        vtt_text = generate_vtt_content(segments_list)
        txt_text = generate_txt_content(segments_list, include_timestamps=True)

        return {
            "speech_detected": True,
            "detected_language": detected_lang,
            "total_segments": len(segments_list),
            "total_words": len(all_words),
            "duration": round(segments_list[-1]["end"] if segments_list else 0.0, 2),
            "segments": segments_list,
            "words": all_words,
            "srt": srt_text,
            "vtt": vtt_text,
            "txt": txt_text
        }

    finally:
        if os.path.exists(audio_temp):
            try:
                os.remove(audio_temp)
            except Exception:
                pass
