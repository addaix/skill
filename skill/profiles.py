"""Per-host validation profiles for SKILL.md, and a YAML-safety check.

The open spec's limits (what :func:`skill.validate` always checks) are not what
every host enforces. A skill can pass them and still be rejected or truncated by
the host it is shipped to. A :class:`Profile` is data: the frontmatter keys a
host accepts and its description cap. ``validate(path, profile='portable')``
adds the checks of that profile on top of the registered validators.

>>> sorted(PROFILES)
['claude-code', 'portable', 'spec']
>>> PROFILES['portable'].max_description
200
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

#: Frontmatter keys of the open agent-skills specification.
SPEC_KEYS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)


@dataclass(frozen=True)
class Profile:
    """What one host enforces on SKILL.md frontmatter.

    ``allowed_keys=None`` means the host does not restrict top-level keys.
    ``max_description=None`` means no cap beyond the open spec's 1024.
    """

    name: str
    allowed_keys: frozenset[str] | None = None
    max_description: int | None = None


PROFILES: Mapping[str, Profile] = {
    # the open spec only: the default, what validate() has always checked
    "spec": Profile("spec"),
    # claude.ai upload, ChatGPT, the Gemini app: only the open spec's keys, and
    # claude.ai caps the description at 200 characters
    "portable": Profile("portable", allowed_keys=SPEC_KEYS, max_description=200),
    # Claude Code (.claude/skills/): 1024 characters; accepts the spec's keys plus
    # when_to_use, argument-hint, disable-model-invocation, user-invocable,
    # model, context, agent, hooks, and ignores any other key
    "claude-code": Profile("claude-code", max_description=1024),
}


def get_profile(profile: str | Profile) -> Profile:
    """Resolve a profile name (or pass a :class:`Profile` through).

    >>> get_profile('spec').name
    'spec'
    >>> get_profile('nope')
    Traceback (most recent call last):
    ...
    ValueError: Unknown profile 'nope'; known: claude-code, portable, spec
    """
    if isinstance(profile, Profile):
        return profile
    try:
        return PROFILES[profile]
    except KeyError:
        raise ValueError(
            f"Unknown profile {profile!r}; known: {', '.join(sorted(PROFILES))}"
        ) from None


def check_profile(
    *, keys: Collection[str], description: str, profile: str | Profile
) -> list[str]:
    """Issues a host profile finds in a skill's top-level ``keys`` and ``description``.

    >>> check_profile(keys=['name', 'description', 'model'], description='x' * 201,
    ...               profile='portable')
    ['Description exceeds 200 characters for profile portable (201)', "Key 'model' is not accepted by profile portable"]
    >>> check_profile(keys=['name'], description='ok', profile='spec')
    []
    """
    p = get_profile(profile)
    issues = []
    if p.max_description is not None and len(description) > p.max_description:
        issues.append(
            f"Description exceeds {p.max_description} characters "
            f"for profile {p.name} ({len(description)})"
        )
    if p.allowed_keys is not None:
        issues += [
            f"Key {k!r} is not accepted by profile {p.name}"
            for k in keys
            if k not in p.allowed_keys
        ]
    return issues


_KEY_LINE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):[ \t]+(?P<value>\S.*)$")
_BLOCK_START = re.compile(r"^[|>][+-]?\d*$")


def check_yaml_safety(frontmatter: str) -> list[str]:
    """Flag unquoted top-level values that YAML reads differently from what was meant.

    A value holding ``": "`` is read as a new key; one holding ``" #"`` as a comment
    (everything after it is dropped). Quoted values and block scalars are safe.

    >>> check_yaml_safety('name: x\\ndescription: Use when: the user asks')
    ["description: unquoted value contains ': ' (YAML reads a new key); quote it"]
    >>> check_yaml_safety('name: x\\ndescription: Fix issue#12 now')
    []
    >>> check_yaml_safety('description: Fix this #12')
    ["description: unquoted value contains ' #' (YAML reads a comment); quote it"]
    >>> check_yaml_safety('description: "Use when: fine #1"\\nname: x')
    []
    """
    issues = []
    for line in frontmatter.splitlines():
        m = _KEY_LINE.match(line)
        if not m:
            continue
        value = m["value"].strip()
        if value[0] in "\"'[{" or _BLOCK_START.match(value):
            continue
        if ": " in value:
            issues.append(
                f"{m['key']}: unquoted value contains ': ' (YAML reads a new key); quote it"
            )
        elif re.search(r"\s#", value):
            issues.append(
                f"{m['key']}: unquoted value contains ' #' (YAML reads a comment); quote it"
            )
    return issues
