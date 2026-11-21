# skill.profiles

Per-host validation profiles for SKILL.md, and a YAML-safety check.

The open spec’s limits (what `skill.validate()` always checks) are not what
every host enforces. A skill can pass them and still be rejected or truncated by
the host it is shipped to. A [`Profile`](#skill.profiles.Profile) is data: the frontmatter keys a
host accepts and its description cap. `validate(path, profile='portable')`
adds the checks of that profile on top of the registered validators.

```pycon
>>> sorted(PROFILES)
['claude-code', 'portable', 'spec']
>>> PROFILES['portable'].max_description
200
```

### Module Attributes

| [`SPEC_KEYS`](#skill.profiles.SPEC_KEYS)   | Frontmatter keys of the open agent-skills specification.   |
|--------------------------------------------------------------|------------------------------------------------------------|

### Functions

| [`check_profile`](#skill.profiles.check_profile)(\*, keys, description, profile)   | Issues a host profile finds in a skill's top-level `keys` and `description`.                         |
|--------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| [`check_yaml_safety`](#skill.profiles.check_yaml_safety)(frontmatter)                  | Flag unquoted top-level values that YAML reads differently from what was meant.                      |
| [`get_profile`](#skill.profiles.get_profile)(profile)                            | Resolve a profile name (or pass a [`Profile`](#skill.profiles.Profile) through). |

### Classes

| [`Profile`](#skill.profiles.Profile)(name[, allowed_keys, max_description])   | What one host enforces on SKILL.md frontmatter.   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------|

### *class* skill.profiles.Profile(name, allowed_keys=None, max_description=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one host enforces on SKILL.md frontmatter.

`allowed_keys=None` means the host does not restrict top-level keys.
`max_description=None` means no cap beyond the open spec’s 1024.

### skill.profiles.SPEC_KEYS *= frozenset({'allowed-tools', 'compatibility', 'description', 'license', 'metadata', 'name'})*

Frontmatter keys of the open agent-skills specification.

### skill.profiles.check_profile(, keys, description, profile)

Issues a host profile finds in a skill’s top-level `keys` and `description`.

```pycon
>>> check_profile(keys=['name', 'description', 'model'], description='x' * 201,
...               profile='portable')
['Description exceeds 200 characters for profile portable (201)', "Key 'model' is not accepted by profile portable"]
>>> check_profile(keys=['name'], description='ok', profile='spec')
[]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### skill.profiles.check_yaml_safety(frontmatter)

Flag unquoted top-level values that YAML reads differently from what was meant.

A value holding `": "` is read as a new key; one holding `" #"` as a comment
(everything after it is dropped). Quoted values and block scalars are safe.

```pycon
>>> check_yaml_safety('name: x\ndescription: Use when: the user asks')
["description: unquoted value contains ': ' (YAML reads a new key); quote it"]
>>> check_yaml_safety('name: x\ndescription: Fix issue#12 now')
[]
>>> check_yaml_safety('description: Fix this #12')
["description: unquoted value contains ' #' (YAML reads a comment); quote it"]
>>> check_yaml_safety('description: "Use when: fine #1"\nname: x')
[]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### skill.profiles.get_profile(profile)

Resolve a profile name (or pass a [`Profile`](#skill.profiles.Profile) through).

```pycon
>>> get_profile('spec').name
'spec'
>>> get_profile('nope')
Traceback (most recent call last):
...
ValueError: Unknown profile 'nope'; known: claude-code, portable, spec
```

* **Return type:**
  [`Profile`](#skill.profiles.Profile)
