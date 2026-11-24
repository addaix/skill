# skill.wheel

The `wheel-included-skills` placement method: a tested build recipe.

The real skill files live once, in the repository’s top-level `skills/<name>/` (where
`gh skill` and the wider ecosystem look), and the build copies that folder into the
wheel as `<pkg>/_skills/` so a `pip install` carries them too (addaix/skill#8, #31).
The copy exists only in the built wheel, never in the repository, so `gh skill` sees
each skill once; it is a copy, never a symlink, because whether `gh skill` follows a
symlink is unverified.

- [`wheel_skills_config()`](#skill.wheel.wheel_skills_config) gives the hatchling `pyproject.toml` settings as a dict,
  to merge into an existing file; [`wheel_skills_snippet()`](#skill.wheel.wheel_skills_snippet) the same as TOML text, for
  a file that has no such table yet, or (setuptools) a `setup.py`, since
  `pyproject.toml` alone cannot keep setuptools’ package discovery and add the
  mapped `<pkg>._skills` package too (addaix/skill#44).
- [`check_wheel_skills()`](#skill.wheel.check_wheel_skills) checks a built wheel against the repository: every
  `skills/<name>/` file is in the wheel under `<pkg>/_skills/<name>/`, byte for byte,
  every `SKILL.md` exactly once, the repository holds each skill once, and every
  subpackage of the import package is in the wheel too.
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
| [`wheel_skills_snippet`](#skill.wheel.wheel_skills_snippet)(package, \*[, backend, ...])  | The recipe as text.                                                                                                                                                                 |
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
  in-wheel folder (`<package>/<target_dir>`) in the repository;
- a subpackage of `package` in the repository (a folder with an `__init__.py`)
  that is not in the wheel: a recipe that lists packages by hand leaves the others
  out (addaix/skill#44).

#### WARNING
a skill whose `audience` is `developer` ships to users; a `tests`
(or `test`) subpackage, or one inside it, is not in the wheel (often deliberate).
A missing package is reported once, not once per subpackage under it. When there
are problems and a `setup.py` sits beside a `pyproject.toml` whose
`[tool.setuptools]` sets packages, `packages.find`, `package-dir` or
`package-data` (which override the `setup.py` recipe), the check names them.

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
- `setuptools`: not expressible in `pyproject.toml`. An explicit
  `[tool.setuptools] packages` list turns package discovery off, so every
  subpackage would be left out of the wheel, and `[tool.setuptools.packages.find]`
  ignores a `package-dir` entry for a package it does not find, so the skills would
  be. This raises `ValueError` pointing at the `setup.py` recipe of
  [`wheel_skills_snippet()`](#skill.wheel.wheel_skills_snippet).

The build must see `source`: a wheel built from an sdist (the default of
`python -m build`) needs it in the sdist too.

```pycon
>>> wheel_skills_config("p")
{'tool': {'hatch': {'build': {'targets': {'wheel': {'force-include': {'skills': 'p/_skills'}}}}}}}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### skill.wheel.wheel_skills_snippet(package, , backend='hatch', source='skills', target_dir='_skills')

The recipe as text. hatchling: [`wheel_skills_config()`](#skill.wheel.wheel_skills_config) as `pyproject.toml`
text, for a file that has none of these tables yet (merge the dict instead when it
has). setuptools: a `setup.py` that keeps package discovery (`find_packages`)
and adds `<package>.<target_dir>` with `source` as its folder; the project’s
metadata stays in `pyproject.toml`, which must then set none of
`[tool.setuptools]` `packages`, `packages.find`, `package-dir` or
`package-data` (each overrides the same `setup.py` setting: move them into
the `setup.py`). setuptools prints a “Package would be ignored” notice for skill
folders whose names are identifiers; they are still shipped as package data. The
`setup.py` is for a flat layout
(`<package>/` at the root); for a `src/` layout pass `where="src"` to
`find_packages` and add `"": "src"` to `package_dir`.

```pycon
>>> print(wheel_skills_snippet("p", backend="setuptools"))
# setup.py: keeps package discovery and adds skills/ to the wheel as p/_skills
from setuptools import find_packages, setup

setup(
    packages=find_packages(include=["p", "p.*"]) + ["p._skills"],
    package_dir={"p._skills": "skills"},
    package_data={"p._skills": ["**/*"]},
)
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
