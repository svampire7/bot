from app.db.models import User
from app.services.vpn_service import first_referral_bonus_allowed


def referred_user(**changes) -> User:
    values = {
        "telegram_id": 1001,
        "referred_by_user_id": 7,
        "referral_bonus_awarded": False,
    }
    values.update(changes)
    return User(**values)


def test_first_referral_bonus_allows_only_first_unawarded_purchase() -> None:
    assert first_referral_bonus_allowed(referred_user(), completed_before=0)


def test_first_referral_bonus_rejects_repeat_purchase() -> None:
    assert not first_referral_bonus_allowed(referred_user(), completed_before=1)


def test_first_referral_bonus_rejects_already_awarded_or_unreferred_user() -> None:
    assert not first_referral_bonus_allowed(
        referred_user(referral_bonus_awarded=True), completed_before=0
    )
    assert not first_referral_bonus_allowed(
        referred_user(referred_by_user_id=None), completed_before=0
    )
