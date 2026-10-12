import math
import time
from typing import Optional
from project.configuration.config_manager import ConfigManager
from project.station.robot.robot_controller import RobotController
from project.application.addition.logger import logger


# Порог расстояния по XY (мм)
DEFAULT_DISTANCE_THRESHOLD_XY_MM_FOR_DELAY: float = 5.0

# Порог расстояния по Z (мм)
DEFAULT_DISTANCE_THRESHOLD_Z_MM_FOR_DELAY: float = 0.5

# Скорость роста задержки по XY (сек на каждый мм сверх порога)
DEFAULT_DELAY_GROWTH_XY_SEC_PER_MM: float = 0.5

# Скорость роста задержки по Z (сек на каждый мм сверх порога)
DEFAULT_DELAY_GROWTH_Z_SEC_PER_MM: float = 0.5

# Минимальная адаптивная задержка (сек)
DEFAULT_MIN_ADAPTIVE_DELAY_SEC: float = 0.5

# Максимально возможная адаптивная задержка (сек).
DEFAULT_MAX_ADAPTIVE_DELAY_SEC: float = 5.0

# Принудительная базовая задержка после перемещения (сек).
DEFAULT_POST_MOVE_DELAY_SEC: float = 0.0


def _get_delay_params(config: 'ConfigManager') -> dict:
    """
    Возвращает актуальные параметры задержки из config.delay_params
    с fallback на значения по умолчанию.

    Возвращает словарь с ключами:
        - distance_threshold_xy_mm_for_delay
        - distance_threshold_z_mm_for_delay
        - delay_growth_xy_sec_per_mm       (рост по XY)
        - delay_growth_z_sec_per_mm     (рост по Z)
        - post_move_delay_sec
        - min_adaptive_delay_sec
        - max_adaptive_delay_sec
    """
    params = getattr(config, "delay_params", None) or {}

    return {
        "distance_threshold_xy_mm_for_delay": params.get(
            "distance_threshold_xy_mm_for_delay",
            DEFAULT_DISTANCE_THRESHOLD_XY_MM_FOR_DELAY
        ),
        "distance_threshold_z_mm_for_delay": params.get(
            "distance_threshold_z_mm_for_delay",
            DEFAULT_DISTANCE_THRESHOLD_Z_MM_FOR_DELAY
        ),
        # Рост по XY — старый ключ delay_growth_xy_sec_per_mm
        "delay_growth_xy_sec_per_mm": params.get(
            "delay_growth_xy_sec_per_mm",
            DEFAULT_DELAY_GROWTH_XY_SEC_PER_MM
        ),
        # Рост по Z — новый ключ; если его нет, используется тот же, что и по XY
        "delay_growth_z_sec_per_mm": params.get(
            "delay_growth_z_sec_per_mm",
            params.get("delay_growth_xy_sec_per_mm", DEFAULT_DELAY_GROWTH_Z_SEC_PER_MM)
        ),
        "post_move_delay_sec": params.get(
            "post_move_delay_sec",
            DEFAULT_POST_MOVE_DELAY_SEC
        ),
        "min_adaptive_delay_sec": params.get(
            "min_adaptive_delay_sec",
            DEFAULT_MIN_ADAPTIVE_DELAY_SEC
        ),
        "max_adaptive_delay_sec": params.get(
            "max_adaptive_delay_sec",
            DEFAULT_MAX_ADAPTIVE_DELAY_SEC
        ),
    }


def _calculate_delay_multiplier(distance_mm: float,
                                threshold_mm: float,
                                growth_sec_per_mm: float) -> float:
    """
    Коэффициент масштабирования задержки в зависимости от пройденного расстояния
    и порога для данной оси/плоскости.

    - distance <= threshold → 1.0
    - distance > threshold → 1.0 + (distance - threshold) * growth_sec_per_mm
    """
    if distance_mm < threshold_mm:
        return 1.0

    excess = distance_mm - threshold_mm
    return 1.0 + excess * growth_sec_per_mm


