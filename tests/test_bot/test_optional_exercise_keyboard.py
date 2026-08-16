from app.bot.keyboards import optional_exercise_keyboard


def test_offers_squats_lunges_and_skip():
    markup = optional_exercise_keyboard()

    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callbacks == ["optional_exercise:squats", "optional_exercise:lunges", "optional_exercise:skip"]
