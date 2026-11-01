import math
import os
import re
import threading
from collections import Counter
from typing import Any, Iterable, List, Mapping, Optional, Set

# A run of key-safe characters (letters, digits and -_. only, so never any
# whitespace or URL/path punctuation) at least this long looks like an api key.
MIN_KEY_LENGTH = 24

# Values picked up because their own name looks like a credential are taken in
# full (they may contain punctuation the token regex can't span), but only when
# at least this long, so trivial values ("", "0", "true") can't blank out
# ordinary words in the conversation.
MIN_VALUE_LENGTH = 8

REDACTED = "<redacted>"

_KEY_LIKE_RE = re.compile(r"[A-Za-z0-9\-_.]{24,}")

# A value that is nothing but an unexpanded reference into the environment.
# Those are not secrets themselves, so they must never be registered.
_ENV_REF_RE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")

# Values that look like filesystem paths are identifiers, not secrets, so they
# are never registered (a key may live at a path, but the path is not the key).
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.~-]+$")
_VERSION_SUFFIX_RE = re.compile(r"[_-]?v?\d+$")

# Name words that mark a value as a credential when they end the name, and
# take precedence over BENIGN_NAME_WORDS. "pwd" is deliberately absent: PWD
# holds the working dir, so it is benign instead (see BENIGN_NAME_WORDS). Words
# only count when they end the name (see SECRET_NAME_SUFFIXES).
SECRET_NAME_WORDS = {
    "apikey",
    "apikeys",
    "credential",
    "credentials",
    "key",
    "keys",
    "passwd",
    "password",
    "passwords",
    "secret",
    "secrets",
    "token",
    "tokens",
}

SECRET_NAME_SUFFIXES = tuple(sorted(SECRET_NAME_WORDS))

# Separators that make a trailing credential word unambiguous. Without one, the
# word is part of a larger token ("MONKEY", "sortKey") and must be confirmed by
# the value itself (see _is_ambiguous_secret_name).
_SUFFIX_SEPARATORS = ("_", "-", ".", "/", "\\", " ")

_SEPARATED_SECRET_SUFFIXES = tuple(
    separator + suffix for separator in _SUFFIX_SEPARATORS for suffix in SECRET_NAME_SUFFIXES
)

# A name that contains a credential word that is not a suffix ("KEY_DESCRIPTION_V2")
# is not trusted on its own: the value must also look key-like, measured as
# Shannon entropy in bits per character. Passwords are allowed a lower bar
# because they are often human-chosen rather than random.
DEFAULT_CREDENTIAL_ENTROPY = 3.2

CREDENTIAL_ENTROPY_THRESHOLDS = {
    "apikey": 3.2,
    "apikeys": 3.2,
    "credential": 3.0,
    "credentials": 3.0,
    "key": 3.2,
    "keys": 3.2,
    "passwd": 2.5,
    "password": 2.5,
    "passwords": 2.5,
    "secret": 3.0,
    "secrets": 3.0,
    "token": 3.2,
    "tokens": 3.2,
}

# Name words that mark a value as an identifier (paths, models, session ids,
# hostnames). These are never scanned for key-like tokens: config/env entries
# named this way legitimately hold long strings that are not secrets, e.g.
# "claude-3-5-sonnet-20241022" or "debuginfod.fedoraproject.org".
BENIGN_NAME_WORDS = {
    "base",
    "bin",
    "branch",
    "cwd",
    "dir",
    "dirs",
    "directory",
    "domain",
    "editor",
    "encoding",
    "env",
    "exe",
    "file",
    "files",
    "format",
    "guid",
    "home",
    "host",
    "hosts",
    "hostname",
    "id",
    "lang",
    "language",
    "locale",
    "model",
    "models",
    "name",
    "oldpwd",
    "pager",
    "path",
    "paths",
    "pid",
    "prefix",
    "profile",
    "pwd",
    "release",
    "repo",
    "root",
    "session",
    "shell",
    "term",
    "terminal",
    "theme",
    "tz",
    "url",
    "urls",
    "user",
    "uuid",
    "venv",
    "version",
    "virtualenv",
    "workspace",
    "workspaces",
    "worktree",
    "worktrees",
}

_api_keys: List[str] = []
_matcher: Optional[re.Pattern] = None
_lock = threading.RLock()


