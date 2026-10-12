import re

_PUNCTUATION = re.compile(r"[.'\-]")
_WHITESPACE = re.compile(r"\s+")
_ABBREVIATIONS = (
    (re.compile(r"^st\s"), "saint "),
    (re.compile(r"^ft\s"), "fort "),
    (re.compile(r"^mt\s"), "mount "),
)


def normalize_city(name: str) -> str:
    s = _PUNCTUATION.sub(" ", name.strip().lower())
    s = _WHITESPACE.sub(" ", s).strip()
    for pattern, replacement in _ABBREVIATIONS:
        s = pattern.sub(replacement, s)
    return s
