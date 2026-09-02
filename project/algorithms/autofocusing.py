import numpy as np
from typing import Optional, Tuple, Dict, List, Union

from project.station.camera.frame_capture import capture_frame
from project.station.camera.frame_process import get_sharpness_fast
from project.station.robot.movements import move_robot_to_coordinates
from project.configuration.config_manager import ConfigManager
from project.station.camera.camera_manager import CameraGXIPY
from project.station.robot.robot_controller import RobotController
from project.application.addition.exceptions import RobotException, KnownSystemException
from project.application.addition.logger import logger

MAX_DIFFERENCE_PERCENT: int = 30


def _autofocusing(robot: 'RobotController',
                  camera: 'CameraGXIPY',
                  config: 'ConfigManager',
                  z_start: float,
                  step_move: float,
                  direction: int,
                  global_data: Optional[Dict[float, Tuple[float, np.ndarray]]] = None
                  ) -> Tuple[float, float, Optional[np.ndarray]]:
    """
    Ядро алгоритма автофокусировки.
    Выполняет поиск оптимальной координаты Z с максимальной резкостью изображения.

    Args:
        robot: Экземпляр класса робота
        camera: Объект камеры (CameraGXIPY) для захвата кадров
        config: Экземпляр класса конфигураций
        z_start: Начальная координата Z для движения
        step_move: Шаг перемещения при автофокусировке
        direction: Направление движения робота (1 - вверх, -1 - вниз)
        global_data: Опциональный словарь для сбора всех измерений (Z -> (резкость, кадр)).

    Returns:
        Tuple[float, float, Optional[np.ndarray]]: Кортеж из:
            - z_best: Координата Z с лучшей резкостью
            - sharpness_best: Лучший уровень резкости изображения
            - frame: Оригинальное изображение с лучшей резкостью

    Raises:
        KnownSystemException: При невозможности выполнить автофокусировку
    """
    sharpness_dict: Dict[float, float] = {}
    prev_sharpness: Optional[float] = None
    z_current: float = z_start
    improvement_threshold: float = 1.1

    while True:
        move_robot_to_coordinates(robot=robot, config=config, z=z_current)
        frame = capture_frame(cam=camera, AOI_mode=True)
        sharpness_current = get_sharpness_fast(frame)
        sharpness_dict[z_current] = sharpness_current
        if global_data is not None:
            global_data[z_current] = (sharpness_current, frame)

        if (prev_sharpness is not None and sharpness_current > 0 and
                prev_sharpness / sharpness_current > improvement_threshold):
            break

        prev_sharpness = sharpness_current
        z_current += step_move * direction

    points: List[Tuple[float, float]] = sorted(sharpness_dict.items(), key=lambda x: x[0])
    num_points: int = len(points)

    if num_points < 2:
        error_message = "Автофокусировка невозможна из-за недостатка фокусных точек"
        logger.error(error_message)
        raise KnownSystemException(message=error_message)

    # Находим точку с максимальной резкостью
    all_sharpness: Dict[float, float] = dict(points)
    best_z_position: float = max(all_sharpness, key=all_sharpness.get)
    sharpness_best: float = all_sharpness[best_z_position]
    best_index: int = points.index((best_z_position, sharpness_best))

    def calculate_mid_value() -> Tuple[float, float]:
        """ Вычисляет резкость в середине отрезка. """
        mid_z = round((z1 + z2) / 2, 2)
        move_robot_to_coordinates(robot=robot, config=config, z=mid_z)
        frame = capture_frame(cam=camera, AOI_mode=True)
        mid_sharpness = get_sharpness_fast(frame)

        if global_data is not None:
            global_data[mid_z] = (mid_sharpness, frame)
        return mid_z, mid_sharpness

    if num_points == 2:
        # Всего 2 точки
        z1, s1 = points[0]
        z2, s2 = points[1]

        # Определяем границы
        start_z, end_z = sorted([z1, z2])
        start_sharpness = s1 if start_z == z1 else s2
        end_sharpness = s2 if end_z == z2 else s1
        mid_z, mid_sharpness = calculate_mid_value()

    elif best_index == 0:
        # Лучшая точка - первая, есть только правый сосед
        z1, s1 = points[0]  # лучшая
        z2, s2 = points[1]  # правый сосед

        start_z, end_z = z1, z2
        start_sharpness, end_sharpness = s1, s2
        mid_z, mid_sharpness = calculate_mid_value()

    elif best_index == num_points - 1:
        # Лучшая точка - последняя, есть только левый сосед
        z1, s1 = points[-2]  # левый сосед
        z2, s2 = points[-1]  # лучшая

        start_z, end_z = z1, z2
        start_sharpness, end_sharpness = s1, s2
        mid_z, mid_sharpness = calculate_mid_value()

    else:
        # Лучшая точка где-то посередине - есть оба соседа
        z_left, s_left = points[best_index - 1]
        z_best, s_best = points[best_index]
        z_right, s_right = points[best_index + 1]

        start_z, mid_z, end_z = z_left, z_best, z_right
        start_sharpness, mid_sharpness, end_sharpness = s_left, s_best, s_right

    tolerance: float = 0.01
    improvement_threshold = 1.3

    # Инициализируем sharpness_dict начальными значениями
    sharpness_dict = {
        start_z: start_sharpness,
        mid_z: mid_sharpness,
        end_z: end_sharpness
    }

    # Переменная для хранения текущего кадра (может быть обновлена в measure_sharpness)
    best_frame: Optional[np.ndarray] = None

    def measure_sharpness(z: float) -> float:
        """ Измеряет резкость в заданной координате Z. """
        nonlocal best_frame
        z = round(z, 2)
        if z in sharpness_dict:
            return sharpness_dict[z]

        # Перемещение и измерение
        move_robot_to_coordinates(robot=robot, config=config, z=z)

        frame = capture_frame(cam=camera, AOI_mode=True)
        sharpness = get_sharpness_fast(frame)

        sharpness_dict[z] = sharpness
        if global_data is not None:
            global_data[z] = (sharpness, frame)
        best_frame = frame  # сохраняем последний захваченный кадр
        return sharpness

    while True:
        segment_length = abs(end_z - start_z)
        if segment_length <= 2 * tolerance:
            z_best = max(sharpness_dict, key=sharpness_dict.get)
            sharpness_best = sharpness_dict[z_best]
            # Возвращаем кадр, соответствующий лучшей точке, если он имеется
            if global_data and z_best in global_data:
                _, best_frame = global_data[z_best]
            return z_best, sharpness_best, best_frame

        current_points = sorted([start_z, mid_z, end_z])
        sharpness_values = {z: sharpness_dict[z] for z in current_points}

        # Получаем значения резкости для крайних точек
        start_sharpness = sharpness_values[start_z]
        end_sharpness = sharpness_values[end_z]

        # Находим, какая из крайних точек имеет большее значение
        if start_sharpness >= end_sharpness:
            higher_z, higher_sharpness = start_z, start_sharpness
            lower_z, lower_sharpness = end_z, end_sharpness
        else:
            higher_z, higher_sharpness = end_z, end_sharpness
            lower_z, lower_sharpness = start_z, start_sharpness

        if lower_sharpness > 0 and higher_sharpness / lower_sharpness > improvement_threshold:
            # Разница более 30% - выбираем отрезок с большим значением
            if higher_z == start_z:
                new_start = start_z
                new_end = mid_z
                new_mid = round(start_z + (mid_z - start_z) / 2, 2)
            else:
                new_start = mid_z
                new_end = end_z
                new_mid = round(mid_z + (end_z - mid_z) / 2, 2)

            measure_sharpness(new_mid)  # Измеряем резкость в новой серединной точке

        else:  # Разница менее 30% - делим оба отрезка
            # Делим левый отрезок
            left_mid = round(start_z + (mid_z - start_z) / 2, 2)
            left_sharpness = measure_sharpness(left_mid)

            # Делим правый отрезок
            right_mid = round(mid_z + (end_z - mid_z) / 2, 2)
            right_sharpness = measure_sharpness(right_mid)

            # Выбираем отрезок с лучшей резкостью в серединной точке
            if left_sharpness > right_sharpness:
                new_start, new_mid, new_end = start_z, left_mid, mid_z
            else:
                new_start, new_mid, new_end = mid_z, right_mid, end_z

        # Удаляем ненужные точки из словаря (оставляем только актуальные)
        keep_points = {new_start, new_mid, new_end}
        keys_to_remove = [k for k in sharpness_dict.keys() if k not in keep_points]
        for k in keys_to_remove:
            del sharpness_dict[k]

        # Обновляем точки для следующей итерации
        start_z, mid_z, end_z = new_start, new_mid, new_end


