"""USD limit validation shared by the worker budget and preflight."""
from decimal import Decimal, InvalidOperation

NANO = 1_000_000_000


def amount_nano(value) -> int:
    try:
        amount = Decimal(str(value)) * NANO
    except (InvalidOperation, ValueError):
        raise ValueError("invalid USD limit") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("USD limit must be positive with at most 9 decimals")
    return int(amount)
