"""
cancel.py — /cancel command handler.

Clears any active FSM state so the user can escape guided flows
(balance editing, tag input, date input, etc.) and return to normal
free-text expense capture.

Must be registered BEFORE all other routers so it always fires.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router()


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять. Просто пиши сумму и название.")
        return
    await state.clear()
    await message.answer("Отменено. Можешь снова записывать траты.")
