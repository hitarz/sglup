import discord
from discord import app_commands
from discord.ext import commands
import markovify
import os
import aiohttp
import io
import textwrap
import random
import time
import re
import hashlib
import threading 
import asyncio
from collections import deque
from PIL import Image, ImageDraw, ImageFont

# ================= НАСТРОЙКИ =================
TOKEN = 
DATA_FILE = 'chat_history.txt'
FONT_FILE = 'font.ttf' 
IMAGE_DIR = 'saved_images' 
FACES_DIR = 'faces' 
BANNED_WORDS_FILE = 'banned_words.txt'

MAX_IMAGES = 2500            
AUTO_REPLY_CHANCE = 37   
MAX_CHARS = 40

CHAT_MIN_LENGTH = 3
CHAT_MAX_LENGTH = 200
CHAT_DEDUP_CACHE = 50_000
CHAT_WRITE_BUFFER = 8

# Глобальные переменные настроек
LAZY_MODE = False
INTELLIGENCE = 50
# =============================================

def load_banned_words():
    if os.path.exists(BANNED_WORDS_FILE):
        with open(BANNED_WORDS_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()

BANNED_WORDS = load_banned_words()

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True 

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='S ', intents=intents)

    async def setup_hook(self):
        if not os.path.exists(IMAGE_DIR):
            os.makedirs(IMAGE_DIR)
        if not os.path.exists(FACES_DIR):
            os.makedirs(FACES_DIR)
        await self.tree.sync()
        print("✅ Команды синхронизированы!")

bot = MyBot()
bot.remove_command('help')

# --- ПАМЯТЬ КАРТИНОК ---

async def save_image_to_memory(attachment):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200: return
                data = await resp.read()
        
        filename = f"{int(time.time())}_{random.randint(100,999)}.jpg"
        filepath = os.path.join(IMAGE_DIR, filename)
        
        with open(filepath, 'wb') as f:
            f.write(data)
            
        files = [os.path.join(IMAGE_DIR, f) for f in os.listdir(IMAGE_DIR)]
        files.sort(key=os.path.getctime)
        
        while len(files) > MAX_IMAGES:
            os.remove(files.pop(0))
            
    except Exception as e:
        print(f"Ошибка сохранения: {e}")

def get_random_image_from_memory():
    if not os.path.exists(IMAGE_DIR): return None
    files = os.listdir(IMAGE_DIR)
    if not files: return None
    return os.path.join(IMAGE_DIR, random.choice(files))

def clean_message_text(message):
    content = message.content
    for user in message.mentions:
        content = content.replace(f"<@{user.id}>", user.display_name)
        content = content.replace(f"<@!{user.id}>", user.display_name)
    return content

# --- СОХРАНЕНИЕ ЧАТА В ФАЙЛ ---

def normalize_chat_line(text: str) -> str:
    text = re.sub(r'<a?:\w+:\d+>', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def is_garbage_line(line: str) -> bool:
    if not line or len(line) < CHAT_MIN_LENGTH:
        return True
    if len(line) > CHAT_MAX_LENGTH:
        return True
    if not re.search(r'[a-zA-Zа-яА-ЯёЁ]', line):
        return True
    if re.search(r'(.)\1{4,}', line):
        return True
    if any(bw in line.lower() for bw in BANNED_WORDS):
        return True
    return False

class ChatHistory:
    def __init__(self, path: str, dedup_cache_size: int = CHAT_DEDUP_CACHE):
        self.path = path
        self._lock = asyncio.Lock()
        self._buffer: list[str] = []
        self._seen: set[str] = set()
        self._recent: deque[str] = deque(maxlen=dedup_cache_size)
        self._load_seen_keys()

    @staticmethod
    def _key(line: str) -> str:
        return hashlib.md5(line.lower().encode('utf-8')).hexdigest()

    def _load_seen_keys(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                tail = deque(maxlen=self._recent.maxlen)
                for line in f:
                    line = line.strip()
                    if line:
                        tail.append(self._key(line))
            self._recent.extend(tail)
            self._seen = set(self._recent)
        except OSError as e:
            print(f"⚠️ Не удалось загрузить кэш чата: {e}")

    def _remember(self, line: str) -> bool:
        key = self._key(line)
        if key in self._seen:
            return False
        self._seen.add(key)
        self._recent.append(key)
        if len(self._recent) == self._recent.maxlen:
            self._seen = set(self._recent)
        return True

    async def add(self, raw_text: str) -> bool:
        line = normalize_chat_line(raw_text)
        if is_garbage_line(line):
            return False
        async with self._lock:
            if not self._remember(line):
                return False
            self._buffer.append(line)
            if len(self._buffer) >= CHAT_WRITE_BUFFER:
                await self._flush_locked()
        return True

    async def add_many(self, texts: list[str]) -> int:
        added = 0
        async with self._lock:
            for raw in texts:
                line = normalize_chat_line(raw)
                if is_garbage_line(line):
                    continue
                if self._remember(line):
                    self._buffer.append(line)
                    added += 1
            if self._buffer:
                await self._flush_locked()
        return added

    async def flush(self):
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self):
        if not self._buffer:
            return
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(self._buffer) + '\n')
        self._buffer.clear()

    def stats(self) -> dict:
        lines = 0
        size = 0
        if os.path.exists(self.path):
            size = os.path.getsize(self.path)
            with open(self.path, 'r', encoding='utf-8') as f:
                for _ in f:
                    lines += 1
        images = 0
        if os.path.exists(IMAGE_DIR):
            images = sum(
                1 for name in os.listdir(IMAGE_DIR)
                if os.path.isfile(os.path.join(IMAGE_DIR, name))
            )
        return {'lines': lines, 'bytes': size, 'images': images, 'buffered': len(self._buffer)}

