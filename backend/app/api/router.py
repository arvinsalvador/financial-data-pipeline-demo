from fastapi import APIRouter

from app.api.routes.generated_datasets import router as generated_datasets_router
from app.api.routes.governance import router as governance_router
from app.api.routes.health import router as health_router
from app.api.routes.ingestions import router as ingestions_router
from app.api.routes.invoice_collections import group_router as invoice_collections_group_router
from app.api.routes.invoice_collections import router as invoice_collections_router
from app.api.routes.messy_datasets import router as messy_datasets_router
from app.api.routes.normalizations import router as normalizations_router
from app.api.routes.payroll_reconciliations import group_router as payroll_group_router
from app.api.routes.payroll_reconciliations import router as payroll_reconciliations_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.reconciliations import (
    match_group_router,
)
from app.api.routes.reconciliations import (
    router as reconciliations_router,
)
from app.api.routes.sources import router as sources_router
from app.api.routes.validation import router as validation_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(ingestions_router, tags=["ingestion"])
api_router.include_router(generated_datasets_router, tags=["generated datasets"])
api_router.include_router(messy_datasets_router, tags=["messy datasets"])
api_router.include_router(normalizations_router, tags=["normalization"])
api_router.include_router(governance_router, tags=["governance"])
api_router.include_router(profiles_router, tags=["profiling"])
api_router.include_router(sources_router, tags=["sources"])
api_router.include_router(validation_router, tags=["validation"])
api_router.include_router(reconciliations_router, tags=["reconciliation"])
api_router.include_router(match_group_router, tags=["reconciliation"])
api_router.include_router(payroll_reconciliations_router, tags=["payroll reconciliation"])
api_router.include_router(payroll_group_router, tags=["payroll reconciliation"])
api_router.include_router(invoice_collections_router, tags=["invoice collections reconciliation"])
api_router.include_router(
    invoice_collections_group_router, tags=["invoice collections reconciliation"]
)
