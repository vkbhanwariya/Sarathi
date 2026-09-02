"""Tests for Contracts 3 & 4: Validity, Expiration, and Capacity Policies."""

from sarathi.smriti.policy import CachePolicy


def test_ttl_validity_rule() -> None:
    policy = CachePolicy(ttl_seconds=100)

    # Valid within TTL window
    assert policy.is_valid(created_at=1000.0, current_time=1050.0) is True

    # Expired past TTL window
    assert policy.is_valid(created_at=1000.0, current_time=1101.0) is False


def test_unlimited_ttl() -> None:
    policy = CachePolicy(ttl_seconds=None)
    assert policy.is_valid(created_at=1000.0, current_time=999999.0) is True
