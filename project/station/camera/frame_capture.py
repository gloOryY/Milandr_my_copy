import cv2
import numpy as np
import base64
from typing import Optional, Tuple, Any
from project.station.camera.frame_process import set_sharpness
from project.station.camera.frame_settings import apply_settings_to_frame
from project.configuration.config_manager import ConfigManager
from project.application.addition.logger import logger
from project.application.addition.exceptions import CameraException


def capture_frame(cam: Any, AOI_mode: bool = False) -> Optional[np.ndarray]:
    """
    Читает кадр с камеры.

    Args:
        cam: Объект камеры (cv2.VideoCapture или Camera) для захвата изображения
        AOI_mode: Флаг режима AOI (блокировка второго потока данных с трансляции)

    Returns:
        Optional[np.ndarray]: Не кодированное изображение или None при ошибке

    Raises:
        CameraException: При ошибках работы с камерой
    """
    try:
        ret, frame = cam.read_AOI_fast() if AOI_mode else cam.read()
        if not ret:
            return None

        return frame

    except CameraException:
        raise

    except Exception as e:
        logger.error(f"Ошибка при захвате кадра: {e}")
        return None


def capture_frame_mock(
        photos_dir: str = None
) -> Optional[np.ndarray]:
    """
    Берёт случайный кадр из указанной директории (для тестирования без камеры).
    Если директория не указана, ищет папку 'photos' по пути Milandr/photos_debugging/photos.

    Args:
        photos_dir: Абсолютный путь к директории с фотографиями (если None - ищется в Milandr/photos_debugging/photos)

    Returns:
        Optional[np.ndarray]: Не кодированное изображение или None при ошибке
    """
    try:
        import random
        from pathlib import Path

        if photos_dir is None:
            current_file = Path(__file__).resolve()

            project_root = current_file
            for parent in current_file.parents:
                if parent.name == "Milandr":
                    project_root = parent
                    break

            photos_dir = project_root / "photos_debugging" / "photos"

            if not photos_dir.exists():
                photos_dir = Path.cwd() / "photos_debugging" / "photos"

            photos_dir = str(photos_dir)

        photos_path = Path(photos_dir)

        if not photos_path.exists():
            logger.error(f"Директория не найдена: {photos_dir}")
            return None

        logger.info(f"Поиск изображений в директории: {photos_dir}")

        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff']
        photo_files = []

        for ext in image_extensions:
            photo_files.extend(photos_path.glob(ext))
            photo_files.extend(photos_path.glob(ext.upper()))

        if not photo_files:
            logger.error(f"В директории {photos_dir} не найдено изображений")
            return None

        random_photo_path = random.choice(photo_files)

        frame = cv2.imread(str(random_photo_path))

        if frame is None:
            logger.error(f"Не удалось прочитать изображение из файла: {random_photo_path}")
            return None

        logger.info(f"Кадр успешно загружен: {random_photo_path.name} из {photos_dir}")
        return frame

    except CameraException:
        raise

    except Exception as e:
        logger.error(f"Ошибка при захвате кадра из директории: {e}")
        return None


def filter_frame(frame):
    """ Фильтрует изображение с определенными фильтрами. """
    return set_sharpness(frame)


def rotate_frame(frame: np.ndarray, rotate_angle: int = 270) -> np.ndarray:
    """
    Поворачивает изображение на указанный угол.

    Args:
        frame: Не кодированное изображение
        rotate_angle: Угол поворота (0, 90, 180, 270)

    Returns:
        np.ndarray: Повёрнутое изображение
    """
    if rotate_angle in [90, 180, 270]:
        if rotate_angle == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if rotate_angle == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if rotate_angle == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return frame


