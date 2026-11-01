import json
import math
from collections import OrderedDict

# Every knob the loop detectors use, in one config dict that callers may
# partially override:
#   ``*_limit``     repeats tolerated at each level before the stream is cancelled
#   ``max_sentences`` size of the sentence memory used by the sentence level
#   ``enabled``     whether allowances adapt at all (False pins them at the limits)
#   ``increase``    multiplicative growth of a level's allowance when it loops
#   ``max``/``min`` bounds an allowance may never leave
#   ``decrease``    additive bleed-off applied to every level after a clean stream
DEFAULT_CONFIG = {
    "char_limit": 100,
    "word_limit": 25,
    "sentence_limit": 5,
    "max_sentences": 10,
    "enabled": True,
    "increase": 2.0,
    "max": 8.0,
    "min": 1.0,
    "decrease": 0.4,
}

# Detector levels, in the order they are checked.
LOOP_LEVELS = ("char", "word", "sentence")


class LoopDetectedError(Exception):
    """Raised when a repeating output loop is detected while streaming.

    ``level`` names the detector level that tripped, so the adaptive tracker can
    relax that repetition allowance on its own.
    """

    def __init__(self, message, level=None):
        super().__init__(message)
        self.level = level


class LoopThresholdTracker:
    """Loop-detection settings plus how much repetition is allowed right now.

    The static config is merged over ``DEFAULT_CONFIG`` and owns the limits; on top
    of them each level (``char``, ``word``, ``sentence``) carries a multiplier that
    adapts to what the model is actually doing. The curve is AIMD run backwards: a
    stream that trips one level multiplies only that level (by ``increase``, up to
    ``max``), so a model chewing through genuinely repetitive data stops getting
    cancelled, while every stream that finishes without tripping subtracts
    ``decrease`` from all of them, bleeding the relaxation back toward ``min``.

    A multiplier of 1.0 means exactly the configured limits, so with the default
    sentence limit of 5 the effective threshold walks
    ``5 -> 10 -> 20 -> 40 (capped) -> 38 -> 36 -> ... -> 5``.
    """

    def __init__(self, config=None):
        settings = dict(DEFAULT_CONFIG)

        if isinstance(config, str):
            # Config files and CLI strings reach us as JSON.
            try:
                config = json.loads(config)
            except (TypeError, ValueError):
                config = None

        if isinstance(config, dict):
            settings.update(config)

        self.enabled = _flag(settings["enabled"])
        self.increase = _positive_float(
            settings["increase"], DEFAULT_CONFIG["increase"], minimum=1.0
        )
        self.max = _positive_float(settings["max"], DEFAULT_CONFIG["max"], minimum=1.0)
        self.min = min(1.0, _positive_float(settings["min"], DEFAULT_CONFIG["min"], minimum=0.0))
        self.decrease = _positive_float(
            settings["decrease"], DEFAULT_CONFIG["decrease"], minimum=0.001
        )
        self.max_sentences = _positive_int(
            settings["max_sentences"], DEFAULT_CONFIG["max_sentences"]
        )
        self.limits = {
            level: _positive_int(settings[f"{level}_limit"], DEFAULT_CONFIG[f"{level}_limit"])
            for level in LOOP_LEVELS
        }

        # Level name -> multiplier, always starting at the configured limits.
        self.factors = dict.fromkeys(LOOP_LEVELS, 1.0)

    def limit(self, level):
        """Return the current cap for one detector level."""
        base = self.limits.get(level, 1)

        if not self.enabled:
            return base

        return max(1, int(math.ceil(base * self.factors.get(level, 1.0))))

    def record_loop(self, level):
        """Relax a single level multiplicatively after a stream tripped it."""
        if not self.enabled or level not in self.factors:
            return self.factors.get(level, 1.0)

        self.factors[level] = min(self.max, max(self.min, self.factors[level] * self.increase))

        return self.factors[level]

    def record_clean_turn(self):
        """Pull every level back down one additive step toward the floor."""
        if not self.enabled:
            return self.factors

        for level in self.factors:
            self.factors[level] = max(self.min, self.factors[level] - self.decrease)

        return self.factors

    def reset(self):
        """Put every level back at its base multiplier."""
        self.factors = dict.fromkeys(LOOP_LEVELS, 1.0)

    def describe(self):
        """Summarize the relaxed levels; empty when all of them are at base."""
        if not self.enabled:
            return ""

        return ", ".join(
            f"{level} {factor:g}x" for level, factor in self.factors.items() if factor > self.min
        )

    def __repr__(self):
        return f"LoopThresholdTracker({self.describe() or 'base'})"


