"""Link a package's bundled skills and agents into one or more Claude homes.

Packages that ship ``<pkg>/data/skills/<name>/`` (and ``<pkg>/data/agents/<name>.md``)
all need the same ~25 lines: link each into ``~/.claude/skills`` (or several Claude
homes, e.g. a second account's ``CLAUDE_CONFIG_DIR``), idempotently, reporting ``ok`` /
``install`` / ``conflict`` per asset and never overwriting something that is not ours
without ``force``. This is that mechanism, once.

**Pure standard library and self-contained on purpose**: a package that keeps zero
runtime dependencies can copy this file instead of depending on ``skill``.

>>> import tempfile, pathlib
>>> root = pathlib.Path(tempfile.mkdtemp())
>>> (root / "data/skills/demo").mkdir(parents=True)
>>> _ = (root / "data/skills/demo/SKILL.md").write_text("---\\nname: demo\\n---\\n")
>>> home = root / "home"
>>> [r["action"] for r in install_bundled(root / "data", homes=[home])]
['install']
>>> [r["action"] for r in install_bundled(root / "data", homes=[home])]
['ok']
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

__all__ = ["claude_homes", "install_bundled"]

SKILLS_SUBDIR = "skills"
AGENTS_SUBDIR = "agents"


def claude_homes() -> list[Path]:
    """Every Claude Code home on this machine: ``~/.claude`` and ``~/.claude-*``.

    A home counts when it has a ``skills`` folder. ``CLAUDE_CONFIG_DIR``, when set, is
    included even if it has none yet.

    >>> all(isinstance(h, Path) for h in claude_homes())
    True
    """
    found = [Path("~/.claude").expanduser(), *sorted(Path.home().glob(".claude-*"))]
    homes = [h for h in found if (h / SKILLS_SUBDIR).is_dir()]
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured and Path(configured).expanduser() not in homes:
        homes.append(Path(configured).expanduser())
    return homes


def _assets(source_dir: Path) -> list[tuple[Path, str]]:
    """``(source, path relative to a home)`` for every bundled skill dir and agent file."""
    skills, agents = source_dir / SKILLS_SUBDIR, source_dir / AGENTS_SUBDIR
    found = [
        (p, f"{SKILLS_SUBDIR}/{p.name}")
        for p in sorted(skills.iterdir() if skills.is_dir() else ())
        if p.is_dir()
    ]
    found += [(p, f"{AGENTS_SUBDIR}/{p.name}") for p in sorted(agents.glob("*.md"))]
    return found


def _is_ours(dest: Path, src: Path) -> bool:
    """``dest`` already is a link to ``src`` (or a faithful copy of it)."""
    if dest.is_symlink():
        return (
            dest.resolve() == src.resolve()
        )  # (os.readlink can carry a \\?\ prefix on Windows)
    if dest.is_file() and src.is_file():
        return dest.read_bytes() == src.read_bytes()
    if dest.is_dir() and src.is_dir() and not dest.is_symlink():
        return _tree(dest) == _tree(src)
    return False


def _tree(root: Path) -> dict[str, bytes]:
    """``{relative path: bytes}`` of every file under ``root``."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _remove(dest: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    else:
        shutil.rmtree(dest)


def _place(src: Path, dest: Path) -> str:
    """Link ``src`` at ``dest``; copy where symlinks are unavailable. Returns the method."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(src, dest, target_is_directory=src.is_dir())
        return "symlink"
    except (OSError, NotImplementedError):
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        return "copy"


def install_bundled(
    source_dir: str | Path,
    *,
    homes: Iterable[str | Path] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    """Install a package's bundled skills and agents into each Claude home.

    ``source_dir`` holds ``skills/<name>/`` directories and/or ``agents/<name>.md`` files
    (a package's ``data`` folder). ``homes`` defaults to :func:`claude_homes`. Returns one
    row per (home, asset): ``{"home", "name", "action"}`` with ``action`` one of

    - ``"ok"``: already installed (a link to the source, or an identical copy);
    - ``"install"``: installed now (or would be, under ``dry_run``); a ``"method"`` key
      says ``symlink`` or ``copy``;
    - ``"conflict"``: something else is at that name; left alone unless ``force``.

    >>> install_bundled("/no/such/folder", homes=["/tmp/never-used"])
    []
    """
    source_dir = Path(source_dir)
    homes = [
        Path(h).expanduser() for h in (homes if homes is not None else claude_homes())
    ]
    rows: list[dict] = []
    for home in homes:
        for src, rel in _assets(source_dir):
            dest = home / rel
            exists = dest.exists() or dest.is_symlink()
            if _is_ours(dest, src):
                action = "ok"
            else:
                action = "conflict" if exists and not force else "install"
            row = {
                "home": str(home),
                "name": src.stem if src.is_file() else src.name,
                "action": action,
            }
            if action == "install" and not dry_run:
                if exists:
                    _remove(dest)
                row["method"] = _place(src, dest)
            rows.append(row)
    return rows
