"""Input fixtures for offline pair review and a read-only V1 fixture check."""

from dataclasses import dataclass
import json

from exchange.payload import BundlePayload
from routing.itineraries import calculate_itinerary
from survey.junctions import Junction
from survey.restrictions import Restriction
from survey.revisions import Revision
from survey.roads import Road
from tiles.fragments import Fragment
from tiles.layout import LayoutPlan, prepare_layout
from tiles.seams import Seam, SeamKey


@dataclass(frozen=True)
class PairFixture:
    junctions: tuple[Junction, ...]
    roads: tuple[Road, ...]
    restrictions: tuple[Restriction, ...]
    corridors: tuple[tuple[str, str], ...]
    plans: tuple[LayoutPlan, ...]


def _fixture(junction_ids, road_rows, corridors, restrictions=(), split_road=None):
    junctions = tuple(Junction(name) for name in junction_ids)
    roads = tuple(Road(*row) for row in road_rows)
    whole = tuple(Fragment(road.id, road.id, "west", 0, road.start, road.end, road.cost) for road in roads)
    plans = (LayoutPlan("single", ("west",), (), whole),)
    if split_road is not None:
        road = next(road for road in roads if road.id == split_road)
        seam = SeamKey(road.id, "join")
        cross = tuple(part for part in whole if part.road_id != road.id) + (
            Fragment(road.id + "-west", road.id, "west", 0, road.start, seam, 0),
            Fragment(road.id + "-east", road.id, "east", 1, seam, road.end, road.cost),
        )
        plans += (LayoutPlan("split", ("west", "east"), (Seam(seam, 4, 2),), cross),)
    return PairFixture(junctions, roads, restrictions, corridors, plans)


def three_branches():
    return _fixture(
        ("S", "A1", "A2", "B", "C", "T"),
        (("a1", "S", "A1", 1), ("a2", "A1", "A2", 1), ("a3", "A2", "T", 1),
         ("b1", "S", "B", 2), ("b2", "B", "T", 2), ("c1", "S", "C", 2), ("c2", "C", "T", 3)),
        (("a1", "P"), ("a2", "Q"), ("a3", "A-only"), ("b1", "P"), ("b2", "B-only"),
         ("c1", "Q"), ("c2", "C-only")),
    )


def forbidden_loop():
    return _fixture(
        ("S", "U", "V", "W", "T"),
        (("a", "S", "U", 1), ("b", "U", "V", 1), ("c", "V", "T", 1),
         ("d", "V", "W", 1), ("e", "W", "V", 1), ("z", "S", "T", 6)),
        (("a", "A"), ("b", "B"), ("c", "C"), ("d", "loop"), ("e", "loop"), ("z", "Z")),
        (Restriction("direct-turn", ("a", "b", "c")),),
        split_road="b",
    )


def tied_direct():
    return _fixture(
        ("S", "T"),
        (("a", "S", "T", 1), ("b", "S", "T", 1), ("c", "S", "T", 1)),
        (("a", "P"), ("b", "Q"), ("c", "R")),
    )


def main():
    for make_fixture, expected in (
        (three_branches, (("a1", "a2", "a3"), 3)),
        (forbidden_loop, (("a", "b", "d", "e", "c"), 5)),
        (tied_direct, (("a",), 1)),
    ):
        case = make_fixture()
        revision = Revision(1, case.junctions, case.roads, case.restrictions)
        for plan in case.plans:
            prepared = prepare_layout(revision, plan)
            payload = BundlePayload(case.junctions, case.roads, prepared.tiles, prepared.seams,
                                    prepared.chains, prepared.rules)
            actual = calculate_itinerary(payload, "S", "T")
            if (actual.roads, actual.cost) != expected:
                raise AssertionError(f"{make_fixture.__name__}/{plan.id}: V1 selected {actual!r}")
            print(json.dumps({"case": make_fixture.__name__, "layout": plan.id,
                              "single_route": actual.roads, "cost": actual.cost}))


if __name__ == "__main__":
    main()