class LoopDetector:
    """Watches a stream of text and raises when the model starts repeating itself.

    All thresholds come from the :class:`LoopThresholdTracker` it is handed, so the
    coder owns the policy and this class only does detection.
    """

    # Written into the assistant message when a stream is cancelled for looping, so
    # the model can see why its output was cut short and change tack.
    INTERJECTION = "[SYSTEM INTERJECTION: AVOID REPETITION]"

    def __init__(self, thresholds=None):
        self.thresholds = thresholds if thresholds is not None else LoopThresholdTracker()

        # Level 1: Character State
        self.last_char = ""
        self.char_count = 0

        # Level 2: Word State
        self.current_word = []
        self.last_word = ""
        self.word_count = 0

        # Level 3: Sentence State (Bounded LRU Cache)
        self.current_sentence = []
        self.sentence_counts = OrderedDict()

    @property
    def char_limit(self):
        return self.thresholds.limit("char")

    @property
    def word_limit(self):
        return self.thresholds.limit("word")

    @property
    def sentence_limit(self):
        return self.thresholds.limit("sentence")

    @property
    def max_sentences(self):
        return self.thresholds.max_sentences

    def push(self, chunk: str) -> None:
        for char in chunk:
            # -------------------------
            # 1. Character Level Check
            # -------------------------
            if not char.isspace():
                if char == self.last_char:
                    self.char_count += 1
                    if self.char_count >= self.char_limit:
                        raise LoopDetectedError(
                            f"Char loop: '{char}' repeated {self.char_count} times.",
                            level="char",
                        )
                else:
                    self.char_count = 1
                self.last_char = char

            # -------------------------
            # 2. Word Level Check
            # -------------------------
            if char.isalnum() or char in ["_", "-"]:
                self.current_word.append(char)
            elif self.current_word:
                word_str = "".join(self.current_word).lower()

                if word_str == self.last_word:
                    self.word_count += 1
                    if self.word_count >= self.word_limit:
                        raise LoopDetectedError(
                            f"Word loop: '{word_str}' repeated {self.word_count} times.",
                            level="word",
                        )
                else:
                    self.word_count = 1

                self.last_word = word_str
                self.current_word = []

            # -------------------------
            # 3. Sentence Level Check
            # -------------------------
            self.current_sentence.append(char)

            if char in [".", "!", "?", "\n"]:
                sentence_str = "".join(self.current_sentence).strip()

                if len(sentence_str) > 10 and is_sentence(sentence_str):
                    normalized = " ".join(sentence_str.lower().split())

                    # Update count and move to the "most recent" position
                    if normalized in self.sentence_counts:
                        self.sentence_counts[normalized] += 1
                        self.sentence_counts.move_to_end(normalized)
                    else:
                        self.sentence_counts[normalized] = 1

                    # Check threshold
                    if self.sentence_counts[normalized] >= self.sentence_limit:
                        raise LoopDetectedError(
                            f"Sentence loop: '{normalized}' occurred {self.sentence_counts[normalized]} times.",
                            level="sentence",
                        )

                    # Enforce the 10-sentence memory bound
                    if len(self.sentence_counts) > self.max_sentences:
                        # popitem(last=False) removes the oldest, least recently used item
                        self.sentence_counts.popitem(last=False)

                self.current_sentence = []

        return None


def is_sentence(text):
    """Return True if *text* looks like a latin-language sentence, not a code block.

    A sentence must be non-empty, start with a capital letter, end with a
    sentence terminator, and contain a space (i.e. multiple words).
    """
    text = text.strip()

    if not text:
        return False

    # Check if it starts with a capital letter
    if not text[0].isupper():
        return False

    # Check if it ends with a punctuation mark
    if text[-1] not in [".", "!", "?"]:
        return False

    # Check if it contains at least one space (implying multiple words)
    if " " not in text:
        return False

    return True


def _positive_float(value, default, minimum=0.0):
    """Coerce a configured value to a finite float at or above ``minimum``.

    Values that are not config-shaped numbers fall back to ``default`` instead of
    being coerced through the magic-method stubs of e.g. a MagicMock args object.
    """
    if not _is_numeric(value):
        return default

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(parsed) or parsed < minimum:
        return default

    return parsed


def _positive_int(value, default, minimum=1):
    """Coerce a configured value to a finite int at or above ``minimum``."""
    if not _is_numeric(value):
        return default

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    return max(minimum, parsed)


def _is_numeric(value):
    """True for numbers or numeric strings; bools and stub objects are excluded."""
    return isinstance(value, (int, float, str)) and not isinstance(value, bool)


def _flag(value):
    """Interpret a configured boolean, tolerating the strings config files use."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")

    return bool(value)