def move_robot_to_coordinates(robot: 'RobotController',
                              config: 'ConfigManager',
                              x: Optional[float] = None,
                              y: Optional[float] = None,
                              z: Optional[float] = None,
                              apply_delay: bool = True) -> None:
    """
    Отправляет команду перемещения манипулятора к указанным координатам.

    Логика задержки после перемещения:
    - Если apply_delay=False → задержка НЕ применяется вообще.
    - Если apply_delay=True:
        - Считается адаптивная задержка:
          base_delay = min_adaptive_delay_sec,
          multiplier_xy считается по XY с growth_xy_sec_per_mm,
          multiplier_z считается по Z с growth_z_sec_per_mm,
          берётся max(multiplier_xy, multiplier_z),
          adaptive_delay = base_delay × multiplier,
          adaptive_delay ограничивается сверху max_adaptive_delay_sec.
          Применяется ТОЛЬКО если расстояние превышает порог (XY или Z).
        - Если post_move_delay_sec > 0:
          → используется max(post_move_delay_sec, adaptive_delay).

    Args:
        robot: Экземпляр класса робота
        config: Экземпляр класса конфигураций
        x: Координата X (опционально, если None - берётся из config)
        y: Координата Y (опционально, если None - берётся из config)
        z: Координата Z (опционально, если None - берётся из config)
        apply_delay: Применять ли задержку вообще. По умолчанию True.

    Raises:
        RobotException: Если произошла ошибка при перемещении робота
    """

    if x is None and y is None and z is None:
        return

    ROUND_NUMBER = 2
    if x is None:
        x = config.current_coordinates["x"]
    if y is None:
        y = config.current_coordinates["y"]
    if z is None:
        z = config.current_coordinates["z"]

    x = round(x, ROUND_NUMBER)
    y = round(y, ROUND_NUMBER)
    z = round(z, ROUND_NUMBER)

    old_x = config.current_coordinates["x"]
    old_y = config.current_coordinates["y"]
    old_z = config.current_coordinates["z"]

    dx = x - old_x
    dy = y - old_y
    dz = z - old_z

    distance_xy = math.sqrt(dx ** 2 + dy ** 2)
    distance_z = abs(dz)
    distance_full = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)

    robot.move_to_coordinates(x=x, y=y, z=z, feed_rate=2000)
    config.current_coordinates = {"x": x, "y": y, "z": z}

    if not apply_delay:
        logger.debug("apply_delay=False — задержка не применяется")
        return

    params = _get_delay_params(config)

    threshold_xy_mm = params["distance_threshold_xy_mm_for_delay"]
    threshold_z_mm = params["distance_threshold_z_mm_for_delay"]
    growth_xy_sec_per_mm = params["delay_growth_xy_sec_per_mm"]
    growth_z_sec_per_mm = params["delay_growth_z_sec_per_mm"]
    post_move_delay_sec = params["post_move_delay_sec"]
    min_adaptive_delay_sec = params["min_adaptive_delay_sec"]
    max_adaptive_delay_sec = params["max_adaptive_delay_sec"]

    # === Считаем адаптивную задержку ===
    adaptive_delay_sec = 0.0

    if distance_xy > threshold_xy_mm or distance_z >= threshold_z_mm:
        if distance_full > 0 and min_adaptive_delay_sec > 0:
            multiplier_xy = _calculate_delay_multiplier(
                distance_xy, threshold_xy_mm, growth_xy_sec_per_mm
            )
            multiplier_z = _calculate_delay_multiplier(
                distance_z, threshold_z_mm, growth_z_sec_per_mm
            )
            multiplier = max(multiplier_xy, multiplier_z)

            adaptive_raw = min_adaptive_delay_sec * multiplier
            adaptive_delay_sec = min(adaptive_raw, max_adaptive_delay_sec)

            logger.debug(
                "Адаптивная задержка: base=%.3f сек, "
                "XY=%.3f мм (рост=%.3f, ×%.2f), "
                "Z=%.3f мм (рост=%.3f, ×%.2f), "
                "multiplier=%.2f, raw=%.3f сек, cap=%.3f сек, adaptive=%.3f сек",
                min_adaptive_delay_sec,
                distance_xy, growth_xy_sec_per_mm, multiplier_xy,
                distance_z, growth_z_sec_per_mm, multiplier_z,
                multiplier, adaptive_raw,
                max_adaptive_delay_sec, adaptive_delay_sec,
            )

    # === Выбираем итоговую задержку ===
    if post_move_delay_sec > 0:
        actual_delay_sec = max(post_move_delay_sec, adaptive_delay_sec)
        logger.debug(
            "Задержка: принудительная=%.3f сек, адаптивная=%.3f сек, "
            "выбрана=%.3f сек (перемещение в [%s; %s; %s])",
            post_move_delay_sec, adaptive_delay_sec, actual_delay_sec, x, y, z,
        )
    elif adaptive_delay_sec > 0:
        actual_delay_sec = adaptive_delay_sec
        logger.debug(
            "Применена адаптивная задержка: %.3f сек (перемещение в [%s; %s; %s])",
            actual_delay_sec, x, y, z,
        )
    else:
        logger.debug("Задержка не применялась!")
        return

    time.sleep(actual_delay_sec)


def robot_to_home(robot: 'RobotController',
                  config: 'ConfigManager',
                  apply_delay: bool = True) -> None:
    """
    Отправляет команду перемещения манипулятора в домашние координаты.

    Args:
        robot: Экземпляр класса робота
        config: Экземпляр класса конфигураций
        apply_delay: Применять ли задержку вообще. По умолчанию True.
                     Если False — задержка не применяется.

    Raises:
        RobotException: Если произошла ошибка при перемещении робота в домашнее положение
    """
    robot.home()
    config.current_coordinates = {"x": 0, "y": 0, "z": 0}

    if not apply_delay:
        return

    params = _get_delay_params(config)
    post_move_delay_sec = params["post_move_delay_sec"]

    if post_move_delay_sec > 0:
        time.sleep(post_move_delay_sec)