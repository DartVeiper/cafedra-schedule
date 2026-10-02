from app.parsers.common import normalize_room, normalize_room_display


def test_room_display_drops_excel_float_suffix():
    """Excel (.xls) отдаёт номер кабинета числом 421.0 — в отчёте должно быть '421'."""
    assert normalize_room_display(421.0) == "421"
    assert normalize_room_display("421.0") == "421"
    assert normalize_room_display("м/ф") == "м/ф"
    assert normalize_room_display("") is None
    assert normalize_room_display(None) is None


def test_room_normalization_ignores_aud_prefix_and_home_building():
    assert normalize_room("ауд. 316", building="5") == "316"
    assert normalize_room("ауд.316") == "316"
    assert normalize_room("ауд. 4.27", building="3") == "3:4.27"
