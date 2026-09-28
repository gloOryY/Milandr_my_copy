import cv2
import os
import numpy as np
import subprocess
import tempfile
import time
import datetime
import atexit
from pathlib import Path
import psutil

from project.application.addition.dialogs import show_warning


class ImageViewer:
    """
    Статический класс для открытия изображений в Paint или стандартном просмотрщике Windows.

    Обеспечивает:
    - Сохранение кадра во временную папку с максимальным качеством JPEG
    - Открытие изображения в Paint (приоритетно) или стандартном просмотрщике
    - Автоматическое закрытие предыдущего окна при открытии нового
    - Очистку временных файлов при завершении программы
    - Различение временных и постоянных файлов (постоянные НЕ удаляются)

    Attributes:
        _temp_folder: Путь к временной папке для хранения изображений
        _initialized: Флаг инициализации класса
        _temp_files: Множество путей к временным файлам для отслеживания
        _current_process: Текущий запущенный процесс просмотрщика
        _current_file_path: Путь к текущему открытому файлу
        _current_file_is_temp: Флаг, является ли текущий файл временным
    """
    _temp_folder = None
    _initialized = False
    _temp_files = set()
    _current_process = None
    _current_file_path = None
    _current_file_is_temp = False

    @classmethod
    def _initialize(cls):
        """
        Инициализирует класс, создает временную папку при первом обращении.

        Создаёт директорию camera_app_temp в системной временной папке
        и регистрирует очистку при завершении программы через atexit.
        """
        if cls._initialized:
            return

        temp_dir = tempfile.gettempdir()
        cls._temp_folder = Path(temp_dir) / "camera_app_temp"
        cls._temp_folder.mkdir(exist_ok=True)
        atexit.register(cls._cleanup)
        cls._initialized = True

    @classmethod
    def _kill_process_tree(cls, pid: int):
        """
        Рекурсивно завершает процесс и всех его потомков.

        Используется для гарантированного закрытия Paint и всех связанных
        с ним процессов. Сначала завершаются дочерние процессы, затем родительский.

        Args:
            pid: ID процесса для завершения
        """
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)

            # Сначала завершаем дочерние процессы
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Ждём завершения дочерних процессов
            psutil.wait_procs(children, timeout=3)

            # Завершаем родительский процесс
            try:
                parent.terminate()
                parent.wait(timeout=2)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                try:
                    parent.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except (psutil.NoSuchProcess, Exception):
            pass

    @classmethod
    def _close_current_viewer(cls):
        """
        Закрывает текущее открытое окно просмотрщика.

        Завершает дерево процессов текущего просмотрщика,
        затем удаляет связанный временный файл с диска (ЕСЛИ ОН ВРЕМЕННЫЙ).
        Постоянные файлы (открытые через open_file) НЕ УДАЛЯЮТСЯ.
        """
        try:
            # Завершаем процесс и всех его потомков
            if cls._current_process is not None:
                try:
                    cls._kill_process_tree(cls._current_process.pid)
                except Exception:
                    pass
                cls._current_process = None

            # Удаляем текущий файл ТОЛЬКО если он временный
            if cls._current_file_path is not None and cls._current_file_is_temp:
                cls._delete_file(cls._current_file_path)
                cls._current_file_path = None
                cls._current_file_is_temp = False

        except Exception:
            pass

    @classmethod
    def open_frame(cls, frame: np.ndarray,
                   filename_prefix: str = "camera") -> bool:
        """
        Открывает frame (numpy array) в Paint или стандартном просмотрщике.

        Предыдущее открытое окно автоматически закрывается перед открытием нового.
        Изображение сохраняется во временную папку в формате JPEG с качеством 100%.

        Args:
            frame: Кадр от OpenCV (numpy array)
            filename_prefix: Префикс для имени временного файла

        Returns:
            True если изображение успешно открыто, False в случае ошибки
        """
        cls._initialize()

        try:
            if frame is None or not isinstance(frame, np.ndarray):
                return False

            # Закрываем предыдущее окно перед открытием нового
            cls._close_current_viewer()

            # Генерируем уникальное имя файла с временной меткой и PID
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{filename_prefix}_{timestamp}_{os.getpid()}.jpg"
            file_path = cls._temp_folder / filename

            # Сохраняем frame в JPG с качеством 100%
            success = cv2.imwrite(
                str(file_path),
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, 100]
            )

            if not success or not file_path.exists():
                return False

            # Проверяем размер файла (должен быть больше 0 байт)
            if file_path.stat().st_size == 0:
                file_path.unlink()
                return False

            # Добавляем файл в список отслеживаемых временных файлов
            cls._temp_files.add(str(file_path))

            # Открываем файл в просмотрщике
            success = cls._open_image_file(str(file_path))
            if success:
                cls._current_file_path = str(file_path)
                cls._current_file_is_temp = True  # Помечаем как временный
            else:
                cls._delete_file(file_path)

            return success

        except Exception:
            return False

    @classmethod
    def open_file(cls, file_path: str | Path) -> bool:
        """
        Открывает существующий файл изображения в Paint или стандартном просмотрщике.

        Предыдущее открытое окно автоматически закрывается перед открытием нового.
        Файл НЕ удаляется при закрытии просмотрщика (в отличие от open_frame),
        так как считается, что пользователь работает с постоянным файлом.

        Args:
            file_path: Путь к файлу изображения (строка или Path)

        Returns:
            True если изображение успешно открыто, False в случае ошибки
        """
        cls._initialize()

        try:
            # Преобразуем в строку и проверяем существование
            path_str = str(file_path)
            if not os.path.exists(path_str):
                return False

            # Проверяем, что файл является изображением (по расширению)
            valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif', '.webp'}
            ext = Path(path_str).suffix.lower()
            if ext not in valid_extensions:
                return False

            # Закрываем предыдущее окно перед открытием нового
            cls._close_current_viewer()

            # Открываем файл в просмотрщике
            success = cls._open_image_file(path_str)
            if success:
                cls._current_file_path = path_str
                cls._current_file_is_temp = False  # Помечаем как постоянный (НЕ УДАЛЯТЬ)
            else:
                cls._current_process = None

            return success

        except Exception:
            return False

    @classmethod
    def _find_paint_path(cls) -> str | None:
        """
        Находит путь к исполняемому файлу Paint на системе.

        Проверяет стандартные пути установки Windows,
        затем выполняет поиск через системную переменную PATH.

        Returns:
            Путь к mspaint.exe или None, если Paint не найден
        """
        standard_paths = [
            r"C:\Windows\System32\mspaint.exe",
            r"C:\Windows\System32\mspaint"
        ]

        for path in standard_paths:
            if os.path.exists(path):
                return path

        # Ищем через PATH с помощью where
        try:
            result = subprocess.run(
                ["where", "mspaint.exe"],
                capture_output=True,
                text=True,
                shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass

        return None

    @classmethod
    def _open_image_file(cls, file_path: str) -> bool:
        """
        Открывает файл изображения в Paint или стандартном просмотрщике.

        При наличии Paint используется он (с сохранением PID процесса),
        иначе — стандартный просмотрщик Windows через os.startfile.

        Args:
            file_path: Путь к файлу изображения

        Returns:
            True если изображение успешно открыто, False в случае ошибки
        """
        try:
            paint_path = cls._find_paint_path()

            if paint_path:
                # Открываем в Paint без shell=True, чтобы получить PID самого Paint
                cls._current_process = subprocess.Popen(
                    [paint_path, file_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Для стандартного просмотрщика используем os.startfile
                os.startfile(file_path)
                cls._current_process = None

            return True

        except Exception:
            cls._current_process = None
            return False

    @classmethod
    def _delete_file(cls, file_path) -> bool:
        """
        Удаляет файл с диска и убирает из списка отслеживания.

        Перед удалением делается небольшая задержка для гарантии
        освобождения файла операционной системой.

        Args:
            file_path: Путь к файлу (строка или Path)

        Returns:
            True если файл успешно удалён, False в случае ошибки
        """
        try:
            path_str = str(file_path) if isinstance(file_path, Path) else file_path

            # Даём время на освобождение файла операционной системой
            time.sleep(0.2)

            if os.path.exists(path_str):
                os.unlink(path_str)

            if path_str in cls._temp_files:
                cls._temp_files.remove(path_str)

            return True

        except Exception:
            return False

    @classmethod
    def close_viewer(cls):
        """
        Публичный метод для принудительного закрытия текущего просмотрщика.

        Может вызываться извне для ручного управления окном просмотра.
        """
        cls._close_current_viewer()

    @classmethod
    def _cleanup(cls) -> int:
        """
        Очищает временные файлы при завершении программы.

        Закрывает просмотрщик, удаляет все временные файлы,
        очищает отслеживание и удаляет временную папку, если она пуста.

        Returns:
            Количество успешно удалённых временных файлов
        """
        cls._close_current_viewer()

        deleted_count = 0
        for file_path in list(cls._temp_files):
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                    deleted_count += 1
            except Exception:
                continue

        cls._temp_files.clear()
        try:
            if cls._temp_folder and cls._temp_folder.exists():
                if not any(cls._temp_folder.iterdir()):
                    cls._temp_folder.rmdir()
        except Exception:
            pass

        return deleted_count


def open_frame_in_viewer(frame: np.ndarray) -> bool:
    """
    Быстрый вызов для открытия frame в просмотрщике.

    Предыдущее окно автоматически закрывается перед открытием нового.
    Является удобной обёрткой над ImageViewer.open_frame().

    Args:
        frame: Кадр от OpenCV (numpy array)

    Returns:
        True если изображение успешно открыто, False в случае ошибки
    """
    return ImageViewer.open_frame(frame)


def open_file_in_viewer(file_path: str | Path, page=None, config=None) -> bool:
    """
    Быстрый вызов для открытия существующего файла изображения в просмотрщике.

    Предыдущее окно автоматически закрывается перед открытием нового.
    При ошибке показывает предупреждение через show_warning.

    Args:
        file_path: Путь к файлу изображения
        page: Страница Flet для показа предупреждения (опционально)
        config: Конфигурация для show_warning (опционально)

    Returns:
        True если изображение успешно открыто, False в случае ошибки
    """
    # Проверяем существование файла перед вызовом
    path_str = str(file_path)
    if not os.path.exists(path_str):
        if page and config:
            show_warning(
                "Ошибка открытия файла",
                f"Файл не найден:\n{path_str}",
                page,
                config
            )
        return False

    # Проверяем расширение
    valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif', '.webp'}
    ext = Path(path_str).suffix.lower()
    if ext not in valid_extensions:
        if page and config:
            show_warning(
                "Ошибка открытия файла",
                f"Файл не является изображением:\n{path_str}\n\n"
                f"Поддерживаемые форматы: {', '.join(valid_extensions)}",
                page,
                config
            )
        return False

    result = ImageViewer.open_file(file_path)

    if not result and page and config:
        show_warning(
            "Ошибка открытия файла",
            f"Не удалось открыть файл:\n{path_str}\n\n"
            f"Возможно, программа просмотра не найдена.",
            page,
            config
        )

    return result


def close_viewer():
    """
    Принудительно закрывает текущее окно просмотрщика.

    Удобная обёртка над ImageViewer.close_viewer() для использования
    в других модулях без прямого обращения к классу.
    """
    ImageViewer.close_viewer()