import os
import json
import re
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables from .env file if available
load_dotenv()

class ScoreBreakdown(BaseModel):
    hook_strength: int = Field(description="Score from 1 to 100 on how captivating the opening 3 seconds are")
    clarity: int = Field(description="Score from 1 to 100 on clarity of the idea, context, and message")
    engagement: int = Field(description="Score from 1 to 100 on emotional impact, pacing, and interest")
    standalone_value: int = Field(description="Score from 1 to 100 on whether the clip makes complete sense independently")
    audience_relevance: int = Field(description="Score from 1 to 100 on broad appeal and shareability")

class CandidateClip(BaseModel):
    title: str = Field(description="Short, punchy, viral title for this clip (max 6-8 words)")
    hook: str = Field(description="The opening hook statement or core question")
    summary: str = Field(description="Brief summary of what is discussed in this clip")
    start_time: float = Field(description="Estimated start time in seconds")
    end_time: float = Field(description="Estimated end time in seconds")
    quote_start: str = Field(description="First 4-8 exact words spoken at the beginning of the clip")
    quote_end: str = Field(description="Last 4-8 exact words spoken at the conclusion of the clip")
    viral_score: int = Field(description="Overall virality score from 1 to 100")
    score_breakdown: ScoreBreakdown
    why_it_works: str = Field(description="Explanation of why this clip works well as a standalone short")

class VideoAnalysisResult(BaseModel):
    video_summary: str = Field(description="Overall summary of the entire video content")
    narrative_segments: List[str] = Field(description="List of key topics/themes discussed in the video")
    candidate_clips: List[CandidateClip] = Field(description="List of complete, high-viral clips extracted from the video")


def get_gemini_client():
    """
    Initializes and returns the google-genai Client if GEMINI_API_KEY is configured.
    Returns None if the key is missing or SDK fails to load.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        # Set 25-second network timeout per model attempt to avoid hanging requests
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=25000)
        )
        return client
    except Exception as e:
        print(f"[Gemini Analyzer] Error initializing google-genai client: {e}")
        return None


def get_model_candidate_list(preferred_model: Optional[str] = None) -> List[str]:
    """Returns prioritized list of models for resilience against 503/spikes."""
    pref = preferred_model or os.environ.get("GEMINI_MODEL", "").strip()
    candidates = []
    if pref:
        candidates.append(pref)
    # Robust pool of high-availability flash models supporting structured output
    fallback_pool = [
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.6-flash",
        "gemini-flash-latest"
    ]
    for m in fallback_pool:
        if m not in candidates:
            candidates.append(m)
    return candidates


def format_transcript_for_gemini(sentences: List[Dict[str, Any]]) -> str:
    """
    Formats parsed sentences into a timestamped transcript for Gemini prompt.
    Format: [MM:SS.s -> MM:SS.s] (start_sec - end_sec): Text
    """
    lines = []
    for s in sentences:
        start_sec = s["start"]
        end_sec = s["end"]
        
        m_start, s_start = divmod(start_sec, 60)
        m_end, s_end = divmod(end_sec, 60)
        
        time_str = f"[{int(m_start):02d}:{s_start:04.1f} -> {int(m_end):02d}:{s_end:04.1f}] ({start_sec:.1f}s - {end_sec:.1f}s)"
        lines.append(f"{time_str}: {s['text']}")
    return "\n".join(lines)


def build_system_prompt(language: str = "en") -> str:
    """Builds a culturally and linguistically nuanced virality prompt for Gemini."""
    base_instructions = """You are an elite short-form video editor, viral content strategist, and narrative architect.
Your mission is to analyze a timestamped video transcript and identify the most compelling, high-retention viral moments suitable for YouTube Shorts, TikTok, and Instagram Reels.

