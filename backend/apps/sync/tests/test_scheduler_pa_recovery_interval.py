from apps.sync.management.commands.runapscheduler import (
    PA_MISSED_ORDER_RECOVERY_INTERVAL,
)


def test_playerauctions_missed_order_recovery_runs_every_fifteen_minutes():
    assert PA_MISSED_ORDER_RECOVERY_INTERVAL == 15
