import numpy as np
from threading import Event, Thread
import queue
import math
import time
import datetime
from pathlib import Path
from flet.core.container import Container
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from project.algorithms.detection_cutting_error import find_cutting_error_defects
from project.algorithms.detection_black_point import find_black_point_defects
from project.station.camera.frame_process import save_frame
from project.station.robot.movements import move_robot_to_coordinates, robot_to_home
from project.algorithms.autocentering import autocentering
from project.algorithms.autofocusing import correct_focus, check_focus_multi
from project.station.camera.frame_capture import capture_frame, get_base64_from_frame, rotate_frame
from project.station.camera.feed import show_loading_image, hide_loading_image
from project.application.addition.dialogs import show_error
from project.algorithms.disk_space_monitor import DiskSpaceMonitor, detect_inspection_disk
from project.application.data_work.wafer_visual import WaferMapVisual
from project.station.robot.robot_controller import RobotController
from project.station.camera.camera_manager import CameraManager
from project.configuration.config_manager import ConfigManager
from project.application.data_work.wafer_data import DieStatus
from project.application.addition.logger import logger
from project.application.addition.exceptions import RobotException


@dataclass
class ProcessingTask:
    """
    Задача для обработки изображения в отдельном потоке.

    Attributes:
        die: Объект кристалла
        die_id: Идентификатор кристалла
        frame: Изображение с камеры
        wrong_die_geometry: Метка неправильной геометрии кристалла
        is_find_cutting_error_defects: Метка поиска ошибок реза
        current_debug_dir: Директория для сохранения отладочных фото
        debug: Режим отладки
        inspection_start_time: Время начала инспекции кристалла
    """
    die: Any
    die_id: str
    frame: np.ndarray
    wrong_die_geometry: bool
    is_find_cutting_error_defects: bool
    current_debug_dir: Optional[Path]
    debug: bool
    inspection_start_time: float


@dataclass
class ProcessingResult:
    """
    Результат обработки изображения.

    Attributes:
        die: Объект кристалла
        die_id: Идентификатор кристалла
        total_count_defect: Общее количество дефектов
        defects_list: Список дефектов
        frame_filtered: Изображение с наложенными дефектами
        new_status: Новый статус кристалла
        frame_original: Оригинальное изображение
        inspection_start_time: Время начала инспекции
        processing_start_time: Время начала обработки
        processing_end_time: Время окончания обработки
    """
    die: Any
    die_id: str
    total_count_defect: int
    defects_list: List[Dict]
    frame_filtered: Optional[np.ndarray]
    new_status: Any
    frame_original: Optional[np.ndarray] = None
    inspection_start_time: float = 0.0
    processing_start_time: float = 0.0
    processing_end_time: float = 0.0


def _clear_queue(q: queue.Queue):
    """
    Очищает очередь, забирая все элементы без обработки.
    Используется для немедленной остановки обработки при нажатии "Стоп".

    Args:
        q: Очередь для очистки
    """
    try:
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                break
        logger.debug(f"Очередь очищена")
    except Exception as e:
        logger.error(f"Ошибка при очистке очереди: {e}")


