import re
import os

# === НАСТРОЙКИ ===
INPUT_FILE = 'chat_history.txt'
OUTPUT_FILE = 'chat_history_smart.txt' 

# Максимальная длина одного предложения. 
# Если кусок текста длиннее этого (и не делится на части), мы считаем это спамом и удаляем.
MAX_SENTENCE_LENGTH = 100 

# Минимальная длина (чтобы не сохранять "а", "ы", "ок")
MIN_SENTENCE_LENGTH = 3
# =================

def smart_split():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл {INPUT_FILE} не найден!")
        return

    print("🔪 Начинаю нарезку длинных сообщений...")

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        original_lines = f.readlines()

    processed_sentences = []
    dropped_count = 0

    for line in original_lines:
        line = line.strip()
        if not line: continue

        # 1. Сначала пробуем разбить строку по знакам препинания (. ! ? ...)
        # Это регулярное выражение ищет конец предложения
        # Оно заменяет ". " на ".\n", чтобы разбить строку на много строк
        
        # Заменяем "Привет! Как дела?" на:
        # Привет!
        # Как дела?
        splitted = re.sub(r'(?<=[.!?…])\s+', '\n', line)
        
        # Получаем список потенциальных предложений
        candidates = splitted.split('\n')

        for sentence in candidates:
            sentence = sentence.strip()
            
            # Проверка длины
            if len(sentence) < MIN_SENTENCE_LENGTH:
                continue # Слишком короткое
            
            if len(sentence) > MAX_SENTENCE_LENGTH:
                # Если даже после разбивки предложение гигантское -> это мусор
                dropped_count += 1
                continue 

            processed_sentences.append(sentence)

    # Убираем дубликаты сразу
    unique_sentences = list(dict.fromkeys(processed_sentences))

    # Сохраняем
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_sentences))

    print("-" * 30)
    print("✅ ГОТОВО!")
    print(f"Было строк (сообщений): {len(original_lines)}")
    print(f"Стало строк (предложений): {len(unique_sentences)}")
    print(f"🗑️ Выброшено слишком длинных кусков: {dropped_count}")
    print(f"💾 Результат в файле: {OUTPUT_FILE}")
    print("-" * 30)
    print("Теперь можешь переименовать chat_history_smart.txt в chat_history.txt")

if __name__ == "__main__":
    smart_split()