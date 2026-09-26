"""Generate content/exercise-packs/python-prod-v1: production Python graded by pytest.

The learner writes a function AND its tests in one module. Grading (runtime/datapass_runtime/
pytest_grading.py) runs the learner's tests, then hidden pytest files that import the module as
`solution`. Real local Python: refused while trusted Python is off.

    python scripts/authoring/gen_python_prod.py
"""
import json
from pathlib import Path

PACK = Path(__file__).resolve().parents[2] / "content" / "exercise-packs" / "python-prod-v1"
MIN_TESTS = 3

EXERCISES = []


def exercise(id, title, difficulty, topics, prompt, signature, reference, hidden, mutants, hints, explanation):
    EXERCISES.append(dict(id=id, title=title, difficulty=difficulty, topics=topics, prompt=prompt, signature=signature,
                          reference=reference, hidden=hidden, mutants=mutants, hints=hints, explanation=explanation))


# ---------------------------------------------------------------------------- 1. typing and parsing
exercise(
    "py-parse-amount", "Parse an amount into cents", "easy", ["typing", "parsing"],
    "Write parse_amount(text: str) -> int that turns a decimal amount such as '12.34', ' 5 ' or '-0.5' into integer cents "
    "(1234, 500, -50). At most two decimals; anything else (empty text, letters, '1.234') raises ValueError. Money never goes "
    "through float. Then write at least 3 tests.",
    'def parse_amount(text: str) -> int:\n    """Decimal amount as integer cents."""\n    raise NotImplementedError\n',
    '''from decimal import Decimal, InvalidOperation


def parse_amount(text: str) -> int:
    """Decimal amount as integer cents; ValueError when it is not an amount with at most two decimals."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {text!r}") from exc
    if not value.is_finite() or value.as_tuple().exponent < -2:
        raise ValueError(f"not an amount with at most two decimals: {text!r}")
    return int(value * 100)


def test_whole_and_decimals():
    assert parse_amount("12.34") == 1234
    assert parse_amount(" 5 ") == 500


def test_negative():
    assert parse_amount("-0.5") == -50


def test_rejects_garbage():
    import pytest
    for bad in ["", "abc", "1.234"]:
        with pytest.raises(ValueError):
            parse_amount(bad)
''',
    '''import pytest
from solution import parse_amount


def test_float_traps():
    # 0.29 * 100 is 28.999999999999996 in binary floating point.
    assert parse_amount("0.29") == 29
    assert parse_amount("1.15") == 115


def test_basic():
    assert parse_amount("0") == 0
    assert parse_amount("100.1") == 10010


@pytest.mark.parametrize("bad", ["", "  ", "12,50", "1.234", "nan", "inf", "1e3.5"])
def test_rejected(bad):
    with pytest.raises(ValueError):
        parse_amount(bad)
''',
    ['''def parse_amount(text: str) -> int:
    text = text.strip()
    if not text or "," in text or (("." in text) and len(text.split(".")[1]) > 2):
        raise ValueError(text)
    return int(float(text) * 100)


def test_whole():
    assert parse_amount("12.00") == 1200


def test_negative():
    assert parse_amount("-0.5") == -50


def test_rejects():
    import pytest
    with pytest.raises(ValueError):
        parse_amount("")
'''],
    ["float cannot represent 0.29 exactly.", "decimal.Decimal parses text exactly; its exponent tells how many decimals there are."],
    "Decimal parses the text exactly, so 0.29 stays 0.29 and becomes 29 cents; float(0.29) * 100 is 28.999... and int() truncates it to 28. "
    "The exponent of the Decimal tells how many decimals were written, and Decimal refuses letters (nan and inf parse, so is_finite() refuses them).")

