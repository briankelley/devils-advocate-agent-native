from dvad_agent import secrets


def test_detects_aws_access_key():
    # Synthesize the fixture so secret scanners don't complain about the literal.
    content = "key = " + "AKIA" + "Z" * 16
    matches = secrets.scan(content)
    kinds = {m.pattern_type for m in matches}
    assert "aws_access_key" in kinds


def test_detects_private_key_block():
    content = "prologue\n-----BEGIN RSA PRIVATE KEY-----\nbody\n"
    matches = secrets.scan(content)
    assert any(m.pattern_type == "private_key_block" for m in matches)


def test_detects_stripe_live_key():
    token = "sk_" + "live_" + "a" * 24
    content = f"pay = {token}"
    matches = secrets.scan(content)
    assert any(m.pattern_type == "stripe_live_key" for m in matches)


def test_detects_connection_string_with_password():
    content = "DATABASE_URL=postgresql://user:sup3rsecretpass@db.example.com:5432/prod"
    matches = secrets.scan(content)
    kinds = {m.pattern_type for m in matches}
    assert "db_connection_with_password" in kinds


def test_entropy_gate_suppresses_placeholders():
    # Long but low-entropy template values shouldn't trip the kv heuristic.
    content = "API_KEY=your_api_key_here\nTOKEN=changeme"
    matches = secrets.scan(content)
    assert not any(m.pattern_type == "high_entropy_kv" for m in matches)


def test_high_entropy_kv_matches():
    content = "MY_SECRET_KEY=xQ8vZ12p9Bk7Lm3nRt4yWoEuIaSdFgHj"
    matches = secrets.scan(content)
    assert any(m.pattern_type == "high_entropy_kv" for m in matches)


def test_scan_annotates_channel():
    token = "AKIA" + "Z" * 16
    matches = secrets.scan(token, channel="reference_file:a.py")
    assert all(m.channel == "reference_file:a.py" for m in matches)


def test_line_ranges_are_captured():
    token = "ghp" + "_" + "b" * 36
    content = f"line 1\nline 2\n{token}\n"
    matches = secrets.scan(content)
    pat = next(m for m in matches if m.pattern_type == "github_pat")
    assert pat.approx_line_range == (3, 3)


def test_redact_replaces_matches():
    token = "AKIA" + "Z" * 16
    content = f"key = {token}\n"
    redacted = secrets.redact(content, secrets.scan(content))
    assert token not in redacted
    assert "[REDACTED_" in redacted
