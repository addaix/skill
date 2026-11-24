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


_HATCH_MAPPING = '[tool.hatch.build.targets.wheel.force-include]\n"skills" = "{pkg}/_skills"\n'
_SETUPTOOLS_MAPPING = '[tool.setuptools]\npackage-dir = {{ "{pkg}._skills" = "skills" }}\n'


def _make_editable_dist(
    site, project, *, dist="edit-dist", pkg="edit_pkg", editable=True, mapping=_HATCH_MAPPING, url=None
):
    """An editable install of ``project`` (``wheel-included-skills`` layout) seen from ``site``.

    The skills sit in the project's top-level ``skills/``, which a wheel build maps into
    the package; an editable install has no such mapping, only ``direct_url.json``.
    """
    import json

    (project / pkg).mkdir(parents=True)
    (project / pkg / "__init__.py").write_text("")
    if mapping is not None:
        (project / "pyproject.toml").write_text(mapping.format(pkg=pkg))
    skill_dir = project / "skills" / "beta"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_SKILL.format(name="beta"))
    info = site / f"{dist.replace('-', '_')}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: 1.0\n")
    (info / "top_level.txt").write_text(pkg + "\n")
    (info / "direct_url.json").write_text(
        json.dumps(
            {"url": project.resolve().as_uri(), "dir_info": {"editable": editable}}
            if url is None
            else url
        )
    )
    importlib.invalidate_caches()


@pytest.mark.parametrize("mapping", [_HATCH_MAPPING, _SETUPTOOLS_MAPPING])
def test_an_editable_install_finds_the_projects_top_level_skills(
    fake_dist, tmp_path, monkeypatch, mapping
):
    project = tmp_path / "my project"  # a space: the URL is percent-encoded
    _make_editable_dist(fake_dist, project, mapping=mapping)
    monkeypatch.syspath_prepend(str(project))  # what the editable .pth does
    found = find_package_skills("edit-dist")
    assert found == (project / "skills").resolve()
    proj = tmp_path / "consumer"
    (proj / ".git").mkdir(parents=True)
    result = install_from_package("edit-dist", agent_targets=["claude-code"], project_dir=proj)
    assert (result["beta"]["claude-code"] / "SKILL.md").is_file()
    sys.modules.pop("edit_pkg", None)


def test_a_non_editable_install_does_not_read_the_source_folder(fake_dist, tmp_path, monkeypatch):
    project = tmp_path / "src"
    _make_editable_dist(fake_dist, project, editable=False)
    monkeypatch.syspath_prepend(str(project))
    with pytest.raises(LookupError, match="ships no skills"):
        find_package_skills("edit-dist")
    sys.modules.pop("edit_pkg", None)


def test_an_editable_install_whose_wheel_does_not_ship_skills_is_not_read(fake_dist, tmp_path, monkeypatch):
    project = tmp_path / "dev-only"
    _make_editable_dist(fake_dist, project, mapping=None)  # skills/ never reaches the wheel
    monkeypatch.syspath_prepend(str(project))
    with pytest.raises(LookupError, match="ships no skills"):
        find_package_skills("edit-dist")
    sys.modules.pop("edit_pkg", None)


@pytest.mark.parametrize(
    "direct_url", [{"dir_info": "yes", "url": "file:///x"}, {"dir_info": {"editable": True}, "url": 5}, [1]]
)
def test_a_malformed_direct_url_reads_as_no_skills(fake_dist, tmp_path, monkeypatch, direct_url):
    project = tmp_path / "odd"
    _make_editable_dist(fake_dist, project, url=direct_url)
    monkeypatch.syspath_prepend(str(project))
    with pytest.raises(LookupError, match="ships no skills"):
        find_package_skills("edit-dist")
    sys.modules.pop("edit_pkg", None)
