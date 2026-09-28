import cv2
import torch
import numpy as np
import time
from typing import Dict, Tuple, Optional, Any, List

import project.algorithms.neural_network.networks_vault as nv
from project.application.addition.logger import logger


# ═══════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ ПО УМОЛЧАНИЮ
# ═══════════════════════════════════════════════════════════════════════════


class _Config:
    """Закрытая конфигурация параметров детекции."""

    # ─── ПРЕДОБРАБОТКА ────────────────────────────────────────────────
    BLUR_FILTER_ENABLED = False
    BLUR_TYPE = "gaussian"  # gaussian | median | bilateral
    BLUR_KERNEL_SIZE = 11
    GAUSSIAN_SIGMA = 2.5

    PREPROCESS_ENABLE = True
    PRE_BRIGHTNESS = 1.0
    PRE_CONTRAST = 6.0
    PRE_RED_GAIN = 1.2
    PRE_GREEN_GAIN = 1.4
    PRE_BLUE_GAIN = 0.0
    PRE_SATURATION = 6.0

    # ─── ДЕТЕКЦИЯ КАЙМЫ ──────────────────────────────────────────────
    SEARCH_ZONE_WIDTH = 130

    LIME_HSV_LOWER = np.array([25, 50, 60], np.uint8)
    LIME_HSV_UPPER = np.array([85, 255, 255], np.uint8)

    # Жёлто-зелёный насыщенный (H=22..42, S=120..160, V=180..235)
    LIME_HSV_LOWER2 = np.array([22, 120, 180], np.uint8)
    LIME_HSV_UPPER2 = np.array([42, 160, 235], np.uint8)

    # Жёлто-зелёный слабонасыщенный (H=21..42, S=85..125, V=130..240)
    LIME_HSV_LOWER3 = np.array([21, 85, 130], np.uint8)
    LIME_HSV_UPPER3 = np.array([42, 125, 240], np.uint8)

    # Коричнево-жёлтый (охра) (H=6..22, S=100..165, V=130..255)
    LIME_HSV_LOWER4 = np.array([6, 100, 130], np.uint8)
    LIME_HSV_UPPER4 = np.array([22, 165, 255], np.uint8)

    LIME_BGR_MIN_G = 70
    LIME_BGR_MIN_EXCESS = 20

    LIME_MIN_TOTAL_PIXELS = 3000
    LIME_CLOSE_KERNEL = 11
    LIME_CLOSE_ITER = 2
    LIME_OPEN_KERNEL = 5

    LIME_DIR_CLOSE_LEN = 31
    LIME_DIR_CLOSE_THICK = 3

    # ─── НОРМАЛИЗАЦИЯ ТОЛЩИНЫ ────────────────────────────────────────
    INNER_BAND_WIDTH = 12
    REFERENCE_SMOOTH_WINDOW = 401

    # ─── ПОСТРОЕНИЕ ЛИНИЙ ────────────────────────────────────────────
    SIDE_SCAN_WIDTH = 130
    ON_MASK_GAP_CLOSE = 25
    CORNER_IGNORE_MARGIN = 200

    MIN_DEFECT_SEGMENT_LENGTH_FALLBACK = 20
    MIN_DEFECT_RELATIVE = 0.005
    MAX_LINE_DEVIATION = 30

    # ─── ДЕТЕКЦИЯ ТЁМНЫХ ПЯТЕН НА КАЙМЕ ─────────────────────────────
    DARK_SPOT_V_MAX = 70
    DARK_SPOT_MIN_PIXELS = 15
    DARK_SPOT_DILATE = 3
    DARK_SPOT_MIN_OVERLAP = 5

    # ─── ВИЗУАЛИЗАЦИЯ ────────────────────────────────────────────────
    DEFECT_BOX_THICKNESS = 3
    DEFECT_LABEL_SCALE = 0.7
    DEFECT_PADDING = 8  # Дополнительный отступ вокруг bbox дефекта (px)
    DEFECT_MIN_SIZE = 24  # Минимальный размер стороны рамки (px)
    DEFECT_BOX_EXTRA_WIDTH = 20  # Дополнительная ширина перпендикулярно кайме


# ═══════════════════════════════════════════════════════════════════════════
# ЗАКРЫТЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════


# Размер вырезаемого патча (ширина x высота в пикселях)
# Итоговое изображение вертикальное: короткая сторона = CROP_W, длинная = CROP_H
CROP_W = 400  # ширина патча
CROP_H = 600  # высота патча


def _get_defect_center(defect: Dict[str, Any], img_shape: Tuple[int, int]) -> Tuple[int, int]:
    """
    Вычисляет центр дефекта в координатах оригинального изображения.

    Для линейных дефектов (разрыв каймы) центр берётся по середине сегмента
    и по средней позиции линии.
    Для тёмных пятен (dark_spot) используется центр bbox.
    """
    if defect.get("type") == "dark_spot":
        cx = (defect["x1"] + defect["x2"]) // 2
        cy = (defect["y1"] + defect["y2"]) // 2
        return cx, cy

    axis = defect["axis"]
    start = defect["start"]
    end = defect["end"]
    line_min = defect["line_min"]
    line_max = defect["line_max"]
    line_center = (line_min + line_max) // 2
    seg_center = (start + end) // 2

    if axis == "vertical":
        # Левая/правая сторона: X — позиция линии, Y — вдоль кромки
        return line_center, seg_center
    else:
        # Верхняя/нижняя: X — вдоль кромки, Y — позиция линии
        return seg_center, line_center


def _rotation_for_side(side: str) -> int:
    """
    Возвращает угол поворота (в градусах) для нормализации ориентации патча.

    Правило: итоговое изображение всегда вертикальное (CROP_W < CROP_H),
    дефект у правой стороны — эталон (0°).

      right  →   0°  (оставляем как есть)
      left   → 180°  (переворачиваем)
      top    →  90°  (поворот по часовой)
      bottom → -90°  (поворот против часовой, т.е. 270°)
    """
    return {"right": 0, "left": 180, "top": 90, "bottom": -90}.get(side, 0)


