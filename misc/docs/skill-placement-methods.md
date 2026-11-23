# Skill placement methods — decision record (2026-11-23)

Decides [addaix/skill#8](https://github.com/addaix/skill/issues/8): the named methods for where a Python package's agent skills live, which one is the default, and how a user on each agent host installs them. **Amends** `skill-management-best-practices.md` (2026-06), whose rule put a pip package's skills in `{pkg}/data/skills/` by default; the layout rules it set (one real location, the `.claude/skills/` symlink bridge, spec-clean frontmatter, `gh skill` as the primary channel) all still hold.

## The methods

Each name describes the method, not its status, so the default can change without renaming anything.

| Method | Real files | In the wheel? | How a user gets the skills |
|---|---|---|---|
| **`repo-skills`** (the default) | `skills/<name>/` at the repository root | no | `gh skill install <owner>/<repo> <name> --agent <host>`, or `skill install` / `skill link-skills <checkout>` |
| **`package-data-skills`** | `{pkg}/data/skills/<name>/` | yes, as package data | the same `gh skill` command (the nested `**/skills/*` glob finds it), or from the installed package (see below) |
| **`wheel-included-skills`** | `skills/<name>/` at the repository root, copied into the wheel at build time (for example `[tool.hatch.build.targets.wheel.force-include] "skills" = "{pkg}/_skills"`) | yes, copied at build | the same `gh skill` command, or from the installed package |
| **`plugin-marketplace`** (additive, Claude Code only) | any of the above, plus `.claude-plugin/` manifests | as the base method | `/plugin install` in Claude Code |

In every method the real files live in exactly one non-hidden place in the repository, and `.claude/skills/<name>` is a relative per-skill symlink to it. `wheel-included-skills` names its in-wheel folder something other than `skills` (`_skills` above) only for clarity: the copy exists in the built wheel, never in the repository, so `gh skill` never sees two.

## The default: `repo-skills`

Chosen as the maintainer proposed in the issue, because:

- **It is where the cross-host tooling looks first.** `gh skill` discovers `**/skills/*/SKILL.md`, and top-level `skills/` is the convention the wider ecosystem's examples use (`skill_distribution_analysis.md`, Option 2). `{pkg}/data/skills/` is discovered too, but only through the nested glob.
- **A wheel is the wrong channel into an agent host.** pip has no post-install hook, so a skill in the wheel still needs a command to reach `.claude/skills/`, `.agents/skills/` or `~/.copilot/skills/`. Bundling saves nobody that step; it only adds bytes to every install, including servers and CI that never run an agent.
- **No ecosystem installs skills automatically with a package.** The closest is npm's opt-in `skills-npm` (a dev tool that links skills on `npm install`), and it is opt-in. Telling the user to install the skills explicitly, per host, is the clean story; `pip install pkg` followed by one `gh skill install` line from the README is it.
- **Skills and code version together anyway.** `gh skill install <owner>/<repo> <name>@vX.Y.Z` pins the skills to the same tag the package was released from.

`package-data-skills` stays fully supported: a package that wants its skills to travel inside the wheel (offline installs, a host with no `gh`) keeps them there. `wheel-included-skills` is the middle way when a package wants both the conventional repository layout and skills in the wheel; it needs only build configuration.

## Install story per host

What each host reads natively, from the research in this folder (`Cross-agent skill format compatibility and translation.md`, `gh-skill-reference.md`, and the agent targets in `skill/install.py`). Items the research marked unverified are marked so.

| Host | Reads skills from | Install command |
|---|---|---|
| Claude Code | `.claude/skills/` (project), `~/.claude/skills/` (user) | `gh skill install o/r name --agent claude-code`, or `skill link-skills <checkout>` |
| GitHub Copilot | `.github/skills/` (project), `~/.copilot/skills/` (user) | `gh skill install o/r name` (Copilot is `gh skill`'s default agent) |
| OpenAI Codex | `.agents/skills/` from the working directory up to the repository root, `~/.agents/skills/` | `gh skill install o/r name --agent codex` |
| Cursor | `.agents/skills/` (project), `~/.cursor/skills/` (user) | `gh skill install o/r name --agent cursor` |
| Gemini CLI | `.agents/skills/` (project), `~/.gemini/skills/` (user); older notes say `.gemini/skills/` (unverified which is current) | `gh skill install o/r name --agent gemini` |
| Others (Windsurf, Roo, Cline) | `.windsurf/skills/`, `.roo/skills/`, `.agents/skills/` | `skill install` with that agent target; `gh skill`'s full `--agent` list is unverified |

`gh skill` needs gh 2.90.0 or later. A README's "Skills" section gives one `gh skill install` line per skill and the `--agent` flag for non-Copilot hosts (`skill-docs` generates it).

## What this spawns

- A CLI path from an installed package to a host: `skill install --from-package <distribution>` that finds the skills of an installed distribution (`package-data-skills` and `wheel-included-skills` layouts, through `importlib.resources`) and links them for a chosen host; and `install_from_github` exposed on the CLI with `--scope`. Filed as an issue in this repository.
- The `wheel-included-skills` recipe as a tested snippet (hatch `force-include`, plus a check that the wheel holds the skills and the repository holds them once). Filed as an issue in this repository.
- `skill-package-setup` (this repository's `skills/`) now teaches `repo-skills` as the default and the other methods by name; `wads-skillify` defers to it and is aligned through an issue in its repository.
- No fleet sweep: the 27 repositories that use `{pkg}/data/skills/` today are already a supported method (`package-data-skills`) and move only on touch, if their maintainer wants the default.
