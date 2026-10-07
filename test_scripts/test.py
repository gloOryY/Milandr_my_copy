import cv2
import numpy as np
import math
from pathlib import Path
from typing import Dict, Tuple, Optional, List

from project.algorithms.crosses_algorihms import detect_crosses_on_frame
from project.station.camera.frame_capture import rotate_frame
from project.configuration.config_manager import ConfigManager
from project.application.data_work.wafer_data import WaferMap
from project.application.addition.logger import logger

PIXEL_TO_MM_COEFFICIENT = 1 / 1250.0
MM_TO_PIXEL_COEFFICIENT = 1250.0
SCALE_FACTOR: int = 4


def autocentering_split(config: 'ConfigManager',
                        frame: Optional[np.ndarray] = None,
                        min_width_offset: int = 6,
                        dir_save: Optional[Path] = None):
    """
    Выравнивание камеры относительно центра кристалла.

    Выполняет позиционирование камеры по центру кристалла с автоматической
    коррекцией отклонений. При неудаче возвращает исходные параметры.

    Args:
        config: Экземпляр класса конфигураций
        frame: Оригинальное изображение с камеры. Если не указано, выполняется захват
        min_width_offset: Минимальная длина реза линии в пикселях
        dir_save: Путь для сохранения фотографий для отладки

    Returns:
        - x_center_new: Новая координата X манипулятора после центрирования,
          или None если центрирование не требуется
        - y_center_new: Новая координата Y манипулятора после центрирования,
          или None если центрирование не требуется
        - frame: Обновленное изображение с камеры после центрирования,
          или None в случае ошибки (повернутое)
        - bool: Метка на неправильную геометрию с правильным позиционированием

    Raises:
        RobotException: Если манипулятор не может достичь целевых координат
    """

    global PIXEL_TO_MM_COEFFICIENT, MM_TO_PIXEL_COEFFICIENT

    frame_original = rotate_frame(frame, rotate_angle=270)
    frame_scaled = _compress_frame(frame_original.copy())

    corners = _find_die_location(config=config, frame=frame_scaled,
                                 min_width_offset=min_width_offset, dir_save=dir_save)

    if corners is None:
        return None

    return _crop_and_rotate_die(frame_original, corners)


def _compress_frame(frame: np.ndarray) -> np.ndarray:
    """ Сжимает изображение в SCALE_FACTOR раз. """
    original_height, original_width = frame.shape[:2]
    target_width = original_width // SCALE_FACTOR
    target_height = original_height // SCALE_FACTOR

    frame_scaled = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)

    return frame_scaled


def _check_die_location(frame: np.ndarray,
                        corners: List[Dict[str, float]],
                        max_offset_mm: float = 0.01) -> bool:
    """
    Проверяет, что все углы кристалла находятся в пределах изображения
    или с незначительным отклонением от его границ.

    Args:
        frame: Сжатое изображение с камеры
        corners: Список углов кристалла с координатами x, y
        max_offset_mm: Максимально допустимое отклонение в мм

    Returns:
        bool: True если найден целый кристалл и все его углы в пределах изображения,
              иначе False
    """
    height, width = frame.shape[:2]
    max_offset_px = max_offset_mm / PIXEL_TO_MM_COEFFICIENT

    def is_corner_outside(corner):
        x, y = corner["x"], corner["y"]

        if 0 <= x <= width and 0 <= y <= height:
            return False

        offset_left = max(0, -x)
        offset_right = max(0, x - width)
        offset_top = max(0, -y)
        offset_bottom = max(0, y - height)

        max_offset = max(offset_left, offset_right, offset_top, offset_bottom)

        if max_offset > max_offset_px:
            return True
        return False

    any_corner_badly_outside = any(is_corner_outside(corner) for corner in corners)
    return not any_corner_badly_outside


