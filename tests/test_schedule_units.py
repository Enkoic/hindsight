"""Schedule-unit text generation. We don't actually load anything into launchd/systemd,
just verify the unit files we'd write are syntactically reasonable."""

from hindsight import schedule


def test_macos_plist_contains_label_and_calendar():
    p = schedule._plist_xml(hour=23, minute=15, targets="markdown,obsidian")
    assert f"<string>{schedule.LABEL}</string>" in p
    assert "<key>Hour</key><integer>23</integer>" in p
    assert "<key>Minute</key><integer>15</integer>" in p
    assert "markdown,obsidian" in p
    assert "<array>" in p and "</array>" in p


def test_linux_service_unit_exec_start():
    unit = schedule._service_unit(targets="markdown,obsidian")
    assert "[Service]" in unit
    assert "ExecStart=" in unit
    assert "run --day yesterday --targets markdown,obsidian" in unit
    assert "[Install]" in unit
    assert "WantedBy=default.target" in unit


def test_linux_timer_oncalendar_pads_zero():
    unit = schedule._timer_unit(hour=9, minute=5)
    assert "OnCalendar=*-*-* 09:05:00" in unit
    assert "Unit=hindsight.service" in unit
    assert "Persistent=true" in unit
