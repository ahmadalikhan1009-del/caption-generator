import os
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

from gemini_analyzer import (
    analyze_transcript_with_gemini,
    transliterate_words_to_roman_urdu,
    transliterate_text_to_roman_urdu,
    VideoAnalysisResult,
    CandidateClip
)
from transliteration import (
    convert_text_by_script_mode,
    convert_words_by_script_mode
)

load_dotenv()

HOOK_WORDS = {
    "secret", "mistake", "never", "always", "truth", "money", "why", "how", 
    "crazy", "warning", "rule", "lesson", "story", "important", "stop", "first",
    "worst", "best", "million", "billion", "billionaire", "advice", "hack",
    "remember", "reason", "imagine", "listen", "fact", "real", "danger",
    "value", "culture", "success", "future", "power", "win", "lose", "change",
    "fail", "failure", "problem", "solution", "system", "habit", "daily",
    "need", "must", "result", "strategy", "simple", "hard", "focus", "life",
    "key", "trick", "mindset", "actually", "believe", "workout", "fitness",
    # Urdu/Hindi transliterated & native engagement markers
    "kya", "kyun", "kaise", "sach", "raaz", "galti", "zindagi", "kamyabi",
    "paisa", "dost", "kabhi", "hamesha", "sunain", "dekhein", "yaad", "faida"
}

DANGLING_CONNECTORS = {
    # English conjunctions, prepositions, open-ended starters
    "and", "but", "or", "so", "because", "if", "when", "that", "which", "who",
    "whom", "whose", "while", "although", "though", "as", "since", "than",
    "whether", "where", "why", "how", "what", "with", "for", "to", "of",
    "in", "on", "at", "by", "into", "onto", "through", "about", "like", "then",
    # Urdu / Hindi transliterated
    "aur", "lekin", "magar", "ya", "k", "ki", "keh", "kyunke", "kyun", "kyunki",
    "kyonki", "agar", "jab", "jahan", "jese", "jaise", "to", "par", "se", "mein",
    "ko", "ka", "ke", "ne", "tak", "liye", "sath", "bhi",
    # Urdu / Hindi native script
    "اور", "لیکن", "مگر", "یا", "کہ", "کیونکہ", "اگر", "جب", "تو", "پر", "سے", "میں", "کو", "کا", "کی", "کے"
}


def clean_word_text(w: str) -> str:
    """Strips punctuation and lowercases for fuzzy/exact token matching."""
    return re.sub(r"[^\w\s]", "", w).strip().lower()


