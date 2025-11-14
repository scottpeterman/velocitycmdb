#!/usr/bin/env python3
"""
TextFSM row -> sane dict with correct handling of embedded lists
- Always keep HARDWARE and SERIAL as lists (critical for switch stacks)
- Preserve order, drop empties, dedupe safely (no comprehensions)
- Build STACK_MEMBERS [{index, model, serial}] for stack-aware consumers
"""

from typing import Any, Dict, List, Optional, Tuple, Set
import json

HEADERS = ['SOFTWARE_IMAGE', 'VERSION', 'RELEASE', 'ROMMON', 'HOSTNAME', 'UPTIME',
           'UPTIME_YEARS', 'UPTIME_WEEKS', 'UPTIME_DAYS', 'UPTIME_HOURS', 'UPTIME_MINUTES',
           'RELOAD_REASON', 'RUNNING_IMAGE', 'HARDWARE', 'SERIAL', 'CONFIG_REGISTER',
           'MAC_ADDRESS', 'RESTARTED']

# Example with multiple hardware/serials to show stack handling
ROW = ['CAT9K_IOSXE', '17.9.6a', 'fc1', 'IOS-XE', 'cal-cr-core-01',
       '21 weeks, 18 hours, 32 minutes', '', '21', '', '18', '32',
       'Reload Command', 'cat9k_iosxe.17.09.06a.SPA.bin',
       ['C9407R', 'C9407R'],                         # HARDWARE (stack members or chassis + modules)
       ['FXS2516Q2GW', 'FXS2516Q2GX', 'FXS2516Q2GX'],# SERIAL   (note duplicate last item)
       '', ['6C:13:D5:BB:D2:40', '6c:13:d5:bb:d2:41'], '14:39:27 PDT Tue Apr 22 2025']


def _is_int_string(value: str) -> bool:
    if value is None:
        return False
    try:
        int(value)
        return True
    except Exception:
        return False


