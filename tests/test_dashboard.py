from datetime import date, timedelta

from app.models import Component, Incident, Location, Maintenance, Service
from app.services.audit import record
from app.services.dashboard import command_center
from app.timeutil import utcnow


def test_empty_db(client, db):
    cc = command_center(db, utcnow())
    assert cc["stats"]["total"] == 0 and cc["inventory_value_cents"] == 0
    assert cc["open_incidents_by_severity"] == {} and cc["low_stock"] == [] and cc["to_test_count"] == 0
    assert client.get("/").status_code == 200


def test_sections_with_data(client, db):
    now = utcnow()
    today = now.date()
    s1, s2 = Service(slug="a", name="A", status="operational"), Service(slug="b", name="B", status="major_outage")
    db.add_all([
        s1, s2,
        Incident(title="Grave", severity="SEV1", status="open"),
        Incident(title="Medio", severity="SEV3", status="investigating"),
        Incident(title="Chiuso", severity="SEV1", status="resolved"),
        Maintenance(title="Domani", starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1)),
        Maintenance(title="Tra un mese", starts_at=now + timedelta(days=30), ends_at=now + timedelta(days=30, hours=1)),
        Component(name="Cavi", tracking="quantity", quantity=1, min_stock=5, purchase_price=1000, attributes={}),
        Component(name="Da provare", status="to_test", purchase_price=25050, attributes={}),
        Component(name="Garanzia", warranty_until=today + timedelta(days=10), attributes={}),
        Component(name="Garanzia lontana", warranty_until=today + timedelta(days=200), attributes={}),
        Component(name="Cestino", purchase_price=99999, deleted_at=now, attributes={}),
        Location(name="Mai verificata"),
    ])
    db.flush()
    record(db, entity_type="component", entity_id=1, action="create", after={"name": "Cavi"})
    db.commit()
    cc = command_center(db, now)
    assert cc["services_by_status"] == {"operational": 1, "major_outage": 1}
    assert cc["open_incidents_by_severity"] == {"SEV1": 1, "SEV3": 1}
    assert [m.title for m in cc["upcoming_maintenance"]] == ["Domani"]
    assert [c.name for c in cc["low_stock"]] == ["Cavi"]
    assert cc["to_test_count"] == 1
    assert [c.name for c in cc["warranty_expiring"]] == ["Garanzia"]
    assert [l.name for l in cc["overdue_locations"]] == ["Mai verificata"]
    assert cc["inventory_value_cents"] == 1000 + 25050
    assert cc["recent_activity"][0].action == "create"
    html = client.get("/").text
    for text in ("Grave", "Cavi", "Garanzia", "260,50"):
        assert text in html
