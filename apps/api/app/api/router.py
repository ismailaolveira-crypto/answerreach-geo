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
    workspace_access,
)
from app.v1.routes import router as cleanroom_v1_router
from app.v1.global_scope import router as global_scope_router
from app.v1.action_workflow_routes import router as action_workflow_router
from app.v1.results_roi_routes import router as results_roi_router
from app.v1.observation_alert_routes import router as observation_alert_router
from app.v1.roi_import_routes import router as roi_import_router
from app.v1.business_goal_routes import router as business_goal_router
from app.v1.collaboration_routes import router as collaboration_router
from app.v1.agent_workspace_routes import router as agent_workspace_router
from app.v1.question_routes import router as question_router
from app.v1.observation_routes import router as observation_router
from app.v1.workspace_routes import router as workspace_v1_router
from app.v1.insight_routes import router as insight_router
from app.v1.content_delivery_routes import router as content_delivery_router
from app.v1.agent_run_routes import router as agent_run_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(alerts.router)
api_router.include_router(audit.router)
api_router.include_router(usage.router)
api_router.include_router(users.router)
api_router.include_router(workspace_access.invite_router)
api_router.include_router(workspace_access.workspace_router)
api_router.include_router(workspace_access.agent_router)
api_router.include_router(companies.router)
api_router.include_router(projects.router)
api_router.include_router(geo_config.router)
api_router.include_router(geo_v1.router)
api_router.include_router(cleanroom_v1_router)
api_router.include_router(global_scope_router)
api_router.include_router(action_workflow_router)
api_router.include_router(results_roi_router)
api_router.include_router(observation_alert_router)
api_router.include_router(roi_import_router)
api_router.include_router(business_goal_router)
api_router.include_router(collaboration_router)
api_router.include_router(agent_workspace_router)
api_router.include_router(question_router)
api_router.include_router(observation_router)
api_router.include_router(workspace_v1_router)
api_router.include_router(insight_router)
api_router.include_router(content_delivery_router)
api_router.include_router(agent_run_router)
api_router.include_router(providers.router)
api_router.include_router(queue.router)
api_router.include_router(crawl.router)
api_router.include_router(reports.router)
api_router.include_router(report_templates.router)
api_router.include_router(review_rules.router)
api_router.include_router(content.router)
api_router.include_router(content.public_router)
