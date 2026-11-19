from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count

from exchange.payload import BundlePayload
from routing.network import build_network
from routing.permissions import compile_permissions, check_passage


@dataclass(frozen=True, slots=True)
class RouteFigure:
    roads: tuple[str, ...]
    corridors: frozenset[str]
    cost: int


def corridor_index(payload: BundlePayload) -> dict[str, str]:
    if payload.corridors is None:
        raise ValueError('bundle has no corridor attribution')
    index: dict[str, str] = {}
    for road_id, corridor_id in payload.corridors:
        if road_id in index:
            raise ValueError(f'duplicate corridor attribution for road {road_id!r}')
        index[road_id] = corridor_id
    if set(index) != {road.id for road in payload.roads}:
        raise ValueError('corridor attribution does not cover the bundle roads')
    return index


def enumerate_figures(payload: BundlePayload, start: str, end: str) -> list[RouteFigure]:
    """Return the cheapest route for every distinct set of used corridors.

    A route is a completed sequence of original directed roads.  Artificial
    seams only continue their own chain; the underlying network edges already
    represent whole original roads, so seams never appear here.  Revisiting a
    junction or a corridor is allowed; a route only terminates when it reaches
    ``end``.  The search state carries the set of corridors used so far, so the
    cheapest road sequence per corridor set is exact even when a route loops.
    """
    network = build_network(payload)
    policy = compile_permissions(payload.rules)
    corridors = corridor_index(payload)
    best = {(start, (), frozenset()): (0, ())}
    queue = []
    ticks = count()
    heappush(queue, (0, (), next(ticks), start, (), frozenset()))
    figures: dict[frozenset[str], tuple[int, tuple[str, ...]]] = {}
    while queue:
        cost, route, _, junction, progress, used = heappop(queue)
        if best.get((junction, progress, used)) != (cost, route):
            continue
        if junction == end:
            current = figures.get(used)
            if current is None or (cost, route) < current:
                figures[used] = (cost, route)
        for passage in network.outgoing.get(junction, ()):
            road = passage.road
            next_progress = check_passage(policy, progress, road.id)
            if next_progress is None:
                continue
            next_used = used | {corridors[road.id]}
            state = road.end, next_progress, next_used
            candidate = cost + passage.cost, (*route, road.id)
            if state not in best or candidate < best[state]:
                best[state] = candidate
                heappush(queue, (candidate[0], candidate[1], next(ticks), *state))
    return [
        RouteFigure(roads, used, cost) for used, (cost, roads) in figures.items()
    ]


def calculate_pair(
    payload: BundlePayload, start: str, end: str
) -> tuple[RouteFigure | None, RouteFigure | None, int | None]:
    if start == end:
        raise ValueError('pair review endpoints must be two different real junctions')
    figures = enumerate_figures(payload, start, end)
    best: tuple[int, tuple[tuple[str, ...], tuple[str, ...]], RouteFigure, RouteFigure] | None = None
    for first_index in range(len(figures)):
        for second_index in range(first_index + 1, len(figures)):
            one, other = figures[first_index], figures[second_index]
            if one.corridors & other.corridors:
                continue
            main, backup = sorted((one, other), key=lambda figure: (figure.cost, figure.roads))
            total = main.cost + backup.cost
            key = (main.roads, backup.roads)
            if best is None or total < best[0] or (total == best[0] and key < best[1]):
                best = (total, key, main, backup)
    if best is None:
        return None, None, None
    return best[2], best[3], best[0]
