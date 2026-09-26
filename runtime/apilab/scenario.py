"""The simulated REST APIs: deterministic, seeded datasets and the rules each endpoint follows.

Pure functions, no I/O: the server (server.py) calls `respond` for every authorized request and logs what it says.
A scenario never depends on the wall clock except the rate limiter's penalty window, which needs real seconds.
"""
from __future__ import annotations

import base64
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

FIRST = ['Alex', 'Sam', 'Nora', 'Liam', 'Maya', 'Omar', 'Ines', 'Theo', 'Lena', 'Yuki', 'Ravi', 'Chloe', 'Hugo', 'Zoe']
LAST = ['Martin', 'Dubois', 'Khan', 'Rossi', 'Novak', 'Silva', 'Meyer', 'Costa', 'Moreau', 'Tanaka', 'Weber', 'Garcia']
COUNTRIES = ['FR', 'DE', 'ES', 'IT', 'NL', 'BE', 'PT', 'IE']
CATEGORIES = ['audio', 'cables', 'laptops', 'phones', 'storage', 'monitors']
EVENT_TYPES = ['page_view', 'add_to_cart', 'checkout', 'search', 'login']
START = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


class ApiError(Exception):
    """An answer other than 200 that the scenario decides (bad parameter, injected fault)."""

    def __init__(self, status: int, message: str, headers: dict[str, str] | None = None, meta: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.headers, self.meta = status, message, headers or {}, meta or {}


@dataclass
class Answer:
    body: Any
    headers: dict[str, str] = field(default_factory=dict)
    # What the request log records: how many records came back, and whether this was the last page.
    records: int = 0
    final: bool = False


@dataclass
class Memory:
    """Per-server state that is not in the state file: fault attempts and the rate limiter, reset at each run."""
    run: int = -1
    attempts: dict[str, int] = field(default_factory=dict)
    served: int = 0
    penalty_until: float = 0.0

    def for_run(self, run: int) -> 'Memory':
        if run != self.run:
            self.run, self.attempts, self.served, self.penalty_until = run, {}, 0, 0.0
        return self


def _int(query: dict[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = query.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, f'{name} must be an integer') from None
    if not low <= value <= high:
        raise ApiError(400, f'{name} must be between {low} and {high}')
    return value


def _paged(rows: list[dict], query: dict[str, str], max_size: int, default_size: int) -> Answer:
    size = _int(query, 'page_size', default_size, 1, max_size)
    total_pages = max(1, math.ceil(len(rows) / size))
    page = _int(query, 'page', 1, 1, 100_000)
    chunk = rows[(page - 1) * size: page * size]
    body = {'data': chunk, 'page': page, 'page_size': size, 'total_pages': total_pages, 'total': len(rows)}
    return Answer(body, records=len(chunk), final=page >= total_pages)


# ---- datasets --------------------------------------------------------------------------------------------------

def customers(seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(230):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        out.append({'id': 1001 + i, 'name': f'{first} {last}', 'email': f'{first}.{last}{i}@example.com'.lower(),
                    'country': rng.choice(COUNTRIES), 'created_at': iso(START - timedelta(days=rng.randint(1, 900)))})
    return out


def orders(seed: int, count: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(count):
        out.append({'order_id': 50001 + i, 'customer_id': 1001 + rng.randint(0, 229),
                    'status': rng.choice(['placed', 'paid', 'shipped']),
                    'amount': round(rng.uniform(8, 480), 2),
                    'created_at': iso(START + timedelta(minutes=67 * i))})
    return out


def events(seed: int) -> list[dict]:
    """360 events delivered at least once: 15 of them come back a second time, a few pages later."""
    rng = random.Random(seed)
    unique = [{'event_id': f'evt_{i:05d}', 'type': rng.choice(EVENT_TYPES), 'user_id': 1001 + rng.randint(0, 229),
               'occurred_at': iso(START + timedelta(seconds=97 * i))} for i in range(360)]
    stream = list(unique)
    for index in sorted(rng.sample(range(0, 300), 15), reverse=True):
        # The redelivered copy lands 40 to 60 positions later: on another page.
        stream.insert(index + rng.randint(40, 60), dict(unique[index]))
    return stream


def incremental_orders(seed: int, day: int) -> list[dict]:
    """Day 1: 300 orders. Day 2: 40 new orders and 25 earlier ones updated (a later updated_at)."""
    rng = random.Random(seed)
    rows = []
    for i in range(300):
        rows.append({'order_id': 70001 + i, 'customer_id': 1001 + rng.randint(0, 229),
                     'status': rng.choice(['placed', 'paid', 'shipped']), 'amount': round(rng.uniform(8, 480), 2),
                     'updated_at': iso(START + timedelta(minutes=110 * i))})
    if day >= 2:
        day2 = datetime(2026, 9, 25, 6, 0, tzinfo=timezone.utc)
        for n, index in enumerate(sorted(rng.sample(range(300), 25))):
            rows[index] = {**rows[index], 'status': 'delivered' if n % 3 else 'cancelled',
                           'updated_at': iso(day2 + timedelta(minutes=13 * n))}
        for i in range(40):
            rows.append({'order_id': 70301 + i, 'customer_id': 1001 + rng.randint(0, 229), 'status': 'placed',
                         'amount': round(rng.uniform(8, 480), 2),
                         'updated_at': iso(day2 + timedelta(minutes=7 * i + 3))})
    return sorted(rows, key=lambda row: (row['updated_at'], row['order_id']))


def products(seed: int, day: int) -> list[dict]:
    """Day 1: 120 products (API v1). Day 2, API v2: `price` renamed `unit_price`, a new `currency`, 15 new products
    and 10 repriced ones; each page is a full snapshot."""
    rng = random.Random(seed)
    rows = [{'sku': f'SKU-{i:04d}', 'name': f'{rng.choice(CATEGORIES).title()} item {i}',
             'category': rng.choice(CATEGORIES), 'price': round(rng.uniform(4, 900), 2)} for i in range(1, 121)]
    if day < 2:
        return rows
    repriced = set(rng.sample(range(120), 10))
    for i in range(121, 136):
        rows.append({'sku': f'SKU-{i:04d}', 'name': f'{rng.choice(CATEGORIES).title()} item {i}',
                     'category': rng.choice(CATEGORIES), 'price': round(rng.uniform(4, 900), 2)})
    out = []
    for index, row in enumerate(rows):
        price = round(row['price'] * 1.1, 2) if index in repriced else row['price']
        out.append({'sku': row['sku'], 'name': row['name'], 'category': row['category'], 'unit_price': price,
                    'currency': 'EUR'})
    return out


# ---- endpoints --------------------------------------------------------------------------------------------------

Handler = Callable[[int, int, dict[str, str], Memory, float], Answer]


def _customers(seed, _day, query, _memory, _now):
    return _paged(customers(seed), query, 100, 50)


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f'o:{offset}'.encode()).decode().rstrip('=')


def _offset(cursor: str) -> int:
    try:
        text = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode()
        if not text.startswith('o:'):
            raise ValueError
        return int(text[2:])
    except ValueError:
        raise ApiError(400, 'invalid cursor') from None


def _orders_cursor(seed, _day, query, memory, _now):
    rows = orders(seed, 420)
    limit = _int(query, 'limit', 100, 1, 100)
    offset = _offset(query['cursor']) if query.get('cursor') else 0
    # Injected upstream faults, each on the first attempt of its page in a run.
    faults = {200: (503, 'upstream timeout, retry later'), 400: (502, 'bad gateway')}
    if offset in faults:
        key = f'orders:{offset}'
        memory.attempts[key] = memory.attempts.get(key, 0) + 1
        if memory.attempts[key] == 1:
            status, message = faults[offset]
            raise ApiError(status, message)
    chunk = rows[offset: offset + limit]
    following = offset + limit
    next_cursor = _cursor(following) if following < len(rows) else None
    return Answer({'data': chunk, 'next_cursor': next_cursor}, records=len(chunk), final=next_cursor is None)


RATE_EVERY = 3
RETRY_AFTER = 1
# Clock slack between the server answering and the client starting to wait.
SLACK = 0.05


def _events(seed, _day, query, memory, now):
    if now < memory.penalty_until - SLACK:
        wait = max(1, math.ceil(memory.penalty_until - now))
        raise ApiError(429, 'rate limit exceeded', {'Retry-After': str(wait)}, {'violation': 'retry_after_ignored'})
    # Every RATE_EVERY served requests, the next one is refused with 429 and a Retry-After window.
    if memory.attempts.get('limit_due'):
        memory.attempts['limit_due'] = 0
        memory.penalty_until = now + RETRY_AFTER
        raise ApiError(429, 'rate limit exceeded', {'Retry-After': str(RETRY_AFTER)})
    answer = _paged(events(seed), query, 50, 50)
    memory.served += 1
    if memory.served % RATE_EVERY == 0:
        memory.attempts['limit_due'] = 1
    return answer


def _orders_incremental(seed, day, query, _memory, _now):
    rows = incremental_orders(seed, day)
    since = query.get('updated_since')
    if since is not None:
        try:
            moment = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            raise ApiError(400, 'updated_since must be an ISO 8601 timestamp, e.g. 2026-09-01T00:00:00Z') from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        rows = [row for row in rows if datetime.fromisoformat(row['updated_at'].replace('Z', '+00:00')) >= moment]
    return _paged(rows, query, 100, 100)


def _products(seed, day, query, _memory, _now):
    answer = _paged(products(seed, day), query, 100, 100)
    answer.headers['X-Api-Version'] = '2' if day >= 2 else '1'
    if day >= 2:
        answer.headers['Deprecation'] = 'price was renamed unit_price in v2; see the changelog'
    return answer


@dataclass(frozen=True)
class Scenario:
    endpoints: dict[str, Handler]
    days: int = 1


SCENARIOS: dict[str, Scenario] = {
    'customers-pages': Scenario({'/v1/customers': _customers}),
    'orders-cursor': Scenario({'/v1/orders': _orders_cursor}),
    'events-ratelimit': Scenario({'/v1/events': _events}),
    'orders-incremental': Scenario({'/v1/orders': _orders_incremental}, days=2),
    'products-drift': Scenario({'/v1/products': _products}, days=2),
}


def respond(scenario: str, seed: int, day: int, path: str, query: dict[str, str], memory: Memory, now: float) -> Answer:
    """The answer to one authorized GET, or ApiError."""
    spec = SCENARIOS[scenario]
    handler = spec.endpoints.get(path)
    if handler is None:
        raise ApiError(404, f'no endpoint {path}; this API serves {", ".join(sorted(spec.endpoints))}')
    return handler(seed, day, query, memory, now)
