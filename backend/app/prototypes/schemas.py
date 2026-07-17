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


class PrototypeSpecification(BaseModel):
    product_name: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    start_screen_id: str = Field(min_length=2, max_length=64)
    theme: PrototypeTheme = Field(default_factory=PrototypeTheme)
    screens: list[PrototypeScreen] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_navigation_graph(self) -> "PrototypeSpecification":
        screen_ids = [screen.id for screen in self.screens]
        if len(screen_ids) != len(set(screen_ids)):
            raise ValueError("screen IDs must be unique")
        if self.start_screen_id not in screen_ids:
            raise ValueError("start_screen_id must reference a screen")
        component_ids: set[str] = set()
        for screen in self.screens:
            for section in screen.sections:
                for component in section.components:
                    if component.id in component_ids:
                        raise ValueError("component IDs must be unique across the prototype")
                    component_ids.add(component.id)
                    if component.action and component.action.type == "navigate":
                        if component.action.target not in screen_ids:
                            raise ValueError(
                                f"component {component.id} navigates to an unknown screen"
                            )
        return self


class PrototypeGenerateRequest(BaseModel):
    project_id: int
    requirement_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=10, max_length=12000)


class PrototypeRegenerateRequest(BaseModel):
    feedback: str = Field(default="", max_length=4000)


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
