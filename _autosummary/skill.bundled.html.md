# skill.bundled

Link a package’s bundled skills and agents into one or more Claude homes.

Packages that ship `<pkg>/data/skills/<name>/` (and `<pkg>/data/agents/<name>.md`)
all need the same ~25 lines: link each into `~/.claude/skills` (or several Claude
homes, e.g. a second account’s `CLAUDE_CONFIG_DIR`), idempotently, reporting `ok` /
`install` / `conflict` per asset and never overwriting something that is not ours
without `force`. This is that mechanism, once.

**Pure standard library and self-contained on purpose**: a package that keeps zero
runtime dependencies can copy this file instead of depending on `skill`.

```pycon
>>> import tempfile, pathlib
>>> root = pathlib.Path(tempfile.mkdtemp())
>>> (root / "data/skills/demo").mkdir(parents=True)
>>> _ = (root / "data/skills/demo/SKILL.md").write_text("---\nname: demo\n---\n")
>>> home = root / "home"
>>> [r["action"] for r in install_bundled(root / "data", homes=[home])]
['install']
>>> [r["action"] for r in install_bundled(root / "data", homes=[home])]
['ok']
```

### Functions

| [`claude_homes`](#skill.bundled.claude_homes)()                                | Every Claude Code home on this machine: `~/.claude` and `~/.claude-*`.   |
|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`install_bundled`](#skill.bundled.install_bundled)(source_dir, \*[, homes, ...]) | Install a package's bundled skills and agents into each Claude home.     |

### skill.bundled.claude_homes()

Every Claude Code home on this machine: `~/.claude` and `~/.claude-*`.

A home counts when it has a `skills` folder. `CLAUDE_CONFIG_DIR`, when set, is
included even if it has none yet.

```pycon
>>> all(isinstance(h, Path) for h in claude_homes())
True
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### skill.bundled.install_bundled(source_dir, , homes=None, force=False, dry_run=False)

Install a package’s bundled skills and agents into each Claude home.

`source_dir` holds `skills/<name>/` directories and/or `agents/<name>.md` files
(a package’s `data` folder). `homes` defaults to [`claude_homes()`](#skill.bundled.claude_homes). Returns one
row per (home, asset): `{"home", "name", "action"}` with `action` one of

- `"ok"`: already installed (a link to the source, or an identical copy);
- `"install"`: installed now (or would be, under `dry_run`); a `"method"` key
  says `symlink` or `copy`;
- `"conflict"`: something else is at that name; left alone unless `force`.

```pycon
>>> install_bundled("/no/such/folder", homes=["/tmp/never-used"])
[]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
