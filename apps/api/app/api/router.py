from fastapi import APIRouter

from app.api.routes import (
    alerts,
    audit,
    auth,
    companies,
    content,
    crawl,
    geo_config,
    geo_v1,
    health,
    projects,
    providers,
    queue,
    reports,
    report_templates,
    review_rules,
    usage,
    users,
)
from app.v1.routes import router as cleanroom_v1_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(alerts.router)
api_router.include_router(audit.router)
api_router.include_router(usage.router)
api_router.include_router(users.router)
api_router.include_router(companies.router)
api_router.include_router(projects.router)
api_router.include_router(geo_config.router)
api_router.include_router(geo_v1.router)
api_router.include_router(cleanroom_v1_router)
api_router.include_router(providers.router)
api_router.include_router(queue.router)
api_router.include_router(crawl.router)
api_router.include_router(reports.router)
api_router.include_router(report_templates.router)
api_router.include_router(review_rules.router)
api_router.include_router(content.router)
api_router.include_router(content.public_router)
