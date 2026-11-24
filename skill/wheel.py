"""The ``wheel-included-skills`` placement method: a tested build recipe.

The real skill files live once, in the repository's top-level ``skills/<name>/`` (where
``gh skill`` and the wider ecosystem look), and the build copies that folder into the
wheel as ``<pkg>/_skills/`` so a ``pip install`` carries them too (addaix/skill#8, #31).
The copy exists only in the built wheel, never in the repository, so ``gh skill`` sees
each skill once; it is a copy, never a symlink, because whether ``gh skill`` follows a
symlink is unverified.

- :func:`wheel_skills_config` gives the ``pyproject.toml`` settings as a dict (hatchling
  or setuptools), to merge into an existing file; :func:`wheel_skills_snippet` the same
  as TOML text, for a file that has no such table yet.
- :func:`check_wheel_skills` checks a built wheel against the repository: every
  ``skills/<name>/`` file is in the wheel under ``<pkg>/_skills/<name>/``, byte for byte,
  every ``SKILL.md`` exactly once, and the repository holds each skill once.
- ``skill install-from-package <distribution>`` then finds ``<pkg>/_skills`` in the
  installed package (:data:`skill.install.PACKAGE_SKILLS_SUBPATHS`).

>>> print(wheel_skills_snippet("my_pkg"))
[tool.hatch.build.targets.wheel.force-include]
"skills" = "my_pkg/_skills"
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from skill.util import INSTALL_MARKER

__all__ = [
    "WHEEL_SKILLS_DIR",
    "WheelSkillsReport",
    "wheel_skills_config",
    "wheel_skills_snippet",
    "check_wheel_skills",
]

#: The folder, inside the import package, that the build copies ``skills/`` to.
WHEEL_SKILLS_DIR = "_skills"

_SKILL_MARKER = "SKILL.md"


def wheel_skills_config(
    package: str,
    *,
    backend: str = "hatch",
    source: str = "skills",
    target_dir: str = WHEEL_SKILLS_DIR,
) -> dict:
    """The ``pyproject.toml`` settings that put ``source`` into the wheel as
    ``<package>/<target_dir>``, as a nested dict to merge into the file (with tomlkit,
    say) rather than append to it.

    - ``hatch``: ``force-include``. hatchling copies the files, following links, and
      skips its built-in excludes (``.DS_Store``, ``.pytest_cache``...).
    - ``setuptools``: ``<package>.<target_dir>`` declared as a package whose directory is
      ``source``, with all its files as package data.

    The build must see ``source``: a wheel built from an sdist (the default of
    ``python -m build``) needs it in the sdist too.

    >>> wheel_skills_config("p")
    {'tool': {'hatch': {'build': {'targets': {'wheel': {'force-include': {'skills': 'p/_skills'}}}}}}}
    """
    if backend == "hatch":
        return {
            "tool": {
                "hatch": {
                    "build": {
                        "targets": {
                            "wheel": {
                                "force-include": {source: f"{package}/{target_dir}"}
                            }
                        }
                    }
                }
            }
        }
    if backend == "setuptools":
        sub = f"{package}.{target_dir}"
        return {
            "tool": {
                "setuptools": {
                    "packages": [package, sub],
                    "package-dir": {sub: source},
                    "package-data": {sub: ["**/*"]},
                }
            }
        }
    raise ValueError(f"backend must be 'hatch' or 'setuptools', not {backend!r}")


def wheel_skills_snippet(
    package: str,
    *,
    backend: str = "hatch",
    source: str = "skills",
    target_dir: str = WHEEL_SKILLS_DIR,
) -> str:
    """:func:`wheel_skills_config` as ``pyproject.toml`` text, for a file that has none
    of these tables yet (merge the dict instead when it has).

    >>> print(wheel_skills_snippet("p", backend="setuptools"))
    [tool.setuptools]
    packages = ["p", "p._skills"]
    package-dir = { "p._skills" = "skills" }
    package-data = { "p._skills" = ["**/*"] }
    """
    if backend == "hatch":
        return (
            "[tool.hatch.build.targets.wheel.force-include]\n"
            f'"{source}" = "{package}/{target_dir}"'
        )
    if backend == "setuptools":
        sub = f"{package}.{target_dir}"
        return (
            "[tool.setuptools]\n"
            f'packages = ["{package}", "{sub}"]\n'
            f'package-dir = {{ "{sub}" = "{source}" }}\n'
            f'package-data = {{ "{sub}" = ["**/*"] }}'
        )
    raise ValueError(f"backend must be 'hatch' or 'setuptools', not {backend!r}")


@dataclass
class WheelSkillsReport:
    """What :func:`check_wheel_skills` found. ``ok`` when there are no ``problems``;
    ``warnings`` (such as a developer skill shipped to users) do not fail it."""

    skills: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def __str__(self) -> str:
        head = (
            f"ok: {len(self.skills)} skill(s) in the wheel"
            if self.ok
            else f"FAILED: {len(self.problems)} problem(s)"
        )
        lines = [head]
        lines += [f"  problem: {p}" for p in self.problems]
        lines += [f"  warning: {w}" for w in self.warnings]
        return "\n".join(lines)


#: What a build leaves out of a copied folder however it is configured (hatchling's
#: built-in excludes), so the check does not expect them in the wheel.
#: ``skill.install`` compares and fingerprints copies with the same lists, plus its marker.
NEVER_SHIPPED_FILES = frozenset({".DS_Store", "Thumbs.db", INSTALL_MARKER})
NEVER_SHIPPED_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        ".tox",
        ".nox",
        ".hg",
    }
)
_NEVER_SHIPPED_FILES, _NEVER_SHIPPED_DIRS = NEVER_SHIPPED_FILES, NEVER_SHIPPED_DIRS


def _tracked(repo_root: Path, source: str) -> set[str] | None:
    """The repository-relative paths git tracks under ``source``, or ``None`` when
    ``repo_root`` is not a git working tree. A wheel built through the sdist (the default
    of ``python -m build``) holds tracked files only, so these are what to expect."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--", source],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {p for p in out.decode("utf-8").split("\0") if p}


