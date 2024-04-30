import logging
import os
import smtplib
import asyncio
from typing import List, Union
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.middlewares import BaseMiddleware

import config as cfg

API_TOKEN = cfg.TOKEN
SENDER_EMAIL = cfg.SENDER_EMAIL
PASSWORD = cfg.PASSWORD
RECEIVER_EMAIL = cfg.RECEIVER_EMAIL

# Настройте ведение журнала
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Папка для сохранения медиа-файлов
MEDIA_FOLDER = 'media'

# Создаем папку, если её еще нет
os.makedirs(MEDIA_FOLDER, exist_ok=True)

class AlbumMiddleware(BaseMiddleware):
  """This middleware is for capturing media groups."""

  album_data: dict = {}

  def __init__(self, latency: Union[int, float] = 0.01):
      """
      Вы можете обеспечить пользовательскую задержку, чтобы убедиться, что альбомы обрабатываются должным образом в условиях высокой нагрузки.
      """
      self.latency = latency
      super().__init__()

  async def on_process_message(self, message: types.Message, data: dict):
      if not message.media_group_id:
          return

      try:
          self.album_data[message.media_group_id].append(message)
          raise CancelHandler()  # Сообщите aiogram об отмене обработчика для этого элемента группы.
      except KeyError:
          self.album_data[message.media_group_id] = [message]
          await asyncio.sleep(self.latency)

          message.conf["is_last"] = True
          data["album"] = self.album_data[message.media_group_id]

  async def on_post_process_message(self, message: types.Message, result: dict, data: dict):
      """Убирайте за собой после работы с нашим альбомом."""
      if message.media_group_id and message.conf.get("is_last"):
          del self.album_data[message.media_group_id]

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
  await message.reply(
      "Привет! 👋\nЯ Анонимный Бот от Алматинского университета энергетики и связи имени Гумарбека Даукеева!\nВы можете оставить анонимное сообщение, просто введите команду /anon.")

@dp.message_handler(commands=['anon'])
async def send_anonymous_instruction(message: types.Message):
    await message.answer(
        "Вы можете оставить анонимное сообщение. Просто отправьте текст вашего сообщения, либо прикрепите медиа-файл.\nПожалуйста, обратите внимание, что максимальный размер одного прикрепленного файла или общий размер всех прикрепленных файлов не должен превышать 15 МБ. 📝📎")

MAX_FILE_SIZE = 15728640  # 15 MB

async def save_media(bot, media_group):
  media_paths = []  # Создаем пустой список для хранения путей к сохраненным медиа-файлам
  total_memory = 0
  for media in media_group.media:
      file_id = media.media
      file_type = media.type
  
      # Получаем информацию о файле
      file_info = await bot.get_file(file_id)
      total_memory += file_info.file_size
      file_path = file_info.file_path
  
      # Загружаем файл
      downloaded_file = await bot.download_file(file_path)

      # Определяем расширение файла в зависимости от типа медиа
      if file_type == "photo":
          file_extension = ".jpg"
      elif file_type == "video":
          file_extension = ".mp4"
      else:
          # В случае неизвестного типа медиа, пропускаем файл
          continue
  
      # Сохраняем файл в папку "media" с уникальным именем
      save_path = os.path.join("media", f"{file_id}{file_extension}")
      with open(save_path, "wb") as new_file:
          new_file.write(downloaded_file.getvalue())
      
      # Добавляем путь к сохраненному файлу в список
      media_paths.append(save_path)
  if total_memory > MAX_FILE_SIZE:
    return 0
  else:
    return media_paths  # Возвращаем список путей к сохраненным медиа-файлам

async def save_single_media(bot, message):
  if message.photo:
      file_info = await bot.get_file(message.photo[-1].file_id)
      file_extension = ".jpg"
  elif message.video:
      file_info = await bot.get_file(message.video.file_id)
      file_extension = ".mp4"
  else:
      return  # Нет медиа для сохранения
  if file_info.file_size > MAX_FILE_SIZE:
    return 0
  file_path = file_info.file_path
  downloaded_file = await bot.download_file(file_path)
  save_path = os.path.join("media", f"{file_info.file_unique_id}{file_extension}")
  
  with open(save_path, "wb") as new_file:
      new_file.write(downloaded_file.getvalue())
  
  return save_path

@dp.message_handler(is_media_group=True, content_types=types.ContentType.ANY)
async def handle_albums(message: types.Message, album: List[types.Message]):
    media_group = types.MediaGroup()
    for obj in album:
        if obj.photo:
            file_id = obj.photo[-1].file_id
        else:
            file_id = obj[obj.content_type].file_id
        try:
            media_group.attach({"media": file_id, "type": obj.content_type})
        except ValueError:
            return await message.answer("Извините, этот тип альбома не поддерживается 🤖")

    try:
        subject = "Анонимное сообщение от пользователя Telegram"
        body = message.caption if message.caption else "Пользователь отправил медиа-файлы 📷"

        media_paths = await save_media(bot, media_group)
        if media_paths == 0:
          await message.answer("Извините, общий размер прикрепленных файлов превышает 15 МБ 🚫")
        else:
          await message.answer("Подождите немного ⏳")

          # Отправляем сообщение
          await send_email(subject, body, media_paths)
  
          await message.answer("Ваше анонимное сообщение успешно отправлено 📬")

    except Exception as e:
        print(f'Не удалось обработать сообщение: {e}')

@dp.message_handler(content_types=types.ContentType.ANY)
async def process_message(message: types.Message):
    try:
        subject = "Анонимное сообщение от пользователя Telegram"
        body = message.text if message.text else (message.caption if message.caption else "Пользователь отправил медиа-файлы 📷")

        media_path = await save_single_media(bot, message)

        if media_path == 0:
          await message.answer("Извините, размер файла превышает 15 МБ 🚫")
        else:
          await message.answer("Подождите немного ⏳")

          # Отправляем сообщение
          await send_email(subject, body, [media_path])
  
          await message.answer("Ваше анонимное сообщение успешно отправлено 📬")

    except Exception as e:
        print(f'Не удалось обработать сообщение: {e}')

async def send_email(subject, body, media_paths):
  try:
      msg = MIMEMultipart()
      msg['From'] = SENDER_EMAIL
      msg['To'] = RECEIVER_EMAIL
      msg['Subject'] = subject

      # Добавляем текст сообщения
      msg.attach(MIMEText(body, 'plain', 'utf-8'))
      if media_paths == [None]:
          print("media_paths пустой")
      else:
          # Добавляем медиа-файлы к сообщению
          for media_path in media_paths:
              with open(media_path, 'rb') as f:
                  attachment = MIMEApplication(f.read(), Name=os.path.basename(media_path))
                  attachment['Content-Disposition'] = f'attachment; filename="{os.path.basename(media_path)}"'
                  msg.attach(attachment)

      with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
          server.login(SENDER_EMAIL, PASSWORD)
          server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
          print('Email sent successfully!')

  except Exception as e:
      print(f'Failed to send email: {e}')

if __name__ == "__main__":
  dp.middleware.setup(AlbumMiddleware())
  executor.start_polling(dp, skip_updates=True)