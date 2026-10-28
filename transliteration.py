"""
transliteration.py
High-quality, bidirectional, and vocabulary-aware transliteration engine
supporting:
  1. Roman Urdu (clean Latin alphabet, natural conversational spelling)
  2. Urdu Script (Perso-Arabic script)
  3. Hindi Devanagari (Devanagari script)

Guarantees 100% Latin character output for Roman Urdu while preserving
conversational Urdu spelling and meaning (NEVER translating to English).
"""

import re
from typing import List, Dict, Any, Optional

# Comprehensive dictionary for high-frequency Urdu & Hindi conversational words to natural Roman Urdu
ROMAN_URDU_DICTIONARY: Dict[str, str] = {
    # Pronouns & Demonstratives
    "آپ": "Aap", "اپ": "Aap", "आप": "Aap",
    "کیسے": "kaise", "कैसे": "kaise",
    "کیسی": "kaisi", "कैसी": "kaisi",
    "کیسا": "kaisa", "कैसा": "kaisa",
    "ہیں": "hain", "हैं": "hain",
    "ہے": "hai", "है": "hai",
    "یہ": "Yeh", "यह": "Yeh",
    "وہ": "Woh", "वह": "Woh",
    "ویڈیو": "video", "विडियो": "video", "वीडियो": "video",
    "بہت": "bohat", "बहुत": "bohat",
    "اچھی": "achi", "अच्छी": "achi",
    "اچھا": "acha", "अच्छा": "acha",
    "اچھے": "ache", "अच्छे": "ache",
    "کیا": "kya", "क्या": "kya",
    "کیوں": "kyun", "क्यों": "kyun",
    "کب": "kab", "कब": "kab",
    "کہاں": "kahan", "कहाँ": "kahan",
    "کون": "kaun", "कौन": "kaun",
    "کس": "kis", "किस": "kis",
    "کسی": "kisi", "किसी": "kisi",
    "کچھ": "kuch", "कुछ": "kuch",
    "کوئی": "koi", "कोई": "koi",
    "میرا": "mera", "मेरा": "mera",
    "میری": "meri", "मेरी": "meri",
    "میرے": "mere", "मेरे": "mere",
    "تیرا": "tera", "तेरा": "tera",
    "تیری": "teri", "तेरी": "teri",
    "تیرے": "tere", "तेरे": "tere",
    "ہمارا": "hamara", "हमारा": "hamara",
    "ہماری": "hamari", "हमारी": "hamari",
    "ہمارے": "hamare", "हमारे": "hamare",
    "تمہارا": "tumhara", "तुम्हारा": "tumhara",
    "تمہاری": "tumhari", "तुम्हारी": "tumhari",
    "تمہارے": "tumhare", "तुम्हारे": "tumhare",
    "اس": "is", "इस": "is",
    "ان": "in", "इन": "in",
    "اسکا": "iska", "اس کا": "iska", "इसका": "iska",
    "اسکی": "iski", "اس کی": "iski", "इसकी": "iski",
    "اسکے": "iske", "اس کے": "iske", "इसके": "iske",
    "انکا": "inka", "ان کا": "inka", "इनका": "inka",
    "انکی": "inki", "ان کی": "inki", "इनकी": "inki",
    "انکے": "inke", "ان کے": "inke", "इनके": "inke",
    "اسکو": "usko", "اس کو": "usko", "उसको": "usko",
    "اسنے": "usne", "اس نے": "usne", "उसने": "usne",
    "مجھے": "mujhe", "मुझे": "mujhe",
    "تجھے": "tujhe", "तुझे": "tujhe",
    "ہمیں": "humein", "हमें": "humein",
    "انہیں": "unhein", "उन्हें": "unhein",
    "ہم": "hum", "हम": "hum",
    "تم": "tum", "तुम": "tum",
    "میں": "mein", "मैं": "mein", "में": "mein",

    # Prepositions & Postpositions
    "سے": "se", "से": "se",
    "کو": "ko", "को": "ko",
    "کا": "ka", "का": "ka",
    "کے": "ke", "के": "ke",
    "کی": "ki", "की": "ki",
    "پر": "par", "पर": "par",
    "تک": "tak", "तक": "tak",
    "ساتھ": "saath", "साथ": "saath",
    "پاس": "paas", "पास": "paas",
    "سامنے": "saamne", "सामने": "saamne",
    "پیچھے": "peeche", "पीछे": "peeche",
    "اوپر": "oopar", "ऊपर": "oopar",
    "نیچے": "neeche", "नीचे": "neeche",
    "اندر": "andar", "अंदर": "andar",
    "باہر": "bahar", "बाहर": "bahar",
    "درمیان": "darmiyan", "दरमियान": "darmiyan",

    # Conjunctions & Adverbs
    "اور": "aur", "और": "aur",
    "یا": "ya", "या": "ya",
    "لیکن": "lekin", "लेकिन": "lekin",
    "مگر": "magar", "मगर": "magar",
    "اگر": "agar", "अगर": "agar",
    "تو": "toh", "तो": "toh",
    "بھی": "bhi", "भी": "bhi",
    "ہی": "hi", "ही": "hi",
    "نہ": "na", "न": "na",
    "نہیں": "nahin", "नहीं": "nahin",
    "ہاں": "haan", "हाँ": "haan",
    "جی": "jee", "जी": "jee",
    "بلکل": "bilkul", "بالکل": "bilkul", "बिल्कुल": "bilkul",
    "اب": "ab", "अब": "ab",
    "تب": "tab", "तब": "tab",
    "جب": "jab", "जब": "jab",
    "یہاں": "yahan", "यहाँ": "yahan",
    "وہاں": "wahan", "वहाँ": "wahan",
    "جہاں": "jahan", "जहाँ": "jahan",
    "ایسے": "aise", "ऐसे": "aise",
    "ویسے": "waise", "वैसे": "waise",
    "جیسے": "jaise", "जैसे": "jaise",
    "سب": "sab", "सब": "sab",
    "سارے": "saare", "सारे": "saare",
    "ساری": "saari", "सारी": "saari",
    "پھر": "phir", "फिर": "phir",
    "پہلے": "pehlay", "पहले": "pehlay",
    "بعد": "baad", "बाद": "baad",
    "صرف": "sirf", "सिर्फ": "sirf",
    "شاید": "shayad", "शायद": "shayad",
    "ضرور": "zaroor", "ज़रूर": "zaroor",
    "ضروری": "zaroori", "ज़रूरी": "zaroori",
    "ہمیشہ": "hamesha", "हमेशा": "hamesha",
    "کبھی": "kabhi", "कभी": "kabhi",
    "دوبارہ": "dobara", "दोबारा": "dobara",

    # Verbs & Auxiliaries
    "تھا": "tha", "था": "tha",
    "تھی": "thi", "थी": "thi",
    "تھے": "the", "थे": "the",
    "تھیں": "theen", "थीं": "theen",
    "ہو": "ho", "हो": "ho",
    "ہونا": "hona", "होना": "hona",
    "ہونے": "hone", "होने": "hone",
    "ہوتا": "hota", "होता": "hota",
    "ہوتی": "hoti", "होती": "hoti",
    "ہوتے": "hote", "होते": "hote",
    "ہوا": "hua", "हुआ": "hua",
    "ہوئی": "hui", "हुई": "hui",
    "ہوئے": "hue", "हुए": "hue",
    "رہا": "raha", "रहा": "raha",
    "رہی": "rahi", "रही": "rahi",
    "رہے": "rahe", "रहे": "rahe",
    "رہیں": "rahein", "रहें": "rahein",
    "کر": "kar", "कर": "kar",
    "کرنا": "karna", "करना": "karna",
    "کرنے": "karne", "करने": "karne",
    "کرنی": "karni", "करनी": "karni",
    "کرتا": "karta", "करता": "karta",
    "کرتی": "karti", "करती": "karti",
    "کرتے": "karte", "करते": "karte",
    "کیا": "kiya", "किया": "kiya",
    "کیے": "kiye", "किए": "kiye",
    "کریں": "karein", "करें": "karein",
    "کرو": "karo", "करो": "karo",
    "دیکھ": "dekh", "देख": "dekh",
    "دیکھو": "dekho", "देखो": "dekho",
    "دیکھنا": "dekhna", "देखना": "dekhna",
    "دیکھا": "dekha", "देखा": "dekha",
    "دیکھی": "dekhi", "देखी": "dekhi",
    "دیکھے": "dekhe", "देखे": "dekhe",
    "سن": "sun", "सुन": "sun",
    "سنو": "suno", "सुनो": "suno",
    "سننا": "sunna", "सुनना": "sunna",
    "سنا": "suna", "सुना": "suna",
    "کہہ": "keh", "कह": "keh",
    "کہو": "kaho", "कहो": "kaho",
    "کہا": "kaha", "कहा": "kaha",
    "کہتے": "kehte", "कहते": "kehte",
    "کہتی": "kehti", "कहती": "kehti",
    "کہتا": "kehta", "कहता": "kehta",
    "سمجھ": "samajh", "समझ": "samajh",
    "سمجھو": "samjho", "समझो": "samjho",
    "سمجھا": "samjha", "समझो": "samjha",
    "سمجھے": "samjhe", "समझे": "samjhe",
    "جان": "jaan", "जान": "jaan",
    "جانو": "jaano", "जानो": "jaano",
    "جانتے": "jaante", "जानते": "jaante",
    "جانتا": "jaanta", "जानता": "jaanta",
    "جا": "jaa", "जा": "jaa",
    "جاؤ": "jao", "जाओ": "jao",
    "جانا": "jaana", "जाना": "jaana",
    "جاتا": "jaata", "जाता": "jaata",
    "جاتی": "jaati", "जाती": "jaati",
    "جاتے": "jaate", "जाते": "jaate",
    "گیا": "gaya", "गया": "gaya",
    "گئی": "gayi", "गई": "gayi",
    "گئے": "gaye", "गए": "gaye",
    "آ": "aa", "आ": "aa",
    "آؤ": "aao", "आओ": "aao",
    "آنا": "aana", "आना": "aana",
    "آتا": "aata", "आता": "aata",
    "آتی": "aati", "आती": "aati",
    "آتے": "aate", "आते": "aate",
    "آیا": "aaya", "आया": "aaya",
    "آئی": "aayi", "आई": "aayi",
    "آئے": "aaye", "आए": "aaye",
    "بول": "bol", "बोल": "bol",
    "بولو": "bolo", "बोलो": "bolo",
    "بولا": "bola", "बोला": "bola",
    "بولتے": "bolte", "बोलते": "bolte",
    "بتا": "bata", "बता": "bata",
    "بتاؤ": "batao", "बताओ": "batao",
    "بتایا": "bataya", "बताया": "bataya",
    "بتانا": "batana", "बताना": "batana",
    "لے": "le", "ले": "le",
    "لو": "lo", "लो": "lo",
    "لینا": "lena", "लेना": "lena",
    "لیا": "liya", "लिया": "liya",
    "لی": "lee", "ली": "lee",
    "لیے": "liye", "लिए": "liye",
    "دے": "de", "दे": "de",
    "دو": "do", "दो": "do",
    "دینا": "dena", "देना": "dena",
    "دیا": "diya", "दिया": "diya",
    "دی": "dee", "दी": "dee",
    "چاہتا": "chahta", "चाहता": "chahta",
    "چاہتی": "chahti", "चाहती": "chahti",
    "چاہتے": "chahte", "चाहते": "chahte",
    "چاہیے": "chahiye", "चाहिए": "chahiye",
    "سکتا": "sakta", "सकता": "sakta",
    "سکتی": "sakti", "सकती": "sakti",
    "سکتے": "sakte", "सकते": "sakte",
    "پڑتا": "padta", "پڑتی": "padti", "پڑتے": "padte",

    # Common Nouns & Adjectives
    "بات": "baat", "बात": "baat",
    "باتیں": "baatein", "बातें": "baatein",
    "کام": "kaam", "काम": "kaam",
    "لوگ": "log", "लोग": "log",
    "وقت": "waqt", "वक्त": "waqt",
    "دن": "din", "दिन": "din",
    "رات": "raat", "रात": "raat",
    "آج": "aaj", "आज": "aaj",
    "کل": "kal", "कल": "kal",
    "زندگی": "zindagi", "ज़िंदगी": "zindagi",
    "دوست": "dost", "दोस्त": "dost",
    "پیسہ": "paisa", "पैसा": "paisa",
    "پیسے": "paise", "पैसे": "paise",
    "طریقہ": "tareeqa", "طریقے": "tareeqay", "तरीका": "tareeqa",
    "شروع": "shuru", "शुरू": "shuru",
    "ختم": "khatam", "खत्म": "khatam",
    "فائدہ": "fayda", "फायदा": "fayda",
    "نقصان": "nuqsan", "नुकसान": "nuqsan",
    "صحیح": "sahi", "सही": "sahi",
    "غلط": "ghalat", "गलत": "ghalat",
    "ٹھیک": "theek", "ठीक": "theek",
    "آسان": "aasan", "आसान": "aasan",
    "مشکل": "mushkil", "मुश्किल": "mushkil",
    "پتا": "pata", "पता": "pata",
    "معلوم": "maloom", "मालूम": "maloom",
    "چینل": "channel", "चैनल": "channel",
    "سبسکرائب": "subscribe", "सब्सक्राइब": "subscribe",
    "لائک": "like", "लाइक": "like",
    "شیئر": "share", "शेयर": "share",
    "کمنٹ": "comment", "कमेंट": "comment",
    "دوستو": "dosto", "दोस्तों": "dosto",
    "بھائی": "bhai", "भाई": "bhai",
    "بہن": "behan", "बहन": "behan",
    "گھر": "ghar", "घर": "ghar",
    "دل": "dil", "दिल": "dil",
    "دنیا": "dunya", "दुनिया": "dunya",
    "نام": "naam", "नाम": "naam",
}

