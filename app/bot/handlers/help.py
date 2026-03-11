from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command('help'))
async def help_cmd(message: Message):
    await message.answer('/capture <text> - create structured draft\n/review_weekly - weekly review agenda draft')
