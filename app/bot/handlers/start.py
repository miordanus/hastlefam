from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def start(message: Message):
    await message.answer('HastleFam bot is online. Use /capture to add an item.')