def _processing_worker(task_queue: queue.Queue, result_queue: queue.Queue, stop_event: Event):
    """
    Рабочий поток для нейросетевой обработки изображений.
    При установке stop_event НЕМЕДЛЕННО прекращает обработку и очищает очередь.

    Проверяет stop_event:
    - Перед получением задачи из очереди
    - Перед началом обработки кадра
    - После обработки кадра (перед отправкой результата)
    - При возникновении ошибки

    Выполняет:
        - Нейросетевую обработку (поиск загрязнений)
        - Обнаружение смещения реза
        - Обнаружение ошибок реза (инородные тела на границе)
        - Определение итогового статуса кристалла

    Args:
        task_queue: Очередь задач на обработку
        result_queue: Очередь результатов обработки
        stop_event: Событие для остановки потока
    """
    while not stop_event.is_set():
        try:
            # Пытаемся получить задачу с таймаутом для проверки stop_event
            task = task_queue.get(timeout=1.0)
            if task is None:  # Сигнал завершения
                break

            # Проверяем остановку перед обработкой
            if stop_event.is_set():
                # logger.debug("Processing worker: остановка перед обработкой кадра")
                _clear_queue(task_queue)  # Очищаем оставшиеся задачи
                break

            # logger.debug(f"Processing worker: начало обработки кристалла {task.die_id}")

            # Фиксируем время начала обработки
            processing_start_time = time.time()

            try:
                total_count_defect = 0
                defects_list = []

                # === СМЕЩЕНИЕ РЕЗА ===
                if task.wrong_die_geometry:
                    total_count_defect += 1
                    defects_list.append({
                        'key': "cutting_offset",
                        'name': "Смещение реза",
                        'color': [-1, -1, -1],
                        'count': 1
                    })

                # === НЕЙРОННАЯ ОБРАБОТКА (ЗАГРЯЗНЕНИЕ) ===
                frame_rot = rotate_frame(task.frame, rotate_angle=90)
                count_black_point_defect, black_point_defect_list, frame_filtered = find_black_point_defects(
                    frame_original=frame_rot,
                    frame_filtered=frame_rot.copy()
                )
                total_count_defect += count_black_point_defect
                if black_point_defect_list:
                    defects_list.extend(black_point_defect_list)
                if frame_filtered is not None:
                    frame_filtered = rotate_frame(frame_filtered)
                else:
                    frame_filtered = rotate_frame(frame_rot)

                # === НЕЙРОННАЯ ОБРАБОТКА (ОШИБКА РЕЗА) ===
                if task.is_find_cutting_error_defects:
                    count_cutting_error_defect, cutting_error_defect_list, frame_filtered = find_cutting_error_defects(
                        frame_original=task.frame,
                        frame_filtered=frame_filtered if frame_filtered is not None else task.frame
                    )
                    total_count_defect += count_cutting_error_defect
                    if cutting_error_defect_list:
                        defects_list.extend(cutting_error_defect_list)

                    #     timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    #     current_debug_dir = Path(r"C:\Users\user\Desktop\Ошибка реза с измерениями")
                    #     save_frame(frame=frame_filtered, filename=f"Фото_с_ошибкой_реза_{timestamp}.jpg",
                    #                dir_save=current_debug_dir)

                # Определение статуса кристалла
                if total_count_defect == 0:
                    new_status = DieStatus.GOOD
                    frame_filtered = None
                else:
                    new_status = DieStatus.BAD

                # Фиксируем время окончания обработки
                processing_end_time = time.time()

                # Проверяем остановку перед отправкой результата
                if stop_event.is_set():
                    logger.debug("Остановка после обработки, результат не отправляется")
                    _clear_queue(task_queue)  # Очищаем оставшиеся задачи
                    break

                # Отправляем результат
                result = ProcessingResult(
                    die=task.die,
                    die_id=task.die_id,
                    total_count_defect=total_count_defect,
                    defects_list=defects_list,
                    frame_filtered=frame_filtered,
                    new_status=new_status,
                    frame_original=task.frame,
                    inspection_start_time=task.inspection_start_time,
                    processing_start_time=processing_start_time,
                    processing_end_time=processing_end_time
                )
                result_queue.put(result)

            except Exception as e:
                logger.error(f"Ошибка обработки кристалла {task.die_id}: {e}")

                # Проверяем остановку перед отправкой результата с ошибкой
                if stop_event.is_set():
                    logger.debug("Остановка после ошибки, результат не отправляется")
                    _clear_queue(task_queue)  # Очищаем оставшиеся задачи
                    break

                # Фиксируем время окончания обработки (даже при ошибке)
                processing_end_time = time.time()

                # В случае ошибки отправляем результат со статусом NEED_CHECK
                result = ProcessingResult(
                    die=task.die,
                    die_id=task.die_id,
                    total_count_defect=0,
                    defects_list=[],
                    frame_filtered=None,
                    new_status=DieStatus.NEED_CHECK,
                    frame_original=task.frame,
                    inspection_start_time=task.inspection_start_time,
                    processing_start_time=processing_start_time,
                    processing_end_time=processing_end_time
                )
                result_queue.put(result)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Критическая ошибка в _processing_worker: {e}")
            _clear_queue(task_queue)  # Очищаем очередь при критической ошибке


def _result_applier_worker(result_queue: queue.Queue, wafer_map_visual,
                           stop_event: Event):
    """
    Отдельный поток для применения результатов обработки.
    При установке stop_event немедленно прекращает работу и очищает очередь результатов.

    Не блокирует основной цикл движения робота.
    Применяет результаты по мере их появления.

    Args:
        result_queue: Очередь результатов обработки
        wafer_map_visual: Визуальная модель данных
        stop_event: Событие для остановки потока
    """
    while not stop_event.is_set():
        try:
            result = result_queue.get(timeout=1.0)
            if result is None:  # Сигнал завершения
                break

            # Проверяем остановку перед применением результата
            if stop_event.is_set():
                logger.debug("Остановка перед применением результата")
                _clear_queue(result_queue)  # Очищаем оставшиеся результаты
                break

            # Применяем результат обработки к кристаллу
            _apply_processing_result(result, wafer_map_visual, stop_event)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Ошибка в потоке применения результатов: {e}")
            _clear_queue(result_queue)  # Очищаем очередь при ошибке
            break


