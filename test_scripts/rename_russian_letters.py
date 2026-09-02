import os
import re
from pathlib import Path


def remove_russian_chars(filename: str) -> str:
    """
    Удаляет все русские символы из имени файла.
    """
    # Список русских букв (кириллица)
    russian_chars = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'

    # Транслитерация для русских букв
    translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }

    # Разделяем имя и расширение
    name, ext = os.path.splitext(filename)

    # Заменяем русские буквы
    new_name = ''.join(translit.get(char, char) for char in name)

    # Удаляем все, что не является буквами, цифрами, точкой или подчеркиванием
    new_name = re.sub(r'[^\w\-_.]', '_', new_name)

    # Убираем множественные подчеркивания
    new_name = re.sub(r'_+', '_', new_name)

    return f"{new_name}{ext}"


def simple_rename(folder_path: str):
    """
    Простое переименование файлов в папке.
    """
    folder = Path(folder_path)

    # Получаем все изображения
    extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']
    files = []
    for ext in extensions:
        files.extend(folder.glob(f'*{ext}'))

    print(f"Найдено файлов: {len(files)}")

    for file_path in files:
        new_name = remove_russian_chars(file_path.name)
        if new_name != file_path.name:
            new_path = file_path.parent / new_name
            if not new_path.exists():
                file_path.rename(new_path)
                print(f"Переименован: {file_path.name} -> {new_name}")
            else:
                print(f"Пропущен (файл с таким именем уже существует): {file_path.name}")


if __name__ == "__main__":
    INPUT_FOLDER = r"C:\Users\user\Desktop\Dataset_polution_2\Dataset_polution_2"
    simple_rename(INPUT_FOLDER)
    print("Готово!")