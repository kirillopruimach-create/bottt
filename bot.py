import asyncio
import json
import os
import re
import time
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (Message, CallbackQuery, ChatMemberUpdated, 
                           InlineKeyboardMarkup, InlineKeyboardButton)
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties

# настройки
BOT_TOKEN = "токен" # сюда надо вписать токен из BotFather в скобки
CONFIG_FILE = "base.json"
COOLDOWN_SECONDS = 300 # 5 минут кулдауна

RULES_TEXT = (
    "📜 <b>Правила предложки:</b>\n\n"
    "1. Новость должна быть от 50 до 700 символов.\n"
    "2. Без мата и бессмысленного набора букв.\n"
    "3. Можно прикрепить 1 фото.\n"
    "4. Отправлять посты можно не чаще 1 раза в 5 минут.\n\n"
    "Просто напиши текст (или прикрепи фото с текстом) и отправь мне!"
)
# это правила, если надо изменить то можно либо просто поменять текста, либо
# добавить между 4 правилом и последней строчкой такое:
# "5. правило.\n\n"

BAD_WORDS = ["блять", "сука", "пидор", "пидорас", "еблан", "нахуй", "пиздец" ] # список матов, можно дополнять

user_last_post_time = {}

router = Router()

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"is_configured": False, "admin_group_id": None, "channel_id": None}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

# антиспам
def check_spam(text: str) -> str:
    if not text:
        return "Пожалуйста, добавьте текст к вашей новости."
    
    if len(text) < 50: # можно изменить минимум символов
        return "❌ Новость слишком короткая (минимум 50 символов)."
    if len(text) > 700: # можно изменить максимум символов
        return "❌ Новость слишком длинная (максимум 700 символов)."
    
    # проверка на "аааааа" или "ыыыыы" (3 одинаковых символов подряд)
    if re.search(r'(.)\1{3,}', text):
        return "❌ Текст похож на спам (слишком много повторяющихся букв)."
    
    # проверка на маты
    text_lower = text.lower()
    for word in BAD_WORDS:
        if word in text_lower:
            return "❌ В тексте обнаружена нецензурная лексика или запрещенные слова."
            
    return None # если все окей то отправляем

# автонастройка
@router.my_chat_member()
async def auto_setup_handler(event: ChatMemberUpdated):
    if event.new_chat_member.status in ["administrator", "member", "creator"]:
        config = load_config()
        chat = event.chat
        
        # защита от других групп
        if config.get("is_configured"):
            if chat.id not in [config.get("admin_group_id"), config.get("channel_id")]:
                await event.bot.leave_chat(chat.id)
            return

        updated = False
        if chat.type in ["group", "supergroup"]:
            config["admin_group_id"] = chat.id
            updated = True
        elif chat.type == "channel":
            config["channel_id"] = chat.id
            updated = True
            
        if updated:
            if config["admin_group_id"] and config["channel_id"]:
                config["is_configured"] = True
            save_config(config)
            
            # если все окей, пишем что все сделано
            if config["is_configured"] and config["admin_group_id"]:
                await event.bot.send_message(
                    config["admin_group_id"], 
                    "✅ <b>Бот успешно настроен!</b> Группа и канал связаны. Ждем предложку."
                )

# приветствие
@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.chat.type != "private":
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")]
    ])
    await message.answer(
        "Привет! Я бот-предложка. Отправь мне свою новость (можно с фото), и админы её рассмотрят.", # можно изменить если надо
        reply_markup=kb
    )

@router.callback_query(F.data == "show_rules")
async def show_rules_cb(callback: CallbackQuery):
    await callback.message.answer(RULES_TEXT)
    await callback.answer()

# прием новостей
@router.message(F.chat.type == "private")
async def receive_news(message: Message, bot: Bot):
    config = load_config()
    if not config.get("is_configured"):
        return await message.answer("🛠 Бот еще не настроен администраторами. Попробуйте позже.")

    user_id = message.from_user.id

    # проверка кд
    current_time = time.time()
    last_time = user_last_post_time.get(user_id, 0)
    if current_time - last_time < COOLDOWN_SECONDS:
        remains = int(COOLDOWN_SECONDS - (current_time - last_time))
        return await message.answer(f"⏳ Вы отправляете новости слишком часто! Подождите еще {remains} сек.")

    # защита от альбомов
    # аиограм может присылать в одном сообщении только 1 фото, так и просим
    if message.media_group_id:
        return await message.answer("❌ Пожалуйста, прикрепите только 1 фото и добавьте к нему текст одним сообщением (не альбомом).")

    # достаем текст
    text = message.html_text or message.caption
    if not text:
         return await message.answer("❌ Вы прислали пустую новость. Напишите текст.")

    # проверка на спам
    spam_error = check_spam(text)
    if spam_error:
        return await message.answer(spam_error)

    user_last_post_time[user_id] = current_time

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")
        ]
    ])
    
    # копируем сообщение
    await bot.copy_message(
        chat_id=config["admin_group_id"],
        from_chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=admin_kb
    )
    
    await message.answer("✅ Ваша новость отправлена на модерацию!")

# кнопки админов
@router.callback_query(F.data.startswith("approve_") | F.data.startswith("reject_"))
async def admin_decision(callback: CallbackQuery, bot: Bot):
    config = load_config()
    action, user_id = callback.data.split("_")
    
    # чтоб кнопки работали только в нашей группе
    if callback.message.chat.id != config.get("admin_group_id"):
        return await callback.answer("Эта кнопка работает только в админке.", show_alert=True)

    if action == "approve":
        # копируем пост в канал
        await bot.copy_message(
            chat_id=config["channel_id"],
            from_chat_id=callback.message.chat.id,
            message_id=callback.message.message_id
        )
        
        # меняем сообщение
        await callback.message.edit_reply_markup(reply_markup=None)
        await bot.send_message(
            callback.message.chat.id, 
            f"✅ Пост опубликован администратором @{callback.from_user.username}",
            reply_to_message_id=callback.message.message_id
        )
        
        # одобрение юзерам
        try:
            await bot.send_message(user_id, "🎉 Ваша новость была одобрена и опубликована!")
        except:
            pass
            
    elif action == "reject":
        await callback.message.delete()
        await bot.send_message(
            callback.message.chat.id, 
            f"❌ Предложка отклонена администратором @{callback.from_user.username}"
        )
        
        # отклонение юзерам
        try:
            await bot.send_message(user_id, "😔 К сожалению, ваша новость была отклонена администрацией.")
        except:
            pass

    await callback.answer()

async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    
    print("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
