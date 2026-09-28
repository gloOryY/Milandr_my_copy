import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List
import cv2
import torch
import numpy as np
import time
from numpy import ndarray

import project.algorithms.neural_network.networks_vault as nv
from project.application.addition.logger import logger
from project.configuration.config_manager import ConfigManager
from project.station.camera.frame_process import save_frame


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

    # ─── ОТРИСОВКА КРАЙНИХ ТОЧЕК КОНТУРА ─────────────────────────────
    CONTOUR_THICKNESS_SHORT = 1
    CONTOUR_THICKNESS_LONG = 3
    CONTOUR_COLOR_NEURAL_MASK_BGR = (0, 0, 255)  # Красный цвет контура нейронной маски в BGR
    CONTOUR_COLOR_MEASUREMENT_LINE_BGR = (255, 255, 0)  # Бирюзовый цвет контура отрезка отступа дефекта от каймы в BGR

    # ─── ПОРОГИ ДЛЯ ОТРЕЗКОВ (добавить в конец класса) ──────────────
    MIN_SEGMENT_LENGTH_MICRONS = 20.0   # Минимальная длина отрезка в микронах
    MIN_SEGMENT_LENGTH_PIXELS = 25      # Минимальная длина отрезка в пикселях (запасной)
    MIN_MASK_AREA = 20                  # Минимальная площадь маски нейросети


# ═══════════════════════════════════════════════════════════════════════════
# ЗАКРЫТЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════


# Размер вырезаемого патча (ширина x высота в пикселях)
# Итоговое изображение вертикальное: короткая сторона = CROP_W, длинная = CROP_H
CROP_W = 400  # ширина патча
CROP_H = 608  # высота патча


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
    inner_is_min = side in ("right", "bottom")

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
# ФУНКЦИИ ДЛЯ ПОИСКА КРАЙНИХ ТОЧЕК КОНТУРА
# ═══════════════════════════════════════════════════════════════════════════

def _create_completed_border_mask(lime_mask: np.ndarray,
                                  defects: List[Dict[str, Any]]) -> np.ndarray:
    """
    Создаёт дополненную маску каймы: оригинальная кайма + линии в местах разрывов.
    """
    completed = lime_mask.copy()

    for defect in defects:
        if defect.get("type") == "dark_spot":
            continue

        axis = defect["axis"]

        if axis == "vertical":
            x1 = defect["line_min"]
            y1 = defect["start"]
            x2 = defect["line_max"]
            y2 = defect["end"]
        else:  # horizontal
            x1 = defect["start"]
            y1 = defect["line_min"]
            x2 = defect["end"]
            y2 = defect["line_max"]

        # Рисуем толстую линию в разрыве
        cv2.line(completed, (x1, y1), (x2, y2), 255, thickness=3)

    return completed


def _find_final_measurement_point_on_mask(point: Tuple[int, int], mask: np.ndarray) -> tuple[Any] | None:
    """Находит ближайшую точку на маске к заданной точке."""
    if not mask.any():
        return None

    mask_points = np.argwhere(mask > 0)  # (y, x)
    if len(mask_points) == 0:
        return None

    mask_points_xy = mask_points[:, ::-1]  # (x, y)

    px, py = point
    distances = np.sqrt((mask_points_xy[:, 0] - px) ** 2 + (mask_points_xy[:, 1] - py) ** 2)
    nearest_idx = np.argmin(distances)

    return tuple(mask_points_xy[nearest_idx].tolist())


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