chat_db = ChatHistory(DATA_FILE)

# --- ГЕНЕРАТОР МАРКОВА ---

def get_markov_text(seed_message=None):
    if not os.path.exists(DATA_FILE): return "Я пуст... Напиши /learn"
    
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        text = f.read()
    
    lines = text.splitlines()
    if len(lines) < 5: return "Мало данных."

    random.shuffle(lines)
    shuffled_text = "\n".join(lines)
    words_count = len(text.split())
    
    if INTELLIGENCE <= 33:
        model_state = 1
    elif INTELLIGENCE <= 85:
        model_state = 2
    else:
        model_state = 3 if words_count > 10000 else 2
        
    tries_limit = int(INTELLIGENCE * 2)
    char_limit = 25 if LAZY_MODE else 100 
    
    if LAZY_MODE:
        tries_limit = 10
    
    try:
        text_model = markovify.NewlineText(shuffled_text, state_size=model_state)
        
        for _ in range(20):
            sentence = None
            
            if seed_message and not LAZY_MODE:
                words = re.findall(r'\b\w+\b', seed_message.lower())
                words = [w for w in words if len(w) > 2]
                words.sort(key=len, reverse=True) 
                top_words = words[:5]
                random.shuffle(top_words)

                for word in top_words:
                    try:
                        temp_sentence = text_model.make_sentence_with_start(word, tries=tries_limit, strict=False)
                        if temp_sentence and len(temp_sentence) <= char_limit:
                            sentence = temp_sentence
                            break
                    except:
                        continue

            if not sentence:
                sentence = text_model.make_short_sentence(max_chars=char_limit, tries=tries_limit)
            
            if sentence:
                banned_words_self = ["сглыпа", "sglypa", "сглыпу", "сглыпе", "сглыпой", "сглып"]
                for bad_word in banned_words_self:
                    sentence = re.sub(bad_word, "", sentence, flags=re.IGNORECASE)
                
                sentence = " ".join(sentence.split())
                
                words_list = sentence.lower().split()
                has_loop = False
                for i in range(len(words_list) - 3):
                    if words_list[i:i+2] == words_list[i+2:i+4]:
                        has_loop = True
                        break
                if has_loop:
                    continue
                
                is_banned = any(bw in sentence.lower() for bw in BANNED_WORDS)
                if not is_banned and sentence.strip():
                    return sentence 

        return random.choice(["Эээ...", "Хмм...", "Лень думать", "Кек", "Понял"])
    except Exception as e:
        return f"Эээ... ({e})"

# --- НАСТРОЙКИ (Команды) ---

@bot.command(name="lazy")
async def toggle_lazy(ctx):
    global LAZY_MODE
    LAZY_MODE = not LAZY_MODE
    await ctx.send(f"🥱 Режим Лени: **{'ВКЛЮЧЕН' if LAZY_MODE else 'ВЫКЛЮЧЕН'}**.")

