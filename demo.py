import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pair_cases
from exchange.catalog import BundleCatalog
from exchange.imports import import_bundle
from exchange.publish import publish
from review.compare import compare
from review.issue import issue, issue_pair
from review.record_store import RecordStore
from review.requests import ReviewRequest
from review.retrieve import retrieve, retrieve_pair
from survey.junctions import Junction
from survey.restrictions import Restriction
from survey.revision_store import RevisionStore
from survey.revisions import save_revision
from survey.roads import Road
from tiles.fragments import Fragment
from tiles.layout import LayoutPlan
from tiles.seams import Seam, SeamKey


SAMPLES = Path(__file__).resolve().parent / 'samples'


def _endpoint(value):
    return SeamKey(*value) if isinstance(value, list) else value


def load_sample():
    survey = json.loads((SAMPLES / 'network.json').read_text(encoding='utf-8'))
    layouts = json.loads((SAMPLES / 'layouts.json').read_text(encoding='utf-8'))
    plans = {}
    for name, layout in layouts.items():
        seams = tuple(Seam(SeamKey(road, label), x, y) for road, label, x, y in layout['seams'])
        fragments = tuple(
            Fragment(label, road, tile, ordinal, _endpoint(start), _endpoint(end), cost)
            for label, road, tile, ordinal, start, end, cost in layout['fragments']
        )
        plans[name] = LayoutPlan(name, tuple(layout['tiles']), seams, fragments)
    return (
        tuple(Junction(name) for name in survey['junctions']),
        tuple(Road(*road) for road in survey['roads']),
        tuple(Restriction(name, tuple(roads)) for name, roads in survey['restrictions']),
        plans,
    )


def _result(record):
    return {'cost': record.itinerary.cost, 'roads': list(record.itinerary.roads)}


def _pair_result(record):
    return {
        'main': None if record.main is None else {'roads': list(record.main.roads), 'cost': record.main.cost},
        'backup': None if record.backup is None else {'roads': list(record.backup.roads), 'cost': record.backup.cost},
        'total_cost': record.total_cost,
    }


def _pair_scenario(make_fixture, shifts=None, layout='split'):
    """Issue a pair after the source database is gone, then reopen by number."""
    case = make_fixture()
    corridors = tuple((road, (shifts or {}).get(road, corridor)) for road, corridor in case.corridors)
    with TemporaryDirectory(prefix='chengwan-pair-') as directory:
        source = Path(directory) / 'survey.sqlite3'
        offline = Path(directory) / 'review.sqlite3'
        revisions, published = RevisionStore(source), BundleCatalog(source)
        accepted, records = BundleCatalog(offline), RecordStore(offline)
        for store in (revisions, published, accepted, records):
            store.initialize()
        revision = save_revision(revisions, case.junctions, case.roads, case.restrictions, corridors=corridors)
        plan = next(plan for plan in case.plans if plan.id == layout)
        bundle_id, wire = publish(revisions, published, revision, plan)
        source.unlink()  # 断源：源库删除后仍凭已发布件接纳并签发
        if import_bundle(accepted, wire) != bundle_id:
            raise AssertionError('accepted the wrong pair package')
        issued = issue_pair(accepted, records, bundle_id, 'S', 'T')
        reopened = retrieve_pair(RecordStore(offline), issued.id)
        if reopened != issued:
            raise AssertionError('reopened pair order differs from the issued snapshot')
        return case, bundle_id, issued, reopened


