import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from project.application.addition.logger import logger

_CONFIG_FILE: str = "spacemouse_config.json"


@dataclass
class JogModeParams:
    """
    Параметры режима перемещения.

    Attributes:
        step_scale (float): Масштаб шага при полном отклонении (мм/тик)
        z_scale (float): Замедление оси Z относительно XY (Z скорость / XY скорость)
        feed_mm_min (int): Максимальная скорость подачи при полном отклонении
        min_feed_mm_min (int): Минимальная скорость подачи при минимальном отклонении
        response_curve (float): Кривая отклика (1.0=линейная, 2.0=квадратичная)
    """
    step_scale: float = 0.5
    z_scale: float = 0.2
    feed_mm_min: int = 4500
    min_feed_mm_min: int = 300
    response_curve: float = 2.5

    @classmethod
    def from_dict(cls, data: Dict) -> 'JogModeParams':
        """Создаёт параметры из словаря."""
        return cls(
            step_scale=float(data.get("step_scale", cls.step_scale)),
            z_scale=float(data.get("z_scale", cls.z_scale)),
            feed_mm_min=int(data.get("feed_mm_min", cls.feed_mm_min)),
            min_feed_mm_min=int(data.get("min_feed_mm_min", cls.min_feed_mm_min)),
            response_curve=float(data.get("response_curve", cls.response_curve)),
        )


@dataclass
class SpaceMouseSettings:
    """
    Настройки SpaceMouse.

    Attributes:
        enabled (bool): Включено ли устройство
        deadzone (float): Мёртвая зона (0.0 .. 1.0)
        poll_interval_ms (int): Интервал опроса в миллисекундах
        default_mode (str): Режим по умолчанию ("precise" или "rapid")
        precise_mode (JogModeParams): Параметры точного режима
        rapid_mode (JogModeParams): Параметры быстрого режима
    """
    enabled: bool = True
    deadzone: float = 0.15
    poll_interval_ms: int = 20
    default_mode: str = "rapid"

    precise_mode: JogModeParams = field(default_factory=lambda: JogModeParams(
        step_scale=0.5,
        feed_mm_min=4500,
        min_feed_mm_min=300,
        response_curve=2.5,
    ))
    rapid_mode: JogModeParams = field(default_factory=lambda: JogModeParams(
        step_scale=8.0,
        feed_mm_min=15000,
        min_feed_mm_min=3000,
        response_curve=1.2,
    ))

    @classmethod
    def from_dict(cls, data: Dict) -> 'SpaceMouseSettings':
        """Создаёт настройки из словаря."""
        settings = cls()

        settings.enabled = bool(data.get("enabled", settings.enabled))
        settings.deadzone = float(data.get("deadzone", settings.deadzone))
        settings.poll_interval_ms = int(data.get("poll_interval_ms", settings.poll_interval_ms))
        settings.default_mode = str(data.get("default_mode", settings.default_mode))

        if "precise_mode" in data and isinstance(data["precise_mode"], dict):
            settings.precise_mode = JogModeParams.from_dict(data["precise_mode"])

        if "rapid_mode" in data and isinstance(data["rapid_mode"], dict):
            settings.rapid_mode = JogModeParams.from_dict(data["rapid_mode"])

        return settings


class SpaceMouseConfig:
    """
    Управление конфигурацией SpaceMouse.
    """

    def __init__(self) -> None:
        """
        Инициализация менеджера конфигурации.
        Ищет JSON-файл в той же папке, где находится данный код.
        """
        current_dir = Path(__file__).resolve().parent
        self._config_path: Path = current_dir / _CONFIG_FILE
        self._settings: SpaceMouseSettings = self._load()

    def _load(self) -> SpaceMouseSettings:
        """
        Загружает настройки из JSON-файла.

        Returns:
            SpaceMouseSettings: Загруженные настройки или настройки по умолчанию
        """
        if not self._config_path.is_file():
            logger.debug(f"Файл конфигурации SpaceMouse не найден: {self._config_path}")
            return SpaceMouseSettings()

        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                return SpaceMouseSettings()

            return SpaceMouseSettings.from_dict(data)

        except Exception as e:
            logger.warning(f"Не удалось загрузить конфигурацию SpaceMouse: {e}")
            return SpaceMouseSettings()

    @property
    def settings(self) -> SpaceMouseSettings:
        """Возвращает текущие настройки."""
        return self._settings


# Глобальный экземпляр конфигурации
spacemouse_config = SpaceMouseConfig()