def autofocusing_extended(robot: 'RobotController',
                          camera: 'CameraGXIPY',
                          config: 'ConfigManager',
                          is_set_ideal_sharpness: bool = False,
                          z_calibration: Optional[float] = None,
                          z_range: float = 5,
                          step_move: float = 1,
                          global_data: Optional[Dict[float, Tuple[float, np.ndarray]]] = None,
                          is_compare_sharpness: bool = True,
                          ) -> Optional[Union[Tuple[float, np.ndarray], bool]]:
    """
    Расширенная автофокусировка с большим диапазоном поиска.

    Выполняет поиск оптимальной координаты Z в расширенном диапазоне.

    Args:
        robot: Экземпляр класса робота
        camera: Объект камеры (CameraGXIPY) для захвата кадров
        config: Экземпляр класса конфигураций
        is_set_ideal_sharpness: Флаг сохранения текущих параметров как идеальных
        z_calibration: Середина рабочей зоны центровки
        z_range: Радиус рабочей зоны центровки
        step_move: Шаг алгоритма автофокусировки
        global_data: Опциональный словарь для сбора всех измерений (Z -> (резкость, кадр)).
        is_compare_sharpness: Метка на сравнение резкостей

    Returns:
        Optional[Union[Tuple[float, np.ndarray], bool]]:
            - Если is_set_ideal_sharpness=True: True/False (установлена ли новая идеальная резкость)
            - Если is_set_ideal_sharpness=False: (sharpness_best, frame) или None при неудаче
    """
    # Определяем начальную позицию для автофокусировки
    if z_calibration is None:
        if config.current_coordinates["z"] != 0:
            z_initial = config.current_coordinates["z"]
        elif config.coordinate_of_the_first_cell["z"] != 0:
            z_initial = config.coordinate_of_the_first_cell["z"]
        else:
            z_initial = -75
    else:
        z_initial = z_calibration

    z_start = min(z_initial, config.extreme_coordinates.get("z_max", float('inf'))) + z_range

    frame = capture_frame(cam=camera, AOI_mode=True)
    sharpness_initial = get_sharpness_fast(frame)
    if global_data is not None:
        global_data[z_initial] = (sharpness_initial, frame)

    try:
        z_best, sharpness_best, frame = _autofocusing(
            robot=robot,
            camera=camera,
            config=config,
            z_start=z_start,
            step_move=step_move,
            direction=-1,
            global_data=global_data
        )

        if is_set_ideal_sharpness:
            return _set_ideal_sharpness(config=config, sharpness_current=sharpness_best)

        if is_compare_sharpness and sharpness_initial > sharpness_best:
            move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
            return None

        return sharpness_best, frame

    except (RobotException, KnownSystemException):
        if z_initial is not None:
            move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
        raise

    except Exception:
        if z_initial is not None:
            move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
        raise


