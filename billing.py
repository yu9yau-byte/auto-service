"""VAT and line-total calculations (single source of truth)."""
from constants import VAT_MULTIPLIER


def split_unit_price_with_vat(price_with_vat: float) -> tuple[float, float, float]:
    """Per-unit: (price_without_vat, vat_amount, price_with_vat)."""
    price_with_vat = float(price_with_vat or 0)
    price_without_vat = round(price_with_vat / VAT_MULTIPLIER, 2)
    vat_amount = round(price_with_vat - price_without_vat, 2)
    return price_without_vat, vat_amount, price_with_vat


def line_totals_with_vat(price_with_vat: float, quantity: int) -> tuple[float, float, float]:
    """Line: (subtotal_without_vat, vat_total, subtotal_with_vat)."""
    qty = max(int(quantity or 1), 1)
    price_without_vat, vat_amount, unit_with_vat = split_unit_price_with_vat(price_with_vat)
    subtotal_without_vat = round(price_without_vat * qty, 2)
    subtotal_with_vat = round(unit_with_vat * qty, 2)
    vat_total = round(vat_amount * qty, 2)
    # Align gross with net + vat when rounding drifts
    if abs(subtotal_with_vat - (subtotal_without_vat + vat_total)) > 0.01:
        vat_total = round(subtotal_with_vat - subtotal_without_vat, 2)
    return subtotal_without_vat, vat_total, subtotal_with_vat