def get_base64_from_frame(frame: Optional[np.ndarray],
                          target_size: Optional[Tuple[int, int]] = None,
                          is_special_filter: bool = False,
                          config: Optional['ConfigManager'] = None,
                          rotate_angle: int = 270) -> Optional[str]:
    """
    Конвертирует изображение в base64 для отображения в Flet.

    Args:
        frame: Не кодированное изображение
        target_size: Целевой размер изображения (ширина, высота). Если None - изображение не изменяется
        is_special_filter: Флаг на применение готового фильтра изображения
        config: Экземпляр класса конфигураций
        rotate_angle: Угол поворота (0, 90, 180, 270)

    Returns:
        Optional[str]: Base64-кодированное изображение или None при ошибке

    Raises:
        CameraException: При ошибках работы с камерой
    """
    try:
        if frame is None:
            return None

        # Поворот изображения
        frame = rotate_frame(frame, rotate_angle)

        if is_special_filter:
            frame = set_sharpness(frame)

        if config is not None:
            frame = apply_settings_to_frame(frame, config)

        # Изменение размера
        if target_size is not None:
            target_width, target_height = target_size
            if target_width > 0 and target_height > 0:
                # Вычисляем новый размер с сохранением пропорций
                height, width = frame.shape[:2]
                width_ratio = target_width / width
                height_ratio = target_height / height
                ratio = min(width_ratio, height_ratio)

                new_width = int(width * ratio)
                new_height = int(height * ratio)

                # Уменьшаем frame для кодирования
                frame_for_encoding = cv2.resize(frame, (new_width, new_height))

                # Кодируем уменьшенное изображение с оптимальным качеством
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 100]
                _, buffer = cv2.imencode(".jpg", frame_for_encoding, encode_param)
            else:
                # Если размеры невалидные, кодируем оригинал
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 100]
                _, buffer = cv2.imencode(".jpg", frame, encode_param)
        else:
            # Если target_size не указан, кодируем оригинал
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 100]
            _, buffer = cv2.imencode(".jpg", frame, encode_param)

        # Кодируем в base64
        return base64.b64encode(buffer).decode('utf-8')

    except CameraException:
        raise

    except Exception as e:
        logger.error(f"Ошибка при захвате кадра: {e}")
        return None


def improve_frame(frame: Optional[np.ndarray],
                  is_bilateral_filter: bool = True,
                  is_unsharp_mask: bool = True) -> Optional[np.ndarray]:
    """
    Фильтрация кадра изображения для улучшения качества.

    Args:
        frame: Входной кадр изображения, который нужно обработать
        is_bilateral_filter: Применять ли билатеральный фильтр для уменьшения шума
        is_unsharp_mask: Применять ли маску для увеличения резкости

    Returns:
        Optional[np.ndarray]: Обработанный кадр изображения или None при ошибке
    """
    if frame is None or frame.size == 0:
        return frame

    # Билатеральный фильтр для уменьшения шума
    if is_bilateral_filter:
        frame = cv2.bilateralFilter(frame, d=5, sigmaColor=75, sigmaSpace=75)

    # Применение маски для увеличения резкости
    if is_unsharp_mask:
        frame = _unsharp_mask(frame, kernel_size=(5, 5), sigma=1.0, amount=1.5, threshold=0)

    return frame


def _unsharp_mask(image: np.ndarray,
                  kernel_size: Tuple[int, int] = (5, 5),
                  sigma: float = 1.0,
                  amount: float = 1.0,
                  threshold: int = 0) -> np.ndarray:
    """
    Улучшение изображения за счёт повышения резкости (фильтр сглаживания по Гауссу).

    Args:
        image: Входное изображение в формате numpy.ndarray
        kernel_size: Размер ядра для размытия по Гауссу
        sigma: Стандартное отклонение для размытия по Гауссу
        amount: Степень повышения резкости
        threshold: Порог для маски низкой контрастности

    Returns:
        np.ndarray: Изображение с повышенной резкостью
    """
    # Применение размытия по Гауссу
    blurred = cv2.GaussianBlur(image, kernel_size, sigma)

    sharpened = float(amount + 1) * image - float(amount) * blurred
    sharpened = np.maximum(sharpened, np.zeros(sharpened.shape))
    sharpened = np.minimum(sharpened, 255 * np.ones(sharpened.shape))
    sharpened = sharpened.round().astype(np.uint8)
    if threshold > 0:
        low_contrast_mask = np.absolute(image - blurred) < threshold
        np.copyto(sharpened, image, where=low_contrast_mask)

    return sharpened
