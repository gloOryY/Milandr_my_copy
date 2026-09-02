import os
import random
from pathlib import Path


def add_random_numbers_to_filenames(root_folder: str, num_digits: int = 10,
                                    extensions: list = None, recursive: bool = True):
    """
    Добавляет случайные цифры в конец названий файлов.

    Args:
        root_folder: Корневая папка для поиска
        num_digits: Количество случайных цифр
        extensions: Список расширений (по умолчанию ['.jpg', '.jpeg'])
        recursive: Искать ли во вложенных папках
    """
    if extensions is None:
        extensions = ['.jpg', '.jpeg']

    root_path = Path(root_folder)
    if not root_path.exists():
        print(f"Папка не найдена: {root_folder}")
        return

    # Поиск файлов (рекурсивно или только в текущей папке)
    files_to_rename = []
    for ext in extensions:
        if recursive:
            files_to_rename.extend(root_path.rglob(f'*{ext}'))
        else:
            files_to_rename.extend(root_path.glob(f'*{ext}'))

    if not files_to_rename:
        print(f"Файлы с расширениями {extensions} не найдены")
        return

    print(f"Найдено {len(files_to_rename)} файлов для обработки")
    print(f"Будет добавлено {num_digits} случайных цифр")
    print("-" * 80)

    renamed_count = 0
    used_names = set()

    for file_path in files_to_rename:
        # Генерируем уникальное случайное число
        max_attempts = 100
        for attempt in range(max_attempts):
            random_number = ''.join(str(random.randint(0, 9)) for _ in range(num_digits))
            new_name = f"{file_path.stem}_{random_number}{file_path.suffix}"
            new_path = file_path.parent / new_name

            if not new_path.exists() and new_name not in used_names:
                break
        else:
            print(f"✗ Не удалось сгенерировать уникальное имя для: {file_path.name}")
            continue

        try:
            file_path.rename(new_path)
            print(f"✓ {file_path.name} -> {new_name}")
            renamed_count += 1
            used_names.add(new_name)
        except Exception as e:
            print(f"✗ Ошибка при переименовании {file_path.name}: {e}")

    print("-" * 80)
    print(f"Успешно переименовано: {renamed_count} файлов")
    print(f"Всего найдено: {len(files_to_rename)} файлов")


if __name__ == "__main__":
    # Настройки
    ROOT_FOLDER = r"C:\Users\user\Desktop\Dataset_result"
    NUM_DIGITS = 10

    # Запуск
    add_random_numbers_to_filenames(ROOT_FOLDER, NUM_DIGITS)
    print("\nГотово!")