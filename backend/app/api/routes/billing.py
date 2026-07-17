from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit
from app.models import LLMUsage, RechargeOrder, TokenTransaction, User, UserRole
from app.schemas import (
    AdminTokenAdjustment,
    RechargeOrderOut,
    RechargeRequest,
    TokenTransactionOut,
    LLMUsageOut,
    WalletOut,
)
from app.services.billing import BillingReferenceError, InsufficientTokensError, apply_token_change


router = APIRouter()
settings = get_settings()


@router.get("/usage", response_model=list[LLMUsageOut])
def list_llm_usage(
    user_id: int | None = None,
    project_id: int | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[LLMUsage]:
    stmt = select(LLMUsage)
    if current_user.role != UserRole.admin:
        stmt = stmt.where(LLMUsage.user_id == current_user.id)
    elif user_id is not None:
        stmt = stmt.where(LLMUsage.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(LLMUsage.project_id == project_id)
    return list(db.scalars(stmt.order_by(LLMUsage.created_at.desc()).limit(min(max(limit, 1), 500))))


@router.get("/wallet", response_model=WalletOut)
def wallet(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WalletOut:
    transactions = list(
        db.scalars(
            select(TokenTransaction)
            .where(TokenTransaction.user_id == current_user.id)
            .order_by(TokenTransaction.created_at.desc(), TokenTransaction.id.desc())
            .limit(100)
        )
    )
    db.refresh(current_user)
    return WalletOut(
        balance=current_user.ai_token_balance,
        chat_cost=settings.chat_token_cost,
        workflow_cost=settings.workflow_token_cost,
        recharge_tokens_per_yuan=settings.recharge_tokens_per_yuan,
        transactions=[TokenTransactionOut.model_validate(item) for item in transactions],
    )


@router.post("/recharge", response_model=RechargeOrderOut)
def fake_recharge(
    payload: RechargeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RechargeOrder:
    check_rate_limit(f"recharge:{current_user.id}", limit=10, window_seconds=60)
    existing = db.scalar(select(RechargeOrder).where(RechargeOrder.order_no == payload.request_id))
    if existing:
        if existing.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recharge request ID is already in use")
        return existing

    token_amount = payload.amount_yuan * settings.recharge_tokens_per_yuan
    order = RechargeOrder(
        order_no=payload.request_id,
        user_id=current_user.id,
        amount_cents=payload.amount_yuan * 100,
        token_amount=token_amount,
        status="PAID",
        paid_at=datetime.now(timezone.utc),
    )
    db.add(order)
    try:
        db.flush()
        apply_token_change(
            db,
            current_user.id,
            token_amount,
            "RECHARGE",
            idempotency_key=f"recharge:{payload.request_id}",
            reference_type="recharge_order",
            reference_id=payload.request_id,
            description=f"模拟充值 {payload.amount_yuan} 元",
        )
        record_audit(
            db,
            "billing.fake_recharge",
            current_user.id,
            resource_type="recharge_order",
            resource_id=payload.request_id,
            details={"amount_yuan": payload.amount_yuan, "token_amount": token_amount},
            request=request,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(RechargeOrder).where(RechargeOrder.order_no == payload.request_id))
        if existing and existing.user_id == current_user.id:
            return existing
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate recharge request")
    db.refresh(order)
    return order


@router.get("/orders", response_model=list[RechargeOrderOut])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RechargeOrder]:
    return list(
        db.scalars(
            select(RechargeOrder)
            .where(RechargeOrder.user_id == current_user.id)
            .order_by(RechargeOrder.created_at.desc())
            .limit(100)
        )
    )


@router.post("/admin/adjust", response_model=TokenTransactionOut)
def admin_adjust_tokens(
    payload: AdminTokenAdjustment,
    request: Request,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TokenTransaction:
    if payload.amount == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Adjustment amount cannot be zero")
    try:
        transaction = apply_token_change(
            db,
            payload.user_id,
            payload.amount,
            "ADJUST",
            idempotency_key=f"admin-adjust:{payload.request_id}",
            reference_type="admin",
            reference_id=str(current_admin.id),
            description=payload.reason,
            operator_user_id=current_admin.id,
        )
    except InsufficientTokensError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except BillingReferenceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    record_audit(
        db,
        "billing.admin_adjust",
        current_admin.id,
        resource_type="user",
        resource_id=payload.user_id,
        details={"amount": payload.amount, "reason": payload.reason},
        request=request,
    )
    db.commit()
    db.refresh(transaction)
    return transaction
