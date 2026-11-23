from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from .graph import InvalidGraph, Task
from .store import get_workflow, submit_workflow

def reject_null_character(value: str) -> str:
    if "\0" in value:
        raise ValueError("Null characters are not supported")
    return value


Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(reject_null_character),
]
TaskStatus = Literal["blocked", "ready", "running", "succeeded", "failed"]


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    key: Label
    type: Label
    depends_on: list[Label] = Field(default_factory=list)
    input: JsonValue = Field(default_factory=dict)

class WorkflowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Label
    tasks: list[TaskSpec] = Field(min_length=1)

class SubmittedWorkflow(BaseModel):
    id: UUID
    status: Literal["pending"] = "pending"


class TaskExecution(TaskSpec):
    status: TaskStatus


class WorkflowExecution(BaseModel):
    id: UUID
    name: str
    status: Literal["pending", "running", "succeeded", "failed"]
    created_at: datetime
    tasks: list[TaskExecution]


app = FastAPI(title="Durable Workflow Engine")


@app.post("/workflows", response_model=SubmittedWorkflow, status_code=201)
def submit(spec: WorkflowSpec) -> SubmittedWorkflow:
    tasks = [Task(task.key, task.type, tuple(task.depends_on), task.input) for task in spec.tasks]
    try:
        return SubmittedWorkflow(id=submit_workflow(spec.name, tasks))
    except InvalidGraph as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/workflows/{workflow_id}", response_model=WorkflowExecution)
def read(workflow_id: UUID) -> dict:
    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow execution not found")
    return workflow
