from decimal import Decimal

from app.bot.handlers.capture import EXPENSE_RE, _tx_fingerprint


def test_expense_regex_basic():
    match = EXPENSE_RE.match("149 biedronka")
    assert match is not None
    assert match.group(1) == "149"
    assert match.group(2) == "biedronka"


def test_expense_regex_with_decimals():
    match = EXPENSE_RE.match("12.50 supermarket")
    assert match is not None
    assert match.group(1) == "12.50"


def test_expense_regex_with_comma_decimal():
    match = EXPENSE_RE.match("12,50 supermarket")
    assert match is not None
    assert match.group(1) == "12,50"


def test_expense_regex_rejects_no_merchant():
    match = EXPENSE_RE.match("149")
    assert match is None


def test_expense_regex_rejects_single_char_merchant():
    match = EXPENSE_RE.match("149 a")
    assert match is None


def test_expense_regex_rejects_text_only():
    match = EXPENSE_RE.match("hello world")
    assert match is None


def test_fingerprint_deterministic():
    fp1 = _tx_fingerprint("h1", Decimal("100"), "shop")
    fp2 = _tx_fingerprint("h1", Decimal("100"), "shop")
    assert fp1 == fp2


def test_fingerprint_differs_by_amount():
    fp1 = _tx_fingerprint("h1", Decimal("100"), "shop")
    fp2 = _tx_fingerprint("h1", Decimal("200"), "shop")
    assert fp1 != fp2
