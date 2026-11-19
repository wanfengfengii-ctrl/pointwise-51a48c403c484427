from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from exchange.payload import BundlePayload
from survey.roads import Road
from tiles.costs import sum_fragment_costs
from tiles.fragments import FragmentChain


@dataclass(frozen=True, slots=True)
class Passage:
    road: Road
    chain: FragmentChain
    cost: int


@dataclass(frozen=True, slots=True)
class RoutingNetwork:
    junctions: frozenset[str]
    outgoing: Mapping[str, tuple[Passage, ...]]
    by_road: Mapping[str, Passage]


def build_network(payload: BundlePayload) -> RoutingNetwork:
    chains = {chain.road_id: chain for chain in payload.chains}
    roads = {}
    outgoing = defaultdict(list)
    for road in sorted(payload.roads, key=lambda road: road.id):
        # Accepted chains only join at their real endpoints. Each edge is one full passage.
        chain = chains[road.id]
        passage = Passage(road, chain, sum_fragment_costs(chain.fragments))
        roads[road.id] = passage
        outgoing[road.start].append(passage)
    return RoutingNetwork(
        frozenset(junction.id for junction in payload.junctions),
        MappingProxyType({junction: tuple(passages) for junction, passages in outgoing.items()}),
        MappingProxyType(roads),
    )