def _find_die_location(config: 'ConfigManager',
                       frame: np.ndarray,
                       min_width_offset: int = 6,
                       dir_save: Optional[Path] = None) -> List[Dict[str, float]] | None:
    """
    Определение координат углов кристалла.

    Args:
        config: Экземпляр класса конфигураций
        frame: Изображение с камеры
        min_width_offset: Минимальная длина реза линии в пикселях
        dir_save: Директория для сохранения фотографии для отладки

    Returns:
        List[Dict[str, float]]: Список координат углов ближайшего кристалла (реальных и предполагаемых)
        None в случае нахождения больше 4-х крестовин или при отсутствии крестовин
    """
    global PIXEL_TO_MM_COEFFICIENT, MM_TO_PIXEL_COEFFICIENT

    crosses_tuples = detect_crosses_on_frame(
        frame=frame,
        min_width=min_width_offset,
        dir_save=dir_save
    )
    crosses = [{"x": point[0], "y": point[1]} for point in crosses_tuples]

    if len(crosses) == 4:
        # Для 4 точек - все углы кристалла найдены
        return _sort_corners(crosses)

    elif len(crosses) == 3:
        # Для 3 точек - восстанавливаем четвертый угол
        longest_line = _find_longest_line(crosses)
        midpoint = _find_midpoint(longest_line)

        return _reconstruct_fourth_corner(crosses, longest_line, midpoint)

    elif len(crosses) == 2:
        line = (crosses[0], crosses[1])
        if not _is_diagonal_line(line, config):
            direction = _determine_perpendicular_direction(line, frame)
            return _reconstruct_corners_from_side(line, direction, config)
        else:
            return _reconstruct_corners_from_diagonal(line, config)

    elif len(crosses) == 1:
        return _reconstruct_corners_from_one_point(config, crosses[0], frame)

    elif len(crosses) > 4:
        logger.warning("Ошибка центровки камеры относительно кристаллов: "
                       "В кадр с камеры входит больше одного кристалла")
        return None

    else:
        logger.warning(("Ошибка центровки камеры относительно кристаллов: "
                        "Не найдены крестовины кристаллов, на которые можно опираться"))
        return None