def _rotate_image(img: np.ndarray, angle: int) -> np.ndarray:
    """Поворачивает изображение на заданный угол (кратный 90°)."""
    if angle == 0:
        return img
    if angle == 90 or angle == -270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180 or angle == -180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == -90 or angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _ensure_odd(k: int) -> int:
    """Гарантирует нечётность числа."""
    return max(1, k | 1)


def _ell_kernel(k: int) -> np.ndarray:
    """Создаёт эллиптическое ядро размера k."""
    k = _ensure_odd(k)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def _rgb_to_bgr(rgb: List[int]) -> Tuple[int, int, int]:
    """Конвертирует RGB в BGR."""
    return (int(rgb[2]), int(rgb[1]), int(rgb[0]))


def _apply_blur_filter(img: np.ndarray) -> np.ndarray:
    """Применяет фильтр размытия согласно конфигурации."""
    if not _Config.BLUR_FILTER_ENABLED:
        return img

    if _Config.BLUR_TYPE == "gaussian":
        kernel = _ensure_odd(_Config.BLUR_KERNEL_SIZE)
        sigma = _Config.GAUSSIAN_SIGMA if _Config.GAUSSIAN_SIGMA > 0 else kernel / 6.0
        return cv2.GaussianBlur(img, (kernel, kernel), sigma)

    if _Config.BLUR_TYPE == "median":
        return cv2.medianBlur(img, _ensure_odd(_Config.BLUR_KERNEL_SIZE))

    kernel = _ensure_odd(_Config.BLUR_KERNEL_SIZE)
    return cv2.GaussianBlur(img, (kernel, kernel), 0)


# ── Кэш LUT для предобработки (перестраивается при изменении конфига) ──
_LUT_CACHE: Dict[str, Any] = {"key": None, "bgr": None, "sat": None}


def _build_preprocess_luts() -> Tuple[np.ndarray, np.ndarray]:
    """
    Собирает LUT'ы для ручной цветокоррекции (контраст+яркость+усиление каналов
    и насыщенность). Результаты кэшируются по значениям конфига.
    """
    key = (
        _Config.PRE_CONTRAST, _Config.PRE_BRIGHTNESS,
        _Config.PRE_BLUE_GAIN, _Config.PRE_GREEN_GAIN, _Config.PRE_RED_GAIN,
        _Config.PRE_SATURATION,
    )
    if _LUT_CACHE["key"] == key:
        return _LUT_CACHE["bgr"], _LUT_CACHE["sat"]

    x = np.arange(256, dtype=np.float32)
    base = (x - 127.5) * _Config.PRE_CONTRAST + 127.5 + _Config.PRE_BRIGHTNESS
    b = np.clip(base * _Config.PRE_BLUE_GAIN, 0, 255).astype(np.uint8)
    g = np.clip(base * _Config.PRE_GREEN_GAIN, 0, 255).astype(np.uint8)
    r = np.clip(base * _Config.PRE_RED_GAIN, 0, 255).astype(np.uint8)
    bgr_lut = cv2.merge([b, g, r])  # форма (1, 256, 3)

    sat_lut = np.clip(x * _Config.PRE_SATURATION, 0, 255).astype(np.uint8)

    _LUT_CACHE["key"] = key
    _LUT_CACHE["bgr"] = bgr_lut
    _LUT_CACHE["sat"] = sat_lut
    return bgr_lut, sat_lut


def _apply_manual_adjustments(img_bgr: np.ndarray) -> np.ndarray:
    """Ручная цветокоррекция изображения через LUT (эквивалентно прежней арифметике)."""
    bgr_lut, sat_lut = _build_preprocess_luts()

    # Контраст + яркость + поканальное усиление одним проходом
    img = cv2.LUT(img_bgr, bgr_lut)

    # Насыщенность через HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = cv2.LUT(hsv[:, :, 1], sat_lut)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def _build_search_zone(h: int, w: int) -> np.ndarray:
    """Создаёт поисковую зону по краям изображения."""
    zone = np.zeros((h, w), dtype=np.uint8)
    width = min(_Config.SEARCH_ZONE_WIDTH, h, w)

    zone[0:width, :] = 255
    zone[h - width:h, :] = 255
    zone[:, 0:width] = 255
    zone[:, w - width:w] = 255

    return zone


def _median_smooth_1d(values: np.ndarray, window: int) -> np.ndarray:
    """
    Медианное сглаживание массива с игнорированием NaN.
    NaN-ы интерполируются линейно, затем применяется скользящая медиана
    (через sliding_window_view одной C-векторной операцией).
    """
    n = len(values)
    if n == 0:
        return values

    known = ~np.isnan(values)
    cnt = int(known.sum())
    if cnt < 2:
        fill = float(values[known][0]) if cnt == 1 else 0.0
        return np.full(n, fill, dtype=np.float64)

    indices = np.arange(n, dtype=np.float64)
    filled = np.interp(indices, np.flatnonzero(known), values[known])

    win = _ensure_odd(window)
    half = win // 2
    pad = np.pad(filled, (half, half), mode="edge")

    # Одна векторизованная медиана по всему массиву
    windows = np.lib.stride_tricks.sliding_window_view(pad, win)
    return np.median(windows, axis=1)


def _reject_outliers(values: np.ndarray, max_deviation: float, smooth_window: int) -> np.ndarray:
    """
    Помечает как NaN точки, отклонившиеся от сглаженной опорной линии
    больше чем на max_deviation.
    """
    if np.sum(~np.isnan(values)) < 2:
        return values.copy()

    ref = _median_smooth_1d(values, smooth_window)
    out = values.copy()
    bad = ~np.isnan(out) & (np.abs(out - ref) > max_deviation)
    out[bad] = np.nan

    return out


