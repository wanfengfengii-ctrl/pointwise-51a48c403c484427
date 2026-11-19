import json

from storage import DatabasePath, connect, is_row_id, write_transaction
from survey.junctions import Junction
from survey.restrictions import Restriction
from survey.roads import Road, decode_cost, encode_cost


class RevisionStore:
    def __init__(self, path: DatabasePath):
        self.path = path

    def initialize(self) -> None:
        with connect(self.path) as database, write_transaction(database):
            database.execute('''
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY,
                    document TEXT NOT NULL
                )
            ''')

    def commit(
        self,
        junctions: tuple[Junction, ...],
        roads: tuple[Road, ...],
        restrictions: tuple[Restriction, ...],
        *,
        ordered_corridors: tuple[tuple[str, str], ...] | None = None,
    ) -> int:
        document: dict = {
            'junctions': [junction.id for junction in junctions],
            'roads': [(road.id, road.start, road.end, encode_cost(road.cost)) for road in roads],
            'restrictions': [(rule.id, rule.roads) for rule in restrictions],
        }
        if ordered_corridors is not None:
            document['corridors'] = [[road_id, corridor_id] for road_id, corridor_id in ordered_corridors]
        encoded = json.dumps(document, separators=(',', ':'))
        with connect(self.path) as database, write_transaction(database):
            cursor = database.execute('INSERT INTO revisions(document) VALUES (?)', (encoded,))
            revision_id = cursor.lastrowid
        return revision_id

    def get(self, revision_id: int):
        if not is_row_id(revision_id):
            return None
        with connect(self.path) as database:
            row = database.execute('SELECT document FROM revisions WHERE id = ?', (revision_id,)).fetchone()
        if row is None:
            return None
        document = json.loads(row[0])
        corridors = None
        if 'corridors' in document:
            corridors = tuple((road_id, corridor_id) for road_id, corridor_id in document['corridors'])
        return (
            tuple(Junction(name) for name in document['junctions']),
            tuple(Road(name, start, end, decode_cost(cost)) for name, start, end, cost in document['roads']),
            tuple(Restriction(name, tuple(roads)) for name, roads in document['restrictions']),
            corridors,
        )