def reconstruct_sentences_from_words(all_words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Groups individual Whisper word timestamps into complete grammatical sentences
    or natural spoken breath units based on punctuation and speech pauses.
    Guarantees that pauses do NOT cut mid-clause on dangling connectors.
    """
    if not all_words:
        return []

    sentences = []
    current_words = []
    sentence_start_idx = 0

    for i, w in enumerate(all_words):
        current_words.append(w)
        word_str = w["word"].strip()

        # Check for terminal punctuation (English, Urdu khatma, Urdu question mark, Hindi purna viram)
        ends_with_terminal = bool(re.search(r"[.?!…۔।॥؟]+$", word_str))
        is_abbrev = bool(re.search(r"^(mr|mrs|ms|dr|prof|vs|etc|st|e\.g|i\.e)\.$", word_str.lower()))
        if is_abbrev:
            ends_with_terminal = False

        # Natural thought boundary: requires meaningful clause length, substantial pause, and no dangling connector
        has_natural_boundary = False
        if i + 1 < len(all_words):
            next_start = all_words[i + 1]["start"]
            current_end = w["end"]
            pause = next_start - current_end
            clean_last = clean_word_text(word_str)
            if pause >= 0.65 and len(current_words) >= 6 and clean_last not in DANGLING_CONNECTORS:
                has_natural_boundary = True
            elif pause >= 1.0 and len(current_words) >= 4 and clean_last not in DANGLING_CONNECTORS:
                has_natural_boundary = True

        is_last_word = (i == len(all_words) - 1)

        # Complete sentence if genuine terminal punctuation found, natural thought boundary, or EOF
        if ends_with_terminal or has_natural_boundary or is_last_word:
            text = " ".join([cw["word"] for cw in current_words]).strip()
            sentences.append({
                "id": len(sentences),
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
                "text": text,
                "start_word_idx": sentence_start_idx,
                "end_word_idx": i,
                "words": list(current_words)
            })
            current_words = []
            sentence_start_idx = i + 1

    # Flush any remaining words
    if current_words:
        text = " ".join([cw["word"] for cw in current_words]).strip()
        sentences.append({
            "id": len(sentences),
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
            "text": text,
            "start_word_idx": sentence_start_idx,
            "end_word_idx": len(all_words) - 1,
            "words": list(current_words)
        })

    return sentences


def find_quote_match_word_index(
    quote: str,
    all_words: List[Dict[str, Any]],
    target_time: float,
    is_start: bool = True,
    search_window_sec: float = 16.0
) -> Optional[int]:
    """
    Finds the exact word index in all_words matching the quote tokens near target_time.
    """
    quote_tokens = [clean_word_text(t) for t in quote.split() if clean_word_text(t)]
    if not quote_tokens:
        return None

    # Filter candidates within search window first
    min_time = max(0.0, target_time - search_window_sec)
    max_time = target_time + search_window_sec

    candidate_indices = [
        i for i, w in enumerate(all_words)
        if min_time <= w["start"] <= max_time
    ]

    best_idx = None
    best_score = 0
    k = len(quote_tokens)

    def _match_in_indices(indices):
        b_idx = None
        b_score = 0
        for idx in indices:
            if idx + k <= len(all_words):
                window_tokens = [clean_word_text(all_words[idx + j]["word"]) for j in range(k)]
                matches = sum(1 for a, b in zip(quote_tokens, window_tokens) if a == b)
                score = matches / k
                if score > b_score and score >= 0.6:
                    b_score = score
                    b_idx = idx if is_start else (idx + k - 1)
        return b_idx, b_score

    if candidate_indices:
        best_idx, best_score = _match_in_indices(candidate_indices)

    # If no reliable match in local window, expand search window moderately (±28s)
    # but never jump across the entire video to prevent matching random identical phrases minutes away
    if best_idx is None:
        expanded_min = max(0.0, target_time - 28.0)
        expanded_max = target_time + 28.0
        expanded_indices = [
            i for i, w in enumerate(all_words)
            if expanded_min <= w["start"] <= expanded_max
        ]
        if expanded_indices:
            best_idx, best_score = _match_in_indices(expanded_indices)

    return best_idx


def snap_to_sentence_boundary(
    word_idx: int,
    sentences: List[Dict[str, Any]],
    is_start: bool = True
) -> int:
    """
    Ensures that a word index strictly respects sentence boundaries.
    If is_start=True, snaps to the beginning of the sentence containing or immediately preceding the word.
    If is_start=False, snaps to the end of the sentence containing the word.
    """
    for s in sentences:
        if s["start_word_idx"] <= word_idx <= s["end_word_idx"]:
            return s["start_word_idx"] if is_start else s["end_word_idx"]
    return word_idx


def align_gemini_clip(
    candidate: CandidateClip,
    all_words: List[Dict[str, Any]],
    sentences: List[Dict[str, Any]],
    min_duration: float = 15.0,
    max_duration: float = 85.0
) -> Optional[Dict[str, Any]]:
    """
    Aligns a Gemini candidate clip to exact Whisper word timestamps with:
    - Quote matching
    - Sentence boundary snapping (NEVER cut mid-sentence)
    - Audio breathing margins
    - Relative word timestamp recalculation for ASS subtitles
    """
    # 1. Match Start Word Index
    start_idx = find_quote_match_word_index(
        candidate.quote_start, all_words, candidate.start_time, is_start=True
    )
    if start_idx is None:
        # Closest sentence start to candidate.start_time
        closest_sentence = min(sentences, key=lambda s: abs(s["start"] - candidate.start_time))
        start_idx = closest_sentence["start_word_idx"]

    # Snap strictly to sentence start
    start_idx = snap_to_sentence_boundary(start_idx, sentences, is_start=True)

    # 2. Match End Word Index
    end_idx = find_quote_match_word_index(
        candidate.quote_end, all_words, candidate.end_time, is_start=False
    )
    if end_idx is None:
        # Closest sentence end to candidate.end_time
        closest_sentence = min(sentences, key=lambda s: abs(s["end"] - candidate.end_time))
        end_idx = closest_sentence["end_word_idx"]

    # Snap strictly to sentence end
    end_idx = snap_to_sentence_boundary(end_idx, sentences, is_start=False)

    if end_idx <= start_idx:
        return None

    # Calculate raw times
    raw_start = all_words[start_idx]["start"]
    raw_end = all_words[end_idx]["end"]
    raw_duration = raw_end - raw_start

    # Adjust if below min_duration by extending to subsequent complete sentences
    if raw_duration < min_duration:
        for s in sentences:
            if s["start_word_idx"] > end_idx:
                test_dur = all_words[s["end_word_idx"]]["end"] - raw_start
                if test_dur <= max_duration:
                    end_idx = s["end_word_idx"]
                    raw_end = all_words[end_idx]["end"]
                    raw_duration = raw_end - raw_start
                    if raw_duration >= min_duration:
                        break
                else:
                    break

    # If raw_duration exceeds max_duration:
    # Do NOT amputate the ending sentence if it holds the answer or conclusion!
    effective_max = max(max_duration, 88.0)
    if raw_duration > effective_max:
        # First, try trimming introductory filler from the START (conversational throat-clearing)
        for s in sentences:
            if s["start_word_idx"] > start_idx and s["end_word_idx"] < end_idx:
                test_start = all_words[s["start_word_idx"]]["start"]
                test_dur = raw_end - test_start
                if test_dur >= min_duration and test_dur <= effective_max:
                    start_idx = s["start_word_idx"]
                    raw_start = test_start
                    raw_duration = test_dur
                    break

    # If still > effective_max, only shrink from the end if the newly remaining final sentence
    # is a complete thought (not ending on an open question or dangling connector)
    if raw_duration > effective_max:
        for s in reversed(sentences):
            if s["end_word_idx"] < end_idx and s["start_word_idx"] >= start_idx:
                test_dur = all_words[s["end_word_idx"]]["end"] - raw_start
                if test_dur >= min_duration:
                    cand_last_word = clean_word_text(all_words[s["end_word_idx"]]["word"])
                    cand_last_text = s["text"].strip()
                    if cand_last_text.endswith(("?", "؟")) or cand_last_word in DANGLING_CONNECTORS:
                        continue
                    end_idx = s["end_word_idx"]
                    raw_end = all_words[end_idx]["end"]
                    raw_duration = raw_end - raw_start
                    break

    # Add safe breathing margin (prevent audio clipping without bleeding into adjacent speech)
    prev_word_end = all_words[start_idx - 1]["end"] if start_idx > 0 else 0.0
    safe_start = max(prev_word_end + 0.04, raw_start - 0.12)
    safe_start = max(0.0, round(safe_start, 3))

    next_word_start = all_words[end_idx + 1]["start"] if end_idx + 1 < len(all_words) else raw_end + 1.0
    safe_end = min(next_word_start - 0.04, raw_end + 0.18)
    safe_end = round(safe_end, 3)

    final_duration = round(safe_end - safe_start, 2)
    if final_duration < min_duration:
        return None

    # Collect all words spoken within the clip's actual video timeframe [safe_start, safe_end]
    clip_words = [
        w for w in all_words
        if (w["end"] >= safe_start and w["start"] <= safe_end)
    ]
    if not clip_words:
        clip_words = all_words[start_idx:end_idx + 1]

    full_text = " ".join([w["word"] for w in clip_words]).strip()

    # Calculate relative timestamps for subtitle burn-in
    relative_words = []
    for w in clip_words:
        rel_start = max(0.0, round(w["start"] - safe_start, 3))
        rel_end = max(rel_start + 0.05, round(w["end"] - safe_start, 3))
        relative_words.append({
            "word": w["word"],
            "start": rel_start,
            "end": rel_end
        })

    return {
        "title": candidate.title.strip(),
        "hook": candidate.hook.strip(),
        "summary": candidate.summary.strip(),
        "start": safe_start,
        "end": safe_end,
        "duration": final_duration,
        "score": candidate.viral_score,
        "score_breakdown": candidate.score_breakdown.model_dump(),
        "why_it_works": candidate.why_it_works.strip(),
        "text_preview": full_text[:140] + ("..." if len(full_text) > 140 else ""),
        "full_text": full_text,
        "words": relative_words
    }


def analyze_sentence_level_fallback(
    sentences: List[Dict[str, Any]],
    all_words: List[Dict[str, Any]],
    min_duration: float = 20.0,
    max_duration: float = 75.0,
    min_score: int = 55
) -> List[Dict[str, Any]]:
    """
    Intelligent sentence-aware fallback algorithm when Gemini API key is missing or offline.
    Evaluates complete sentence combinations, strictly ensuring ZERO mid-sentence cuts
    and penalizing clips that end on open questions or dangling conjunctions without answers.
    """
    if not sentences or not all_words:
        return []

    print("[AI Clipper] Running sentence-aware fallback clipping engine...")
    clips = []

    for s_idx in range(len(sentences)):
        start_sent = sentences[s_idx]
        start_word_idx = start_sent["start_word_idx"]
        raw_start = all_words[start_word_idx]["start"]

        best_cand = None
        best_cand_score = -1

        for e_idx in range(s_idx, min(len(sentences), s_idx + 15)):
            end_sent = sentences[e_idx]
            end_word_idx = end_sent["end_word_idx"]
            raw_end = all_words[end_word_idx]["end"]
            dur = raw_end - raw_start

            if dur < min_duration:
                continue
            if dur > max_duration:
                break

            end_text_clean = end_sent["text"].strip()
            ends_with_q = end_text_clean.endswith(("?", "؟"))
            last_word_clean = clean_word_text(all_words[end_word_idx]["word"])
            ends_with_dangling = last_word_clean in DANGLING_CONNECTORS

            clip_words = all_words[start_word_idx:end_word_idx + 1]
            full_text = " ".join([w["word"] for w in clip_words]).strip()

            base_score = 50
            wps = len(clip_words) / max(0.1, dur)
            density_score = min(25, round((wps / 2.6) * 25))
            hook_count = sum(1 for w in clip_words if clean_word_text(w["word"]) in HOOK_WORDS)
            hook_score = min(20, hook_count * 5)
            punct_score = min(15, (full_text.count("!") * 5) + ((full_text.count("?") + full_text.count("؟")) * 4))

            # Penalty if candidate ends on an open question or dangling connector without resolution
            penalty = 0
            if ends_with_q:
                penalty += 15
            if ends_with_dangling:
                penalty += 20

            total_score = min(98, max(30, base_score + density_score + hook_score + punct_score - penalty))

            if total_score >= min_score and total_score > best_cand_score:
                best_cand_score = total_score
                best_cand = (start_word_idx, end_word_idx, raw_start, raw_end, clip_words, full_text, total_score, hook_score, density_score)

        if best_cand:
            b_start_w, b_end_w, b_raw_start, b_raw_end, b_clip_words, b_full_text, b_total_score, b_hook_score, b_density_score = best_cand
            words_preview = [w["word"] for w in b_clip_words[:8]]
            title_hook = " ".join(words_preview).strip(".,?! ")
            if len(title_hook) > 40:
                title_hook = title_hook[:37] + "..."

            prev_end = all_words[b_start_w - 1]["end"] if b_start_w > 0 else 0.0
            safe_start = max(prev_end + 0.04, b_raw_start - 0.12)
            safe_start = max(0.0, round(safe_start, 3))

            next_start = all_words[b_end_w + 1]["start"] if b_end_w + 1 < len(all_words) else b_raw_end + 1.0
            safe_end = min(next_start - 0.04, b_raw_end + 0.18)
            safe_end = round(safe_end, 3)

            cand_words = [
                w for w in all_words
                if (w["end"] >= safe_start and w["start"] <= safe_end)
            ]
            if not cand_words:
                cand_words = b_clip_words

            rel_words = []
            for w in cand_words:
                rel_words.append({
                    "word": w["word"],
                    "start": max(0.0, round(w["start"] - safe_start, 3)),
                    "end": max(0.05, round(w["end"] - safe_start, 3))
                })

            clips.append({
                "title": f"Key Moment: {title_hook.upper()}",
                "hook": title_hook,
                "summary": b_full_text[:100] + "...",
                "start": safe_start,
                "end": safe_end,
                "duration": round(safe_end - safe_start, 2),
                "score": b_total_score,
                "score_breakdown": {
                    "hook_strength": min(95, b_hook_score * 2),
                    "clarity": 80,
                    "engagement": round(b_density_score * 2.5),
                    "standalone_value": 85,
                    "audience_relevance": 75
                },
                "why_it_works": "Complete narrative concept with verified boundary closure.",
                "text_preview": b_full_text[:140] + ("..." if len(b_full_text) > 140 else ""),
                "full_text": b_full_text,
                "words": rel_words
            })

    return clips


def analyze_viral_clips(
    segments: List[Dict[str, Any]],
    min_duration: float = 18.0,
    max_duration: float = 85.0,
    min_score: int = 55,
    language: str = "en",
    script_mode: str = "original",
    progress_callback = None
) -> List[Dict[str, Any]]:
    """
    Main entry point for AI Video Clipping.
    1. Extracts full word timestamps from Whisper segments.
    2. Reconstructs complete sentence blocks with natural grammatical boundaries.
    3. Calls Gemini API for narrative understanding & complete concept identification.
    4. Aligns boundaries with exact sub-second precision to Whisper words.
    5. Falls back seamlessly to sentence-level heuristic engine if API key is not present.
    6. Deduplicates overlapping moments and sorts chronologically.
    7. Supports English, Hindi, Urdu, Mixed languages, and Roman Urdu script output.
    """
    if not segments:
        return []

    # Flatten all words with timestamps
    all_words = []
    for seg in segments:
        for w in seg.get("words", []):
            clean_w = w["word"].strip()
            if clean_w:
                all_words.append({
                    "word": clean_w,
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3)
                })

    if not all_words:
        return []

    # Reconstruct complete sentences
    sentences = reconstruct_sentences_from_words(all_words)
    if not sentences:
        return []

    processed_clips = []
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if gemini_key:
        print(f"[AI Studio] GEMINI_API_KEY detected. Initiating deep semantic clipping with Gemini ({language})...")
        analysis_result = analyze_transcript_with_gemini(
            sentences, language=language, progress_callback=progress_callback
        )

        if analysis_result and analysis_result.candidate_clips:
            print(f"[AI Studio] Aligning {len(analysis_result.candidate_clips)} Gemini candidates to audio...")
            for candidate in analysis_result.candidate_clips:
                aligned = align_gemini_clip(
                    candidate, all_words, sentences, min_duration, max_duration
                )
                if aligned:
                    processed_clips.append(aligned)
        else:
            print("[AI Studio] Gemini analysis produced no candidates or API failed. Switching to sentence fallback.")

    if not processed_clips:
        if not gemini_key:
            print("[AI Studio] Note: GEMINI_API_KEY not configured. Running intelligent sentence-aware engine.")
        processed_clips = analyze_sentence_level_fallback(
            sentences, all_words, min_duration, max_duration, min_score
        )

    if not processed_clips:
        return []

    # Apply script mode conversion (Roman Urdu, Urdu Script, Hindi Devanagari)
    if script_mode and script_mode != "original":
        print(f"[AI Studio] Applying script mode '{script_mode}' to extracted clips...")
        for c in processed_clips:
            if c.get("words"):
                c["words"] = convert_words_by_script_mode(c["words"], script_mode)
            if c.get("title"):
                c["title"] = convert_text_by_script_mode(c["title"], script_mode)
            if c.get("hook"):
                c["hook"] = convert_text_by_script_mode(c["hook"], script_mode)
            if c.get("text_preview"):
                c["text_preview"] = convert_text_by_script_mode(c["text_preview"], script_mode)
            if c.get("full_text"):
                c["full_text"] = convert_text_by_script_mode(c["full_text"], script_mode)

    # Deduplicate overlapping clips (keep higher viral score)
    processed_clips.sort(key=lambda x: x["score"], reverse=True)
    unique_clips = []

    for c in processed_clips:
        overlaps = False
        for uc in unique_clips:
            # Overlap test: intersection over shorter duration > 0.35
            overlap_start = max(c["start"], uc["start"])
            overlap_end = min(c["end"], uc["end"])
            overlap_duration = max(0.0, overlap_end - overlap_start)
            shorter_duration = min(c["duration"], uc["duration"])

            if shorter_duration > 0 and (overlap_duration / shorter_duration) > 0.35:
                overlaps = True
                break

        if not overlaps:
            unique_clips.append(c)

    # Sort chronologically for timeline display
    unique_clips.sort(key=lambda x: x["start"])

    # Re-assign sequential clean IDs
    for idx, c in enumerate(unique_clips):
        c["id"] = idx + 1

    return unique_clips
