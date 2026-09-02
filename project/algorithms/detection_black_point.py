import cv2
import torch
import numpy as np
import time
from math import ceil
from typing import List, Dict, Any, Tuple, Optional

import project.algorithms.neural_network.networks_vault as nv
from project.application.addition.logger import logger


def find_black_point_defects(frame_original: np.ndarray,
                             frame_filtered: np.ndarray) -> Tuple[int, List[Dict[str, Any]], Optional[np.ndarray]]:
    """
    Нахождение дефектов кристалла с использованием всех доступных моделей дефектов.

    Args:
        frame_original: Оригинальное изображение с камеры для анализа (BGR, numpy array)
        frame_filtered: Изображение с уже наложенными фильтрами других дефектов,
                       на которое будут добавлены прямоугольники новых дефектов (BGR, numpy array)

    Returns:
        tuple: (total_defect_count, defects_info, frame_filtered)
            - total_defect_count (int): Суммарное количество найденных дефектов
            - defects_info (List[Dict]): Список словарей с информацией о каждом типе дефектов:
                * 'key': английское название модели
                * 'name': русское название дефекта
                * 'color': цвет контура (RGB)
                * 'count': количество найденных дефектов данного типа
            - frame_filtered (np.ndarray or None): Изображение с наложенными контурами
              всех найденных дефектов или None, если дефекты не найдены
    """
    if (frame_original is None or frame_original.size == 0 or
            frame_filtered is None or frame_filtered.size == 0):
        return 0, [], None

    try:
        total_start = time.time()

        defects_info = []
        defect_model = nv.get_defect_model_by_type('black_point')
        model_key = defect_model.get('defect_type', 'unknown')
        model_name = defect_model.get('name', 'Unknown')
        model_color = defect_model.get('color', [255, 0, 0])

        defect_count, processed_frame = _process_black_point_frame(
            frame_original=frame_original.copy(),
            frame_filtered=frame_filtered.copy(),
            model_dict=defect_model
        )

        if defect_count > 0:
            defects_info.append({
                'key': model_key,
                'name': model_name,
                'color': model_color,
                'count': defect_count
            })

        total_elapsed = time.time() - total_start
        logger.info(f"Полное время анализа изображения: {total_elapsed:.2f}с")

        if defect_count > 0:
            return defect_count, defects_info, (processed_frame if processed_frame is not None else frame_filtered)
        else:
            return 0, [], frame_filtered

    except Exception as e:
        logger.error(f"Ошибка при анализе кристалла: {e}")
        return 0, [], frame_filtered


