import json
import sqlite3
from dataclasses import replace

import pair_cases
from exchange.catalog import BundleCatalog
from exchange.imports import import_bundle
from exchange.manifest import build_manifest, canonical_json, pack_bundle, unpack_bundle
from review.issue import issue_pair
from review.record_store import RecordStore
from review.requests import ReviewRequest
from review.retrieve import retrieve, retrieve_pair
from storage import connect
from survey.junctions import Junction
from survey.restrictions import Restriction
from survey.revisions import load_revision
from survey.roads import Road
from tests.support import WorksiteTest, read_payload, reject_next_commit
from tiles.fragments import Fragment


class PairCaseTest(WorksiteTest):
    """Shared plumbing for the pure pair fixtures."""

    def load_case(self, make_fixture):
        case = make_fixture()
        self.case = case
        return case

    def save_case(self, corridors=None, rules=None):
        case = self.case
        return self.save(
            junctions=case.junctions,
            roads=case.roads,
            rules=case.restrictions if rules is None else rules,
            corridors=case.corridors if corridors is None else corridors,
        )

    def save(self, *, junctions=None, roads=None, rules=None, corridors=None):
        case = getattr(self, 'case', None)
        if case is not None:
            junctions = case.junctions if junctions is None else junctions
            roads = case.roads if roads is None else roads
            rules = case.restrictions if rules is None else rules
        return super().save(junctions=junctions, roads=roads, rules=rules, corridors=corridors)

    def publish_case(self, revision_id, layout_id='single'):
        plan = next((plan for plan in self.case.plans if plan.id == layout_id), self.case.plans[0])
        return self.publish(revision_id, plan)

    def issue_pair(self, bundle_id, start='S', end='T'):
        return issue_pair(self.accepted, self.records, bundle_id, start, end)

    def shifted(self, overrides):
        return tuple((road_id, overrides.get(road_id, corridor_id)) for road_id, corridor_id in self.case.corridors)

    def assert_pair(self, record, main, backup, total):
        if main is None:
            self.assertIsNone(record.main)
            self.assertIsNone(record.backup)
            self.assertIsNone(record.total_cost)
            self.assertIsNone(total)
            return
        self.assertEqual((record.main.roads, record.main.cost), main)
        self.assertEqual((record.backup.roads, record.backup.cost), backup)
        self.assertEqual(record.total_cost, total)


class ThreeBranchesTests(PairCaseTest):
    def test_cheapest_disjoint_pair_and_revision_shift(self):
        self.load_case(pair_cases.three_branches)
        revision = self.save_case()
        bundle_id = self.accept(self.publish_case(revision))
        record = self.issue_pair(bundle_id)
        self.assert_pair(record, (('b1', 'b2'), 4), (('c1', 'c2'), 5), 9)
        self.assertEqual(record.main.corridors, frozenset({'P', 'B-only'}))
        self.assertEqual(record.backup.corridors, frozenset({'Q', 'C-only'}))
        self.assertEqual(record.request, ReviewRequest(bundle_id, 'S', 'T'))
        self.assertEqual(self.issue_pair(bundle_id).main, record.main)

        shifted_revision = self.save_case(self.shifted({'a2': 'A-private'}))
        shifted_bundle = self.accept(self.publish_case(shifted_revision))
        shifted = self.issue_pair(shifted_bundle)
        self.assert_pair(shifted, (('a1', 'a2', 'a3'), 3), (('c1', 'c2'), 5), 8)
        self.assertEqual(shifted.total_cost, 8)
        self.assertEqual(retrieve_pair(RecordStore(self.offline), record.id), record)

    def test_both_layouts_agree(self):
        self.load_case(pair_cases.three_branches)
        revision = self.save_case()
        for layout_id in ('single', 'split'):
            with self.subTest(layout=layout_id):
                bundle_id = self.accept(self.publish_case(revision, layout_id))
                self.assert_pair(self.issue_pair(bundle_id), (('b1', 'b2'), 4), (('c1', 'c2'), 5), 9)


class ForbiddenLoopTests(PairCaseTest):
    def test_loop_continuation_single_and_split(self):
        self.load_case(pair_cases.forbidden_loop)
        revision = self.save_case()
        for layout_id in ('single', 'split'):
            with self.subTest(layout=layout_id):
                bundle_id = self.accept(self.publish_case(revision, layout_id))
                record = self.issue_pair(bundle_id)
                self.assert_pair(record, (('a', 'b', 'd', 'e', 'c'), 5), (('z',), 6), 11)
                self.assertEqual(record.main.corridors, frozenset({'A', 'B', 'C', 'loop'}))
                self.assertEqual(record.backup.corridors, frozenset({'Z'}))

    def test_span_split_keeps_directed_chain(self):
        self.load_case(pair_cases.forbidden_loop)
        revision = self.save_case()
        bundle_id = self.accept(self.publish_case(revision, 'split'))
        _, payload = read_payload(self.accepted.find_accepted(bundle_id))
        bridge = next(chain for chain in payload.chains if chain.road_id == 'b')
        self.assertEqual(bridge.refs, (('west', 'b-west'), ('east', 'b-east')))
        self.assert_pair(self.issue_pair(bundle_id), (('a', 'b', 'd', 'e', 'c'), 5), (('z',), 6), 11)

    def test_shared_corridor_leaves_no_pair(self):
        self.load_case(pair_cases.forbidden_loop)
        revision = self.save_case(self.shifted({'z': 'loop'}))
        bundle_id = self.accept(self.publish_case(revision))
        record = self.issue_pair(bundle_id)
        self.assert_pair(record, None, None, None)
        self.assertEqual(retrieve_pair(RecordStore(self.offline), record.id), record)


