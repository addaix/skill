# skill.wheel

The `wheel-included-skills` placement method: a tested build recipe.

The real skill files live once, in the repository’s top-level `skills/<name>/` (where
`gh skill` and the wider ecosystem look), and the build copies that folder into the
wheel as `<pkg>/_skills/` so a `pip install` carries them too (addaix/skill#8, #31).
The copy exists only in the built wheel, never in the repository, so `gh skill` sees
each skill once; it is a copy, never a symlink, because whether `gh skill` follows a
symlink is unverified.

- [`wheel_skills_config()`](#skill.wheel.wheel_skills_config) gives the `pyproject.toml` settings as a dict (hatchling
  or setuptools), to merge into an existing file; [`wheel_skills_snippet()`](#skill.wheel.wheel_skills_snippet) the same
  as TOML text, for a file that has no such table yet.
- [`check_wheel_skills()`](#skill.wheel.check_wheel_skills) checks a built wheel against the repository: every
  `skills/<name>/` file is in the wheel under `<pkg>/_skills/<name>/`, byte for byte,
  every `SKILL.md` exactly once, and the repository holds each skill once.
- `skill install-from-package <distribution>` then finds `<pkg>/_skills` in the
  installed package (`skill.install.PACKAGE_SKILLS_SUBPATHS`).

```pycon
>>> print(wheel_skills_snippet("my_pkg"))
[tool.hatch.build.targets.wheel.force-include]
"skills" = "my_pkg/_skills"
```

### Module Attributes

| [`WHEEL_SKILLS_DIR`](#skill.wheel.WHEEL_SKILLS_DIR)   | The folder, inside the import package, that the build copies `skills/` to.   |
|---------------------------------------------------------------------|------------------------------------------------------------------------------|

### Functions

| [`wheel_skills_config`](#skill.wheel.wheel_skills_config)(package, \*[, backend, ...])   | The `pyproject.toml` settings that put `source` into the wheel as `<package>/<target_dir>`, as a nested dict to merge into the file (with tomlkit, say) rather than append to it.   |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`wheel_skills_snippet`](#skill.wheel.wheel_skills_snippet)(package, \*[, backend, ...])  | [`wheel_skills_config()`](#skill.wheel.wheel_skills_config) as `pyproject.toml` text, for a file that has none of these tables yet (merge the dict instead when it has). |
| [`check_wheel_skills`](#skill.wheel.check_wheel_skills)(wheel[, repo_root, ...])        | Check a built wheel against the repository it was built from.                                                                                                                       |

### Classes

| [`WheelSkillsReport`](#skill.wheel.WheelSkillsReport)([skills, problems, warnings])   | What [`check_wheel_skills()`](#skill.wheel.check_wheel_skills) found.   |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|

### skill.wheel.WHEEL_SKILLS_DIR *= '_skills'*

The folder, inside the import package, that the build copies `skills/` to.

### *class* skill.wheel.WheelSkillsReport(skills=list(), problems=list(), warnings=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What [`check_wheel_skills()`](#skill.wheel.check_wheel_skills) found. `ok` when there are no `problems`;
`warnings` (such as a developer skill shipped to users) do not fail it.

### skill.wheel.check_wheel_skills(wheel, repo_root='.', , package=None, source='skills', target_dir='_skills')

Check a built wheel against the repository it was built from.

Problems (`report.ok` is false):

- a repository skill (`<source>/<name>/`) missing from the wheel, or one of its
  files missing or different in `<package>/<target_dir>/<name>/`;
- a skill whose `SKILL.md` the wheel holds more than once (anywhere), or a
  skill in the wheel’s `<target_dir>` that the repository does not have;
- a skill whose real `SKILL.md` the repository holds in more than one
  non-hidden place (`gh skill` reports duplicates), or a committed copy of the
  in-wheel folder (`<package>/<target_dir>`) in the repository.

#### WARNING
a skill whose `audience` is `developer` ships to users.

`package` defaults to the one import package that has a `<target_dir>` in the
wheel.

* **Return type:**
  [`WheelSkillsReport`](#skill.wheel.WheelSkillsReport)

### skill.wheel.wheel_skills_config(package, , backend='hatch', source='skills', target_dir='_skills')

The `pyproject.toml` settings that put `source` into the wheel as
`<package>/<target_dir>`, as a nested dict to merge into the file (with tomlkit,
say) rather than append to it.

- `hatch`: `force-include`. hatchling copies the files, following links, and
  skips its built-in excludes (`.DS_Store`, `.pytest_cache`…).
- `setuptools`: `<package>.<target_dir>` declared as a package whose directory is
  `source`, with all its files as package data.

The build must see `source`: a wheel built from an sdist (the default of
`python -m build`) needs it in the sdist too.

```pycon
>>> wheel_skills_config("p")
{'tool': {'hatch': {'build': {'targets': {'wheel': {'force-include': {'skills': 'p/_skills'}}}}}}}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### skill.wheel.wheel_skills_snippet(package, , backend='hatch', source='skills', target_dir='_skills')

[`wheel_skills_config()`](#skill.wheel.wheel_skills_config) as `pyproject.toml` text, for a file that has none
of these tables yet (merge the dict instead when it has).

```pycon
>>> print(wheel_skills_snippet("p", backend="setuptools"))
[tool.setuptools]
packages = ["p", "p._skills"]
package-dir = { "p._skills" = "skills" }
package-data = { "p._skills" = ["**/*"] }
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
