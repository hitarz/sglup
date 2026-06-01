import os
import hashlib

# ================= НАСТРОЙКИ =================
TARGET_FOLDER = 'saved_images' # Имя папки, которую чистим
# =============================================

def calculate_hash(filepath):
    """Считает уникальный 'отпечаток' файла (MD5)"""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        # Читаем кусками, чтобы не забить память, если картинка большая
        buf = f.read(65536)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()

def clean_duplicates(directory):
    print(f"🔄 Начинаю сканирование папки: {directory}...")
    
    if not os.path.exists(directory):
        print(f"❌ Ошибка: Папка '{directory}' не найдена!")
        print("Убедись, что программа лежит рядом с папкой saved_images.")
        input("\nНажми Enter для выхода...")
        return

    hashes = {} # Тут будем хранить уникальные хеши
    duplicates_count = 0
    total_files = 0
    
    # Получаем список всех файлов
    files = os.listdir(directory)
    
    for filename in files:
        filepath = os.path.join(directory, filename)
        
        # Пропускаем, если это папка, а не файл
        if os.path.isdir(filepath):
            continue
            
        total_files += 1
        
        try:
            # Считаем хеш файла
            file_hash = calculate_hash(filepath)
            
            if file_hash in hashes:
                # Если такой хеш уже был -> это дубликат
                print(f"🗑️ Удален дубликат: {filename}")
                os.remove(filepath)
                duplicates_count += 1
            else:
                # Если хеша не было -> запоминаем файл как оригинал
                hashes[file_hash] = filename
                
        except Exception as e:
            print(f"⚠️ Ошибка при чтении {filename}: {e}")

    print("\n" + "="*30)
    print("✅ ГОТОВО!")
    print(f"📂 Проверено файлов: {total_files}")
    print(f"🔥 Удалено дубликатов: {duplicates_count}")
    print(f"💾 Осталось уникальных: {len(hashes)}")
    print("="*30)
    input("\nНажми Enter, чтобы закрыть...")

if __name__ == "__main__":
    clean_duplicates(TARGET_FOLDER)