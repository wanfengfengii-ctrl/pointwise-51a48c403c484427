from review.record_store import PairRecord, RecordStore, ReviewRecord


def retrieve(records: RecordStore, record_id: int) -> ReviewRecord | None:
    return records.get(record_id)


def retrieve_pair(records: RecordStore, record_id: int) -> PairRecord | None:
    return records.get_pair(record_id)
