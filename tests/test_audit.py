from types import SimpleNamespace

from sqlalchemy import text

from app.models import AuditLog
from app.services import audit


def _signer():
    return SimpleNamespace(operator_id=None, signature_id=None)


def test_record_links_hashes(db):
    a = audit.record(db, entity_type="component", entity_id=1, action="create", after={"name": "A"})
    b = audit.record(db, entity_type="component", entity_id=1, action="update",
                     before={"name": "A"}, after={"name": "B"}, signer=_signer())
    db.commit()
    assert a.prev_hash == audit.GENESIS
    assert b.prev_hash == a.hash
    assert len(a.hash) == 64 and a.hash != b.hash


def test_changed_only_diff():
    before, after = audit.changed({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "c": 3, "d": 4})
    assert before == {"b": 2, "d": None}
    assert after == {"b": 5, "d": 4}


def test_snapshot_fields():
    obj = SimpleNamespace(name="X", qty=2, other="no")
    assert audit.snapshot(obj, ["name", "qty"]) == {"name": "X", "qty": 2}


def test_verify_chain_ok_and_detects_tamper(db):
    for i in range(3):
        audit.record(db, entity_type="machine", entity_id=i, action="create", after={"n": i})
    db.commit()
    report = audit.verify_chain(db)
    assert report.ok and report.checked == 3 and report.first_bad_id is None
    second = db.query(AuditLog).order_by(AuditLog.id).all()[1]
    db.execute(text("UPDATE audit_log SET after = :v WHERE id = :id"), {"v": '{"n": 99}', "id": second.id})
    db.commit()
    db.expire_all()
    report = audit.verify_chain(db)
    assert not report.ok and report.first_bad_id == second.id


def test_audit_page_lists(client, db):
    audit.record(db, entity_type="component", entity_id=7, action="create", after={"name": "Visibile"})
    db.commit()
    html = client.get("/audit").text
    assert "component" in html and "create" in html
    assert client.get("/audit/verify").status_code == 200
