from aiogram import Router

from app.bot.handlers.admin import router as admin_router
from app.bot.handlers.backdate import router as backdate_router
from app.bot.handlers.history import router as history_router
from app.bot.handlers.menu import router as menu_router
from app.bot.handlers.onboarding import router as onboarding_router
from app.bot.handlers.payments_stars import router as payments_stars_router
from app.bot.handlers.questionnaire import router as questionnaire_router
from app.bot.handlers.reports import router as reports_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.subscription import router as subscription_router
from app.bot.handlers.workout import router as workout_router
from app.bot.handlers.workout_edit import router as workout_edit_router

# ВАЖНО: очерёдность include_router определяет приоритет — start и menu
# обязаны идти первыми, чтобы /start, /cancel и кнопки нижнего меню всегда
# перехватывали апдейт раньше хендлеров, завязанных на FSM-состояние (см.
# комментарии в start.py и menu.py).
router = Router()
router.include_router(start_router)
router.include_router(menu_router)
router.include_router(onboarding_router)
router.include_router(questionnaire_router)
router.include_router(subscription_router)
router.include_router(payments_stars_router)
router.include_router(workout_router)
router.include_router(workout_edit_router)
router.include_router(backdate_router)
router.include_router(history_router)
router.include_router(reports_router)
router.include_router(admin_router)
