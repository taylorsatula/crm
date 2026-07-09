"""Authenticated lifecycle endpoints for CRM workspaces."""

from fastapi import APIRouter, Request

from api.base import success_response


def create_workspace_router(postgres) -> APIRouter:
    """Create routes whose workspace ID comes exclusively from request context."""
    router = APIRouter(tags=["workspace"])

    @router.post("/workspace/provision")
    async def provision_workspace(request: Request):
        workspace_id = request.state.workspace_id
        postgres.execute(
            """
            INSERT INTO workspaces (id)
            VALUES (%s)
            ON CONFLICT (id) DO NOTHING
            """,
            (workspace_id,),
        )
        return success_response(
            {"workspace_id": str(workspace_id)},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    @router.delete("/workspace")
    async def delete_workspace(request: Request):
        workspace_id = request.state.workspace_id
        postgres.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,))
        return success_response(
            {"workspace_id": str(workspace_id), "deleted": True},
            request_id=request.state.request_id,
        ).model_dump(mode="json")

    return router
