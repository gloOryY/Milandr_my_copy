import os
import sys
import logging
import shutil
from datetime import datetime
from typing import Final, List, Tuple
from logging.handlers import RotatingFileHandler


class LoggerConfig:
    """
    Конфигурация логгера.

    Содержит все настраиваемые параметры для системы логирования:
    - Пути к файлам логов
    - Уровни логирования
    - Форматы вывода
    - Параметры ротации логов

    Attributes:
        LOG_DIR: Директория для хранения лог-файлов
        LOG_LEVEL: Уровень логирования (по умолчанию DEBUG)
        MAX_BYTES: Максимальный размер лог-файла перед ротацией (5MB)
        LOG_FORMAT: Формат строки лога
        LOGGER_NAME: Имя корневого логгера
        DATE_FORMAT: Формат даты/времени в логах
        BACKUP_COUNT: Количество сохраняемых архивных лог-файлов
        MAX_LOG_DIR_SIZE_BYTES: Максимальный размер всей папки логов (1 ГБ)
        TARGET_LOG_DIR_SIZE_BYTES: Целевой размер после очистки (800 МБ)
    """
    LOG_DIR: Final[str] = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
    )

    LOG_LEVEL: Final[int] = logging.DEBUG
    MAX_BYTES: Final[int] = 5 * 1024 * 1024  # 5 МБ
    LOG_FORMAT: Final[str] = '%(asctime)s - %(levelname)s - %(message)s'
    LOGGER_NAME: Final[str] = 'ledger_app'
    DATE_FORMAT: Final[str] = '%Y-%m-%d %H:%M:%S'
    BACKUP_COUNT: Final[int] = 3

    # Лимиты размера папки логов
    MAX_LOG_DIR_SIZE_BYTES: Final[int] = 1 * 1024 * 1024 * 1024  # 1 ГБ
    TARGET_LOG_DIR_SIZE_BYTES: Final[int] = 800 * 1024 * 1024  # 800 МБ

    @staticmethod
    def get_session_timestamp() -> str:
        """
        Генерирует timestamp для сессии логирования в формате ГГГГ-ММ-ДД_ЧЧ-ММ-СС.
        Этот timestamp будет использоваться как имя папки сессии.

        Returns:
            str: timestamp сессии
        """
        return datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    @staticmethod
    def get_session_dir_name() -> str:
        """
        Возвращает имя директории для текущей сессии логирования.

        Returns:
            str: Имя директории в формате ГГГГ-ММ-ДД_ЧЧ-ММ-СС
        """
        return LoggerConfig.get_session_timestamp()


class LogDirectoryManager:
    """
    Менеджер для управления размером директории с логами.

    Обеспечивает:
    - Проверку текущего размера папки логов
    - Очистку старых логов при превышении лимита
    - Упорядоченное удаление по дате создания
    """

    @staticmethod
    def get_directory_size(directory_path: str) -> int:
        """
        Вычисляет общий размер всех файлов в директории и её поддиректориях.

        Args:
            directory_path: Путь к директории

        Returns:
            int: Размер директории в байтах
        """
        total_size = 0
        if not os.path.exists(directory_path):
            return 0

        for dirpath, dirnames, filenames in os.walk(directory_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, FileNotFoundError):
                    continue
        return total_size

    @staticmethod
    def get_session_directories(log_dir: str) -> List[Tuple[str, float, int]]:
        """
        Возвращает список сессий логов с их метаданными.

        Args:
            log_dir: Путь к корневой директории логов

        Returns:
            List[Tuple[str, float, int]]: Список кортежей (путь, timestamp_создания, размер)
        """
        sessions = []
        if not os.path.exists(log_dir):
            return sessions

        for session_name in os.listdir(log_dir):
            session_path = os.path.join(log_dir, session_name)
            if not os.path.isdir(session_path):
                continue

            try:
                # Парсим timestamp из имени папки
                # Формат: YYYY-MM-DD_HH-MM-SS
                dt = datetime.strptime(session_name, '%Y-%m-%d_%H-%M-%S')
                timestamp = dt.timestamp()

                # Вычисляем размер папки
                size = LogDirectoryManager.get_directory_size(session_path)

                sessions.append((session_path, timestamp, size))
            except ValueError:
                # Если имя папки не соответствует формату timestamp, пропускаем
                continue

        # Сортируем по timestamp (старые в начале)
        sessions.sort(key=lambda x: x[1])
        return sessions

    @staticmethod
    def cleanup_old_logs(log_dir: str, max_size_bytes: int, target_size_bytes: int) -> Tuple[int, int]:
        """
        Очищает старые логи при превышении лимита размера.

        Args:
            log_dir: Путь к корневой директории логов
            max_size_bytes: Максимальный допустимый размер (при превышении начинаем очистку)
            target_size_bytes: Целевой размер после очистки

        Returns:
            Tuple[int, int]: (количество удалённых сессий, освобождённое место в байтах)
        """
        current_size = LogDirectoryManager.get_directory_size(log_dir)
        if current_size <= max_size_bytes:
            return 0, 0

        # Получаем список сессий, отсортированных по дате (старые в начале)
        sessions = LogDirectoryManager.get_session_directories(log_dir)

        deleted_count = 0
        freed_bytes = 0

        # Удаляем самые старые сессии, пока не достигнем целевого размера
        for session_path, _, session_size in sessions:
            if current_size <= target_size_bytes:
                break

            try:
                # Удаляем всю папку сессии
                shutil.rmtree(session_path)
                deleted_count += 1
                freed_bytes += session_size
                current_size -= session_size

                logging.getLogger(LoggerConfig.LOGGER_NAME).info(
                    f"Удалена старая сессия логов: {os.path.basename(session_path)} "
                    f"(размер: {session_size / (1024 * 1024):.2f} МБ)"
                )
            except Exception as e:
                logging.getLogger(LoggerConfig.LOGGER_NAME).error(
                    f"Ошибка при удалении сессии логов {session_path}: {e}"
                )

        if deleted_count > 0:
            final_size = LogDirectoryManager.get_directory_size(log_dir)
            logging.getLogger(LoggerConfig.LOGGER_NAME).info(
                f"Очистка логов завершена. Удалено {deleted_count} сессий, "
                f"освобождено {freed_bytes / (1024 * 1024):.2f} МБ, "
                f"текущий размер: {final_size / (1024 * 1024):.2f} МБ"
            )

        return deleted_count, freed_bytes


