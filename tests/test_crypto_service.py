from decimal import Decimal

from app.services.crypto_service import (
    crypto_bonus_amount,
    crypto_credit_amount,
    parse_ltc_toman_rate,
    toman_to_ltc,
)


def test_toman_to_ltc_rounds_up_to_satoshi() -> None:
    assert toman_to_ltc(100_000, 7_000_000) == Decimal("0.01428572")


def test_parse_ltc_toman_rate_from_coingecko_irr() -> None:
    assert parse_ltc_toman_rate({"litecoin": {"irr": 70_000_000}}) == 7_000_000


def test_parse_ltc_toman_rate_from_wallex() -> None:
    assert (
        parse_ltc_toman_rate(
            {"result": {"symbols": {"LTCTMN": {"stats": {"lastPrice": "9582366.0000000000000000"}}}}}
        )
        == 9_582_366
    )


def test_parse_ltc_toman_rate_from_custom_toman() -> None:
    assert parse_ltc_toman_rate({"toman": 7_000_000}) == 7_000_000


def test_crypto_bonus_credit_amount() -> None:
    assert crypto_bonus_amount(900_000, 10) == 90_000
    assert crypto_credit_amount(900_000, 10) == 990_000
