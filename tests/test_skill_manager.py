"""
Tests for SkillManager (skills/utils.py).

Loading a skill is a two-step IVCAP download: look up the aspect
(entity, schema='urn:sd:schema:crew.skill') to find the artifact URN, then
download that artifact's body as the skill markdown. Either step can fail, so
these tests cover the three interesting shapes:

  * the skill does not exist   - no aspect, or an aspect with no artifact ref
  * the skill is not downloadable - the artifact URN resolves to nothing, or
                                    reading its body blows up
  * the skill exists and is downloadable - the happy path, down to the
    spec-compliant SKILL.md that CrewAI can actually parse

The IVCAP client is replaced with a fake, so nothing here touches the network.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Must set env vars before importing any crewai / ivcap modules.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("IVCAP_BASE_URL", "http://localhost:8077")

# Ensure project root is on sys.path so imports resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from skills.utils import (  # noqa: E402
    SKILL_FILE_NAME,
    SKILL_SCHEMA,
    Skill,
    SkillManager,
    SkillNotFound,
    parse_front_matter,
    skill_dir_name,
    skill_entity_urn,
)

ENTITY = "urn:sd:crewai:crew.skill.scientific_review_writer_report"
ASPECT_URN = "urn:ivcap:aspect:11111111-1111-1111-1111-111111111111"
ARTIFACT_URN = "urn:ivcap:artifact:80968d8c-7a34-499c-b13b-79974a3ea98c"

SKILL_MD = """---
name: Scientific Review Writer Report
description: How to structure a scientific review report.
metadata:
  version: 1.0.0
  author: csiro
---

# Report structure

1. Abstract
2. Methods
"""


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _Reader:
    """The file-like object an artifact's `open()` hands back."""

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


class FakeArtifact:
    """Stands in for an ivcap_client artifact; `open()` yields its body."""

    def __init__(self, body, fail_on_open: Exception = None):
        self._body = body
        self._fail_on_open = fail_on_open

    def open(self):
        if self._fail_on_open:
            raise self._fail_on_open
        return _Reader(self._body)


def make_aspect(urn=ASPECT_URN, content=None):
    return SimpleNamespace(urn=urn, content=content)


def make_manager(tmp_path, ivcap_client, *, job_id="job-42", token="Bearer jwt-123"):
    """A SkillManager wired to `ivcap_client` and writing under `tmp_path`."""
    job_context = SimpleNamespace(job_id=job_id, job_authorization=token)
    with patch("skills.utils.IVCAP", return_value=ivcap_client) as mock_ivcap:
        mgr = SkillManager(job_context=job_context, parent_dir=str(tmp_path))
    mgr._ivcap_ctor = mock_ivcap
    return mgr


def client_with(aspects=None, artifact=None, get_artifact_error: Exception = None):
    """
    A fake IVCAP client: `list_aspects` returns `aspects`, `get_artifact` returns
    `artifact` (or raises `get_artifact_error`).
    """
    client = MagicMock()
    client.list_aspects.return_value = iter(aspects or [])
    if get_artifact_error is not None:
        client.get_artifact.side_effect = get_artifact_error
    else:
        client.get_artifact.return_value = artifact
    return client


@pytest.fixture
def happy_manager(tmp_path):
    """A manager whose single skill exists and downloads cleanly."""
    client = client_with(
        aspects=[make_aspect(content={"artifact": ARTIFACT_URN, "version": "1.0.0"})],
        artifact=FakeArtifact(SKILL_MD.encode("utf-8")),
    )
    return make_manager(tmp_path, client), client


# ---------------------------------------------------------------------------
# Helpers: URN expansion, directory naming, front matter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("scientific_review_writer_report", ENTITY),
        (ENTITY, ENTITY),
        ("urn:sd:crewai:crew.skill.foo", "urn:sd:crewai:crew.skill.foo"),
    ],
)
def test_skill_entity_urn_expands_bare_names_only(given, expected):
    assert skill_entity_urn(given) == expected


@pytest.mark.parametrize(
    "name,entity,expected",
    [
        (None, "urn:sd:crewai:crew.skill.foo_bar", "foo-bar"),
        ("Scientific Review Writer", ENTITY, "scientific-review-writer"),
        ("__weird__", ENTITY, "weird"),
        # Fall back to a usable name rather than an empty directory name.
        ("***", ENTITY, "skill"),
    ],
)
def test_skill_dir_name_is_kebab_case(name, entity, expected):
    skill = Skill(entity=entity, aspect_urn="", artifact_urn="", content="", name=name)
    assert skill_dir_name(skill) == expected