def autofocusing_standard(robot: 'RobotController',
                          camera: 'CameraGXIPY',
                          config: 'ConfigManager',
                          is_set_ideal_sharpness: bool = False,
                          global_data: Optional[Dict[float, Tuple[float, np.ndarray]]] = None,
                          is_compare_sharpness: bool = True
                          ) -> Optional[Union[Tuple[float, np.ndarray], bool]]:
    """
    Стандартная автоматическая фокусировка.

    Выполняет фокусировку с определением направления движения.

    Args:
        robot: Экземпляр класса робота
        camera: Объект камеры (CameraGXIPY) для захвата кадров
        config: Экземпляр класса конфигураций
        is_set_ideal_sharpness: Флаг сохранения текущих параметров как идеальных
        global_data: Опциональный словарь для сбора всех измерений (Z -> (резкость, кадр)).
        is_compare_sharpness: Метка на сравнение резкостей

    Returns:
        Optional[Union[Tuple[float, np.ndarray], bool]]:
            - Если is_set_ideal_sharpness=True: True/False (установлена ли новая идеальная резкость)
            - Если is_set_ideal_sharpness=False: (sharpness_best, frame) или None при неудаче
    """
    if config.sharpness_ideal <= 0:
        return autofocusing_extended(robot=robot, camera=camera, config=config,
                                     global_data=global_data)

    def get_up_and_down_sharpness(increase_step: float) -> Tuple[float, float]:
        """
        Выполняет тестовые перемещения вверх и вниз для измерения уровня резкости.

        Args:
            increase_step: Шаг при определении нижней и верхней резкости изображения

        Returns:
            Tuple[float, float]: (резкость при движении вниз, резкость при движении вверх)
        """

        def get_sharpness_fast_for_direction(step_direction: int) -> float:
            """
            Получает резкость для заданного направления перемещения.

            Args:
                step_direction: 1 или -1 - направление перемещения

            Returns:
                float: Уровень резкости
            """
            step = increase_step * step_direction
            multiplier = 1

            while True:
                test_z = z_initial + step * multiplier

                # Проверяем границы
                z_min, z_max = config.extreme_coordinates["z_min"], config.extreme_coordinates["z_max"]
                if z_min < test_z < z_max:
                    break

                # Если шаг слишком маленький - ошибка
                if abs(step * multiplier) < 0.02:
                    direction_name = "верхней" if step_direction > 0 else "нижней"
                    error_msg = f"Камера слишком близко к предельной {direction_name} границе"
                    logger.error(error_msg)
                    result = autofocusing_extended(
                        robot=robot,
                        camera=camera,
                        config=config,
                        z_calibration=z_initial,
                        z_range=5,
                        step_move=0.5,
                        global_data=global_data
                    )
                    # Возвращаем резкость из расширенной автофокусировки или 0
                    if result and isinstance(result, tuple):
                        return result[0]
                    return 0

                multiplier /= 2

            # Перемещаем и измеряем резкость
            move_robot_to_coordinates(robot=robot, config=config, z=test_z)
            frame = capture_frame(cam=camera, AOI_mode=True)
            sharpness_val = get_sharpness_fast(frame)
            if global_data is not None:
                global_data[test_z] = (sharpness_val, frame)
            return sharpness_val

        # Возвращаем резкости для обоих направлений
        return get_sharpness_fast_for_direction(-1), get_sharpness_fast_for_direction(1)

    z_initial = config.current_coordinates["z"]

    frame = capture_frame(cam=camera, AOI_mode=True)
    sharpness_initial = get_sharpness_fast(frame)
    if global_data is not None:
        global_data[z_initial] = (sharpness_initial, frame)

    # Этап 1: Определение направления фокусировки
    increase_step = 0.1
    improvement_threshold = 1.1

    try:
        while True:
            down_sharpness, up_sharpness = get_up_and_down_sharpness(increase_step)

            if down_sharpness > 0 and up_sharpness / down_sharpness > improvement_threshold:
                direction = 1
                break
            elif up_sharpness > 0 and down_sharpness / up_sharpness > improvement_threshold:
                direction = -1
                break

            increase_step -= 0.02
            if increase_step <= 0.01:
                result = autofocusing_extended(
                    robot=robot,
                    camera=camera,
                    config=config,
                    z_calibration=z_initial,
                    z_range=5,
                    step_move=0.5,
                    global_data=global_data
                )
                return result

        # Этап 2: Выполнение автофокусировки в заданном направлении
        z_best, sharpness_best, frame = _autofocusing(
            robot=robot,
            camera=camera,
            config=config,
            z_start=z_initial,
            step_move=0.1,
            direction=direction,
            global_data=global_data
        )

        if is_set_ideal_sharpness:
            return _set_ideal_sharpness(config=config, sharpness_current=sharpness_best)

        if is_compare_sharpness and sharpness_initial > sharpness_best:
            move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
            return None

        return sharpness_best, frame

    except (RobotException, KnownSystemException):
        if z_initial is not None:
            move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
        raise

    except Exception:
        if z_initial is not None:
            move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
        raise


