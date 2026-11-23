"""Installation logic: symlink/copy skills into agent target directories.

Also provides :func:`install_from_github`, a thin wrapper over the ``gh skill``
CLI that any package can call programmatically to install skills it ships on
GitHub into the user's agent host.
"""

import os
import shutil
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

from skill.base import Skill
from skill.stores import LocalSkillStore
from skill.translate import translators
from skill.util import find_project_root
from skill.config import load_config
from skill.registry import Registry
from skill.create import _validate_skill, check_dependencies


# ---------------------------------------------------------------------------
# Agent target registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentTarget:
    """Describes where an agent expects skills to be installed.

    Path templates support ``{home}``, ``{project}``, and ``{name}`` placeholders.

    >>> str(AgentTarget(name='test', project_path='{project}/.test/{name}').format_project_path('/proj', 'my-skill'))
    '/proj/.test/my-skill'
    """

    name: str
    global_path: str | None = None
    project_path: str | None = None
    format: str = "skill.md"
    needs_translation: bool = False
    # True: the translation is one ``## name`` section of a shared file (Copilot, Gemini)
    appends: bool = False
    # The host this target installs for, when it differs from ``name`` (the rules-file
    # target ``cursor-rules`` is for host ``cursor``). Lets a caller find every way a
    # skill can be installed for one host.
    host: str | None = None

    @property
    def host_name(self) -> str:
        """The host this target serves: ``host`` when set, else ``name``.

        >>> AgentTarget(name='cursor-rules', host='cursor').host_name
        'cursor'
        >>> AgentTarget(name='codex').host_name
        'codex'
        """
        return self.host or self.name

    def format_global_path(self, name: str) -> Path | None:
        if self.global_path is None:
            return None
        return Path(self.global_path.format(home=Path.home(), name=name))

    def format_project_path(self, project: str | Path, name: str) -> Path | None:
        if self.project_path is None:
            return None
        return Path(self.project_path.format(project=project, name=name))


agent_targets: Registry[AgentTarget] = Registry("agent_targets")
"""Registry of agent targets (e.g., claude-code, cursor, copilot)."""

agent_targets.register(
    "claude-code",
    AgentTarget(
        name="claude-code",
        global_path="{home}/.claude/skills/{name}",
        project_path="{project}/.claude/skills/{name}",
        format="skill.md",
    ),
)
# Codex reads SKILL.md folders natively (``.agents/skills`` from cwd up to the repo
# root, and ``~/.agents/skills``) and follows symlinks: a lossless target like
# claude-code. https://developers.openai.com/codex/skills
agent_targets.register(
    "codex",
    AgentTarget(
        name="codex",
        global_path="{home}/.agents/skills/{name}",
        project_path="{project}/.agents/skills/{name}",
        format="skill.md",
    ),
)
# Hosts that now read SKILL.md folders natively (per each host's own skills docs, as
# tabulated by `npx skills` 1.9.0: https://github.com/vercel-labs/skills/blob/main/docs/agents.md).
# Cursor, Copilot, Gemini CLI and Cline share the cross-host ``.agents/skills`` project
# folder with Codex, so one install serves all of them; their user-level folders differ.
_NATIVE_HOSTS = {
    # name: (global_path, project_path)
    "cursor": ("{home}/.cursor/skills/{name}", "{project}/.agents/skills/{name}"),
    "copilot": ("{home}/.copilot/skills/{name}", "{project}/.agents/skills/{name}"),
    "gemini": ("{home}/.gemini/skills/{name}", "{project}/.agents/skills/{name}"),
    "cline": ("{home}/.agents/skills/{name}", "{project}/.agents/skills/{name}"),
    "windsurf": (
        "{home}/.codeium/windsurf/skills/{name}",
        "{project}/.windsurf/skills/{name}",
    ),
}
for _name, (_global, _project) in _NATIVE_HOSTS.items():
    agent_targets.register(
        _name,
        AgentTarget(
            name=_name, global_path=_global, project_path=_project, format="skill.md"
        ),
    )