# ---------------------------------------------------------------------------- 2. reading files
exercise(
    "py-read-totals", "Total a CSV file per customer", "easy", ["files", "csv"],
    "Write total_by_customer(path) -> dict[str, int] that reads a UTF-8 CSV file with a header row customer,amount "
    "(amount is an integer) and returns the total amount per customer. Blank lines are skipped. Customer names can "
    "contain commas when quoted (\"Smith, Jo\") and non-ASCII letters. Then write at least 3 tests (pytest's tmp_path fixture "
    "gives each test its own folder).",
    'from pathlib import Path\n\n\ndef total_by_customer(path: str | Path) -> dict[str, int]:\n    """Total amount per customer in a CSV file."""\n    raise NotImplementedError\n',
    '''import csv
from pathlib import Path


def total_by_customer(path: str | Path) -> dict[str, int]:
    """Total amount per customer in a UTF-8 CSV file with a header customer,amount."""
    totals: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("customer"):
                continue
            totals[row["customer"]] = totals.get(row["customer"], 0) + int(row["amount"])
    return totals


def test_totals(tmp_path):
    f = tmp_path / "sales.csv"
    f.write_text("customer,amount\\nana,10\\nbo,5\\nana,7\\n", encoding="utf-8")
    assert total_by_customer(f) == {"ana": 17, "bo": 5}


def test_quoted_comma(tmp_path):
    f = tmp_path / "sales.csv"
    f.write_text('customer,amount\\n"Smith, Jo",3\\n', encoding="utf-8")
    assert total_by_customer(f) == {"Smith, Jo": 3}


def test_empty_file_has_no_totals(tmp_path):
    f = tmp_path / "sales.csv"
    f.write_text("customer,amount\\n", encoding="utf-8")
    assert total_by_customer(f) == {}
''',
    '''from solution import total_by_customer


def test_quoted_names_and_unicode(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text('customer,amount\\n"Smith, Jo",3\\nZoë,4\\n"Smith, Jo",2\\n\\nZoë,1\\n', encoding="utf-8")
    assert total_by_customer(f) == {"Smith, Jo": 5, "Zoë": 5}


def test_accepts_str_path(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("customer,amount\\nx,1\\n", encoding="utf-8")
    assert total_by_customer(str(f)) == {"x": 1}


def test_windows_line_endings(tmp_path):
    f = tmp_path / "s.csv"
    f.write_bytes("customer,amount\\r\\na,2\\r\\na,3\\r\\n".encode("utf-8"))
    assert total_by_customer(f) == {"a": 5}
''',
    ['''from pathlib import Path


def total_by_customer(path: str | Path) -> dict[str, int]:
    totals: dict[str, int] = {}
    lines = Path(path).read_text(encoding="utf-8").splitlines()[1:]
    for line in lines:
        if not line.strip():
            continue
        customer, amount = line.rsplit(",", 1)
        totals[customer] = totals.get(customer, 0) + int(amount)
    return totals


def test_totals(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("customer,amount\\nana,10\\nana,7\\n", encoding="utf-8")
    assert total_by_customer(f) == {"ana": 17}


def test_blank_lines(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("customer,amount\\n\\nbo,5\\n", encoding="utf-8")
    assert total_by_customer(f) == {"bo": 5}


def test_empty(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("customer,amount\\n", encoding="utf-8")
    assert total_by_customer(f) == {}
'''],
    ["A quoted field can contain the separator: splitting lines on ',' breaks it.", "csv.DictReader reads the header and handles quotes; open the file with newline=''."],
    "The csv module understands quoting, so \"Smith, Jo\" stays one field; splitting on commas keeps the quotes in the name and "
    "breaks on names with commas. newline='' lets csv handle Windows line endings, and an explicit encoding keeps Zoë readable "
    "whatever the computer's default encoding is.")