def _process_black_point_frame(frame_original: np.ndarray,
                               frame_filtered: np.ndarray,
                               model_dict: Dict[str, Any],
                               contour_thickness: int = 2) -> Tuple[int, Optional[np.ndarray]]:
    """
    Анализ изображения через нейросеть для поиска дефектов пассификации кристалла.
    Оптимизированная версия с пакетной обработкой, однократным преобразованием RGB
    и GPU-постобработкой масок.

    Args:
        frame_original (np.ndarray): Оригинальное изображение с камеры (BGR)
        frame_filtered (np.ndarray): Изображение, на которе необходимо накладывать контура
        model_dict (dict): Словарь с данными нейронной модели (см. find_defects)
        contour_thickness (int): Толщина контура для отрисовки

    Returns:
        tuple: (defect_count, frame)
    """
    model = model_dict['model']
    conf_threshold = float(model_dict["conf"])

    h, w = frame_original.shape[:2]
    tile_w, tile_h = 1280, 720
    min_overlap = 0.1  # 10% перекрытия

    # Фаза 1: генерация координат тайлов и нарезка (с однократной сменой цветового пространства)
    tile_coords = _get_tile_coords((h, w), (tile_w, tile_h), min_overlap)
    frame_rgb = cv2.cvtColor(frame_original, cv2.COLOR_BGR2RGB)
    tile_imgs_rgb = [frame_rgb[y:y + tile_h, x:x + tile_w] for (x, y) in tile_coords]

    if not tile_imgs_rgb:
        return 0, None

    # Фаза 2: пакетный инференс
    device = next(model.parameters()).device
    use_half = device.type != 'cpu'

    t1 = time.time()

    results = model.predict(
        source=tile_imgs_rgb,
        device=device,
        conf=conf_threshold,
        iou=0,
        imgsz=1280,
        half=use_half,
        verbose=False,
        task="segment",
        stream=False
    )

    t_infer = time.time() - t1
    logger.debug(f"Инференс: {t_infer:.3f}с")

    # Фаза 3: обработка масок (GPU) + поиск контуров
    all_contours = []
    defect_count = 0

    for result, (x_off, y_off) in zip(results, tile_coords):
        if result.masks is None:
            continue
        # Тензор масок (N, H_out, W_out) на устройстве вывода
        masks_tensor = result.masks.data  # может быть на GPU или CPU в зависимости от predict
        # Переносим на GPU, если модель на GPU, чтобы выполнять interpolate
        if device.type != 'cpu':
            masks_tensor = masks_tensor.to(device)

        # Масштабирование до размера тайла на GPU
        masks_resized = torch.nn.functional.interpolate(
            masks_tensor.unsqueeze(1),  # (N, 1, H, W)
            size=(tile_h, tile_w),
            mode='nearest'
        ).squeeze(1)  # (N, tile_h, tile_w)
        masks_binary = (masks_resized > 0.5).byte()
        masks_np = masks_binary.cpu().numpy()  # Перенос на CPU для OpenCV

        defect_count += len(masks_np)

        for mask in masks_np:
            # Преобразуем в формат uint8 (0 и 255)
            mask_uint8 = mask * 255
            contours, _ = cv2.findContours(
                mask_uint8,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )
            # Смещение контуров в глобальные координаты
            for cnt in contours:
                if len(cnt) >= 3:
                    cnt[:, :, 0] += x_off
                    cnt[:, :, 1] += y_off
                    all_contours.append(cnt)

    if all_contours:
        color_outline = (model_dict["color"][2], model_dict["color"][1], model_dict["color"][0])
        cv2.drawContours(frame_filtered, all_contours, -1, color_outline, contour_thickness)
        return defect_count, frame_filtered
    else:
        return 0, None


def _get_tile_coords(frame_shape: Tuple[int, int],
                     tile_size: Tuple[int, int] = (1280, 720),
                     min_overlap: float = 0.1) -> List[Tuple[int, int]]:
    """
    Возвращает список координат (x, y) левого верхнего угла для тайлов,
    покрывающих изображение с заданным перекрытием.
    """
    h, w = frame_shape
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


def mock_find_black_point_defects() -> Tuple[int, List[Dict[str, Any]], Optional[np.ndarray]]:
    """
    Мок-функция для тестирования: 50% без дефектов, 50% со случайными дефектами.
    """
    import random

    # Получаем список доступных типов дефектов
    defect_types = []
    for defect_model in nv.models['defects']:
        if defect_model.get('version_id') == 1:
            defect_types.append({
                'key': defect_model.get('defect_type', 'unknown'),
                'name': defect_model.get('name', 'Unknown'),
                'color': defect_model.get('color', [0, 0, 255])
            })

    if not defect_types:
        defect_types = [
            {'key': 'scratch', 'name': 'Царапина', 'color': [255, 0, 0]},
            {'key': 'chip', 'name': 'Скол', 'color': [0, 255, 0]},
            {'key': 'contamination', 'name': 'Загрязнение', 'color': [0, 0, 255]},
            {'key': 'crack', 'name': 'Трещина', 'color': [255, 255, 0]},
        ]

    if random.random() < 0.5:
        return 0, [], None

    num_types = random.randint(1, min(3, len(defect_types)))
    selected_types = random.sample(defect_types, num_types)

    defects_info = []
    total_count = 0
    for defect in selected_types:
        count = random.randint(1, 4)
        total_count += count
        defects_info.append({
            'key': defect['key'],
            'name': defect['name'],
            'color': defect['color'],
            'count': count
        })

    return total_count, defects_info, None