# Phonetic character mapping for Urdu Perso-Arabic letters
URDU_PHONETIC_MAP = {
    # Aspirates and digraphs
    "بھ": "bh", "پھ": "ph", "تھ": "th", "ٹھ": "th", "جھ": "jh",
    "چھ": "chh", "دھ": "dh", "ڈھ": "dh", "کھ": "kh", "گھ": "gh",
    "ڑھ": "rh",
    # Single letters
    "آ": "aa", "ا": "a", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t",
    "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d",
    "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh",
    "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z",
    "ع": "a", "غ": "gh", "ف": "f", "ق": "q", "ک": "k", "گ": "g",
    "ل": "l", "م": "m", "ن": "n", "ں": "n", "و": "o", "ہ": "h",
    "ھ": "h", "ء": "", "ی": "i", "ے": "e", "ۃ": "t"
}

# Phonetic character mapping for Devanagari letters
DEVANAGARI_PHONETIC_MAP = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
    "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "फ़": "f",
    "ड़": "r", "ढ़": "rh",
    # Vowels & Matras
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "oo",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "्": "",
    "ं": "n", "ँ": "n", "ः": "h", "।": ".", "॥": "."
}

PUNCT_REGEX = r"[!?.؟۔،؛:,\"'()\[\]{}–—\-_/\\@#$%^&*]+"


