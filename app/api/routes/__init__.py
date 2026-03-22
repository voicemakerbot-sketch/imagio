from fastapi import APIRouter

from app.api.routes import payments

api_router = APIRouter()
api_router.include_router(payments.router)
