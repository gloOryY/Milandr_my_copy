import os
import cv2
from pathlib import Path
from math import ceil
from typing import Tuple, List

from project.station.camera.frame_capture import rotate_frame


def convert_png_to_jpg(input_folder: str):
    """
    Конвертирует все PNG файлы в папке в JPG.
    """
    png_files = list(Path(input_folder).glob('*.png'))

    for png_path in png_files:
        jpg_path = png_path.with_suffix('.jpg')

        # Пропускаем, если JPG уже существует
        if jpg_path.exists():
            print(f"JPG уже существует: {jpg_path}")
            continue

        # Читаем PNG и сохраняем как JPG
        image = cv2.imread(str(png_path))
        if image is not None:
            cv2.imwrite(str(jpg_path), image, [cv2.IMWRITE_JPEG_QUALITY, 100])
            print(f"Конвертирован: {png_path.name} -> {jpg_path.name}")
        else:
            print(f"Не удалось прочитать PNG: {png_path}")

    print(f"Конвертация завершена. Обработано {len(png_files)} PNG файлов")


def get_tile_coords(image_shape: Tuple[int, int], tile_size: Tuple[int, int] = (1280, 720), min_overlap: float = 0.1) -> \
        List[Tuple[int, int]]:
    """
    Возвращает список координат (x, y) левого верхнего угла для тайлов.
    """
    h, w = image_shape
    tile_w, tile_h = tile_size

    step_w = int(tile_w * (1 - min_overlap))
    step_h = int(tile_h * (1 - min_overlap))

    n_cols = ceil((w - tile_w) / step_w) + 1 if w > tile_w else 1
    n_rows = ceil((h - tile_h) / step_h) + 1 if h > tile_h else 1

    if n_cols > 1:
        step_w = (w - tile_w) / (n_cols - 1)
    if n_rows > 1:
        step_h = (h - tile_h) / (n_rows - 1)

    x_coords = [min(int(col * step_w), w - tile_w) for col in range(n_cols)]
    y_coords = [min(int(row * step_h), h - tile_h) for row in range(n_rows)]

    return [(x, y) for y in y_coords for x in x_coords]


def split_image_into_tiles(image_path: str, output_dir: str, tile_size: Tuple[int, int] = (1280, 720),
                           min_overlap: float = 0.1):
    """
    Разбивает изображение на фрагменты и сохраняет их в папку.
    """
    # Чтение изображения
    image = cv2.imread(image_path)
    if image is None:
        print(f"Не удалось загрузить изображение: {image_path}")
        return

    image = rotate_frame(image, rotate_angle=90)

    # Создание папки для текущего изображения
    image_name = Path(image_path).stem
    image_folder = os.path.join(output_dir, image_name)
    os.makedirs(image_folder, exist_ok=True)

    # Получение координат тайлов
    h, w = image.shape[:2]
    tile_coords = get_tile_coords((h, w), tile_size, min_overlap)

    # Сохранение фрагментов
    for idx, (x, y) in enumerate(tile_coords):
        tile = image[y:y + tile_size[1], x:x + tile_size[0]]
        tile_filename = f"tile_{idx:04d}_x{x}_y{y}.jpg"
        tile_path = os.path.join(image_folder, tile_filename)
        cv2.imwrite(tile_path, tile)

    print(f"Изображение {image_name}: сохранено {len(tile_coords)} фрагментов в {image_folder}")


def process_images(input_folder: str, output_folder: str, tile_size: Tuple[int, int] = (1280, 720),
                   min_overlap: float = 0.1):
    """
    Обрабатывает все JPG изображения из папки.
    """
    # Создание выходной папки
    os.makedirs(output_folder, exist_ok=True)

    # Поиск JPG файлов
    image_extensions = ['.jpg']
    image_files = []

    for ext in image_extensions:
        image_files.extend(Path(input_folder).glob(f'*{ext}'))

    if not image_files:
        print(f"JPG файлы не найдены в папке: {input_folder}")
        return

    print(f"Найдено {len(image_files)} изображений")

    # Обработка каждого изображения
    for image_path in image_files:
        split_image_into_tiles(str(image_path), output_folder, tile_size, min_overlap)


if __name__ == "__main__":
    # Настройки
    INPUT_FOLDER = r"C:\Users\user\Desktop\Dataset_polution_2\Dataset_polution_2"  # Папка с исходными фотографиями
    OUTPUT_FOLDER = r"C:\Users\user\Desktop\Dataset_result"  # Папка для сохранения фрагментов
    TILE_SIZE = (1280, 720)  # Размер фрагмента (ширина, высота)
    MIN_OVERLAP = 0.1  # Минимальное перекрытие (10%)

    # Конвертируем PNG в JPG перед обработкой
    convert_png_to_jpg(INPUT_FOLDER)

    # Запуск обработки
    process_images(INPUT_FOLDER, OUTPUT_FOLDER, TILE_SIZE, MIN_OVERLAP)
