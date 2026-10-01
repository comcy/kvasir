"""Branch-Vorlagen: Prüfung, Namensbau, Korrekturvorschlag. Reine Logik."""
import re
import unicodedata
from difflib import SequenceMatcher

TYPES = ("feat", "fix", "docs", "refactor", "chore", "test", "perf", "ci", "build", "style", "revert")

_ID = r"(?:[A-Z][A-Z0-9]*-\d+|\d+)"
_SLUG = r"[a-z0-9]+(?:[-.][a-z0-9]+)*"
_DATE = r"\d{4}-\d{2}-\d{2}"
_TYPE = "|".join(TYPES)
_FIELDS = {"type": _TYPE, "id": _ID, "slug": _SLUG, "date": _DATE}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """`features/{id}-{slug}` -> Regex. Unbekannter Platzhalter -> ValueError."""
    out, pos = "", 0
    for m in _PLACEHOLDER.finditer(pattern):
        if m[1] not in _FIELDS:
            raise ValueError(f"unknown placeholder {m[0]} in {pattern!r}")
        out += re.escape(pattern[pos:m.start()]) + f"(?P<{m[1]}>{_FIELDS[m[1]]})"
        pos = m.end()
    return re.compile(out + re.escape(pattern[pos:]))


def matches(name: str, patterns: list[str]) -> bool:
    return any(compile_pattern(p).fullmatch(name) for p in patterns)


def slugify(title: str) -> str:
    """Freier Titel -> kebab-case. Umlaute: ä->ae, ö->oe, ü->ue, ß->ss. Kann leer sein."""
    title = unicodedata.normalize("NFKD", title.translate(_UMLAUTE)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9.]+", "-", title.lower()).strip("-.")


def build(pattern: str, **fields: str) -> str:
    """Setzt Felder in die Vorlage ein; fehlendes Feld -> KeyError."""
    compile_pattern(pattern)  # validiert Platzhalter
    return pattern.format(**fields)


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def suggest(name: str, patterns: list[str]) -> str | None:
    """Korrekturvorschlag aus der ähnlichsten Vorlage; None wenn name gültig ist oder
    keine Vorlage existiert. Nicht ableitbare Felder bleiben als `{feld}` stehen."""
    if not patterns or matches(name, patterns):
        return None
    rest, found = name, {}
    for key, rx in (("date", _DATE), ("id", _ID), ("type", rf"\b(?:{_TYPE})\b")):
        m = re.search(rx, rest, re.IGNORECASE if key != "date" else 0)
        if m:
            found[key] = m[0].upper() if key == "id" else m[0].lower()
            rest = rest[:m.start()] + " " + rest[m.end():]
    cands = []
    for p in patterns:
        words = re.findall(r"[A-Za-z]+", "".join(_PLACEHOLDER.split(p)[::2]))  # Vorlagen-Literale nicht in den Slug
        r = re.sub(rf"\b(?:{'|'.join(words)})\b", " ", rest, flags=re.IGNORECASE) if words else rest
        slug = slugify(r)
        cands.append(p.format_map(_Keep(found | ({"slug": slug} if slug else {}))))
    return max(cands, key=lambda c: SequenceMatcher(None, name.lower(), c).ratio())
