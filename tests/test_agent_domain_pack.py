"""Structural contract tests for the .agent/ domain pack (Wave 0).

There is no runtime agent-execution code yet -- .agent/ is prompts, tool manifests, and eval
scenarios (JSON/YAML/Markdown). These tests catch the class of bug that actually happens at this
stage: a manifest referencing a specialist that doesn't exist, agency.yaml enabling a tool with no
manifest behind it, an eval case with a malformed shape, or a retry constant drifting between
policy.md's prose and .env.example's real default. They do not execute a fleet run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / ".agent"
MANIFEST_DIR = AGENT_DIR / "tools" / "manifests"
DOMAIN_DIR = AGENT_DIR / "prompts" / "domains" / "auctor"
SPECIALISTS_DIR = DOMAIN_DIR / "specialists"
EVALS_DIR = DOMAIN_DIR / "evals"

# The 14 domain specialists, per ENGINEERING-WAVES.md's "Final role count" section.
EXPECTED_SPECIALISTS = {
    "researcher",
    "brand_strategist",
    "copywriter",
    "builder",
    "voice_qa",
    "deployer",
    "metrics_researcher",
    "trend_researcher",
    "signal_summarizer",
    "voice_writer",
    "content_strategist",
    "ghostwriter",
    "publisher",
    "engagement_analyst",
}

# Tools built into the Fabri kernel itself -- agency.yaml enables them by name but no
# .agent/tools/manifests/*.json file exists for them (they aren't domain-pack tools).
BUILTIN_TOOLS = {
    "read_file",
    "write_file",
    "edit_file",
    "list_dir",
    "python_exec",
    "batch",
    "spawn_subagent",
}

REQUIRED_MANIFEST_KEYS = {
    "name",
    "command",
    "input_schema",
    "output_schema",
    "allowed_agents",
    "risk_level",
    "retry_policy",
    "timeout_s",
}


def _load_manifests() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(MANIFEST_DIR.glob("*.json"))}


def _load_agency_yaml() -> dict:
    return yaml.safe_load((AGENT_DIR / "agency.yaml").read_text())


def _load_cases() -> list[dict]:
    return json.loads((EVALS_DIR / "cases.json").read_text())


# --------------------------------------------------------------------------- agency.yaml


def test_agency_yaml_is_valid_yaml_with_expected_shape():
    doc = _load_agency_yaml()
    assert doc["agent"]["name"] == "auctor-agency-lead"
    assert "tools" in doc and "enabled" in doc["tools"]
    assert isinstance(doc["tools"]["enabled"], list) and doc["tools"]["enabled"]


def test_every_enabled_non_builtin_tool_has_a_manifest():
    doc = _load_agency_yaml()
    manifests = _load_manifests()
    enabled = set(doc["tools"]["enabled"])
    domain_tools = enabled - BUILTIN_TOOLS
    missing = sorted(t for t in domain_tools if t not in manifests)
    assert not missing, f"agency.yaml enables tools with no manifest file: {missing}"


def test_github_activity_research_not_yet_enabled():
    """HANDOFF-github-integration.md is explicitly paused; agency.yaml must not silently enable
    a tool whose manifest doesn't exist yet."""
    doc = _load_agency_yaml()
    assert "github_activity_research" not in doc["tools"]["enabled"]
    assert not (MANIFEST_DIR / "github_activity_research.json").exists()


# --------------------------------------------------------------------------- tool manifests


def test_every_manifest_is_valid_json_with_required_keys():
    manifests = _load_manifests()
    assert manifests, "expected at least one tool manifest"
    for stem, manifest in manifests.items():
        missing = REQUIRED_MANIFEST_KEYS - manifest.keys()
        assert not missing, f"{stem}.json missing required keys: {missing}"


def test_manifest_name_field_matches_filename():
    for stem, manifest in _load_manifests().items():
        assert manifest["name"] == stem, (
            f"{stem}.json's 'name' field is {manifest['name']!r}, expected {stem!r}"
        )


def test_manifest_allowed_agents_reference_real_specialists():
    """Every allowed_agents entry must be one of the 12 specialists that actually has a prompt
    file -- a typo'd or renamed role here silently locks a tool out at runtime."""
    for stem, manifest in _load_manifests().items():
        for role in manifest["allowed_agents"]:
            assert role in EXPECTED_SPECIALISTS, (
                f"{stem}.json allows unknown agent role {role!r} "
                f"(not in {sorted(EXPECTED_SPECIALISTS)})"
            )


def test_manifest_risk_level_and_approval_policy_are_consistent():
    """A high-risk, side-effecting tool (publish/deploy) must require approval; approval_policy
    is either the literal string 'none' or an object with a 'required' bool."""
    for stem, manifest in _load_manifests().items():
        risk = manifest["risk_level"]
        assert risk in {"low", "medium", "high"}, f"{stem}.json has unknown risk_level {risk!r}"
        policy = manifest.get("approval_policy")
        if risk == "high":
            assert isinstance(policy, dict) and policy.get("required") is True, (
                f"{stem}.json is risk_level 'high' but does not require approval: {policy!r}"
            )


