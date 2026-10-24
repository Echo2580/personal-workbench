from fastapi import APIRouter, Header, Response
from .models import DTO, RecipeSet, ProjectSettings, ProjectNameInput
from .settings import validate_python


class ManualInput(DTO):
    path: str
    name: str | None = None


class ActionInput(DTO):
    recipe_id: str
    fingerprint: str


class PythonInput(DTO):
    path: str


def create_router(service):
    router = APIRouter(prefix="/api/v1")

    @router.get("/projects")
    def projects():
        return service.snapshot()

    @router.get("/projects/removed")
    def removed():
        return service.removed_projects()

    @router.delete("/projects/{pid}")
    def remove_project(pid: str, if_match: str = Header()):
        return service.remove_project(pid, if_match.strip('"'))

    @router.post("/projects/{pid}/restore")
    def restore_project(pid: str, if_match: str = Header()):
        return service.restore_project(pid, if_match.strip('"'))

    @router.post("/projects/scan", status_code=202)
    def scan():
        return service.request_scan()

    @router.post("/projects/manual")
    def manual(body: ManualInput):
        return service.add_manual_project(body.path, body.name)

    @router.delete("/projects/{pid}/manual")
    def remove(pid: str):
        return service.remove_manual(pid)

    @router.patch("/projects/{pid}/name")
    def rename_project(pid: str, body: ProjectNameInput, if_match: str = Header()):
        return service.rename_project(pid, body.name, if_match.strip('"'))

    @router.delete("/projects/{pid}/name")
    def reset_project_name(pid: str, if_match: str = Header()):
        return service.reset_project_name(pid, if_match.strip('"'))

    @router.get("/projects/{pid}/recipes")
    def recipes(pid: str):
        return service.get_recipes(pid)

    @router.get("/projects/{pid}/scripts")
    def scripts(pid: str):
        return service.script_candidates(pid)

    @router.put("/projects/{pid}/recipes")
    def save(pid: str, body: RecipeSet, if_match: str = Header()):
        return service.save_recipes(pid, body, if_match.strip('"'))

    @router.delete("/projects/{pid}/override")
    def reset(pid: str, if_match: str = Header()):
        return service.reset_override(pid, if_match.strip('"'))

    @router.post("/projects/{pid}/recipe-approval")
    def approve(pid: str, body: ActionInput):
        return service.approve(pid, body.recipe_id, body.fingerprint)

    @router.post("/projects/{pid}/actions")
    def action(pid: str, body: ActionInput, response: Response):
        result = service.execute(pid, body.recipe_id, body.fingerprint)
        response.status_code = 202 if "run" in result else 200
        return result

    @router.get("/projects/runs")
    def runs():
        return {"runs": service.runs()}

    @router.post("/projects/runs/{rid}/stop")
    def stop(rid: str):
        return service.runtime.stop(rid)

    @router.get("/settings/projects")
    def settings():
        return service.get_settings()

    @router.put("/settings/projects")
    def save_settings(body: ProjectSettings, if_match: str = Header()):
        return service.save_settings(body, if_match.strip('"'))

    @router.post("/settings/projects/validate-python")
    def python(body: PythonInput):
        return validate_python(body.path)

    return router