def _walk_files(directory: Path):
    """Every file under ``directory``, following linked folders (as the build does)."""
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in _NEVER_SHIPPED_DIRS)
        for name in sorted(filenames):
            if name not in _NEVER_SHIPPED_FILES and not name.endswith((".pyc", ".pyo")):
                yield Path(dirpath, name)


def _repo_skill_files(repo_root: Path, source: str) -> dict[str, dict[str, bytes]]:
    """``{skill name: {relative posix path: bytes}}`` for every ``<source>/<name>/``
    with a ``SKILL.md``: its tracked files when the repository is a git working tree
    (a tracked linked folder counts with its contents), else every file a build copies."""
    out: dict[str, dict[str, bytes]] = {}
    root = repo_root / source
    if not root.is_dir():
        return out
    tracked = _tracked(repo_root, source)
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (skill_dir / _SKILL_MARKER).is_file():
            continue
        files = {}
        for f in _walk_files(skill_dir):
            rel_repo = f.relative_to(repo_root).as_posix()
            if tracked is not None and not _is_tracked(rel_repo, tracked):
                continue
            files[f.relative_to(skill_dir).as_posix()] = f.read_bytes()
        out[skill_dir.name] = files
    return out


def _is_tracked(path: str, tracked: set[str]) -> bool:
    """``path`` is tracked, or lies under a tracked link to a folder."""
    if path in tracked:
        return True
    parts = path.split("/")
    return any("/".join(parts[:i]) in tracked for i in range(1, len(parts)))


def _repo_skill_md_locations(repo_root: Path) -> dict[str, list[str]]:
    """``{skill name: [repo-relative dirs]}`` for every real ``skills/<name>/SKILL.md``
    in the repository: the places ``gh skill`` discovers (a ``skills`` folder at any
    non-hidden depth). Links are not followed (``.claude/skills`` links are bridges),
    and environments and build output are skipped."""
    skip = {
        "build",
        "dist",
        "node_modules",
        "venv",
        "env",
        "site-packages",
        "__pycache__",
    }
    found: dict[str, list[str]] = {}
    for dirpath, dirnames, _ in os.walk(repo_root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in skip
            and not (here / d / "pyvenv.cfg").exists()
            and not (here / d).is_symlink()
        )
        if here.name != "skills" or here == repo_root:
            continue
        for d in dirnames:
            md = here / d / _SKILL_MARKER
            if md.is_file() and not md.is_symlink():
                found.setdefault(d, []).append(
                    (here / d).relative_to(repo_root).as_posix()
                )
    return found


