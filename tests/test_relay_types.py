import pytest

from resilientdns.relay_types import (
    RelayConfig,
    RelayDnsResponse,
    RelayLimits,
    validate_base_url,
    validate_limits,
)


def test_relay_urls_strip_trailing_slash():
    cfg = RelayConfig(base_url="https://x")
    assert cfg.info_url == "https://x/v1/info"
    assert cfg.dns_url == "https://x/v1/dns"

    cfg = RelayConfig(base_url="https://x/")
    assert cfg.info_url == "https://x/v1/info"
    assert cfg.dns_url == "https://x/v1/dns"


def test_relay_urls_with_prefix():
    cfg = RelayConfig(base_url="https://x/prefix/", api_version=2)
    assert cfg.info_url == "https://x/prefix/v2/info"
    assert cfg.dns_url == "https://x/prefix/v2/dns"


def test_validate_base_url_requires_scheme():
    with pytest.raises(ValueError, match="relay_base_url"):
        validate_base_url("example.com")


def test_validate_limits_rejects_non_positive():
    limits = RelayLimits(max_items=0)
    with pytest.raises(ValueError, match="max_items"):
        validate_limits(limits)


def test_relay_response_missing_fields():
    with pytest.raises(ValueError, match="missing field"):
        RelayDnsResponse.from_dict({})


def test_relay_response_ok_requires_payload():
    data = {"v": 1, "id": "req", "items": [{"id": "a", "ok": True}]}
    with pytest.raises(ValueError, match="ok item"):
        RelayDnsResponse.from_dict(data)


def test_relay_response_err_requires_error():
    data = {"v": 1, "id": "req", "items": [{"id": "a", "ok": False}]}
    with pytest.raises(ValueError, match="error item"):
        RelayDnsResponse.from_dict(data)
