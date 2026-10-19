import time
from pathlib import Path
import project.algorithms.neural_network.networks_vault as nv
import cv2
from project.algorithms.detection_cutting_error import find_cutting_error_defects
from project.configuration.config_manager import ConfigManager

if __name__ == "__main__":

    config = ConfigManager(page=None)

    nv.networks_init()

    INPUT_FOLDER = r"C:\Users\user\Desktop\trouble_frames"
    OUTPUT_FOLDER = r"C:\Users\user\Desktop\results_old"

    input_folder = Path(INPUT_FOLDER)
    output_folder = Path(OUTPUT_FOLDER)

    output_folder.mkdir(parents=True, exist_ok=True)

    # Проверка существования папки
    if not input_folder.exists():
        print(f"ОШИБКА: Папка не найдена: {input_folder}")
        exit()

    # Получаем список всех JPG файлов в папке
    image_extensions = ['.jpg']
    image_files = []

    for ext in image_extensions:
        image_files.extend(input_folder.glob(f"*{ext}"))

    # Сортируем файлы для удобства
    image_files = sorted(image_files)

    if not image_files:
        print(f"В папке {input_folder} не найдено JPG файлов")
        exit()

    print(f"Найдено {len(image_files)} изображений для обработки")
    print("=" * 60)

    total_images = len(image_files)
    processed_images = 0
    images_with_defects = 0
    total_defects_all = 0

    start_time_total = time.time()

    # Цикл по всем изображениям
    for idx, image_path in enumerate(image_files, 1):

        # if idx > 10:
        #     break

        print(f"\nОбработка [{idx}/{total_images}]: {image_path.name}")

        # Загрузка изображения
        frame_original = cv2.imread(str(image_path))

        if frame_original is None:
            print(f"  ОШИБКА: Не удалось загрузить изображение: {image_path.name}")
            continue

        print(f"  Размер: {frame_original.shape[1]}x{frame_original.shape[0]}")

        # Запуск детекции
        start_time = time.time()

        try:
            total_defects, defects_info, result_frame = find_cutting_error_defects(
                frame_original=frame_original,
                frame_filtered=frame_original.copy()
            )

            elapsed = time.time() - start_time
            print(f"  Детекция завершена за {elapsed:.2f}с")

            # Вывод результатов для текущего изображения
            if total_defects > 0:
                images_with_defects += 1
                total_defects_all += total_defects

                print(f"  Найдено дефектов: {total_defects}")
                for info in defects_info:
                    print(f"    - {info['name']}: {info['count']} шт.")

                # Сохраняем результат
                output_path = output_folder / f"filtered_{image_path.name}"
                cv2.imwrite(str(output_path), result_frame)
                print(f"  Результат сохранён: {output_path.name}")

            else:
                print(f"  Дефектов не найдено")

            processed_images += 1

        except Exception as e:
            print(f"  ОШИБКА при обработке {image_path.name}: {str(e)}")
            continue

        print("-" * 60)

    # Итоговая статистика
    total_elapsed = time.time() - start_time_total
    print("\n" + "=" * 60)
    print("ОБРАБОТКА ЗАВЕРШЕНА")
    print("=" * 60)
    print(f"Всего изображений: {total_images}")
    print(f"Обработано успешно: {processed_images}")
    print(f"Изображений с дефектами: {images_with_defects}")
    print(f"Всего найдено дефектов: {total_defects_all}")
    print(f"Общее время: {total_elapsed:.2f}с")
    print(f"Среднее время на изображение: {total_elapsed / processed_images:.2f}с")
    print(f"Результаты сохранены в: {output_folder}")