# The older rules-file translations, kept reachable under explicit names for anyone
# who wants a rules file (or to uninstall one an earlier version wrote). They are lossy:
# ``skill.translate`` warns about the fields it drops.
agent_targets.register(
    "cursor-rules",
    AgentTarget(
        name="cursor-rules",
        host="cursor",
        project_path="{project}/.cursor/rules/{name}.mdc",
        format="mdc",
        needs_translation=True,
    ),
)
agent_targets.register(
    "copilot-instructions",
    AgentTarget(
        name="copilot-instructions",
        host="copilot",
        project_path="{project}/.github/copilot-instructions.md",
        format="copilot_md",
        needs_translation=True,
        appends=True,
    ),
)
agent_targets.register(
    "windsurf-rules",
    AgentTarget(
        name="windsurf-rules",
        host="windsurf",
        project_path="{project}/.windsurf/rules/{name}.md",
        format="windsurf_md",
        needs_translation=True,
    ),
)
agent_targets.register(
    "cline-rules",
    AgentTarget(
        name="cline-rules",
        host="cline",
        project_path="{project}/.clinerules/{name}.md",
        format="clinerules_md",
        needs_translation=True,
    ),
)
agent_targets.register(
    "gemini-md",
    AgentTarget(
        name="gemini-md",
        host="gemini",
        project_path="{project}/GEMINI.md",
        format="gemini_md",
        needs_translation=True,
        appends=True,
    ),
)

# Keep AGENT_TARGETS as a backward-compatible alias
AGENT_TARGETS = agent_targets


# ---------------------------------------------------------------------------
# Install skills published on GitHub via the ``gh skill`` CLI
# ---------------------------------------------------------------------------

_GH_INSTALL_URL = "https://cli.github.com/"
_GH_SKILL_DOCS_URL = "https://cli.github.com/manual/gh_skill"


