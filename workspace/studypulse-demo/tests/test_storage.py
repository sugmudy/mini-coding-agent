from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from studypulse.models import StudyRecord
from studypulse.storage import JsonRecordStore
from studypulse.webapp import create_server


@pytest.fixture()
def store() -> JsonRecordStore:
    with TemporaryDirectory() as tmpdir:
        yield JsonRecordStore(Path(tmpdir) / "records.json")


def test_create_record_strips_subject_and_persists(store: JsonRecordStore) -> None:
    record = store.create_record("  Mathematics  ", 45)

    assert record.subject == "Mathematics"
    assert record.completed is False

    records = store.list_records()
    assert records == [record]


def test_from_dict_strips_subject_before_persisting() -> None:
    record = StudyRecord.from_dict({"id": "abc", "subject": "  Physics  ", "minutes": 30, "completed": False})

    assert record.subject == "Physics"


def test_create_record_validates_fields() -> None:
    with pytest.raises(ValueError):
        StudyRecord.create("   ", 30)
    with pytest.raises(ValueError):
        StudyRecord.create("Math", 0)
    with pytest.raises(ValueError):
        StudyRecord.create("Math", 601)
    with pytest.raises(ValueError):
        StudyRecord.create("Math", True)
    with pytest.raises(ValueError):
        StudyRecord.create("Math", 30, completed="no")


def test_create_record_rejects_boolean_minutes(store: JsonRecordStore) -> None:
    with pytest.raises(ValueError):
        store.create_record("Math", True)


def test_toggle_completed_is_idempotent(store: JsonRecordStore) -> None:
    record = store.create_record("Physics", 50)

    first = store.set_completed(record.id, True)
    second = store.set_completed(record.id, True)
    third = store.set_completed(record.id, False)

    assert first.completed is True
    assert second.completed is True
    assert third.completed is False
    assert store.list_records()[0].completed is False


def test_set_completed_unknown_id_raises(store: JsonRecordStore) -> None:
    with pytest.raises(KeyError):
        store.set_completed("missing", True)


def test_delete_record_persists_and_removes_item(store: JsonRecordStore) -> None:
    first = store.create_record("Chemistry", 30)
    second = store.create_record("Biology", 45)

    deleted = store.delete_record(first.id)

    assert deleted == first
    assert store.list_records() == [second]
    assert store.delete_record(second.id) == second
    assert store.list_records() == []


def test_delete_unknown_id_raises(store: JsonRecordStore) -> None:
    with pytest.raises(KeyError):
        store.delete_record("missing")


def test_concurrent_creates_do_not_lose_records_and_json_stays_valid() -> None:
    with TemporaryDirectory() as tmpdir:
        store = JsonRecordStore(Path(tmpdir) / "records.json")

        def create_many(prefix: str) -> None:
            for i in range(25):
                store.create_record(f"{prefix}-{i}", i + 1)

        threads = [Thread(target=create_many, args=(f"t{n}",)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        records = store.list_records()
        assert len(records) == 150
        parsed = store.path.read_text(encoding="utf-8")
        assert parsed.strip().startswith("[")
        assert len(__import__("json").loads(parsed)) == 150


def test_http_api_supports_list_create_toggle_and_delete() -> None:
    with TemporaryDirectory() as tmpdir:
        store = JsonRecordStore(Path(tmpdir) / "records.json")
        server = create_server("127.0.0.1", 0, store_path=store.path)
        thread = Thread(target=server.serve_forever)
        thread.start()
        host, port = server.server_address
        base = f"http://{host}:{port}"
        try:
            with urlopen(f"{base}/api/records") as response:
                data = response.read().decode("utf-8")
            assert data == "[]"

            create_req = Request(
                f"{base}/api/records",
                data=b'{"subject":"Chemistry","minutes":30,"completed":false}',
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(create_req) as response:
                payload = response.read().decode("utf-8")
            assert '"subject": "Chemistry"' in payload

            record_id = store.list_records()[0].id
            patch_req = Request(
                f"{base}/api/records/{record_id}",
                data=b'{"completed":true}',
                method="PATCH",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(patch_req) as response:
                payload = response.read().decode("utf-8")
            assert '"completed": true' in payload

            delete_req = Request(f"{base}/api/records/{record_id}", method="DELETE")
            with urlopen(delete_req) as response:
                payload = response.read().decode("utf-8")
            assert '"subject": "Chemistry"' in payload
            assert store.list_records() == []

            with pytest.raises(HTTPError):
                urlopen(
                    Request(
                        f"{base}/api/records/missing",
                        method="DELETE",
                    )
                )

            with pytest.raises(HTTPError):
                urlopen(
                    Request(
                        f"{base}/api/records/missing",
                        data=b'{"completed":true}',
                        method="PATCH",
                        headers={"Content-Type": "application/json"},
                    )
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