def run_pair_demo():
    case, bundle_id, issued, reopened = _pair_scenario(pair_cases.forbidden_loop)
    forbidden = _pair_result(issued)

    shifted_case, shifted_bundle, shifted, _ = _pair_scenario(pair_cases.forbidden_loop, {'z': 'loop'})
    shared = _pair_result(shifted)

    tied_case, tied_bundle, tied, _ = _pair_scenario(pair_cases.tied_direct, layout='single')
    tied_result = _pair_result(tied)

    expected_forbidden = {'main': {'roads': ['a', 'b', 'd', 'e', 'c'], 'cost': 5},
                          'backup': {'roads': ['z'], 'cost': 6}, 'total_cost': 11}
    expected_shared = {'main': None, 'backup': None, 'total_cost': None}
    expected_tied = {'main': {'roads': ['a'], 'cost': 1}, 'backup': {'roads': ['b'], 'cost': 1}, 'total_cost': 2}
    actual = {'forbidden_loop': forbidden, 'shared_corridor': shared, 'tied_direct': tied_result}
    expected = {'forbidden_loop': expected_forbidden, 'shared_corridor': expected_shared, 'tied_direct': expected_tied}
    if actual != expected:
        raise AssertionError(f'pair review differs from the hand calculation: {actual!r}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'pair-v1',
        'input': {'endpoints': ['S', 'T'], 'split_road': 'b', 'rule': ['a', 'b', 'c'],
                  'corridors': {road: corridor for road, corridor in shifted_case.corridors}},
        'expected': expected,
        'actual': actual,
        'downstream_expected': {'reopened': expected_forbidden, 'bundle': bundle_id},
        'downstream_actual': {'reopened': _pair_result(reopened), 'bundle': bundle_id},
        'code_paths': ['survey/corridors.py', 'survey/revisions.py', 'exchange/payload.py',
                       'exchange/imports.py', 'routing/pairs.py', 'review/issue.py', 'review/retrieve.py'],
        'oracle': 'Enumerate corridor-disjoint S-to-T route pairs, minimise the sum, and reopen the stored order.',
    }, sort_keys=True))


def main():
    run_pair_demo()
    with TemporaryDirectory(prefix='chengwan-demo-') as directory:
        source = Path(directory) / 'survey.sqlite3'
        offline = Path(directory) / 'review.sqlite3'
        revisions, published = RevisionStore(source), BundleCatalog(source)
        accepted, records = BundleCatalog(offline), RecordStore(offline)
        for store in (revisions, published, accepted, records):
            store.initialize()
        junctions, roads, rules, plans = load_sample()
        before = save_revision(revisions, junctions, roads, rules)
        single_id, single_wire = publish(revisions, published, before, plans['single'])
        before_id, before_wire = publish(revisions, published, before, plans['split'])
        after = save_revision(revisions, junctions, roads, ())
        after_id, after_wire = publish(revisions, published, after, plans['split'])
        source.unlink()

        issued = []
        for bundle_id, wire in ((single_id, single_wire), (before_id, before_wire), (after_id, after_wire)):
            if import_bundle(accepted, wire) != bundle_id:
                raise AssertionError('accepted the wrong package')
            issued.append(issue(accepted, records, ReviewRequest(bundle_id, 'X', 'T')))

        reopened = RecordStore(offline)
        previous = retrieve(reopened, issued[1].id)
        current = retrieve(reopened, issued[2].id)
        comparison = compare(reopened, previous.id, current.id)
        expected = {
            'single': {'cost': 5, 'roads': ['h', 'd', 'b', 'c']},
            'split': {'cost': 5, 'roads': ['h', 'd', 'b', 'c']},
            'correction': {'cost': 4, 'roads': ['a', 'b', 'c']},
        }
        actual = {'single': _result(issued[0]), 'split': _result(previous), 'correction': _result(current)}
        downstream_expected = {'old_bundle': before_id, 'new_bundle': after_id, 'route_changed': True, 'cost_changed': True}
        downstream_actual = {
            'old_bundle': comparison.before.request.bundle_id,
            'new_bundle': comparison.after.request.bundle_id,
            'route_changed': comparison.route_changed,
            'cost_changed': comparison.cost_changed,
        }
        if actual != expected or downstream_actual != downstream_expected or issued[1:] != [previous, current]:
            raise AssertionError(f'route review differs from the hand calculation: {actual!r}, {downstream_actual!r}')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v7',
            'input': {'roads': [[road.id, road.start, road.end, road.cost] for road in roads],
                      'old_rules': [['a', 'b', 'c']], 'new_rules': [], 'split_road': 'b', 'endpoints': ['X', 'T']},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['exchange/publish.py', 'exchange/imports.py', 'routing/search.py',
                           'review/issue.py', 'review/retrieve.py', 'review/compare.py'],
            'oracle': 'Manually sum the two possible X-to-T routes and discard a-b-c for the original revision.',
        }, sort_keys=True))


if __name__ == '__main__':
    main()
