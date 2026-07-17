import argparse
import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.llm import get_llm
from app.core.llm_usage import bind_llm_usage
from app.models import Agent, EvaluationCase, EvaluationResult, EvaluationRun


settings = get_settings()


def score_answer(answer: str, expected_keywords: list[str]) -> tuple[float, str]:
    if not expected_keywords:
        return 1.0, json.dumps({"matched": [], "missing": []})
    lower = answer.lower()
    matched = [keyword for keyword in expected_keywords if keyword.lower() in lower]
    missing = [keyword for keyword in expected_keywords if keyword.lower() not in lower]
    return len(matched) / len(expected_keywords), json.dumps(
        {"matched": matched, "missing": missing},
        ensure_ascii=False,
    )


async def run_evaluation(db: Session, user_id: int | None = None) -> EvaluationRun:
    cases = list(db.scalars(select(EvaluationCase).where(EvaluationCase.enabled.is_(True)).order_by(EvaluationCase.id)))
    run = EvaluationRun(status="RUNNING", total_cases=len(cases), created_by_user_id=user_id)
    db.add(run)
    db.flush()
    scores: list[float] = []
    passed = 0
    for case in cases:
        agent = db.scalar(select(Agent).where(Agent.role == case.agent_role))
        answer = ""
        error = ""
        score = 0.0
        details = "{}"
        if not agent:
            error = f"Agent role not found: {case.agent_role}"
        else:
            try:
                with bind_llm_usage(db=db, agent_id=agent.id):
                    answer = await get_llm().chat(agent.system_prompt, case.input_text, agent.model)
                expected = json.loads(case.expected_keywords_json or "[]")
                score, details = score_answer(answer, expected)
            except Exception as exc:
                error = str(exc)[:1000]
        case_passed = not error and score >= settings.evaluation_case_min_score
        passed += int(case_passed)
        scores.append(score)
        db.add(
            EvaluationResult(
                run_id=run.id,
                case_id=case.id,
                agent_id=agent.id if agent else None,
                answer=answer,
                score=score,
                passed=case_passed,
                details_json=details,
                error=error,
            )
        )
    run.passed_cases = passed
    run.average_score = sum(scores) / len(scores) if scores else 0.0
    run.status = "COMPLETED"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent Workspace AI regression evaluations")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--min-average", type=float, default=settings.evaluation_min_average)
    args = parser.parse_args()
    with SessionLocal() as db:
        run = asyncio.run(run_evaluation(db))
    print(json.dumps({"run_id": run.id, "cases": run.total_cases, "passed": run.passed_cases, "average": run.average_score}))
    return 0 if run.average_score >= args.min_average else 1


if __name__ == "__main__":
    raise SystemExit(main())