def _audience(skill_md: bytes) -> str | None:
    """The ``metadata.audience`` (or top-level ``audience``) of a SKILL.md, if any."""
    import yaml

    text = skill_md.decode("utf-8", errors="replace")
    from skill.base import split_frontmatter

    parts = split_frontmatter(text)
    if parts is None:
        return None
    try:
        front = yaml.safe_load(parts[0]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict):
        return None
    meta = front.get("metadata")
    value = meta.get("audience") if isinstance(meta, dict) else None
    return str(value or front.get("audience") or "") or None


def check_wheel_skills(
    wheel: str | Path,
    repo_root: str | Path = ".",
    *,
    package: str | None = None,
    source: str = "skills",
    target_dir: str = WHEEL_SKILLS_DIR,
) -> WheelSkillsReport:
    """Check a built wheel against the repository it was built from.

    Problems (``report.ok`` is false):

    - a repository skill (``<source>/<name>/``) missing from the wheel, or one of its
      files missing or different in ``<package>/<target_dir>/<name>/``;
    - a skill whose ``SKILL.md`` the wheel holds more than once (anywhere), or a
      skill in the wheel's ``<target_dir>`` that the repository does not have;
    - a skill whose real ``SKILL.md`` the repository holds in more than one
      non-hidden place (``gh skill`` reports duplicates), or a committed copy of the
      in-wheel folder (``<package>/<target_dir>``) in the repository.

    Warnings: a skill whose ``audience`` is ``developer`` ships to users.

    ``package`` defaults to the one import package that has a ``<target_dir>`` in the
    wheel.
    """
    wheel, repo_root = Path(wheel), Path(repo_root)
    report = WheelSkillsReport()
    repo_skills = _repo_skill_files(repo_root, source)
    if not repo_skills:
        report.problems.append(f"the repository has no skills under {source}/")
        return report

    with zipfile.ZipFile(wheel) as zf:
        members = {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}
    paths = [PurePosixPath(n) for n in members]

    if package is None:
        candidates = sorted(
            {p.parts[0] for p in paths if len(p.parts) > 2 and p.parts[1] == target_dir}
        )
        if len(candidates) != 1:
            report.problems.append(
                f"no single package holds {target_dir}/ in the wheel "
                f"(found: {candidates or 'none'}); pass package="
            )
            return report
        package = candidates[0]
    prefix = PurePosixPath(package, target_dir)

    # Every SKILL.md in the wheel, by skill name.
    md_by_name: dict[str, list[str]] = {}
    for p in paths:
        if p.name == _SKILL_MARKER and len(p.parts) >= 2:
            md_by_name.setdefault(p.parent.name, []).append(str(p))

    for name, files in repo_skills.items():
        report.skills.append(name)
        for rel, data in files.items():
            member = str(prefix / name / rel)
            if member not in members:
                report.problems.append(f"{name}: {rel} is not in the wheel ({member})")
            elif members[member] != data:
                report.problems.append(f"{name}: {rel} differs from the repository")
        copies = md_by_name.get(name, [])
        if len(copies) > 1:
            report.problems.append(
                f"{name}: the wheel holds SKILL.md {len(copies)} times: {', '.join(sorted(copies))}"
            )
        if _audience(files.get(_SKILL_MARKER, b"")) == "developer":
            report.warnings.append(
                f"{name}: a developer skill (audience: developer) ships to users"
            )

    in_wheel = {
        p.parts[len(prefix.parts)]
        for p in paths
        if p.parts[: len(prefix.parts)] == prefix.parts
        and len(p.parts) > len(prefix.parts) + 1
    }
    for extra in sorted(in_wheel - set(repo_skills)):
        report.problems.append(
            f"{extra}: in the wheel's {prefix}/ but not in the repository's {source}/"
        )

    for name, places in _repo_skill_md_locations(repo_root).items():
        if name in repo_skills and len(places) > 1:
            report.problems.append(
                f"{name}: the repository holds it in {len(places)} places: {', '.join(places)}"
            )
    if (repo_root / package / target_dir).exists():
        report.problems.append(
            f"{package}/{target_dir} exists in the repository: it must exist only in "
            "the wheel (the build makes it), or gh skill sees every skill twice"
        )
    report.skills.sort()
    return report