class LoggerFactory:
    """
    Фабрика для создания и настройки логгера.

    Предоставляет методы для:
    - Создания форматтера логов
    - Обеспечения существования лог-директории сессии
    - Проверки и очистки логов при превышении лимита
    - Создания обработчиков (файловые и консольный)
    - Полной настройки логгера с разделением на краткие и подробные логи
    """

    @staticmethod
    def create_formatter() -> logging.Formatter:
        """
        Создает форматтер логов с заданным форматом.

        Returns:
            logging.Formatter: Форматтер с настроенным форматом вывода и даты.

        Examples:
            >>> formatter = LoggerFactory.create_formatter()
            >>> isinstance(formatter, logging.Formatter)
            True
        """
        return logging.Formatter(
            LoggerConfig.LOG_FORMAT,
            datefmt=LoggerConfig.DATE_FORMAT
        )

    @staticmethod
    def check_and_cleanup_logs() -> None:
        """
        Проверяет размер папки логов и очищает старые логи при необходимости.

        Выполняет очистку если общий размер логов превышает MAX_LOG_DIR_SIZE_BYTES,
        удаляя самые старые сессии до достижения TARGET_LOG_DIR_SIZE_BYTES.
        """
        try:
            deleted_count, freed_bytes = LogDirectoryManager.cleanup_old_logs(
                LoggerConfig.LOG_DIR,
                LoggerConfig.MAX_LOG_DIR_SIZE_BYTES,
                LoggerConfig.TARGET_LOG_DIR_SIZE_BYTES
            )

            if deleted_count == 0:
                current_size = LogDirectoryManager.get_directory_size(LoggerConfig.LOG_DIR)
                if current_size > LoggerConfig.MAX_LOG_DIR_SIZE_BYTES:
                    logging.getLogger(LoggerConfig.LOGGER_NAME).warning(
                        f"Размер папки логов превышает лимит ({current_size / (1024 * 1024 * 1024):.2f} ГБ), "
                        f"но очистка не выполнена (нет сессий для удаления или ошибка)"
                    )

        except Exception as e:
            logging.getLogger(LoggerConfig.LOGGER_NAME).error(
                f"Ошибка при проверке/очистке логов: {e}"
            )

    @staticmethod
    def ensure_session_directory(session_dir: str) -> None:
        """
        Создает директорию для текущей сессии логирования, если она не существует.
        Перед созданием проверяет и очищает старые логи при необходимости.

        Args:
            session_dir: Путь к директории сессии

        Raises:
            OSError: Если не удалось создать директорию.

        Examples:
            >>> LoggerFactory.ensure_session_directory("test_session")
            >>> os.path.exists(os.path.join(LoggerConfig.LOG_DIR, "test_session"))
            True
        """
        # Проверяем и очищаем логи перед созданием новой сессии
        LoggerFactory.check_and_cleanup_logs()

        # Создаем директорию сессии
        os.makedirs(session_dir, exist_ok=True)

    @staticmethod
    def get_current_session_dir() -> str:
        """
        Возвращает путь к директории текущей сессии логирования.
        Создает директорию, если она не существует.

        Returns:
            str: Полный путь к директории сессии
        """
        session_name = LoggerConfig.get_session_dir_name()
        session_dir = os.path.join(LoggerConfig.LOG_DIR, session_name)
        LoggerFactory.ensure_session_directory(session_dir)
        return session_dir

    @staticmethod
    def create_detailed_file_handler() -> RotatingFileHandler:
        """
        Создает файловый обработчик для подробных логов (включая DEBUG).
        Логи сохраняются в директории текущей сессии с суффиксом '_detailed.log'.

        Returns:
            RotatingFileHandler: Настроенный обработчик для записи
                                 подробных логов в файл.

        Examples:
            >>> handler = LoggerFactory.create_detailed_file_handler()
            >>> isinstance(handler, RotatingFileHandler)
            True
            >>> handler.level == logging.DEBUG
            True
        """
        session_dir = LoggerFactory.get_current_session_dir()

        # Имя файла с суффиксом '_detailed.log'
        session_timestamp = LoggerConfig.get_session_timestamp()
        log_filename = f"{session_timestamp}_detailed.log"
        log_file = os.path.join(session_dir, log_filename)

        handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=LoggerConfig.MAX_BYTES,
            backupCount=LoggerConfig.BACKUP_COUNT,
            encoding='utf-8'
        )
        handler.setFormatter(LoggerFactory.create_formatter())
        handler.setLevel(logging.DEBUG)  # Включаем DEBUG для подробных логов
        return handler

    @staticmethod
    def create_short_file_handler() -> RotatingFileHandler:
        """
        Создает файловый обработчик для кратких логов (без DEBUG).
        Логи сохраняются в директории текущей сессии с суффиксом '_short.log'.

        Returns:
            RotatingFileHandler: Настроенный обработчик для записи
                                 кратких логов в файл.

        Examples:
            >>> handler = LoggerFactory.create_short_file_handler()
            >>> isinstance(handler, RotatingFileHandler)
            True
            >>> handler.level == logging.INFO
            True
        """
        session_dir = LoggerFactory.get_current_session_dir()

        # Имя файла с суффиксом '_short.log'
        session_timestamp = LoggerConfig.get_session_timestamp()
        log_filename = f"{session_timestamp}_short.log"
        log_file = os.path.join(session_dir, log_filename)

        handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=LoggerConfig.MAX_BYTES,
            backupCount=LoggerConfig.BACKUP_COUNT,
            encoding='utf-8'
        )
        handler.setFormatter(LoggerFactory.create_formatter())
        handler.setLevel(logging.INFO)  # Исключаем DEBUG, начинаем с INFO
        return handler

    @staticmethod
    def create_console_handler() -> logging.StreamHandler:
        """
        Создает консольный обработчик для вывода в stdout.
        Уровень логирования для консоли можно настроить отдельно.

        Returns:
            logging.StreamHandler: Настроенный консольный обработчик.

        Examples:
            >>> handler = LoggerFactory.create_console_handler()
            >>> isinstance(handler, logging.StreamHandler)
            True
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(LoggerFactory.create_formatter())
        # Устанавливаем тот же уровень что и для подробного файлового логгера
        handler.setLevel(logging.DEBUG)  # Было: handler.setLevel(logging.INFO)
        return handler

    @staticmethod
    def setup_logger() -> logging.Logger:
        """
        Настраивает и возвращает готовый к использованию логгер.
        Создает логгер с двумя файловыми обработчиками:
        1. Для подробных логов (включая DEBUG)
        2. Для кратких логов (без DEBUG)
        3. Консольный обработчик

        Выполняет:
        - Создание нового логгера
        - Установку уровня логирования
        - Проверку и очистку старых логов
        - Добавление файловых и консольного обработчиков
        - Отключение пропагации сообщений в родительские логгеры

        Returns:
            logging.Logger: Полностью настроенный логгер приложения.

        Examples:
            >>> logger = LoggerFactory.setup_logger()
            >>> logger.name == LoggerConfig.LOGGER_NAME
            True
            >>> len(logger.handlers)
            3
            >>> all(isinstance(h, (RotatingFileHandler, logging.StreamHandler))
            ...     for h in logger.handlers)
            True
        """
        app_logger = logging.getLogger(LoggerConfig.LOGGER_NAME)

        app_logger.handlers.clear()

        # Устанавливаем минимальный уровень для самого логгера
        app_logger.setLevel(LoggerConfig.LOG_LEVEL)

        # Добавляем обработчик для подробных логов (с DEBUG)
        app_logger.addHandler(LoggerFactory.create_detailed_file_handler())

        # Добавляем обработчик для кратких логов (без DEBUG)
        app_logger.addHandler(LoggerFactory.create_short_file_handler())

        # Добавляем консольный обработчик
        app_logger.addHandler(LoggerFactory.create_console_handler())

        app_logger.propagate = False

        return app_logger


# Глобальный логгер, доступный для импорта
logger: logging.Logger = LoggerFactory.setup_logger()

# Логируем информацию о текущей сессии
session_dir = LoggerFactory.get_current_session_dir()
current_size = LogDirectoryManager.get_directory_size(LoggerConfig.LOG_DIR)
logger.info(f"Сессия логирования создана: {os.path.basename(session_dir)}")
logger.info(f"Текущий размер папки логов: {current_size / (1024 * 1024 * 1024):.2f} ГБ")