def test_parse_front_matter_handles_missing_and_broken_yaml():
    assert parse_front_matter("# no front matter") == {}
    assert parse_front_matter("---\nname: x\n---\nbody") == {"name": "x"}
    # Malformed YAML is warned about, not raised.
    assert parse_front_matter("---\n: : :\n---\nbody") == {}


def test_skill_body_strips_front_matter():
    skill = Skill(
        entity=ENTITY, aspect_urn="", artifact_urn="", content=SKILL_MD
    )
    assert skill.body.startswith("# Report structure")
    assert "description:" not in skill.body


def test_extract_token_strips_bearer_prefix():
    assert SkillManager._extract_token("Bearer abc") == "abc"
    assert SkillManager._extract_token("abc") == "abc"
    assert SkillManager._extract_token(None) is None


# ---------------------------------------------------------------------------
# Case 1: the skill does not exist
# ---------------------------------------------------------------------------


def test_load_skill_raises_when_no_aspect_exists(tmp_path):
    client = client_with(aspects=[])
    mgr = make_manager(tmp_path, client)

    with pytest.raises(SkillNotFound, match="No aspect with schema"):
        mgr.load_skill("does_not_exist")

    # Looked up the right entity/schema pair, and never tried to download.
    _, kwargs = client.list_aspects.call_args
    assert kwargs["entity"] == "urn:sd:crewai:crew.skill.does_not_exist"
    assert kwargs["schema"] == SKILL_SCHEMA
    client.get_artifact.assert_not_called()


def test_load_skill_raises_when_aspect_has_no_artifact_reference(tmp_path):
    client = client_with(aspects=[make_aspect(content={"version": "1.0.0"})])
    mgr = make_manager(tmp_path, client)

    with pytest.raises(SkillNotFound, match="has no artifact reference"):
        mgr.load_skill(ENTITY)
    client.get_artifact.assert_not_called()


def test_load_skill_raises_when_aspect_content_is_not_an_object(tmp_path):
    client = client_with(aspects=[make_aspect(content="just a string")])
    mgr = make_manager(tmp_path, client)

    with pytest.raises(SkillNotFound, match="not a JSON object"):
        mgr.load_skill(ENTITY)


def test_load_skill_raises_when_aspect_content_is_empty(tmp_path):
    client = client_with(aspects=[make_aspect(content=None)])
    mgr = make_manager(tmp_path, client)

    with pytest.raises(SkillNotFound, match="has no artifact reference"):
        mgr.load_skill(ENTITY)


def test_missing_skill_writes_nothing(tmp_path):
    mgr = make_manager(tmp_path, client_with(aspects=[]))

    with pytest.raises(SkillNotFound):
        mgr.load_skill(ENTITY)

    assert not mgr.skills_dir.exists()
    assert mgr.get_skills_path() is None


# ---------------------------------------------------------------------------
# Case 2: the skill exists but is not downloadable
# ---------------------------------------------------------------------------


def test_load_skill_propagates_artifact_lookup_failure(tmp_path):
    client = client_with(
        aspects=[make_aspect(content={"artifact": ARTIFACT_URN})],
        get_artifact_error=ValueError(f"artifact {ARTIFACT_URN} not found"),
    )
    mgr = make_manager(tmp_path, client)

    with pytest.raises(ValueError, match="not found"):
        mgr.load_skill(ENTITY)

    client.get_artifact.assert_called_once_with(ARTIFACT_URN)
    assert not mgr.skills_dir.exists()


def test_load_skill_propagates_artifact_read_failure(tmp_path):
    client = client_with(
        aspects=[make_aspect(content={"artifact": ARTIFACT_URN})],
        artifact=FakeArtifact(None, fail_on_open=IOError("403 Forbidden")),
    )
    mgr = make_manager(tmp_path, client)

    with pytest.raises(IOError, match="403 Forbidden"):
        mgr.load_skill(ENTITY)

    assert not mgr.skills_dir.exists()


