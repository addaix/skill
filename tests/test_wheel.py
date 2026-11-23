"""The wheel-included-skills recipe, end to end (addaix/skill#31).

A fixture package keeps its skill in top-level ``skills/``; hatchling builds a wheel with
the recipe's ``force-include``; :func:`check_wheel_skills` accepts it; the wheel, unpacked
onto ``sys.path``, is found by :func:`find_package_skills` (what ``skill
install-from-package`` uses). Built offline, with the installed hatchling.
"""

import os
import sys
import zipfile
from pathlib import Path

import pytest

hatchling_build = pytest.importorskip("hatchling.build")

from skill import find_package_skills
from skill.wheel import (
    WHEEL_SKILLS_DIR,
    check_wheel_skills,
    wheel_skills_config,
    wheel_skills_snippet,
)

SKILL_MD = (
    "---\nname: {name}\ndescription: Use {name} for things.\n{extra}---\n\nBody.\n"
)


def _fixture_repo(
    root: Path, *, dist="demo-skills-pkg", pkg="demo_skills_pkg", dev=False
) -> Path:
    (root / pkg).mkdir(parents=True)
    (root / pkg / "__init__.py").write_text('"""Demo."""\n')
    for name in ("demo-quickstart", "demo-advanced"):
        d = root / "skills" / name
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text(SKILL_MD.format(name=name, extra=""))
        (d / "references" / "api.md").write_text(f"# {name} API\n")
    if dev:
        d = root / "skills" / "demo-dev-release"
        d.mkdir()
        (d / "SKILL.md").write_text(
            SKILL_MD.format(
                name="demo-dev-release", extra="metadata:\n  audience: developer\n"
            )
        )
    # The .claude/skills bridge: relative symlinks, which the check must not count twice.
    bridge = root / ".claude" / "skills"
    bridge.mkdir(parents=True)
    (bridge / "demo-quickstart").symlink_to(
        Path("..", "..", "skills", "demo-quickstart")
    )
    (root / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n\n'
        "[project]\n"
        f'name = "{dist}"\n'
        'version = "0.1.0"\n\n'
        f"{wheel_skills_snippet(pkg)}\n"
    )
    return root


def _build(repo: Path, out: Path) -> Path:
    out.mkdir()
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        name = hatchling_build.build_wheel(str(out))
    finally:
        os.chdir(cwd)
    return out / name


def test_snippet_is_hatch_force_include():
    assert wheel_skills_snippet("p") == (
        '[tool.hatch.build.targets.wheel.force-include]\n"skills" = "p/_skills"'
    )


def test_recipe_builds_a_wheel_that_passes_the_check_and_installs(
    tmp_path, monkeypatch
):
    repo = _fixture_repo(tmp_path / "repo")
    wheel = _build(repo, tmp_path / "dist")
    names = zipfile.ZipFile(wheel).namelist()
    assert f"demo_skills_pkg/{WHEEL_SKILLS_DIR}/demo-quickstart/SKILL.md" in names
    assert (
        f"demo_skills_pkg/{WHEEL_SKILLS_DIR}/demo-advanced/references/api.md" in names
    )
    assert not (repo / "demo_skills_pkg" / WHEEL_SKILLS_DIR).exists()  # wheel-only copy

    report = check_wheel_skills(wheel, repo)
    assert report.ok, str(report)
    assert report.skills == ["demo-advanced", "demo-quickstart"]

    site = tmp_path / "site"
    zipfile.ZipFile(wheel).extractall(site)
    monkeypatch.syspath_prepend(str(site))
    for mod in [m for m in sys.modules if m.startswith("demo_skills_pkg")]:
        monkeypatch.delitem(sys.modules, mod)
    found = find_package_skills("demo-skills-pkg")
    assert found == site / "demo_skills_pkg" / WHEEL_SKILLS_DIR
    assert sorted(p.name for p in found.iterdir()) == [
        "demo-advanced",
        "demo-quickstart",
    ]