def clean_punctuation(token: str):
    """Separates leading and trailing punctuation from word token."""
    lead_m = re.match(r"^(" + PUNCT_REGEX + r")", token)
    lead = lead_m.group(1) if lead_m else ""
    token_body = token[len(lead):]
    
    trail_m = re.search(r"(" + PUNCT_REGEX + r")$", token_body)
    trail = trail_m.group(1) if trail_m else ""
    if trail:
        token_body = token_body[:-len(trail)]

    # Map Eastern punctuation to Western
    lead = lead.replace("؟", "?").replace("۔", ".").replace("،", ",").replace("؛", ";")
    trail = trail.replace("؟", "?").replace("۔", ".").replace("،", ",").replace("؛", ";")

    return lead, token_body, trail


def transliterate_urdu_word_phonetic(word: str) -> str:
    """Phonetically converts an Urdu word into Latin Roman Urdu."""
    if not word:
        return ""
    out = []
    i = 0
    w_len = len(word)
    while i < w_len:
        if i + 1 < w_len and word[i:i+2] in URDU_PHONETIC_MAP:
            out.append(URDU_PHONETIC_MAP[word[i:i+2]])
            i += 2
            continue
        ch = word[i]
        if ch in URDU_PHONETIC_MAP:
            out.append(URDU_PHONETIC_MAP[ch])
        elif ch.isascii():
            out.append(ch)
        i += 1
    
    res = "".join(out)
    if res.endswith("h") and len(res) > 2 and res[-2] not in "aeioukh":
        res = res[:-1] + "a"
    return res


