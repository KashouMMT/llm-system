"""HTTP routes for the recycling UI (ui/src/plugins/recycling/), mounted
by the server under /plugins/recycling/."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.plugins.contracts import RouteContext
from app.plugins.recycling.database import (
    CatalogRepository,
    CatalogStorageError,
    EvidenceRepository,
)

# Enough for a screenful at any sensible row height; the cap stops one
# request from asking for a 10k-row catalog at once.
MAX_PAGE_SIZE = 200


def make_routes(context: RouteContext) -> APIRouter:
    catalog_repository = CatalogRepository(context.tool.db_pool)
    evidence_repository = EvidenceRepository(context.tool.db_pool)

    router = APIRouter()

    # Admin only, like /recycle show_catalog: the catalog is the operator's
    # reference data, and its evidence images are other users' room photos.
    @router.get("/catalog", dependencies=[Depends(context.require_admin)])
    async def get_catalog(
        search: str = "",
        visual_class: str | None = None,
        excluded: bool | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    ) -> dict[str, Any]:
        """One filtered page of the catalog, each row with its evidence
        (file ids the browser shows through GET /files/{id}, where admins
        may read any file)."""
        try:
            page = await catalog_repository.page(
                search=search,
                visual_class=visual_class,
                excluded=excluded,
                offset=offset,
                limit=limit,
            )
            evidence = await evidence_repository.by_item(
                [row["id"] for row in page.rows]
            )
        except CatalogStorageError as error:
            # Already logged by the repository, with the traceback.
            raise HTTPException(
                status_code=500, detail="The catalog could not be loaded."
            ) from error

        return {
            "total": page.total,
            "offset": offset,
            "limit": limit,
            "visual_classes": page.visual_classes,
            "items": [
                {
                    **row,
                    "evidence": [
                        {
                            "file_id": str(record.file_id),
                            "frame_index": record.frame_index,
                            "raw_label": record.raw_label,
                        }
                        for record in evidence.get(row["id"], [])
                    ],
                }
                for row in page.rows
            ],
        }

    return router
