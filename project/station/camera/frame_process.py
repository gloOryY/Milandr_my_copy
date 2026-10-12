import cv2
import numpy as np
from PIL import Image, ImageEnhance
from pathlib import Path
from typing import Optional

from project.application.addition.logger import logger


def get_sharpness_fast(frame: Optional[np.ndarray],
                       max_size: int = 800,
                       lo_thresh: int = 15,
                       hi_thresh: int = 240,
                       sobel_ksize: int = 3) -> float:
    """
    Сбалансированная оценка резкости: быстро, по методу Тененграда с простой маской
    Время работы: обычно < 5 мс для стандартных разрешений.

    Args:
        frame:        Входное изображение (BGR или grayscale).
        max_size:     Макс. размер по большей стороне, px (800).
        lo_thresh:    Нижний порог яркости для маски (15).
        hi_thresh:    Верхний порог яркости для маски (240).
        sobel_ksize:  Размер ядра Собеля (3).

    Returns:
        float: Резкость по Тененграду (выше = резче), 0.0 при ошибке.
    """
    if frame is None or frame.size == 0:
        return 0.0

    try:
        # Приводим к серому и уменьшаем для скорости
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        h, w = gray.shape[:2]
        scale = max_size / max(h, w)
        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Быстрая маска: исключаем пересветы и глубокие тени
        mask = (gray > lo_thresh) & (gray < hi_thresh)

        # Если маска пуста (всё изображение вне диапазона), вернём 0
        if not np.any(mask):
            return 0.0

        # Тененград (gx² + gy²) только по маске
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=sobel_ksize)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=sobel_ksize)
        mag2 = gx * gx + gy * gy

        vals = mag2[mask]
        return float(np.mean(vals)) if vals.size > 0 else 0.0

    except Exception as e:
        print(f"Ошибка при вычислении резкости: {e}")
        return 0.0


def get_sharpness_exact(frame: Optional[np.ndarray]) -> float:
    """
    Определяет уровень резкости изображения методом Тененграда с маской.

    Args:
        frame: Изображение в формате numpy array (BGR или grayscale)

    Returns:
        float: Значение резкости (чем выше - тем резче). Возвращает 0.0 при ошибке.
    """

    def _make_mask(gray: np.ndarray,
                   satur_upper_pct: float = 0.99,
                   satur_lower_pct: float = 0.01,
                   use_edges: bool = True,
                   dilate_px: int = 1) -> np.ndarray:
        """
        Создает маску для исключения бликов, провалов и отбора информативных пикселей.

        Маска создается на основе:
        1. Исключения слишком темных и слишком светлых пикселей (квантили)
        2. Опционально - на основе границ (Canny) для выделения структур

        Args:
            gray: Изображение в оттенках серого (numpy array)
            satur_upper_pct: Верхний квантиль для исключения бликов (0.99 = исключаем 1% самых ярких)
            satur_lower_pct: Нижний квантиль для исключения теней (0.01 = исключаем 1% самых темных)
            use_edges: Использовать границы (Canny) для создания маски
            dilate_px: Радиус дилатации границ (расширение области границ)

        Returns:
            np.ndarray: Бинарная маска (uint8, 0 - фон, 1 - область интереса)
        """
        q_hi = np.quantile(gray, satur_upper_pct)
        q_lo = np.quantile(gray, satur_lower_pct)
        base = (gray > q_lo) & (gray < q_hi)

        if use_edges:
            blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
            th_val, th_img = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            lo = max(10, int(0.5 * float(th_val)))
            hi = max(20, int(1.5 * float(th_val)))
            edges = cv2.Canny(gray, lo, hi, L2gradient=True)

            if dilate_px > 0:
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * dilate_px + 1, 2 * dilate_px + 1))
                edges = cv2.dilate(edges, k)

            edge_mask = edges > 0
            base &= edge_mask

        return base.astype(np.uint8)

    if frame is None or frame.size == 0:
        return 0.0

    try:
        # Преобразуем в оттенки серого, если необходимо
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Создаем маску для исключения бликов и фона
        mask = _make_mask(gray, use_edges=True, dilate_px=1)

        # Метод Тененграда с маской (на основе градиентов Собеля)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag2 = gx * gx + gy * gy

        # Используем маску, если она не пустая
        if mask is not None and np.any(mask > 0):
            tenengrad_vals = mag2[mask > 0]
        else:
            tenengrad_vals = mag2.ravel()

        # Возвращаем среднее значение градиентов
        return float(np.mean(tenengrad_vals)) if tenengrad_vals.size else 0.0

    except Exception as e:
        print(f"Ошибка при вычислении резкости: {e}")
        return 0.0


def get_exposure(frame: Optional[np.ndarray]) -> float:
    """
    Определяет степень экспозиции кадра.

    Args:
        frame: Изображение в формате numpy array (BGR)

    Returns:
        float: Значение от 0 (полная темнота) до 100 (полный пересвет)
    """
    if frame is None or frame.size == 0:
        return 0.0

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = np.mean(gray)  # Средняя яркость (0-255)
    exposure_level = (mean_brightness / 255) * 100

    return float(exposure_level)


def set_sharpness(frame: np.ndarray, sharpness_factor: float = 30) -> np.ndarray:
    """
    Изменяет уровень резкости у изображения.

    Args:
        frame: Изображение в формате numpy array (BGR)
        sharpness_factor: Целевой параметр резкости

    Returns:
        np.ndarray: Отфильтрованное по резкости изображение (BGR)
    """
    try:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(frame_rgb)
        enhancer = ImageEnhance.Sharpness(pil_image)
        sharpened_image = enhancer.enhance(sharpness_factor)
        return cv2.cvtColor(np.array(sharpened_image), cv2.COLOR_RGB2BGR)
    except Exception as e:
        print(f"Ошибка обработки кадра: {e}")
        return frame


def save_frame(frame: Optional[np.ndarray],
               filename: str,
               dir_save: Optional[Path]) -> bool:
    """
    Сохраняет кадр для отладки.

    Args:
        frame: Изображение для сохранения
        filename: Имя файла
        dir_save: Директория для сохранения

    Returns:
        bool: True если сохранение успешно
    """
    try:
        file_path = dir_save / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.suffix.lower() in ['.jpg', '.jpeg']:
            success = cv2.imwrite(str(file_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
        else:
            success = cv2.imwrite(str(file_path), frame)

        if success:
            logger.debug(f"Фото сохранено: {file_path}")
        else:
            logger.warning(f"Фото НЕ сохранено: {file_path}")

        return success
    except Exception as e:
        logger.error(f"Ошибка сохранения отладочного фото {filename}: {e}")
        return False



