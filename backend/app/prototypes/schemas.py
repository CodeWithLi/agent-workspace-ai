from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PrototypeComponentType = Literal[
    "heading",
    "text",
    "input",
    "textarea",
    "select",
    "button",
    "link",
    "stepper",
    "stats",
    "callout",
    "table",
    "tabs",
    "list",
    "divider",
]
PrototypeActionType = Literal["navigate", "toast", "submit", "copy", "advance_step", "back"]


class PrototypeAction(BaseModel):
    type: PrototypeActionType
    target: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_target(self) -> "PrototypeAction":
        if self.type == "navigate" and not self.target:
            raise ValueError("navigate actions require a target screen")
        return self


class PrototypeOption(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=100)


class PrototypeComponent(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    type: PrototypeComponentType
    label: str = Field(default="", max_length=120)
    text: str = Field(default="", max_length=1000)
    placeholder: str = Field(default="", max_length=200)
    value: str = Field(default="", max_length=500)
    variant: Literal["default", "primary", "secondary", "success", "warning", "danger"] = "default"
    required: bool = False
    disabled: bool = False
    options: list[PrototypeOption] = Field(default_factory=list, max_length=20)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    columns: list[str] = Field(default_factory=list, max_length=8)
    steps: list[str] = Field(default_factory=list, max_length=8)
    active_step: int = Field(default=1, ge=1, le=8)
    action: PrototypeAction | None = None

    @model_validator(mode="after")
    def validate_component_contract(self) -> "PrototypeComponent":
        if self.type in {"input", "textarea", "select"} and not self.label:
            raise ValueError(f"{self.type} components require a visible label")
        if self.type == "select" and not self.options:
            raise ValueError("select components require options")
        if self.type == "stepper" and len(self.steps) < 2:
            raise ValueError("stepper components require at least two steps")
        if self.type == "table" and not self.columns:
            raise ValueError("table components require columns")
        return self


class PrototypeSection(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    title: str = Field(default="", max_length=150)
    description: str = Field(default="", max_length=500)
    width: Literal["narrow", "medium", "wide", "full"] = "medium"
    components: list[PrototypeComponent] = Field(min_length=1, max_length=40)


class PrototypeScreen(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    layout: Literal["auth", "app", "dashboard", "form", "list"] = "app"
    sections: list[PrototypeSection] = Field(min_length=1, max_length=12)


class PrototypeTheme(BaseModel):
    primary: str = Field(default="#1F2937", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(default="#2563EB", pattern=r"^#[0-9A-Fa-f]{6}$")
    background: str = Field(default="#F7F8FA", pattern=r"^#[0-9A-Fa-f]{6}$")
    surface: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    foreground: str = Field(default="#111827", pattern=r"^#[0-9A-Fa-f]{6}$")
    radius: Literal["compact", "soft", "rounded"] = "soft"


class PrototypeJourneyStep(BaseModel):
    screen_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    instruction: str = Field(min_length=1, max_length=300)
    expected_screen_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")


class PrototypeJourney(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=500)
    steps: list[PrototypeJourneyStep] = Field(min_length=1, max_length=20)


class PrototypeSpecification(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    start_screen_id: str = Field(min_length=2, max_length=64)
    theme: PrototypeTheme = Field(default_factory=PrototypeTheme)
    journeys: list[PrototypeJourney] = Field(max_length=20)
    screens: list[PrototypeScreen] = Field(min_length=2, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_specification_without_journeys(cls, value: Any) -> Any:
        if isinstance(value, dict) and "journeys" not in value:
            return {**value, "journeys": []}
        return value

    @model_validator(mode="after")
    def validate_navigation_graph(self) -> "PrototypeSpecification":
        screen_ids = [screen.id for screen in self.screens]
        if len(screen_ids) != len(set(screen_ids)):
            raise ValueError("screen IDs must be unique")
        if self.start_screen_id not in screen_ids:
            raise ValueError("start_screen_id must reference a screen")
        component_ids: set[str] = set()
        components_by_screen: dict[str, dict[str, PrototypeComponent]] = {}
        for screen in self.screens:
            screen_components: dict[str, PrototypeComponent] = {}
            for section in screen.sections:
                for component in section.components:
                    if component.id in component_ids:
                        raise ValueError("component IDs must be unique across the prototype")
                    component_ids.add(component.id)
                    screen_components[component.id] = component
                    if component.action and component.action.type == "navigate":
                        if component.action.target not in screen_ids:
                            raise ValueError(
                                f"component {component.id} navigates to an unknown screen"
                            )
            components_by_screen[screen.id] = screen_components

        journey_ids = [journey.id for journey in self.journeys]
        if len(journey_ids) != len(set(journey_ids)):
            raise ValueError("journey IDs must be unique")
        for journey in self.journeys:
            previous_expected_screen: str | None = None
            for step in journey.steps:
                if step.screen_id not in screen_ids:
                    raise ValueError(
                        f"journey {journey.id} references an unknown screen {step.screen_id}"
                    )
                if step.expected_screen_id not in screen_ids:
                    raise ValueError(
                        f"journey {journey.id} expects an unknown screen {step.expected_screen_id}"
                    )
                if previous_expected_screen and step.screen_id != previous_expected_screen:
                    raise ValueError(
                        f"journey {journey.id} must continue from {previous_expected_screen}"
                    )
                component = components_by_screen[step.screen_id].get(step.component_id)
                if component is None:
                    raise ValueError(
                        f"journey {journey.id} references unknown component {step.component_id}"
                    )
                if component.type not in {"button", "link"} or component.action is None:
                    raise ValueError(
                        f"journey {journey.id} component {step.component_id} must be an executable button or link"
                    )
                if component.action.type == "navigate":
                    if step.expected_screen_id != component.action.target:
                        raise ValueError(
                            f"journey {journey.id} expected screen must match navigation target"
                        )
                elif component.action.type != "back" and step.expected_screen_id != step.screen_id:
                    raise ValueError(
                        f"journey {journey.id} non-navigation action must remain on its current screen"
                    )
                previous_expected_screen = step.expected_screen_id
        return self


class PrototypeGenerateRequest(BaseModel):
    project_id: int
    requirement_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=10, max_length=12000)


class PrototypeRegenerateRequest(BaseModel):
    feedback: str = Field(default="", max_length=4000)


class PrototypeGenerationCreateRequest(PrototypeGenerateRequest):
    request_id: str = Field(min_length=8, max_length=64)


class PrototypeGenerationRegenerateRequest(PrototypeRegenerateRequest):
    request_id: str = Field(min_length=8, max_length=64)


class PrototypeGenerationStageOut(BaseModel):
    stage: str
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    round: int = Field(default=0, ge=0)
    agent_role: str | None = None
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PrototypeGenerationJobOut(BaseModel):
    job_id: int
    operation: Literal["CREATE", "REGENERATE"]
    project_id: int
    title: str
    prototype_id: int | None
    base_version: int | None
    target_version: int
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLING", "CANCELLED"]
    stage: str
    stage_history: list[PrototypeGenerationStageOut]
    progress_percent: int = Field(ge=0, le=100)
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    latest_event_id: int
    retryable: bool
    error_code: str | None
    error_message: str | None
    result_prototype_id: int | None
    result_version: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class PrototypeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    status: Literal["DRAFT", "REVIEW", "APPROVED", "ARCHIVED"] | None = None


class PrototypeVersionOut(BaseModel):
    id: int
    version: int
    source_prompt: str
    specification: PrototypeSpecification
    agent_trace: list[dict[str, Any]]
    quality: dict[str, Any]
    generation_mode: str
    created_by_user_id: int
    created_at: datetime


class PrototypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    requirement_id: int | None
    created_by_user_id: int
    title: str
    summary: str
    status: str
    active_version: int
    screen_count: int
    quality_score: float
    created_at: datetime
    updated_at: datetime


class PrototypeDetailOut(PrototypeOut):
    current: PrototypeVersionOut
    versions: list[PrototypeVersionOut]


class PrototypeCommentCreate(BaseModel):
    screen_id: str | None = Field(default=None, max_length=64)
    body: str = Field(min_length=1, max_length=5000)


class PrototypeCommentUpdate(BaseModel):
    status: Literal["OPEN", "RESOLVED"]


class PrototypeCommentOut(BaseModel):
    id: int
    prototype_id: int
    prototype_version: int
    screen_id: str | None
    user_id: int
    user_name: str
    body: str
    status: str
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PrototypeMaterializeRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)


class PrototypeTestCaseOut(BaseModel):
    id: int
    prototype_id: int
    prototype_version: int
    screen_id: str
    case_key: str
    title: str
    preconditions: str
    steps: list[str]
    expected_result: str
    priority: str
    created_at: datetime


class PrototypeMaterializationOut(BaseModel):
    id: int
    prototype_id: int
    prototype_version: int
    task_ids: list[int]
    test_cases: list[PrototypeTestCaseOut]
    created_at: datetime
