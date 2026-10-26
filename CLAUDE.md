Project: meal-planning app MVP (working name: Pantrio)

Goal
- Plan weekly meals from selected meals/ingredients
- Generate a shopping list with pack-aware quantities and prices
- Show calories and macros per meal, day and week
- Track ingredient leftovers (pantry) and suggest meals that use them
- Out of MVP scope: cooked leftovers, price history, multiple shops per user

Stack
- Python, FastAPI, SQLAlchemy + Alembic, PostgreSQL
- Auth: own JWT (access + refresh) via PyJWT; email/username/password
  registration with Argon2/bcrypt hashing; OAuth 2.0 / OpenID Connect
  login (Google, Yandex, VK) via Authlib. Protected routes use a
  get_current_user dependency.

Data model (current draft)
- User: email, username, password_hash (nullable for social-only users)
- SocialAccount: user, provider, provider_user_id (unique pair)
- Ingredient: name, created_by (null = global), calories/protein/fat/
  carbs per 100 g, grams_per_piece, grams_per_ml
- ShopProduct: ingredient, name, shop_name, pack_size_g, price
- Meal: name, created_by, servings
- RecipeItem: meal, ingredient, quantity, unit (g | ml | piece)
- WeekPlan: user, start_date; PlanSlot: plan, day, meal_type, meal, servings
- Leftover: user, ingredient, quantity_g (unique per user + ingredient)

Key design rules
- Grams are the base unit for every ingredient; all quantities convert
  to grams before any calorie, price or leftover calculation
- Never store derived totals (meal calories, list costs); compute them
- Meal suggestions rank meals by how much of their ingredients the
  pantry covers (scoring method still being decided)

Open decisions
- Meal suggestion scoring: share of ingredients, grams, or money saved
- Whether an OAuth login with an existing email links automatically

How to help me
- I'm building this partly to learn: explain the reasoning behind
  design choices, not just the code
- Point out bugs, weak designs and security issues directly
- Prefer clear, idiomatic FastAPI and SQLAlchemy code