from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import TokenTransaction, User


class InsufficientTokensError(ValueError):
    pass


class BillingReferenceError(LookupError):
    pass


def apply_token_change(
    db: Session,
    user_id: int,
    amount: int,
    transaction_type: str,
    *,
    idempotency_key: str,
    reference_type: str = "",
    reference_id: str = "",
    description: str = "",
    operator_user_id: int | None = None,
) -> TokenTransaction:
    existing = db.scalar(select(TokenTransaction).where(TokenTransaction.idempotency_key == idempotency_key))
    if existing:
        if existing.user_id != user_id or existing.amount != amount:
            raise BillingReferenceError("Idempotency key is already used for a different token operation")
        return existing
    if amount == 0:
        raise ValueError("Token amount cannot be zero")

    stmt = update(User).where(User.id == user_id)
    if amount < 0:
        stmt = stmt.where(User.ai_token_balance >= -amount)
    balance = db.execute(
        stmt.values(ai_token_balance=User.ai_token_balance + amount).returning(User.ai_token_balance)
    ).scalar_one_or_none()
    if balance is None:
        if db.get(User, user_id) is None:
            raise BillingReferenceError("User not found")
        raise InsufficientTokensError("Insufficient AI Token balance")

    transaction = TokenTransaction(
        user_id=user_id,
        amount=amount,
        balance_after=balance,
        transaction_type=transaction_type,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        description=description,
        operator_user_id=operator_user_id,
    )
    db.add(transaction)
    db.flush()
    return transaction


def refund_consumption(db: Session, transaction_id: int, reason: str) -> TokenTransaction:
    original = db.get(TokenTransaction, transaction_id)
    if not original or original.amount >= 0 or original.transaction_type != "CONSUME":
        raise BillingReferenceError("Consumable token transaction not found")
    return apply_token_change(
        db,
        original.user_id,
        -original.amount,
        "REFUND",
        idempotency_key=f"refund:{original.id}",
        reference_type=original.reference_type,
        reference_id=original.reference_id,
        description=reason,
    )