def test_failed_skill_is_not_cached(tmp_path):
    """A failed load must not poison the cache - a retry should hit IVCAP again."""
    client = client_with(
        aspects=[make_aspect(content={"artifact": ARTIFACT_URN})],
        get_artifact_error=RuntimeError("boom"),
    )
    mgr = make_manager(tmp_path, client)

    with pytest.raises(RuntimeError):
        mgr.load_skill(ENTITY)

    client.list_aspects.return_value = iter(
        [make_aspect(content={"artifact": ARTIFACT_URN})]
    )
    client.get_artifact.side_effect = None
    client.get_artifact.return_value = FakeArtifact(SKILL_MD.encode("utf-8"))

    skill = mgr.load_skill(ENTITY)
    assert skill.name == "Scientific Review Writer Report"


def test_load_skills_skips_undownloadable_and_keeps_the_rest(tmp_path):
    """load_skills is best-effort: one bad skill must not lose the good ones."""
    good_aspect = make_aspect(content={"artifact": ARTIFACT_URN, "version": "2.0.0"})
    client = MagicMock()
    # 1st ref: no aspect. 2nd ref: aspect but the artifact fails. 3rd ref: fine.
    client.list_aspects.side_effect = [iter([]), iter([good_aspect]), iter([good_aspect])]
    client.get_artifact.side_effect = [
        RuntimeError("connection reset"),
        FakeArtifact(SKILL_MD.encode("utf-8")),
    ]
    mgr = make_manager(tmp_path, client)

    skills = mgr.load_skills(["missing", "broken", "good"])

    assert len(skills) == 1
    assert skills[0].entity == "urn:sd:crewai:crew.skill.good"
    assert skills[0].path.exists()


def test_load_skills_handles_empty_and_none(tmp_path):
    mgr = make_manager(tmp_path, client_with(aspects=[]))
    assert mgr.load_skills([]) == []
    assert mgr.load_skills(None) == []


# ---------------------------------------------------------------------------
# Case 3: the skill exists and is downloadable
# ---------------------------------------------------------------------------


def test_load_skill_returns_populated_skill(happy_manager):
    mgr, client = happy_manager

    skill = mgr.load_skill("scientific_review_writer_report")

    assert skill.entity == ENTITY
    assert skill.aspect_urn == ASPECT_URN
    assert skill.artifact_urn == ARTIFACT_URN
    assert skill.name == "Scientific Review Writer Report"
    assert skill.description == "How to structure a scientific review report."
    assert skill.metadata == {"version": "1.0.0", "author": "csiro"}
    # `version` comes from the aspect content, not the front matter.
    assert skill.version == "1.0.0"
    assert skill.body.startswith("# Report structure")
    client.get_artifact.assert_called_once_with(ARTIFACT_URN)


@pytest.mark.parametrize("key", ["artifact", "artifactUrn", "artifact-urn", "artifactId"])
def test_artifact_urn_is_read_from_any_supported_key(tmp_path, key):
    client = client_with(
        aspects=[make_aspect(content={key: ARTIFACT_URN})],
        artifact=FakeArtifact(SKILL_MD.encode("utf-8")),
    )
    mgr = make_manager(tmp_path, client)

    assert mgr.load_skill(ENTITY).artifact_urn == ARTIFACT_URN


def test_artifact_body_may_be_bytes_or_str(tmp_path):
    for body in (SKILL_MD, SKILL_MD.encode("utf-8")):
        client = client_with(
            aspects=[make_aspect(content={"artifact": ARTIFACT_URN})],
            artifact=FakeArtifact(body),
        )
        mgr = make_manager(tmp_path, client)
        assert mgr.load_skill(ENTITY).content == SKILL_MD


def test_load_skill_writes_skill_md_in_its_own_directory(happy_manager, tmp_path):
    mgr, _ = happy_manager

    skill = mgr.load_skill(ENTITY)

    expected = tmp_path / "skills" / "scientific-review-writer-report" / SKILL_FILE_NAME
    assert skill.path == expected
    assert expected.is_file()
    assert mgr.get_skills_path() == str((tmp_path / "skills").absolute())

    written = expected.read_text(encoding="utf-8")
    front_matter = parse_front_matter(written)
    # CrewAI requires name == directory name, and a non-empty description.
    assert front_matter["name"] == "scientific-review-writer-report"
    assert front_matter["description"] == "How to structure a scientific review report."
    assert front_matter["metadata"]["author"] == "csiro"
    # Body is kept verbatim.
    assert "# Report structure" in written