def _set_ideal_sharpness(config: 'ConfigManager', sharpness_current: float) -> bool:
    """
    Проверяет текущие параметры автофокусировки с идеальными.
    Если текущие параметры лучше идеальных, устанавливает их как идеальные.

    Args:
        config: Экземпляр класса конфигураций
        sharpness_current: Текущая резкость

    Returns:
        bool: True если текущая резкость лучше идеальной, иначе False
    """
    # if config.sharpness_ideal > 0:
    #     print(f"sharpness_current = {sharpness_current}")
    #     print(f"config.sharpness_ideal = {config.sharpness_ideal}")
    #     print(f"difference_percent = {(1 - sharpness_current / config.sharpness_ideal) * 100}")
    
    if sharpness_current > config.sharpness_ideal:
        config.sharpness_ideal = sharpness_current
        logger.debug(f"Обновлен параметр эталонной резкости: {sharpness_current}")
        
        return True

    return False


def _check_focus(config: 'ConfigManager',
                 frame: Optional[np.ndarray] = None,
                 sharpness: Optional[float] = None,
                 max_difference_percent: float = MAX_DIFFERENCE_PERCENT) -> bool:
    """
    Проверяет текущие параметры автофокусировки с идеальными.

    Args:
        config: Экземпляр класса конфигураций
        frame: Изображение с камеры
        sharpness: Резкость изображения (если не передана, вычисляется из frame)
        max_difference_percent: Максимально допустимая разница в процентах

    Returns:
        bool: True если резкость в допустимых пределах, иначе False
    """
    sharpness_current = sharpness if sharpness is not None else get_sharpness_fast(frame)
    if sharpness_current > config.sharpness_ideal:
        return True

    difference_percent = (1 - sharpness_current / config.sharpness_ideal) * 100
    if difference_percent < max_difference_percent:
        return True

    print(f"sharpness_current = {sharpness_current}")
    print(f"config.sharpness_ideal = {config.sharpness_ideal}")
    print(f"difference_percent = {difference_percent}")

    return False


