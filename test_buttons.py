import logging
import random
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor

TOKEN =  "токен ту зе мууууу  уууу уууун"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

user_states = {}  # Keeps track of user's current state
user_sequences = {}  # The sequence user has pressed so far


def generate_keyboard():
    sequence = [1, 2, 3]
    random.shuffle(sequence)
    keyboard = InlineKeyboardMarkup(row_width=3)
    buttons = [
        InlineKeyboardButton(str(number), callback_data=str(number))
        for number in sequence
    ]
    keyboard.add(*buttons)
    return keyboard


@dp.message_handler(commands=["test"])
async def cmd_start(message: types.Message):
    keyboard = generate_keyboard()
    await message.answer("Press the numbers in order:", reply_markup=keyboard)
    user_states[message.from_user.id] = "awaiting_sequence_start"
    user_sequences[message.from_user.id] = []


@dp.callback_query_handler(lambda call: call.data in ["1", "2", "3"])
async def process_callback_button_press(call: types.CallbackQuery):
    user_id = call.from_user.id
    pressed = int(call.data)

    # If user presses 1 and they are at the starting state
    if user_states.get(user_id) == "awaiting_sequence_start" and pressed == 1:
        user_states[user_id] = "awaiting_sequence_continue"
        user_sequences[user_id].append(pressed)

    # If user starts with the wrong button
    elif user_states.get(user_id) == "awaiting_sequence_start" and pressed != 1:
        user_sequences[user_id] = []
        keyboard = generate_keyboard()
        # await call.message.edit_text(
        #     "Press the numbers in order:", reply_markup=keyboard
        # )
        await call.answer("Incorrect start. Try again with 1.", show_alert=False)

    # If user is in the middle of the sequence
    elif user_states.get(user_id) == "awaiting_sequence_continue":
        user_sequences[user_id].append(pressed)

        # If the sequence is wrong
        if user_sequences[user_id] == [1, 3]:
            user_sequences[user_id] = []
            keyboard = generate_keyboard()
            await call.message.edit_text(
                "Press the numbers in order:", reply_markup=keyboard
            )
            await call.answer("Incorrect sequence. Restart with 1.", show_alert=False)

        # If the sequence is correct
        elif len(user_sequences[user_id]) == 3 and user_sequences[user_id] == [1, 2, 3]:
            await call.message.answer("Confirmed!")
            user_states[user_id] = "awaiting_sequence_start"
            user_sequences[user_id] = []

        # If the sequence is wrong and they've pressed three buttons
        elif len(user_sequences[user_id]) == 3:
            user_sequences[user_id] = []
            keyboard = generate_keyboard()
            # await call.message.edit_text(
            #     "Press the numbers in order:", reply_markup=keyboard
            # )
            await call.answer("Incorrect sequence. Restart with 1.", show_alert=False)

    else:
        await call.answer()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
