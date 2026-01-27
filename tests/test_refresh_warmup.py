from dnslib import CLASS

from resilientdns.refresh_warmup import parse_warmup_source


def test_parses_valid_lines_and_ignores_comments():
    text = """
    # comment

    example.com A
    example.net\tAAAA
    """
    items, invalid = parse_warmup_source(text)
    assert invalid == 0
    assert items == [
        ("example.com", 1, CLASS.IN),
        ("example.net", 28, CLASS.IN),
    ]


def test_handles_extra_whitespace():
    text = "   Example.COM   A   "
    items, invalid = parse_warmup_source(text)
    assert invalid == 0
    assert items == [("example.com", 1, CLASS.IN)]


def test_counts_invalid_lines():
    text = """
    example.com
    example.com INVALIDTYPE
    example.com A IN
    """
    items, invalid = parse_warmup_source(text)
    assert items == []
    assert invalid == 3


def test_qclass_defaults_to_in():
    text = "example.com A"
    items, invalid = parse_warmup_source(text)
    assert invalid == 0
    assert items[0][2] == CLASS.IN