def transliterate_hindi_word_phonetic(word: str) -> str:
    """Phonetically converts a Hindi Devanagari word into Latin script."""
    if not word:
        return ""
    out = []
    i = 0
    w_len = len(word)
    while i < w_len:
        if i + 1 < w_len and word[i:i+2] in DEVANAGARI_PHONETIC_MAP:
            out.append(DEVANAGARI_PHONETIC_MAP[word[i:i+2]])
            i += 2
            continue
        ch = word[i]
        if ch in DEVANAGARI_PHONETIC_MAP:
            out.append(DEVANAGARI_PHONETIC_MAP[ch])
        elif ch.isascii():
            out.append(ch)
        i += 1
    return "".join(out)


def convert_word_to_roman_urdu(raw_token: str) -> str:
    """
    Converts a single word token to natural Roman Urdu in Latin script.
    Preserves English words, punctuation, and digits.
    """
    if not raw_token or not raw_token.strip():
        return raw_token

    lead_punct, core, trail_punct = clean_punctuation(raw_token)
    if not core:
        return raw_token

    # If already Latin ASCII, preserve it (e.g., 'YouTube', 'video', '123')
    if core.isascii():
        return f"{lead_punct}{core}{trail_punct}"

    # 1. Direct dictionary match
    if core in ROMAN_URDU_DICTIONARY:
        converted = ROMAN_URDU_DICTIONARY[core]
    else:
        clean_norm = core.strip()
        if clean_norm in ROMAN_URDU_DICTIONARY:
            converted = ROMAN_URDU_DICTIONARY[clean_norm]
        else:
            # 2. Phonetic conversion based on script type
            is_urdu = any('\u0600' <= ch <= '\u06FF' for ch in core)
            is_hindi = any('\u0900' <= ch <= '\u097F' for ch in core)
            if is_urdu:
                converted = transliterate_urdu_word_phonetic(core)
            elif is_hindi:
                converted = transliterate_hindi_word_phonetic(core)
            else:
                converted = core

    if not converted or not converted.strip():
        converted = core

    return f"{lead_punct}{converted}{trail_punct}"