def detect_api_keys(
    merged_config: Optional[Mapping[str, Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> List[str]:
    """Collect api-key-like strings from a merged config and the environment.

    Every value is classified by the name it is stored under:

      - credential-named (ends with "key", "token", "password", "secret", ...):
        the whole value is taken as a candidate, since such values may contain
        punctuation that a key-like token regex cannot span.
      - containing a credential word, as a word or inside a longer token (e.g.
        "KEY_DESCRIPTION_V2" or "sortKey"): the whole value is taken only when
        it also looks key-like (length, letter/digit mix and entropy above the
        threshold for that word).
      - identifier-named (see BENIGN_NAME_WORDS) or path-shaped: not
        registered in full, because these legitimately hold long non-secret
        strings; any key-like tokens embedded in the value are still registered.
      - anything else: scanned for key-like tokens, i.e. runs of
        ``MIN_KEY_LENGTH``+ characters of ``[A-Za-z0-9-_.]``.

    Config values additionally have ``$VAR``/``${VAR}`` expanded against
    ``environ`` first, since config files usually reference keys that live in
    the environment.

    Args:
        merged_config: The fully merged config dict (see
            config_utils.read_and_merge_all_configs).
        environ: Environment mapping to read, defaults to os.environ.

    Returns:
        Sorted, de-duplicated list of candidate secret strings.
    """
    if environ is None:
        environ = os.environ

    found: Set[str] = set()

    _scan_entries(environ, found, expand=False)
    _scan_entries(merged_config, found, expand=True)

    return sorted(found)


def register_api_keys(keys: Iterable[str]) -> List[str]:
    """Add candidate secrets to the process-wide redaction list.

    Registration is additive, so later calls (an oauth flow, a config reload)
    only widen the set. Values shorter than ``MIN_VALUE_LENGTH`` are ignored
    for the same reason as in detect_api_keys.

    Returns:
        The full registered list, longest first.
    """
    global _api_keys, _matcher

    with _lock:
        merged = set(_api_keys)

        for key in keys:
            if isinstance(key, str) and len(key) >= MIN_VALUE_LENGTH:
                merged.add(key)

        # Longest first so a key nested inside a longer one still wins.
        _api_keys = sorted(merged, key=lambda item: (-len(item), item))
        _matcher = None

        return list(_api_keys)


def reset_api_keys() -> None:
    """Drop all registered secrets (used by tests and config reloads)."""
    global _api_keys, _matcher

    with _lock:
        _api_keys = []
        _matcher = None


def get_api_keys() -> List[str]:
    """Return the registered secrets, longest first."""
    with _lock:
        return list(_api_keys)


def redact_api_keys(value: Any) -> Any:
    """Replace every registered secret in ``value`` with ``<redacted>``.

    Walks dicts, lists and tuples so nested content blocks and tool-call
    arguments are covered. Returns the input untouched when nothing is
    registered, and only rebuilds a container whose contents actually changed.
    """
    if not _api_keys:
        return value

    matcher = _get_matcher()

    if isinstance(value, str):
        return matcher.sub(REDACTED, value)

    if isinstance(value, Mapping):
        return _redact_mapping(value)

    if isinstance(value, list):
        return _redact_seq(value, list)

    if isinstance(value, tuple):
        return _redact_seq(value, tuple)

    return value


def _scan_entries(mapping: Any, found: Set[str], expand: bool) -> None:
    """Classify and scan every entry of a nested config/env mapping."""
    if not isinstance(mapping, Mapping):
        return

    for name, value in mapping.items():
        _scan_entry(name, value, found, expand, forced=False)


def _scan_entry(name: Any, value: Any, found: Set[str], expand: bool, forced: bool) -> None:
    """Scan one value under ``name``, recursing into containers.

    ``forced`` marks values inherited from a credential-named parent, so a
    mapping under e.g. ``api-keys:`` is still read as secrets.
    """
    if isinstance(value, Mapping):
        credential_named = forced or _is_secret_name(name)

        for sub_name, sub_value in value.items():
            _scan_entry(sub_name, sub_value, found, expand, credential_named)

        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            _scan_entry(name, item, found, expand, forced)

        return

    if not isinstance(value, str) or not value:
        return

    text = os.path.expandvars(value) if expand else value

    if forced or _is_secret_name(name):
        _register_secret_value(text, found)
        return

    if _contains_secret_word(name) or _is_ambiguous_secret_name(name):
        if _looks_like_key_value(text, name):
            _register_secret_value(text, found)
            return

    if _looks_path_ish(text.strip()):
        _register_embedded_keys(text, found)
        return

    if _is_benign_name(name):
        return

    found.update(_KEY_LIKE_RE.findall(text))


def _register_secret_value(value: str, found: Set[str]) -> None:
    """Take a credential-named value in full, plus any key-like tokens in it.

    Path-shaped values are not registered in full, but any key-like tokens
    embedded in them still are.
    """
    stripped = value.strip()

    if len(stripped) < MIN_VALUE_LENGTH or _ENV_REF_RE.match(stripped):
        return

    if _looks_like_path(stripped):
        _register_embedded_keys(stripped, found)
        return

    found.add(stripped)
    found.update(_KEY_LIKE_RE.findall(stripped))


def _is_secret_name(name: Any) -> bool:
    """True if the name unambiguously ends with a credential word."""
    lowered = _strip_version_suffix(name)

    if lowered in SECRET_NAME_WORDS:
        return True

    return lowered.endswith(_SEPARATED_SECRET_SUFFIXES)


def _is_ambiguous_secret_name(name: Any) -> bool:
    """True if the name ends with a credential word inside a longer token."""
    lowered = _strip_version_suffix(name)

    return lowered.endswith(SECRET_NAME_SUFFIXES) and not _is_secret_name(name)


def _strip_version_suffix(name: Any) -> str:
    """Lowercase ``name`` and drop a trailing version like ``2`` or ``_V2``."""
    return _VERSION_SUFFIX_RE.sub("", str(name).strip().lower())


def _is_benign_name(name: Any) -> bool:
    """True if the name says this value is an identifier, not a secret."""
    return bool(_name_words(name) & BENIGN_NAME_WORDS)


def _name_words(name: Any) -> Set[str]:
    """Split ``name`` into lowercased words, handling -/. and camelCase."""
    words = set()

    for chunk in re.split(r"[^A-Za-z0-9]+", str(name)):
        if not chunk:
            continue

        words.add(chunk.lower())
        words.update(w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", chunk))

    return words


def _contains_secret_word(name: Any) -> bool:
    """True if a credential word appears as a separate word in the name."""
    return bool(_name_words(name) & SECRET_NAME_WORDS)


def _looks_like_key_value(value: str, name: Any) -> bool:
    """True if a value under a containing credential name looks like a key.

    Best-effort: requires ``MIN_KEY_LENGTH`` characters, letters and digits and
    no whitespace, so short or all-alpha passphrases under ambiguous names are
    intentionally not detected.
    """
    stripped = value.strip()

    if len(stripped) < MIN_KEY_LENGTH or _looks_like_path(stripped):
        return False

    if any(char.isspace() for char in stripped):
        return False

    has_alpha = any(char.isalpha() for char in stripped)
    has_digit = any(char.isdigit() for char in stripped)

    if not has_alpha or not has_digit:
        return False

    return _shannon_entropy(stripped) >= _entropy_threshold(name)


def _entropy_threshold(name: Any) -> float:
    """Return the entropy bar for the credential words in ``name``."""
    words = _name_words(name) & set(CREDENTIAL_ENTROPY_THRESHOLDS)

    if not words:
        return DEFAULT_CREDENTIAL_ENTROPY

    return min(CREDENTIAL_ENTROPY_THRESHOLDS[word] for word in words)


def _looks_like_path(value: str) -> bool:
    """True if ``value`` looks like a filesystem path rather than a secret."""
    if _URL_RE.match(value):
        return False

    if value.startswith(("/", "~", "./", "../")):
        return True

    if _WINDOWS_PATH_RE.match(value) or value.startswith("\\\\"):
        return True

    if "\\" in value:
        return _has_path_extension(value, "\\")

    if "/" not in value:
        return False

    return _has_path_extension(value, "/")


def _has_path_extension(value: str, separator: str) -> bool:
    """True if ``value`` has 2+ ``separator`` segments and a dotted segment."""
    segments = [segment for segment in value.split(separator) if segment]

    return len(segments) > 1 and any("." in segment for segment in segments)


def _looks_path_ish(value: str) -> bool:
    """True if ``value`` looks like any path, including extensionless relative."""
    if _looks_like_path(value):
        return True

    if "/" in value:
        return _all_path_segments(value.split("/"))

    if "\\" in value:
        return _all_path_segments(value.split("\\"))

    return False


def _all_path_segments(segments: Iterable[str]) -> bool:
    """True if ``segments`` form a relative path and not a token with slashes."""
    parts = [segment for segment in segments if segment]

    return len(parts) > 1 and all(_PATH_SEGMENT_RE.match(segment) for segment in parts)


def _register_embedded_keys(value: str, found: Set[str]) -> None:
    """Register key-like tokens in a path-shaped value, skipping path chunks.

    A slash-containing token under a generic name is indistinguishable from a
    path segment and is skipped; credential-named values are registered in full
    before this helper is reached.
    """
    for chunk in value.split():
        if _looks_path_ish(chunk):
            continue

        found.update(_KEY_LIKE_RE.findall(chunk))


def _shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of ``value`` in bits per character."""
    counts = Counter(value)
    length = len(value)

    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _redact_mapping(mapping: Mapping) -> Mapping:
    """Apply redaction to every value, keeping the mapping when unchanged."""
    items = {}
    changed = False

    for key, item in mapping.items():
        new_item = redact_api_keys(item)
        changed = changed or new_item is not item
        items[key] = new_item

    return items if changed else mapping


def _redact_seq(seq: list, ctor) -> Any:
    """Apply ``redact_api_keys`` to ``seq``, keeping it when nothing changed."""
    items = []
    changed = False

    for item in seq:
        new_item = redact_api_keys(item)
        changed = changed or new_item is not item
        items.append(new_item)

    return ctor(items) if changed else seq


def _get_matcher() -> re.Pattern:
    """Build (and cache) the alternation matcher for the registered secrets."""
    global _matcher

    with _lock:
        if _matcher is None:
            pattern = "|".join(re.escape(key) for key in _api_keys)
            _matcher = re.compile(pattern)

        return _matcher
