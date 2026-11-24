"""install_bundled: idempotent, conflict-safe linking of a package's skills and agents."""

import os

import pytest

from skill import install_bundled


@pytest.fixture
def data(tmp_path):
    (tmp_path / "data/skills/alpha").mkdir(parents=True)
    (tmp_path / "data/skills/alpha/SKILL.md").write_text("alpha")
    (tmp_path / "data/agents").mkdir(parents=True)
    (tmp_path / "data/agents/scout.md").write_text("scout")
    return tmp_path / "data"


def actions(rows):
    return {r["name"]: r["action"] for r in rows}


def test_install_then_ok(data, tmp_path):
    home = tmp_path / "home"
    assert actions(install_bundled(data, homes=[home])) == {"alpha": "install", "scout": "install"}
    assert actions(install_bundled(data, homes=[home])) == {"alpha": "ok", "scout": "ok"}
    assert (home / "skills/alpha/SKILL.md").read_text() == "alpha"
    assert (home / "agents/scout.md").read_text() == "scout"


def test_foreign_file_is_a_conflict_and_left_alone(data, tmp_path):
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills/alpha").mkdir()
    (home / "skills/alpha/mine.txt").write_text("keep")
    assert actions(install_bundled(data, homes=[home]))["alpha"] == "conflict"
    assert (home / "skills/alpha/mine.txt").read_text() == "keep"


def test_force_replaces_a_conflict(data, tmp_path):
    home = tmp_path / "home"
    (home / "skills/alpha").mkdir(parents=True)
    assert actions(install_bundled(data, homes=[home], force=True))["alpha"] == "install"
    assert (home / "skills/alpha/SKILL.md").read_text() == "alpha"


def test_dry_run_changes_nothing(data, tmp_path):
    home = tmp_path / "home"
    rows = install_bundled(data, homes=[home], dry_run=True)
    assert {r["action"] for r in rows} == {"install"}
    assert not home.exists()


def test_several_homes_and_copy_fallback(data, tmp_path, monkeypatch):
    def no_symlinks(*a, **k):
        raise OSError("no symlinks here")

    monkeypatch.setattr(os, "symlink", no_symlinks)
    homes = [tmp_path / "h1", tmp_path / "h2"]
    rows = install_bundled(data, homes=homes)
    assert {r["method"] for r in rows} == {"copy"} and len(rows) == 4
    assert {r["action"] for r in install_bundled(data, homes=homes)} == {"ok"}


def test_relative_source_dir_links_to_the_real_source(data, tmp_path, monkeypatch):
    """A relative source_dir must not leave a dangling, relative link (#43)."""
    home = tmp_path / "home"
    monkeypatch.chdir(data.parent)
    assert actions(install_bundled("data", homes=[home])) == {"alpha": "install", "scout": "install"}
    assert (home / "skills/alpha/SKILL.md").read_text() == "alpha"
    assert os.path.isabs(os.readlink(home / "skills/alpha"))
    assert actions(install_bundled("data", homes=[home])) == {"alpha": "ok", "scout": "ok"}


def test_a_dangling_link_at_the_name_is_replaced_without_force(data, tmp_path):
    """A link left by a removed environment holds nothing; it is not a conflict (#43)."""
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "agents").mkdir(parents=True)
    (home / "skills/alpha").symlink_to(tmp_path / "gone-venv/data/skills/alpha")
    (home / "agents/scout.md").symlink_to(tmp_path / "gone-venv/data/agents/scout.md")
    assert actions(install_bundled(data, homes=[home])) == {"alpha": "install", "scout": "install"}
    assert (home / "skills/alpha/SKILL.md").read_text() == "alpha"
    assert (home / "agents/scout.md").read_text() == "scout"


def test_a_dangling_link_is_reported_as_install_under_dry_run(data, tmp_path):
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills/alpha").symlink_to(tmp_path / "gone")
    rows = install_bundled(data, homes=[home], dry_run=True)
    assert actions(rows)["alpha"] == "install"
    assert (home / "skills/alpha").is_symlink()  # untouched
