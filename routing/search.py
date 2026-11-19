from heapq import heappop, heappush

from routing.network import RoutingNetwork
from routing.permissions import RestrictionPolicy, check_passage


def find_shortest_route(
    network: RoutingNetwork, policy: RestrictionPolicy, start: str, end: str
) -> tuple[str, ...] | None:
    if start not in network.junctions or end not in network.junctions:
        raise ValueError('route endpoints must be real junctions in the selected bundle')
    queue = [(0, (), start, ())]
    best = {(start, ()): (0, ())}
    while queue:
        cost, route, junction, progress = heappop(queue)
        if best[junction, progress] != (cost, route):
            continue
        if junction == end:
            return route
        for passage in network.outgoing.get(junction, ()):
            road = passage.road
            next_progress = check_passage(policy, progress, road.id)
            if next_progress is None:
                continue
            state = road.end, next_progress
            candidate = cost + passage.cost, (*route, road.id)
            # Positive complete-road costs exclude strict-prefix ties at a state.
            if state not in best or candidate < best[state]:
                best[state] = candidate
                heappush(queue, (*candidate, *state))
    return None
