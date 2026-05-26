from __future__ import annotations

from app.services.payment_service import (
    format_package_prices,
    format_unlimited_time_packages,
    parse_package_prices,
    parse_unlimited_time_packages,
)
from app.utils.validators import parse_positive_int


NUMERIC_SETTING_KEYS = {
    "price_per_gb_toman",
    "min_custom_gb",
    "max_custom_gb",
    "ltc_toman_rate",
    "referral_bonus_gb",
    "price_per_gb_reseller",
    "min_reseller_bulk_gb",
}

NON_NEGATIVE_NUMERIC_SETTING_KEYS = {"crypto_ltc_bonus_percent"}

BOOLEAN_SETTING_KEYS = {"card_reference_required", "trial_enabled"}

BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


class AdminSettingValidationError(ValueError):
    pass


def normalize_admin_setting_value(key: str, raw_value: str) -> str:
    value = raw_value.strip()
    if key in NUMERIC_SETTING_KEYS:
        if parse_positive_int(value) is None:
            raise AdminSettingValidationError("invalid_value")
        return value
    if key in NON_NEGATIVE_NUMERIC_SETTING_KEYS:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise AdminSettingValidationError("invalid_value") from exc
        if parsed < 0:
            raise AdminSettingValidationError("invalid_value")
        return str(parsed)
    if key in BOOLEAN_SETTING_KEYS:
        normalized = value.lower()
        if normalized in BOOLEAN_TRUE_VALUES:
            return "1"
        if normalized in BOOLEAN_FALSE_VALUES:
            return "0"
        raise AdminSettingValidationError("invalid_boolean_value")
    if key == "package_prices_toman":
        try:
            return format_package_prices(parse_package_prices(value))
        except ValueError as exc:
            raise AdminSettingValidationError("invalid_package_prices") from exc
    if key == "unlimited_time_packages_toman":
        try:
            return format_unlimited_time_packages(parse_unlimited_time_packages(value))
        except ValueError as exc:
            raise AdminSettingValidationError("invalid_unlimited_time_packages") from exc
    return value