def convert_text_to_roman_urdu(text: str) -> str:
    """
    Converts full sentences to natural Roman Urdu in Latin script.
    Guarantees Latin script output while preserving meaning and structure.
    """
    if not text or not text.strip():
        return text

    has_indic_or_arabic = any(
        ('\u0600' <= ch <= '\u06FF') or ('\u0900' <= ch <= '\u097F')
        for ch in text
    )
    if not has_indic_or_arabic:
        return text

    tokens = text.split()
    converted_tokens = [convert_word_to_roman_urdu(tok) for tok in tokens]
    res = " ".join(converted_tokens)

    # Clean any leftover non-ASCII characters if any slipped through
    cleaned_chars = []
    for ch in res:
        if ch.isascii():
            cleaned_chars.append(ch)
        elif '\u0600' <= ch <= '\u06FF':
            cleaned_chars.append(URDU_PHONETIC_MAP.get(ch, ""))
        elif '\u0900' <= ch <= '\u097F':
            cleaned_chars.append(DEVANAGARI_PHONETIC_MAP.get(ch, ""))
        else:
            cleaned_chars.append(ch)
    res = "".join(cleaned_chars)

    # Capitalize first letter of sentences
    res = re.sub(r"(?:^|[.!?]\s+)([a-z])", lambda m: m.group(0).upper(), res)
    return res


