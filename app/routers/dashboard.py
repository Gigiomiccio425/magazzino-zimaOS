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
    return render(request, "dashboard.html", {"cc": cc, "stats": cc["stats"], "SERVICE_STATUSES": SERVICE_STATUSES,
                                              "SEVERITIES": SEVERITIES, "INCIDENT_STATUSES": INCIDENT_STATUSES})
