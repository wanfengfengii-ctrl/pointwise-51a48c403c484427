from collections.abc import Mapping

from survey.junctions import require_name
from survey.roads import Road


def index_corridors(corridors, roads: Mapping[str, Road]) -> dict[str, str]:
    """Return the corridor owning each directed original road.

    ``corridors`` is a sequence of ``(road_id, corridor_id)`` pairs.  Every
    directed road of ``roads`` must be listed exactly once.  Names use the V1
    nonblank convention.
    """
    if isinstance(corridors, (str, bytes)):
        raise ValueError('corridor attribution must be a sequence of road and corridor pairs')
    try:
        items = tuple(corridors)
    except TypeError as error:
        raise ValueError('corridor attribution must be a sequence of road and corridor pairs') from error
    indexed: dict[str, str] = {}
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError('corridor attribution must contain (road, corridor) pairs')
        road_id = require_name(item[0], 'corridor road')
        corridor_id = require_name(item[1], 'corridor id')
        if road_id not in roads:
            raise ValueError(f'unknown road {road_id!r} in corridor attribution')
        if road_id in indexed:
            raise ValueError(f'duplicate corridor attribution for road {road_id!r}')
        indexed[road_id] = corridor_id
    if set(indexed) != set(roads):
        raise ValueError('corridor attribution must cover every directed original road')
    return indexed
