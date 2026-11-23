"""The ``wheel-included-skills`` placement method: a tested build recipe.

The real skill files live once, in the repository's top-level ``skills/<name>/`` (where
``gh skill`` and the wider ecosystem look), and the build copies that folder into the
wheel as ``<pkg>/_skills/`` so a ``pip install`` carries them too (addaix/skill#8, #31).
The copy exists only in the built wheel, never in the repository, so ``gh skill`` sees
each skill once; it is a copy, never a symlink, because whether ``gh skill`` follows a
symlink is unverified.

- :func:`wheel_skills_snippet` gives the ``pyproject.toml`` lines (hatchling).
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

import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

__all__ = [
    "WHEEL_SKILLS_DIR",
    "WheelSkillsReport",
    "wheel_skills_snippet",
    "check_wheel_skills",
]

#: The folder, inside the import package, that the build copies ``skills/`` to.
WHEEL_SKILLS_DIR = "_skills"

_SKILL_MARKER = "SKILL.md"


def wheel_skills_snippet(
    package: str, *, source: str = "skills", target_dir: str = WHEEL_SKILLS_DIR
) -> str:
    """The ``pyproject.toml`` lines that copy ``source`` into the wheel (hatchling).

    hatchling's ``force-include`` copies files, following no link, so the wheel holds
    real files; nothing is written to the repository. setuptools has no equivalent that
    reaches outside the package: a setuptools package that wants skills in its wheel
    uses ``package-data-skills`` (``<pkg>/data/skills/``) instead.
    """
    return (
        "[tool.hatch.build.targets.wheel.force-include]\n"
        f'"{source}" = "{package}/{target_dir}"'
    )


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


def _repo_skill_files(repo_root: Path, source: str) -> dict[str, dict[str, bytes]]:
    """``{skill name: {relative posix path: bytes}}`` for every ``<source>/<name>/``
    with a ``SKILL.md`` (files only; caches skipped)."""
    out: dict[str, dict[str, bytes]] = {}
    root = repo_root / source
    if not root.is_dir():
        return out
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (skill_dir / _SKILL_MARKER).is_file():
            continue
        files = {}
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                files[f.relative_to(skill_dir).as_posix()] = f.read_bytes()
        out[skill_dir.name] = files
    return out


def _repo_skill_md_locations(repo_root: Path) -> dict[str, list[str]]:
    """``{skill name: [repo-relative dirs holding its real SKILL.md]}``, outside hidden
    and build folders, not following symlinks (``.claude/skills`` links are bridges)."""
    skip = {".git", "build", "dist", "node_modules", ".venv", "venv", "__pycache__"}
    found: dict[str, list[str]] = {}

    def walk(d: Path) -> None:
        for child in sorted(d.iterdir()):
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name.startswith(".") or child.name in skip:
                    continue
                if (child / _SKILL_MARKER).is_file() and not (
                    child / _SKILL_MARKER
                ).is_symlink():
                    found.setdefault(child.name, []).append(
                        child.relative_to(repo_root).as_posix()
                    )
                walk(child)

    walk(repo_root)
    return found


def _audience(skill_md: bytes) -> str | None:
    """The ``metadata.audience`` (or top-level ``audience``) of a SKILL.md, if any."""
    text = skill_md.decode("utf-8", errors="replace")
    if not text.startswith("---"):
        return None
    front = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    for line in front.splitlines():
        key, _, value = line.strip().partition(":")
        if key == "audience":
            return value.strip().strip("'\"") or None
    return None


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
