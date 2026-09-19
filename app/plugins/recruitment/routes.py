"""HTTP routes for the recruitment UI (ui/src/plugins/recruitment/),
mounted by the server under /plugins/recruitment/."""

import asyncio

from fastapi import APIRouter, HTTPException, Response

from app.plugins.contracts import RouteContext
from app.plugins.recruitment.blank import BLANK_DOCUMENTS
from app.utils.filenames import attachment_disposition


def make_routes(_context: RouteContext) -> APIRouter:
    router = APIRouter()

    @router.get("/blank/{doc_type}")
    async def download_blank_document(doc_type: str) -> Response:
        """
        Stream an empty form for the user to fill in by hand. Any signed-in
        user (the server requires sign-in on every plugin route).

        Rendered on demand from the same template and renderer the agent's
        generate_* tools use. There is no stored file and no database row,
        because a blank form carries nothing worth keeping.

        Moved here from core: it used to be registered whether or not this
        plugin loaded, which left core importing a plugin and a deployment
        that excluded recruitment still serving its forms.
        """
        document = BLANK_DOCUMENTS.get(doc_type)

        if document is None:
            raise HTTPException(status_code=404, detail="Unknown document type")

        # openpyxl and docxtpl are synchronous and not instant; keep them
        # off the event loop, as the generate tools do.
        content = await asyncio.to_thread(document.render)

        return Response(
            content=content,
            media_type=document.renderer.content_type,
            headers={"Content-Disposition": attachment_disposition(document.filename)},
        )

    return router