def check_focus_multi(config: 'ConfigManager',
                      frame: Optional[np.ndarray] = None,
                      sharpness: Optional[float] = None,
                      max_difference_percent: float = MAX_DIFFERENCE_PERCENT,
                      max_attempts_capture_frame: int = 3,
                      camera: 'CameraGXIPY' = None) -> bool:
    """
    Проверяет текущие параметры автофокусировки с идеальными заданное количество раз в целях повышения точности.

    Args:
        config: Экземпляр класса конфигураций
        frame: Изображение с камеры
        sharpness: Резкость изображения (если не передана, вычисляется из frame)
        max_difference_percent: Максимально допустимая разница в процентах
        max_attempts_capture_frame: Максимальное количество попыток взятия кадра для достоверности
        camera: Объект камеры для захвата кадров

    Returns:
        bool: True если резкость в допустимых пределах, иначе False
    """
    for _ in range(max_attempts_capture_frame):
        if _check_focus(config=config, frame=frame, sharpness=sharpness, max_difference_percent=max_difference_percent):
            return True

        if camera is not None:
            frame = capture_frame(cam=camera, AOI_mode=True)

    return False


def correct_focus(robot: 'RobotController',
                  camera: 'CameraGXIPY',
                  config: 'ConfigManager',
                  offsets=None) -> Optional[np.ndarray]:
    """
    Корректирует резкость (фокусное расстояние) изображения.

    Выполняет серию попыток улучшить фокусировку, собирая все измерения резкости
    и соответствующие кадры в общий словарь. По окончании при необходимости
    выбирается координата с максимальной резкостью, и робот перемещается в неё,
    возвращая сохранённый кадр без повторного захвата.

    Args:
        robot: Экземпляр класса робота
        camera: Объект камеры для захвата кадров
        config: Экземпляр класса конфигураций
        offsets: Список смещений относительно начального положения

    Returns:
        Optional[np.ndarray]: Оригинальное изображение с хорошей фокусировкой или None
    """
    if offsets is None:
        offsets = [0.1, -0.1]

    z_initial = config.current_coordinates["z"]

    # Словарь для сбора всех результатов: Z -> (резкость, кадр)
    global_data: Dict[float, Tuple[float, np.ndarray]] = {}

    try:
        # Цикл попыток с разными смещениями
        for offset in offsets:
            new_data_focus = autofocusing_standard(
                robot=robot,
                camera=camera,
                config=config,
                global_data=global_data
            )
            if new_data_focus is not None and isinstance(new_data_focus, tuple):
                sharpness, frame = new_data_focus
                if check_focus_multi(config=config, sharpness=sharpness, camera=camera):
                    return frame

            print(f"Нет! offset = {offset}")
            move_robot_to_coordinates(robot=robot, config=config, z=(z_initial + offset))

        # Возвращение в начальную позицию перед финальной попыткой
        move_robot_to_coordinates(robot=robot, config=config, z=z_initial)

        return autofocusing_extended(
            robot=robot,
            camera=camera,
            config=config,
            global_data=global_data,
            is_compare_sharpness=False)[1]

    except Exception:
        move_robot_to_coordinates(robot=robot, config=config, z=z_initial)
        raise