CRITICAL RULES FOR SELECTING CLIPS:
1. COMPLETE CONCEPT & NARRATIVE AUTONOMY:
   - Every clip MUST be a 100% self-contained story, lesson, debate, humor, or insight.
   - The viewer must understand the WHO, WHAT, and WHY immediately without having seen any other part of the video.
   - NEVER select clips that rely on unexplained context or pronouns without immediate introduction.

2. ZERO MID-SENTENCE CUTS & ZERO CLIFFHANGERS (STRICT REQUIREMENT):
   - A clip MUST begin at the very start of a sentence or thought. Never cut in the middle of a sentence or explanation.
   - A clip MUST end at the natural conclusion of that sentence or thought.
   - NEVER end on a dangling cliffhanger like "and then...", "because...", "so I told...", or unfinished thoughts.

3. QUESTION + FULL ANSWER / SETUP + CONCLUSION (CRITICAL REQUIREMENT):
   - If a clip opens with or contains a question (e.g. "Why does...", "How do you...", "What is the secret...", "Kya aap jaante hain..."), curiosity gap, setup, or problem statement, the clip MUST NOT end until the speaker has delivered the complete answer, explanation, resolution, or conclusion.
   - A clip that poses a question or setup but cuts off before delivering the answer is a CRITICAL FAILURE. You MUST extend the clip boundary so the full resolution is included.
   - If a speaker starts a story or example to demonstrate a point, include both the story and the concluding takeaway/lesson.
   - NEVER invent dialogue, answers, or details that are not in the transcript.

4. TARGET DURATION (PRIORITIZE COMPLETION OVER RIGID TIME):
   - Standard viral clip duration is 20 to 60 seconds (allowed range: 15 to 85 seconds).
   - If an answer or explanation needs 70-80 seconds to reach its complete conclusion, DO NOT cut it short at 30 seconds. Allow the thought to resolve completely.

5. EXACT QUOTES FOR SUB-SECOND ALIGNMENT:
   - quote_start: Must be the EXACT first 4 to 8 words spoken at the beginning of the clip as they appear in the transcript.
   - quote_end: Must be the EXACT last 4 to 8 words spoken at the end of the clip as they appear in the transcript.

6. ACCURATE VIRALITY SCORING (1-100):
   - Provide a realistic assessment across all 5 dimensions:
     * hook_strength: Power of opening 3 seconds
     * clarity: Immediate comprehension without external context
     * engagement: Pacing, emotional resonance, and intrigue
     * standalone_value: Completeness of the takeaway/story
     * audience_relevance: Shareability and universal appeal
"""

    if language in ["hi", "hindi"]:
        return base_instructions + """
7. HINDI LANGUAGE & CULTURAL SPECIFICS:
   - The dialogue is in spoken Hindi (or conversational Hindi).
   - Spoken Hindi often uses rhetorical framing ("Dekhiye, main aapko ek baat batata hoon...", "Sawaal yeh hai...", "Asal wajah yeh hai...").
   - You MUST ensure the clip includes the full substantive answer or moral ("To iska jawab yeh hai...", "Wajah yeh hai...", "Iska matlab yeh hai...").
   - Titles and hooks should be engaging, natural Hindi/Hinglish suitable for YouTube Shorts / Reels.
   - Quotes must match the spoken Hindi words in the transcript exactly.
"""
    elif language in ["ur", "urdu"]:
        return base_instructions + """
7. URDU LANGUAGE & CULTURAL SPECIFICS:
   - The dialogue is in spoken Urdu (Nastaliq or conversational Urdu).
   - Spoken Urdu often uses rhetorical openers ("Dekhein...", "Sawaal yeh paida hota hai k...", "Main aapko bataoon...", "Asal baat yeh hai k...").
   - You MUST ensure the clip includes the full substantive answer, explanation, or moral ("To uska hal yeh hai...", "Iska jawab yeh hai...", "Wajah yeh hai k...").
   - Titles and hooks should be natural, engaging Urdu/Roman Urdu suitable for social media feeds.
   - Quotes must match the spoken Urdu words in the transcript exactly.
