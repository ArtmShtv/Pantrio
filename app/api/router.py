from fastapi import APIRouter

from app.api.routes import auth, health, ingredients, meals, pantry, plans, products, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(ingredients.router)
api_router.include_router(products.router)
api_router.include_router(meals.router)
api_router.include_router(plans.router)
api_router.include_router(pantry.router)