@bot.command(name="i")
async def set_smart(ctx, value: int = None):
    global INTELLIGENCE
    if value is None or value < 1 or value > 100:
        await ctx.send("⚠️ Ошибка: Укажите уровень интеллекта от 1 до 100. (Пример: `S i 80`)")
        return
        
    INTELLIGENCE = value
    
    if value <= 33:
        status = "state_size=1 (Хаос и бред)"
    elif value <= 85:
        status = "state_size=2 (Нормальная речь)"
    else:
        status = "state_size=3 (Высокая точность)"
        
    await ctx.send(f"🧠 Уровень интеллекта установлен на: **{INTELLIGENCE}/100**.\n`Технические параметры: {status}, лимит попыток: {INTELLIGENCE * 2}`")

@bot.command(name="b")
async def ban_word(ctx, *, word: str):
    word = word.strip().lower()
    BANNED_WORDS.add(word)
    with open(BANNED_WORDS_FILE, 'a', encoding='utf-8') as f:
        f.write(word + '\n')
    await ctx.send(f"🚫 Слово `{word}` добавлено в бан-лист.")

# --- КОМАНДА HELP ---

@bot.command(name="help", aliases=["команды", "cmds", "помощь"])
async def custom_help(ctx):
    help_text = """
**🤖 СПИСОК КОМАНД БОТА**

**🧠 Настройки мозга**
`S lazy` — Включить/выключить режим лени (короткие ответы).
`S i <1-100>` — Настроить интеллект (1 - хаос, 100 - логика).
`S b <слово>` — Добавить слово в бан-лист бота.

**🎨 Генерация контента**
`S g a [текст]` — Сгенерировать анекдот (можно задать начало).
`S g c <1-8>` — Нарисовать комикс с заданным числом кадров.
`S demot` — Сделать демотиватор. *Лайфхак: ответь этой командой на чужую картинку.*

**⚙️ Системные (Слэш-команды `/`)**
`/learn <число>` — Выучить историю чата и сохранить новые картинки.
`/cleandb` — Удалить дубликаты из текстовой базы (ускоряет работу).
`/stats` — Размер базы: строки, файл, картинки в памяти.
`/demot` — Сделать мем из случайной картинки в памяти.
`/g` — Сгенерировать мысль в чат.
"""
    await ctx.send(help_text)

# --- ГРУППА КОМАНД ГЕНЕРАЦИИ (S g ...) ---

@bot.group(name="g", invoke_without_command=True)
async def generate_group(ctx, *, user_text: str = None):
    response = get_markov_text(seed_message=user_text) if user_text else get_markov_text()
    if user_text:
        response = f"{user_text} {response}"
    await ctx.send(response)

@generate_group.command(name="a")
async def gen_anecdote(ctx, *, start_text: str = None):
    async with ctx.typing():
        lines = []
        
        # Завязка
        if start_text:
            first = get_markov_text(seed_message=start_text)
            lines.append(f"— {start_text} {first.lower()}")
        else:
            lines.append(f"— {get_markov_text()}")
            
        # Развитие (1-2 случайные реплики)
        for _ in range(random.randint(1, 2)):
            lines.append(f"— {get_markov_text()}")
            
        # Панчлайн (короткий ответ для эффекта неожиданности)
        global LAZY_MODE
        old_lazy = LAZY_MODE
        LAZY_MODE = True 
        lines.append(f"— {get_markov_text()}")
        LAZY_MODE = old_lazy
        
        await ctx.send("\n".join(lines))

