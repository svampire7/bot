from app.db.models import VPNService
from app.services.traffic_alert_service import traffic_alerts_due


def service(**changes) -> VPNService:
    values = {
        "user_id": 1,
        "marzban_username": "tg_1_1",
        "data_limit_gb": 10,
        "remaining_traffic_gb": 10,
        "low_traffic_alert_sent": False,
        "traffic_depleted_alert_sent": False,
    }
    values.update(changes)
    return VPNService(**values)


def test_low_traffic_alert_fires_once_at_80_percent_used() -> None:
    assert traffic_alerts_due(service(remaining_traffic_gb=2)).low_traffic
    assert not traffic_alerts_due(
        service(remaining_traffic_gb=2, low_traffic_alert_sent=True)
    ).low_traffic


def test_depleted_alert_wins_over_late_low_traffic_alert() -> None:
    due = traffic_alerts_due(service(remaining_traffic_gb=0))
    assert due.depleted
    assert not due.low_traffic


def test_depleted_alert_fires_only_once() -> None:
    assert not traffic_alerts_due(
        service(remaining_traffic_gb=0, traffic_depleted_alert_sent=True)
    ).depleted