# ---------------------------------------------------------------------------- 3. logging
exercise(
    "py-log-bad-rows", "Log the rows you drop", "medium", ["logging"],
    "Write clean_rows(rows: list[dict]) -> list[dict] that keeps the rows whose 'qty' is an int >= 0 and drops the others. "
    "For each dropped row, log ONE message at WARNING level on the logger named 'pipeline.clean' that contains the row's "
    "'id'. Use the logging module, not print. Then write at least 3 tests (pytest's caplog fixture captures log records).",
    'import logging\n\n\ndef clean_rows(rows: list[dict]) -> list[dict]:\n    """Keep rows with a valid qty; log a warning for each dropped row."""\n    raise NotImplementedError\n',
    '''import logging

log = logging.getLogger("pipeline.clean")


def clean_rows(rows: list[dict]) -> list[dict]:
    """Keep rows whose qty is an int >= 0; log one warning per dropped row."""
    kept = []
    for row in rows:
        qty = row.get("qty")
        if isinstance(qty, int) and not isinstance(qty, bool) and qty >= 0:
            kept.append(row)
        else:
            log.warning("dropped row %s: invalid qty %r", row.get("id"), qty)
    return kept


def test_keeps_valid_rows():
    rows = [{"id": 1, "qty": 2}, {"id": 2, "qty": 0}]
    assert clean_rows(rows) == rows


def test_drops_and_logs(caplog):
    with caplog.at_level("WARNING", logger="pipeline.clean"):
        assert clean_rows([{"id": 7, "qty": -1}]) == []
    assert "7" in caplog.text


def test_missing_qty(caplog):
    with caplog.at_level("WARNING"):
        assert clean_rows([{"id": 3}]) == []
    assert len(caplog.records) == 1
''',
    '''import logging
from solution import clean_rows


def test_one_warning_per_dropped_row_on_the_right_logger(caplog):
    with caplog.at_level(logging.DEBUG):
        kept = clean_rows([{"id": "a", "qty": 1}, {"id": "b", "qty": -3}, {"id": "c", "qty": "2"}, {"id": "d", "qty": None}])
    assert [r["id"] for r in kept] == ["a"]
    records = [r for r in caplog.records if r.name == "pipeline.clean"]
    assert [r.levelno for r in records] == [logging.WARNING] * 3
    assert all(any(i in r.getMessage() for i in "bcd") for r in records)


def test_bool_is_not_a_quantity(caplog):
    with caplog.at_level(logging.WARNING, logger="pipeline.clean"):
        assert clean_rows([{"id": "t", "qty": True}]) == []


def test_nothing_logged_for_clean_input(caplog):
    with caplog.at_level(logging.DEBUG):
        clean_rows([{"id": 1, "qty": 5}])
    assert not [r for r in caplog.records if r.name == "pipeline.clean"]
''',
    ['''import logging

log = logging.getLogger("pipeline.clean")


def clean_rows(rows: list[dict]) -> list[dict]:
    kept = []
    for row in rows:
        qty = row.get("qty")
        if isinstance(qty, int) and qty >= 0:
            kept.append(row)
        else:
            log.info("dropped row %s", row.get("id"))
    return kept


def test_keeps():
    assert clean_rows([{"id": 1, "qty": 1}]) == [{"id": 1, "qty": 1}]


def test_drops():
    assert clean_rows([{"id": 1, "qty": -1}]) == []


def test_missing():
    assert clean_rows([{"id": 1}]) == []
'''],
    ["A dropped row is a problem someone should see: which level is that?", "bool is a subclass of int in Python: True passes isinstance(x, int)."],
    "WARNING is the level for data problems the pipeline survives; INFO is filtered out by most production configurations, so "
    "those drops would be silent. A named module logger ('pipeline.clean') lets operators route and filter the messages. "
    "isinstance(True, int) is True in Python, so a quantity check must exclude bool explicitly.")

