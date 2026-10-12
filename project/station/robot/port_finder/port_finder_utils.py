import serial.tools.list_ports
import datetime
from typing import Dict, Union, Any
from project.application.addition.logger import logger


def verify_port(port_name: str) -> bool:
    """
    Проверяет доступность последовательного порта и его соответствие критериям.

    Examples:
    >>> # Проверка существующего порта
    >>> verify_port('COM3')  # Должен вернуть True для существующего порта
    True

    >>> # Проверка несуществующего порта
    >>> verify_port('NOT_EXIST')  # Всегда False для несуществующих портов
    False

    >>> # Проверка с ошибкой (передаем None вместо строки)
    >>> verify_port(None)  # Обрабатывается исключение, возвращается False
    False
    """
    try:
        logger.debug("Проверка доступности порта: %s", port_name)
        ports = serial.tools.list_ports.comports()

        if not ports:
            logger.warning("Не найдено ни одного последовательного порта")
            return False

        port_exists = any(p.device == port_name for p in ports)

        if port_exists:
            logger.info("Порт %s доступен и соответствует критериям", port_name)
        else:
            logger.warning("Порт %s не найден среди доступных портов", port_name)

        return port_exists

    except Exception as e:
        logger.error("Ошибка при проверке порта %s: %s", port_name, str(e))
        return False


def get_port_info(port: Any) -> Dict[str, Union[str, int, None]]:
    """
    Собирает подробную информацию о последовательном порте.

    Examples:
    >>> # Получение информации о существующем порте
    >>> ports = serial.tools.list_ports.comports()
    >>> if ports:
    ...     port_info = get_port_info(ports[0])
    ...     isinstance(port_info, dict) and 'device' in port_info
    True

    >>> # Передача None
    >>> get_port_info(None)  # Возвращает пустой словарь
    {}

    >>> # Передача объекта без атрибутов порта
    >>> get_port_info(object())  # Возвращает словарь с None значениями
    {'device': None, ...}
    """
    try:
        logger.debug("Получение информации о порте: %s", port.device if port else 'None')

        if not port:
            logger.warning("Передан пустой объект порта")
            return {}

        port_info = {
            'device': port.device,
            'description': port.description,
            'hwid': port.hwid,
            'vid': port.vid if hasattr(port, 'vid') else None,
            'pid': port.pid if hasattr(port, 'pid') else None,
            'serial_number': port.serial_number if hasattr(port, 'serial_number') else None,
            'location': port.location if hasattr(port, 'location') else None,
            'manufacturer': port.manufacturer if hasattr(port, 'manufacturer') else None,
            'product': port.product if hasattr(port, 'product') else None,
            'interface': port.interface if hasattr(port, 'interface') else None,
            'found_at': datetime.datetime.now().isoformat(),
        }

        logger.debug("Собранная информация о порте: %s", port_info)
        return port_info

    except Exception as e:
        logger.error("Ошибка при получении информации о порте: %s", str(e))
        return {}


def is_virtual_port(port: Any) -> bool:
    """
    Определяет, является ли порт виртуальным, на основе его описания.

    Examples:
    >>> # Тест с виртуальным портом
    >>> virtual_port = type('obj', (), {'device': 'COM1', 'description': 'Virtual COM Port'})
    >>> is_virtual_port(virtual_port)
    True

    >>> # Тест с физическим портом
    >>> phys_port = type('obj', (), {'device': 'COM2', 'description': 'USB Serial Device'})
    >>> is_virtual_port(phys_port)
    False

    >>> # Порт без описания
    >>> no_desc_port = type('obj', (), {'device': 'COM3'})
    >>> is_virtual_port(no_desc_port)
    False
    """
    try:
        if not port:
            logger.debug("Передан пустой объект порта")
            return False

        if not port.description:
            logger.debug("Порт %s не имеет описания, считаем физическим", port.device)
            return False

        is_virtual = any(word in port.description.lower()
                         for word in ['bluetooth', 'virtual', 'com0com', 'tcp', 'network'])

        if is_virtual:
            logger.info("Порт %s идентифицирован как виртуальный", port.device)
        else:
            logger.debug("Порт %s считается физическим", port.device)

        return is_virtual

    except Exception as e:
        logger.error("Ошибка при проверке виртуального порта: %s", str(e))
        return False
