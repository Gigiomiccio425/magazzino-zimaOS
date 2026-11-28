"""Dashboard: centro di comando (servizi, incidenti, scorte, test, garanzie, attivita')."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import render
from ..models import INCIDENT_STATUSES, SERVICE_STATUSES, SEVERITIES
from ..services.dashboard import command_center
from ..timeutil import utcnow

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    cc = command_center(db, utcnow())
    from ..services import alerts, purchasing
    cc["warranties"] = alerts.expiring_warranties(db, 60)[:8]
    cc["upcoming"] = alerts.upcoming_maintenances(db, 7)[:5]
    cc["to_reorder"] = sum(len(v) for v in purchasing.reorder_list(db).values())
    return render(request, "dashboard.html", {"cc": cc, "stats": cc["stats"], "SERVICE_STATUSES": SERVICE_STATUSES,
                                              "SEVERITIES": SEVERITIES, "INCIDENT_STATUSES": INCIDENT_STATUSES})
