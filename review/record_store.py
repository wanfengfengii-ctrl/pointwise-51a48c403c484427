from dataclasses import dataclass
import json

from review.requests import ReviewRequest
from routing.itineraries import Itinerary
from storage import DatabasePath, connect, is_row_id, write_transaction
from survey.roads import decode_cost, encode_cost


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    id: int
    request: ReviewRequest
    itinerary: Itinerary


@dataclass(frozen=True, slots=True)
class PairRoute:
    roads: tuple[str, ...]
    corridors: frozenset[str]
    cost: int


@dataclass(frozen=True, slots=True)
class PairRecord:
    id: int
    request: ReviewRequest
    main: PairRoute | None
    backup: PairRoute | None
    total_cost: int | None


class RecordStore:
    def __init__(self, path: DatabasePath):
        self.path = path

    def initialize(self) -> None:
        with connect(self.path) as database, write_transaction(database):
            database.execute('''
                CREATE TABLE IF NOT EXISTS review_records (
                    id INTEGER PRIMARY KEY,
                    bundle_id TEXT NOT NULL,
                    endpoints TEXT NOT NULL,
                    roads TEXT,
                    cost TEXT,
                    CHECK ((roads IS NULL) = (cost IS NULL))
                )
            ''')
            database.execute('''
                CREATE TABLE IF NOT EXISTS pair_records (
                    id INTEGER PRIMARY KEY,
                    bundle_id TEXT NOT NULL,
                    endpoints TEXT NOT NULL,
                    main TEXT,
                    backup TEXT,
                    total_cost TEXT,
                    CHECK ((main IS NULL) = (backup IS NULL)),
                    CHECK ((main IS NULL) = (total_cost IS NULL))
                )
            ''')

    def commit(self, request: ReviewRequest, itinerary: Itinerary) -> ReviewRecord:
        endpoints = json.dumps((request.start, request.end))
        roads = None if itinerary.roads is None else json.dumps(itinerary.roads)
        cost = None if itinerary.cost is None else encode_cost(itinerary.cost)
        with connect(self.path) as database, write_transaction(database):
            cursor = database.execute(
                'INSERT INTO review_records(bundle_id, endpoints, roads, cost) VALUES (?, ?, ?, ?)',
                (request.bundle_id, endpoints, roads, cost),
            )
            record_id = cursor.lastrowid
        return ReviewRecord(record_id, request, itinerary)

    def get(self, record_id: int) -> ReviewRecord | None:
        if not is_row_id(record_id):
            return None
        with connect(self.path) as database:
            row = database.execute(
                'SELECT bundle_id, endpoints, roads, cost FROM review_records WHERE id = ?', (record_id,)
            ).fetchone()
        if row is None:
            return None
        bundle_id, encoded_endpoints, encoded_roads, encoded_cost = row
        start, end = json.loads(encoded_endpoints)
        roads = None if encoded_roads is None else tuple(json.loads(encoded_roads))
        cost = None if encoded_cost is None else decode_cost(encoded_cost)
        return ReviewRecord(record_id, ReviewRequest(bundle_id, start, end), Itinerary(roads, cost))

    def commit_pair(
        self,
        request: ReviewRequest,
        main: PairRoute | None,
        backup: PairRoute | None,
        total_cost: int | None,
    ) -> PairRecord:
        endpoints = json.dumps((request.start, request.end))
        main_text = None if main is None else _encode_route(main)
        backup_text = None if backup is None else _encode_route(backup)
        total_text = None if total_cost is None else encode_cost(total_cost)
        with connect(self.path) as database, write_transaction(database):
            cursor = database.execute(
                'INSERT INTO pair_records(bundle_id, endpoints, main, backup, total_cost) '
                'VALUES (?, ?, ?, ?, ?)',
                (request.bundle_id, endpoints, main_text, backup_text, total_text),
            )
            record_id = cursor.lastrowid
        return PairRecord(record_id, request, main, backup, total_cost)

    def get_pair(self, record_id: int) -> PairRecord | None:
        if not is_row_id(record_id):
            return None
        with connect(self.path) as database:
            row = database.execute(
                'SELECT bundle_id, endpoints, main, backup, total_cost FROM pair_records WHERE id = ?',
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        bundle_id, encoded_endpoints, main_text, backup_text, total_text = row
        start, end = json.loads(encoded_endpoints)
        main = None if main_text is None else _decode_route(main_text)
        backup = None if backup_text is None else _decode_route(backup_text)
        total_cost = None if total_text is None else decode_cost(total_text)
        return PairRecord(record_id, ReviewRequest(bundle_id, start, end), main, backup, total_cost)


def _encode_route(route: PairRoute) -> str:
    return json.dumps({
        'roads': list(route.roads),
        'corridors': sorted(route.corridors),
        'cost': encode_cost(route.cost),
    }, separators=(',', ':'))


def _decode_route(text: str) -> PairRoute:
    document = json.loads(text)
    return PairRoute(
        tuple(document['roads']),
        frozenset(document['corridors']),
        decode_cost(document['cost']),
    )