def test_saved_skill_md_gets_a_default_description_when_none_supplied(tmp_path):
    client = client_with(
        aspects=[make_aspect(content={"artifact": ARTIFACT_URN})],
        artifact=FakeArtifact("# Just a body, no front matter\n"),
    )
    mgr = make_manager(tmp_path, client)

    skill = mgr.load_skill(ENTITY)

    front_matter = parse_front_matter(skill.path.read_text(encoding="utf-8"))
    assert front_matter["name"] == "scientific-review-writer-report"
    assert front_matter["description"]  # non-empty is what CrewAI insists on
    assert ENTITY in front_matter["description"]


def test_saved_skill_md_is_loadable_by_crewai(happy_manager):
    """The whole point of the layout: CrewAI must accept the SKILL.md we write."""
    mgr, _ = happy_manager

    skill = mgr.load_skill(ENTITY)
    crew_skill = SkillManager._as_crew_skill(skill)

    assert crew_skill is not None
    assert crew_skill.name == "scientific-review-writer-report"


def test_as_crew_skill_returns_none_for_unsaved_skill():
    skill = Skill(entity=ENTITY, aspect_urn="", artifact_urn="", content=SKILL_MD)
    assert SkillManager._as_crew_skill(skill) is None


def test_load_skill_with_save_false_downloads_but_writes_nothing(tmp_path):
    client = client_with(
        aspects=[make_aspect(content={"artifact": ARTIFACT_URN})],
        artifact=FakeArtifact(SKILL_MD.encode("utf-8")),
    )
    mgr = make_manager(tmp_path, client)

    skill = mgr.load_skill(ENTITY, save=False)

    assert skill.content == SKILL_MD
    assert skill.path is None
    assert not mgr.skills_dir.exists()


def test_load_skill_is_cached_per_entity(happy_manager):
    """A skill named by several agents must only be downloaded once."""
    mgr, client = happy_manager

    first = mgr.load_skill("scientific_review_writer_report")
    second = mgr.load_skill(ENTITY)  # same entity, referenced by its full URN

    assert first is second
    assert client.list_aspects.call_count == 1
    assert client.get_artifact.call_count == 1


def test_load_skills_returns_all_resolvable_skills(tmp_path):
    aspects = [
        make_aspect(urn="urn:ivcap:aspect:a", content={"artifact": "urn:ivcap:artifact:a"}),
        make_aspect(urn="urn:ivcap:aspect:b", content={"artifact": "urn:ivcap:artifact:b"}),
    ]
    client = MagicMock()
    client.list_aspects.side_effect = [iter([aspects[0]]), iter([aspects[1]])]
    client.get_artifact.side_effect = [
        FakeArtifact("---\nname: alpha\ndescription: A\n---\nAlpha body\n"),
        FakeArtifact("---\nname: beta\ndescription: B\n---\nBeta body\n"),
    ]
    mgr = make_manager(tmp_path, client)

    skills = mgr.load_skills(["alpha", "beta"])

    assert [s.name for s in skills] == ["alpha", "beta"]
    assert {p.name for p in (tmp_path / "skills").iterdir()} == {"alpha", "beta"}


def test_as_prompt_renders_title_description_and_body(happy_manager):
    mgr, _ = happy_manager
    prompt = mgr.load_skill(ENTITY).as_prompt()

    assert prompt.startswith("# Skill: Scientific Review Writer Report")
    assert "How to structure a scientific review report." in prompt
    assert "# Report structure" in prompt


def test_cleanup_removes_downloaded_skills(happy_manager):
    mgr, _ = happy_manager
    mgr.load_skill(ENTITY)
    assert mgr.skills_dir.exists()

    mgr.cleanup()

    assert not mgr.skills_dir.exists()
    assert mgr.get_skills_path() is None
    # Cleaning up twice is harmless.
    mgr.cleanup()


def test_manager_authenticates_with_the_jobs_jwt(tmp_path):
    client = client_with(aspects=[])
    mgr = make_manager(tmp_path, client, token="Bearer jwt-abc")

    _, kwargs = mgr._ivcap_ctor.call_args
    assert kwargs["token"] == "jwt-abc"
