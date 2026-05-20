from app.utils.validators import parse_toman_amount


def test_parse_toman_amount_accepts_full_amount() -> None:
    assert parse_toman_amount("480000") == 480000
    assert parse_toman_amount("480,000") == 480000


def test_parse_toman_amount_expands_thousand_shorthand() -> None:
    assert parse_toman_amount("480") == 480000


def test_parse_toman_amount_rejects_invalid_values() -> None:
    assert parse_toman_amount("0") is None
    assert parse_toman_amount("-1") is None
    assert parse_toman_amount("abc") is None