def _skeletonize_mask(mask: np.ndarray) -> np.ndarray:
    """
    Скелетизирует бинарную маску до толщины в 1 пиксель.
    Использует алгоритм Zhang-Suen через OpenCV ximgproc.

    Args:
        mask: Бинарная маска (0 или 255)

    Returns:
        Скелетизированная маска толщиной в 1 пиксель
    """
    if not mask.any():
        return mask

    # Преобразуем в формат, подходящий для thinning
    img = mask.copy()

    # Используем cv2.ximgproc.thinning если доступен
    # Если нет, используем альтернативный метод
    try:
        skeleton = cv2.ximgproc.thinning(img, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN)
    except AttributeError:
        # Запасной вариант: итеративная эрозия с открытием
        skeleton = np.zeros(img.shape, np.uint8)
        element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))

        while True:
            # Открытие (эрозия затем дилатация)
            opened = cv2.morphologyEx(img, cv2.MORPH_OPEN, element)

            # Вычитаем открытие из оригинала для получения тонких линий
            temp = cv2.subtract(img, opened)

            # Добавляем к скелету
            skeleton = cv2.bitwise_or(skeleton, temp)

            # Эрозия оригинала
            img = cv2.erode(img, element)

            # Если изображение полностью исчезло, выходим
            if cv2.countNonZero(img) == 0:
                break

    return skeleton


def _draw_lime_border_with_gap_lines(frame_filtered: np.ndarray,
                                     lime_mask: np.ndarray,
                                     defects: List[Dict[str, Any]],
                                     color: Tuple[int, int, int] = (0, 255, 0),
                                     alpha: float = 1.0,
                                     gap_line_color: Tuple[int, int, int] = (100, 255, 0),
                                     gap_line_thickness: int = 1,
                                     skeletonize: bool = True) -> np.ndarray:
    """
    Рисует маску каймы на изображении с заданным цветом и прозрачностью,
    а также соединяет красными линиями места разрывов в кайме.
    Опционально скелетизирует кайму до толщины в 1 пиксель.

    Args:
        frame_filtered: Изображение для наложения маски (BGR)
        lime_mask: Бинарная маска каймы (0 или 255)
        defects: Список дефектов (разрывов) в кайме
        color: Цвет для отрисовки маски в BGR (по умолчанию зеленый)
        alpha: Прозрачность наложения (0.0 - полностью прозрачно, 1.0 - непрозрачно)
        gap_line_color: Цвет линии разрыва в BGR (по умолчанию красный)
        gap_line_thickness: Толщина линии разрыва в пикселях
        skeletonize: Скелетизировать кайму до 1 пикселя (по умолчанию True)

    Returns:
        Изображение с наложенной маской каймы и красными линиями в местах разрывов
    """
    if not lime_mask.any():
        return frame_filtered

    # Скелетизируем маску до 1 пикселя, если нужно
    if skeletonize:
        display_mask = _skeletonize_mask(lime_mask)
    else:
        display_mask = lime_mask

    # Создаем цветную маску
    colored_mask = np.zeros_like(frame_filtered)
    colored_mask[display_mask > 0] = color

    # Накладываем с прозрачностью
    result = cv2.addWeighted(frame_filtered, 1.0, colored_mask, alpha, 0)

    # Рисуем красные линии в местах разрывов
    for defect in defects:
        # Пропускаем dark_spot дефекты
        if defect.get("type") == "dark_spot":
            continue

        axis = defect["axis"]

        # Получаем координаты начала и конца разрыва
        if axis == "vertical":
            # Вертикальные дефекты (левая/правая сторона)
            x1 = defect["line_min"]
            y1 = defect["start"]
            x2 = defect["line_max"]
            y2 = defect["end"]

            # Соединяем края разрыва по внутренней кромке
            cv2.line(result, (x1, y1), (x2, y2), gap_line_color, gap_line_thickness, cv2.LINE_AA)

        else:  # horizontal
            # Горизонтальные дефекты (верхняя/нижняя сторона)
            x1 = defect["start"]
            y1 = defect["line_min"]
            x2 = defect["end"]
            y2 = defect["line_max"]

            # Соединяем края разрыва по внутренней кромке
            cv2.line(result, (x1, y1), (x2, y2), gap_line_color, gap_line_thickness, cv2.LINE_AA)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ОСНОВНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════

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


