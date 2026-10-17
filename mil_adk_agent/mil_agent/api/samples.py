"""Sample complaints: the customer documents for each demo case, for the upload path."""

import io
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from mil_agent.data import samples

router = APIRouter(prefix="/api/samples", tags=["samples"])


@router.get("")
def sample_list():
    return [{k: v for k, v in s.items() if k != "label"} for s in samples.SAMPLE_CASES]


@router.get("/{sample_id}/download")
def sample_download(sample_id: str):
    try:
        files = samples.sample_files(sample_id, include_requested=True)
    except (StopIteration, KeyError):
        raise HTTPException(404, "Unknown sample")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=complaint_{sample_id}_documents.zip"})
