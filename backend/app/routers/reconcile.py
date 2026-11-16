from fastapi import APIRouter

from app.services import reconcile_service as svc

router = APIRouter(prefix="/reconcile", tags=["reconcile"])


@router.get("/sales")
def reconcile_sales():
    return svc.reconcile_sales()