def _batch_crop_defects_for_yolo(
        frame_original: np.ndarray,
        defects: List[Dict[str, Any]],
        crop_w: int = CROP_W,
        crop_h: int = CROP_H
) -> List[np.ndarray]:
    """
    Пакетное вырезание патчей для YOLO.
    Использует векторизованные операции где возможно.
    """
    if not defects:
        return []

    img_h, img_w = frame_original.shape[:2]
    patches = []
    half_w = crop_w // 2
    half_h = crop_h // 2

    # Предварительно вычисляем углы поворота для всех дефектов
    angles = [_rotation_for_side(d.get("side", "right")) for d in defects]

    for defect, angle in zip(defects, angles):
        # Центр дефекта
        cx, cy = _get_defect_center(defect, (img_h, img_w))

        # Координаты патча
        x1 = cx - half_w
        y1 = cy - half_h
        x2 = x1 + crop_w
        y2 = y1 + crop_h

        # Обрезка с паддингом
        pad_left = max(0, -x1)
        pad_top = max(0, -y1)
        pad_right = max(0, x2 - img_w)
        pad_bottom = max(0, y2 - img_h)

        x1c = max(0, x1)
        y1c = max(0, y1)
        x2c = min(img_w, x2)
        y2c = min(img_h, y2)

        patch = frame_original[y1c:y2c, x1c:x2c].copy()

        if pad_left or pad_top or pad_right or pad_bottom:
            patch = cv2.copyMakeBorder(
                patch,
                pad_top, pad_bottom, pad_left, pad_right,
                cv2.BORDER_CONSTANT,
                value=(0, 0, 0),
            )

        if angle != 0:
            patch = _rotate_image(patch, angle)

        patches.append(patch)

    return patches


def _find_suspicious_areas_with_cutting_error(frame: np.ndarray) -> tuple[list[dict[str, Any]], ndarray]:
    """
    Поиск ошибки реза кристаллов.
    Дефект — разрыв в белой кайме по краям кристалла.

    Args:
        frame: Оригинальное изображение с камеры для анализа (BGR, numpy array)

    Returns:
        defects: Словарь с координатами тех зон, где подозрение на дефект ошибки реза
        lime_mask: Координаты дополненной каймы
    """
    try:
        if frame is None:
            return [], np.array([])

        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        search_zone = _build_search_zone(h, w)
        lime_mask_raw = _detect_lime_border(frame, hsv, search_zone)
        lime_mask = _trim_lime_uniform(lime_mask_raw)

        defects = _detect_defects(frame, hsv, lime_mask)

        return defects, lime_mask

    except Exception as e:
        logger.error(f"Ошибка при поиске дефекта Ошибка реза: {e}")
        return [], np.array([])


def _rects_intersect(r1: List[int], r2: List[int]) -> bool:
    """Проверяет пересечение двух прямоугольников [x1, y1, x2, y2]."""
    return not (
            r1[2] < r2[0] or r2[2] < r1[0] or
            r1[3] < r2[1] or r2[3] < r1[1]
    )


def _place_patch_mask_to_image(mask_patch: np.ndarray,
                               patch_x1: int,
                               patch_y1: int,
                               img_h: int,
                               img_w: int) -> np.ndarray:
    """
    Размещает маску патча (размер tile_h x tile_w) в координатах полного изображения
    с учетом выхода патча за границы кадра.
    """
    out = np.zeros((img_h, img_w), dtype=np.uint8)

    src_x1 = max(0, -patch_x1)
    src_y1 = max(0, -patch_y1)
    dst_x1 = max(0, patch_x1)
    dst_y1 = max(0, patch_y1)

    copy_w = min(mask_patch.shape[1] - src_x1, img_w - dst_x1)
    copy_h = min(mask_patch.shape[0] - src_y1, img_h - dst_y1)

    if copy_w <= 0 or copy_h <= 0:
        return out

    out[dst_y1:dst_y1 + copy_h, dst_x1:dst_x1 + copy_w] = \
        mask_patch[src_y1:src_y1 + copy_h, src_x1:src_x1 + copy_w]

    return out


