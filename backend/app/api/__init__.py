from fastapi import APIRouter

from app.api.routes import agents, audit, auth, billing, dashboard, evaluations, knowledge, meetings, notifications, projects, reports, requirements, search, settings, users, workflow


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(requirements.router, prefix="/requirements", tags=["requirements"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(evaluations.router, prefix="/evaluations", tags=["evaluations"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(workflow.router, prefix="/workflow", tags=["workflow"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
