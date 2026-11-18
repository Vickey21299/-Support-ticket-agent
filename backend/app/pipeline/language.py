"""S2b Language detection [CODE]: which language did the customer write in? (nl / en / de)

Decided in code (lingua, restricted to the three languages the helpdesk accepts), not by the LLM:
in our practice runs the LLM mislabelled English tickets that mention Dutch or German words.

1. Quoted text is removed first: UI labels, button names or copied messages in quotes are not the
   customer's own language (an English ticket that quotes a German button label is still English).
2. Low confidence (very short or mixed text) -> `confident=False`. The helpdesk only accepts nl/en/de,
   so the label then falls back to the model's guess and policy.py forces a handoff instead of replying.
3. Unsupported language guard: a detector restricted to nl/en/de must pick one of them even for Spanish or
   Turkish (it said "es -> en 0.83", "tr -> de 0.85"). So a second detector over ALL languages checks the text;
   if its top language is not nl/en/de, the result is `unsupported` (+ `confident=False`): no reply, a human answers.
   Under 5 words that guess is too noisy to name ("ok" -> Zulu), so short text only becomes `unsure`
   (a 2-word Turkish ticket was otherwise "de 0.97").
   The all-language scores are not used as confidence (they are spread over ~75 languages, Dutch vs Afrikaans
   often scores < 0.5), only its top pick. Model load ~5 s once, then ~2 ms per ticket.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

CONFIDENCE_THRESHOLD = 0.70
SUPPORTED = ("nl", "en", "de")   # the only values the helpdesk accepts
MIN_WORDS_FOR_GUARD = 5          # on a word or two the all-language detector guesses wildly ("ok" -> Zulu)
_QUOTED = re.compile(r"""'[^'\n]{1,120}'|"[^"\n]{1,120}"|‘[^’\n]{1,120}’|“[^”\n]{1,120}”|„[^“”\n]{1,120}[“”]""")
_NOISE = re.compile(r"https?://\S+|\S+@\S+|\[[A-Z]+\]|\d+([.,:/-]\d+)*")
_REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|wg|antw)\s*:\s*)+", re.IGNORECASE)


@dataclass(frozen=True)
class LanguageResult:
    code: Optional[str]          # "nl" / "en" / "de", or None when there is no text
    confidence: float
    confident: bool
    unsupported: Optional[str] = None   # e.g. "es": the customer wrote in a language the helpdesk does not support

    def describe(self) -> str:
        if self.unsupported:
            return f"{self.unsupported} (not nl/en/de)"
        if not self.code:
            return "no text to detect"
        return f"{self.code} ({self.confidence:.2f}{'' if self.confident else ', unsure'})"


@lru_cache(maxsize=1)
def _detector():
    from lingua import Language, LanguageDetectorBuilder
    return LanguageDetectorBuilder.from_languages(Language.DUTCH, Language.ENGLISH, Language.GERMAN).build()


@lru_cache(maxsize=1)
def _all_languages_detector():
    from lingua import LanguageDetectorBuilder
    return LanguageDetectorBuilder.from_all_languages().build()


def _all_languages_top(text: str) -> Optional[str]:
    """ISO code of the top language over all languages, or None."""
    values = _all_languages_detector().compute_language_confidence_values(text)
    return values[0].language.iso_code_639_1.name.lower() if values else None


def customer_text(subject: str, body: str) -> str:
    """The customer's own words: subject + body without quoted text, links, emails, numbers, masks."""
    text = f"{_REPLY_PREFIX.sub('', subject or '')}\n{body or ''}"
    text = _QUOTED.sub(" ", text)
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_language(subject: str, body: str, threshold: float = CONFIDENCE_THRESHOLD) -> LanguageResult:
    text = customer_text(subject, body)
    if not re.search(r"[^\W\d_]{2,}", text):
        return LanguageResult(None, 0.0, False)
    values = _detector().compute_language_confidence_values(text)
    if not values:
        return LanguageResult(None, 0.0, False)
    top = values[0]
    code = top.language.iso_code_639_1.name.lower()
    other = _all_languages_top(text)
    if other and other not in SUPPORTED:
        if len(re.findall(r"[^\W\d_]{2,}", text)) >= MIN_WORDS_FOR_GUARD:
            return LanguageResult(code, float(top.value), False, unsupported=other)
        # short text: the all-language guess is not reliable enough to name, but it is enough doubt to not reply
        return LanguageResult(code, float(top.value), False)
    return LanguageResult(code, float(top.value), float(top.value) >= threshold)