def _select_inner_part_of_mask(mask_img: np.ndarray,
                               completed_lime_mask: np.ndarray,
                               defect_side: str) -> np.ndarray:
    """
    Делит нейронную маску каймой на части и оставляет только ту часть,
    которая находится СО СТОРОНЫ ЦЕНТРА изображения.

    Важно:
    - кайма используется как "разделитель", а не как область исключения
    - если вся маска находится с наружной стороны каймы, вернется пустая маска
    """
    if not mask_img.any():
        return np.zeros_like(mask_img)

    if completed_lime_mask is None or not completed_lime_mask.any():
        return mask_img.copy()

    # Немного утолщаем кайму, чтобы гарантированно разрезать маску на части
    split_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    border_splitter = cv2.dilate(completed_lime_mask, split_kernel, iterations=1)

    # Разрезаем маску каймой
    split_mask = cv2.bitwise_and(mask_img, cv2.bitwise_not(border_splitter))
    if not split_mask.any():
        return np.zeros_like(mask_img)

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(split_mask, 8)

    selected = np.zeros_like(mask_img)

    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area <= 3:
            continue

        cx = int(round(centroids[i][0]))
        cy = int(round(centroids[i][1]))

        nearest_border_pt = _find_final_measurement_point_on_mask((cx, cy), completed_lime_mask)
        if nearest_border_pt is None:
            continue

        bx, by = nearest_border_pt

        # Выбираем компоненту, которая находится СО СТОРОНЫ ЦЕНТРА
        is_inner = (
                (defect_side == "left" and cx > bx) or
                (defect_side == "right" and cx < bx) or
                (defect_side == "top" and cy > by) or
                (defect_side == "bottom" and cy < by)
        )

        if is_inner:
            selected[labels == i] = 255

    # Если внутренней части нет — возвращаем пустую маску
    if not selected.any():
        return selected

    # Чуть восстанавливаем пиксели возле линии разреза, но только внутри исходной маски
    selected = cv2.bitwise_and(
        cv2.dilate(selected, split_kernel, iterations=1),
        mask_img
    )

    return selected


def _get_pixels_to_microns_coeff() -> Optional[float]:
    """
    Возвращает коэффициент пересчёта пикселей в микроны из ConfigManager.
    Если ConfigManager недоступен или коэффициент не задан — возвращает None.
    """
    try:
        if not ConfigManager.has_instance():
            return None
        cfg = ConfigManager.get_instance()
        coeff = getattr(cfg, "translation_coefficient", None)
        if coeff and float(coeff) > 0:
            return float(coeff)
        return 0.0008 * 1000

    except Exception:
        return None


def _merge_rectangles_gpu(rects: List[List[int]]) -> List[List[int]]:
    """
    GPU-ускоренное объединение пересекающихся прямоугольников.
    Использует матричные операции через NumPy.
    """
    if len(rects) <= 1:
        return rects

    rects_np = np.array(rects, dtype=np.int32)

    # Вычисляем площади всех прямоугольников
    areas = (rects_np[:, 2] - rects_np[:, 0]) * (rects_np[:, 3] - rects_np[:, 1])

    # Проверяем пересечения всех пар (векторизованно)
    merged = list(rects)
    changed = True

    while changed and len(merged) > 1:
        changed = False
        merged_np = np.array(merged, dtype=np.int32)
        n = len(merged_np)

        # Вычисляем пересечения для всех пар
        for i in range(n):
            for j in range(i + 1, n):
                r1, r2 = merged_np[i], merged_np[j]

                # Проверка пересечения
                if r1[2] >= r2[0] and r2[2] >= r1[0] and r1[3] >= r2[1] and r2[3] >= r1[1]:
                    # Объединяем
                    merged_np[i] = [
                        min(r1[0], r2[0]),
                        min(r1[1], r2[1]),
                        max(r1[2], r2[2]),
                        max(r1[3], r2[3])
                    ]
                    merged_np = np.delete(merged_np, j, axis=0)
                    changed = True
                    break
            if changed:
                break

        merged = merged_np.tolist() if changed else merged

    return merged


