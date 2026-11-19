from collections.abc import Iterable
from dataclasses import dataclass

from tiles.evidence import RuleEvidence


Progress = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RestrictionPolicy:
    blocked: frozenset[Progress]
    first: frozenset[Progress]
    first_two: frozenset[Progress]


def compile_permissions(evidence: Iterable[RuleEvidence]) -> RestrictionPolicy:
    blocked = frozenset(rule.roads for rule in evidence)
    return RestrictionPolicy(
        blocked,
        frozenset(sequence[:1] for sequence in blocked),
        frozenset(sequence[:2] for sequence in blocked),
    )


def check_passage(policy: RestrictionPolicy, progress: Progress, road_id: str) -> Progress | None:
    candidate = (*progress, road_id)
    if candidate in policy.blocked:
        return None
    # A shorter matching suffix is also a suffix of the longest retained prefix.
    if candidate[-2:] in policy.first_two:
        return candidate[-2:]
    if candidate[-1:] in policy.first:
        return candidate[-1:]
    return ()
