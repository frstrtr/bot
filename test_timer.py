import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor

TOKEN = "токен ту зе мууууу  уууу уууун"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# Variables to keep state and message IDs for users.
user_states = {}
user_messages = {}


async def start_countdown(user_id, action_result):
    seconds = 15
    while seconds:
        if user_states.get(user_id) != "waiting_for_confirmation":
            return  # Exit if state has changed

        keyboard = InlineKeyboardMarkup()
        label_button = InlineKeyboardButton(
            f"{action_result} : {seconds}s", callback_data="confirm"
        )
        keyboard.add(label_button)

        await bot.edit_message_text(
            f"Action Confirmation",
            user_id,
            user_messages[user_id],
            reply_markup=keyboard,
        )
        await asyncio.sleep(1)
        seconds -= 1

    if user_states.get(user_id) == "waiting_for_confirmation":
        keyboard = InlineKeyboardMarkup()
        thumbs_up_button = InlineKeyboardButton("👍", callback_data="thumbs_up")
        keyboard.add(thumbs_up_button)
        await bot.edit_message_text(
            f"Action Confirmation",
            user_id,
            user_messages[user_id],
            reply_markup=keyboard,
        )
        del user_states[user_id]


@dp.message_handler(commands=["test"])
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    thumbs_up_button = InlineKeyboardButton("👍", callback_data="thumbs_up")
    keyboard.add(thumbs_up_button)

    sent_message = await message.answer("Action Confirmation", reply_markup=keyboard)
    user_messages[message.from_user.id] = sent_message.message_id


@dp.callback_query_handler(lambda call: call.data == "thumbs_up")
async def process_callback_thumbs_up(call: types.CallbackQuery):
    action_result = "Confirm in"  # This could be dynamic based on some action.
    user_states[call.from_user.id] = "waiting_for_confirmation"
    asyncio.create_task(start_countdown(call.from_user.id, action_result))
    await call.answer()


@dp.callback_query_handler(lambda call: call.data == "confirm")
async def process_callback_confirm(call: types.CallbackQuery):
    if user_states.get(call.from_user.id) == "waiting_for_confirmation":
        user_states[call.from_user.id] = "confirmed"
        await bot.edit_message_text(
            "Action Confirmed!", call.from_user.id, call.message.message_id
        )
        await call.answer()


if __name__ == "__main__":
    from aiogram import executor

    executor.start_polling(dp, skip_updates=True)
