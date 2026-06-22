from datetime import datetime, date
from logger import logger
from typing import List, Dict, Any, Optional

try:
    from gurux_dlms.GXDateTime import GXDateTime
except ImportError:
    GXDateTime = None

try:
    from gurux_dlms.GXDate import GXDate
except ImportError:
    GXDate = None

try:
    from gurux_dlms.GXTime import GXTime
except ImportError:
    GXTime = None


def _normalize_value(value):
    """
    Convert gurux-specific types to plain Python primitives so records
    are JSON-serialisable and human-readable.

    Handles:
      - GXDateTime  → ISO-8601 string  e.g. "2024-09-17T14:30:00"
      - GXDate      → ISO date string  e.g. "2024-09-17"
      - GXTime      → time string      e.g. "14:30:00"
      - datetime    → ISO-8601 string
      - date        → ISO date string
      - bytearray / bytes → hex string e.g. "0A1B2C"
      - everything else → returned as-is (int, float, str, None, ...)
    """
    # GXDateTime — most common culprit in billing/LSD timestamps
    if GXDateTime and isinstance(value, GXDateTime):
        try:
            # GXDateTime.value is a Python datetime when parseable
            dt = value.value
            if isinstance(dt, datetime):
                return dt.isoformat()
            # Fallback: str() gives a human-readable representation
            return str(value)
        except Exception:
            return str(value)

    if GXDate and isinstance(value, GXDate):
        try:
            return value.value.isoformat() if hasattr(value, "value") else str(value)
        except Exception:
            return str(value)

    if GXTime and isinstance(value, GXTime):
        try:
            return str(value.value) if hasattr(value, "value") else str(value)
        except Exception:
            return str(value)

    # Standard Python datetime types
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    # Raw bytes returned for some OBIS registers
    if isinstance(value, (bytearray, bytes)):
        return value.hex().upper()

    return value


def _extract_headers(columns):  # type: (List[List[Any]]) -> List[str]
    """
    Flatten the column descriptor list returned by attribute-3 reads and
    return only the OBIS/name tokens (every other item).
    """
    flat = []
    for col in columns:
        for data in col:
            flat.append(str(data).split()[0])
    return [v for i, v in enumerate(flat) if i % 2 == 0]


def _rows_to_records(rows, headers, sn, obis):  # type: (List[List[Any]], List[str], str, str) -> List[Dict[str, Any]]

    """
    Convert raw row lists into a list of dicts keyed by header name.
    Always includes 'serial_number' and 'obis' fields.
    All values are passed through _normalize_value so the result is
    JSON-serialisable with no gurux objects left inside.
    """
    records = []
    for row in rows:
        record = {"serial_number": sn, "obis": obis}
        for idx, value in enumerate(row):
            key = headers[idx] if idx < len(headers) else "col_{}".format(idx)
            record[key] = _normalize_value(value)
        records.append(record)
    return records


def _safe_close(reader, settings):
    """Best-effort cleanup — never raises."""
    for target, label in [(reader, "reader"), (settings.media, "media")]:
        if target:
            try:
                target.close()
            except Exception as ex:
                logger.warning("Error closing {}: {}".format(label, ex), to_file=True)