@generate_group.command(name="c")
async def gen_comic(ctx, num: int = 4):
    if num < 1 or num > 8:
        await ctx.send("⚠️ Число ячеек должно быть от 1 до 8!")
        return
        
    async with ctx.typing():
        cols = 2 if num > 1 else 1
        rows = (num + cols - 1) // cols
        
        panel_w = 400
        panel_h = 400
        
        canvas = Image.new('RGB', (cols * panel_w, rows * panel_h), 'white')
        draw = ImageDraw.Draw(canvas)
        
        try:
            font = ImageFont.truetype(FONT_FILE, 24)
        except:
            font = ImageFont.load_default()
            
        faces = []
        if os.path.exists(FACES_DIR):
            faces = [os.path.join(FACES_DIR, f) for f in os.listdir(FACES_DIR) if f.endswith(('.png', '.jpg', '.jpeg'))]

        for i in range(num):
            x = (i % cols) * panel_w
            y = (i // cols) * panel_h
            
            draw.rectangle([x, y, x+panel_w, y+panel_h], outline='black', width=3)
            
            text = get_markov_text()
            lines = textwrap.wrap(text, width=28)
            y_text = y + 20
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                w = bbox[2] - bbox[0]
                draw.text((x + (panel_w - w)/2, y_text), line, font=font, fill='black')
                y_text += 30
                
            if faces:
                try:
                    face_path = random.choice(faces)
                    face_img = Image.open(face_path).convert("RGBA")
                    max_face_size = 250
                    face_img.thumbnail((max_face_size, max_face_size), Image.Resampling.LANCZOS)
                    
                    fx = x + (panel_w - face_img.width) // 2
                    fy = y + panel_h - face_img.height - 20
                    
                    if fy < y_text + 10: fy = y_text + 10 
                    
                    bg = Image.new("RGBA", face_img.size, (255, 255, 255, 0))
                    bg.paste(face_img, (0, 0), face_img)
                    canvas.paste(bg, (int(fx), int(fy)), bg)
                except:
                    pass

        output = io.BytesIO()
        canvas.save(output, 'PNG')
        output.seek(0)
        await ctx.send(file=discord.File(fp=output, filename='comic.png'))

# --- РИСОВАЛКА ДЕМОТИВАТОРОВ И КОНСОЛЬ ---
async def create_demotivator(image_source, text, is_local_file=False):
    if is_local_file:
        with open(image_source, 'rb') as f:
            data = f.read()
    else:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_source) as resp:
                data = await resp.read()

    img = Image.open(io.BytesIO(data)).convert("RGB")
    target_width = 500
    aspect_ratio = img.height / img.width
    target_height = int(target_width * aspect_ratio)
    img = img.resize((target_width, target_height))

    padding = 30
    bottom_text_area = 80 + (len(text) // 30 * 40)
    
    canvas = Image.new('RGB', (target_width + padding*2, target_height + padding*2 + bottom_text_area), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    
    draw.rectangle([padding-5, padding-5, target_width+padding+5, target_height+padding+5], outline="white", width=2)
    canvas.paste(img, (padding, padding))

    try:
        font = ImageFont.truetype(FONT_FILE, 28)
    except:
        font = ImageFont.load_default()

    lines = textwrap.wrap(text, width=30)
    y_text = target_height + padding + 30
    
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x_text = (canvas.width - text_w) / 2
        draw.text((x_text, y_text), line, font=font, fill="white")
        y_text += bbox[3] - bbox[1] + 5

    output = io.BytesIO()
    canvas.save(output, 'PNG')
    output.seek(0)
    return output

async def send_console_demot(channel_id, text):
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"❌ Канал {channel_id} не найден.")
            return

        local_file = get_random_image_from_memory()
        if not local_file: return
        file_data = await create_demotivator(local_file, text, is_local_file=True)
        await channel.send(file=discord.File(fp=file_data, filename='demot.png'))
        print("✅ Отправлено!")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def console_reader():
    print("\n[CONSOLE] Формат: ID_КАНАЛА ТЕКСТ")
    while True:
        try:
            user_input = input() 
            if not user_input.strip(): continue
            parts = user_input.split(' ', 1)
            if len(parts) >= 2:
                asyncio.run_coroutine_threadsafe(send_console_demot(int(parts[0]), parts[1]), bot.loop)
        except: pass

# --- ИВЕНТЫ И СТАНДАРТНЫЕ КОМАНДЫ ---

@bot.event
async def on_ready():
    print(f'🤖 {bot.user} готов!')
    s = chat_db.stats()
    print(f'📚 База: {s["lines"]} строк, {s["images"]} картинок')
    threading.Thread(target=console_reader, daemon=True).start()

@bot.event
async def on_disconnect():
    await chat_db.flush()

@bot.event
async def on_message(message):
    if message.author.bot: return

    if message.attachments:
        for att in message.attachments:
            if att.content_type and att.content_type.startswith('image'):
                await save_image_to_memory(att)

    trigger_words = ["сглыпа", "sglypa", "сглыпу", "сглыпе", "сглып", "глып", "хахол", "хохол"]
    triggered = any(word in message.content.lower() for word in trigger_words)

    if triggered:
        should_send_image = random.choice([True, False])
        local_file = get_random_image_from_memory()
        if should_send_image and local_file:
            try:
                text = get_markov_text(seed_message=message.content)
                file_data = await create_demotivator(local_file, text, is_local_file=True)
                await message.reply(file=discord.File(fp=file_data, filename='demot.png'))
            except:
                await message.reply(get_markov_text(seed_message=message.content))
        else:
            await message.reply(get_markov_text(seed_message=message.content))
    
    elif not message.content.startswith(('S ', '/')):
        if random.randint(1, AUTO_REPLY_CHANCE) == 1:
            async with message.channel.typing(): 
                if random.choice([True, False]):
                    await message.channel.send(get_markov_text(seed_message=message.content))
                else:
                    local_file = get_random_image_from_memory()
                    if local_file:
                        try:
                            text = get_markov_text(seed_message=message.content)
                            file_data = await create_demotivator(local_file, text, is_local_file=True)
                            await message.channel.send(file=discord.File(fp=file_data, filename='demot.png'))
                        except:
                            await message.channel.send(get_markov_text())

    if not message.content.startswith(('S ', '/')):
        await chat_db.add(clean_message_text(message))

    await bot.process_commands(message)

# Демотиватор
@bot.command(name='demot')
async def demot_text(ctx):
    target_url = None
    is_local = False
    
    if ctx.message.reference:
        original_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if original_msg.attachments: target_url = original_msg.attachments[0].url
    elif ctx.message.attachments:
        target_url = ctx.message.attachments[0].url

    if not target_url:
        local_file = get_random_image_from_memory()
        if local_file:
            target_url, is_local = local_file, True
        else:
            return await ctx.send("Нет картинок в памяти!")

    user_text = ctx.message.content.replace("S demot", "")
    text = get_markov_text(seed_message=user_text if user_text else None)
    file_data = await create_demotivator(target_url, text, is_local_file=is_local)
    await ctx.send(file=discord.File(fp=file_data, filename='demot.png'))

@bot.tree.command(name="cleandb", description="Удалить дубликаты и мусор из базы")
async def clean_db_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    if not os.path.exists(DATA_FILE):
        return await interaction.followup.send("База данных пуста.")
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        raw_lines = [line.strip() for line in f if line.strip()]
    original_count = len(raw_lines)
    unique_lines = []
    seen = set()
    for line in raw_lines:
        line = normalize_chat_line(line)
        if is_garbage_line(line):
            continue
        key = ChatHistory._key(line)
        if key in seen:
            continue
        seen.add(key)
        unique_lines.append(line)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_lines) + ('\n' if unique_lines else ''))
    chat_db._seen = seen
    chat_db._recent = deque(seen, maxlen=CHAT_DEDUP_CACHE)
    await interaction.followup.send(
        f"🧹 Было: {original_count} | Стало: {len(unique_lines)} "
        f"(удалено дублей/мусора: {original_count - len(unique_lines)})"
    )

