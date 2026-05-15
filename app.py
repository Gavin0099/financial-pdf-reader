from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import os

from database.mongo.client import connect_mongodb

app = FastAPI(
    title="Taiwan Financial PDF Reader",
    description="Evidence-bound financial report reader for Taiwan-listed companies.",
    version="0.1.0",
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_allowed_origins = ["*"] if _raw_origins.strip() == "*" else [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allowed_origins != ["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def start_database():
    connect_mongodb()


@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Taiwan Financial PDF Reader API", "version": "0.1.0"}


@app.get("/health", tags=["Root"])
async def health():
    return {"status": "ok"}


# Phase 1: document ingestion
from apis.v1.routers.documents import router as DocumentsRouter
app.include_router(DocumentsRouter, tags=["Documents"], prefix="/api/v1/documents")

# Phase 2: evidence-bound summary
from apis.v1.routers.summary import router as SummaryRouter
app.include_router(SummaryRouter, tags=["Summary"], prefix="/api/v1/documents")

# Phase 3: financial section classification
from apis.v1.routers.classification import router as ClassificationRouter
app.include_router(ClassificationRouter, tags=["Classification"], prefix="/api/v1/documents")

# Phase 4: two-PDF diff report
from apis.v1.routers.diff import router as DiffRouter
app.include_router(DiffRouter, tags=["Diff"], prefix="/api/v1/reports")

# Phase 5: table extraction & numeric cross-check
from apis.v1.routers.tables import router as TablesRouter
app.include_router(TablesRouter, tags=["Tables"], prefix="/api/v1/documents")

# Phase 6: Taiwan data source integration
from apis.v1.routers.data_source import router as DataSourceRouter
app.include_router(DataSourceRouter, tags=["DataSource"], prefix="/api/v1/stocks")

# Phase 7: Governance Layer — R1-R7 claim audit
from apis.v1.routers.audit import router as AuditRouter
app.include_router(AuditRouter, tags=["Audit"], prefix="/api/v1/documents")

# Phase 9D: Disclosure Coverage Engine — 14 項法定揭露稽核
from apis.v1.routers.disclosures import router as DisclosureRouter
app.include_router(DisclosureRouter, tags=["Disclosures"], prefix="/api/v1/documents")

# Phase 9E: Reasoning Pattern Registry — 6 財報檢查模式（純 Python，不呼叫 Claude）
from apis.v1.routers.patterns import router as PatternsRouter
app.include_router(PatternsRouter, tags=["Patterns"], prefix="/api/v1/documents")

# Phase 9: Simple HTML UI
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/ui", include_in_schema=False)
async def serve_ui():
    return FileResponse("static/index.html")
