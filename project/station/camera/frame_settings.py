import cv2
import json
import numpy as np
from PIL import Image, ImageEnhance
from pathlib import Path
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


# Файл создаётся рядом с этим модулем: project/station/camera/filter_presets.json
_FILTER_PRESETS_PATH = Path(__file__).with_name("filter_presets.json")
_FILTER_PARAMETER_KEYS = (
    "brightness", "contrast", "saturation", "grain_level",
    "red_filter", "green_filter", "blue_filter",
)

def load_filter_presets() -> dict[str, dict[str, int]]:
    """Возвращает корректные именованные конфигурации фильтров из JSON."""
    if not _FILTER_PRESETS_PATH.exists():
        return {}
    try:
        with _FILTER_PRESETS_PATH.open("r", encoding="utf-8") as file:
            raw_presets = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw_presets, dict):
        return {}
    presets = {}
    for name, values in raw_presets.items():
        if not isinstance(name, str) or not isinstance(values, dict):
            continue
        try:
            preset = {key: int(values[key]) for key in _FILTER_PARAMETER_KEYS}
        except (KeyError, TypeError, ValueError):
            continue
        if all(0 <= value <= 100 for value in preset.values()):
            presets[name] = preset
    return presets

def save_filter_preset(name: str, values: dict[str, int]) -> None:
    """Сохраняет или перезаписывает именованную конфигурацию в JSON-файле."""
    name = name.strip()
    if not name:
        raise ValueError("Название конфигурации не может быть пустым")
    preset = {key: int(values[key]) for key in _FILTER_PARAMETER_KEYS}
    if not all(0 <= value <= 100 for value in preset.values()):
        raise ValueError("Значения фильтров должны находиться в диапазоне 0..100")

    presets = load_filter_presets()
    presets[name] = preset
    temp_path = _FILTER_PRESETS_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(presets, file, ensure_ascii=False, indent=2)
    temp_path.replace(_FILTER_PRESETS_PATH)