def _to_list(value: Any) -> List[Any]:
    """Ensure value is a list; flatten singletons; None/'' -> empty list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if value == "":
        return []
    return [value]


def _dedupe_preserve_order(items: List[Any]) -> List[Any]:
    """Dedupe while preserving order, without comprehensions."""
    seen: Set[Any] = set()
    result: List[Any] = []
    i = 0
    n = len(items)
    while i < n:
        item = items[i]
        if item not in seen:
            result.append(item)
            seen.add(item)
        i += 1
    return result


def _sanitize_scalar_or_list(value: Any, force_list: bool, lowercase: bool = False) -> Any:
    """
    - If force_list=True: always return a cleaned list (drop empties, dedupe, str-cast, optional lowercase)
    - Else: collapse single-item lists to scalar; keep multi-item lists
    """
    items = _to_list(value)

    # normalize each item: cast to str, strip, optional lowercase
    cleaned: List[Any] = []
    i = 0
    while i < len(items):
        v = items[i]
        if v is None:
            i += 1
            continue
        s = str(v).strip()
        if s == "":
            i += 1
            continue
        if lowercase:
            s = s.lower()
        cleaned.append(s)
        i += 1

    cleaned = _dedupe_preserve_order(cleaned)

    if force_list:
        return cleaned

    # not forced: collapse singletons to scalar
    if len(cleaned) == 0:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return cleaned


def _coerce_int_fields(d: Dict[str, Any], keys: List[str]) -> None:
    i = 0
    length = len(keys)
    while i < length:
        k = keys[i]
        v = d.get(k)
        if isinstance(v, str) and _is_int_string(v):
            d[k] = int(v)
        i += 1


def _compute_uptime_minutes(d: Dict[str, Any]) -> None:
    years = d.get("UPTIME_YEARS")
    weeks = d.get("UPTIME_WEEKS")
    days = d.get("UPTIME_DAYS")
    hours = d.get("UPTIME_HOURS")
    minutes = d.get("UPTIME_MINUTES")

    if years is None:
        years = 0
    if weeks is None:
        weeks = 0
    if days is None:
        days = 0
    if hours is None:
        hours = 0
    if minutes is None:
        minutes = 0

    try:
        total_minutes = (((years * 52) + weeks) * 7 + days) * 24 * 60
        total_minutes = total_minutes + (hours * 60) + minutes
        d["UPTIME_TOTAL_MINUTES"] = total_minutes
    except Exception:
        d["UPTIME_TOTAL_MINUTES"] = None


def _build_stack_members(d: Dict[str, Any]) -> None:
    """
    Create STACK_MEMBERS as a list of dicts with aligned model/serial pairs.
    If counts differ, pair to min length and put extras in *_UNMATCHED for visibility.
    """
    hardware_list = d.get("HARDWARE")
    serial_list = d.get("SERIAL")

    # Ensure lists (they are, due to force_list policy)
    if not isinstance(hardware_list, list):
        hardware_list = _to_list(hardware_list)
    if not isinstance(serial_list, list):
        serial_list = _to_list(serial_list)

    # Lengths
    m = len(hardware_list)
    n = len(serial_list)
    limit = m if m < n else n

    members: List[Dict[str, Any]] = []
    idx = 0
    while idx < limit:
        entry = {
            "index": idx + 1,
            "model": hardware_list[idx],
            "serial": serial_list[idx],
        }
        members.append(entry)
        idx += 1

    d["STACK_MEMBERS"] = members

    # capture unmatched tails (if any)
    if m > limit:
        extra_models: List[str] = []
        i = limit
        while i < m:
            extra_models.append(hardware_list[i])
            i += 1
        d["HARDWARE_UNMATCHED"] = extra_models

    if n > limit:
        extra_serials: List[str] = []
        i = limit
        while i < n:
            extra_serials.append(serial_list[i])
            i += 1
        d["SERIAL_UNMATCHED"] = extra_serials


def textfsm_row_to_dict(headers: List[str], row: List[Any]) -> Dict[str, Any]:
    """
    Convert a TextFSM row to a sane dict with embedded-list policy:
      - HARDWARE, SERIAL, MAC_ADDRESS => always lists
      - everything else: empty -> None; singletons collapse to scalar; multi-item lists preserved
    """
    result: Dict[str, Any] = {}

    # Keys to force into list form
    force_list_keys = set()
    force_list_keys.add("HARDWARE")
    force_list_keys.add("SERIAL")
    force_list_keys.add("MAC_ADDRESS")

    idx = 0
    max_len = len(headers) if len(headers) < len(row) else len(row)
    while idx < max_len:
        key = headers[idx]
        value = row[idx]

        # MAC addresses: normalize case
        if key == "MAC_ADDRESS":
            result[key] = _sanitize_scalar_or_list(value, force_list=True, lowercase=True)
        # Stack-critical fields: HARDWARE / SERIAL must remain lists
        elif key in force_list_keys:
            result[key] = _sanitize_scalar_or_list(value, force_list=True)
        else:
            # default policy
            # empty string -> None; single-item list -> scalar; multi-item -> list
            if value == "":
                result[key] = None
            else:
                result[key] = _sanitize_scalar_or_list(value, force_list=False)

        idx += 1

    # ints
    int_fields = []
    int_fields.append("UPTIME_YEARS")
    int_fields.append("UPTIME_WEEKS")
    int_fields.append("UPTIME_DAYS")
    int_fields.append("UPTIME_HOURS")
    int_fields.append("UPTIME_MINUTES")
    _coerce_int_fields(result, int_fields)

    # aggregate uptime
    _compute_uptime_minutes(result)

    # build stack members for easy downstream use
    _build_stack_members(result)

    return result


if __name__ == "__main__":
    d = textfsm_row_to_dict(HEADERS, ROW)
    print(json.dumps(d, indent=2))