def main_algorithm(wafer_map_visual: 'WaferMapVisual',
                   robot: 'RobotController',
                   camera_manager: 'CameraManager',
                   config: 'ConfigManager',
                   left_image_container: Container,
                   right_image_container: Container,
                   stop_event: Event,
                   pause_event: Event,
                   on_pause_request,
                   debug: bool = False) -> int | None:
    """
    Основной алгоритм, здесь вызываются функции движения и отбраковки кристаллов.

    Выполняет:
        - Проверка свободного места на диске
        - Подключение к манипулятору и его калибровку
        - Перемещение к первому инспектируемому кристаллу
        - Запуск основного цикла перемещения и инспекции

    Args:
        wafer_map_visual: Визуальная модель данных с кристаллами
        robot: Класс робота
        camera_manager: Класс-менеджер камер
        config: Класс конфигураций
        left_image_container: Левое изображение (оригинальное)
        right_image_container: Правое изображение (с фильтрами)
        stop_event: threading.Event для остановки
        pause_event: threading.Event для паузы
        on_pause_request: Функция для запроса паузы (pause_AOI_handler)
        debug: Режим отладки (True - сохранять фото и логировать время)

    Returns:
        int: Количество проверенных кристаллов

    Raises:
        RobotException: При ошибках подключения или калибровки манипулятора
    """
    # Инициализация монитора дискового пространства
    disk_path = detect_inspection_disk()
    disk_monitor = DiskSpaceMonitor(disk_path=disk_path, config=config)

    # Функция для остановки инспекции при критической нехватке памяти
    def emergency_stop_due_to_disk_space():
        logger.error(f"Критическая нехватка места на диске {disk_path}! Принудительная остановка инспекции")
        stop_event.set()

    # Запуск фонового мониторинга дискового пространства
    disk_monitor.start_monitoring(stop_callback=emergency_stop_due_to_disk_space)

    try:
        # Показать загрузку перед калибровкой
        windows = [left_image_container.content, right_image_container.content]

        show_loading_image("Манипулятор калибруется", windows, config)
        robot_to_home(robot=robot, config=config)
        hide_loading_image(windows)

        show_loading_image("Манипулятор движется к первому инспектируемому кристаллу", windows, config)
        move_robot_to_coordinates(
            robot=robot,
            config=config,
            x=wafer_map_visual.wafer_map.orientation.x_coord_of_first_reference_die,
            y=wafer_map_visual.wafer_map.orientation.y_coord_of_first_reference_die,
            z=wafer_map_visual.wafer_map.orientation.z_coord_of_first_reference_die
        )

    except RobotException:
        disk_monitor.stop_monitoring()
        raise

    try:
        # Запуск основного цикла перемещения и инспекции
        count_checked_dice = _movement(wafer_map_visual=wafer_map_visual,
                                       robot=robot,
                                       config=config,
                                       camera_manager=camera_manager,
                                       left_image_container=left_image_container,
                                       right_image_container=right_image_container,
                                       stop_event=stop_event,
                                       pause_event=pause_event,
                                       on_pause_request=on_pause_request,
                                       debug=debug)

        return count_checked_dice

    finally:
        # Остановка мониторинга дискового пространства после завершения инспекции
        disk_monitor.stop_monitoring()
        logger.debug("Мониторинг дискового пространства остановлен")


def _get_traversal_path_from_reference_cell(wafer_map, start_row: int, start_col: int) -> List[List[int]]:
    """
    Возвращает путь обхода матрицы кристаллов от референсной точки.
    Сначала идет вниз по змейке от начальной позиции, затем вверх (без повторения начальной).

    Args:
        wafer_map: Объект WaferMap
        start_row: Начальная строка
        start_col: Начальный столбец

    Returns:
        List[List[int]]: Список координат [row, col] для обхода кристаллов
    """
    rows = wafer_map.total_rows
    cols = wafer_map.total_cols
    path = []

    # ФАЗА 1: Движение ВНИЗ от стартовой строки
    for col in range(start_col, cols):
        die = wafer_map.die_matrix[start_row][col]
        if die:
            path.append([start_row, col])

    for row in range(start_row + 1, rows):
        if (row - start_row) % 2 == 1:
            for col in range(cols - 1, -1, -1):
                die = wafer_map.die_matrix[row][col]
                if die:
                    path.append([row, col])
        else:
            for col in range(cols):
                die = wafer_map.die_matrix[row][col]
                if die:
                    path.append([row, col])

    # ФАЗА 2: Движение ВВЕРХ от стартовой строки
    for col in range(start_col - 1, -1, -1):
        die = wafer_map.die_matrix[start_row][col]
        if die:
            path.append([start_row, col])

    for row in range(start_row - 1, -1, -1):
        if (start_row - row) % 2 == 1:
            for col in range(cols):
                die = wafer_map.die_matrix[row][col]
                if die:
                    path.append([row, col])
        else:
            for col in range(cols - 1, -1, -1):
                die = wafer_map.die_matrix[row][col]
                if die:
                    path.append([row, col])

    return path


