import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

_CURRENCY_PREFIX = re.compile(r"^(?:[$€£₱]|PHP\s*)", re.IGNORECASE)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")


@dataclass(frozen=True)
class DateParseResult:
    value: datetime | None
    format_name: str | None
    ambiguous: bool = False


def parse_decimal(value: str, *, currency: bool = False) -> Decimal | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    negative_parentheses = cleaned.startswith("(") and cleaned.endswith(")")
    if negative_parentheses:
        cleaned = cleaned[1:-1].strip()
    if currency:
        cleaned = _CURRENCY_PREFIX.sub("", cleaned).strip()
    cleaned = cleaned.replace(",", "")
    if not _NUMBER.fullmatch(cleaned):
        return None
    try:
        result = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -result if negative_parentheses else result


def parse_date(value: str) -> DateParseResult:
    cleaned = value.strip()
    if not cleaned:
        return DateParseResult(None, None)
    iso_value = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_value)
        return DateParseResult(parsed, "ISO-8601" if "T" in cleaned else "%Y-%m-%d")
    except ValueError:
        pass
    slash_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    if slash_match:
        first, second = int(slash_match.group(1)), int(slash_match.group(2))
        if first <= 12 and second <= 12:
            return DateParseResult(None, None, ambiguous=True)
        format_name = "%d/%m/%Y" if first > 12 else "%m/%d/%Y"
        try:
            return DateParseResult(datetime.strptime(cleaned, format_name), format_name)
        except ValueError:
            return DateParseResult(None, None)
    for format_name in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return DateParseResult(datetime.strptime(cleaned, format_name), format_name)
        except ValueError:
            continue
    return DateParseResult(None, None)
