"""Local RAG endpoint using the existing retrieval and answer checks."""

from threading import Lock
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from scripts.ask_rag import MODEL, Statement, answer_from_sources
from scripts.search_rag import search

router = APIRouter(prefix="/rag", tags=["RAG"])
RAG_LOCK = Lock()


class RagRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    question: str = Field(strict=True, min_length=1, max_length=1000)


class CitedStatement(Statement):
    source: str
    section: str


class RagResponse(BaseModel):
    request_id: str
    generation_model: str
    answerable: bool
    statements: list[CitedStatement]


@router.post("/ask", response_model=RagResponse)
def ask_rag(payload: RagRequest, request: Request):
    # Keep one RAG request active per API process.
    if not RAG_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="RAG is busy. Try again shortly.",
            headers={"Retry-After": "5"},
        )

    try:
        sources = search(payload.question, top_k=3)
        answer = answer_from_sources(payload.question, sources)
        by_id = {source["chunk_id"]: source for source in sources}

        statements = [
            CitedStatement(
                **statement.model_dump(),
                source=by_id[statement.source_id]["source"],
                section=by_id[statement.source_id]["section"],
            )
            for statement in answer.statements
        ]

        return RagResponse(
            request_id=request.state.request_id,
            generation_model=MODEL,
            answerable=answer.answerable,
            statements=statements,
        )

    except HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Ollama returned an error.",
        ) from error

    except (URLError, TimeoutError) as error:
        raise HTTPException(
            status_code=503,
            detail="Local Ollama is unavailable or the request timed out.",
        ) from error

    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail="Local RAG files could not be read.",
        ) from error

    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(
            status_code=502,
            detail="RAG data or the generated answer failed validation.",
        ) from error

    finally:
        RAG_LOCK.release()
