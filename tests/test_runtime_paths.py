"""Install-root persistence — exe must not write into _MEI temp."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import certifi

from centbot.core.config import Config
from centbot.platforms.http import HttpClient
from centbot.runtime_paths import fix_ssl_certificates, install_root, ssl_verify_path


def test_save_local_writes_under_centbot_root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True)
    default = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    (tmp_path / "config" / "default.yaml").write_text(default.read_text(encoding="utf-8"), encoding="utf-8")

    cfg = Config(tmp_path / "config" / "default.yaml")
    path = cfg.save_local({"operator": {"email": "persist@example.com"}, "system": {"mode": "live"}})
    assert path == tmp_path / "config" / "local.yaml"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "persist@example.com" in text
    assert "live" in text
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
    monkeypatch.setattr(sys, "_MEIPASS", str(mei), raising=False)

    cfg = Config(tmp_path / "config" / "default.yaml")
    path = cfg.save_local({"operator": {"full_name": "Safe"}}, path=mei / "config" / "local.yaml")
    assert str(mei) not in str(path.resolve())
    assert path == tmp_path / "config" / "local.yaml"
    assert "Safe" in path.read_text(encoding="utf-8")


def test_install_root_respects_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    assert install_root() == tmp_path.resolve()


def test_fix_ssl_certificates_sets_env_when_certifi_present(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    # Reset module cache so durable path is recomputed for tmp root
    import centbot.runtime_paths as rp

    monkeypatch.setattr(rp, "_SSL_VERIFY", None)
    out = fix_ssl_certificates()
    assert "cacert" in out
    path = Path(out["cacert"])
    assert path.is_file()
    assert path.stat().st_size > 10_000
    assert path == tmp_path / "certs" / "cacert.pem"
    assert Path(os.environ["SSL_CERT_FILE"]) == path


def test_ssl_survives_broken_certifi_where(tmp_path: Path, monkeypatch):
    """Simulate PyInstaller: certifi.where() points at missing _MEI path."""
    import centbot.runtime_paths as rp

    monkeypatch.setenv("CENTBOT_ROOT", str(tmp_path))
    monkeypatch.setattr(rp, "_SSL_VERIFY", None)
    broken = tmp_path / "_MEI_fake" / "certifi" / "cacert.pem"
    monkeypatch.setattr(certifi, "where", lambda: str(broken))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI_fake"), raising=False)

    out = fix_ssl_certificates()
    assert "cacert" in out
    assert Path(out["cacert"]).is_file()
    assert certifi.where() == out["cacert"]
    assert Path(str(ssl_verify_path())).is_file()

    client = HttpClient("https://example.com")
    assert Path(str(client.session.verify)).is_file()


def test_vendored_cacert_exists_in_repo():
    root = Path(__file__).resolve().parents[1]
    pem = root / "centbot" / "certs" / "cacert.pem"
    assert pem.is_file()
    assert pem.stat().st_size > 10_000


def test_emulator_status_label_when_enabled_without_devices():
    from centbot.android.emulator import EmulatorManager

    emu = EmulatorManager(enabled=True, max_emulators=4)
    st = emu.status()
    assert st["enabled"] is True
    assert st["label"].startswith("ON")
    assert "running" in st and "available" in st
