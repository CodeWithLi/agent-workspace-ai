from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.core.config import get_settings
from app.models import User
from app.schemas import SettingOut

router = APIRouter()


@router.get("", response_model=SettingOut)
def get_system_settings(_: User = Depends(require_admin)) -> SettingOut:
    settings = get_settings()
    return SettingOut(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        embedding_model=settings.embedding_model,
        milvus_collection=settings.milvus_collection,
        environment=settings.environment,
        allow_registration=settings.allow_registration,
        registration_email_domains=settings.registration_email_domains,
    )