# ---------------------------------------------------------------------------- 4. error handling
exercise(
    "py-config-errors", "Clear errors for a bad config", "medium", ["errors", "json"],
    "Write load_config(text: str) -> dict that parses a JSON object with a required string 'source' and a required integer "
    "'batch_size' > 0, and returns it. Define class ConfigError(ValueError). Every problem raises ConfigError with a message "
    "that names the key at fault; invalid JSON raises ConfigError chained from the JSON error (raise ... from exc). Then write "
    "at least 3 tests.",
    'class ConfigError(ValueError):\n    """A configuration problem."""\n\n\ndef load_config(text: str) -> dict:\n    """Parse and validate a JSON config."""\n    raise NotImplementedError\n',
    '''import json


class ConfigError(ValueError):
    """A configuration problem; the message names the key at fault."""


def load_config(text: str) -> dict:
    """Parse and validate a JSON config with 'source' (str) and 'batch_size' (int > 0)."""
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config is not valid JSON: {exc.msg}") from exc
    if not isinstance(config, dict):
        raise ConfigError("config must be a JSON object")
    if not isinstance(config.get("source"), str) or not config["source"]:
        raise ConfigError("'source' is required and must be a non-empty string")
    size = config.get("batch_size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ConfigError("'batch_size' is required and must be an integer > 0")
    return config


def test_valid():
    assert load_config('{"source": "s3", "batch_size": 10}')["batch_size"] == 10


def test_missing_key_named():
    import pytest
    with pytest.raises(ConfigError, match="batch_size"):
        load_config('{"source": "s3"}')


def test_bad_json_is_chained():
    import json, pytest
    with pytest.raises(ConfigError) as info:
        load_config("{oops")
    assert isinstance(info.value.__cause__, json.JSONDecodeError)
''',
    '''import json
import pytest
from solution import ConfigError, load_config


def test_config_error_is_a_value_error():
    assert issubclass(ConfigError, ValueError)


@pytest.mark.parametrize("text,key", [
    ('{"batch_size": 5}', "source"),
    ('{"source": "", "batch_size": 5}', "source"),
    ('{"source": "a", "batch_size": 0}', "batch_size"),
    ('{"source": "a", "batch_size": "5"}', "batch_size"),
    ('{"source": "a", "batch_size": true}', "batch_size"),
])
def test_names_the_key(text, key):
    with pytest.raises(ConfigError, match=key):
        load_config(text)


def test_invalid_json_chained():
    with pytest.raises(ConfigError) as info:
        load_config('{"source": ')
    assert isinstance(info.value.__cause__, json.JSONDecodeError)


def test_not_an_object():
    with pytest.raises(ConfigError):
        load_config("[1, 2]")
''',
    ['''import json


class ConfigError(ValueError):
    pass


def load_config(text: str) -> dict:
    config = json.loads(text)
    if "source" not in config:
        raise ConfigError("missing source")
    if "batch_size" not in config or config["batch_size"] <= 0:
        raise ConfigError("bad batch_size")
    return config


def test_valid():
    assert load_config('{"source": "a", "batch_size": 1}')["source"] == "a"


def test_missing_source():
    import pytest
    with pytest.raises(ConfigError):
        load_config('{"batch_size": 1}')


def test_zero_batch():
    import pytest
    with pytest.raises(ConfigError):
        load_config('{"source": "a", "batch_size": 0}')
'''],
    ["json.loads raises json.JSONDecodeError: catch it and raise your own error from it.", "Check the types too: \"5\" and true are not integers > 0."],
    "Callers catch one exception type (ConfigError, still a ValueError) and read which key is wrong. `raise ... from exc` keeps "
    "the JSON error as __cause__, so the traceback shows where the text broke. Validating types matters: \"5\" > 0 raises "
    "TypeError and true counts as 1.")