def install_from_github(
    repo: str,
    names,
    *,
    agent: str = "claude-code",
    preview: bool = False,
    pin: str | None = None,
    scope: str | None = None,
) -> list[dict]:
    """Install (or preview) skills published on GitHub via the ``gh skill`` CLI.

    Shells out to ``gh skill install <repo> <name> --agent <agent>`` for each
    requested skill name (or ``gh skill preview <repo> <name>`` when
    ``preview=True``). This is the shared utility packages call programmatically
    to let users grab the skills they ship on GitHub.

    Parameters
    ----------
    repo : str
        The GitHub ``owner/repo`` that publishes the skills (e.g. ``'thorwhalen/skill'``).
    names : str | list[str]
        A single skill name or a list of skill names to install.
    agent : str
        The agent host to install into (default ``'claude-code'``). Ignored for previews.
    preview : bool
        If True, run ``gh skill preview`` instead of ``gh skill install``.
    pin : str | None
        A tag or commit SHA to install, passed as ``gh skill install --pin``, so the
        install is reproducible and ``gh skill update`` leaves it alone. ``None``
        (default) installs the latest. Ignored for previews.
    scope : str | None
        ``'project'`` or ``'user'`` (``'global'`` is accepted as ``'user'``), passed as
        ``gh skill install --scope``. ``None`` (default) leaves it to ``gh``. Ignored
        for previews.

    Returns
    -------
    list[dict]
        One result per name: ``{'name', 'repo', 'argv', 'returncode', 'stdout', 'stderr'}``.

    Raises
    ------
    RuntimeError
        If the GitHub CLI (``gh``) is not installed, or if the ``gh skill``
        extension/command is unavailable — with a message pointing to the
        relevant install docs.

    Example
    -------
    >>> install_from_github('thorwhalen/skill', 'skill-package-setup')  # doctest: +SKIP
    [{'name': 'skill-package-setup', 'repo': 'thorwhalen/skill', ...}]
    """
    if isinstance(names, str):
        names = [names]
    if scope == "global":
        scope = "user"
    if scope not in (None, "project", "user"):
        raise ValueError(f"scope must be 'project' or 'user', got {scope!r}")
    if pin is not None and (inline := [n for n in names if "@" in n]):
        raise ValueError(
            f"pin={pin!r} cannot be combined with an inline @version in {inline}: "
            "use one or the other"
        )

    if shutil.which("gh") is None:
        raise RuntimeError(
            "The GitHub CLI (`gh`) is required to install skills from GitHub, "
            f"but it was not found on your PATH. Install it from {_GH_INSTALL_URL}"
        )

    verb = "preview" if preview else "install"
    results = []
    for name in names:
        argv = ["gh", "skill", verb, repo, name]
        if not preview:
            argv += ["--agent", agent]
            if pin is not None:
                argv += ["--pin", pin]
            if scope is not None:
                argv += ["--scope", scope]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "The GitHub CLI (`gh`) is required to install skills from GitHub, "
                f"but it could not be executed. Install it from {_GH_INSTALL_URL}"
            ) from e

        if proc.returncode != 0:
            stderr = proc.stderr or ""
            lower = stderr.lower()
            if "unknown command" in lower or "unknown subcommand" in lower:
                raise RuntimeError(
                    "The `gh skill` command is unavailable (you may need a newer "
                    "GitHub CLI or the skill extension). See "
                    f"{_GH_SKILL_DOCS_URL}\n\n{stderr.strip()}"
                )
            raise RuntimeError(
                f"`{' '.join(argv)}` failed (exit {proc.returncode}):\n{stderr.strip()}"
            )

        results.append(
            {
                "name": name,
                "repo": repo,
                "argv": argv,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Link/copy helpers
# ---------------------------------------------------------------------------


def _check_existing(target: Path) -> str:
    """Classify what currently exists at ``target``.

    Returns one of: ``'none'``, ``'our_symlink'``, ``'foreign_symlink'``,
    ``'directory'``, ``'file'``.

    >>> _check_existing(Path('/nonexistent/path/abc'))
    'none'
    """
    if not target.exists() and not target.is_symlink():
        return "none"
    if target.is_symlink():
        # Check if it points into our skills dir
        link_target = str(target.resolve())
        from skill.config import skills_dir

        if str(skills_dir()) in link_target:
            return "our_symlink"
        return "foreign_symlink"
    if target.is_dir():
        return "directory"
    return "file"


def _is_install_of(dest: Path, source: Path) -> bool:
    """True when ``dest`` is a link to ``source`` or a copy of it (same SKILL.md).

    Several hosts share one folder (``.agents/skills``), and a skill installed for one
    of them in an earlier call must be recognised, not refused or deleted as foreign.

    >>> _is_install_of(Path('/nonexistent/a'), Path('/nonexistent/b'))
    False
    """
    try:
        if dest.is_symlink():
            return dest.resolve() == source.resolve()
        if dest.is_dir():
            ours, theirs = dest / "SKILL.md", source / "SKILL.md"
            return (
                ours.is_file()
                and theirs.is_file()
                and ours.read_bytes() == theirs.read_bytes()
            )
    except OSError:
        return False
    return False


def _legacy_artifacts(host: str, project_dir, skill_name: str) -> list[Path]:
    """Rules-file installs an earlier version wrote for ``host`` that still exist."""
    found = []
    for t in AGENT_TARGETS.values():
        if not (
            t.needs_translation and t.host_name == host and project_dir is not None
        ):
            continue
        dest = t.format_project_path(project_dir, skill_name)
        if dest is None or not dest.is_file():
            continue
        if not t.appends or f"<!-- skill:{skill_name} -->" in dest.read_text(
            errors="replace"
        ):
            found.append(dest)
    return found


def _create_link(
    source: Path,
    target: Path,
    *,
    copy: bool = False,
    force: bool = False,
) -> Path:
    """Create a symlink (or copy) from ``target`` pointing to ``source``.

    On Windows, uses a directory junction instead of symlink.
    """
    existing = _check_existing(target)
    if existing != "none" and not force and _is_install_of(target, source):
        return target  # this skill is already there (another host sharing the folder)
    if existing == "our_symlink":
        # Already linked by us — update if source changed
        target.unlink()
    elif existing != "none":
        if not force:
            raise FileExistsError(
                f"Target already exists ({existing}): {target}. "
                f"Use force=True to overwrite."
            )
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)

    if copy:
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    else:
        os.symlink(source, target)

    return target


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------


def install(
    key: str,
    *,
    agent_targets: list[str] | None = None,
    scope: str = "project",
    copy: bool = False,
    force: bool = False,
    project_dir: Path | str | None = None,
    store: LocalSkillStore | None = None,
) -> dict[str, Path]:
    """Install a skill into one or more agent target directories.

    Returns a dict mapping agent target names to the paths where the skill
    was installed.

    Parameters
    ----------
    key : str
        Canonical skill key (e.g., ``'owner/skill-name'``).
    agent_targets : list[str] | None
        Agent targets to install into. Defaults to config's ``default_agent_targets``.
    scope : str
        ``'project'`` (default) or ``'global'``.
    copy : bool
        If True, copy instead of symlink.
    force : bool
        If True, overwrite existing files/links.
    project_dir : Path | str | None
        Project root. Auto-detected if None.
    store : LocalSkillStore | None
        Skill store to read from. Uses default if None.
    """
    if store is None:
        store = LocalSkillStore()

    if key not in store:
        raise KeyError(f"Skill {key!r} not found in local store. Fetch it first.")

    skill = store[key]

    # Warn about missing dependencies (non-blocking)
    dep_warnings = check_dependencies(skill, store=store)
    for w in dep_warnings:
        warnings.warn(w, stacklevel=2)

    config = load_config()
    targets = agent_targets or config.default_agent_targets

    if scope == "project":
        if project_dir is None:
            project_dir = find_project_root()
        if project_dir is None:
            raise RuntimeError(
                "Could not detect project root. Pass project_dir explicitly "
                "or run from within a project directory."
            )
        project_dir = Path(project_dir)

    return _install_to_targets(
        skill,
        skill.source_path or store._key_to_path(key),
        targets=targets,
        scope=scope,
        project_dir=project_dir,
        copy=copy,
        force=force,
        key=key,
    )


def _install_to_targets(
    skill: Skill,
    source_path: Path,
    *,
    targets: list[str],
    scope: str,
    project_dir: Path | None,
    copy: bool,
    force: bool,
    key: str | None = None,
) -> dict[str, Path]:
    """Install one skill (whose folder is ``source_path``) into each agent target.

    The shared core of :func:`install` (a skill in the local store) and
    :func:`install_from_package` (a skill shipped inside an installed package).
    """
    installed = {}
    for target_name in targets:
        target = AGENT_TARGETS.get(target_name)
        if target is None:
            warnings.warn(f"Unknown agent target: {target_name!r}", stacklevel=2)
            continue

        skill_name = skill.meta.name

        if scope == "project":
            dest = target.format_project_path(project_dir, skill_name)
        else:
            dest = target.format_global_path(skill_name)

        if dest is None:
            warnings.warn(
                f"Agent target {target_name!r} has no {scope} path",
                stacklevel=2,
            )
            continue

        if dest in installed.values():
            # Several hosts share one folder (``.agents/skills``): installed once
            installed[target_name] = dest
            continue

        if target.appends and dest.is_symlink():
            # Typically GEMINI.md -> AGENTS.md: appending would edit the canonical
            warnings.warn(
                f"{dest.name} is a symlink; not appending skill {skill_name!r} "
                f"to it for {target_name!r}",
                stacklevel=2,
            )
            continue

        if target.needs_translation:
            # Write translated content as a file
            translator = translators.get(target.format)
            if translator is None:
                warnings.warn(
                    f"No translator for format {target.format!r}", stacklevel=2
                )
                continue
            content = translator(skill)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if target.appends:
                # A shared instructions file: append the skill as a section
                _append_or_create(dest, content, skill_name)
            else:
                dest.write_text(content)
            installed[target_name] = dest
        else:
            # Symlink/copy the skill directory
            source = source_path
            _create_link(source, dest, copy=copy, force=force)
            installed[target_name] = dest
            if scope == "project":
                for old in _legacy_artifacts(target.host_name, project_dir, skill_name):
                    warnings.warn(
                        f"{old} is an older rules-file install of {skill_name!r} for "
                        f"{target.host_name}; the host may now load the skill twice. "
                        f"Remove it with uninstall({key or skill_name!r}, agent_targets="
                        f"[{_legacy_target_name(target.host_name)!r}])",
                        stacklevel=2,
                    )

    return installed


#: Where a distribution keeps the skills it ships, relative to its import package:
#: ``package-data-skills`` and ``wheel-included-skills`` (the latter copies the
#: repository's top-level ``skills/`` into the wheel at build time).
PACKAGE_SKILLS_SUBPATHS: tuple[tuple[str, ...], ...] = (
    ("data", "skills"),
    ("_skills",),
)


def find_package_skills(distribution: str) -> Path:
    """The folder holding the skills shipped by an installed ``distribution``.

    The import packages come from the distribution's metadata (``top_level.txt``,
    its file list, and its normalised name), never from a folder name, and each
    is located with ``importlib`` so editable installs work too.

    Raises ``LookupError`` if the distribution is not installed or ships no skills.
    """
    import importlib.util
    from importlib import metadata

    try:
        dist = metadata.distribution(distribution)
    except metadata.PackageNotFoundError:
        raise LookupError(f"Distribution {distribution!r} is not installed") from None
    names: list[str] = []
    top_level = dist.read_text("top_level.txt") or ""
    names += top_level.split()
    for f in dist.files or ():
        top = f.parts[0] if len(f.parts) > 1 else ""
        if (
            top
            and not top.endswith((".dist-info", ".egg-info"))
            and top != "__pycache__"
        ):
            names.append(top)
    names.append(distribution.replace("-", "_").lower())
    for name in dict.fromkeys(names):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        for location in (spec.submodule_search_locations or ()) if spec else ():
            for subpath in PACKAGE_SKILLS_SUBPATHS:
                candidate = Path(location, *subpath)
                if _has_skills(candidate):
                    return candidate
    raise LookupError(
        f"Distribution {distribution!r} ships no skills (looked for "
        + ", ".join("<pkg>/" + "/".join(p) for p in PACKAGE_SKILLS_SUBPATHS)
        + ")"
    )


def install_from_package(
    distribution: str,
    *,
    agent_targets: list[str] | None = None,
    scope: str = "project",
    copy: bool = False,
    force: bool = False,
    project_dir: Path | str | None = None,
) -> dict[str, dict[str, Path]]:
    """Install the skills shipped by an installed distribution into agent hosts.

    Finds them with :func:`find_package_skills`, validates each (an invalid skill is
    skipped with a warning), and links or copies it to every agent target. Returns
    ``{skill_name: {agent_target: path}}``.
    """
    source = find_package_skills(distribution)
    targets = agent_targets or load_config().default_agent_targets
    if scope == "project":
        project_dir = Path(project_dir) if project_dir else find_project_root()
        if project_dir is None:
            raise RuntimeError(
                "Could not detect project root. Pass project_dir explicitly "
                "or run from within a project directory."
            )
    installed: dict[str, dict[str, Path]] = {}
    for name, skill_dir in _iter_skill_dirs(source):
        skill = Skill.from_path(skill_dir)
        issues = _validate_skill(skill)
        if issues:
            warnings.warn(
                f"Skipping invalid skill {name!r} at {skill_dir}: " + "; ".join(issues),
                stacklevel=2,
            )
            continue
        installed[name] = _install_to_targets(
            skill,
            skill_dir,
            targets=targets,
            scope=scope,
            project_dir=project_dir,
            copy=copy,
            force=force,
        )
    return installed


def _legacy_target_name(host: str) -> str:
    """The registered rules-file target for ``host`` (for messages)."""
    return next(
        (
            n
            for n, t in AGENT_TARGETS.items()
            if t.needs_translation and t.host_name == host
        ),
        host,
    )


def _append_or_create(path: Path, content: str, skill_name: str) -> None:
    """Append content to a file, or create it. Avoids duplicates by skill name."""
    marker = f"<!-- skill:{skill_name} -->"
    end_marker = f"<!-- /skill:{skill_name} -->"

    if path.exists():
        existing = path.read_text()
        if marker in existing:
            # Replace existing section
            start = existing.index(marker)
            end = existing.index(end_marker) + len(end_marker)
            existing = existing[:start] + existing[end:]
            existing = existing.rstrip() + "\n\n"
        else:
            existing = existing.rstrip() + "\n\n"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""

    path.write_text(f"{existing}{marker}\n{content}\n{end_marker}\n")


def uninstall(
    key: str,
    *,
    agent_targets: list[str] | None = None,
    scope: str = "project",
    project_dir: Path | str | None = None,
    store: LocalSkillStore | None = None,
) -> dict[str, Path]:
    """Remove a skill's installation from agent target directories.

    Returns a dict mapping agent target names to the paths that were removed.

    Hosts that share a folder (Codex, Cursor, Copilot, Gemini CLI and Cline all read
    ``<project>/.agents/skills``) share one installation, so removing it for one of
    them removes it for all (a warning names the others). Only an installation of this
    skill (a link to it or a copy of it) is removed; anything else at that path, such
    as a skill of the same name written by hand or by another installer, is left alone
    with a warning.
    """
    if store is None:
        store = LocalSkillStore()

    if key not in store:
        raise KeyError(f"Skill {key!r} not found in local store.")

    skill = store[key]
    config = load_config()
    targets = agent_targets or config.default_agent_targets

    if scope == "project":
        if project_dir is None:
            project_dir = find_project_root()
        if project_dir is None:
            raise RuntimeError("Could not detect project root.")
        project_dir = Path(project_dir)

    removed = {}
    for target_name in targets:
        target = AGENT_TARGETS.get(target_name)
        if target is None:
            continue

        skill_name = skill.meta.name
        if scope == "project":
            dest = target.format_project_path(project_dir, skill_name)
        else:
            dest = target.format_global_path(skill_name)

        if dest is None:
            continue

        if target.appends:
            # A shared instructions file: remove only the skill's section, never the
            # file, and never through a symlink (GEMINI.md -> AGENTS.md)
            if dest.is_symlink():
                warnings.warn(
                    f"{dest.name} is a symlink; not editing it for {target_name!r}",
                    stacklevel=2,
                )
            elif dest.is_file() and _remove_section(dest, skill_name):
                removed[target_name] = dest
        elif dest in removed.values():
            removed[target_name] = dest  # a shared folder, already removed in this call
        elif dest.exists() or dest.is_symlink():
            source = skill.source_path or store._key_to_path(key)
            if not target.needs_translation and not (
                _check_existing(dest) == "our_symlink" or _is_install_of(dest, source)
            ):
                warnings.warn(
                    f"{dest} is not an installation of {key!r}; leaving it alone",
                    stacklevel=2,
                )
                continue
            sharing = sorted(
                n
                for n, t in AGENT_TARGETS.items()
                if n not in targets
                and not t.needs_translation
                and (
                    t.format_project_path(project_dir, skill_name)
                    if scope == "project"
                    else t.format_global_path(skill_name)
                )
                == dest
            )
            if sharing:
                warnings.warn(
                    f"{dest} is shared: removing it also removes {skill_name!r} for "
                    f"{', '.join(sharing)}",
                    stacklevel=2,
                )
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            elif dest.is_dir():
                shutil.rmtree(dest)
            removed[target_name] = dest

    return removed


# ---------------------------------------------------------------------------
# Link skills from a source directory
# ---------------------------------------------------------------------------

_SKILL_MARKER = "SKILL.md"


def _has_skills(directory: Path) -> bool:
    """Return True if ``directory`` contains at least one skill subdirectory."""
    if not directory.is_dir():
        return False
    return any(
        child.is_dir() and (child / _SKILL_MARKER).exists()
        for child in directory.iterdir()
    )


def _resolve_skills_source(source: Path) -> Path:
    """Find the actual skills directory given a path that might be a project root.

    Resolution order:

    1. If ``source`` itself contains skill subdirectories, use it directly.
    2. If ``source/skills`` exists and contains skills, use that. This is the
       canonical, cross-agent layout that ``gh skill``/``npx skills`` discover,
       so it takes precedence over the others when present.
    3. If ``source/.claude/skills`` exists and contains skills, use that.
    4. If ``source/{pkg}/data/skills`` exists for some package ``pkg`` (detected
       via ``pyproject.toml``), use that.
    5. Fall back to ``source`` as-is (will yield nothing if no skills found).
    """
    # 1. Direct: source already contains skill subdirs
    if _has_skills(source):
        return source

    # 2. Canonical top-level skills/ (gh skill / npx skills layout)
    top_level_skills = source / "skills"
    if _has_skills(top_level_skills):
        return top_level_skills

    # 3. .claude/skills convention
    claude_skills = source / ".claude" / "skills"
    if _has_skills(claude_skills):
        return claude_skills

    # 4. {pkg}/data/skills convention (Python projects)
    pyproject = source / "pyproject.toml"
    if pyproject.exists():
        # Infer package name from the directory name (common convention)
        pkg_name = source.name.replace("-", "_")
        pkg_skills = source / pkg_name / "data" / "skills"
        if _has_skills(pkg_skills):
            return pkg_skills

    return source


def _iter_skill_dirs(source: Path):
    """Yield ``(name, path)`` for each skill directory found under ``source``.

    A skill directory is any immediate subdirectory containing a ``SKILL.md``.
    """
    if not source.is_dir():
        raise NotADirectoryError(f"Not a directory: {source}")
    for child in sorted(source.iterdir()):
        if child.is_dir() and (child / _SKILL_MARKER).exists():
            yield child.name, child


# ---------------------------------------------------------------------------
# Target validation
# ---------------------------------------------------------------------------


def _known_target_parents() -> set[Path]:
    """Return the set of resolved parent directories for all known agent targets.

    Only user-level (global) paths are read: for example ``~/.claude/skills`` for
    claude-code and ``~/.cursor/skills`` for cursor.
    """
    parents = set()
    home = str(Path.home())
    for target in AGENT_TARGETS.values():
        if target.global_path is not None:
            # Format with a dummy name, then take the parent
            p = Path(target.global_path.format(home=home, name="_dummy"))
            parents.add(p.parent)
    return parents


def _is_recognized_target(target_path: Path) -> bool:
    """Check whether ``target_path`` is a recognized skills target directory.

    Recognized if:
    - It matches a known agent target parent directory (e.g. ~/.claude/skills).
    - It already contains at least one skill subdirectory (existing skills dir).
    - It is empty or does not yet exist (fresh target — allow it).
    """
    resolved = target_path.resolve()

    # Known agent target directories
    if resolved in _known_target_parents():
        return True

    # Doesn't exist yet or is empty — safe to create into
    if not resolved.exists():
        return True
    if resolved.is_dir() and not any(resolved.iterdir()):
        return True

    # Already contains skills — it's a skills directory
    if _has_skills(resolved):
        return True

    return False


def link_skills(
    source: str,
    *,
    target: str = "",
    copy: bool = False,
    force: bool = False,
) -> dict[str, Path]:
    """Symlink (or copy) every skill found under ``source`` into ``target``.

    ``source`` can be a skills directory directly, a project root (will look
    for ``.claude/skills/`` or ``{pkg}/data/skills/``), or any directory
    containing skill subdirectories (each with a ``SKILL.md``).

    Each candidate skill is validated before linking. Skills with validation
    errors are skipped and a warning is emitted.

    The ``target`` directory is checked against known agent target directories.
    If it doesn't match a recognized target, a ``ValueError`` is raised (unless
    it's empty or already contains skills).

    Returns a dict mapping skill names to their installed paths.

    Parameters
    ----------
    source : str
        A skills directory, or a project root containing skills.
    target : str
        Destination directory. Defaults to ``~/.claude/skills``.
    copy : bool
        If True, copy instead of symlink.
    force : bool
        If True, overwrite existing files/links at the destination.
    """
    source_path = _resolve_skills_source(Path(source).resolve())
    if target:
        target_path = Path(target).expanduser().resolve()
    else:
        target_path = Path.home() / ".claude" / "skills"

    if not _is_recognized_target(target_path):
        raise ValueError(
            f"Target directory {target_path} is not a recognized skills "
            f"target. Known targets: "
            f"{', '.join(str(p) for p in sorted(_known_target_parents()))}. "
            f"The target must be a known agent skills directory, an empty "
            f"directory, or a directory already containing skills."
        )

    installed = {}
    for name, skill_dir in _iter_skill_dirs(source_path):
        skill = Skill.from_path(skill_dir)
        issues = _validate_skill(skill)
        if issues:
            warnings.warn(
                f"Skipping invalid skill {name!r} at {skill_dir}: " + "; ".join(issues),
                stacklevel=2,
            )
            continue
        dest = target_path / name
        _create_link(skill_dir, dest, copy=copy, force=force)
        installed[name] = dest

    return installed


def _remove_section(path: Path, skill_name: str) -> bool:
    """Remove a skill's section from a shared instructions file (Copilot, Gemini).

    Returns whether there was a section to remove.
    """
    marker = f"<!-- skill:{skill_name} -->"
    end_marker = f"<!-- /skill:{skill_name} -->"
    content = path.read_text()
    if marker in content and end_marker in content:
        start = content.index(marker)
        end = content.index(end_marker) + len(end_marker)
        content = content[:start] + content[end:]
        content = content.strip() + "\n" if content.strip() else ""
        path.write_text(content)
        return True
    return False