class GPUContourProcessor:
    """
    GPU-ускоритель для обработки масок нейросети.
    Все операции с масками выполняются на GPU, контуры извлекаются только для
    отобранных кандидатов.
    """

    def __init__(self, device: torch.device):
        self.device = device
        self._cache = {}  # Кэш для повторяющихся операций

    def process_masks_batch(
            self,
            masks_tensor: torch.Tensor,
            tile_coords: List[Tuple[int, int]],
            tile_size: Tuple[int, int],
            img_shape: Tuple[int, int],
            min_area: int = 20
    ) -> List[np.ndarray]:
        """
        Пакетная обработка масок на GPU.

        Args:
            masks_tensor: Тензор масок (N, H, W) на GPU
            tile_coords: Координаты тайлов [(x, y), ...]
            tile_size: (tile_w, tile_h)
            img_shape: (h, w)
            min_area: Минимальная площадь контура

        Returns:
            Список контуров в глобальных координатах
        """
        if masks_tensor is None or masks_tensor.numel() == 0:
            return []

        # Переносим на GPU если еще не там
        if masks_tensor.device != self.device:
            masks_tensor = masks_tensor.to(self.device)

        # Пакетный resize
        tile_w, tile_h = tile_size
        masks_resized = torch.nn.functional.interpolate(
            masks_tensor.unsqueeze(1),
            size=(tile_h, tile_w),
            mode='nearest'
        ).squeeze(1)

        # Бинаризация (векторизованно)
        masks_binary = (masks_resized > 0.5).byte()

        all_contours = []

        # Обработка каждой маски
        for i, (x_off, y_off) in enumerate(tile_coords):
            if i >= masks_binary.shape[0]:
                break

            mask = masks_binary[i].cpu().numpy()

            # Быстрая проверка на наличие ненулевых пикселей
            if mask.sum() < min_area:
                continue

            # Находим контуры только для масок с достаточной площадью
            contours, _ = cv2.findContours(
                mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            for cnt in contours:
                if len(cnt) >= 3:
                    cnt[:, :, 0] += x_off
                    cnt[:, :, 1] += y_off
                    all_contours.append(cnt)

        return all_contours


def _process_cutting_error_frame(frame_original: np.ndarray,
                                 frame_filtered: np.ndarray,
                                 cropped_frame_list: List[np.ndarray],
                                 defects: List[Dict[str, Any]],
                                 model_dict: Dict[str, Any],
                                 lime_mask: np.ndarray = None,
                                 batch_size: int = 4) -> Tuple[int, Optional[np.ndarray]]:
    """
    Анализ вырезанных патчей через нейросеть для поиска ошибок реза.
    ОПТИМИЗИРОВАННАЯ версия с пакетной обработкой и GPU-масками.

    ВСЯ ОТРИСОВКА СОХРАНЕНА:
    - контур маски (красный)
    - отрезок до каймы (бирюзовый)
    - круги на концах отрезка
    - подпись с расстоянием
    - жёлтый bbox зоны
    """
    model = model_dict['model']
    conf_threshold = float(model_dict["conf"])

    if not cropped_frame_list:
        return 0, None

    tile_w, tile_h = CROP_W, CROP_H
    device = next(model.parameters()).device
    use_half = device.type != 'cpu'

    # ─── ПАКЕТНЫЙ ИНФЕРЕНС ──────────────────────────────────────────
    start_time = time.time()
    all_results = []
    total_patches = len(cropped_frame_list)
    batch_size = min(batch_size, total_patches)

    for i in range(0, total_patches, batch_size):
        batch = cropped_frame_list[i:i + batch_size]
        results = model.predict(
            source=batch,
            device=device,
            conf=conf_threshold,
            iou=0,
            imgsz=608,
            half=use_half,
            verbose=False,
            task="segment",
            stream=False
        )
        all_results.extend(results)
    logger.debug(f"Инференс: {time.time() - start_time:.3f}с")

    img_h, img_w = frame_original.shape[:2]

    # ─── ПОДГОТОВКА МАСОК ДЛЯ ИЗМЕРЕНИЙ ──────────────────────────
    completed_lime_mask = None
    dist_from_border = None
    if lime_mask is not None and lime_mask.any():
        completed_lime_mask = _create_completed_border_mask(lime_mask, defects)
        border_inv = cv2.bitwise_not(completed_lime_mask)
        dist_from_border = cv2.distanceTransform(border_inv, cv2.DIST_L2, 5)

    candidates = []
    px_to_um = _get_pixels_to_microns_coeff()

    for result, defect in zip(all_results, defects):
        if result.masks is None:
            continue

        angle = _rotation_for_side(defect.get("side", "right"))

        # Получаем маски на GPU
        masks_tensor = result.masks.data
        if device.type != 'cpu':
            masks_tensor = masks_tensor.to(device)

        # Размер патча после поворота
        if angle in (90, -90, 270, -270):
            rot_w, rot_h = tile_h, tile_w
        else:
            rot_w, rot_h = tile_w, tile_h

        # Масштабирование масок на GPU (одна операция вместо N)
        masks_resized = torch.nn.functional.interpolate(
            masks_tensor.unsqueeze(1),
            size=(rot_h, rot_w),
            mode='nearest'
        ).squeeze(1)

        # Бинаризация на GPU
        masks_binary = (masks_resized > 0.5).byte()

        # Объединяем все маски предсказания по данному дефекту на GPU
        combined_mask_gpu = torch.any(masks_binary, dim=0).byte()

        # Проверяем количество ненулевых пикселей
        if combined_mask_gpu.sum().item() < _Config.MIN_MASK_AREA:
            continue

        # Переносим на CPU только для финальной обработки
        combined_mask_rot = combined_mask_gpu.cpu().numpy()

        # Возвращаем маску из повернутого состояния
        combined_mask_patch = _rotate_image(combined_mask_rot, -angle)

        # Координаты исходного патча ДО поворота
        cx, cy = _get_defect_center(defect, (img_h, img_w))
        half_w = tile_w // 2
        half_h = tile_h // 2
        patch_x1 = cx - half_w
        patch_y1 = cy - half_h
        patch_x2 = patch_x1 + tile_w
        patch_y2 = patch_y1 + tile_h

        # Размещаем маску в координатах полного изображения
        combined_mask_img = _place_patch_mask_to_image(
            mask_patch=combined_mask_patch,
            patch_x1=patch_x1,
            patch_y1=patch_y1,
            img_h=img_h,
            img_w=img_w
        )

        if not combined_mask_img.any():
            continue

        defect_side = defect.get("side", "left")

        # ── Берем только внутреннюю часть маски ─────────────────────
        inner_mask_img = _select_inner_part_of_mask(
            mask_img=combined_mask_img,
            completed_lime_mask=completed_lime_mask,
            defect_side=defect_side
        )

        if not inner_mask_img.any():
            continue

        # Контуры только выбранной внутренней части
        contours_img, _ = cv2.findContours(
            inner_mask_img,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours_img:
            continue

        # В рамках одного дефекта выбираем только один контур
        best_local = None

        for cnt in contours_img:
            if len(cnt) < 3:
                continue

            component_mask = np.zeros((img_h, img_w), dtype=np.uint8)
            cv2.drawContours(component_mask, [cnt], -1, 255, thickness=-1)

            if dist_from_border is not None:
                dist_local = dist_from_border.copy()
                dist_local[component_mask == 0] = -1.0

                max_idx = int(np.argmax(dist_local))
                max_val = float(dist_local.flat[max_idx])

                if max_val <= 0:
                    continue

                py, px = np.unravel_index(max_idx, dist_local.shape)
                start_measurement_point = (int(px), int(py))
            else:
                pts = cnt.reshape(-1, 2)
                start_measurement_point = tuple(np.mean(pts, axis=0).astype(int).tolist())

            final_measurement_point = None
            seg_length = 0

            if completed_lime_mask is not None:
                final_measurement_point = _find_final_measurement_point_on_mask(
                    start_measurement_point, completed_lime_mask
                )
                if final_measurement_point is None:
                    continue

                dx = final_measurement_point[0] - start_measurement_point[0]
                dy = final_measurement_point[1] - start_measurement_point[1]
                seg_length = int(np.sqrt(dx * dx + dy * dy))

            # ── Проверка порогов ─────────────────────────────────────
            if px_to_um is not None:
                seg_microns = seg_length * px_to_um
                if seg_microns < _Config.MIN_SEGMENT_LENGTH_MICRONS:  # ← ИСПОЛЬЗУЕМ КОНСТАНТУ
                    continue
            else:
                if seg_length < _Config.MIN_SEGMENT_LENGTH_PIXELS:  # ← ИСПОЛЬЗУЕМ КОНСТАНТУ
                    continue

            candidate = {
                "rect": [
                    max(0, patch_x1),
                    max(0, patch_y1),
                    min(img_w - 1, patch_x2),
                    min(img_h - 1, patch_y2)
                ],
                "contour": cnt.copy(),
                "start_measurement_point": start_measurement_point,
                "final_measurement_point": final_measurement_point,
                "segment_length": seg_length
            }

            if best_local is None or candidate["segment_length"] > best_local["segment_length"]:
                best_local = candidate

        if best_local is not None:
            candidates.append(best_local)

    if not candidates:
        return 0, None

    # ── Объединяем жёлтые прямоугольники ────────────────────────────
    merged_rects = _merge_rectangles_gpu([c["rect"] for c in candidates])
    if not merged_rects:
        return 0, None

    color_outline = (
        model_dict["color"][2],
        model_dict["color"][1],
        model_dict["color"][0]
    )

    zone_count = 0

    for merged_rect in merged_rects:
        zone_candidates = [
            c for c in candidates
            if _rects_intersect(c["rect"], merged_rect)
        ]
        if not zone_candidates:
            continue

        # В рамках одной жёлтой зоны — только один контур и один отрезок
        chosen = max(zone_candidates, key=lambda c: c["segment_length"])

        cnt = chosen["contour"]
        start_measurement_point = chosen["start_measurement_point"]
        final_measurement_point = chosen["final_measurement_point"]
        seg_length = chosen["segment_length"]

        # ─── ОТРИСОВКА (ВСЯ СОХРАНЕНА) ──────────────────────────────

        # 1. Контур маски (красный)
        cv2.polylines(
            frame_filtered,
            [cnt.astype(np.int32)],
            isClosed=True,
            color=_Config.CONTOUR_COLOR_NEURAL_MASK_BGR,
            thickness=_Config.CONTOUR_THICKNESS_SHORT,
            lineType=cv2.LINE_AA
        )

        # 2. Отрезок до каймы (бирюзовый)
        if final_measurement_point is not None and seg_length > 0:
            cv2.line(
                frame_filtered,
                start_measurement_point,
                final_measurement_point,
                _Config.CONTOUR_COLOR_MEASUREMENT_LINE_BGR,
                _Config.CONTOUR_THICKNESS_SHORT,
                cv2.LINE_AA
            )

            # 3. Конечная точка отрезка (на кайме)
            cv2.circle(
                frame_filtered,
                final_measurement_point,
                _Config.CONTOUR_THICKNESS_LONG,
                _Config.CONTOUR_COLOR_MEASUREMENT_LINE_BGR,
                -1,
                cv2.LINE_AA
            )

            # 4. Начальная точка отрезка (на маске дефекта)
            cv2.circle(
                frame_filtered,
                start_measurement_point,
                _Config.CONTOUR_THICKNESS_LONG,
                _Config.CONTOUR_COLOR_MEASUREMENT_LINE_BGR,
                -1,
                cv2.LINE_AA
            )

            # 5. Подпись с расстоянием
            text_x = (start_measurement_point[0] + final_measurement_point[0]) // 2 + 8
            text_y = (start_measurement_point[1] + final_measurement_point[1]) // 2 - 8

            if px_to_um is not None:
                microns = seg_length * px_to_um
                text_str = f"{microns:.1f} um"
            else:
                text_str = f"{seg_length}px"

            (tw_txt, th_txt), _ = cv2.getTextSize(
                text_str,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                2
            )

            cv2.rectangle(
                frame_filtered,
                (text_x - 3, text_y - th_txt - 3),
                (text_x + tw_txt + 3, text_y + 3),
                (0, 0, 0),
                -1,
                cv2.LINE_AA
            )

            cv2.putText(
                frame_filtered,
                text_str,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                2,
                cv2.LINE_AA
            )

        # 6. Жёлтый bbox зоны
        x1, y1, x2, y2 = merged_rect
        cv2.rectangle(
            frame_filtered,
            (x1, y1), (x2, y2),
            color_outline,
            _Config.CONTOUR_THICKNESS_LONG,
            cv2.LINE_AA
        )

        zone_count += 1

    if zone_count > 0:
        return zone_count, frame_filtered

    return 0, None


# ═══════════════════════════════════════════════════════════════════════════
# ОСНОВНАЯ ФУНКЦИЯ
# ═══════════════════════════════════════════════════════════════════════════

def find_cutting_error_defects(frame_original: np.ndarray,
                               frame_filtered: np.ndarray,
                               debug: bool = False,
                               batch_size: int = 4) -> Tuple[int, List[Dict[str, Any]], Optional[np.ndarray]]:
    """
    ОПТИМИЗИРОВАННАЯ версия поиска ошибки реза кристаллов.

    ВСЯ ФУНКЦИОНАЛЬНОСТЬ СОХРАНЕНА:
    - CV-детекция каймы
    - Пакетный инференс нейросети
    - Полная отрисовка (контуры, отрезки, подписи)
    - Отладка (сохранение изображений)
    """
    try:
        if (frame_original is None or frame_original.size == 0 or
                frame_filtered is None or frame_filtered.size == 0):
            return 0, [], None

        total_start = time.time()
        defects_info = []
        total_defect_count = 0

        # Загружаем модель
        defect_model = nv.get_defect_model_by_type('cutting_error')
        if defect_model is None:
            logger.error("Модель 'cutting_error' не найдена")
            return 0, [], frame_filtered

        model_key = defect_model.get('defect_type', 'unknown')
        model_name = defect_model.get('name', 'Unknown')
        model_color = defect_model.get('color', [255, 255, 0])

        # ─── 1. ПРЕДОБРАБОТКА ──────────────────────────────────────
        frame = _apply_blur_filter(frame_original.copy())
        if _Config.PREPROCESS_ENABLE:
            frame = _apply_manual_adjustments(frame)

        # ─── 2. CV-ДЕТЕКЦИЯ ────────────────────────────────────────
        defects, lime_mask = _find_suspicious_areas_with_cutting_error(frame)
        if not defects:
            return 0, [], frame_filtered

        # ─── 3. ПАКЕТНАЯ НАРЕЗКА ПАТЧЕЙ ───────────────────────────
        cropped_patches = _batch_crop_defects_for_yolo(frame_original, defects)

        if not cropped_patches:
            return 0, [], frame_filtered

        # ─── 4. НЕЙРОСЕТЬ + ПОСТОБРАБОТКА ─────────────────────────
        defect_count, processed_frame = _process_cutting_error_frame(
            frame_original=frame_original,
            frame_filtered=frame_filtered,
            cropped_frame_list=cropped_patches,
            defects=defects,
            model_dict=defect_model,
            lime_mask=lime_mask,
            batch_size=batch_size
        )

        if defect_count > 0:
            defects_info.append({
                'key': model_key,
                'name': model_name,
                'color': model_color,
                'count': defect_count
            })
            total_defect_count = defect_count

        logger.debug(f"Полное время: {time.time() - total_start:.3f}с")

        # ─── 5. ОТЛАДОЧНАЯ ОТРИСОВКА ──────────────────────────────
        if debug and lime_mask is not None and lime_mask.any():
            frame_filtered = _draw_lime_border_with_gap_lines(
                frame_filtered,
                lime_mask,
                defects,
                color=(0, 255, 0),
                alpha=1.0,
                gap_line_color=(127, 255, 0),
                gap_line_thickness=1,
                skeletonize=True
            )

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            save_frame(
                frame=frame_filtered,
                filename=f"С_фильтрами_{timestamp}.jpg",
                dir_save=Path(r"C:\Users\user\Desktop\С_фильтрами")
            )

        if total_defect_count > 0:
            return total_defect_count, defects_info, (
                processed_frame if processed_frame is not None else frame_filtered
            )
        else:
            return 0, [], frame_filtered

    except Exception as e:
        logger.error(f"Ошибка при поиске дефекта Ошибка реза: {e}")
        return 0, [], frame_filtered