@bot.tree.command(name="learn", description="Учить историю")
async def learn_slash(interaction: discord.Interaction, amount: int):
    await interaction.response.defer()
    texts = []
    img_count = 0
    async for msg in interaction.channel.history(limit=amount):
        if msg.author.bot:
            continue
        if msg.content:
            texts.append(clean_message_text(msg))
        if msg.attachments:
            for att in msg.attachments:
                if att.content_type and att.content_type.startswith('image'):
                    await save_image_to_memory(att)
                    img_count += 1
    count = await chat_db.add_many(texts)
    await interaction.followup.send(f"✅ Добавлено {count} новых строк, {img_count} картинок.")

@bot.tree.command(name="stats", description="Статистика базы знаний")
async def stats_slash(interaction: discord.Interaction):
    s = chat_db.stats()
    mb = s['bytes'] / (1024 * 1024)
    await interaction.response.send_message(
        f"📊 **База чата**\n"
        f"Строк: **{s['lines']}**\n"
        f"Файл: **{mb:.2f} MB**\n"
        f"Картинок: **{s['images']}** / {MAX_IMAGES}\n"
        f"В буфере (ещё не на диске): **{s['buffered']}**"
    )

if not TOKEN:
    raise SystemExit('Укажите DISCORD_TOKEN в .env или переменных окружения.')

bot.run(TOKEN)
