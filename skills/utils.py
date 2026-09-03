"""
Skill utilities for IVCAP CrewAI Service.

Skills are markdown documents (with optional YAML front matter) that describe
how an agent should perform a piece of work - e.g. the expected structure of a
scientific review report.

They are stored on IVCAP as an aspect of schema `urn:sd:schema:crew.skill`
attached to a skill entity, e.g.

    entity: urn:sd:crewai:crew.skill.scientific_review_writer_report
    schema: urn:sd:schema:crew.skill
    content: {
        "$entity": "urn:sd:crewai:crew.skill.scientific_review_writer_report",
        "$schema": "urn:sd:schema:crew.skill",
        "artifact": "urn:ivcap:artifact:80968d8c-7a34-499c-b13b-79974a3ea98c",
        "version": "1.0.0"
    }

Loading a skill is therefore a two-step download (mirroring `download_manager`):
  1. Look up the aspect by (entity, schema) and read the artifact URN from its content.
  2. Download that artifact - its body is the skill markdown.

Downloaded skills are laid out per the CrewAI Agent Skills standard, i.e. one
directory per skill holding a `SKILL.md`, so they can be handed straight to
`Agent(skills=[...])` - CrewAI renders them into the agent's system prompt.

Usage:
    mgr = SkillManager(job_context=jobCtxt, parent_dir=runs_base_dir)
    skill = mgr.load_skill("urn:sd:crewai:crew.skill.scientific_review_writer_report")
    print(skill.body)         # markdown without front matter
    agent = Agent(..., skills=[skill.crew_skill])
    mgr.cleanup()             # remove downloaded skill files
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from crewai.skills import Skill as CrewAISkill, activate_skill
from crewai.skills.parser import SKILL_FILENAME, load_skill_metadata
from crewai.skills.models import MAX_DESCRIPTION_LENGTH
from crewai.skills.validation import MAX_SKILL_NAME_LENGTH
from ivcap_client import IVCAP
from ivcap_service import JobContext, getLogger

logger = getLogger("app.skills")

IVCAP_URL = os.environ.get("IVCAP_BASE_URL", "https://develop.ivcap.net")

# Schema all skill aspects are registered under.
SKILL_SCHEMA = "urn:sd:schema:crew.skill"

# Skill entities follow `urn:sd:crewai:crew.skill.{name}`, so a bare skill name
# can be expanded into a full entity URN.
SKILL_ENTITY_PREFIX = "urn:sd:crewai:crew.skill."

# Keys the artifact URN may appear under in the aspect content.
ARTIFACT_KEYS = ("artifact", "artifactUrn", "artifact-urn", "artifactId")

# Each skill lives in its own directory holding this file (CrewAI's SKILL.md).
SKILL_FILE_NAME = SKILL_FILENAME

# CrewAI requires skill (and hence directory) names to be kebab-case, so IVCAP
# skill names such as `scientific_review_writer_report` get normalised.
_UNSAFE_NAME_CHARS_RE = re.compile(r"[^a-z0-9]+")

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class SkillNotFound(Exception):
    """Raised when a skill aspect or its artifact cannot be resolved on IVCAP."""


@dataclass
class Skill:
    """A skill downloaded from IVCAP."""

    entity: str
    aspect_urn: str
    artifact_urn: str
    content: str
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: Optional[str] = None
    path: Optional[Path] = None
    crew_skill: Optional[CrewAISkill] = None

    @property
    def body(self) -> str:
        """Skill markdown with the YAML front matter stripped."""
        return _FRONT_MATTER_RE.sub("", self.content, count=1).strip()

    def as_prompt(self) -> str:
        """Render the skill for injection into an agent backstory or task description."""
        title = self.name or self.entity.rsplit(".", 1)[-1]
        header = f"# Skill: {title}"
        if self.description:
            header = f"{header}\n{self.description}"
        return f"{header}\n\n{self.body}"


def skill_entity_urn(name_or_urn: str) -> str:
    """
    Expand a bare skill name into a full entity URN.

    >>> skill_entity_urn("scientific_review_writer_report")
    'urn:sd:crewai:crew.skill.scientific_review_writer_report'
    >>> skill_entity_urn("urn:sd:crewai:crew.skill.foo")
    'urn:sd:crewai:crew.skill.foo'
    """
    if name_or_urn.startswith("urn:"):
        return name_or_urn
    return f"{SKILL_ENTITY_PREFIX}{name_or_urn}"


def skill_dir_name(skill: "Skill") -> str:
    """
    Name of a skill's directory - and of the skill itself as far as CrewAI is
    concerned: its front matter `name`, else the last segment of its entity URN.

    CrewAI's Agent Skills standard only accepts kebab-case names and requires
    the directory to be named after the skill, so anything else is normalised.

    >>> skill_dir_name(Skill(entity="urn:sd:crewai:crew.skill.foo_bar", aspect_urn="", artifact_urn="", content=""))
    'foo-bar'
    """
    raw = skill.name or skill.entity.rsplit(".", 1)[-1]
    name = _UNSAFE_NAME_CHARS_RE.sub("-", raw.lower()).strip("-")
    return name[:MAX_SKILL_NAME_LENGTH].strip("-") or "skill"


def parse_front_matter(content: str) -> Dict[str, Any]:
    """Parse the YAML front matter of a skill document; returns {} when absent/invalid."""
    m = _FRONT_MATTER_RE.match(content)
    if not m:
        return {}
    try:
        parsed = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        logger.warning(f"Could not parse skill front matter: {e}")
        return {}
    return parsed if isinstance(parsed, dict) else {}


class SkillManager:
    """
    Downloads skills from IVCAP for a specific job.

    Directory structure - `skills/` under the job directory passed in as
    `parent_dir`, which service.py sets to {cwd}/runs/{job_id}, alongside the
    other job-isolated dirs (inputs/, outputs/):
        {parent_dir}/skills/
            scientific-review-writer-report/SKILL.md
            {other-skill}/SKILL.md
    """

    def __init__(self, job_context: JobContext, parent_dir: str):
        self.job_id = job_context.job_id
        self.skills_dir = Path(f"{parent_dir}/skills")
        # `job_context.ivcap` builds an unauthenticated client when running inside
        # the platform, so build our own with the job's JWT (same as DownloadManager).
        self.ivcap_client = IVCAP(
            url=IVCAP_URL, token=self._extract_token(job_context.job_authorization)
        )
        self._cache: Dict[str, Skill] = {}

    @staticmethod
    def _extract_token(authorization: Optional[str]) -> Optional[str]:
        if isinstance(authorization, str) and authorization.startswith("Bearer "):
            return authorization[len("Bearer ") :]
        return authorization

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_skill(self, name_or_urn: str, *, save: bool = True) -> Skill:
        """
        Load a single skill from IVCAP.

        Args:
            name_or_urn: Skill name (`scientific_review_writer_report`) or full
                entity URN (`urn:sd:crewai:crew.skill.scientific_review_writer_report`).
            save: Also write the skill markdown to the job's skills directory.

        Returns:
            The downloaded Skill.

        Raises:
            SkillNotFound: If no aspect exists for the entity, or it carries no artifact.
        """
        entity = skill_entity_urn(name_or_urn)
        if entity in self._cache:
            return self._cache[entity]

        aspect_urn, content = self._read_skill_aspect(entity)
        artifact_urn = next(
            (content[k] for k in ARTIFACT_KEYS if isinstance(content.get(k), str)), None
        )
        if not artifact_urn:
            raise SkillNotFound(
                f"Skill aspect '{aspect_urn}' for entity '{entity}' has no artifact "
                f"reference (looked for {', '.join(ARTIFACT_KEYS)})"
            )

        logger.info(f"Downloading skill artifact {artifact_urn} for '{entity}'")
        artifact = self.ivcap_client.get_artifact(artifact_urn)
        text = self._read_artifact_text(artifact)

        front_matter = parse_front_matter(text)
        skill = Skill(
            entity=entity,
            aspect_urn=aspect_urn,
            artifact_urn=artifact_urn,
            content=text,
            name=front_matter.get("name"),
            description=front_matter.get("description"),
            metadata=front_matter.get("metadata") or {},
            version=content.get("version"),
        )

        if save:
            skill.path = self._save(skill)

        logger.info(
            f"Loaded skill '{skill.name or entity}' "
            f"(version {skill.version or 'unknown'}, {len(text)} chars)"
        )
        self._cache[entity] = skill
        return skill

    def load_skills(
        self, names_or_urns: List[str], *, save: bool = True
    ) -> List[Skill]:
        """
        Load several skills, skipping (with a warning) any that fail to resolve.
        """
        skills: List[Skill] = []
        for ref in names_or_urns or []:
            try:
                skills.append(self.load_skill(ref, save=save))
            except Exception as e:
                logger.warning(f"Failed to load skill '{ref}': {e}")
        return skills

    def cleanup(self):
        """Remove all downloaded skill files for this job."""
        if self.skills_dir.exists():
            try:
                shutil.rmtree(self.skills_dir)
                logger.info(f"Cleaned up skills for job {self.job_id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup skills: {e}")

    def get_skills_path(self) -> Optional[str]:
        """Return absolute path to the skills directory if it exists."""
        if self.skills_dir.exists():
            return str(self.skills_dir.absolute())
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_skill_aspect(self, entity: str) -> Tuple[str, Dict[str, Any]]:
        """
        Find the most recent skill aspect for `entity` and return (aspect_urn, content).
        """
        logger.info(
            f"Looking up skill aspect for entity '{entity}' (schema {SKILL_SCHEMA})"
        )
        aspects = list(
            self.ivcap_client.list_aspects(
                entity=entity,
                schema=SKILL_SCHEMA,
                limit=1,
                order_by="valid_from",
                order_direction="DESC",
                include_content=True,
            )
        )
        if not aspects:
            raise SkillNotFound(
                f"No aspect with schema '{SKILL_SCHEMA}' found for entity '{entity}'"
            )

        aspect = aspects[0]
        content = aspect.content or {}
        if not isinstance(content, dict):
            raise SkillNotFound(
                f"Skill aspect '{aspect.urn}' content is not a JSON object"
            )
        logger.info(f"  Found skill aspect {aspect.urn}: {content}")
        return aspect.urn, content

    @staticmethod
    def _read_artifact_text(artifact) -> str:
        """
        Read an artifact's body as text.

        `open()` loads the whole blob into memory, which is fine here — skills
        are small markdown documents. It yields bytes for platform artifacts and
        text for local-file ones, hence the conditional decode.
        """
        with artifact.open() as f:
            raw = f.read()
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def _save(self, skill: Skill) -> Path:
        """
        Write the skill into its own directory under the job's skills dir:

            {skills_dir}/{skill_name}/SKILL.md

        This is the layout CrewAI's Agent Skills standard expects, so the result
        can be handed to `Agent(skills=[...])` (see `_as_crew_skill`). The
        directory also leaves room for any resources a skill ships with
        (`scripts/`, `references/`, `assets/`).
        """
        name = skill_dir_name(skill)
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        path = skill_dir / SKILL_FILE_NAME
        path.write_text(self._as_skill_md(skill, name), encoding="utf-8")
        logger.info(f"  Saved skill → {path}")
        return path

    @staticmethod
    def _as_skill_md(skill: Skill, name: str) -> str:
        """
        Render the downloaded markdown as a spec-compliant SKILL.md.

        The body is kept verbatim; the front matter is rewritten so CrewAI can
        parse it - `name` must be the (normalised) directory name and a
        non-empty `description` is mandatory. Any other keys are preserved.
        """
        front_matter = dict(parse_front_matter(skill.content))
        front_matter["name"] = name
        description = (
            skill.description
            or front_matter.get("description")
            or f"IVCAP skill '{name}' ({skill.entity})"
        )
        front_matter["description"] = str(description)[:MAX_DESCRIPTION_LENGTH]

        # CrewAI types metadata as a string→string mapping.
        metadata = front_matter.get("metadata")
        metadata = (
            {k: str(v) for k, v in metadata.items()}
            if isinstance(metadata, dict)
            else {}
        )
        if skill.version:
            metadata.setdefault("version", str(skill.version))
        if metadata:
            front_matter["metadata"] = metadata
        else:
            front_matter.pop("metadata", None)

        yaml_block = yaml.safe_dump(front_matter, sort_keys=False).strip()
        return f"---\n{yaml_block}\n---\n\n{skill.body}\n"

    @staticmethod
    def _as_crew_skill(skill: Skill) -> Optional[CrewAISkill]:
        """
        Load the saved skill as a CrewAI Skill, fully disclosed so CrewAI injects
        the whole SKILL.md into the agent's system prompt.

        Returns None (with a warning) if CrewAI rejects the document, so one bad
        skill does not fail crew construction.
        """
        if skill.path is None:
            return None
        try:
            return activate_skill(load_skill_metadata(skill.path.parent))
        except Exception as e:
            logger.warning(
                f"CrewAI could not load skill '{skill.entity}' from {skill.path}: {e}"
            )
            return None
