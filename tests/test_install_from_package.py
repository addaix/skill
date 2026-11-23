"""Tests for install_from_package / find_package_skills and the gh-install scope."""

import importlib
import subprocess
import sys

import pytest

from skill import find_package_skills, install_from_package, install_from_github

install_mod = importlib.import_module("skill.install")

_SKILL = "---\nname: {name}\ndescription: Does {name} things. Use when testing.\n---\n\n# {name}\n\nBody.\n"


def _make_dist(
    root, *, dist="demo-dist", pkg="demo_pkg", subpath=("_skills",), skills=("alpha",)
):
    package = root / pkg
    package.mkdir(parents=True, exist_ok=True)
    skills_dir = package.joinpath(*subpath)
    for name in skills:
        (skills_dir / name).mkdir(parents=True)
        (skills_dir / name / "SKILL.md").write_text(_SKILL.format(name=name))
    (package / "__init__.py").write_text("")
    info = root / f"{dist.replace('-', '_')}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist}\nVersion: 1.0\n"
    )
    (info / "top_level.txt").write_text(pkg + "\n")
    importlib.invalidate_caches()
    return package


@pytest.fixture()
def fake_dist(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()
    yield site
    sys.modules.pop("demo_pkg", None)


@pytest.mark.parametrize("subpath", [("_skills",), ("data", "skills")])
def test_find_package_skills_both_layouts(fake_dist, subpath):
    # the distribution name differs from the package name: metadata, not a folder guess
    _make_dist(fake_dist, subpath=subpath)
    assert find_package_skills("demo-dist").parts[-len(subpath) :] == subpath


def test_missing_distribution_and_no_skills(fake_dist):
    with pytest.raises(LookupError, match="not installed"):
        find_package_skills("no-such-dist-xyz")
    _make_dist(fake_dist, dist="bare-dist", pkg="bare_pkg", skills=())
    with pytest.raises(LookupError, match="ships no skills"):
        find_package_skills("bare-dist")


def test_install_from_package_links_each_skill(fake_dist, tmp_path):
    _make_dist(fake_dist, skills=("alpha", "beta"))
    project = tmp_path / "proj"
    project.mkdir()
    out = install_from_package(
        "demo-dist", agent_targets=["claude-code"], project_dir=project, copy=True
    )
    assert sorted(out) == ["alpha", "beta"]
    for name, paths in out.items():
        assert (paths["claude-code"] / "SKILL.md").is_file()
        assert project in paths["claude-code"].parents


def test_install_from_package_skips_invalid(fake_dist, tmp_path):
    package = _make_dist(fake_dist, skills=("good",))
    bad = package / "_skills" / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter at all")
    project = tmp_path / "proj"
    project.mkdir()
    with pytest.warns(UserWarning, match="Skipping invalid skill"):
        out = install_from_package(
            "demo-dist", agent_targets=["claude-code"], project_dir=project, copy=True
        )
    assert list(out) == ["good"]


def test_gh_install_passes_scope(monkeypatch):
    monkeypatch.setattr(install_mod.shutil, "which", lambda _: "/usr/bin/gh")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(install_mod.subprocess, "run", fake_run)
    install_from_github("o/r", "s", scope="global")
    assert calls[0][-2:] == ["--scope", "user"]
    with pytest.raises(ValueError, match="scope"):
        install_from_github("o/r", "s", scope="nonsense")


def test_cli_commands_exist():
    out = subprocess.run(
        [sys.executable, "-m", "skill", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    assert "install-from-package" in out and "gh-install" in out


def test_a_fresh_claude_home_without_skills_is_still_a_home(tmp_path, monkeypatch):
    """A fresh ~/.claude has no skills/ folder yet (addaix/skill#37)."""
    from skill.bundled import claude_homes

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude-backup").mkdir()  # no skills/: not a home
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows reads this, not HOME
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert claude_homes() == [home / ".claude"]
