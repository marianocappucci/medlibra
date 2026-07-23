from datetime import date

from fastapi import APIRouter, Depends

from ..dependencies import get_dashboard_service
from ..services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(
    date_from: date, date_to: date,
    dashboard: DashboardService = Depends(get_dashboard_service),
):
    return dashboard.summary(date_from, date_to)