"""
    elif language in ["mixed", "hinglish"]:
        return base_instructions + """
7. HINDI / URDU MIXED & BILINGUAL SPECIFICS:
   - The dialogue is in mixed Hindi/Urdu/English (Hinglish/conversational South Asian speech).
   - Capture complete moments where questions and their answers are fully delivered.
   - Quotes must match the spoken words in the transcript exactly.
"""
    return base_instructions


def chunk_sentences(
    sentences: List[Dict[str, Any]],
    chunk_size: int = 250,
    overlap: int = 20
) -> List[List[Dict[str, Any]]]:
    """
    Splits a long transcript into overlapping sentence chunks for Gemini API calls.
    chunk_size=250 ≈ 15–20 minutes of typical speech per chunk.
    overlap=20 sentences shared between adjacent chunks to avoid missing clips at
    chunk boundaries. For short transcripts that fit in one chunk, returns as-is.
    """
    if len(sentences) <= chunk_size:
        return [sentences]
    chunks = []
    start = 0
    while start < len(sentences):
        end = min(start + chunk_size, len(sentences))
        chunks.append(sentences[start:end])
        if end >= len(sentences):
            break
        start = end - overlap  # Overlap so boundary clips appear in both adjacent chunks
    return chunks


def _call_gemini_chunk(
    client,
    chunk: List[Dict[str, Any]],
    language: str,
    model_name: Optional[str],
    system_instruction: str
) -> Optional[VideoAnalysisResult]:
    """
    Calls Gemini API for a single sentence chunk with full model failover.
    Isolated so the chunked orchestrator can call it independently per chunk.
    """
    models_to_try = get_model_candidate_list(model_name)
    formatted_transcript = format_transcript_for_gemini(chunk)
    if not formatted_transcript.strip():
        return None

    lang_desc = {
        "en": "English", "hi": "Hindi", "ur": "Urdu", "mixed": "Hindi/Urdu Mixed"
    }.get(language, "Spoken")

    user_prompt = f"""Analyze the following timestamped {lang_desc} video transcript and discover all high-viral, complete-concept clips according to the instructions.

TRANSCRIPT:
---
{formatted_transcript}
---