# ---------------------------------------------------------------------------- 5. retries
exercise(
    "py-retry-backoff", "Retry with exponential backoff", "medium", ["retries", "errors"],
    "Write retry(func, attempts=3, delay=0.5, sleep=time.sleep, retry_on=(ConnectionError, TimeoutError)) that calls func() "
    "and returns its result. When func raises one of retry_on, sleep delay * 2**n (0.5, then 1.0, …) and try again, up to "
    "`attempts` calls in total; after the last failure, re-raise that exception. Any other exception propagates at once, "
    "without sleeping. Then write at least 3 tests (pass a fake sleep so the tests do not wait).",
    'import time\n\n\ndef retry(func, attempts=3, delay=0.5, sleep=time.sleep, retry_on=(ConnectionError, TimeoutError)):\n    """Call func, retrying transient errors with exponential backoff."""\n    raise NotImplementedError\n',
    '''import time


def retry(func, attempts=3, delay=0.5, sleep=time.sleep, retry_on=(ConnectionError, TimeoutError)):
    """Call func; retry the exceptions in retry_on with exponential backoff, re-raise the last one."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(attempts):
        try:
            return func()
        except retry_on:
            if attempt == attempts - 1:
                raise
            sleep(delay * 2 ** attempt)


def test_returns_after_transient_errors():
    calls, waits = [], []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("down")
        return "ok"
    assert retry(flaky, sleep=waits.append) == "ok"
    assert waits == [0.5, 1.0]


def test_reraises_after_last_attempt():
    import pytest
    def down():
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        retry(down, attempts=2, sleep=lambda s: None)


def test_other_errors_not_retried():
    import pytest
    waits = []
    def broken():
        raise KeyError("x")
    with pytest.raises(KeyError):
        retry(broken, sleep=waits.append)
    assert waits == []
''',
    '''import pytest
from solution import retry


def test_backoff_sequence_and_call_count():
    calls, waits = [], []
    def always():
        calls.append(1)
        raise ConnectionError("x")
    with pytest.raises(ConnectionError):
        retry(always, attempts=4, delay=0.1, sleep=waits.append)
    assert len(calls) == 4
    assert waits == pytest.approx([0.1, 0.2, 0.4])


def test_non_transient_error_is_not_retried():
    calls, waits = [], []
    def bad():
        calls.append(1)
        raise ValueError("bad input")
    with pytest.raises(ValueError):
        retry(bad, sleep=waits.append)
    assert calls == [1] and waits == []


def test_custom_retry_on():
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise KeyError("once")
        return 5
    assert retry(flaky, retry_on=(KeyError,), sleep=lambda s: None) == 5


def test_success_first_time_does_not_sleep():
    waits = []
    assert retry(lambda: 1, sleep=waits.append) == 1
    assert waits == []
''',
    ['''import time


def retry(func, attempts=3, delay=0.5, sleep=time.sleep, retry_on=(ConnectionError, TimeoutError)):
    for attempt in range(attempts):
        try:
            return func()
        except Exception:
            if attempt == attempts - 1:
                raise
            sleep(delay * 2 ** attempt)


def test_ok():
    assert retry(lambda: 3, sleep=lambda s: None) == 3


def test_backoff():
    waits, calls = [], []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError()
        return 1
    retry(flaky, sleep=waits.append)
    assert waits == [0.5, 1.0]


def test_reraise():
    import pytest
    with pytest.raises(TimeoutError):
        retry(lambda: (_ for _ in ()).throw(TimeoutError()), sleep=lambda s: None)
''',
     '''import time


def retry(func, attempts=3, delay=0.5, sleep=time.sleep, retry_on=(ConnectionError, TimeoutError)):
    for attempt in range(attempts):
        try:
            return func()
        except retry_on:
            if attempt == attempts - 1:
                raise
            sleep(delay)


def test_ok():
    assert retry(lambda: 3, sleep=lambda s: None) == 3


def test_retries():
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise ConnectionError()
        return 1
    assert retry(flaky, sleep=lambda s: None) == 1


def test_not_retried():
    import pytest
    with pytest.raises(KeyError):
        retry(lambda: {}["x"], sleep=lambda s: None)
'''],
    ["Only transient errors deserve a retry: a ValueError will fail the same way next time.", "Inject sleep so a test can record the waits instead of waiting."],
    "Retrying everything hides real bugs (a KeyError fails identically every time) and multiplies load on a broken service. "
    "Exponential backoff gives a struggling service room to recover. Injecting sleep keeps the tests instant and lets them check the waits.")

