from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, Project, Report, Task, TaskStatus


def requirement_create(user_input: str) -> dict[str, Any]:
    objective = user_input.strip()[:800] or "形成可实施、可验证的项目目标"
    return {
        "product_background": f"围绕「{objective}」建立业务背景、问题和价值假设。",
        "target_users": ["业务负责人", "目标用户", "项目交付团队"],
        "user_stories": [
            f"作为业务负责人，我希望可验证地完成「{objective}」。",
            "作为项目成员，我希望查看范围、假设、验收证据和责任边界。",
        ],
        "features": [f"核心目标：{objective}", "多 Agent 协作交付", "可追溯验收证据"],
        "pages": [],
        "acceptance": [
            f"可验证完成用户目标：{objective}",
            "关键失败路径具有恢复方案、负责人和审计证据",
        ],
    }


def task_create(db: Session, project_id: int, titles: list[str] | None = None) -> list[Task]:
    task_titles = titles or ["需求评审", "架构设计", "核心接口开发", "前端页面开发", "测试验收"]
    existing_titles = set(db.scalars(select(Task.title).where(Task.project_id == project_id)))
    tasks = [
        Task(
            project_id=project_id,
            title=title,
            description=f"由AI项目经理自动创建：{title}",
            priority="HIGH" if index < 2 else "MEDIUM",
            status=TaskStatus.todo,
        )
        for index, title in enumerate(task_titles)
        if title not in existing_titles
    ]
    db.add_all(tasks)
    db.flush()
    return tasks


def architecture_generate(user_input: str) -> dict[str, Any]:
    return {
        "technology": ["Vue3", "FastAPI", "PostgreSQL", "Redis", "Milvus", "MinIO", "LangGraph"],
        "architecture": "前后端分离，后端统一LLM Gateway，Agent通过Tool Registry访问工具和知识库。",
        "database": ["users", "projects", "agents", "tasks", "documents", "embeddings", "meetings", "reports"],
        "apis": ["auth", "projects", "agents", "workflow", "knowledge", "meetings", "reports", "notifications"],
        "deployment": "Docker Compose 编排应用与依赖服务。",
        "source": user_input,
    }


def testcase_create(user_input: str) -> dict[str, Any]:
    return {
        "test_plan": "覆盖认证、项目、Agent聊天、工作流、知识库、会议、报告。",
        "functional_cases": ["登录注册", "创建项目", "运行工作流", "上传知识文件", "生成会议纪要"],
        "edge_cases": ["空输入", "无权限项目", "无知识库结果", "LLM超时降级"],
        "api_cases": ["401认证失败", "404资源不存在", "422参数校验失败"],
        "source": user_input,
    }


def meeting_summary(transcript: str) -> dict[str, Any]:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    return {
        "summary": "；".join(lines[:3]) if lines else "会议内容较少，需要补充记录。",
        "decisions": lines[:2],
        "todos": [{"task": line, "owner": "待确认", "due_date": "待确认"} for line in lines[2:6]],
    }


def notification_create(title: str, content: str, channel: str = "email") -> dict[str, str]:
    return {
        "title": title,
        "channel": channel,
        "content": f"【{title}】\n\n{content}\n\n请相关负责人及时确认。",
    }


def report_generate(sections: dict[str, Any]) -> str:
    return "\n\n".join(f"## {title}\n{content}" for title, content in sections.items())


def analytics_report(db: Session, project_id: int) -> dict[str, Any]:
    tasks = list(db.scalars(select(Task).where(Task.project_id == project_id)))
    done = len([task for task in tasks if task.status == TaskStatus.done])
    total = len(tasks)
    health = round((done / total) * 100, 1) if total else 80.0
    return {
        "health_score": health,
        "task_total": total,
        "task_done": done,
        "risks": [] if health >= 70 else ["完成率偏低，需要项目经理介入"],
        "suggestions": ["明确下一个里程碑", "优先处理高优先级任务", "每周生成风险报告"],
    }


def context_search(db: Session, project_id: int) -> dict[str, Any]:
    project = db.get(Project, project_id)
    tasks = list(db.scalars(select(Task).where(Task.project_id == project_id).limit(10)))
    reports = list(db.scalars(select(Report).where(Report.project_id == project_id).limit(5)))
    notifications = list(db.scalars(select(Notification).where(Notification.project_id == project_id).limit(5)))
    return {
        "project": {"id": project.id, "name": project.name, "description": project.description} if project else None,
        "tasks": [{"title": task.title, "status": task.status.value} for task in tasks],
        "reports": [{"title": report.title, "type": report.report_type} for report in reports],
        "notifications": [{"title": item.title, "status": item.status} for item in notifications],
    }
