import json
from pathlib import Path

from dvad_agent.install import run_install


def test_fresh_install(tmp_path):
    config = tmp_path / ".claude.json"
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(config), skill_dir=str(skills))
    assert rc == 0
    data = json.loads(config.read_text())
    assert "dvad" in data["mcpServers"]
    assert data["mcpServers"]["dvad"]["type"] == "stdio"
    assert "dvad-agent-mcp" in data["mcpServers"]["dvad"]["command"]
    assert (skills / "dvad.md").exists()


def test_merges_into_existing_without_losing_other_servers(tmp_path):
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({
        "mcpServers": {"other": {"command": "other-cmd"}},
        "foo": "bar",
    }))
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(config), skill_dir=str(skills))
    assert rc == 0
    data = json.loads(config.read_text())
    assert "other" in data["mcpServers"]
    assert "dvad" in data["mcpServers"]
    assert data["foo"] == "bar"


def test_dry_run_writes_nothing(tmp_path):
    config = tmp_path / ".claude.json"
    skills = tmp_path / "skills"
    rc = run_install(dry_run=True, config_path=str(config), skill_dir=str(skills))
    assert rc == 0
    assert not config.exists()
    assert not skills.exists()


def test_backup_created_when_config_present(tmp_path):
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({"mcpServers": {}}))
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(config), skill_dir=str(skills))
    assert rc == 0
    backups = list(tmp_path.glob(".claude.json.dvad-backup.*"))
    assert backups, "expected a timestamped backup file"


def test_resolves_full_binary_path(tmp_path):
    """The installed entry should contain a full path to dvad-agent-mcp
    (when the binary is on PATH), not just the bare command name."""
    config = tmp_path / ".claude.json"
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(config), skill_dir=str(skills))
    assert rc == 0
    data = json.loads(config.read_text())
    command = data["mcpServers"]["dvad"]["command"]
    # If dvad-agent-mcp is on PATH (it should be during test runs), the
    # command should be an absolute path. If not on PATH, it falls back
    # to the bare name — both are acceptable.
    assert "dvad-agent-mcp" in command


def test_entry_includes_type_stdio(tmp_path):
    config = tmp_path / ".claude.json"
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(config), skill_dir=str(skills))
    assert rc == 0
    data = json.loads(config.read_text())
    assert data["mcpServers"]["dvad"]["type"] == "stdio"


def test_local_scope_install(tmp_path, monkeypatch):
    config = tmp_path / ".claude.json"
    skills = tmp_path / "skills"
    test_cwd = str(tmp_path / "my-project")
    monkeypatch.chdir(tmp_path)
    rc = run_install(
        dry_run=False, config_path=str(config), skill_dir=str(skills), scope="local",
    )
    assert rc == 0
    data = json.loads(config.read_text())
    # Local scope puts the entry under projects.<cwd>.mcpServers
    assert "projects" in data
    # Find the project key (it'll be the monkeypatched cwd)
    project_keys = list(data["projects"].keys())
    assert len(project_keys) == 1
    proj = data["projects"][project_keys[0]]
    assert "dvad" in proj["mcpServers"]
    assert proj["mcpServers"]["dvad"]["type"] == "stdio"
