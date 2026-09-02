import threading
import json
from pathlib import Path
from typing import Dict, Optional
from project.application.addition.logger import logger


class PortFinderConfig:
    """
    Класс для управления конфигурацией поиска портов станции.
    Реализован как Singleton для обеспечения единственного экземпляра конфигурации.

    Обеспечивает сохранение, загрузку и очистку информации о порте
    в JSON-файле конфигурации. Автоматически создает необходимые директории,
    поддерживает потокобезопасность и валидацию данных.

    Attributes:
        _instance (Optional['PortFinderConfig']): Единственный экземпляр класса
        _initialized (bool): Флаг инициализации экземпляра
        PORT_FINDER_CONFIG_DIR (str): Директория по умолчанию для хранения файла конфигурации.
        PORT_FINDER_CONFIG_FILE (str): Имя файла конфигурации по умолчанию.
        _lock (threading.Lock): Блокировка для потокобезопасного доступа к файлу.
        _port_finder_config_dir (Path): Директория, в которой хранится файл конфигурации.
        _port_finder_config_file (str): Имя файла конфигурации.
        _port_finder_config_path (Path): Полный путь к файлу конфигурации.
    """

    _instance: Optional['PortFinderConfig'] = None
    _initialized: bool = False

    PORT_FINDER_CONFIG_DIR: str = "project/station/robot/port_finder"
    PORT_FINDER_CONFIG_FILE: str = "port_finder.json"

    def __new__(cls, *args, **kwargs) -> 'PortFinderConfig':
        """
        Контролирует создание экземпляра класса.
        Если экземпляр уже существует, возвращает его, иначе создает новый.

        Returns:
            PortFinderConfig: Единственный экземпляр класса
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 port_finder_config_dir: Optional[str] = None,
                 port_finder_config_file: Optional[str] = None):
        """
        Инициализирует конфигурацию поиска портов.
        При повторном вызове __init__ после создания экземпляра,
        инициализация не выполняется повторно (благодаря флагу _initialized).

        Создает необходимые директории и формирует полный путь к файлу конфигурации.
        Поддерживает пользовательские значения директории и имени файла.

        Args:
            port_finder_config_dir: Пользовательский путь к директории конфигурации.
                        Если не указан, используется значение PORT_FINDER_CONFIG_DIR.
            port_finder_config_file: Пользовательское имя файла конфигурации.
                         Если не указано, используется значение PORT_FINDER_CONFIG_FILE.

        Examples:
            >>> # Использование путей по умолчанию
            >>> port_finder_config = PortFinderConfig()
            >>> print(port_finder_config.port_finder_config_path)
            project/station/port_finder/port_finder.json

            >>> # Использование пользовательских путей
            >>> custom_config = PortFinderConfig(
            ...     port_finder_config_dir="/tmp/my_station",
            ...     port_finder_config_file="custom_port.json"
            ... )
            >>> print(custom_config.port_finder_config_path)
            /tmp/my_station/custom_port.json
        """
        # Предотвращаем повторную инициализацию
        if PortFinderConfig._initialized:
            logger.debug("PortFinderConfig уже инициализирован, повторная инициализация пропущена")
            return

        self._lock: threading = threading.Lock()
        self._port_finder_config_dir: Path = Path(port_finder_config_dir or self.PORT_FINDER_CONFIG_DIR)
        self._port_finder_config_file: str = port_finder_config_file or self.PORT_FINDER_CONFIG_FILE
        self._port_finder_config_path: Path = self._port_finder_config_dir / self._port_finder_config_file
        self._ensure_config_dir_exists()

        # Устанавливаем флаг инициализации
        PortFinderConfig._initialized = True

    @classmethod
    def get_instance(cls,
                     port_finder_config_dir: Optional[str] = None,
                     port_finder_config_file: Optional[str] = None) -> 'PortFinderConfig':
        """
        Получение единственного экземпляра PortFinderConfig.
        Если экземпляр еще не создан, создает его с переданными параметрами.
        Если экземпляр уже существует, возвращает его (параметры игнорируются).

        Args:
            port_finder_config_dir: Пользовательский путь к директории конфигурации
            port_finder_config_file: Пользовательское имя файла конфигурации

        Returns:
            PortFinderConfig: Единственный экземпляр конфигурации
        """
        if cls._instance is None:
            cls._instance = cls(
                port_finder_config_dir=port_finder_config_dir,
                port_finder_config_file=port_finder_config_file
            )
        return cls._instance

    @classmethod
    def has_instance(cls) -> bool:
        """
        Проверяет, создан ли уже экземпляр PortFinderConfig.

        Returns:
            bool: True если экземпляр существует, иначе False
        """
        return cls._instance is not None

    @classmethod
    def reset_instance(cls) -> None:
        """
        Сбрасывает Singleton экземпляр.
        Используется в основном для тестирования или при необходимости
        полного пересоздания конфигурации с новыми параметрами.
        """
        if cls._instance is not None:
            cls._instance = None
            cls._initialized = False
            logger.info("Экземпляр PortFinderConfig сброшен")

    def _ensure_config_dir_exists(self) -> None:
        """
        Проверяет и создает директорию для хранения конфигурации.

        Создает все промежуточные директории, если они не существуют.
        В случае ошибки логирует и пробрасывает исключение.

        Raises:
            Exception: Если не удалось создать директорию.

        Examples:
            >>> port_finder_config = PortFinderConfig()
            >>> port_finder_config._ensure_config_dir_exists()
            >>> # Директория будет создана, если не существует
            >>> assert port_finder_config.port_finder_config_dir.exists()
        """
        try:
            self._port_finder_config_dir.mkdir(parents=True, exist_ok=True)
            logger.debug("Проверена директория конфига: %s", self._port_finder_config_dir)
        except Exception as e:
            logger.error("Ошибка создания директории конфига: %s", str(e))
            raise

    def save_port(self, port_info: Dict[str, str]) -> bool:
        """
        Сохраняет информацию о порте в JSON-файл конфигурации.

        Выполняет базовую валидацию входных данных и блокирует доступ
        к файлу на время записи для потокобезопасности.

        Args:
            port_info: Словарь с информацией о порте, обязательно содержащий:
                      - 'device': имя порта (например, 'COM3')
                      - Дополнительные метаданные о порте (опционально)

        Returns:
            bool: True если сохранение прошло успешно, False в случае ошибки.

        Examples:
            >>> port_finder_config = PortFinderConfig()
            >>> # Успешное сохранение
            >>> port_data = {'device': 'COM3', 'description': 'Main station port'}
            >>> port_finder_config.save_port(port_data)
            True

            >>> # Ошибка валидации - отсутствует 'device'
            >>> invalid_data = {'description': 'No device specified'}
            >>> port_finder_config.save_port(invalid_data)
            False
        """
        if not isinstance(port_info, dict) or "device" not in port_info:
            logger.error("Неверный формат port_info: отсутствует ключ 'device'")
            return False

        with self._lock:
            try:
                with open(self._port_finder_config_path, "w", encoding="utf-8") as f:
                    json.dump(port_info, f, indent=2, ensure_ascii=False)
                logger.info("Информация о порте сохранена в %s", self._port_finder_config_path)
                logger.debug("Сохраненные данные: %s", port_info)
                return True
            except Exception as e:
                logger.error("Ошибка сохранения конфига порта: %s", str(e))
                return False

    def load_port(self) -> Optional[Dict[str, str]]:
        """
        Загружает информацию о порте из JSON-файла конфигурации.
        Безопасно читает файл в потокобезопасном режиме.

        Returns:
            Optional[Dict[str, str]]: Словарь с информацией о порте вида:
                                     {'device': 'COM3', ...} или None,
                                     если файл не существует или произошла ошибка.

        Examples:
            >>> port_finder_config = PortFinderConfig()
            >>> # Загрузка существующего конфига
            >>> _ = port_finder_config.save_port({'device': 'COM4', 'baud': '9600'})
            >>> port_info = port_finder_config.load_port()
            >>> print(port_info)
            {'device': 'COM4', 'baud': '9600'}

            >>> # Загрузка несуществующего конфига
            >>> new_config = PortFinderConfig(port_finder_config_file="nonexistent.json")
            >>> new_config.load_port() is None
            True
        """
        with self._lock:
            try:
                if not self._port_finder_config_path.exists():
                    logger.debug("Конфигурационный файл не существует")
                    return None

                with open(self._port_finder_config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info("Загружена информация о порте из %s", self._port_finder_config_path)
                logger.debug("Загруженные данные: %s", data)
                return data
            except json.JSONDecodeError as e:
                logger.error("Некорректный JSON в конфигурационном файле: %s", str(e))
                return None
            except Exception as e:
                logger.error("Ошибка загрузки конфига порта: %s", str(e))
                return None

    def clear_config(self) -> bool:
        """
        Очищает конфигурационный файл, записывая в него пустой словарь.
        Выполняется в потокобезопасном режиме.

        Returns:
            bool: True если очистка прошла успешно, False в случае ошибки.

        Examples:
            >>> port_finder_config = PortFinderConfig()
            >>> _ = port_finder_config.save_port({'device': 'COM5'})
            >>> port_finder_config.clear_config()
            True
            >>> # После очистки файл существует, но пуст
            >>> port_finder_config.load_port()
            {}
        """
        with self._lock:
            try:
                with open(self._port_finder_config_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=2, ensure_ascii=False)
                logger.info("Конфигурационный файл очищен: %s", self._port_finder_config_path)
                return True
            except Exception as e:
                logger.error("Ошибка очистки конфигурационного файла: %s", str(e))
                return False