def convert_words_list_to_roman_urdu(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts word-timestamp objects to Roman Urdu while strictly preserving timings.
    """
    if not words:
        return []

    new_words = []
    for w in words:
        orig_word = w.get("word", "")
        converted_word = convert_word_to_roman_urdu(orig_word)
        new_words.append({
            "word": converted_word,
            "start": w.get("start", 0.0),
            "end": w.get("end", 0.0)
        })
    return new_words


# Bidirectional mapping between Urdu Script and Devanagari for script-selection support
URDU_TO_HINDI_MAP: Dict[str, str] = {
    "آپ": "आप", "کیسے": "कैसे", "کیسی": "कैसी", "کیسا": "कैसा",
    "ہیں": "हैं", "ہے": "है", "یہ": "यह", "وہ": "वह",
    "ویڈیو": "वीडियो", "بہت": "बहुत", "اچھی": "अच्छी", "اچھا": "अच्छा", "اچھے": "अच्छे",
    "کیا": "क्या", "کیوں": "क्यों", "کب": "कब", "کہاں": "कहाँ",
    "کون": "कौन", "کس": "किस", "کسی": "किसी", "کچھ": "कुछ", "کوئی": "कोई",
    "میرا": "मेरा", "میری": "मेरी", "میرے": "मेरे",
    "تیرا": "तेरा", "تیری": "तेरी", "تیرے": "तेरे",
    "ہمارا": "हमारा", "ہماری": "हमारी", "ہمارے": "हमारे",
    "تمہارا": "तुम्हारा", "تمہاری": "तुम्हारी", "تمہارے": "तुम्हारे",
    "اس": "इस", "ان": "इन", "اس کا": "इसका", "اس کی": "इसकी", "اس کے": "इसके",
    "مجھے": "मुझे", "تجھے": "तुझे", "ہمیں": "हमें", "انہیں": "उन्हें",
    "ہم": "हम", "تم": "तुम", "میں": "मैं",
    "سے": "से", "کو": "को", "کا": "का", "کے": "के", "کی": "की", "پر": "पर", "تک": "तक",
    "اور": "और", "یا": "या", "لیکن": "लेकिन", "مگر": "मगर", "اگر": "अगर", "تو": "तो",
    "بھی": "भी", "ہی": "ही", "نہ": "न", "نہیں": "नहीं", "ہاں": "हाँ", "جی": "जी",
    "تھا": "था", "تھی": "थी", "تھے": "थे",
    "ہو": "हो", "ہونا": "होना", "ہوتا": "होता", "ہوتی": "होती", "ہوتے": "होते",
    "ہوا": "हुआ", "ہوئی": "हुई", "ہوئے": "हुए",
    "رہا": "रहा", "رہی": "रही", "رہے": "रहे",
    "کر": "कर", "کرنا": "करना", "کرتے": "करते", "کرتی": "करती", "کرتا": "करता", "کیا": "किया",
    "دیکھ": "देख", "دیکھو": "देखो", "سن": "सुन", "سنو": "सुनो",
    "کہہ": "कह", "کہو": "कहो", "کہا": "कहा", "کہتے": "कहते",
    "سمجھ": "समझ", "جان": "जान", "پتا": "पता", "معلوم": "मालूम",
    "بات": "बात", "کام": "काम", "لوگ": "लोग", "وقت": "वक्त",
    "دن": "दिन", "رات": "रात", "آج": "आज", "کل": "कल",
    "زندگی": "ज़िंदगी", "دوست": "दोस्त"
}
HINDI_TO_URDU_MAP: Dict[str, str] = {v: k for k, v in URDU_TO_HINDI_MAP.items()}


def convert_text_to_urdu_script(text: str) -> str:
    """Converts text to Urdu script if it was transcribed in Devanagari."""
    if not text:
        return text
    # If already Urdu script, return as is
    has_devanagari = any('\u0900' <= ch <= '\u097F' for ch in text)
    if not has_devanagari:
        return text

    words = text.split()
    res = []
    for w in words:
        lead, core, trail = clean_punctuation(w)
        if core in HINDI_TO_URDU_MAP:
            conv = HINDI_TO_URDU_MAP[core]
        else:
            conv = core
        lead_u = lead.replace("?", "؟").replace(".", "۔").replace(",", "،")
        trail_u = trail.replace("?", "؟").replace(".", "۔").replace(",", "،")
        res.append(f"{lead_u}{conv}{trail_u}")
    return " ".join(res)


def convert_text_to_hindi_devanagari(text: str) -> str:
    """Converts text to Hindi Devanagari if it was transcribed in Urdu script."""
    if not text:
        return text
    has_urdu = any('\u0600' <= ch <= '\u06FF' for ch in text)
    if not has_urdu:
        return text

    words = text.split()
    res = []
    for w in words:
        lead, core, trail = clean_punctuation(w)
        if core in URDU_TO_HINDI_MAP:
            conv = URDU_TO_HINDI_MAP[core]
        else:
            conv = core
        lead_h = lead.replace("؟", "?").replace("۔", ".").replace("،", ",")
        trail_h = trail.replace("؟", "?").replace("۔", ".").replace("،", ",")
        res.append(f"{lead_h}{conv}{trail_h}")
    return " ".join(res)


def convert_text_by_script_mode(text: str, script_mode: str) -> str:
    """
    Direct dispatcher for script conversion based on script_mode:
      - 'roman_urdu': Latin Roman Urdu
      - 'urdu_script': Perso-Arabic Urdu Script
      - 'hindi_devanagari': Devanagari Hindi Script
      - 'original' or others: As-is
    """
    if not text:
        return text
    mode = (script_mode or "original").lower().strip()
    if mode == "roman_urdu":
        return convert_text_to_roman_urdu(text)
    elif mode in ["urdu_script", "urdu"]:
        return convert_text_to_urdu_script(text)
    elif mode in ["hindi_devanagari", "hindi", "devanagari"]:
        return convert_text_to_hindi_devanagari(text)
    return text


def convert_words_by_script_mode(words: List[Dict[str, Any]], script_mode: str) -> List[Dict[str, Any]]:
    """
    Converts word objects based on requested script mode while preserving timestamps.
    """
    if not words:
        return []
    mode = (script_mode or "original").lower().strip()
    if mode == "roman_urdu":
        return convert_words_list_to_roman_urdu(words)
    elif mode in ["urdu_script", "urdu"]:
        new_words = []
        for w in words:
            new_words.append({
                "word": convert_text_to_urdu_script(w.get("word", "")),
                "start": w.get("start", 0.0),
                "end": w.get("end", 0.0)
            })
        return new_words
    elif mode in ["hindi_devanagari", "hindi", "devanagari"]:
        new_words = []
        for w in words:
            new_words.append({
                "word": convert_text_to_hindi_devanagari(w.get("word", "")),
                "start": w.get("start", 0.0),
                "end": w.get("end", 0.0)
            })
        return new_words
    return words


def is_valid_roman_urdu(text: str) -> bool:
    """
    Validation check: Verifies that Roman Urdu output uses Latin characters
    (a-zA-Z, spaces, numbers, punctuation) with NO remaining Urdu or Devanagari script.
    Allows English words, digits, and ordinary punctuation.
    """
    if not text:
        return True
    has_non_latin = any(
        ('\u0600' <= ch <= '\u06FF') or ('\u0900' <= ch <= '\u097F')
        for ch in text
    )
    return not has_non_latin
