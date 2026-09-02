"""
MOCK-версия для тестирования протоколов.
Закомментированы только движения робота и нейросетевая обработка.
"""

import numpy as np
from threading import Event, Thread
import queue
import time
from flet.core.container import Container
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import random

from project.station.camera.feed import show_loading_image, hide_loading_image
from project.application.addition.dialogs import show_error
from project.algorithms.disk_space_monitor import DiskSpaceMonitor, detect_inspection_disk
from project.application.data_work.wafer_visual import WaferMapVisual
from project.station.camera.frame_capture import get_base64_from_frame
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
    """
    die: Any
    die_id: str


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


def processing_worker(task_queue: queue.Queue, result_queue: queue.Queue, stop_event: Event):
    """
    Рабочий поток для нейросетевой обработки изображений.
    MOCK-версия: генерирует случайные дефекты вместо нейросетей.
    """
    while not stop_event.is_set():
        try:
            # Пытаемся получить задачу с таймаутом для проверки stop_event
            task = task_queue.get(timeout=1.0)
            if task is None:  # Сигнал завершения
                break

            # Проверяем остановку перед обработкой
            if stop_event.is_set():
                _clear_queue(task_queue)
                break

            # Фиксируем время начала обработки
            processing_start_time = time.time()

            try:
                # MOCK: случайные дефекты
                has_defect = random.choice([True, False])

                if has_defect:
                    total_count_defect = random.randint(1, 3)
                    defects_list = []
                    for i in range(total_count_defect):
                        defects_list.append({
                            'key': f"defect_{i}",
                            'name': f"Дефект {i + 1}",
                            'color': [255, 0, 0],
                            'count': 1
                        })
                    new_status = DieStatus.BAD

                else:
                    total_count_defect = 0
                    defects_list = []
                    new_status = DieStatus.GOOD

                # Фиксируем время окончания обработки
                processing_end_time = time.time()

                # Проверяем остановку перед отправкой результата
                if stop_event.is_set():
                    _clear_queue(task_queue)
                    break

                # Отправляем результат
                result = ProcessingResult(
                    die=task.die,
                    die_id=task.die_id,
                    total_count_defect=total_count_defect,
                    defects_list=defects_list,
                    frame_filtered=None,
                    new_status=new_status,
                    frame_original=None,
                    inspection_start_time=0.0,
                    processing_start_time=processing_start_time,
                    processing_end_time=processing_end_time
                )
                result_queue.put(result)

            except Exception as e:
                logger.error(f"Ошибка обработки кристалла {task.die_id}: {e}")

                if stop_event.is_set():
                    _clear_queue(task_queue)
                    break

                processing_end_time = time.time()

                # В случае ошибки отправляем результат со статусом NEED_CHECK
                result = ProcessingResult(
                    die=task.die,
                    die_id=task.die_id,
                    total_count_defect=0,
                    defects_list=[],
                    frame_filtered=None,
                    new_status=DieStatus.NEED_CHECK,
                    frame_original=None,
                    inspection_start_time=0.0,
                    processing_start_time=processing_start_time,
                    processing_end_time=processing_end_time
                )
                result_queue.put(result)

        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Критическая ошибка в processing_worker: {e}")
            _clear_queue(task_queue)


def result_applier_worker(result_queue: queue.Queue, wafer_map_visual,
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
        time.sleep(1)
        hide_loading_image(windows)
        show_loading_image("Манипулятор движется к первому инспектируемому кристаллу", windows, config)
        time.sleep(1)

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


def _apply_processing_result(result: ProcessingResult, wafer_map_visual, stop_event):
    """
    Применяет результат обработки к кристаллу и обновляет UI.
    """
    # === СОХРАНЕНИЕ ФОТОГРАФИЙ ДЛЯ ДЕФЕКТНЫХ КРИСТАЛЛОВ ===
    if result.total_count_defect > 0:
        clean_die_id = result.die_id.replace('[', '').replace(']', '').replace(',', '_')
        folder_name = f"crystal_{clean_die_id}"

        # Сохраняем фотографии через протокол (если они есть)
        if result.frame_original is not None or result.frame_filtered is not None:
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
        if stop_event.is_set():
            logger.debug("Алгоритм остановлен (проверка перед итерацией робота)")
            return False
        was_paused = False
        if pause_event.is_set() and not stop_event.is_set():
            while pause_event.is_set() and not stop_event.is_set():
                was_paused = True
                pause_event.wait(timeout=0.5)
        if was_paused:
            logger.debug("Переподключение камеры после паузы")
        return True

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

    wafer_map = wafer_map_visual.wafer_map
    die_matrix = wafer_map.die_matrix

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

    die_prev_ref = wafer_map.die_prev_ref
    last_inspected_die = die_prev_ref

    # === СОЗДАНИЕ ОЧЕРЕДЕЙ И ПОТОКОВ ===
    MAX_QUEUE_SIZE = 5
    task_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
    result_queue = queue.Queue()

    processing_thread = Thread(
        target=processing_worker,
        args=(task_queue, result_queue, stop_event),
        daemon=True
    )
    processing_thread.start()

    result_applier_thread = Thread(
        target=result_applier_worker,
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

        current_die_id = f"[{row_idx + 1},{col_idx + 1}]"

        # Флаг для определения, нужно ли обновлять опорный кристалл
        should_update_ref = False

        try:
            die = die_matrix[row_idx][col_idx]
            wafer_map_visual.highlight_die(die)

            # === ОТПРАВКА ЗАДАЧИ В ОЧЕРЕДЬ НА ОБРАБОТКУ ===
            task_queue.put(ProcessingTask(
                die=die,
                die_id=current_die_id,
            ))

            # Обновляем опорный кристалл только если все проверки пройдены
            if should_update_ref:
                die_prev_ref = die
                wafer_map.die_prev_ref = die

            count_checked_dice += 1
            wafer_map.protocol.count_need_focus = count_need_focus
            wafer_map.protocol.count_need_centering = count_need_centering

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

    return count_checked_dice