Extract all distinct moments that make outstanding standalone viral clips. Ensure quotes match the transcript exactly."""

    from google.genai import types

    for target_model in models_to_try:
        try:
            print(f"[Gemini Analyzer] Sending {len(chunk)} sentences to '{target_model}' ({lang_desc})...")
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=VideoAnalysisResult,
            )
            response = client.models.generate_content(
                model=target_model,
                contents=user_prompt,
                config=config,
            )
            if not response or not response.text:
                print(f"[Gemini Analyzer] Empty response from '{target_model}'. Trying next model...")
                continue
            result_data = json.loads(response.text)
            result = VideoAnalysisResult(**result_data)
            print(f"[Gemini Analyzer] '{target_model}': {len(result.candidate_clips)} candidates found.")
            return result
        except Exception as e:
            print(f"[Gemini Analyzer] '{target_model}' failed: {str(e)[:120]}...")
            continue

    return None


def analyze_transcript_with_gemini(
    sentences: List[Dict[str, Any]],
    language: str = "en",
    model_name: Optional[str] = None,
    progress_callback = None
) -> Optional[VideoAnalysisResult]:
    """
    Sends the formatted timestamped transcript to Gemini API using google-genai SDK
    with automatic chunking for long videos, parallel processing, model failover, and retries.

    Long transcripts (>250 sentences, ~15+ min of speech) are split into overlapping
    250-sentence chunks so each API call stays within the context window and avoids
    response timeouts. Chunks are processed in parallel (up to 3 concurrent workers)
    to dramatically reduce wait time for long videos. All candidate clips are merged
    and deduplicated downstream in analyze_viral_clips().
    """
    client = get_gemini_client()
    if not client:
        return None

    if not sentences:
        return None

    # Split long transcripts: 250 sentences ≈ 15–20 min of typical speech per chunk
    CHUNK_SIZE = 250
    CHUNK_OVERLAP = 20  # Overlap sentences to avoid missing clips at chunk boundaries
    chunks = chunk_sentences(sentences, CHUNK_SIZE, CHUNK_OVERLAP)
    system_instruction = build_system_prompt(language)

    if len(chunks) > 1:
        print(f"[Gemini Analyzer] Long transcript: {len(sentences)} sentences → {len(chunks)} chunks for parallel analysis.")

    all_candidates: List = []

    if len(chunks) == 1:
        chunk_result = _call_gemini_chunk(client, chunks[0], language, model_name, system_instruction)
        if chunk_result and chunk_result.candidate_clips:
            all_candidates.extend(chunk_result.candidate_clips)
        if progress_callback:
            progress_callback(1, 1)
    else:
        # Process chunks in parallel (max 3 concurrent requests to respect rate limits)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(3, len(chunks))
        results = [None] * len(chunks)
        completed_count = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_call_gemini_chunk, client, chunk, language, model_name, system_instruction): idx
                for idx, chunk in enumerate(chunks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    res = future.result()
                    results[idx] = res
                except Exception as e:
                    print(f"[Gemini Analyzer] Chunk {idx + 1} worker encountered error: {e}")
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, len(chunks))

        for r in results:
            if r and r.candidate_clips:
                all_candidates.extend(r.candidate_clips)

    if not all_candidates:
        print("[Gemini Analyzer] All chunks returned no candidates. Falling back to sentence engine.")
        return None

    print(f"[Gemini Analyzer] Total: {len(all_candidates)} candidates discovered across {len(chunks)} chunk(s).")
    return VideoAnalysisResult(
        video_summary=f"Analyzed {len(sentences)} sentences across {len(chunks)} segment(s).",
        narrative_segments=[],
        candidate_clips=all_candidates
    )


from transliteration import (
    convert_text_to_roman_urdu,
    convert_words_list_to_roman_urdu,
    is_valid_roman_urdu
)


def transliterate_text_to_roman_urdu(text: str, client=None) -> str:
    """
    Transliterates Hindi/Urdu text to clean, natural Roman Urdu in Latin script.
    Does NOT translate into English.
    Guarantees Latin script output through dictionary & phonetic transliteration.
    """
    if not text or not text.strip():
        return ""
    if not any(('\u0900' <= ch <= '\u097F') or ('\u0600' <= ch <= '\u06FF') for ch in text):
        return text  # Already Latin script

    # Attempt with Gemini if available
    if client is None:
        client = get_gemini_client()
    if client:
        models_to_try = get_model_candidate_list()
        prompt = f"Transliterate the following Hindi/Urdu text into clean, social-media style Roman Urdu (Latin alphabet). Do NOT translate into English. Return ONLY the transliterated text. Text: {text}"

        for m in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config={"http_options": {"timeout": 4000}}
                )
                if resp and resp.text:
                    cleaned = resp.text.strip().strip('"\'')
                    if is_valid_roman_urdu(cleaned):
                        return cleaned
            except Exception:
                continue

    # Guaranteed local transliteration fallback
    return convert_text_to_roman_urdu(text)


def transliterate_words_to_roman_urdu(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transliterates word tokens from Devanagari/Urdu script into Roman Urdu (Latin script)
    while strictly preserving the exact start and end timestamps.
    """
    if not words:
        return []

    # Check if words actually contain Indic or Arabic characters
    has_indic_or_arabic = any(
        any(('\u0900' <= ch <= '\u097F') or ('\u0600' <= ch <= '\u06FF') for ch in w.get("word", ""))
        for w in words
    )
    if not has_indic_or_arabic:
        return words

    return convert_words_list_to_roman_urdu(words)