# ---------------------------------------------------------------------------- 6. generators
exercise(
    "py-chunked", "Split any iterable into batches", "easy", ["generators", "typing"],
    "Write chunked(items: Iterable[T], size: int) -> Iterator[list[T]] that yields lists of `size` items, the last one "
    "possibly shorter. It must work lazily on generators (never call len() or list() on the whole input) and raise "
    "ValueError when size < 1. Then write at least 3 tests.",
    'from collections.abc import Iterable, Iterator\nfrom typing import TypeVar\n\nT = TypeVar("T")\n\n\ndef chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:\n    """Yield lists of size items."""\n    raise NotImplementedError\n',
    '''from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield lists of `size` items, lazily; the last list may be shorter."""
    if size < 1:
        raise ValueError("size must be at least 1")
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def test_even_and_remainder():
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_generator_input():
    assert list(chunked((i for i in range(3)), 3)) == [[0, 1, 2]]


def test_bad_size():
    import pytest
    with pytest.raises(ValueError):
        list(chunked([1], 0))
''',
    '''import itertools
import pytest
from solution import chunked


def test_last_partial_batch_kept():
    assert list(chunked("abcdefg", 3)) == [["a", "b", "c"], ["d", "e", "f"], ["g"]]


def test_empty():
    assert list(chunked([], 4)) == []


def test_lazy_on_infinite_input():
    first = next(chunked(itertools.count(), 2))
    assert first == [0, 1]


def test_negative_size():
    with pytest.raises(ValueError):
        list(chunked([1, 2], -1))
''',
    ['''from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    if size < 1:
        raise ValueError("size")
    iterator = iter(items)
    while True:
        batch = list(islice(iterator, size))
        if len(batch) < size:
            return
        yield batch


def test_even():
    assert list(chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


def test_generator():
    assert list(chunked((i for i in range(2)), 2)) == [[0, 1]]


def test_bad():
    import pytest
    with pytest.raises(ValueError):
        list(chunked([1], 0))
'''],
    ["itertools.islice takes the next n items of an iterator without reading further.", "What happens to the last few items when they do not fill a batch?"],
    "islice on one shared iterator reads exactly `size` items at a time, so generators and even infinite inputs work and memory "
    "stays bounded. The last short batch still holds data: dropping it loses rows.")

# ---------------------------------------------------------------------------- 7. deduplication
exercise(
    "py-latest-by-key", "Keep the latest version of each record", "medium", ["data-quality", "typing"],
    "Write latest_by_key(rows: list[dict], key: str, ts: str) -> list[dict] that keeps, for each value of rows[i][key], the "
    "row with the greatest rows[i][ts] (ISO-8601 strings such as '2026-09-26T10:00:00'); on a tie, the row that comes later "
    "in the input wins. Return the kept rows in the order their key first appeared. Then write at least 3 tests.",
    'def latest_by_key(rows: list[dict], key: str, ts: str) -> list[dict]:\n    """Latest row per key."""\n    raise NotImplementedError\n',
    '''def latest_by_key(rows: list[dict], key: str, ts: str) -> list[dict]:
    """Latest row per key (ties: the later row wins), in order of the keys' first appearance."""
    latest: dict = {}
    for row in rows:
        current = latest.get(row[key])
        if current is None or row[ts] >= current[ts]:
            latest[row[key]] = row
    return list(latest.values())


def test_latest_wins():
    rows = [{"id": 1, "t": "2026-01-01", "v": "a"}, {"id": 1, "t": "2026-02-01", "v": "b"}]
    assert latest_by_key(rows, "id", "t") == [rows[1]]


def test_keys_kept_apart():
    rows = [{"id": 1, "t": "1"}, {"id": 2, "t": "1"}]
    assert latest_by_key(rows, "id", "t") == rows


def test_tie_later_row_wins():
    rows = [{"id": 1, "t": "x", "v": 1}, {"id": 1, "t": "x", "v": 2}]
    assert latest_by_key(rows, "id", "t")[0]["v"] == 2
''',
    '''from solution import latest_by_key


def test_out_of_order_input():
    rows = [
        {"k": "a", "ts": "2026-09-26T10:00:00", "v": 2},
        {"k": "b", "ts": "2026-09-25T00:00:00", "v": 1},
        {"k": "a", "ts": "2026-09-24T10:00:00", "v": 0},
    ]
    assert [r["v"] for r in latest_by_key(rows, "k", "ts")] == [2, 1]


def test_ties_prefer_later_rows():
    rows = [{"k": 1, "ts": "t", "v": "first"}, {"k": 1, "ts": "t", "v": "second"}]
    assert latest_by_key(rows, "k", "ts")[0]["v"] == "second"


def test_order_of_first_appearance():
    rows = [{"k": "z", "ts": "1"}, {"k": "y", "ts": "1"}, {"k": "z", "ts": "2"}]
    assert [r["k"] for r in latest_by_key(rows, "k", "ts")] == ["z", "y"]


def test_empty():
    assert latest_by_key([], "k", "ts") == []
''',
    ['''def latest_by_key(rows: list[dict], key: str, ts: str) -> list[dict]:
    seen = {}
    for row in rows:
        if row[key] not in seen:
            seen[row[key]] = row
    return list(seen.values())


def test_one_key():
    rows = [{"id": 1, "t": "1"}]
    assert latest_by_key(rows, "id", "t") == rows


def test_two_keys():
    rows = [{"id": 1, "t": "1"}, {"id": 2, "t": "1"}]
    assert latest_by_key(rows, "id", "t") == rows


def test_empty():
    assert latest_by_key([], "id", "t") == []
''',
     '''def latest_by_key(rows: list[dict], key: str, ts: str) -> list[dict]:
    latest = {}
    for row in rows:
        if row[key] not in latest or row[ts] > latest[row[key]][ts]:
            latest[row[key]] = row
    return list(latest.values())


def test_latest():
    rows = [{"id": 1, "t": "1"}, {"id": 1, "t": "2"}]
    assert latest_by_key(rows, "id", "t") == [rows[1]]


def test_keys():
    rows = [{"id": 1, "t": "1"}, {"id": 2, "t": "1"}]
    assert latest_by_key(rows, "id", "t") == rows


def test_empty():
    assert latest_by_key([], "id", "t") == []
'''],
    ["The first row for a key is not the latest one when input arrives out of order.", "ISO-8601 strings of the same format sort correctly as text; >= decides ties."],
    "Change feeds arrive out of order, so the first row seen is not the newest. Comparing ISO-8601 strings works because they "
    "sort chronologically as text; >= lets a later row win a tie, which matches 'the last write wins'. A dict keeps insertion "
    "order, so the keys stay in order of first appearance.")

