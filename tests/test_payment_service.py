from app.services.admin_settings_service import AdminSettingValidationError, normalize_admin_setting_value
from app.services.payment_service import format_package_prices, parse_package_prices


def test_package_prices_roundtrip_sorted() -> None:
    packages = parse_package_prices("10:1600000,1:220000,5:900000")
    assert packages == [(1, 220000), (5, 900000), (10, 1600000)]
    assert format_package_prices(packages) == "1:220000,5:900000,10:1600000"


def test_admin_boolean_setting_normalization() -> None:
    assert normalize_admin_setting_value("card_reference_required", "on") == "1"
    assert normalize_admin_setting_value("card_reference_required", "0") == "0"
    assert normalize_admin_setting_value("trial_enabled", "off") == "0"
    assert normalize_admin_setting_value("trial_enabled", "enabled") == "1"


def test_admin_ltc_bonus_allows_zero() -> None:
    assert normalize_admin_setting_value("crypto_ltc_bonus_percent", "0") == "0"
    assert normalize_admin_setting_value("crypto_ltc_bonus_percent", "10") == "10"


def test_admin_boolean_setting_rejects_invalid_value() -> None:
    try:
        normalize_admin_setting_value("trial_enabled", "maybe")
    except AdminSettingValidationError as exc:
        assert str(exc) == "invalid_boolean_value"
    else:
        raise AssertionError("Expected AdminSettingValidationError")
