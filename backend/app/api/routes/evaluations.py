import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.audit import record_audit
from app.core.database import get_db
from app.evaluation import run_evaluation
from app.models import EvaluationCase, EvaluationRun, User
from app.schemas import EvaluationCaseCreate, EvaluationCaseOut, EvaluationRunOut


router = APIRouter()


def case_out(item: EvaluationCase) -> EvaluationCaseOut:
    return EvaluationCaseOut(
        id=item.id,
        name=item.name,
        agent_role=item.agent_role,
        input_text=item.input_text,
        expected_keywords=json.loads(item.expected_keywords_json or "[]"),
        enabled=item.enabled,
        created_at=item.created_at,
    )


@router.get("/cases", response_model=list[EvaluationCaseOut])
def list_evaluation_cases(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[EvaluationCaseOut]:
    return [case_out(item) for item in db.scalars(select(EvaluationCase).order_by(EvaluationCase.id))]


@router.post("/cases", response_model=EvaluationCaseOut, status_code=status.HTTP_201_CREATED)
def create_evaluation_case(
    payload: EvaluationCaseCreate,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationCaseOut:
    item = EvaluationCase(
        name=payload.name,
        agent_role=payload.agent_role.value,
        input_text=payload.input_text,
        expected_keywords_json=json.dumps(payload.expected_keywords, ensure_ascii=False),
        enabled=payload.enabled,
        created_by_user_id=current_admin.id,
    )
    db.add(item)
    db.flush()
    record_audit(
        db,
        "evaluation.case_create",
        current_admin.id,
        resource_type="evaluation_case",
        resource_id=item.id,
        request=request,
    )
    db.commit()
    db.refresh(item)
    return case_out(item)


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation_case(
    case_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(EvaluationCase, case_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation case not found")
    db.delete(item)
    db.commit()


@router.post("/run", response_model=EvaluationRunOut)
async def execute_evaluation(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EvaluationRun:
    return await run_evaluation(db, current_admin.id)


@router.get("/runs", response_model=list[EvaluationRunOut])
def list_evaluation_runs(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[EvaluationRun]:
    return list(db.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100)))