def test_check_fails_on_a_wheel_without_the_recipe(tmp_path):
    repo = _fixture_repo(tmp_path / "repo")
    text = (repo / "pyproject.toml").read_text()
    (repo / "pyproject.toml").write_text(text.split("[tool.hatch")[0])
    wheel = _build(repo, tmp_path / "dist")
    report = check_wheel_skills(wheel, repo, package="demo_skills_pkg")
    assert not report.ok
    assert any(
        "demo-quickstart: SKILL.md is not in the wheel" in p for p in report.problems
    )


def test_check_fails_on_a_stale_or_duplicated_skill(tmp_path):
    repo = _fixture_repo(tmp_path / "repo")
    wheel = _build(repo, tmp_path / "dist")
    # The repository moved on after the build: the wheel is stale.
    (repo / "skills" / "demo-advanced" / "SKILL.md").write_text(
        "---\nname: demo-advanced\n---\nNew.\n"
    )
    # And a second real copy appeared (gh skill would report a duplicate).
    dup = repo / "demo_skills_pkg" / "data" / "skills" / "demo-quickstart"
    dup.mkdir(parents=True)
    (dup / "SKILL.md").write_text("---\nname: demo-quickstart\n---\n")
    problems = "\n".join(check_wheel_skills(wheel, repo).problems)
    assert "demo-advanced: SKILL.md differs from the repository" in problems
    assert "demo-quickstart: the repository holds it in 2 places" in problems


def test_check_fails_on_a_committed_copy_of_the_wheel_folder(tmp_path):
    repo = _fixture_repo(tmp_path / "repo")
    wheel = _build(repo, tmp_path / "dist")
    (repo / "demo_skills_pkg" / WHEEL_SKILLS_DIR).mkdir()
    problems = check_wheel_skills(wheel, repo).problems
    assert any("exists in the repository" in p for p in problems)


def test_a_developer_skill_shipped_to_users_is_a_warning(tmp_path):
    repo = _fixture_repo(tmp_path / "repo", dev=True)
    wheel = _build(repo, tmp_path / "dist")
    report = check_wheel_skills(wheel, repo)
    assert report.ok
    assert report.warnings == [
        "demo-dev-release: a developer skill (audience: developer) ships to users"
    ]


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.org",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
    )


def test_untracked_and_os_litter_are_not_expected_in_the_wheel(tmp_path):
    """Review findings: a Finder .DS_Store (which hatchling never ships) and a git-ignored
    file (which a build through the sdist drops) are not expected in the wheel."""
    repo = _fixture_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("*.env\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture")
    (repo / "skills" / "demo-quickstart" / ".DS_Store").write_bytes(b"x")
    (repo / "skills" / "demo-quickstart" / "secret.env").write_text("TOKEN=x\n")
    wheel = _build(repo, tmp_path / "dist")
    report = check_wheel_skills(wheel, repo)
    assert report.ok, str(report)


def test_only_skills_folders_count_as_duplicates(tmp_path):
    """A fixture folder named like a skill, and a symlinked skills/ copy in a non-hidden
    folder, are not places gh skill discovers a second real copy."""
    repo = _fixture_repo(tmp_path / "repo")
    fixture = repo / "tests" / "fixtures" / "demo-quickstart"
    fixture.mkdir(parents=True)
    (fixture / "SKILL.md").write_text("---\nname: demo-quickstart\n---\n")
    (repo / "docs" / "skills").mkdir(parents=True)
    (repo / "docs" / "skills" / "demo-advanced").symlink_to(
        Path("..", "..", "skills", "demo-advanced")
    )
    wheel = _build(repo, tmp_path / "dist")
    assert check_wheel_skills(wheel, repo).ok


def test_setuptools_variant_and_config_dict():
    assert wheel_skills_config("p", backend="setuptools")["tool"]["setuptools"][
        "package-dir"
    ] == {"p._skills": "skills"}
    assert "force-include" in wheel_skills_snippet("p")
    with pytest.raises(ValueError):
        wheel_skills_config("p", backend="flit")


def test_cli_reports_a_missing_wheel_cleanly(tmp_path):
    from skill.__main__ import check_wheel_skills as cli

    with pytest.raises(SystemExit, match="Cannot read the wheel"):
        cli(str(tmp_path / "nope.whl"), repo_root=str(_fixture_repo(tmp_path / "repo")))
