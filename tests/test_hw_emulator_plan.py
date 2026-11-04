"""RAM-aware emulator count — free RAM must cap AVD launches."""

from __future__ import annotations

from centbot.windows.avd import plan_emulator_count
from centbot.windows.hwcheck import recommended_emulator_count


def test_recommended_uses_available_ram():
    # 16 GB total would allow 4, but 1.5 GB free allows 0
    assert recommended_emulator_count(16, 8, available_gb=1.5) == 0
    assert recommended_emulator_count(16, 8, available_gb=3.0) == 1
    assert recommended_emulator_count(16, 8, available_gb=5.0) == 2
    assert recommended_emulator_count(15.5, 14, available_gb=12.0) == 3
    # Without available_gb, keep total-RAM behaviour
    assert recommended_emulator_count(15.5, 14) == 3


def test_plan_emulator_count_includes_message(monkeypatch):
    fake_hw = {
        "ram": {"total_gb": 15.5, "available_gb": 1.52},
        "cpu": {"physical_cores": 14},
        "disk": {"free_gb": 80},
        "blockers": [],
    }
    monkeypatch.setattr("centbot.windows.avd.full_hw_report", lambda: fake_hw)
    plan = plan_emulator_count()
    assert plan["recommended"] == 0
    assert plan["names"] == []
    assert "RAM" in (plan.get("message") or "") or "RAM" in (plan.get("reason") or "")