# ---------------------------------------------------------------------------- 8. safe file writes
exercise(
    "py-write-report", "Write a report file safely", "hard", ["files", "errors"],
    "Write write_report(folder: Path, name: str, text: str) -> Path that writes text (UTF-8) to folder/name and returns that "
    "path. Create the folder if it is missing. Refuse (ValueError) a name that is empty, contains / or \\\\, or is '.' or '..', "
    "so nothing is written outside the folder. Write atomically: write a temporary file in the same folder, then replace the "
    "target with os.replace, so a reader never sees half a report; leave no temporary file behind. Then write at least 3 tests.",
    'from pathlib import Path\n\n\ndef write_report(folder: Path, name: str, text: str) -> Path:\n    """Write text to folder/name atomically."""\n    raise NotImplementedError\n',
    '''import os
import tempfile
from pathlib import Path


def write_report(folder: Path, name: str, text: str) -> Path:
    """Write text to folder/name atomically; refuse names that leave the folder."""
    if not name or name in {".", ".."} or "/" in name or "\\\\" in name:
        raise ValueError(f"not a plain file name: {name!r}")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    fd, temp = tempfile.mkstemp(dir=folder, prefix="." + name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return target


def test_writes(tmp_path):
    path = write_report(tmp_path, "r.txt", "hello")
    assert path.read_text(encoding="utf-8") == "hello"


def test_creates_folder(tmp_path):
    assert write_report(tmp_path / "new", "r.txt", "x").exists()


def test_refuses_parent(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        write_report(tmp_path, "../escape.txt", "x")
''',
    '''import pytest
from solution import write_report


@pytest.mark.parametrize("name", ["", ".", "..", "../x.txt", "a/b.txt", "a\\\\b.txt"])
def test_refused_names(tmp_path, name):
    with pytest.raises(ValueError):
        write_report(tmp_path / "out", name, "x")
    assert not (tmp_path / "x.txt").exists()


def test_overwrite_and_no_temp_left(tmp_path):
    write_report(tmp_path, "r.txt", "one")
    path = write_report(tmp_path, "r.txt", "two")
    assert path == tmp_path / "r.txt"
    assert path.read_text(encoding="utf-8") == "two"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.txt"]


def test_unicode(tmp_path):
    assert write_report(tmp_path, "zoë.txt", "déjà vu").read_text(encoding="utf-8") == "déjà vu"
''',
    ['''from pathlib import Path


def write_report(folder: Path, name: str, text: str) -> Path:
    if not name:
        raise ValueError("empty name")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_text(text, encoding="utf-8")
    return target


def test_writes(tmp_path):
    assert write_report(tmp_path, "r.txt", "a").read_text(encoding="utf-8") == "a"


def test_folder(tmp_path):
    assert write_report(tmp_path / "n", "r.txt", "a").exists()


def test_empty_name(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        write_report(tmp_path, "", "a")
'''],
    ["'..' and separators let a name escape the folder: refuse them before building the path.", "tempfile.mkstemp(dir=folder) + os.replace(temp, target) is the atomic write pattern."],
    "A name from outside (a report title, a customer name) must not choose where the file lands: '..' or a separator would "
    "write outside the folder. os.replace swaps the complete file in one step on the same filesystem, so readers see the old "
    "report or the new one, never a truncated file, and the except branch removes the temporary file on failure.")


