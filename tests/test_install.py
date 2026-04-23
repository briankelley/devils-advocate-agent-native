import json
from pathlib import Path

from dvad_agent.install import run_install


def test_fresh_install(tmp_path):
    settings = tmp_path / "settings.json"
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(settings), skill_dir=str(skills))
    assert rc == 0
    data = json.loads(settings.read_text())
    assert data["mcpServers"]["dvad"]["command"] == "dvad-agent-mcp"
    assert (skills / "dvad.md").exists()


def test_merges_into_existing_without_losing_other_servers(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "mcpServers": {"other": {"command": "other-cmd"}},
        "foo": "bar",
    }))
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(settings), skill_dir=str(skills))
    assert rc == 0
    data = json.loads(settings.read_text())
    assert "other" in data["mcpServers"]
    assert "dvad" in data["mcpServers"]
    assert data["foo"] == "bar"


def test_dry_run_writes_nothing(tmp_path):
    settings = tmp_path / "settings.json"
    skills = tmp_path / "skills"
    rc = run_install(dry_run=True, config_path=str(settings), skill_dir=str(skills))
    assert rc == 0
    assert not settings.exists()
    assert not skills.exists()


def test_backup_created_when_settings_present(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"mcpServers": {}}))
    skills = tmp_path / "skills"
    rc = run_install(dry_run=False, config_path=str(settings), skill_dir=str(skills))
    assert rc == 0
    backups = list(tmp_path.glob("settings.json.dvad-backup.*"))
    assert backups, "expected a timestamped backup file"
