import asyncio
import os
import psycopg
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import uvicorn
from aiogram.types import ChatMemberUpdated

bot = Bot(token=os.environ.get("BOT_TOKEN"))
dp = Dispatcher()
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
DB_URL = os.environ.get("DATABASE_URL")

def get_cursor():
    global conn
    try:
        conn.cursor().execute("SELECT 1")
    except Exception:
        conn = psycopg.connect(DB_URL, autocommit=True)
    return conn.cursor()

conn = psycopg.connect(DB_URL, autocommit=True)
get_cursor().execute("CREATE TABLE IF NOT EXISTS bot_users (user_id BIGINT PRIMARY KEY, last_post TEXT)")

@dp.chat_member(F.new_chat_member.status == "member")
async def on_user_join(event: ChatMemberUpdated):
    if event.chat.id != CHANNEL_ID:
        return

    bot_info = await bot.get_me()
    btn = InlineKeyboardButton(text="📝 Подать объявление", url=f"https://t.me/{helper_job26_bot}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])

    msg = await bot.send_message(
        chat_id=event.chat.id,
        text=f"Добро пожаловать, {event.new_chat_member.user.first_name}!\nПодать объявление можно в нашем боте.",
        reply_markup=kb
    )
    
    async def delete_later():
        await asyncio.sleep(300)
        try:
            await bot.delete_message(chat_id=event.chat.id, message_id=msg.message_id)
        except Exception:
            pass
    asyncio.create_task(delete_later())

class AdForm(StatesGroup):
    waiting_for_text = State()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    btn = InlineKeyboardButton(text="📝 Подать объявление", callback_data="start_ad")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn]])
    await message.answer("Привет! Нажми кнопку ниже:", reply_markup=kb)

@dp.callback_query(F.data == "start_ad")
async def process_start_ad(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cursor = get_cursor()
    cursor.execute("SELECT last_post FROM bot_users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()

    if row:
        last_post = datetime.fromisoformat(row[0])
        if datetime.now() - last_post < timedelta(hours=24):
            await callback.answer("Вы можете подать только 1 объявление в сутки!", show_alert=True)
            return
    await callback.message.answer("Отправьте текст вашего объявления одним сообщением:")
    await state.set_state(AdForm.waiting_for_text)
    await callback.answer()

@dp.message(AdForm.waiting_for_text)
async def process_ad_text(message: Message, state: FSMContext):
    ad_text = message.text
    user_id = message.from_user.id

    now_str = datetime.now().isoformat()
    get_cursor().execute("INSERT INTO bot_users (user_id, last_post) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET last_post = EXCLUDED.last_post", (user_id, now_str))

    await message.answer("Ваше объявление отправлено на модерацию! Ожидайте.")

    btn_ok = InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{user_id}")
    btn_no = InlineKeyboardButton(text="❌ Отклонить", callback_data="reject")
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn_ok, btn_no]])

    await bot.send_message(ADMIN_ID, f"Новое объявление на модерацию:\n\n{ad_text}", reply_markup=kb)
    await state.clear()

@dp.callback_query(F.data.startswith("approve_"))
async def process_approve(callback: CallbackQuery):
    author_id = callback.data.split("_")[1]
    ad_text = callback.message.text.replace("Новое объявление на модерацию:\n\n", "")
    await callback.message.edit_text(f"{callback.message.text}\n\n✅ ОДОБРЕНО")
    

    await bot.send_message(CHANNEL_ID, f"{ad_text}\n\n#Москва #Вакансия #Работа")
    await bot.send_message(author_id, "Ваше объявление одобрено и опубликовано в канале!")
    await callback.answer("Опубликовано!")

@dp.callback_query(F.data == "reject")
async def process_reject(callback: CallbackQuery):
    await callback.message.edit_text(f"{callback.message.text}\n\n❌ ОТКЛОНЕНО")
    await callback.answer("Отклонено!")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(f"{render_url}/webhook", allowed_updates=dp.resolve_used_update_types())
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        await bot.set_webhook(f"{render_url}/webhook")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    update_data = await request.json()
    update = types.Update(**update_data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))