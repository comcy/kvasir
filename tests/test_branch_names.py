import pytest

from kvasir.branch_names import build, matches, slugify, suggest

TYPE_SLUG = "{type}/{slug}"
FEAT = "features/{id}-{slug}"
FIX = "fixes/{id}-{slug}"
REL = "release/{date}"
ALL = [TYPE_SLUG, FEAT, FIX, REL]


@pytest.mark.parametrize("name", [
    "feat/add-login", "fix/v1.2-hotfix", "features/1234-add-login", "features/ABC-123-add-login",
    "fixes/42-crash", "release/2026-10-02",
])
def test_valid(name):
    assert matches(name, ALL)


@pytest.mark.parametrize("name", [
    "Feat/add-login",  # Großbuchstaben im Typ
    "feat/Add-Login",  # Großbuchstaben im Slug
    "feat/",  # leerer Slug
    "features/abc-123-x",  # id klein
    "features/ABC-add",  # id ohne Zahl
    "feat/a--b", "feat/-a", "feature/x", "release/2026-1-2", "main",
])
def test_invalid(name):
    assert not matches(name, ALL)


def test_matches_no_patterns_and_unknown_placeholder():
    assert not matches("feat/x", [])
    with pytest.raises(ValueError):
        matches("x", ["{nope}"])


def test_build():
    assert build(FEAT, id="ABC-123", slug="add-login") == "features/ABC-123-add-login"
    assert build(TYPE_SLUG, type="fix", slug=slugify("Größe ändern")) == "fix/groesse-aendern"
    with pytest.raises(KeyError):
        build(FEAT, id="1")


@pytest.mark.parametrize("title,slug", [
    ("Füge Größe hinzu", "fuege-groesse-hinzu"),
    ("Ärger über Öl & Maß", "aerger-ueber-oel-mass"),
    ("  foo --  bar!! ", "foo-bar"),
    ("a___b///c", "a-b-c"),
    ("v1.2 release", "v1.2-release"),
    ("!!!", ""),
    ("", ""),
])
def test_slugify(title, slug):
    assert slugify(title) == slug


def test_suggest():
    assert suggest("feat/add-login", ALL) is None
    assert suggest("Feat/Add Login", ALL) == "feat/add-login"
    assert suggest("Features/abc-123 Add Login", [FEAT]) == "features/ABC-123-add-login"
    assert suggest("Features/Add Login", [FEAT]) == "features/{id}-add-login"
    assert suggest("release/Oct 2", [REL]) == "release/{date}"
    assert suggest("anything", []) is None
