from collections import OrderedDict


class LoopDetectedError(Exception):
    """Raised when a repeating output loop is detected while streaming."""


class LoopDetector:
    def __init__(self, char_limit=100, word_limit=25, sentence_limit=5, max_sentences=10):
        self.char_limit = char_limit
        self.word_limit = word_limit
        self.sentence_limit = sentence_limit
        self.max_sentences = max_sentences

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
                            f"Char loop: '{char}' repeated {self.char_count} times."
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
                            f"Word loop: '{word_str}' repeated {self.word_count} times."
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
                            f"Sentence loop: '{normalized}' occurred {self.sentence_counts[normalized]} times."
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
