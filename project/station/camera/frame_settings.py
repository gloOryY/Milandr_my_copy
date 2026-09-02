import cv2
import numpy as np
from PIL import Image, ImageEnhance
from project.configuration.config_manager import ConfigManager


def apply_settings_to_frame(frame: np.ndarray, config: 'ConfigManager') -> np.ndarray:
    """
    Применяет следующие фильтры к изображению из конфигурации:
    - Яркость (brightness)
    - Контрастность (contrast)
    - Насыщенность (saturation)
    - Резкость/зернистость (grain_level)
    - Цветовые фильтры по каналам (red_filter, green_filter, blue_filter)

    Args:
        frame: Исходное изображение в формате BGR (numpy array)
        config: Экземпляр класса конфигураций

    Returns:
        np.ndarray: Обработанное изображение в формате BGR
    """
    params = config.picture_parameters

    # Предварительная конвертация только если нужна
    need_pil = any([
        params["brightness"] != 50,
        params["contrast"] != 50,
        params["saturation"] != 50,
        params["grain_level"] != 50
    ])

    if need_pil:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame)

        if params["brightness"] != 50:
            image = ImageEnhance.Brightness(image).enhance(params["brightness"] / 50)

        if params["contrast"] != 50:
            image = ImageEnhance.Contrast(image).enhance(params["contrast"] / 50)

        if params["saturation"] != 50:
            image = ImageEnhance.Color(image).enhance(params["saturation"] / 50)

        if params["grain_level"] != 50:
            image = ImageEnhance.Sharpness(image).enhance(params["grain_level"] / 50)

        frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    # Цветовые фильтры (всегда эффективны)
    if any([params["red_filter"] != 100, params["green_filter"] != 100, params["blue_filter"] != 100]):
        frame = frame.astype(np.float32)
        frame[:, :, 0] *= params["blue_filter"] / 100
        frame[:, :, 1] *= params["green_filter"] / 100
        frame[:, :, 2] *= params["red_filter"] / 100
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    return frame