class TiedDirectTests(PairCaseTest):
    def test_tie_order_and_corridor_shift(self):
        self.load_case(pair_cases.tied_direct)
        revision = self.save_case()
        bundle_id = self.accept(self.publish_case(revision))
        self.assert_pair(self.issue_pair(bundle_id), (('a',), 1), (('b',), 1), 2)

        shifted_revision = self.save_case(self.shifted({'b': 'P'}))
        shifted_bundle = self.accept(self.publish_case(shifted_revision))
        self.assert_pair(self.issue_pair(shifted_bundle), (('a',), 1), (('c',), 1), 2)


class PairContractTests(PairCaseTest):
    def setUp(self):
        super().setUp()
        self.load_case(pair_cases.three_branches)

    def test_attribution_validation(self):
        for broken in (
            self.case.corridors[:-1],
            (*self.case.corridors, ('a1', 'P')),
            (*self.case.corridors, ('ghost', 'P')),
            (*self.case.corridors[:-1], ('c2', '  ')),
        ):
            with self.subTest(corridors=broken), self.assertRaises(ValueError):
                self.save_case(broken)
        self.assertEqual(self.revision_ids(), [])
        empty = self.save(roads=(), junctions=(Junction('S'),), rules=(), corridors=())
        self.assertEqual(load_revision(self.revisions, empty).corridors, ())

    def test_attribution_participates_in_digest_and_freeze(self):
        revision = self.save_case()
        legacy = self.save()
        addressed = self.publish_case(revision)
        plain = self.publish_case(legacy)
        self.assertNotEqual(addressed[0], plain[0])
        _, addressed_payload = read_payload(addressed[1])
        _, plain_payload = read_payload(plain[1])
        self.assertEqual(addressed_payload.corridors, tuple(sorted(self.case.corridors)))
        self.assertIsNone(plain_payload.corridors)
        self.assertEqual(load_revision(self.revisions, revision).corridors, tuple(sorted(self.case.corridors)))
        shifted = self.save_case(self.shifted({'a2': 'A-private'}))
        self.assertEqual(load_revision(self.revisions, revision).corridors, tuple(sorted(self.case.corridors)))
        self.assertNotEqual(load_revision(self.revisions, shifted).corridors, tuple(sorted(self.case.corridors)))

    def test_import_rejects_missing_reattested_attribution(self):
        revision = self.save_case()
        bundle_id, wire = self.publish_case(revision)
        manifest, encoded = unpack_bundle(wire)
        document = json.loads(encoded)
        document['corridors'] = document['corridors'][:-1]
        broken_payload = canonical_json(document)
        forged = build_manifest(manifest.revision_id, manifest.layout_id, broken_payload)
        broken_wire = pack_bundle(forged, broken_payload)
        self.assertEqual(unpack_bundle(broken_wire), (forged, broken_payload))
        with self.assertRaises(ValueError):
            import_bundle(self.accepted, broken_wire)
        self.assertIsNone(self.accepted.find_accepted(forged.bundle_id))
        self.assertEqual(self.bundle_ids(self.offline, 'accepted'), [])
        self.assertEqual(import_bundle(self.accepted, wire), bundle_id)

    def test_null_attribution_is_invalid(self):
        revision = self.save_case()
        _, wire = self.publish_case(revision)
        manifest, encoded = unpack_bundle(wire)
        document = json.loads(encoded)
        document['corridors'] = None
        payload = canonical_json(document)
        forged = build_manifest(manifest.revision_id, manifest.layout_id, payload)
        with self.assertRaises(ValueError):
            import_bundle(self.accepted, pack_bundle(forged, payload))

    def test_legacy_and_unknown_bundles(self):
        legacy = self.accept(self.publish_case(self.save()))
        self.assert_itinerary(self.issue(legacy, 'S', 'T'), 3, ('a1', 'a2', 'a3'))
        with self.assertRaises(ValueError):
            self.issue_pair(legacy)
        with self.assertRaises(KeyError):
            self.issue_pair('pkg-absent')
        self.assertEqual(self.record_pair_ids(), [])

    def test_endpoint_rules(self):
        revision = self.save_case()
        bundle_id = self.accept(self.publish_case(revision))
        for start, end in (('S', 'S'), ('S', 'ghost'), ('ghost', 'T'), ('S', None)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.issue_pair(bundle_id, start, end)
        self.assertEqual(self.record_pair_ids(), [])
        forward = self.issue_pair(bundle_id, 'S', 'T')
        reverse = self.issue_pair(bundle_id, 'T', 'S')
        self.assertIsNone(reverse.main)
        self.assert_pair(forward, (('b1', 'b2'), 4), (('c1', 'c2'), 5), 9)
        self.assertEqual(self.record_pair_ids(), [forward.id, reverse.id])

    def test_commit_failure_leaves_no_pair(self):
        revision = self.save_case()
        bundle_id = self.accept(self.publish_case(revision))
        first = self.issue_pair(bundle_id)
        reject_next_commit(self.offline, 'pair_records')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            self.issue_pair(bundle_id, 'T', 'S')
        self.assertEqual(self.record_pair_ids(), [first.id])
        self.assertEqual(retrieve_pair(RecordStore(self.offline), first.id), first)
        with connect(self.offline) as database:
            self.assertEqual(database.execute('SELECT * FROM test_pending').fetchall(), [])
            database.execute('DROP TRIGGER test_reject_commit')
        retry = self.issue_pair(bundle_id, 'T', 'S')
        self.assert_pair(retry, None, None, None)
        self.assertEqual(retrieve_pair(RecordStore(self.offline), first.id), first)

    def record_pair_ids(self):
        with connect(self.offline) as database:
            return [row[0] for row in database.execute('SELECT id FROM pair_records ORDER BY id')]
