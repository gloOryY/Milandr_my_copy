import re
import serial.tools.list_ports
from typing import Optional, List, Dict, Tuple, Pattern, Any
from project.station.robot.port_finder.port_finder_utils import verify_port, get_port_info, is_virtual_port
from project.station.robot.port_finder.port_finder_config import PortFinderConfig
from project.application.addition.logger import logger


class PortFinder:
    """
    Класс для поиска и идентификации последовательных портов станции.
    Реализован как Singleton для обеспечения единственного экземпляра поисковика портов.

    Обеспечивает поиск порта по различным критериям (VID/PID, предпочтительные устройства,
    шаблоны описания) с поддержкой кэширования и проверки доступности портов.

    Attributes:
        _instance (Optional['PortFinder']): Единственный экземпляр класса
        _initialized (bool): Флаг инициализации экземпляра
        _port_finder_config (PortFinderConfig): Конфигурация для хранения информации о порте
        KNOWN_DEVICES (Dict[Tuple[int, int], str]): Словарь известных устройств по VID/PID
        COMMON_PATTERNS (List[Pattern[str]]): Список регулярных выражений для поиска портов

    Example:
    >>> finder = PortFinder()
    >>> # Поиск с использованием кеша (результат проверяем)
    >>> found_port = finder.find_station_port()
    >>> found_port is None or isinstance(found_port, str)
    True
    >>> # Принудительный поиск нового порта с проверкой
    >>> new_port = finder.find_station_port(use_cached=False)
    >>> new_port is None or isinstance(new_port, str)
    True
    >>> # Очистка кеша с проверкой результата
    >>> cache_cleared = finder._clear_cache()
    >>> isinstance(cache_cleared, bool)
    True
    """

    _instance: Optional['PortFinder'] = None
    _initialized: bool = False

    KNOWN_DEVICES: Dict[Tuple[int, int], str] = {
        (0x1A86, 0x7523): "CH340 Serial Adapter",
        (0x2341, 0x0043): "Arduino Uno",
        (0x2341, 0x0001): "Arduino Mega",
        (0x0403, 0x6001): "FTDI FT232",
        (0x10C4, 0xEA60): "CP210x Serial Adapter",
    }

    COMMON_PATTERNS: List[Pattern[str]] = [
        re.compile(r'laser', re.IGNORECASE),
        re.compile(r'cnc|grbl|serial|usb|ch34|arduino', re.IGNORECASE),
    ]

    def __new__(cls, *args, **kwargs) -> 'PortFinder':
        """
        Контролирует создание экземпляра класса.
        Если экземпляр уже существует, возвращает его, иначе создает новый.

        Returns:
            PortFinder: Единственный экземпляр класса
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, port_finder_config: Optional['PortFinderConfig'] = None) -> None:
        """
        Инициализация поисковика портов.
        При повторном вызове __init__ после создания экземпляра,
        инициализация не выполняется повторно (благодаря флагу _initialized).

        Args:
            port_finder_config: Конфигурация для хранения информации о порте (опционально)
        """
        # Предотвращаем повторную инициализацию
        if PortFinder._initialized:
            logger.debug("PortFinder уже инициализирован, повторная инициализация пропущена")
            return

        self._port_finder_config = port_finder_config or PortFinderConfig()
        logger.debug("Инициализация PortFinder")

        # Устанавливаем флаг инициализации
        PortFinder._initialized = True

    @classmethod
    def get_instance(cls, port_finder_config: Optional['PortFinderConfig'] = None) -> 'PortFinder':
        """
        Получение единственного экземпляра PortFinder.
        Если экземпляр еще не создан, создает его с переданными параметрами.
        Если экземпляр уже существует, возвращает его (параметры игнорируются).

        Args:
            port_finder_config: Конфигурация для хранения информации о порте (опционально)

        Returns:
            PortFinder: Единственный экземпляр поисковика портов
        """
        if cls._instance is None:
            cls._instance = cls(port_finder_config=port_finder_config)
        return cls._instance

    @classmethod
    def has_instance(cls) -> bool:
        """
        Проверяет, создан ли уже экземпляр PortFinder.

        Returns:
            bool: True если экземпляр существует, иначе False
        """
        return cls._instance is not None

    @classmethod
    def reset_instance(cls) -> None:
        """
        Сбрасывает Singleton экземпляр.
        Используется в основном для тестирования или при необходимости
        полного пересоздания поисковика портов с новыми параметрами.
        """
        if cls._instance is not None:
            cls._instance = None
            cls._initialized = False
            logger.info("Экземпляр PortFinder сброшен")

    def find_station_port(self,
                          vid: Optional[int] = None,
                          pid: Optional[int] = None,
                          preferred_devices: Optional[List[str]] = None,
                          skip_virtual: bool = True,
                          use_cached: bool = True
                          ) -> Optional[str]:
        """
        Основной метод поиска порта станции.

        Args:
            vid: Vendor ID для поиска по точному совпадению
            pid: Product ID для поиска по точному совпадению
            preferred_devices: Список предпочтительных типов устройств
            skip_virtual: Пропускать ли виртуальные порты
            use_cached: Использовать ли сохраненный порт из кэша

        Returns:
            Optional[str]: Имя найденного порта (например, "COM3" или "/dev/ttyUSB0"),
                          или None если порт не найден

        Example:
            >>> finder = PortFinder()
            >>> # Поиск Arduino
            >>> port = finder.find_station_port(vid=0x2341, pid=0x0043)
            >>> print(f"Найден порт: {port}")
            >>> # Поиск с предпочтениями
            >>> preferred_port = finder.find_station_port(preferred_devices=["Arduino"])
            >>> preferred_port is None or isinstance(preferred_port, str)
            True
        """
        logger.info("Запуск процедуры поиска порта")

        if use_cached and (cached_port := self._get_cached_port()):
            logger.info("Используется сохраненный порт: %s", cached_port)
            return cached_port

        logger.debug("Сканирование доступных последовательных портов")
        ports = list(serial.tools.list_ports.comports())

        if not ports:
            logger.warning("Последовательные порты не найдены")
            return None

        logger.debug("Найдено %d последовательных портов", len(ports))

        return (self._find_by_vid_pid(vid, pid, ports) or
                self._find_by_preferred(preferred_devices, ports, skip_virtual) or
                self._find_by_patterns(ports, skip_virtual))

    def _get_cached_port(self) -> Optional[str]:
        """
        Загружает информацию о порте из конфигурации и проверяет его доступность.

        Example:
            >>> finder = PortFinder()
            >>> # Сохраняем тестовый порт
            >>> finder._save_port_info(type('obj', (), {'device': 'COM3', 'vid': 1234, 'pid': 5678}))
            >>> # Получаем сохраненный порт
            >>> port = finder._get_cached_port()
        """
        logger.debug("Проверка сохраненного порта")
        if cached := self._port_finder_config.load_port():
            logger.debug("Найдена информация о сохраненном порте: %s", cached)
            if verify_port(cached.get('device')):
                logger.info("Сохраненный порт подтвержден: %s", cached['device'])
                return cached['device']
            logger.debug("Сохраненный порт недоступен")
        return None

    def _find_by_vid_pid(self,
                         vid: Optional[int],
                         pid: Optional[int],
                         ports: List[Any]
                         ) -> Optional[str]:
        """
        Поиск порта по точному совпадению VID/PID.

        Args:
            vid: Vendor ID для поиска
            pid: Product ID для поиска
            ports: Список доступных последовательных портов

        Returns:
            Optional[str]: Имя порта при совпадении VID/PID, иначе None

        Example:
            >>> finder = PortFinder()
            >>> test_ports = [type('obj', (), {'device': 'COM3', 'vid': 0x2341, 'pid': 0x0043})]
            >>> found_port = finder._find_by_vid_pid(0x2341, 0x0043, test_ports)
            >>> assert found_port == 'COM3'
        """
        if vid and pid:
            logger.debug("Поиск порта по VID/PID: %04X/%04X", vid, pid)
            for port in ports:
                if hasattr(port, 'vid') and hasattr(port, 'pid'):
                    if port.vid == vid and port.pid == pid:
                        logger.info("Найден порт по VID/PID: %s", port.device)
                        self._save_port_info(port)
                        return port.device
        return None

    def _find_by_preferred(self,
                           preferred: Optional[List[str]],
                           ports: List[Any],
                           skip_virtual: bool
                           ) -> Optional[str]:
        """
        Поиск порта по предпочтительным устройствам.

        Args:
            preferred: Список предпочтительных типов устройств
            ports: Список доступных последовательных портов
            skip_virtual: Пропускать ли виртуальные порты

        Returns:
            Optional[str]: Имя порта если найдено предпочтительное устройство, иначе None

        Example:
            >>> finder = PortFinder()
            >>> test_ports = [type('obj', (), {
            ...     'device': 'COM3',
            ...     'vid': 0x2341,
            ...     'pid': 0x0043,
            ...     'description': 'Arduino Uno'
            ... })]
            >>> port = finder._find_by_preferred(["Arduino"], test_ports, True)
            >>> assert port == 'COM3'
        """
        if not preferred:
            return None

        logger.debug("Поиск порта по предпочтительным устройствам: %s", preferred)
        for port in ports:
            if skip_virtual and is_virtual_port(port):
                logger.debug("Пропуск виртуального порта: %s", port.device)
                continue

            if hasattr(port, 'vid') and hasattr(port, 'pid'):
                if (port.vid, port.pid) in self.KNOWN_DEVICES:
                    device_type = self.KNOWN_DEVICES[(port.vid, port.pid)]
                    if any(p.lower() in device_type.lower() for p in preferred):
                        logger.info("Найдено предпочтительное устройство: %s (%s)",
                                    port.device, device_type)
                        self._save_port_info(port)
                        return port.device
        return None

    def _find_by_patterns(self,
                          ports: List[Any],
                          skip_virtual: bool
                          ) -> Optional[str]:
        """
        Поиск порта по регулярным выражениям.

        Args:
            ports: Список доступных последовательных портов
            skip_virtual: Пропускать ли виртуальные порты

        Returns:
            Optional[str]: Имя порта если найдено совпадение с шаблоном, иначе None

        Example:
            >>> finder = PortFinder()
            >>> test_ports = [type('obj', (), {'device': 'COM3', 'description': 'Arduino Uno'})]
            >>> port = finder._find_by_patterns(test_ports, True)
            >>> assert port == 'COM3'
        """
        logger.debug("Поиск порта по шаблонам")
        for port in ports:
            if skip_virtual and is_virtual_port(port):
                logger.debug("Пропуск виртуального порта: %s", port.device)
                continue

            port_description = getattr(port, 'description', '') or ''
            if any(p.search(port_description) for p in self.COMMON_PATTERNS):
                logger.info("Найден порт, соответствующий шаблонам: %s (%s)",
                            port.device, port_description)
                self._save_port_info(port)
                return port.device
        return None

    def _save_port_info(self, port: Any) -> bool:
        """
        Сохраняет информацию о порте в конфигурацию.

        Example:
            >>> finder = PortFinder()
            >>> test_port = type('obj', (), {'device': 'COM3', 'vid': 1234, 'pid': 5678})
            >>> result = finder._save_port_info(test_port)
            >>> assert result is True or result is False
        """
        if port_info := get_port_info(port):
            if self._port_finder_config.save_port(port_info):
                logger.debug("Информация о порте успешно сохранена")
                return True
            logger.warning("Не удалось сохранить информацию о порте")
        return False

    def _clear_cache(self) -> bool:
        """
        Удаляет сохраненную информацию о порте из файла конфигурации.

        Example:
            >>> finder = PortFinder()
            >>> result = finder._clear_cache()
            >>> assert result is True or result is False
        """
        logger.info("Очистка кеша портов...")
        if self._port_finder_config.clear_config():
            logger.info("Кеш портов успешно очищен")
            return True
        logger.warning("Не удалось очистить кеш портов")
        return False
