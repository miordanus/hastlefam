from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command('capture'))
async def capture(message: Message):
    payload = message.text.replace('/capture', '', 1).strip() if message.text else ''
    await message.answer(f'Captured draft text: {payload or "(empty)"}. Confirm/edit flow is placeholder.')


@router.message(Command('review_weekly'))
async def review_weekly(message: Message):
    await message.answer('Weekly review agenda draft placeholder.')
