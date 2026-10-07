import cv2
import numpy as np
from pathlib import Path
import datetime
from typing import List, Tuple, Optional
from project.application.addition.logger import logger
from project.station.camera.frame_process import save_frame


def detect_crosses_on_frame(frame: np.ndarray,
                            black_threshold: int = 50,
                            min_width: int = 6,
                            min_length: int = 600,
                            dir_save: Optional[Path] = None) -> List[Tuple[int, int]]:
    """
    Детектирует пересечения (крестовины) на изображении с камеры.

    Args:
        frame: Изображение с камеры (numpy array)
        black_threshold: Порог для определения черных пикселей (0-255)
        min_width: Минимальная ширина линии в пикселях
        min_length: Минимальная длина линии в пикселях
        dir_save: Директория для сохранения фотографии для отладки

    Returns:
        List[Tuple[int, int]]: Список координат центров пересечений (x, y) в пикселях исходного изображения
    """
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        # Конвертация в оттенки серого, если изображение цветное
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()

        # Создаем бинарное изображение: черные пиксели (<= threshold) оставляем черными, остальные делаем белыми
        binary_image = np.ones_like(gray) * 255
        binary_image[gray <= black_threshold] = 0

        # Сохраняем промежуточный результат, если указана папка
        if dir_save:
            save_frame(frame=binary_image, filename=f"041_Черно_белая_маска_{timestamp}.jpg", dir_save=dir_save)

        # Инвертируем изображение (линии становятся белыми на черном)
        inverted = cv2.bitwise_not(binary_image)

        # Создаем структурные элементы для выделения линий
        kernel_horiz = cv2.getStructuringElement(cv2.MORPH_RECT, (min_length, 1))
        kernel_vert = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_length))

        # Выделяем горизонтальные и вертикальные линии
        lines_horiz = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, kernel_horiz)
        lines_vert = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, kernel_vert)

        # Фильтруем по ширине
        kernel_thick = cv2.getStructuringElement(cv2.MORPH_RECT, (min_width, min_width))
        lines_horiz = cv2.morphologyEx(lines_horiz, cv2.MORPH_OPEN, kernel_thick)
        lines_vert = cv2.morphologyEx(lines_vert, cv2.MORPH_OPEN, kernel_thick)

        # Находим контуры линий
        contours_horiz, _ = cv2.findContours(lines_horiz, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours_vert, _ = cv2.findContours(lines_vert, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Находим пересечения горизонтальных и вертикальных линий
        intersections = []
        for h_contour in contours_horiz:
            # Создаем маску для текущей горизонтальной линии
            h_mask = np.zeros_like(binary_image)
            cv2.drawContours(h_mask, [h_contour], -1, 255, thickness=cv2.FILLED)

            for v_contour in contours_vert:
                # Создаем маску для текущей вертикальной линии
                v_mask = np.zeros_like(binary_image)
                cv2.drawContours(v_mask, [v_contour], -1, 255, thickness=cv2.FILLED)

                # Находим пересечение масок
                intersection = cv2.bitwise_and(h_mask, v_mask)

                # Находим центры пересечений
                intersection_points = cv2.findNonZero(intersection)
                if intersection_points is not None:
                    num_labels, labels = cv2.connectedComponents(intersection)
                    for i in range(1, num_labels):
                        mask = (labels == i).astype(np.uint8) * 255
                        moments = cv2.moments(mask)
                        if moments['m00'] > 0:
                            cx = int(moments['m10'] / moments['m00'])
                            cy = int(moments['m01'] / moments['m00'])
                            intersections.append((cx, cy))

        # Удаляем дубликаты пересечений (могут появиться из-за разных комбинаций контуров)
        unique_intersections = []
        tolerance = 5  # Допуск в пикселях для определения дубликатов
        for point in intersections:
            is_duplicate = False
            for unique_point in unique_intersections:
                if abs(point[0] - unique_point[0]) <= tolerance and abs(point[1] - unique_point[1]) <= tolerance:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_intersections.append(point)

        # Сохраняем визуализацию, если указана папка и найдены пересечения
        if dir_save and len(unique_intersections) > 0:
            # Создаем цветное изображение для визуализации
            overlay = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR)

            # Рисуем горизонтальные линии (синим цветом)
            cv2.drawContours(overlay, contours_horiz, -1, (255, 0, 0), 2)

            # Рисуем вертикальные линии (красным цветом)
            cv2.drawContours(overlay, contours_vert, -1, (0, 0, 255), 2)

            # Отмечаем центры пересечений (зеленым цветом)
            for (x, y) in unique_intersections:
                cv2.circle(overlay, (x, y), 5, (0, 255, 0), -1)
                cv2.circle(overlay, (x, y), 7, (0, 255, 0), 2)
            if dir_save:
                save_frame(frame=overlay, filename=f"042_Пересечения_линий_реза_{timestamp}.jpg", dir_save=dir_save)

        return unique_intersections

    except Exception as e:
        logger.error(f"Ошибка при детектировании крестовин: {str(e)}")
        return []
