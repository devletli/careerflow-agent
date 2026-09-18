import pytest
from shared.infra.redis_bus import calculate_backoff


def test_calculate_backoff_progression():
    b0 = calculate_backoff(0, base_delay=1.0, factor=2.0)
    b1 = calculate_backoff(1, base_delay=1.0, factor=2.0)
    b2 = calculate_backoff(2, base_delay=1.0, factor=2.0)
    b3 = calculate_backoff(3, base_delay=1.0, factor=2.0)

    assert b0 == 1.0
    assert b1 == 2.0
    assert b2 == 4.0
    assert b3 == 8.0


def test_calculate_backoff_max_capping():
    # Large retry count should be capped at max_delay
    b_large = calculate_backoff(10, base_delay=1.0, max_delay=30.0, factor=2.0)
    assert b_large == 30.0