def _trim_path_from_position(full_traversal_path: List[List[int]],
                             target_row: int,
                             target_col: int) -> list[list[int]] | None:
    """
    Обрезает путь обхода, оставляя только элементы от заданной позиции до конца.
    Изменяет исходный список.

    Args:
        full_traversal_path: Полный путь обхода (список [row, col])
        target_row: Целевая строка
        target_col: Целевой столбец

    Returns:
        Optional[List[List[int]]]: Обрезанный список или None, если позиция не найдена
    """
    for i, (row, col) in enumerate(full_traversal_path):
        if row == target_row and col == target_col:
            del full_traversal_path[:i]
            return full_traversal_path
    return None


def _apply_processing_result(result: ProcessingResult, wafer_map_visual,
                             stop_event):
    """
    Применяет результат обработки к кристаллу и обновляет UI.

    Args:
        result: Результат обработки изображения
        wafer_map_visual: Визуальная модель данных
        stop_event: Событие для остановки
    """
    # === СОХРАНЕНИЕ ФОТОГРАФИЙ ДЛЯ ДЕФЕКТНЫХ КРИСТАЛЛОВ ===
    # Сохраняем фотографии только если кристалл имеет дефекты (total_count_defect > 0)
    if result.total_count_defect > 0:
        # Генерируем имя папки для фотографий (убираем скобки и заменяем запятую на подчеркивание)
        clean_die_id = result.die_id.replace('[', '').replace(']', '').replace(',', '_')
        folder_name = f"crystal_{clean_die_id}"

        # Сохраняем фотографии через протокол
        file_frame_original_path, file_frame_filtered_path = \
            wafer_map_visual.wafer_map.protocol.save_die_photos(
                folder_name=folder_name,
                frame_original=result.frame_original,
                frame_filtered=result.frame_filtered
            )

        # Сохраняем пути к фотографиям в объекте кристалла
        if file_frame_original_path is not None:
            result.die.file_frame_original_path = file_frame_original_path
        if file_frame_filtered_path is not None:
            result.die.file_frame_filtered_path = file_frame_filtered_path

    result.die.update_die_status(
        new_status=result.new_status,
        defects_info=result.defects_list
    )
    wafer_map_visual.update_visual_die(die=result.die, is_need_update_canvas=True)

    if not stop_event.is_set() and result.frame_original is not None:
        update_images_global(
            frame_original=result.frame_original,
            frame_filtered=result.frame_filtered,
            is_rotated=False
        )