def test_publish_and_deploy_tools_are_not_retried_automatically():
    """publish_x/publish_linkedin/deploy_site are irreversible side effects -- an automatic retry
    could double-publish or double-deploy. max_attempts must be 1 for these."""
    irreversible = {"publish_x", "publish_linkedin", "deploy_site"}
    manifests = _load_manifests()
    for name in irreversible:
        assert name in manifests, f"expected manifest {name}.json to exist"
        max_attempts = manifests[name]["retry_policy"]["max_attempts"]
        assert max_attempts == 1, (
            f"{name}.json allows {max_attempts} attempts; irreversible publish/deploy tools "
            "must not be auto-retried (max_attempts must be 1)"
        )


# --------------------------------------------------------------------------- specialists


def test_all_specialists_have_a_prompt_file():
    present = {p.stem for p in SPECIALISTS_DIR.glob("*.md")}
    missing = EXPECTED_SPECIALISTS - present
    assert not missing, f"missing specialist prompt files: {missing}"


def test_no_unexpected_specialist_files():
    present = {p.stem for p in SPECIALISTS_DIR.glob("*.md")}
    extra = present - EXPECTED_SPECIALISTS
    assert not extra, (
        f"unexpected specialist file(s) {extra} not in ENGINEERING-WAVES.md's 14-role roster "
        "-- update EXPECTED_SPECIALISTS here if this is an intentional new role"
    )


# --------------------------------------------------------------------------- evals


def test_suite_json_points_at_a_real_cases_file():
    suite = json.loads((EVALS_DIR / "suite.json").read_text())
    cases_path = EVALS_DIR / suite["cases_file"]
    assert cases_path.exists(), f"suite.json's cases_file {suite['cases_file']!r} does not exist"


def test_suite_retry_constants_match_env_example():
    """policy.md/.env.example define SITE_MAX_RETRY_ATTEMPTS and CONTENT_MAX_RETRY_ATTEMPTS once;
    suite.json's *_under_test fields must not silently drift from the real default."""
    suite = json.loads((EVALS_DIR / "suite.json").read_text())
    env_text = (REPO_ROOT / ".env.example").read_text()

    site_match = re.search(r"SITE_MAX_RETRY_ATTEMPTS=(\d+)", env_text)
    content_match = re.search(r"CONTENT_MAX_RETRY_ATTEMPTS=(\d+)", env_text)
    assert site_match and content_match, ".env.example missing retry-attempt defaults"

    assert suite["site_max_retry_attempts_under_test"] == int(site_match.group(1))
    assert suite["content_max_retry_attempts_under_test"] == int(content_match.group(1))


REQUIRED_CASE_KEYS = {
    "id",
    "name",
    "specialist_refs",
    "setup",
    "steps",
    "expected_outcome",
    "assertions",
}


def test_eval_cases_have_required_shape():
    cases = _load_cases()
    assert cases, "expected at least one eval case"
    for case in cases:
        missing = REQUIRED_CASE_KEYS - case.keys()
        assert not missing, f"case {case.get('id', '<no id>')!r} missing keys: {missing}"
        assert case["steps"], f"case {case['id']!r} has no steps"
        assert case["assertions"], f"case {case['id']!r} has no assertions"


def test_eval_case_ids_are_unique():
    cases = _load_cases()
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate eval case ids: {dupes}"


def test_eval_case_specialist_refs_point_at_real_files():
    for case in _load_cases():
        for ref in case["specialist_refs"]:
            ref_path = REPO_ROOT / ref
            assert ref_path.exists(), f"case {case['id']!r} references missing file {ref}"


# --------------------------------------------------------------------------- policy <-> artifacts


def test_policy_retry_prose_matches_env_example_defaults():
    """policy.md states the default retry counts in prose ("default `2`" / "default `1`"); this
    guards against the prose drifting from the real env default without updating both."""
    policy_text = (DOMAIN_DIR / "policy.md").read_text()
    env_text = (REPO_ROOT / ".env.example").read_text()

    site_default = re.search(r"SITE_MAX_RETRY_ATTEMPTS.*?default `(\d+)`", policy_text)
    content_default = re.search(r"CONTENT_MAX_RETRY_ATTEMPTS.*?default `(\d+)`", policy_text)
    assert site_default and content_default, "policy.md missing documented retry defaults"

    env_site = re.search(r"SITE_MAX_RETRY_ATTEMPTS=(\d+)", env_text)
    env_content = re.search(r"CONTENT_MAX_RETRY_ATTEMPTS=(\d+)", env_text)

    assert site_default.group(1) == env_site.group(1)
    assert content_default.group(1) == env_content.group(1)


def test_published_post_platform_status_has_no_top_level_boolean_in_artifacts_doc():
    """Regression guard for the #1 ops-flagged failure mode (policy.md's PUBLISH STATUS rule):
    artifacts.md must document platform_status as per-platform, never introduce a bare
    top-level 'published' boolean field."""
    artifacts_text = (DOMAIN_DIR / "artifacts.md").read_text()
    assert "platform_status" in artifacts_text
    assert '"published": true' not in artifacts_text.replace(" ", "")
    assert '"published":false' not in artifacts_text.replace(" ", "")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