def _sort_corners(corners: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Сортировка углов кристалла по порядку:
    верхний-левый, верхний-правый, нижний-правый, нижний-левый.
    """
    center_x = sum(c["x"] for c in corners) / len(corners)
    center_y = sum(c["y"] for c in corners) / len(corners)

    def get_angle(corner):
        return math.atan2(corner["y"] - center_y, corner["x"] - center_x)

    sorted_corners = sorted(corners, key=get_angle)
    for i, corner in enumerate(sorted_corners):
        angle = get_angle(corner)
        if -2.8 < angle < -1.8:  # Приблизительно для верхнего-левого угла
            sorted_corners = sorted_corners[i:] + sorted_corners[:i]
            break

    return sorted_corners


def _reconstruct_fourth_corner(three_corners: List[Dict[str, float]],
                               longest_line: Tuple[Dict[str, float], Dict[str, float]],
                               midpoint: Dict[str, float]
                               ) -> List[Dict[str, float]]:
    """
    Восстановление четвертого угла по трем известным.

    Args:
        three_corners: Три известных угла
        longest_line: Самая длинная линия (диагональ)
        midpoint: Середина диагонали

    Returns:
        List[Dict[str, float]]: Все четыре угла кристалла в отсортированном порядке
    """
    point1, point2 = longest_line

    # Находим третий угол (не входящий в диагональ)
    third_point = None
    for corner in three_corners:
        if corner != point1 and corner != point2:
            third_point = corner
            break

    if third_point:
        # Четвертый угол симметричен третьему относительно центра
        fourth_point = {
            "x": 2 * midpoint["x"] - third_point["x"],
            "y": 2 * midpoint["y"] - third_point["y"]
        }

        # Возвращаем все 4 угла в отсортированном порядке
        all_corners = [point1, point2, third_point, fourth_point]
        return _sort_corners(all_corners)

    return three_corners


def _reconstruct_corners_from_side(line: Tuple[Dict[str, float], Dict[str, float]],
                                   direction: str,
                                   config: 'ConfigManager'
                                   ) -> List[Dict[str, float]]:
    """
    Восстановление четырех углов кристалла по известной стороне.

    Args:
        line: Кортеж из двух точек (сторона кристалла)
        direction: Направление перпендикуляра ("up", "down", "right", "left")
        config: Экземпляр класса конфигураций

    Returns:
        List[Dict[str, float]]: Четыре угла кристалла в отсортированном порядке
    """
    global MM_TO_PIXEL_COEFFICIENT

    point1, point2 = line

    dx = point2["x"] - point1["x"]
    dy = point2["y"] - point1["y"]
    length = math.hypot(dx, dy)

    ux = dx / length
    uy = dy / length

    px = -uy
    py = ux

    if direction in ("right", "left"):
        perp_length = config.wafer_params["x_distance"] * MM_TO_PIXEL_COEFFICIENT
    else:
        perp_length = config.wafer_params["y_distance"] * MM_TO_PIXEL_COEFFICIENT

    if direction in ("left", "down"):
        px = -px
        py = -py

    # Вектор смещения для построения противоположной стороны
    vx = px * perp_length
    vy = py * perp_length

    corners = [
        {"x": point1["x"] + vx, "y": point1["y"] + vy},
        {"x": point2["x"] + vx, "y": point2["y"] + vy},
        point1,
        point2
    ]

    return _sort_corners(corners)


def _reconstruct_corners_from_diagonal(line: Tuple[Dict[str, float], Dict[str, float]],
                                       config: 'ConfigManager') -> List[Dict[str, float]]:
    """
    Восстановление углов кристалла по диагонали.

    Используется построение прямоугольного треугольника по трем сторонам.
    Учитывается книжная ориентация кристалла.

    Args:
        line: Диагональ кристалла (две точки)
        config: Экземпляр класса конфигураций

    Returns:
        List[Dict[str, float]]: Четыре угла кристалла в отсортированном порядке
    """
    global MM_TO_PIXEL_COEFFICIENT

    p1, p2 = line

    a = config.wafer_params["x_distance"] * MM_TO_PIXEL_COEFFICIENT  # ширина (меньшая)
    b = config.wafer_params["y_distance"] * MM_TO_PIXEL_COEFFICIENT  # высота (большая)

    # Вектор диагонали
    dx = p2["x"] - p1["x"]
    dy = p2["y"] - p1["y"]
    c = math.sqrt(dx ** 2 + dy ** 2)

    # Нормализованный вектор диагонали
    dx_norm = dx / c
    dy_norm = dy / c

    # Вектор перпендикуляра
    perp_x = -dy_norm
    perp_y = dx_norm

    # Высота прямоугольного треугольника
    h = a * b / c

    # Для первого треугольника: к p1 прилегает a, к p2 прилегает b
    t1 = a ** 2 / (a ** 2 + b ** 2)
    foot1_x = p1["x"] + dx * t1
    foot1_y = p1["y"] + dy * t1

    corner1_up = {
        "x": foot1_x + perp_x * h,
        "y": foot1_y + perp_y * h
    }

    corner1_down = {
        "x": foot1_x - perp_x * h,
        "y": foot1_y - perp_y * h
    }

    # Для второго треугольника: к p1 прилегает b, к p2 прилегает a
    t2 = b ** 2 / (a ** 2 + b ** 2)
    foot2_x = p1["x"] + dx * t2
    foot2_y = p1["y"] + dy * t2

    corner2_up = {
        "x": foot2_x + perp_x * h,
        "y": foot2_y + perp_y * h
    }

    corner2_down = {
        "x": foot2_x - perp_x * h,
        "y": foot2_y - perp_y * h
    }

    # Проверяем первый вариант: corner1_up и corner2_down
    corners_v1 = [p1, p2, corner1_up, corner2_down]
    sorted_v1 = _sort_corners(corners_v1)

    # Вычисляем размеры прямоугольника для первого варианта
    width_v1 = abs(sorted_v1[1]["x"] - sorted_v1[0]["x"])  # правый верхний - левый верхний
    height_v1 = abs(sorted_v1[2]["y"] - sorted_v1[1]["y"])  # правый нижний - правый верхний

    error_v1 = abs(width_v1 - a) + abs(height_v1 - b)

    # Проверяем второй вариант: corner1_down и corner2_up
    corners_v2 = [p1, p2, corner1_down, corner2_up]
    sorted_v2 = _sort_corners(corners_v2)

    # Вычисляем размеры прямоугольника для второго варианта
    width_v2 = abs(sorted_v2[1]["x"] - sorted_v2[0]["x"])
    height_v2 = abs(sorted_v2[2]["y"] - sorted_v2[1]["y"])

    error_v2 = abs(width_v2 - a) + abs(height_v2 - b)

    # Выбираем вариант с меньшей ошибкой (должен быть книжный формат)
    if error_v1 < error_v2:
        return sorted_v1
    else:
        return sorted_v2


def _reconstruct_corners_from_one_point(config: 'ConfigManager',
                                        point_angle: Dict[str, float],
                                        frame: np.ndarray) -> List[Dict[str, float]]:
    """
    Восстановление четырех углов кристалла по одной найденной крестовине.

    Args:
        config: Экземпляр класса конфигураций
        point_angle: Координаты единственного найденного угла кристалла
        frame: Изображение с камеры

    Returns:
        List[Dict[str, float]]: Четыре угла кристалла в отсортированном порядке
    """
    global MM_TO_PIXEL_COEFFICIENT

    height, width = frame.shape[:2]
    img_center_x = width // 2
    img_center_y = height // 2

    rotation_angle = WaferMap.get_instance().orientation.rotation_angle
    if rotation_angle is None:
        rotation_angle = 0

    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)

    # Половины размеров кристалла В ПИКСЕЛЯХ (а не в мм!)
    half_width_px = (config.wafer_params["x_distance"] / 2) * MM_TO_PIXEL_COEFFICIENT
    half_height_px = (config.wafer_params["y_distance"] / 2) * MM_TO_PIXEL_COEFFICIENT

    # Определяем, какой угол найден, и соответствующий вектор от угла к центру (В ПИКСЕЛЯХ)
    if point_angle["x"] > img_center_x and point_angle["y"] > img_center_y:
        base_offset_x = -half_width_px
        base_offset_y = -half_height_px
    elif point_angle["x"] < img_center_x and point_angle["y"] > img_center_y:
        base_offset_x = half_width_px
        base_offset_y = -half_height_px
    elif point_angle["x"] > img_center_x and point_angle["y"] < img_center_y:
        base_offset_x = -half_width_px
        base_offset_y = half_height_px
    else:
        base_offset_x = half_width_px
        base_offset_y = half_height_px

    # Поворачиваем вектор от угла к центру
    rotated_center_offset_x = base_offset_x * cos_a - base_offset_y * sin_a
    rotated_center_offset_y = base_offset_x * sin_a + base_offset_y * cos_a

    # Вычисляем центр кристалла (уже в пикселях, т.к. base_offset в пикселях)
    center_x = point_angle["x"] + rotated_center_offset_x
    center_y = point_angle["y"] + rotated_center_offset_y

    # Все четыре вектора от центра к углам (В ПИКСЕЛЯХ)
    corner_offsets_px = [
        (-half_width_px, -half_height_px),  # левый верхний
        (half_width_px, -half_height_px),  # правый верхний
        (half_width_px, half_height_px),  # правый нижний
        (-half_width_px, half_height_px)  # левый нижний
    ]

    # Поворачиваем и получаем все четыре угла
    corners = []
    for offset_x, offset_y in corner_offsets_px:
        # Поворачиваем вектор
        rotated_x = offset_x * cos_a - offset_y * sin_a
        rotated_y = offset_x * sin_a + offset_y * cos_a

        corner_x = center_x + rotated_x
        corner_y = center_y + rotated_y

        corners.append({"x": corner_x, "y": corner_y})

    return _sort_corners(corners)


def _find_longest_line(points: List[Dict[str, int]]
                       ) -> Optional[Tuple[Dict[str, int], Dict[str, int]]]:
    """
    Нахождение самой длинной прямой (пары точек с максимальным расстоянием)
    среди всех возможных пар.
    """
    longest_line = None
    max_distance = -1

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            point1 = points[i]
            point2 = points[j]

            distance = _calculate_distance(point1, point2)
            if distance > max_distance:
                max_distance = distance
                longest_line = (point1, point2)

    return longest_line


def _find_midpoint(line: Tuple[Dict[str, float], Dict[str, float]]) -> Dict[str, float]:
    """ Нахождение середины прямой, заданной двумя точками. """
    point1, point2 = line
    mid_x = (point1["x"] + point2["x"]) / 2
    mid_y = (point1["y"] + point2["y"]) / 2

    return {"x": mid_x, "y": mid_y}


def _is_diagonal_line(line: Tuple[Dict[str, float], Dict[str, float]],
                      config: 'ConfigManager') -> bool:
    """ Определяет, является ли линия диагональю или стороной прямоугольника. """
    global MM_TO_PIXEL_COEFFICIENT

    point1, point2 = line
    distance = _calculate_distance(point1, point2)

    return (distance > 1.1 * MM_TO_PIXEL_COEFFICIENT *
            max(config.wafer_params["x_distance"], config.wafer_params["y_distance"]))


def _determine_perpendicular_direction(
        line: Tuple[Dict[str, float], Dict[str, float]],
        frame: np.ndarray) -> str:
    """
    Определение направления перпендикуляра ВГЛУБЬ кристалла.

    Если видим сторону кристалла, значит кристалл находится
    с противоположной стороны от этой линии.
    """
    orientation = _determine_line_orientation(line)
    midpoint = _find_midpoint(line)

    height, width = frame.shape[:2]
    center_x = width // 2
    center_y = height // 2

    if orientation == "horizontal":
        # Горизонтальная сторона (верхняя или нижняя граница кристалла)
        # Если линия внизу изображения - это верхняя сторона, кристалл сверху
        # Если линия вверху изображения - это нижняя сторона, кристалл снизу
        if midpoint["y"] > center_y:
            return "up"  # Линия внизу → кристалл сверху → строим вверх
        else:
            return "down"  # Линия вверху → кристалл снизу → строим вниз
    else:  # vertical
        # Вертикальная сторона (левая или правая граница кристалла)
        # Если линия справа - это левая сторона, кристалл слева
        # Если линия слева - это правая сторона, кристалл справа
        if midpoint["x"] > center_x:
            return "left"  # Линия справа → кристалл слева → строим влево
        else:
            return "right"  # Линия слева → кристалл справа → строим вправо


def _determine_line_orientation(line: Tuple[Dict[str, float], Dict[str, float]]) -> str:
    """ Определение ориентации прямой через соотношение сторон. """
    point1, point2 = line
    dx = abs(point2["x"] - point1["x"])
    dy = abs(point2["y"] - point1["y"])

    if dx > dy:
        return "horizontal"
    else:
        return "vertical"


def _calculate_distance(point1: Dict[str, float], point2: Dict[str, float]) -> float:
    """ Вычисление расстояния между двумя точками. """
    dx = point2["x"] - point1["x"]
    dy = point2["y"] - point1["y"]
    return math.sqrt(dx ** 2 + dy ** 2)


def _calculate_center_from_corners(corners: List[Dict[str, float]]) -> Dict[str, float]:
    """
    Вычисление центра кристалла по его углам.
    """
    if len(corners) == 4:
        # Центр - пересечение диагоналей
        center_x = (corners[0]["x"] + corners[2]["x"]) / 2
        center_y = (corners[0]["y"] + corners[2]["y"]) / 2
    else:
        # Среднее арифметическое всех углов
        center_x = sum(c["x"] for c in corners) / len(corners)
        center_y = sum(c["y"] for c in corners) / len(corners)

    return {"x": center_x, "y": center_y}


def _determine_point_offset_direction(point: Dict[str, float], frame: np.ndarray) -> Tuple[float, float]:
    """
    Определяет координаты смещения центра изображения от центра искомого кристалла.

    Args:
        point: Координаты точки в формате {"x": x1, "y": y1}
        frame: Изображение с камеры

    Returns:
        Tuple[float, float]: Координаты перемещения (dx, dy)
    """
    height, width = frame.shape[:2]
    center_x = width // 2
    center_y = height // 2

    d_x = center_x - point["x"]
    d_y = center_y - point["y"]

    return d_x, d_y


def _validate_corners_geometry(corners: List[Dict[str, float]],
                               config: 'ConfigManager',
                               tolerance_percent: float = 1.0) -> bool:
    """
    Проверяет корректность геометрии найденных углов кристалла через площадь.

    Args:
        corners: Список из 4 углов в отсортированном порядке
        config: Экземпляр класса конфигураций
        tolerance_percent: Допустимое отклонение площади в процентах

    Returns:
        bool: True если площадь соответствует ожидаемой, иначе False
    """
    global MM_TO_PIXEL_COEFFICIENT

    if len(corners) != 4:
        return False

    # Теоретическая площадь в пикселях
    expected_width_px = config.wafer_params["x_distance"] * MM_TO_PIXEL_COEFFICIENT
    expected_height_px = config.wafer_params["y_distance"] * MM_TO_PIXEL_COEFFICIENT
    expected_area = expected_width_px * expected_height_px

    # Фактическая площадь через формулу Гаусса
    actual_area = 0.5 * abs(
        sum(corners[i]["x"] * corners[(i + 1) % 4]["y"] -
            corners[(i + 1) % 4]["x"] * corners[i]["y"]
            for i in range(4))
    )

    # Отклонение в процентах
    area_deviation = abs(actual_area - expected_area) / expected_area * 100

    logger.debug(f"Проверка площади - Фактическая: {actual_area:.2f}px², "
                 f"Ожидаемая: {expected_area:.2f}px², "
                 f"Отклонение: {area_deviation:.1f}%")

    return area_deviation <= tolerance_percent


def _crop_and_rotate_die(frame_original: np.ndarray,
                         corners_scaled: List[Dict[str, float]]) -> np.ndarray:
    """
    Обрезка изображения по прямоугольнику кристалла.

    Всё, что вне прямоугольника, закрашивается чёрным.
    Изображение обрезается максимально близко к прямоугольнику.

    Args:
        frame_original: Оригинальное изображение
        corners_scaled: Координаты углов кристалла в масштабированном изображении

    Returns:
        np.ndarray: Изображение с закрашенным фоном и обрезанное по прямоугольнику
    """
    global SCALE_FACTOR

    original_height, original_width = frame_original.shape[:2]
    corners_original = []
    for corner in corners_scaled:
        corners_original.append({
            "x": corner["x"] * SCALE_FACTOR,
            "y": corner["y"] * SCALE_FACTOR
        })

    x_coords = [c["x"] for c in corners_original]
    y_coords = [c["y"] for c in corners_original]

    x_min = int(min(x_coords))
    x_max = int(max(x_coords))
    y_min = int(min(y_coords))
    y_max = int(max(y_coords))

    mask = np.zeros((original_height, original_width), dtype=np.uint8)
    contour = np.array([[c["x"], c["y"]] for c in corners_original], dtype=np.int32)
    cv2.fillPoly(mask, [contour], 255)

    result = frame_original.copy()
    result[mask == 0] = 0

    # Обрезаем изображение максимально близко к прямоугольнику
    # Добавляем небольшой отступ в 1 пиксель, чтобы точно не обрезать прямоугольник
    crop_x_min = max(0, x_min - 1)
    crop_x_max = min(original_width, x_max + 1)
    crop_y_min = max(0, y_min - 1)
    crop_y_max = min(original_height, y_max + 1)

    cropped_result = result[crop_y_min:crop_y_max, crop_x_min:crop_x_max].copy()

    return cropped_result


if __name__ == "__main__":
    config = ConfigManager(None)

    input_folder = Path(r"C:\Users\user\Desktop\Tyuehn")    # Папка с исходными изображениями
    output_folder = Path(r"C:\Users\user\Desktop\Cropped_1")  # Папка для сохранения результатов

    # Создаем папку для выходных данных
    output_folder.mkdir(parents=True, exist_ok=True)

    # Получаем все изображения
    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
    image_files = []
    for ext in image_extensions:
        image_files.extend(input_folder.glob(ext))

    print(f"Найдено {len(image_files)} изображений для обработки")

    # Обрабатываем каждое изображение
    for i, image_path in enumerate(image_files, 1):
        print(f"\nОбработка {i}/{len(image_files)}: {image_path.name}")

        # Загружаем изображение
        frame = cv2.imread(str(image_path))
        if frame is None:
            print(f"  Ошибка: Не удалось загрузить изображение {image_path}")
            continue

        # Обрезаем кристалл
        cropped_frame = autocentering_split(
            config=config,
            frame=frame,
            dir_save=output_folder
        )

        if cropped_frame is not None:
            output_path = output_folder / f"cropped_{image_path.name}"
            cv2.imwrite(str(output_path), cropped_frame)
            print(f"  Успешно: Обрезанное изображение сохранено как {output_path.name}")
        else:
            print(f"  Ошибка: Не удалось обрезать")