def _movement(wafer_map_visual: 'WaferMapVisual',
              robot: 'RobotController',
              camera_manager: 'CameraManager',
              config: 'ConfigManager',
              left_image_container: Container,
              right_image_container: Container,
              stop_event: Event,
              pause_event: Event,
              on_pause_request,
              debug: bool = False) -> int:
    """
    Функция перемещения камеры по пластине с параллельной обработкой изображений.

    ЗАЩИТА ОТ СБОЕВ: если расстояние между опорным и текущим кристаллом
    выходит за допустимый диапазон (теоретическое ± полудиагональ кристалла),
    кристалл пропускается, а опорный кристалл НЕ обновляется.
    Робот возвращается на последний корректный опорный кристалл и продолжает
    инспекцию со следующего кристалла.

    ПЕРИОДИЧЕСКАЯ КОРРЕКЦИЯ УГЛА: каждые 100 проверенных кристаллов
    выполняется коррекция угла поворота пластины относительно самого первого
    референсного кристалла. Коррекция применяется на первом же кристалле,
    где есть успешная центровка.
    """

    def update_images(frame_original: Optional[np.ndarray] = None,
                      frame_filtered: Optional[np.ndarray] = None,
                      is_rotated: int = True) -> None:
        rotate_angle = 90 if is_rotated else 0
        try:
            if frame_original is not None:
                left_image_container.content.src_base64 = get_base64_from_frame(frame_original,
                                                                                target_size=(800, 580),
                                                                                rotate_angle=rotate_angle)
            else:
                left_image_container.content.src_base64 = ""
            if frame_filtered is not None:
                right_image_container.content.src_base64 = get_base64_from_frame(frame_filtered,
                                                                                 target_size=(800, 580),
                                                                                 rotate_angle=rotate_angle)
            else:
                right_image_container.content.src_base64 = ""
            left_image_container.update()
            right_image_container.update()
        except Exception as e:
            logger.error(f"Ошибка обновления изображений: {e}")

    global update_images_global
    update_images_global = update_images

    def check_status() -> bool:
        nonlocal camera
        if stop_event.is_set():
            logger.debug("Алгоритм остановлен (проверка перед итерацией робота)")
            return False
        was_paused = False
        if pause_event.is_set() and not stop_event.is_set():
            camera.disconnect()
            while pause_event.is_set() and not stop_event.is_set():
                was_paused = True
                pause_event.wait(timeout=0.5)
        if was_paused:
            logger.debug("Переподключение камеры после паузы")
            camera = camera_manager.connect_cam(index_of_cam=0, priority_window=2)
        return True

    def save_debug_frame(frame: Optional[np.ndarray], filename: str, debug_dir: Optional[Path]) -> bool:
        if not debug or frame is None or debug_dir is None:
            return False
        return save_frame(frame=frame, filename=filename, dir_save=debug_dir)

    def clear_all_highlights():
        try:
            for row in range(wafer_map.total_rows):
                for col in range(wafer_map.total_cols):
                    die = die_matrix[row][col]
                    if die is not None:
                        wafer_map_visual.update_visual_die(die=die, is_need_update_canvas=False)
            if wafer_map_visual._canvas_ref:
                wafer_map_visual._canvas_ref.update()
            logger.debug("Подсветка всех кристаллов убрана")
        except Exception as e:
            logger.error(f"Ошибка при очистке подсветки кристаллов: {e}")

    def validate_die_distance(first_die, second_die, second_die_coords) -> tuple[bool, float, float, float, float]:
        """
        Проверяет, что расстояние между опорным и текущим кристаллом в допустимом диапазоне.

        Returns:
            tuple: (is_valid, actual_distance, theoretical_distance, min_allowed, max_allowed)
        """
        real_x1, real_y1 = first_die.physical_x, first_die.physical_y
        real_x2, real_y2 = second_die_coords

        # Фактическое расстояние
        actual_distance = math.hypot(real_x2 - real_x1, real_y2 - real_y1)

        # Теоретическое расстояние (используем ТЕОРЕТИЧЕСКИЕ координаты второго кристалла)
        theoretical_x2 = second_die.physical_x
        theoretical_y2 = second_die.physical_y
        theoretical_distance = math.hypot(theoretical_x2 - real_x1, theoretical_y2 - real_y1)

        # Допустимое отклонение: полудиагональ кристалла
        half_width = wafer_map.cell_size_x_mm / 2.0
        half_height = wafer_map.cell_size_y_mm / 2.0
        max_deviation = math.hypot(half_width, half_height)

        min_allowed = max(0, theoretical_distance - max_deviation)
        max_allowed = theoretical_distance + max_deviation

        is_valid = min_allowed <= actual_distance <= max_allowed

        return is_valid, actual_distance, theoretical_distance, min_allowed, max_allowed

    wafer_map = wafer_map_visual.wafer_map
    die_matrix = wafer_map.die_matrix

    camera = camera_manager.connect_cam(index_of_cam=0, priority_window=2)
    for _ in range(40):
        capture_frame(cam=camera, AOI_mode=True)

    def filter_dice(die) -> bool:
        return die.status == DieStatus.NEED_CHECK

    full_traversal_path = _get_traversal_path_from_reference_cell(
        wafer_map=wafer_map,
        start_row=wafer_map.orientation.first_reference_die.row,
        start_col=wafer_map.orientation.first_reference_die.col
    )

    traversal_path = [
        [row, col] for row, col in full_traversal_path
        if filter_dice(wafer_map.die_matrix[row][col])
    ]

    count_need_focus = 0
    count_need_centering = 0
    count_checked_dice = 0
    count_skipped_dice = 0

    die_prev_ref = wafer_map.die_prev_ref
    last_inspected_die = die_prev_ref

    # Переменные для периодической коррекции угла
    correction_angle_pending = False  # Флаг, что нужна коррекция угла
    next_angle_correction_at = 100  # Следующий индекс для коррекции угла

    # === СОЗДАНИЕ ОЧЕРЕДЕЙ И ПОТОКОВ ===
    MAX_QUEUE_SIZE = 5
    task_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
    result_queue = queue.Queue()

    processing_thread = Thread(
        target=_processing_worker,
        args=(task_queue, result_queue, stop_event),
        daemon=True
    )
    processing_thread.start()

    result_applier_thread = Thread(
        target=_result_applier_worker,
        args=(result_queue, wafer_map_visual, stop_event),
        daemon=True
    )
    result_applier_thread.start()

    # Основной цикл инспекции кристаллов
    for path_idx, (row_idx, col_idx) in enumerate(traversal_path):
        if not check_status():
            if last_inspected_die is not None and last_inspected_die != die_prev_ref:
                wafer_map.die_prev_ref = last_inspected_die
                die_prev_ref = last_inspected_die
            clear_all_highlights()
            _clear_queue(task_queue)
            break

        start_time = time.time()
        current_die_id = f"[{row_idx + 1},{col_idx + 1}]"

        current_debug_dir = None

        if debug:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            current_debug_dir = (Path(__file__).resolve().parents[2] /
                                 "photos_debugging" / f"crystal_{row_idx + 1}_{col_idx + 1}_{timestamp}")
            current_debug_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"[DEBUG] Создана папка для отладки: {current_debug_dir}")
            logger.debug(f"[DEBUG] Начало инспекции кристалла {current_die_id}")

        # Флаг для определения, нужно ли обновлять опорный кристалл
        should_update_ref = False

        try:
            die = die_matrix[row_idx][col_idx]
            x, y = die.physical_x, die.physical_y

            wafer_map_visual.highlight_die(die)

            # 1. ПЕРЕМЕЩЕНИЕ К КРИСТАЛЛУ
            # Вычисляем расстояние перемещения (если есть предыдущие координаты)
            move_distance_mm = 0.0
            if last_inspected_die is not None:
                move_distance_mm = math.hypot(x - last_inspected_die.physical_x, y - last_inspected_die.physical_y)

            move_robot_to_coordinates(robot=robot, config=config, x=x, y=y)

            # 2. ЗАХВАТ КАДРА
            frame = None
            for _ in range(min(3 + (math.floor(move_distance_mm / 50) * 4), 8)):
                frame = capture_frame(cam=camera, AOI_mode=True)

            # 3. АВТОФОКУСИРОВКА
            try:
                save_debug_frame(frame, "01_До_автофокуса.jpg", current_debug_dir)
                # save_frame(frame=frame, filename=f"До_автофокуса_{timestamp}.jpg",
                #            dir_save=Path(r"C:\Users\user\Desktop\До_автофокуса"))

                if not check_focus_multi(config=config, frame=frame, camera=camera):
                    count_need_focus += 1

                    frame = correct_focus(robot=robot, camera=camera, config=config)

                    save_debug_frame(frame, "02_После_автофокуса.jpg", current_debug_dir)
                    # save_frame(frame=frame, filename=f"После_автофокуса_{timestamp}.jpg",
                    #            dir_save=Path(r"C:\Users\user\Desktop\После_автофокуса"))

            except Exception as e:
                logger.error(f"Произошла ошибка при автофокусировке кристалла {current_die_id}: {e}")
                frame = capture_frame(cam=camera, AOI_mode=True)

            # === АВТОПОЗИЦИОНИРОВАНИЕ (ЦЕНТРОВКА) ===
            is_find_cutting_error_defects = True
            wrong_die_geometry = False
            centering_success = False
            x_center_new = None
            y_center_new = None
            frame_before = None
            distance_check_failed = False

            try:
                for attempt in range(6):
                    if debug and attempt > 0:
                        logger.debug(f"Попытка центровки #{attempt + 1} для {current_die_id}")

                    if frame is not None:
                        frame_before = frame.copy()

                    if attempt <= 1:
                        max_attempts = 2 * (attempt + 1)
                        max_offset_mm = 0.01
                        is_find_cutting_error_defects = True
                        min_width_offset = 6
                    elif attempt <= 3:
                        max_attempts = 4
                        max_offset_mm = 0.1 if attempt == 2 else 0.3
                        is_find_cutting_error_defects = False
                        min_width_offset = 6
                    else:
                        max_attempts = 4
                        max_offset_mm = 0.5 if attempt == 4 else 0.8
                        is_find_cutting_error_defects = False
                        min_width_offset = 9 - attempt

                    x_center_new, y_center_new, frame, wrong_geometry_with_correct_location = autocentering(
                        robot=robot,
                        camera=camera,
                        config=config,
                        frame=frame,
                        max_attempts=max_attempts,
                        max_offset_mm=max_offset_mm,
                        min_width_offset=min_width_offset,
                        dir_save=current_debug_dir if debug else None
                    )

                    if wrong_geometry_with_correct_location:
                        wrong_die_geometry = True
                        frame = rotate_frame(capture_frame(cam=camera, AOI_mode=True))
                        break

                    if frame is not None:
                        centering_success = True
                        if x_center_new is not None and y_center_new is not None:
                            count_need_centering += 1

                            # === ПРОВЕРКА РАССТОЯНИЯ ===
                            if count_checked_dice == 0:
                                wafer_map.update_die_coordinates_by_reference_die(
                                    die=die, die_real_coords=(x_center_new, y_center_new)
                                )
                                die.physical_x = x_center_new
                                die.physical_y = y_center_new
                                last_inspected_die = die
                                should_update_ref = True
                            else:
                                # Проверяем расстояние ДО обновления координат
                                is_valid, actual_dist, theor_dist, min_allowed, max_allowed = \
                                    validate_die_distance(die_prev_ref, die, (x_center_new, y_center_new))

                                if not is_valid:
                                    # АНОМАЛИЯ: пропускаем кристалл, НЕ обновляем опорный
                                    logger.error(f"АНОМАЛИЯ расстояния для кристалла {current_die_id}: "
                                                 f"расстояние до опорного "
                                                 f"[{die_prev_ref.row + 1},{die_prev_ref.col + 1}] "
                                                 f"вне допустимого диапазона! "
                                                 f"Факт: {actual_dist:.3f} мм, Теор: {theor_dist:.3f} мм, "
                                                 f"Диапазон: [{min_allowed:.3f}, {max_allowed:.3f}] мм")

                                    # Возвращаем робота на последний корректный опорный кристалл
                                    logger.info(f"Возврат робота на опорный кристалл "
                                                f"[{die_prev_ref.row + 1},{die_prev_ref.col + 1}]")
                                    move_robot_to_coordinates(
                                        robot=robot,
                                        config=config,
                                        x=die_prev_ref.physical_x,
                                        y=die_prev_ref.physical_y
                                    )

                                    # Отмечаем кристалл как NEED_CHECK
                                    die.update_die_status(
                                        new_status=DieStatus.NEED_CHECK,
                                        defects_info=[]
                                    )
                                    wafer_map_visual.update_visual_die(die=die, is_need_update_canvas=True)

                                    count_skipped_dice += 1
                                    distance_check_failed = True
                                    should_update_ref = False
                                    break

                                # Расстояние в норме - обновляем координаты
                                wafer_map.update_die_coordinates_AOI(
                                    first_die=die_prev_ref,
                                    second_die=die,
                                    second_die_coords=(x_center_new, y_center_new),
                                    traversal_path=_trim_path_from_position(full_traversal_path, row_idx, col_idx)
                                )
                                die.physical_x = x_center_new
                                die.physical_y = y_center_new
                                last_inspected_die = die
                                should_update_ref = True

                        break

                    frame = capture_frame(cam=camera, AOI_mode=True)

                if debug and frame_before is not None and frame is not None:
                    save_debug_frame(frame_before, f"03_До_центровки.jpg",
                                     current_debug_dir)
                    save_debug_frame(frame, f"04_После_центровки.jpg",
                                     current_debug_dir)

                # if frame_before is not None and frame is not None:
                #     save_frame(frame=frame_before, filename=f"До_центровки_{timestamp}.jpg",
                #                dir_save=Path(r"C:\Users\user\Desktop\До_центровки"))
                #
                #     save_frame(frame=frame, filename=f"После_центровки_{timestamp}.jpg",
                #                dir_save=Path(r"C:\Users\user\Desktop\После_центровки"))

                if wrong_die_geometry or not centering_success:
                    is_find_cutting_error_defects = False
                    if not distance_check_failed:
                        should_update_ref = True

            except Exception as e:
                logger.error(f"Произошла ошибка при позиционировании на кристалл {current_die_id}: {e}")
                frame = capture_frame(cam=camera, AOI_mode=True)
                if not distance_check_failed:
                    should_update_ref = True

            # Если проверка расстояния провалена - пропускаем кристалл
            if distance_check_failed:
                logger.warning(f"Кристалл {current_die_id} ПРОПУЩЕН из-за аномалии расстояния. "
                               f"Опорный кристалл: [{die_prev_ref.row + 1},{die_prev_ref.col + 1}]")
                continue

            # === ОТПРАВКА ЗАДАЧИ В ОЧЕРЕДЬ НА ОБРАБОТКУ ===
            task_queue.put(ProcessingTask(
                die=die,
                die_id=current_die_id,
                frame=frame,
                wrong_die_geometry=wrong_die_geometry,
                is_find_cutting_error_defects=is_find_cutting_error_defects,
                current_debug_dir=current_debug_dir,
                debug=debug,
                inspection_start_time=start_time
            ))

            # Обновляем опорный кристалл только если все проверки пройдены
            if should_update_ref:
                die_prev_ref = die
                wafer_map.die_prev_ref = die

            count_checked_dice += 1
            wafer_map.protocol.count_need_focus = count_need_focus
            wafer_map.protocol.count_need_centering = count_need_centering

            # === ПЕРИОДИЧЕСКАЯ КОРРЕКЦИЯ УГЛА ===
            # Проверяем, не пора ли выполнить коррекцию угла
            if count_checked_dice >= next_angle_correction_at:
                correction_angle_pending = True
                next_angle_correction_at += 100  # Следующая коррекция через 100 кристаллов

            # Выполняем коррекцию угла, когда есть подходящий кристалл с центровкой
            if correction_angle_pending and x_center_new is not None and y_center_new is not None:
                first_ref = wafer_map.orientation.first_reference_die
                if first_ref and first_ref != die:
                    dx_real = x_center_new - first_ref.physical_x
                    dy_real = y_center_new - first_ref.physical_y
                    dx_theor = die.physical_x - first_ref.physical_x
                    dy_theor = die.physical_y - first_ref.physical_y

                    real_angle = math.atan2(dy_real, dx_real)
                    theor_angle = math.atan2(dy_theor, dx_theor)
                    angle_correction = real_angle - theor_angle

                    if abs(angle_correction) > 0.0001:
                        cos_a = math.cos(angle_correction)
                        sin_a = math.sin(angle_correction)
                        for pos in traversal_path:
                            row, col = pos
                            d = die_matrix[row][col]
                            if d:
                                rel_x = d.physical_x - x_center_new
                                rel_y = d.physical_y - y_center_new
                                d.physical_x = x_center_new + rel_x * cos_a - rel_y * sin_a
                                d.physical_y = y_center_new + rel_x * sin_a + rel_y * cos_a

                    correction_angle_pending = False

        except Exception as e:
            error_message = f"Ошибка при инспекции кристалла {current_die_id}: {e}"
            logger.error(error_message)
            show_error("Ошибка при инспекции",
                       f"{error_message}\n"
                       f"Данный кристалл не был корректно инспектирован, поэтому его состояние не обновится.\n"
                       f"Нажмите на Продолжить, чтобы продолжить инспекцию",
                       config.page, config)
            on_pause_request(None)
            continue

    # === ЗАВЕРШЕНИЕ ===

    if stop_event.is_set():
        logger.info("Инспекция остановлена оператором. Очистка очередей...")

        if last_inspected_die is not None and last_inspected_die != die_prev_ref:
            wafer_map.die_prev_ref = last_inspected_die

        clear_all_highlights()

        _clear_queue(task_queue)
        task_queue.put(None)
        _clear_queue(result_queue)
        result_queue.put(None)

        processing_thread.join(timeout=5)
        result_applier_thread.join(timeout=5)

        logger.info("Очереди очищены, потоки остановлены")
    else:
        logger.info(f"Проход робота завершен. Ожидание завершения обработки очереди "
                    f"(осталось задач: {task_queue.qsize()}, результатов: {result_queue.qsize()})")

        task_queue.put(None)
        processing_thread.join(timeout=60)

        time.sleep(2)

        result_queue.put(None)
        result_applier_thread.join(timeout=10)

    camera.disconnect()

    # === ВЫВОД СТАТИСТИКИ ===
    if debug:
        logger.debug(f"[DEBUG] Статистика отладки:")
        logger.debug(f"[DEBUG]   - Всего проверено кристаллов: {count_checked_dice}")
        logger.debug(f"[DEBUG]   - Пропущено из-за аномалий расстояния: {count_skipped_dice}")
        logger.debug(f"[DEBUG]   - Требовалось автофокусировок: {count_need_focus}")
        logger.debug(f"[DEBUG]   - Требовалось автопозиционирований: {count_need_centering}")

    return count_checked_dice
