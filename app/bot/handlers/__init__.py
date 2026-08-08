from aiogram import Router

from app.bot.handlers.backdate import router as backdate_router
from app.bot.handlers.history import router as history_router
from app.bot.handlers.onboarding import router as onboarding_router
from app.bot.handlers.payments_stars import router as payments_stars_router
from app.bot.handlers.questionnaire import router as questionnaire_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.subscription import router as subscription_router
from app.bot.handlers.workout import router as workout_router
from app.bot.handlers.workout_edit import router as workout_edit_router

router = Router()
router.include_router(start_router)
router.include_router(onboarding_router)
router.include_router(questionnaire_router)
router.include_router(subscription_router)
router.include_router(payments_stars_router)
router.include_router(workout_router)
router.include_router(workout_edit_router)
router.include_router(backdate_router)
router.include_router(history_router)
