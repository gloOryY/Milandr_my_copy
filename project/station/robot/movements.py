from typing import Optional
from project.configuration.config_manager import ConfigManager
from project.station.robot.robot_controller import RobotController
from project.application.addition.exceptions import RobotException
from project.application.addition.logger import logger


def move_robot_to_coordinates(robot: 'RobotController',
                              config: 'ConfigManager',
                              x: Optional[float] = None,
                              y: Optional[float] = None,
                              z: Optional[float] = None) -> None:
    """
    Отправляет команду перемещения манипулятора к указанным координатам.

    Если координата не указана, используется текущее значение из конфигурации.
    Координаты округляются до 2 знаков после запятой перед отправкой.

    Args:
        robot: Экземпляр класса робота
        config: Экземпляр класса конфигураций
        x: Координата X (опционально, если None - берется из config)
        y: Координата Y (опционально, если None - берется из config)
        z: Координата Z (опционально, если None - берется из config)

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

    robot.move_to_coordinates(x=x, y=y, z=z, feed_rate=2000)
    config.current_coordinates = {"x": x, "y": y, "z": z}


def robot_to_home(robot: 'RobotController', config: 'ConfigManager') -> None:
    """
    Отправляет команду перемещения манипулятора в домашние координаты.

    Args:
        robot: Экземпляр класса робота
        config: Экземпляр класса конфигураций

    Returns:
        bool: True если команда отправлена успешно

    Raises:
        RobotException: Если произошла ошибка при перемещении робота в домашнее положение
    """
    robot.home()
    config.current_coordinates = {"x": 0, "y": 0, "z": 0}
