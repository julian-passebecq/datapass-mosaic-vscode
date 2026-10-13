# Python cheatsheet

Reference for the Learning path "Python for data work". Python examples in Learning and Mosaic run as trusted local
Python only after you enable it for the workspace; the worker is not a sandbox.

## Records, dicts and sets

```python
from collections import Counter

counts = Counter(row["status"] for row in rows)          # {"DONE": 3, "OPEN": 1}
lookup = {c["id"]: c for c in customers}                 # build once: a hash join
enriched = [{**o, "name": lookup.get(o["customer_id"], {}).get("name")} for o in orders]
unique_in_order = list(dict.fromkeys(ids))               # dedupe, keep first-seen order
top = sorted(rows, key=lambda r: r["amount"], reverse=True)[:5]
```

- `d[key]` raises `KeyError`; `d.get(key, default)` does not.
- `x in some_set` is a hash lookup; `x in some_list` scans the list.
- `[... for ...]` builds a list; `(... for ...)` is a lazy generator, consumed once.
- Never use a mutable default argument (`def f(items=[])`): use `None` and create the list inside.

## Errors

```python
class ConfigError(ValueError):
    """A bad configuration value."""

try:
    size = int(raw)
except ValueError as exc:
    raise ConfigError(f"batch_size must be an integer, got {raw!r}") from exc
finally:
    pass  # always runs
```

- Catch the narrowest exception you can handle; a bare `except:` also hides bugs and Ctrl+C.
- `raise ... from exc` keeps the original error as the cause in the traceback.
- If you drop a bad row on purpose, log it with its line number.

## Files and CSV

```python
import csv
from pathlib import Path

path = Path("data") / "orders.csv"
with path.open(encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        amount = int(row["amount"])          # every CSV value is a string
        print(reader.line_num, row["customer"], amount)
```

- Always pass `encoding="utf-8"`; open CSV files with `newline=""`.
- Use `csv`, not `line.split(",")`: quoted fields can contain commas.
- Atomic write: write a temporary file in the same folder, then `os.replace(tmp, final)`.

## Dates and money

- `datetime.fromisoformat("2026-10-12T08:30:00")`; `datetime.strptime(text, "%d/%m/%Y")` for other formats.
- `0.1 + 0.2 == 0.3` is `False`. Use `decimal.Decimal("12.34")` or integer cents for money.

## Type hints

```python
def total_by_customer(path: Path) -> dict[str, int]: ...
def find(rows: list[dict[str, str]], key: str) -> dict[str, str] | None: ...
```

Hints are not checked at runtime; `mypy` or `pyright` check them.

## pytest

```python
import pytest

@pytest.mark.parametrize("text, cents", [("12.34", 1234), (" 5 ", 500), ("-0.5", -50)])
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents

def test_parse_amount_rejects_three_decimals():
    with pytest.raises(ValueError, match="not an amount"):
        parse_amount("1.234")

def test_reads_file(tmp_path):
    file = tmp_path / "orders.csv"
    file.write_text("customer,amount\nAda,5\n", encoding="utf-8")
    assert total_by_customer(file) == {"Ada": 5}
```

Cover at least the normal case, an edge case and the error case.

## Retries

Retry only transient failures (timeouts, HTTP 429, 502, 503, 504) with exponential backoff and jitter
(`delay = base * 2 ** attempt + random.uniform(0, base)`), up to a maximum number of attempts; honour `Retry-After`.
