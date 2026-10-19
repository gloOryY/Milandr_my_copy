import math
import time
from typing import Optional
from project.configuration.config_manager import ConfigManager
from project.station.robot.robot_controller import RobotController
from project.application.addition.logger import logger


DEFAULT_FIXED_DELAY_SEC: float = 0.2

def move_robot_to_coordinates(robot: 'RobotController',
                              config: 'ConfigManager',
                              x: Optional[float] = None,
                              y: Optional[float] = None,
                              z: Optional[float] = None,
                              apply_delay: bool = True) -> None:
    """
    Перемещение манипулятора.

    Логика задержки:
    - если apply_delay=False — задержки нет;
    - если apply_delay=True — фиксированная задержка 0.2 с.
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

    robot.move_to_coordinates(x=x, y=y, z=z, feed_rate=2000)

    config.current_coordinates = {"x": x, "y": y, "z": z}

    if not apply_delay:
        logger.debug("apply_delay=False — задержка не применяется")
        return

    time.sleep(DEFAULT_FIXED_DELAY_SEC)


def robot_to_home(robot: 'RobotController',
                  config: 'ConfigManager',
                  apply_delay: bool = True) -> None:
    """
    Возврат манипулятора в домашние координаты.
    """
    robot.home()

    config.current_coordinates = {"x": 0, "y": 0, "z": 0}

    if not apply_delay:
        return

    time.sleep(DEFAULT_FIXED_DELAY_SEC)

def apply_user_delay(config: 'ConfigManager') -> None:
    """
    Принудительная задержка перед финальным фото.
    Используется только отдельно, не внутри обычных перемещений.
    """
    params = getattr(config, "delay_params", None) or {}

    try:
        delay_sec = float(params.get("user_delay_sec", 0.0))
    except (TypeError, ValueError):
        delay_sec = 0.0

    if delay_sec > 0:
        time.sleep(delay_sec)