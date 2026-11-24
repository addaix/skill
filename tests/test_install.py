"""Tests for skill.install."""

import os
import pytest
from pathlib import Path

from skill.base import Skill, SkillMeta
from skill.stores import LocalSkillStore
from skill.install import (
    install,
    uninstall,
    _check_existing,
    _create_link,
    AgentTarget,
    AGENT_TARGETS,
)


def _setup_store_and_project(tmp_path):
    """Create a store with one skill and a fake project directory."""
    store_root = tmp_path / 'store'
    project = tmp_path / 'project'
    (project / '.git').mkdir(parents=True)

    store = LocalSkillStore(root=store_root)
    store['alice/greet'] = Skill(
        meta=SkillMeta(name='greet', description='Say hello'),
        body='# Greet\n\nSay hello to the user.\n',
    )
    return store, project


class TestCheckExisting:
    def test_none(self, tmp_path):
        assert _check_existing(tmp_path / 'nope') == 'none'

    def test_directory(self, tmp_path):
        d = tmp_path / 'existing'
        d.mkdir()
        assert _check_existing(d) == 'directory'

    def test_file(self, tmp_path):
        f = tmp_path / 'file.txt'
        f.write_text('hello')
        assert _check_existing(f) == 'file'

    def test_symlink(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        link = tmp_path / 'link'
        os.symlink(src, link)
        assert _check_existing(link) == 'foreign_symlink'


class TestCreateLink:
    def test_symlink(self, tmp_path):
        src = tmp_path / 'source'
        src.mkdir()
        target = tmp_path / 'target'
        result = _create_link(src, target)
        assert result.is_symlink()
        assert result.resolve() == src.resolve()

    def test_copy(self, tmp_path):
        src = tmp_path / 'source'
        src.mkdir()
        (src / 'file.txt').write_text('content')
        target = tmp_path / 'target'
        _create_link(src, target, copy=True)
        assert target.is_dir()
        assert (target / 'file.txt').read_text() == 'content'

    def test_force_overwrites(self, tmp_path):
        src = tmp_path / 'source'
        src.mkdir()
        target = tmp_path / 'target'
        target.write_text('existing')
        _create_link(src, target, force=True)
        assert target.is_symlink()

    def test_a_dangling_link_is_replaced_without_force(self, tmp_path):
        """A link whose target is gone holds nothing to lose (addaix/skill#43)."""
        src = tmp_path / 'source'
        src.mkdir()
        target = tmp_path / 'target'
        os.symlink(tmp_path / 'removed-env' / 'greet', target)
        _create_link(src, target)
        assert target.resolve() == src.resolve()

    def test_existing_raises_without_force(self, tmp_path):
        src = tmp_path / 'source'
        src.mkdir()
        target = tmp_path / 'target'
        target.mkdir()
        with pytest.raises(FileExistsError):
            _create_link(src, target)


class TestInstall:
    def test_install_claude_code(self, tmp_path):
        store, project = _setup_store_and_project(tmp_path)
        result = install(
            'alice/greet',
            agent_targets=['claude-code'],
            scope='project',
            project_dir=project,
            store=store,
        )
        assert 'claude-code' in result
        installed_path = result['claude-code']
        assert installed_path.is_symlink() or installed_path.is_dir()

    def test_install_cursor(self, tmp_path):
        store, project = _setup_store_and_project(tmp_path)
        result = install(
            'alice/greet',
            agent_targets=['cursor-rules'],
            scope='project',
            project_dir=project,
            store=store,
        )
        assert 'cursor-rules' in result
        content = result['cursor-rules'].read_text()
        assert 'description: Say hello' in content
        assert 'alwaysApply' in content

    def test_install_copilot(self, tmp_path):
        store, project = _setup_store_and_project(tmp_path)
        result = install(
            'alice/greet',
            agent_targets=['copilot-instructions'],
            scope='project',
            project_dir=project,
            store=store,
        )
        assert 'copilot-instructions' in result
        content = result['copilot-instructions'].read_text()
        assert '## greet' in content
        assert 'skill:greet' in content  # marker

    def test_install_missing_skill_raises(self, tmp_path):
        store, project = _setup_store_and_project(tmp_path)
        with pytest.raises(KeyError, match='nonexistent'):
            install('alice/nonexistent', store=store, project_dir=project)


class TestUninstall:
    def test_uninstall_claude_code(self, tmp_path):
        store, project = _setup_store_and_project(tmp_path)
        install(
            'alice/greet',
            agent_targets=['claude-code'],
            scope='project',
            project_dir=project,
            store=store,
        )
        result = uninstall(
            'alice/greet',
            agent_targets=['claude-code'],
            scope='project',
            project_dir=project,
            store=store,
        )
        assert 'claude-code' in result
        assert not result['claude-code'].exists()

    def test_uninstall_copilot(self, tmp_path):
        store, project = _setup_store_and_project(tmp_path)
        install(
            'alice/greet',
            agent_targets=['copilot-instructions'],
            scope='project',
            project_dir=project,
            store=store,
        )
        uninstall(
            'alice/greet',
            agent_targets=['copilot-instructions'],
            scope='project',
            project_dir=project,
            store=store,
        )
        instructions = project / '.github' / 'copilot-instructions.md'
        if instructions.exists():
            assert 'skill:greet' not in instructions.read_text()


class TestAgentTargets:
    def test_claude_code_exists(self):
        assert 'claude-code' in AGENT_TARGETS

    def test_cursor_exists(self):
        assert 'cursor' in AGENT_TARGETS
        assert AGENT_TARGETS['cursor-rules'].needs_translation

    def test_copilot_exists(self):
        assert 'copilot' in AGENT_TARGETS


def test_install_codex_links_into_agents_skills(tmp_path):
    # thorwhalen/skill#13: Codex reads SKILL.md folders from .agents/skills natively
    store, project = _setup_store_and_project(tmp_path)
    result = install(
        'alice/greet', agent_targets=['codex'], scope='project',
        project_dir=project, store=store,
    )
    path = result['codex']
    assert path == project / '.agents' / 'skills' / 'greet'
    assert path.is_symlink() and (path / 'SKILL.md').is_file()
    assert not AGENT_TARGETS['codex'].needs_translation


# -- more hosts: windsurf, cline, gemini (thorwhalen/opsward#68) --


@pytest.mark.parametrize(
    'target, rel, expected',
    [
        ('windsurf-rules', '.windsurf/rules/greet.md', 'trigger: model_decision'),
        ('cline-rules', '.clinerules/greet.md', '# greet'),
        ('gemini-md', 'GEMINI.md', 'skill:greet'),
    ],
)
def test_install_and_uninstall_new_hosts(tmp_path, target, rel, expected):
    from skill.install import uninstall

    store, project = _setup_store_and_project(tmp_path)
    kw = dict(agent_targets=[target], scope='project', project_dir=project, store=store)
    result = install('alice/greet', **kw)
    assert result[target] == project / rel
    assert expected in (project / rel).read_text()
    uninstall('alice/greet', **kw)
    assert not (project / rel).exists() or 'greet' not in (project / rel).read_text()


def test_appending_never_writes_through_a_symlink(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    (project / 'AGENTS.md').write_text('# canonical\n')
    (project / 'GEMINI.md').symlink_to('AGENTS.md')
    with pytest.warns(UserWarning, match='symlink'):
        result = install(
            'alice/greet', agent_targets=['gemini-md'], scope='project',
            project_dir=project, store=store,
        )
    assert result == {} and (project / 'AGENTS.md').read_text() == '# canonical\n'


def test_uninstall_never_edits_or_deletes_a_symlinked_shared_file(tmp_path):
    from skill.install import uninstall

    store, project = _setup_store_and_project(tmp_path)
    canonical = '# c\n<!-- skill:greet -->\nx\n<!-- /skill:greet -->\n'
    (project / 'AGENTS.md').write_text(canonical)
    (project / 'GEMINI.md').symlink_to('AGENTS.md')
    kw = dict(agent_targets=['gemini-md'], scope='project', project_dir=project, store=store)
    with pytest.warns(UserWarning, match='symlink'):
        assert uninstall('alice/greet', **kw) == {}
    assert (project / 'AGENTS.md').read_text() == canonical
    (project / 'GEMINI.md').unlink()
    (project / 'GEMINI.md').symlink_to('NOPE.md')  # dangling
    with pytest.warns(UserWarning, match='symlink'):
        uninstall('alice/greet', **kw)
    assert (project / 'GEMINI.md').is_symlink()
    (project / 'GEMINI.md').unlink()
    (project / 'GEMINI.md').write_text('# mine\n')
    assert uninstall('alice/greet', **kw) == {}  # no section: nothing removed


# -- native SKILL.md folders for the hosts that used to need translation (addaix/skill#24) --


@pytest.mark.parametrize(
    'target, rel',
    [
        ('cursor', '.agents/skills/greet'),
        ('copilot', '.agents/skills/greet'),
        ('gemini', '.agents/skills/greet'),
        ('cline', '.agents/skills/greet'),
        ('windsurf', '.windsurf/skills/greet'),
    ],
)
def test_former_translating_hosts_now_link_the_skill_folder(tmp_path, target, rel):
    store, project = _setup_store_and_project(tmp_path)
    result = install(
        'alice/greet', agent_targets=[target], scope='project',
        project_dir=project, store=store,
    )
    assert result[target] == project / rel
    assert (project / rel / 'SKILL.md').is_file()
    assert not AGENT_TARGETS[target].needs_translation
    assert AGENT_TARGETS[target].global_path  # user-level install is possible now


def test_hosts_sharing_a_folder_install_it_once(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    hosts = ['codex', 'cursor', 'copilot', 'gemini', 'cline']
    result = install(
        'alice/greet', agent_targets=hosts, scope='project', copy=True,
        project_dir=project, store=store,
    )
    assert set(result) == set(hosts)
    assert set(result.values()) == {project / '.agents' / 'skills' / 'greet'}


def test_the_rules_file_translations_stay_reachable():
    for name, fmt in [
        ('cursor-rules', 'mdc'), ('copilot-instructions', 'copilot_md'),
        ('windsurf-rules', 'windsurf_md'), ('cline-rules', 'clinerules_md'),
        ('gemini-md', 'gemini_md'),
    ]:
        assert AGENT_TARGETS[name].needs_translation
        assert AGENT_TARGETS[name].format == fmt


# -- review findings on addaix/skill#24: shared folders, ownership, legacy installs --


def test_uninstall_leaves_a_folder_it_did_not_install(tmp_path):
    from skill.install import uninstall

    store, project = _setup_store_and_project(tmp_path)
    own = project / '.agents' / 'skills' / 'greet'
    own.mkdir(parents=True)
    (own / 'SKILL.md').write_text('---\nname: greet\ndescription: mine\n---\nhand-written\n')
    with pytest.warns(UserWarning, match='not an installation'):
        removed = uninstall(
            'alice/greet', agent_targets=['gemini'], scope='project',
            project_dir=project, store=store,
        )
    assert removed == {} and (own / 'SKILL.md').is_file()


def test_uninstalling_a_shared_folder_names_the_other_hosts(tmp_path):
    from skill.install import uninstall

    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['codex', 'cursor'], **kw)
    with pytest.warns(UserWarning, match='also removes .* for .*codex'):
        removed = uninstall('alice/greet', agent_targets=['cursor'], **kw)
    assert not removed['cursor'].exists()


def test_a_second_host_reuses_an_earlier_install_of_the_same_skill(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['codex'], copy=True, **kw)
    result = install('alice/greet', agent_targets=['cursor'], **kw)  # no FileExistsError
    assert (result['cursor'] / 'SKILL.md').is_file()


def test_a_leftover_rules_file_install_is_flagged(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['cursor-rules'], **kw)
    with pytest.warns(UserWarning, match="cursor-rules"):
        install('alice/greet', agent_targets=['cursor'], **kw)


def test_every_rules_file_target_names_its_host():
    rules = {n: t for n, t in AGENT_TARGETS.items() if t.needs_translation}
    assert {t.host_name for t in rules.values()} == {
        'cursor', 'copilot', 'windsurf', 'cline', 'gemini'
    }
    assert all(t.host_name in AGENT_TARGETS for t in rules.values())


# -- review findings on addaix/skill#27: a copy is recognised by more than its SKILL.md --


def _store_skill_dir(store):
    return store._key_to_path('alice/greet')


def test_reinstalling_a_copy_refreshes_a_changed_supporting_file(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store, copy=True)
    src = _store_skill_dir(store)
    (src / 'scripts').mkdir()
    (src / 'scripts' / 'run.py').write_text("print('v1')\n")
    install('alice/greet', agent_targets=['cursor'], **kw)
    (src / 'scripts' / 'run.py').write_text("print('v2')\n")  # SKILL.md unchanged
    result = install('alice/greet', agent_targets=['cursor'], **kw)
    assert (result['cursor'] / 'scripts' / 'run.py').read_text() == "print('v2')\n"


def test_an_unmarked_copy_with_other_files_is_not_overwritten_without_force(tmp_path):
    import shutil

    store, project = _setup_store_and_project(tmp_path)
    src = _store_skill_dir(store)
    dest = project / '.agents' / 'skills' / 'greet'
    shutil.copytree(src, dest)  # e.g. made by hand, then edited
    (dest / 'notes.md').write_text('my edits\n')
    kw = dict(scope='project', project_dir=project, store=store, copy=True)
    with pytest.raises(FileExistsError, match='force=True'):
        install('alice/greet', agent_targets=['cursor'], **kw)
    assert (dest / 'notes.md').is_file()


def test_uninstall_removes_its_copy_after_the_store_skill_changed(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['claude-code'], copy=True, **kw)
    src = _store_skill_dir(store)
    (src / 'SKILL.md').write_text(
        (src / 'SKILL.md').read_text().replace('Say hello to the user.', 'Say hi.')
    )
    removed = uninstall('alice/greet', agent_targets=['claude-code'], **kw)
    assert not removed['claude-code'].exists()


def test_uninstall_for_a_host_removes_its_older_rules_file_install(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['cursor-rules'], **kw)
    mdc = project / '.cursor' / 'rules' / 'greet.mdc'
    assert mdc.is_file()
    removed = uninstall('alice/greet', agent_targets=['cursor'], **kw)
    assert removed == {'cursor-rules': mdc} and not mdc.exists()


def test_uninstall_for_a_host_flags_an_edited_rules_file_and_keeps_it(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['cursor-rules'], **kw)
    mdc = project / '.cursor' / 'rules' / 'greet.mdc'
    mdc.write_text(mdc.read_text() + '\nmy own rule\n')
    with pytest.warns(UserWarning, match=r"agent_targets=\['cursor-rules'\]"):
        removed = uninstall('alice/greet', agent_targets=['cursor'], **kw)
    assert removed == {} and mdc.is_file()


def test_uninstall_for_a_host_removes_its_section_of_a_shared_rules_file(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['copilot-instructions'], **kw)
    shared = project / '.github' / 'copilot-instructions.md'
    removed = uninstall('alice/greet', agent_targets=['copilot'], **kw)
    assert removed == {'copilot-instructions': shared}
    assert '<!-- skill:greet -->' not in shared.read_text()


# -- review of the fix: never lose edits, no path in the marker, noise, atomic refresh --


def test_a_copy_edited_since_install_is_not_replaced_or_removed_without_force(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    dest = install('alice/greet', agent_targets=['claude-code'], copy=True, **kw)['claude-code']
    (dest / 'notes.md').write_text('my edits\n')
    with pytest.raises(FileExistsError, match='force=True'):
        install('alice/greet', agent_targets=['claude-code'], copy=True, **kw)
    with pytest.warns(UserWarning, match='not an installation'):
        assert uninstall('alice/greet', agent_targets=['claude-code'], **kw) == {}
    assert (dest / 'notes.md').is_file()


def test_link_skills_keeps_an_edited_copy(tmp_path):
    from skill.install import link_skills

    src = tmp_path / 'src' / 'greet'
    src.mkdir(parents=True)
    (src / 'SKILL.md').write_text('---\nname: greet\ndescription: Say hello. Use when greeting.\n---\nv1\n')
    target = tmp_path / 'target'
    target.mkdir()
    link_skills(str(src.parent), target=str(target), copy=True)
    (target / 'greet' / 'SKILL.md').write_text('edited\n')
    with pytest.raises(FileExistsError):
        link_skills(str(src.parent), target=str(target), copy=True)
    assert (target / 'greet' / 'SKILL.md').read_text() == 'edited\n'


def test_the_marker_holds_no_path(tmp_path):
    import json

    from skill.install import INSTALL_MARKER

    store, project = _setup_store_and_project(tmp_path)
    dest = install('alice/greet', agent_targets=['claude-code'], copy=True,
                   scope='project', project_dir=project, store=store)['claude-code']
    marker = json.loads((dest / INSTALL_MARKER).read_text())
    assert set(marker) == {'key', 'name', 'digest'}
    assert str(tmp_path) not in json.dumps(marker)


def test_build_noise_does_not_make_an_identical_copy_foreign(tmp_path):
    import shutil

    store, project = _setup_store_and_project(tmp_path)
    dest = project / '.agents' / 'skills' / 'greet'
    shutil.copytree(_store_skill_dir(store), dest)
    (dest / '.DS_Store').write_bytes(b'\0')
    (dest / '__pycache__').mkdir()
    install('alice/greet', agent_targets=['codex'], scope='project', project_dir=project, store=store)


def test_a_read_only_source_is_copied_and_marked(tmp_path):
    import stat

    from skill.install import INSTALL_MARKER

    store, project = _setup_store_and_project(tmp_path)
    src = _store_skill_dir(store)
    src.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        dest = install('alice/greet', agent_targets=['claude-code'], copy=True,
                       scope='project', project_dir=project, store=store)['claude-code']
        assert (dest / INSTALL_MARKER).is_file()
        uninstall('alice/greet', agent_targets=['claude-code'], scope='project',
                  project_dir=project, store=store)
        assert not dest.exists()
    finally:
        src.chmod(stat.S_IRWXU)


def test_a_failed_refresh_leaves_the_old_install(tmp_path, monkeypatch):
    import shutil

    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store, copy=True)
    dest = install('alice/greet', agent_targets=['claude-code'], **kw)['claude-code']
    (_store_skill_dir(store) / 'extra.md').write_text('new\n')

    def broken_copytree(*a, **k):
        raise OSError('disk full')

    monkeypatch.setattr(shutil, 'copytree', broken_copytree)
    with pytest.raises(OSError, match='disk full'):
        install('alice/greet', agent_targets=['claude-code'], **kw)
    assert (dest / 'SKILL.md').is_file()
    assert [p.name for p in dest.parent.iterdir()] == ['greet']


def test_a_target_reached_through_a_linked_folder_is_never_the_victim(tmp_path):
    repo = tmp_path / 'repo'
    src = repo / 'skills' / 'greet'
    src.mkdir(parents=True)
    (src / 'SKILL.md').write_text('---\nname: greet\ndescription: d\n---\nbody\n')
    (repo / '.claude').mkdir()
    os.symlink(repo / 'skills', repo / '.claude' / 'skills')
    target = repo / '.claude' / 'skills' / 'greet'
    assert _create_link(src, target, force=True) == target
    assert (src / 'SKILL.md').is_file() and not src.is_symlink()


def test_copy_over_a_link_to_the_source_makes_a_copy(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    dest = install('alice/greet', agent_targets=['claude-code'], **kw)['claude-code']
    assert dest.is_symlink()
    install('alice/greet', agent_targets=['claude-code'], copy=True, **kw)
    assert dest.is_dir() and not dest.is_symlink()


def test_uninstall_keeps_an_unmarked_copy_with_other_files(tmp_path):
    import shutil

    store, project = _setup_store_and_project(tmp_path)
    dest = project / '.agents' / 'skills' / 'greet'
    shutil.copytree(_store_skill_dir(store), dest)
    (dest / 'notes.md').write_text('mine\n')
    with pytest.warns(UserWarning, match='not an installation'):
        uninstall('alice/greet', agent_targets=['codex'], scope='project',
                  project_dir=project, store=store)
    assert (dest / 'notes.md').is_file()


def test_uninstall_keeps_an_edited_section_of_a_shared_rules_file(tmp_path):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['copilot-instructions'], **kw)
    shared = project / '.github' / 'copilot-instructions.md'
    shared.write_text(shared.read_text().replace('<!-- /skill:greet -->', 'team rule\n<!-- /skill:greet -->'))
    with pytest.warns(UserWarning, match='copilot-instructions'):
        assert uninstall('alice/greet', agent_targets=['copilot'], **kw) == {}
    assert 'team rule' in shared.read_text()


def test_naming_both_targets_removes_an_edited_rules_file_without_a_warning(tmp_path, recwarn):
    store, project = _setup_store_and_project(tmp_path)
    kw = dict(scope='project', project_dir=project, store=store)
    install('alice/greet', agent_targets=['cursor-rules'], **kw)
    mdc = project / '.cursor' / 'rules' / 'greet.mdc'
    mdc.write_text(mdc.read_text() + 'edited\n')
    removed = uninstall('alice/greet', agent_targets=['cursor', 'cursor-rules'], **kw)
    assert removed == {'cursor-rules': mdc} and not mdc.exists()
    assert not [w for w in recwarn if 'differs' in str(w.message)]