def _prefilter_bulges(lime_mask: np.ndarray, expected_width: int) -> np.ndarray:
    """Эрозия для удаления тонких выпираний перед поиском опорной линии."""
    erode_size = max(1, expected_width // 3)

    # Горизонтальная эрозия
    k_horz = cv2.getStructuringElement(cv2.MORPH_RECT, (erode_size, 1))
    eroded_horz = cv2.erode(lime_mask, k_horz, iterations=1)

    # Вертикальная эрозия
    k_vert = cv2.getStructuringElement(cv2.MORPH_RECT, (1, erode_size))
    eroded_vert = cv2.erode(lime_mask, k_vert, iterations=1)

    return cv2.bitwise_or(eroded_horz, eroded_vert)


def _detect_lime_border(img_bgr: np.ndarray, hsv: np.ndarray, search_zone: np.ndarray) -> np.ndarray:
    """
    Детектирует белую кайму кристалла.
    Использует HSV и BGR критерии для выделения белых областей.
    """
    b = img_bgr[:, :, 0].astype(np.int16)
    g = img_bgr[:, :, 1].astype(np.int16)
    r = img_bgr[:, :, 2].astype(np.int16)

    # HSV детекция — основной зелёный диапазон
    lime_hsv = cv2.inRange(hsv, _Config.LIME_HSV_LOWER, _Config.LIME_HSV_UPPER)

    # Дополнительные диапазоны каймы
    lime_hsv2 = cv2.inRange(hsv, _Config.LIME_HSV_LOWER2, _Config.LIME_HSV_UPPER2)
    lime_hsv3 = cv2.inRange(hsv, _Config.LIME_HSV_LOWER3, _Config.LIME_HSV_UPPER3)
    lime_hsv4 = cv2.inRange(hsv, _Config.LIME_HSV_LOWER4, _Config.LIME_HSV_UPPER4)

    # BGR детекция (зелёный канал доминирует)
    lime_bgr = (
                       (g >= _Config.LIME_BGR_MIN_G) &
                       (g > r + _Config.LIME_BGR_MIN_EXCESS) &
                       (g > b + _Config.LIME_BGR_MIN_EXCESS)
               ).astype(np.uint8) * 255

    # Комбинируем все маски и ограничиваем поисковой зоной
    lime_mask = cv2.bitwise_or(lime_hsv, lime_hsv2)
    lime_mask = cv2.bitwise_or(lime_mask, lime_hsv3)
    lime_mask = cv2.bitwise_or(lime_mask, lime_hsv4)
    lime_mask = cv2.bitwise_or(lime_mask, lime_bgr)
    lime_mask = cv2.bitwise_and(lime_mask, search_zone)

    # Открытие для удаления шума
    lime_mask = cv2.morphologyEx(lime_mask, cv2.MORPH_OPEN, _ell_kernel(_Config.LIME_OPEN_KERNEL))

    # Фильтрация по размеру компонент связности (векторизованно)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(lime_mask, 8)
    if n > 1:
        areas = stats[:, cv2.CC_STAT_AREA]
        keep = np.zeros(n, dtype=bool)
        keep[1:] = areas[1:] >= _Config.LIME_MIN_TOTAL_PIXELS
        filtered = np.where(keep[labels], np.uint8(255), np.uint8(0))
    else:
        filtered = np.zeros_like(lime_mask)

    # Закрытие для заполнения пустот
    filtered = cv2.morphologyEx(
        filtered, cv2.MORPH_CLOSE,
        _ell_kernel(_Config.LIME_CLOSE_KERNEL),
        iterations=_Config.LIME_CLOSE_ITER
    )

    # Направленное закрытие для соединения разорванных участков
    thick = _ensure_odd(_Config.LIME_DIR_CLOSE_THICK)
    length = _ensure_odd(_Config.LIME_DIR_CLOSE_LEN)
    k_vert = cv2.getStructuringElement(cv2.MORPH_RECT, (thick, length))
    k_horz = cv2.getStructuringElement(cv2.MORPH_RECT, (length, thick))

    filtered = cv2.morphologyEx(filtered, cv2.MORPH_CLOSE, k_vert)
    filtered = cv2.morphologyEx(filtered, cv2.MORPH_CLOSE, k_horz)

    return filtered


def _paint_band_rows(out: np.ndarray, lime_mask: np.ndarray,
                     inner_ref: np.ndarray, band_width: int,
                     anchor_is_start: bool, w: int) -> None:
    """
    Векторизованная отрисовка полосы по строкам.
    anchor_is_start=True  → inner_ref задаёт левый край полосы (стороны right/bottom).
    anchor_is_start=False → inner_ref задаёт правый край полосы (стороны left/top).
    Поведение по выходу за границы эквивалентно прежнему: пишем только то,
    что попало в [0, w-1].
    """
    h = out.shape[0]
    a = np.round(inner_ref).astype(np.int32)
    if not anchor_is_start:
        a = a - band_width + 1

    col_off = np.arange(band_width, dtype=np.int32)
    cols = a[:, None] + col_off[None, :]  # (h, band_width)
    valid = (cols >= 0) & (cols < w)
    y_idx = np.broadcast_to(np.arange(h, dtype=np.int32)[:, None], cols.shape)

    ys = y_idx[valid]
    xs = cols[valid]
    if ys.size == 0:
        return
    out[ys, xs] = np.maximum(out[ys, xs], lime_mask[ys, xs])


def _paint_band_cols(out: np.ndarray, lime_mask: np.ndarray,
                     inner_ref: np.ndarray, band_width: int,
                     anchor_is_start: bool, h: int) -> None:
    """
    Векторизованная отрисовка полосы по столбцам.
    anchor_is_start=True  → inner_ref задаёт верхний край (bottom).
    anchor_is_start=False → inner_ref задаёт нижний край (top).
    """
    w = out.shape[1]
    a = np.round(inner_ref).astype(np.int32)
    if not anchor_is_start:
        a = a - band_width + 1

    row_off = np.arange(band_width, dtype=np.int32)
    rows = a[:, None] + row_off[None, :]  # (w, band_width)
    valid = (rows >= 0) & (rows < h)
    x_idx = np.broadcast_to(np.arange(w, dtype=np.int32)[:, None], rows.shape)

    xs = x_idx[valid]
    ys = rows[valid]
    if ys.size == 0:
        return
    out[ys, xs] = np.maximum(out[ys, xs], lime_mask[ys, xs])


def _trim_lime_uniform(lime_mask: np.ndarray) -> np.ndarray:
    """
    Удаляет внешний излишек каймы, оставляя полосу INNER_BAND_WIDTH,
    привязанную к внутренней кромке.
    """
    h, w = lime_mask.shape
    band_width = _Config.INNER_BAND_WIDTH
    scan_width = _Config.SIDE_SCAN_WIDTH
    smooth_window = _Config.REFERENCE_SMOOTH_WINDOW

    cleaned = _prefilter_bulges(lime_mask, band_width)
    out = np.zeros_like(lime_mask)

    # ── Правая сторона ──
    cs = max(0, w - scan_width)
    strip = cleaned[:, cs:w]
    inner = _find_inner_edge(strip, "row", "right", cs)
    inner_ref = _median_smooth_1d(inner, smooth_window)
    _paint_band_rows(out, lime_mask, inner_ref, band_width, anchor_is_start=True, w=w)

    # ── Левая сторона ──
    ce = min(scan_width, w)
    strip = cleaned[:, :ce]
    inner = _find_inner_edge(strip, "row", "left", 0)
    inner_ref = _median_smooth_1d(inner, smooth_window)
    _paint_band_rows(out, lime_mask, inner_ref, band_width, anchor_is_start=False, w=w)

    # ── Нижняя сторона ──
    rs = max(0, h - scan_width)
    strip = cleaned[rs:h, :]
    inner = _find_inner_edge(strip, "col", "bottom", rs)
    inner_ref = _median_smooth_1d(inner, smooth_window)
    _paint_band_cols(out, lime_mask, inner_ref, band_width, anchor_is_start=True, h=h)

    # ── Верхняя сторона ──
    re = min(scan_width, h)
    strip = cleaned[:re, :]
    inner = _find_inner_edge(strip, "col", "top", 0)
    inner_ref = _median_smooth_1d(inner, smooth_window)
    _paint_band_cols(out, lime_mask, inner_ref, band_width, anchor_is_start=False, h=h)

    return out


def _find_inner_edge(strip: np.ndarray, axis: str, side: str, offset: int) -> np.ndarray:
    """
    Находит координату внутренней кромки каймы для каждой строки/столбца.
    Внутренняя кромка — та, что смотрит внутрь снимка.
    Векторизованная реализация через argmax по булевой маске.
    """
    mask = strip > 0
    inner_is_min = side in ("right", "bottom")  # left/top → нужен max-индекс (последний True)

    if axis == "row":
        has_white = mask.any(axis=1)
        if inner_is_min:
            idx = mask.argmax(axis=1)
        else:
            w = mask.shape[1]
            idx = (w - 1) - mask[:, ::-1].argmax(axis=1)
        out = idx.astype(np.float64) + offset
        out[~has_white] = np.nan
        return out

    # axis == "col"
    has_white = mask.any(axis=0)
    if inner_is_min:
        idx = mask.argmax(axis=0)
    else:
        hh = mask.shape[0]
        idx = (hh - 1) - mask[::-1, :].argmax(axis=0)
    out = idx.astype(np.float64) + offset
    out[~has_white] = np.nan
    return out


def _build_side_line(lime_mask: np.ndarray, side: str, h: int, w: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Строит опорную линию по внутренней кромке каймы для указанной стороны.
    Возвращает координаты и маску наличия линии.
    """
    scan_width = _Config.SIDE_SCAN_WIDTH

    if side == "left":
        raw = _fit_edge_column(lime_mask, 0, min(scan_width, w), h, "left")
    elif side == "right":
        raw = _fit_edge_column(lime_mask, max(0, w - scan_width), w, h, "right")
    elif side == "top":
        raw = _fit_edge_row(lime_mask, 0, min(scan_width, h), w, "top")
    elif side == "bottom":
        raw = _fit_edge_row(lime_mask, max(0, h - scan_width), h, w, "bottom")
    else:
        raise ValueError(f"Неизвестная сторона: {side}")

    on_mask = ~np.isnan(raw)
    interpolated = _interpolate_gaps(raw)
    safe = np.where(np.isnan(interpolated), 0.0, interpolated)
    coords = np.round(safe).astype(np.int32)

    return coords, on_mask


def _fit_edge_column(lime_mask: np.ndarray, col_start: int, col_end: int, h: int, side: str) -> np.ndarray:
    """Находит внутреннюю кромку для левой/правой стороны (векторизованно)."""
    strip = lime_mask[:, col_start:col_end]
    xs = _find_inner_edge(strip, "row", side, col_start)
    return _reject_outliers(xs, _Config.MAX_LINE_DEVIATION, _Config.REFERENCE_SMOOTH_WINDOW)


def _fit_edge_row(lime_mask: np.ndarray, row_start: int, row_end: int, w: int, side: str) -> np.ndarray:
    """Находит внутреннюю кромку для верхней/нижней стороны (векторизованно)."""
    strip = lime_mask[row_start:row_end, :]
    ys = _find_inner_edge(strip, "col", side, row_start)
    return _reject_outliers(ys, _Config.MAX_LINE_DEVIATION, _Config.REFERENCE_SMOOTH_WINDOW)


def _interpolate_gaps(values: np.ndarray) -> np.ndarray:
    """Линейная интерполяция NaN-значений."""
    n = len(values)
    result = values.copy()
    indices = np.arange(n)
    known = ~np.isnan(values)

    if known.sum() < 2:
        if known.sum() == 1:
            result[:] = values[known][0]
        return result

    return np.interp(indices, indices[known], values[known])


def _smooth_on_mask(on_mask: np.ndarray, gap_close: int) -> np.ndarray:
    """Морфологическое закрытие для сглаживания разрывов в маске."""
    if gap_close <= 1:
        return on_mask

    arr = (on_mask.astype(np.uint8) * 255).reshape(1, -1)
    kernel = np.ones((1, _ensure_odd(gap_close)), np.uint8)
    closed = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel)

    return closed.reshape(-1) > 0


def _mask_corner_zones(on_mask: np.ndarray, margin: int) -> np.ndarray:
    """Маскирует углы, где детекция нестабильна."""
    if margin <= 0:
        return on_mask

    result = on_mask.copy()
    m = min(margin, len(result))
    result[:m] = True
    result[-m:] = True

    return result


def _collect_defect_segments(on_mask: np.ndarray, coords: np.ndarray, axis: str,
                             side: str, min_len: int) -> List[Dict[str, Any]]:
    """
    Собирает информацию о дефектах (разрывах) в линии.
    Дефект — непрерывный участок, где линия отсутствует.
    Для каждого дефекта также вычисляются границы по координатам линии.
    """
    n = len(on_mask)
    if n == 0:
        return []

    pad = np.empty(n + 2, dtype=np.int8)
    pad[0] = 1
    pad[-1] = 1
    pad[1:-1] = on_mask.astype(np.int8)
    diffs = np.diff(pad)

    starts = np.flatnonzero(diffs == -1)
    ends_excl = np.flatnonzero(diffs == 1)
    if starts.size == 0:
        return []

    lengths = ends_excl - starts
    keep = lengths >= min_len
    starts = starts[keep]
    ends_excl = ends_excl[keep]
    lengths = lengths[keep]

    defects: List[Dict[str, Any]] = []
    for s, e_excl, L in zip(starts.tolist(), ends_excl.tolist(), lengths.tolist()):
        e = e_excl - 1

        # Получаем координаты линии на участке дефекта
        seg_coords = coords[s:e + 1]
        line_min = int(seg_coords.min())
        line_max = int(seg_coords.max())

        if axis == "vertical":
            # Вертикальные линии (левая и правая стороны)
            x1, y1 = line_min, s
            x2, y2 = line_max, e
        else:  # horizontal
            # Горизонтальные линии (верхняя и нижняя стороны)
            x1, y1 = s, line_min
            x2, y2 = e, line_max

        defects.append({
            "side": side,
            "axis": axis,
            "start": int(s),
            "end": int(e),
            "length": int(L),
            "x1": x1, "y1": y1,
            "x2": x2, "y2": y2,
            "line_min": line_min,
            "line_max": line_max,
        })

    return defects


def _expand_bbox_for_side(bbox: Tuple[int, int, int, int], side: str,
                          band_width: int, padding: int, extra_width: int,
                          img_shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """
    Расширяет bbox для дефекта с учетом стороны кристалла.

    Args:
        bbox: (x1, y1, x2, y2) исходный bbox
        side: сторона кристалла (left/right/top/bottom)
        band_width: ширина каймы
        padding: базовый отступ
        extra_width: дополнительная ширина перпендикулярно кайме
        img_shape: размеры изображения (h, w)

    Returns:
        Расширенный bbox (x1, y1, x2, y2)
    """
    h, w = img_shape[:2]
    x1, y1, x2, y2 = bbox

    # Базовый отступ
    x1 -= padding
    x2 += padding
    y1 -= padding
    y2 += padding

    # Расширение в сторону края (перпендикулярно кайме)
    if side == "left":
        x1 -= (band_width + extra_width)
    elif side == "right":
        x2 += (band_width + extra_width)
    elif side == "top":
        y1 -= (band_width + extra_width)
    elif side == "bottom":
        y2 += (band_width + extra_width)

    # Ограничиваем границами изображения
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w - 1, x2)
    y2 = min(h - 1, y2)

    return x1, y1, x2, y2


def _enforce_min_size(bbox: Tuple[int, int, int, int], min_size: int,
                      img_shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """
    Гарантирует минимальный размер bbox.

    Args:
        bbox: (x1, y1, x2, y2)
        min_size: минимальный размер стороны в пикселях
        img_shape: размеры изображения (h, w)

    Returns:
        bbox с гарантированным минимальным размером
    """
    h, w = img_shape[:2]
    x1, y1, x2, y2 = bbox

    bw = x2 - x1 + 1
    bh = y2 - y1 + 1

    if bw < min_size:
        cx = (x1 + x2) // 2
        x1 = cx - min_size // 2
        x2 = x1 + min_size - 1

    if bh < min_size:
        cy = (y1 + y2) // 2
        y1 = cy - min_size // 2
        y2 = y1 + min_size - 1

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w - 1, x2)
    y2 = min(h - 1, y2)

    return x1, y1, x2, y2


def _draw_adaptive_rectangle(img: np.ndarray, defect: Dict[str, Any],
                             color: Tuple[int, int, int], thickness: int,
                             band_width: int, padding: int, extra_width: int,
                             min_size: int) -> None:
    """
    Рисует адаптивный прямоугольник для дефекта.
    Прямоугольник строится от начала дефекта до конца, с расширением наружу.

    Args:
        img: Изображение для рисования
        defect: Словарь с информацией о дефекте
        color: Цвет прямоугольника в BGR
        thickness: Толщина линии
        band_width: Ширина каймы
        padding: Базовый отступ
        extra_width: Дополнительная ширина перпендикулярно кайме
        min_size: Минимальный размер стороны
    """
    side = defect["side"]
    axis = defect["axis"]

    # Получаем координаты дефекта
    if axis == "vertical":
        # Для вертикальных дефектов ось Y - длина дефекта, ось X - позиция линии
        y1, y2 = defect["start"], defect["end"]
        line_min = defect.get("line_min", defect["x1"])
        line_max = defect.get("line_max", defect["x2"])
        bbox = (line_min, y1, line_max, y2)
    else:  # horizontal
        # Для горизонтальных дефектов ось X - длина дефекта, ось Y - позиция линии
        x1, x2 = defect["start"], defect["end"]
        line_min = defect.get("line_min", defect["y1"])
        line_max = defect.get("line_max", defect["y2"])
        bbox = (x1, line_min, x2, line_max)

    # Расширяем bbox
    expanded = _expand_bbox_for_side(bbox, side, band_width, padding, extra_width, img.shape)

    # Обеспечиваем минимальный размер
    final_bbox = _enforce_min_size(expanded, min_size, img.shape)

    x1, y1, x2, y2 = final_bbox

    # Рисуем прямоугольник
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)

    # Рисуем подпись с номером дефекта
    label = f"#{defect.get('id', 0)}"
    cv2.putText(
        img, label, (x1, max(15, y1 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX, _Config.DEFECT_LABEL_SCALE, color, 2, cv2.LINE_AA
    )


def _detect_dark_spots_on_border(img_bgr: np.ndarray, hsv: np.ndarray,
                                 lime_mask: np.ndarray) -> List[Dict[str, Any]]:
    """Детектирует тёмные пятна поверх каймы с проверкой реального перекрытия."""
    if not lime_mask.any():
        return []
    img_h, img_w = img_bgr.shape[:2]
    margin = _Config.CORNER_IGNORE_MARGIN
    dilate_k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (_ensure_odd(_Config.DARK_SPOT_DILATE), _ensure_odd(_Config.DARK_SPOT_DILATE))
    )
    search_zone = cv2.dilate(lime_mask, dilate_k, iterations=1)
    corner_mask = np.ones((img_h, img_w), dtype=np.uint8) * 255
    corner_mask[:margin, :margin] = 0
    corner_mask[:margin, img_w - margin:] = 0
    corner_mask[img_h - margin:, :margin] = 0
    corner_mask[img_h - margin:, img_w - margin:] = 0
    search_zone = cv2.bitwise_and(search_zone, corner_mask)
    dark_mask = (hsv[:, :, 2] <= _Config.DARK_SPOT_V_MAX).astype(np.uint8) * 255
    dark_on_border = cv2.bitwise_and(dark_mask, search_zone)
    open_k = _ell_kernel(3)
    dark_on_border = cv2.morphologyEx(dark_on_border, cv2.MORPH_OPEN, open_k)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(dark_on_border, 8)
    defects = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < _Config.DARK_SPOT_MIN_PIXELS:
            continue
        component_mask = (labels == i).astype(np.uint8) * 255
        overlap = cv2.countNonZero(cv2.bitwise_and(component_mask, lime_mask))
        if overlap < _Config.DARK_SPOT_MIN_OVERLAP:
            continue
        x1 = int(stats[i, cv2.CC_STAT_LEFT])
        y1 = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        x2 = x1 + bw - 1
        y2 = y1 + bh - 1
        cx, cy = centroids[i]
        dist = {"top": cy, "bottom": img_h - cy, "left": cx, "right": img_w - cx}
        side = min(dist, key=dist.get)
        defects.append({
            "side": side,
            "axis": "vertical" if side in ("left", "right") else "horizontal",
            "start": y1 if side in ("left", "right") else x1,
            "end": y2 if side in ("left", "right") else x2,
            "length": max(bw, bh),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "line_min": x1 if side in ("left", "right") else y1,
            "line_max": x2 if side in ("left", "right") else y2,
            "type": "dark_spot", "area": area,
        })
    return defects


def _detect_defects(img_bgr: np.ndarray, hsv: np.ndarray, lime_mask: np.ndarray) -> List[Dict[str, Any]]:
    """
    Обнаруживает дефекты в кайме без отрисовки линий.
    Возвращает список дефектов.
    """
    h, w = lime_mask.shape
    all_defects = []

    # Строим линии по всем сторонам
    left_coords, left_on_mask = _build_side_line(lime_mask, "left", h, w)
    right_coords, right_on_mask = _build_side_line(lime_mask, "right", h, w)
    top_coords, top_on_mask = _build_side_line(lime_mask, "top", h, w)
    bottom_coords, bottom_on_mask = _build_side_line(lime_mask, "bottom", h, w)

    # Постобработка масок
    left_on_mask = _smooth_on_mask(left_on_mask, _Config.ON_MASK_GAP_CLOSE)
    right_on_mask = _smooth_on_mask(right_on_mask, _Config.ON_MASK_GAP_CLOSE)
    top_on_mask = _smooth_on_mask(top_on_mask, _Config.ON_MASK_GAP_CLOSE)
    bottom_on_mask = _smooth_on_mask(bottom_on_mask, _Config.ON_MASK_GAP_CLOSE)

    left_on_mask = _mask_corner_zones(left_on_mask, _Config.CORNER_IGNORE_MARGIN)
    right_on_mask = _mask_corner_zones(right_on_mask, _Config.CORNER_IGNORE_MARGIN)
    top_on_mask = _mask_corner_zones(top_on_mask, _Config.CORNER_IGNORE_MARGIN)
    bottom_on_mask = _mask_corner_zones(bottom_on_mask, _Config.CORNER_IGNORE_MARGIN)

    # Собираем дефекты
    min_len = max(_Config.MIN_DEFECT_SEGMENT_LENGTH_FALLBACK,
                  int(_Config.MIN_DEFECT_RELATIVE * max(h, w)))

    all_defects += _collect_defect_segments(left_on_mask, left_coords, "vertical", "left", min_len)
    all_defects += _collect_defect_segments(right_on_mask, right_coords, "vertical", "right", min_len)
    all_defects += _collect_defect_segments(top_on_mask, top_coords, "horizontal", "top", min_len)
    all_defects += _collect_defect_segments(bottom_on_mask, bottom_coords, "horizontal", "bottom", min_len)

    # Детектируем тёмные пятна поверх каймы
    dark_spots = _detect_dark_spots_on_border(img_bgr, hsv, lime_mask)
    all_defects += dark_spots

    # Присваиваем ID дефектам
    for i, d in enumerate(all_defects):
        d["id"] = i + 1

    return all_defects


# ═══════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ОСНОВНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════

def _process_cutting_error_frame(frame_original: np.ndarray,
                                 frame_filtered: np.ndarray,
                                 cropped_frame_list: List[np.ndarray],
                                 defects: List[Dict[str, Any]],
                                 model_dict: Dict[str, Any],
                                 contour_thickness: int = 4) -> Tuple[int, Optional[np.ndarray]]:
    """
    Анализ вырезанных патчей через нейросеть для поиска ошибок реза.

    Находит контуры из масок (сегментация), проверяет их уверенность,
    затем рисует прямоугольники 400×608 вокруг центров подтверждённых дефектов.
    Пересекающиеся прямоугольники объединяются в один непрерывный контур.
    """
    model = model_dict['model']
    conf_threshold = float(model_dict["conf"])

    if not cropped_frame_list:
        return 0, None

    tile_w, tile_h = CROP_W, CROP_H  # 400×608
    device = next(model.parameters()).device
    use_half = device.type != 'cpu'

    t1 = time.time()

    results = model.predict(
        source=cropped_frame_list,
        device=device,
        conf=conf_threshold,
        iou=0,
        imgsz=608,
        half=use_half,
        verbose=False,
        task="segment",
        stream=False
    )

    t_infer = time.time() - t1
    logger.debug(f"Инференс: {t_infer:.3f}с")

    confirmed_rects = []  # Список подтверждённых прямоугольников [x1, y1, x2, y2]
    defect_count = 0

    for result, defect in zip(results, defects):
        if result.masks is None:
            continue

        masks_tensor = result.masks.data
        if device.type != 'cpu':
            masks_tensor = masks_tensor.to(device)

        # Масштабирование до размера патча на GPU
        masks_resized = torch.nn.functional.interpolate(
            masks_tensor.unsqueeze(1),
            size=(tile_h, tile_w),
            mode='nearest'
        ).squeeze(1)

        # Старый порог бинаризации — 0.5
        masks_binary = (masks_resized > 0.5).byte()
        masks_np = masks_binary.cpu().numpy()

        # Вычисляем смещение патча относительно оригинального изображения
        img_h, img_w = frame_original.shape[:2]
        cx, cy = _get_defect_center(defect, (img_h, img_w))

        # Проверяем контуры: суммируем точки со всех контуров
        total_contour_points = 0

        for mask in masks_np:
            mask_uint8 = mask * 255
            contours, _ = cv2.findContours(
                mask_uint8,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )
            for cnt in contours:
                total_contour_points += len(cnt)

        has_confirmed_defect = total_contour_points >= 20
        if has_confirmed_defect:
            defect_count += 1

            # Прямоугольник 400×608 с центром на дефекте
            half_w = tile_w // 2
            half_h = tile_h // 2

            x1 = cx - half_w
            y1 = cy - half_h
            x2 = x1 + tile_w
            y2 = y1 + tile_h

            # Обрезаем по границам изображения
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(img_w - 1, x2)
            y2 = min(img_h - 1, y2)

            confirmed_rects.append([x1, y1, x2, y2])

    # Объединяем пересекающиеся прямоугольники
    merged_rects = _merge_intersecting_rectangles(confirmed_rects)

    # Рисуем объединённые прямоугольники
    if merged_rects:
        color_outline = (model_dict["color"][2], model_dict["color"][1], model_dict["color"][0])

        for rect in merged_rects:
            x1, y1, x2, y2 = rect
            cv2.rectangle(
                frame_filtered,
                (x1, y1), (x2, y2),
                color_outline,
                contour_thickness,
                cv2.LINE_AA
            )

        return defect_count, frame_filtered
    else:
        return 0, None


def _merge_intersecting_rectangles(rects: List[List[int]]) -> List[List[int]]:
    """
    Объединяет пересекающиеся прямоугольники в один непрерывный контур.

    Алгоритм:
    1. Вычисляет IoU (Intersection over Union) для всех пар
    2. Если два прямоугольника пересекаются — объединяет их (bounding box обоих)
    3. Повторяет, пока есть пересечения

    Args:
        rects: Список прямоугольников [x1, y1, x2, y2]

    Returns:
        Список объединённых прямоугольников
    """
    if len(rects) <= 1:
        return rects

    # Функция для вычисления площади пересечения
    def intersection_area(r1, r2):
        x1 = max(r1[0], r2[0])
        y1 = max(r1[1], r2[1])
        x2 = min(r1[2], r2[2])
        y2 = min(r1[3], r2[3])

        if x1 >= x2 or y1 >= y2:
            return 0

        return (x2 - x1) * (y2 - y1)

    # Функция для вычисления площади прямоугольника
    def rect_area(r):
        return (r[2] - r[0]) * (r[3] - r[1])

    # Функция для вычисления IoU
    def iou(r1, r2):
        inter = intersection_area(r1, r2)
        if inter == 0:
            return 0
        union = rect_area(r1) + rect_area(r2) - inter
        return inter / union if union > 0 else 0

    # Итеративно объединяем пересекающиеся прямоугольники
    merged = list(rects)  # Копируем список

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(merged):
            j = i + 1
            while j < len(merged):
                # Если IoU > 0 (любое пересечение) — объединяем
                if iou(merged[i], merged[j]) > 0:
                    # Объединяем: bounding box обоих прямоугольников
                    r1, r2 = merged[i], merged[j]
                    merged[i] = [
                        min(r1[0], r2[0]),
                        min(r1[1], r2[1]),
                        max(r1[2], r2[2]),
                        max(r1[3], r2[3])
                    ]
                    # Удаляем второй прямоугольник
                    merged.pop(j)
                    changed = True
                else:
                    j += 1
            i += 1

    return merged


def _crop_defect_for_yolo(frame_original: np.ndarray,
                          defect: Dict[str, Any],
                          crop_w: int = CROP_W,
                          crop_h: int = CROP_H) -> np.ndarray:
    """
    Вырезает патч вокруг дефекта для последующей разметки / инференса YOLO.

    Алгоритм:
    1. Находит центр дефекта.
    2. Вырезает прямоугольник crop_w × crop_h с центром на дефекте.
       Если патч выходит за границы изображения — дополняет чёрными пикселями.
    3. Поворачивает патч так, чтобы дефект всегда располагался у одной стороны
       (нормализация ориентации для обучения YOLO):
         - right  →   0° (патч не поворачивается, эталон)
         - left   → 180°
         - top    →  90°
         - bottom → -90°

    Args:
        frame_original: Оригинальное BGR-изображение (numpy array).
        defect:         Словарь дефекта из find_cutting_error_defects().
        crop_w:         Ширина патча в пикселях (короткая сторона).
        crop_h:         Высота патча в пикселях (длинная сторона).

    Returns:
        BGR numpy array размером crop_w × crop_h (после нормализации поворота).
    """
    img_h, img_w = frame_original.shape[:2]

    # 1. Центр дефекта
    cx, cy = _get_defect_center(defect, (img_h, img_w))

    # 2. Вырезаем патч crop_w × crop_h, дефект в центре
    half_w = crop_w // 2
    half_h = crop_h // 2

    x1 = cx - half_w
    y1 = cy - half_h
    x2 = x1 + crop_w
    y2 = y1 + crop_h

    # Отступы для padding (если выходим за границы)
    pad_left = max(0, -x1)
    pad_top = max(0, -y1)
    pad_right = max(0, x2 - img_w)
    pad_bottom = max(0, y2 - img_h)

    # Клипируем к границам изображения
    x1c = max(0, x1)
    y1c = max(0, y1)
    x2c = min(img_w, x2)
    y2c = min(img_h, y2)

    patch = frame_original[y1c:y2c, x1c:x2c].copy()

    # Дополняем чёрными пикселями, если патч у края
    if pad_left or pad_top or pad_right or pad_bottom:
        patch = cv2.copyMakeBorder(
            patch,
            pad_top, pad_bottom, pad_left, pad_right,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )

    # 3. Нормализуем ориентацию поворотом
    angle = _rotation_for_side(defect.get("side", "right"))
    patch = _rotate_image(patch, angle)

    return patch


def _find_suspicious_areas_with_cutting_error(frame: np.ndarray) -> list[dict[str, Any]]:
    """
    Поиск ошибки реза кристаллов.
    Дефект — разрыв в белой кайме по краям кристалла.

    Args:
        frame: Оригинальное изображение с камеры для анализа (BGR, numpy array)

    Returns:
        Словарь с координатами тех зон, где подозрение на дефект ошибки реза
    """
    try:
        # ── Проверка входных данных ──────────────────────────────────
        if frame is None:
            return []

        # ── Предобработка оригинала для анализа ──────────────────────
        img_filtered = _apply_blur_filter(frame)
        img_preprocessed = _apply_manual_adjustments(img_filtered) if _Config.PREPROCESS_ENABLE else img_filtered

        h, w = img_preprocessed.shape[:2]
        hsv = cv2.cvtColor(img_preprocessed, cv2.COLOR_BGR2HSV)

        # ── Детекция каймы ───────────────────────────────────────────
        search_zone = _build_search_zone(h, w)
        lime_mask_raw = _detect_lime_border(img_preprocessed, hsv, search_zone)

        # ── Нормализация толщины каймы ───────────────────────────────
        lime_mask = _trim_lime_uniform(lime_mask_raw)

        # ── Поиск дефектов без отрисовки ─────────────────────────────
        defects = _detect_defects(img_preprocessed, hsv, lime_mask)

        return defects

    except Exception as e:
        logger.error(f"Ошибка при поиске дефекта Ошибка реза: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# ОСНОВНАЯ ФУНКЦИЯ
# ═══════════════════════════════════════════════════════════════════════════


def find_cutting_error_defects(frame_original: np.ndarray,
                               frame_filtered: np.ndarray) -> Tuple[int, List[Dict[str, Any]], Optional[np.ndarray]]:
    """
    Поиск ошибки реза кристаллов.
    Дефект — разрыв в белой кайме по краям кристалла.

    Args:
        frame_original: Оригинальное изображение с камеры для анализа (BGR, numpy array)
        frame_filtered: Изображение с уже наложенными фильтрами других дефектов,
                       на которое будут добавлены прямоугольники новых дефектов (BGR, numpy array)

    Returns:
        tuple: (total_defect_count, defects_info, frame_filtered)
    """
    try:
        # ── Проверка входных данных ──────────────────────────────────
        if (frame_original is None or frame_original.size == 0 or
                frame_filtered is None or frame_filtered.size == 0):
            return 0, [], None

        total_start = time.time()

        defects_info = []
        total_defect_count = 0

        defect_model = nv.get_defect_model_by_type('cutting_error')
        if defect_model is None:
            logger.error("Модель 'cutting_error' не найдена")
            return 0, [], frame_filtered

        model_key = defect_model.get('defect_type', 'unknown')
        model_name = defect_model.get('name', 'Unknown')
        model_color = defect_model.get('color', [255, 255, 0])

        # Ищем подозрительные области через классический CV
        defects = _find_suspicious_areas_with_cutting_error(frame_original)
        if not defects:
            return 0, [], frame_filtered

        # Вырезаем патчи для нейросетевой проверки
        cropped_frame_list = []
        for defect in defects:
            patch = _crop_defect_for_yolo(frame_original, defect)
            cropped_frame_list.append(patch)

        # Проверяем через нейросеть
        defect_count, processed_frame = _process_cutting_error_frame(
            frame_original=frame_original,
            frame_filtered=frame_filtered,
            cropped_frame_list=cropped_frame_list,
            defects=defects,
            model_dict=defect_model
        )

        if defect_count > 0:
            defects_info.append({
                'key': model_key,
                'name': model_name,
                'color': model_color,
                'count': defect_count
            })
            total_defect_count = defect_count

        total_elapsed = time.time() - total_start
        logger.info(f"Полное время анализа изображения: {total_elapsed:.2f}с")

        if total_defect_count > 0:
            return total_defect_count, defects_info, (
                processed_frame if processed_frame is not None else frame_filtered)
        else:
            return 0, [], frame_filtered

    except Exception as e:
        logger.error(f"Ошибка при поиске дефекта Ошибка реза: {e}")
        return 0, [], frame_filtered
