"""
D2C AI Platform FastAPI application.

Entry point for the API server. Wires up all routes,
configures CORS, and handles database initialization.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import create_tables
from api.routes import merchants, connectors, chat, agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan handler for startup and shutdown events.
    Creates database tables on startup.
    """
    # Startup: create tables
    await create_tables()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="D2C AI Platform",
    version="0.1.0",
    description="Intelligence layer for D2C founders across SaaS tools",
    lifespan=lifespan
)

# CORS middleware - allow all origins for v0
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(merchants.router)
app.include_router(connectors.router)
app.include_router(chat.router)
app.include_router(agent.router)


# Root endpoint
@app.get("/")
def root():
    """Root endpoint."""
    return {"message": "D2C AI Platform API", "version": "0.1.0"}


# Health check endpoint
@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0", "environment": settings.ENV}