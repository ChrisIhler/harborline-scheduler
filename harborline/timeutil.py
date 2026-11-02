"""Clock-time helpers. Times are stored as minutes after midnight."""

import re


def to_min(hhmm: str) -> int:
    """'06:30' -> 390."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(hhmm))
    if not m:
        raise ValueError(f"Not a 24-hour HH:MM time: {hhmm!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 24 and 0 <= mi < 60) or (h == 24 and mi):
        raise ValueError(f"Time out of range: {hhmm!r}")
    return h * 60 + mi


def to_hhmm(minutes: int) -> str:
    """390 -> '06:30'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def to_12h(minutes: int) -> str:
    """390 -> '6:30 AM' (for people-facing output)."""
    h, m = divmod(minutes, 60)
    suffix = "AM" if h < 12 or h == 24 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


_TIME_RE = re.compile(
    r"""
    (?<![\d:])
    (?P<h>\d{1,2})
    (?: [:.](?P<m>\d{2}) )?
    \s*
    (?P<ampm>a\.?\s?m\.?|p\.?\s?m\.?)?
    (?![\d:])
    """,
    re.IGNORECASE | re.VERBOSE,
)


def times_in_text(text: str) -> set[int]:
    """Every clock time a person wrote in `text`, as minutes after midnight.

    Accepts '6:30 am', '6:30AM', '6 pm', '18:45', 'noon', 'midnight'.
    A bare number like '15' is NOT a time (it could be minutes or a count),
    so it only counts when it has a colon or an am/pm marker.
    For '7:15' with no am/pm, both 07:15 and 19:15 are accepted, because the
    person did write that clock time; the day's service hours decide which.
    """
    found: set[int] = set()
    lowered = text.lower()
    if "noon" in lowered:
        found.add(12 * 60)
    if "midnight" in lowered:
        found.add(24 * 60)
    # Ranges like "6 to 9 am" or "4-7 pm": the first number borrows the marker.
    for m in re.finditer(
        r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*(?:-|–|to|until|through)\s*\d{1,2}(?::\d{2})?\s*(a\.?\s?m\.?|p\.?\s?m\.?)",
        text, re.IGNORECASE,
    ):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 1 <= h <= 12 and mi < 60:
            found.add((h % 12) * 60 + mi)        # as AM
            found.add((h % 12 + 12) * 60 + mi)   # as PM ("11 to 1 pm" means 11 AM)
    for m in _TIME_RE.finditer(text):
        h = int(m.group("h"))
        mi = int(m.group("m")) if m.group("m") else None
        ampm = (m.group("ampm") or "").lower().replace(".", "").replace(" ", "")
        if mi is None and not ampm:
            continue  # bare number, not a time
        mi = mi or 0
        if mi >= 60 or h > 24:
            continue
        if ampm == "am":
            if 1 <= h <= 12:
                found.add((0 if h == 12 else h) * 60 + mi)
        elif ampm == "pm":
            if 1 <= h <= 12:
                found.add((12 if h == 12 else h + 12) * 60 + mi)
        else:
            found.add(h * 60 + mi)
            if 1 <= h <= 11:
                found.add((h + 12) * 60 + mi)
    return found


def numbers_in_text(text: str) -> set[int]:
    """Every whole number written in `text` (digits, plus one to sixty in words)."""
    nums = {int(n) for n in re.findall(r"(?<![\d])\d+(?![\d])", text)}
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
        "forty": 40, "forty-five": 45, "sixty": 60,
    }
    lowered = text.lower()
    for w, n in words.items():
        if re.search(rf"\b{re.escape(w)}\b", lowered):
            nums.add(n)
    if re.search(r"\bhalf an hour\b|\bhalf-hour\b|\bhalf hour\b", lowered):
        nums.add(30)
    if re.search(r"\bquarter hour\b|\bquarter-hour\b", lowered):
        nums.add(15)
    if re.search(r"\b(an|one) hour\b|\bhourly\b", lowered):
        nums.add(60)
    return nums
