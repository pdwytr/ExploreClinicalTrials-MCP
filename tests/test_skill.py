"""The ctgov-search skill follows the Agent Skills specification (https://agentskills.io/specification)
and stays small enough for progressive disclosure."""

import json
import re
from pathlib import Path

import pytest
import yaml

from cheiron.fetch.models import SEARCH_PARAMS
from cheiron.workflow import SearchPlan

SKILL_DIR = Path(__file__).resolve().parent.parent / "src" / "cheiron" / "agents" / "skills" / "ctgov-search"
SKILL_MD = SKILL_DIR / "SKILL.md"


def split_skill() -> tuple[dict, str]:
    text = SKILL_MD.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter between --- lines"
    return yaml.safe_load(match.group(1)), match.group(2)


def test_frontmatter_follows_spec():
    meta, _ = split_skill()
    name = meta["name"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert name == SKILL_DIR.name, "name must match the directory name"
    assert 1 <= len(meta["description"]) <= 1024
    assert all(isinstance(v, str) for v in meta.get("metadata", {}).values()), "metadata values must be strings"


def test_body_stays_within_recommended_size():
    _, body = split_skill()
    assert len(body.splitlines()) < 500
    assert len(body) / 4 < 5000, "keep SKILL.md under ~5,000 tokens; move detail to references/"


def test_every_reference_exists_and_is_linked_from_skill_md():
    _, body = split_skill()
    linked = set(re.findall(r"references/[\w.-]+\.md", body))
    on_disk = {f"references/{p.name}" for p in (SKILL_DIR / "references").glob("*.md")}
    assert linked == on_disk, "every reference file must be listed (with when to read it) in SKILL.md"


@pytest.mark.parametrize("ref", sorted((SKILL_DIR / "references").glob("*.md")), ids=lambda p: p.name)
def test_reference_files_stay_focused(ref):
    assert len(ref.read_text()) / 4 < 6000, "split large references so the agent loads less"


def test_worked_examples_are_valid_plans():
    _, body = split_skill()
    examples = re.findall(r"```json\n(.*?)\n```", body, re.DOTALL)
    assert len(examples) >= 3
    for example in examples:
        SearchPlan.model_validate(json.loads(example))


@pytest.mark.parametrize("path", [SKILL_MD, SKILL_DIR / "references" / "parameters.md"], ids=lambda p: p.name)
def test_skill_only_teaches_parameters_code_accepts(path):
    taught = set(re.findall(r"`((?:query|filter)\.\w+)`", path.read_text()))
    assert taught <= SEARCH_PARAMS, f"teaches parameters code rejects: {taught - SEARCH_PARAMS}"
