import re
import os

# === НАСТРОЙКИ ===
INPUT_FILE = 'chat_history.txt'
OUTPUT_FILE = 'chat_history_clean.txt' # Сохраним в новый файл, чтобы не испортить оригинал
MIN_LENGTH = 2  # Минимальная длина сообщения (букв)
REMOVE_ENGLISH = True # True = удалять строки, где только английский (ghbdtn, asdfg)
# =================

def is_garbage(line):
    # 1. Убираем пробелы и переносы
    line = line.strip()
    
    # 2. Если строка пустая
    if not line:
        return True

    # 3. Если в строке одни цифры или знаки препинания (нет букв)
    # Ищем хотя бы одну букву (русскую или английскую)
    if not re.search(r'[a-zA-Zа-яА-ЯёЁ]', line):
        return True

    # 4. Если строка слишком короткая (меньше MIN_LENGTH букв)
    if len(line) < MIN_LENGTH:
        return True

    # 5. Фильтр "Забыл поменять раскладку" / Английский спам
    # Если строка состоит ТОЛЬКО из английских букв и символов (нет кириллицы)
    # Это удалит "ghbdtn", "hello", "lol", "asdf"
    if REMOVE_ENGLISH:
        # Если есть английские, но НЕТ русских -> считаем мусором
        if re.search(r'[a-zA-Z]', line) and not re.search(r'[а-яА-ЯёЁ]', line):
            return True

    # 6. Удаляем мусорные повторы типа "ааааааааааа" (более 4 одинаковых подряд)
    if re.search(r'(.)\1{4,}', line):
        return True

    return False

def clean_file():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Файл {INPUT_FILE} не найден!")
        return

    print("🔄 Начинаю очистку...")
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    unique_lines = set()
    cleaned_count = 0
    total_lines = len(lines)

    for line in lines:
        line = line.strip()
        
        # Проверка на мусор
        if is_garbage(line):
            continue
            
        # Проверка на дубликаты
        if line in unique_lines:
            continue
            
        unique_lines.add(line)
        cleaned_count += 1

    # Сохраняем результат
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(unique_lines))

    print(f"✅ Готово!")
    print(f"Было строк: {total_lines}")
    print(f"Стало строк: {cleaned_count}")
    print(f"Удалено мусора: {total_lines - cleaned_count}")
    print(f"Результат сохранен в: {OUTPUT_FILE}")
    print("⚠️ Теперь переименуй chat_history_clean.txt в chat_history.txt (или измени название в боте)")

if __name__ == "__main__":
    clean_file()