def starter(e):
    return (f'"""{e["title"]}.\n\n{e["prompt"]}\n"""\n\n{e["signature"]}\n\n'
            "# Your tests: pytest runs every function named test_... in this file (write at least 3).\n"
            "def test_example():\n    assert True\n")


def main():
    definitions, grading, mutants = [], {}, {}
    for e in EXERCISES:
        definitions.append({
            "schema_version": 1, "id": e["id"], "version": "1", "title": e["title"], "difficulty": e["difficulty"],
            "topics": ["python-production", *e["topics"]], "tags": ["pytest", "production-python"], "origin": "authored",
            "language": "pytest", "runtime": "datapass-pytest-v1", "prompt": e["prompt"],
            "sections": [
                {"title": "Graded by pytest (real local Python)",
                 "body": "Your file runs as real local Python, only while trusted local Python is on for this workspace. Grading runs pytest twice: on your file (your tests must pass, at least 3 of them), then, on Submit, on hidden tests that import your module as `solution`."},
                {"title": "Run it yourself", "body": "In a VS Code terminal in the exercise folder: python -m pytest solution.py -q (with the Datapass runtime's Python or any Python with pytest)."}],
            "starter_source": starter(e),
            "fixtures": [{"id": e["id"] + "-fixtures", "version": "1"}],
            "visible_checks": [{"id": "own-tests", "description": f"Your own tests pass (at least {MIN_TESTS})."}],
            "hidden_check_refs": ["hidden"], "edge_check_refs": [],
            "hints": e["hints"], "solution": {"available": True, "reveal": "explicit"}, "explanation": e["explanation"],
            "follow_ups": [], "canonical_placement": {"domain": "python-production", "topic": "python-production"},
            "related_associations": ["practice/python"], "validator_version": "pytest-v1",
            "runtime_requirements": ["python", "pytest"],
            "provenance": {"source": "Authored for Datapass Workbench"},
            "constraints": {"truth": "Real local Python and pytest, trusted local Python only; not a security sandbox."},
            "truth": "real",
        })
        grading[e["id"]] = {"solution": e["reference"], "fixtures": [
            {"id": "own-tests", "visibility": "visible", "input_rows": [], "expected": [], "scenario": {"check": "own-tests", "min_tests": MIN_TESTS}},
            {"id": "hidden", "visibility": "hidden", "input_rows": [], "expected": [], "scenario": {"check": "hidden", "tests": e["hidden"]}},
        ]}
        mutants[e["id"]] = e["mutants"]
    PACK.mkdir(parents=True, exist_ok=True)
    dump = lambda name, data: (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dump("manifest.json", {"schema_version": 1, "id": "python-prod-v1", "version": "1",
                           "title": "Production Python: typing, files, logging, errors, retries (graded by pytest)",
                           "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}})
    dump("exercises.json", definitions)
    dump("grading.server.json", grading)
    dump("quality.json", {"flags": {"runnable_starters": True}, "mutants": mutants})
    print(f"python-prod-v1: {len(definitions)} exercises")


if __name__ == "__main__":
    main()
