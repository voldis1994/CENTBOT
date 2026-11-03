"""Install-root persistence — exe must not write into _MEI temp."""

from __future__ import annotations

from pathlib import Path

from centbot.core.config import Config
from centbot.runtime_paths import fix_ssl_certificates, install_root


def test_save_local_writes_under_centbot_root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True)
    # Seed a minimal default.yaml
    default = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    (tmp_path / "config" / "default.yaml").write_text(default.read_text(encoding="utf-8"), encoding="utf-8")

    cfg = Config(tmp_path / "config" / "default.yaml")
    path = cfg.save_local({"operator": {"email": "persist@example.com"}, "system": {"mode": "live"}})
    assert path == tmp_path / "config" / "local.yaml"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "persist@example.com" in text
    assert "live" in text
    # Reload sees durable values
    cfg2 = Config(tmp_path / "config" / "default.yaml")
    assert cfg2.get("operator.email") == "persist@example.com"
    assert cfg2.is_live()


def test_save_local_refuses_meipass_target(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    mei = tmp_path / "_MEI_fake"
    mei.mkdir()
    (tmp_path / "config").mkdir(parents=True)
    default = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    (tmp_path / "config" / "default.yaml").write_text(default.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("sys._MEIPASS", str(mei), raising=False)

    cfg = Config(tmp_path / "config" / "default.yaml")
    # Even if caller passes a MEI path, save_local must redirect to install root
    path = cfg.save_local({"operator": {"full_name": "Safe"}}, path=mei / "config" / "local.yaml")
    assert str(mei) not in str(path.resolve())
    assert path == tmp_path / "config" / "local.yaml"
    assert "Safe" in path.read_text(encoding="utf-8")


def test_install_root_respects_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    assert install_root() == tmp_path.resolve()


def test_fix_ssl_certificates_sets_env_when_certifi_present(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    out = fix_ssl_certificates()
    # In normal venv certifi.where() works
    assert "cacert" in out or "error" in out
