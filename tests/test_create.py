"""Tests for skill.create."""

import pytest
from pathlib import Path

from skill.base import Skill, SkillMeta
from skill.stores import LocalSkillStore
from skill.create import create, scaffold, validate, _is_valid_name


class TestCreate:
    def test_creates_skill_in_store(self, tmp_path):
        store = LocalSkillStore(root=tmp_path)
        s = create('my-skill', description='Does things', store=store)
        assert s.meta.name == 'my-skill'
        assert '_local/my-skill' in store

    def test_custom_body(self, tmp_path):
        store = LocalSkillStore(root=tmp_path)
        s = create('custom', description='Custom', body='Custom body', store=store)
        assert s.body == 'Custom body'

    def test_custom_owner(self, tmp_path):
        store = LocalSkillStore(root=tmp_path)
        create('test', description='Test', owner='myorg', store=store)
        assert 'myorg/test' in store


class TestScaffold:
    def test_creates_directory(self, tmp_path):
        path = scaffold('demo', path=tmp_path / 'demo')
        assert (path / 'SKILL.md').exists()
        assert (path / 'scripts').is_dir()
        assert (path / 'references').is_dir()

    def test_skill_md_content(self, tmp_path):
        path = scaffold('demo', description='A demo skill', path=tmp_path / 'demo')
        content = (path / 'SKILL.md').read_text()
        assert 'name: demo' in content
        assert 'A demo skill' in content


class TestValidate:
    def test_valid_skill(self, tmp_path):
        d = tmp_path / 'good'
        Skill(
            meta=SkillMeta(name='good-skill', description='A good skill'),
            body='# Good\n',
        ).write_to(d)
        assert validate(str(d)) == []

    def test_missing_name(self, tmp_path):
        d = tmp_path / 'bad'
        Skill(meta=SkillMeta(name='', description='desc'), body='body').write_to(d)
        issues = validate(str(d))
        assert any('name' in i for i in issues)

    def test_missing_description(self, tmp_path):
        d = tmp_path / 'bad'
        Skill(meta=SkillMeta(name='ok-name', description=''), body='body').write_to(d)
        issues = validate(str(d))
        assert any('description' in i for i in issues)

    def test_empty_body(self, tmp_path):
        d = tmp_path / 'bad'
        Skill(meta=SkillMeta(name='ok-name', description='desc'), body='').write_to(d)
        issues = validate(str(d))
        assert any('body' in i.lower() for i in issues)

    def test_invalid_name_format(self, tmp_path):
        d = tmp_path / 'bad'
        Skill(meta=SkillMeta(name='BadName', description='desc'), body='body').write_to(d)
        issues = validate(str(d))
        assert any('Invalid name' in i for i in issues)

    def test_missing_skill_md(self, tmp_path):
        d = tmp_path / 'empty'
        d.mkdir()
        issues = validate(str(d))
        assert any('Missing SKILL.md' in i for i in issues)


class TestIsValidName:
    def test_valid(self):
        assert _is_valid_name('my-skill')
        assert _is_valid_name('skill123')
        assert _is_valid_name('a')

    def test_invalid(self):
        assert not _is_valid_name('MySkill')
        assert not _is_valid_name('my_skill')
        assert not _is_valid_name('')
        assert not _is_valid_name('-leading-dash')


class TestValidateProfiles:
    """Host profiles and the YAML-safety rule (#20)."""

    @staticmethod
    def _write(tmp_path, front):
        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\n{front}\n---\nbody\n")
        return str(d)

    def test_default_profile_is_the_open_spec(self, tmp_path):
        from skill import validate

        d = self._write(tmp_path, f"name: s\ndescription: {'x' * 300}\nmodel: opus")
        assert validate(d) == []

    def test_portable_caps_description_and_keys(self, tmp_path):
        from skill import validate

        d = self._write(tmp_path, f"name: s\ndescription: {'x' * 300}\nmodel: opus")
        issues = validate(d, profile="portable")
        assert any("200" in i for i in issues) and any("'model'" in i for i in issues)

    def test_claude_code_accepts_its_keys(self, tmp_path):
        from skill import validate

        d = self._write(tmp_path, f"name: s\ndescription: {'x' * 300}\nmodel: opus")
        assert validate(d, profile="claude-code") == []

    def test_unknown_profile_is_an_error(self, tmp_path):
        from skill import validate

        with pytest.raises(ValueError, match="Unknown profile"):
            validate(self._write(tmp_path, "name: s\ndescription: d"), profile="nope")

    def test_yaml_safety_flags_unquoted_colon_and_hash(self, tmp_path):
        from skill import validate

        d = self._write(tmp_path, "name: s\ndescription: Use when: asked # now")
        assert any("quote it" in i for i in validate(d))


def test_a_value_holding_dashes_does_not_end_the_frontmatter(tmp_path):
    """Keys after `description: a --- b` are still YAML-safety checked (addaix/skill#35)."""
    from skill.base import parse_frontmatter
    from skill.create import validate

    text = (
        "---\nname: s\ndescription: Reports --- fast\nlicense: MIT # see LICENSE\n---\n# Body\n"
    )
    meta, body = parse_frontmatter(text)
    assert meta["license"] == "MIT" and body.startswith("# Body")
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(text)
    problems = validate(d)
    assert any("license" in p or "#" in p for p in problems), problems
