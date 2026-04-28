from pathlib import Path

from hindsight.redact import DEFAULT_RULES, build_rules, load_user_rules, redact


def test_redacts_anthropic_key():
    text = "use sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCDEFGH for that"
    out, hits = redact(text)
    assert "<ANTHROPIC_KEY>" in out
    assert "sk-ant-" not in out
    assert hits == {"anthropic_key": 1}


def test_redacts_ark_and_openai_and_github():
    # Synthetic credentials only — never put real keys in test fixtures.
    text = (
        "ARK=ark-00000000-1111-2222-3333-444444444444-aaaaa "
        "OAI=sk-proj-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
        "GH=ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"
    )
    out, hits = redact(text)
    assert "ark-" not in out
    assert "sk-proj-" not in out and "<OPENAI_KEY>" in out
    assert "ghp_" not in out
    assert hits["ark_key"] == 1
    assert hits["openai_key"] == 1
    assert hits["gh_token"] == 1


def test_redacts_email_and_private_ip():
    text = "ping me at user.name@example.com or ssh into 192.168.1.42"
    out, hits = redact(text)
    assert "<EMAIL>" in out and "@example.com" not in out
    assert "<PRIVATE_IP>" in out
    assert hits["email"] == 1
    assert hits["private_ipv4"] == 1


def test_does_not_touch_public_ipv4():
    """8.8.8.8 should pass through; only RFC1918 is redacted."""
    out, hits = redact("dns at 8.8.8.8")
    assert "8.8.8.8" in out
    assert "private_ipv4" not in hits


def test_jwt_and_bearer_redaction():
    jwt = "eyJabcdefgh.eyJpYXQiOjE2OTkwMDAwMDB9.signature_abc_def_ghi"
    text = f"Authorization: Bearer {jwt} should disappear"
    out, hits = redact(text)
    assert "Authorization: Bearer <REDACTED>" in out or "<JWT>" in out
    assert any(k in hits for k in ("bearer_header", "jwt"))


def test_sshpass_redaction():
    out, hits = redact("sshpass -p hunter2 ssh me@server.example")
    assert "sshpass -p <REDACTED>" in out
    assert hits["sshpass"] == 1


def test_user_rule_file(tmp_path: Path):
    rules_file = tmp_path / "rules.tsv"
    rules_file.write_text(
        "# comment\nproject_codename\\tProject Apollo\\t<PROJECT>\n".replace("\\t", "\t"),
        encoding="utf-8",
    )
    rules = build_rules(rules_file)
    out, hits = redact("Internal name: Project Apollo is shipping", rules)
    assert "<PROJECT>" in out
    assert hits["project_codename"] == 1


def test_invalid_user_rule_silently_skipped(tmp_path: Path):
    rules_file = tmp_path / "rules.tsv"
    rules_file.write_text("bad\t[unclosed\tX\nok\thello\t<HI>\n", encoding="utf-8")
    rules = load_user_rules(rules_file)
    assert len(rules) == 1
    assert rules[0].name == "ok"


def test_no_rules_means_no_changes():
    out, hits = redact("nothing to redact here", [])
    assert out == "nothing to redact here"
    assert hits == {}


def test_default_rule_set_is_non_empty():
    assert len(DEFAULT_RULES) >= 8
    assert all(r.placeholder for r in DEFAULT_RULES)
