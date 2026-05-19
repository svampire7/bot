import pytest

from app.services.bulk_service import BulkPlanError, BulkPlanItem, parse_bulk_plan


def test_parse_bulk_plan_accepts_x_and_spaces() -> None:
    assert parse_bulk_plan("10x3\n3 x 5\n2 1") == [
        BulkPlanItem(quantity=10, gb=3),
        BulkPlanItem(quantity=3, gb=5),
        BulkPlanItem(quantity=2, gb=1),
    ]


def test_parse_bulk_plan_rejects_empty_or_too_large() -> None:
    with pytest.raises(BulkPlanError):
        parse_bulk_plan("")
    with pytest.raises(BulkPlanError):
        parse_bulk_plan("201x1", max_accounts=200)
