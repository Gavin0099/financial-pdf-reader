from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.mongo.client import connect_mongodb

app = FastAPI(
    title="Taiwan Financial PDF Reader",
    description="Evidence-bound financial report reader for Taiwan-listed companies.",
    version="0.1.0",
)

# TODO: restrict origins before production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
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
