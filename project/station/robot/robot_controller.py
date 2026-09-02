import serial
import re
import serial.tools.list_ports
import time
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict

from serial import SerialException

from project.application.addition.exceptions import RobotException
from project.application.addition.logger import logger
from project.configuration.config_manager import ConfigManager
from project.configuration.worker import read_from_json
from project.station.robot.port_finder.port_finder import PortFinder
from project.station.robot.port_finder.port_finder_config import PortFinderConfig
from project.station.robot.port_finder.port_finder_utils import get_port_info


class RobotController:
    """
    Контроллер для управления роботизированной станцией через последовательный порт (ЧПУ-станок).
    Реализован как Singleton для обеспечения единственного экземпляра контроллера.

    Обеспечивает подключение к станции, отправку G-code команд,
    перемещение по координатам, калибровку и управление подключением.

    Особенности:
    - Ленивая загрузка порта: порт ищется при первом подключении, а не при инициализации
    - Проверка и восстановление GRBL-настроек при каждом новом подключении
    - Перед синхронизацией настроек контроллер выводится из состояния Alarm через $X
      (без физического движения осей), так как GRBL отклоняет $-команды в Alarm
      с ошибкой error:8
    - Автоматическая калибровка: если робот не калиброван, калибровка выполняется при первом движении
    - Сброс калибровки при отключении: если USB выдернут, флаг калибровки сбрасывается

    Настройки берутся из project/configuration/robot_config.json. При подключении
    контроллер читает текущие настройки через $$ и $N, перезаписывает только
    отличающиеся значения и выполняет итоговую проверку. Команда $H в этой
    процедуре не используется — калибровка выполняется только вручную.
    """

    _instance: Optional["RobotController"] = None
    _initialized: bool = False
    _robot_config: Optional[Dict[str, Dict[str, str]]] = None

    def __new__(cls, *args, **kwargs) -> "RobotController":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
            self,
            config: "ConfigManager",
            port_finder: Optional["PortFinder"] = None,
            port_finder_config: Optional["PortFinderConfig"] = None,
            baudrate: int = 115200,
            timeout_connection: float = 0.05,
            max_retries: int = 3,
    ) -> None:
        if RobotController._initialized:
            return

        self._port_finder_config = port_finder_config or PortFinderConfig()
        self._port_finder = port_finder or PortFinder(self._port_finder_config)

        self._baudrate: int = baudrate
        self._timeout_connection: float = timeout_connection
        self._max_retries: int = max_retries
        self._connection: Optional[serial.Serial] = None
        self._port: Optional[str] = None
        self._device_type: Optional[str] = None
        self.is_homed: bool = False
        self._port_loaded: bool = False

        self._extreme_coordinates = {
            "x_min": config.extreme_coordinates["x_min"],
            "x_max": config.extreme_coordinates["x_max"],
            "y_min": config.extreme_coordinates["y_min"],
            "y_max": config.extreme_coordinates["y_max"],
            "z_min": config.extreme_coordinates["z_min"],
            "z_max": config.extreme_coordinates["z_max"],
        }

        logger.info(
            "Инициализирован RobotController "
            "(порт будет загружен при первом подключении)"
        )
        RobotController._initialized = True

    def _load_robot_settings_config(self) -> Dict[str, Dict[str, str]]:
        """
        Загружает конфигурацию робота из robot_config.json.
        Использует read_from_json для загрузки с восстановлением значений по умолчанию.
        """
        config_path = "project/configuration/robot_config.json"

        # Значения по умолчанию
        default_config = {
            "settings": {},
            "startup_blocks": {}
        }

        try:
            # Загружаем settings
            settings = read_from_json(config_path, "settings")
            if not isinstance(settings, dict):
                logger.warning("settings в robot_config.json не является словарем, используются значения по умолчанию")
                settings = {}

            # Загружаем startup_blocks
            startup_blocks = read_from_json(config_path, "startup_blocks")
            if not isinstance(startup_blocks, dict):
                logger.warning(
                    "startup_blocks в robot_config.json не является словарем, используются значения по умолчанию")
                startup_blocks = {}

            config = {
                "settings": settings,
                "startup_blocks": startup_blocks
            }

            # Проверяем, что конфиг не пустой
            if not config["settings"] and not config["startup_blocks"]:
                logger.warning(
                    "robot_config.json пуст или содержит некорректные данные, используются значения по умолчанию")

            return config

        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации робота: {e}")
            return default_config

    def _ensure_port_loaded(self) -> bool:
        """
        Ленивая загрузка порта. Ищет порт только при первом обращении.
        """
        if self._port_loaded and self._port is not None:
            return True

        logger.debug("Ленивая загрузка порта...")
        self._port = self._get_valid_port()
        self._port_loaded = True

        if self._port:
            logger.info("Порт загружен: %s", self._port)
            return True

        logger.error("Не удалось найти порт станции")
        return False

    def _ensure_homed(self) -> bool:
        """
        Проверяет, откалиброван ли робот. Если нет — выполняет калибровку.
        """
        if self.is_homed:
            return True

        logger.info("Робот не откалиброван, выполняю автоматическую калибровку...")
        self.home()
        logger.info("Автоматическая калибровка выполнена успешно")
        return True

    def _reset_homed_on_disconnect(self) -> None:
        """Сбрасывает флаг калибровки при обнаружении отключения."""
        if self.is_homed:
            logger.warning("Сброс флага калибровки (робот был отключен)")
        self.is_homed = False

    def _get_valid_port(self) -> Optional[str]:
        """Получает валидный порт из конфига или выполняет автоматический поиск."""
        if port_info := self._port_finder_config.load_port():
            if port := port_info.get("device"):
                if self._verify_port_available(port):
                    logger.info("Используется сохраненный порт: %s", port)
                    return port
                logger.warning("Сохраненный порт %s недоступен", port)

        logger.info("Попытка автоматического поиска порта станции")
        if new_port := self._port_finder.find_station_port(use_cached=False):
            if self._verify_port_available(new_port):
                logger.info("Найден новый порт: %s", new_port)
                return new_port

        logger.error("Не удалось найти подходящий порт станции")
        return None

    def _verify_port_available(self, port: str) -> bool:
        """Проверяет, что COM-порт не занят, например приложением Arduino."""
        try:
            test_conn = serial.Serial(port=port, baudrate=self._baudrate, timeout=0.5)
            test_conn.close()
            return True
        except SerialException:
            return False

    def _find_new_port(self) -> Optional[str]:
        logger.info("Поиск нового порта станции...")
        if new_port := self._port_finder.find_station_port(use_cached=False):
            port_object = next(
                (p for p in serial.tools.list_ports.comports() if p.device == new_port),
                None,
            )
            if port_object and (port_info := get_port_info(port_object)):
                self._port_finder_config.save_port(port_info)
                logger.info("Обновлен порт в конфиге: %s", new_port)
                return new_port
        return None

    def connect(self, retry_count: int = 0) -> bool:
        """
        Устанавливает подключение через последовательный порт.

        После открытия и идентификации контроллера:
        1. проверяет и при необходимости снимает Alarm через $X (без движения);
        2. синхронизирует настройки с robot_config.json.
        """
        if not self._ensure_port_loaded():
            raise RobotException("Не удалось найти порт станции")

        if self._is_connected():
            return True

        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

        self._reset_homed_on_disconnect()

        try:
            logger.info(
                "Попытка подключения к %s (baudrate=%d)",
                self._port,
                self._baudrate,
            )
            self._connection = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=self._timeout_connection,
            )

            self._connection.reset_input_buffer()
            self._connection.reset_output_buffer()
            time.sleep(2)

            if not self._identify_device():
                logger.error("Не удалось идентифицировать устройство")
                self._close_connection_after_error()
                raise RobotException("Не удалось идентифицировать устройство")

            self._ensure_idle_for_settings_sync()

            changed_commands = self._synchronize_robot_settings()
            if changed_commands:
                logger.warning(
                    "Настройки робота восстановлены из JSON: %s",
                    ", ".join(changed_commands),
                )
            else:
                logger.info("Настройки робота уже соответствуют robot_config.json")

            logger.info("Успешное подключение к %s", self._port)
            return True

        except SerialException as error:
            logger.error("Ошибка подключения к %s: %s", self._port, str(error))
            self._connection = None

            if retry_count < self._max_retries:
                logger.info(
                    "Попытка переподключения (%d/%d)",
                    retry_count + 1,
                    self._max_retries,
                )
                if new_port := self._find_new_port():
                    self._port = new_port
                    return self.connect(retry_count + 1)

            raise RobotException(
                f"Не удалось подключиться к манипулятору (порт {self._port})"
            ) from error

        except RobotException:
            self._close_connection_after_error()
            raise
        except Exception as error:
            self._close_connection_after_error()
            logger.error("Ошибка подключения: %s", str(error))
            raise RobotException(
                f"Ошибка подключения к манипулятору: {str(error)}"
            ) from error

    def disconnect(self) -> bool:
        if not self._is_connected():
            return False

        try:
            logger.info("Закрытие подключения к %s", self._port)
            self._connection.close()
            self._connection = None
            self._reset_homed_on_disconnect()
            logger.info("Подключение к %s успешно закрыто", self._port)
            return True
        except SerialException as error:
            logger.error("Ошибка при закрытии подключения: %s", str(error))
            return False

    def _ensure_idle_for_settings_sync(self) -> None:
        """
        Перед синхронизацией настроек нужно снять Alarm через $X, если станок
        не в состоянии Idle. Это не калибровка и не движение осей.
        """
        status_str = self._query_status()

        if "Alarm" in status_str:
            logger.warning(
                "Станок в состоянии Alarm перед синхронизацией настроек, "
                "выполняю $X (без движения осей)"
            )
            self._send_command("$X")
            time.sleep(0.3)

        status_str = self._query_status()

        if "Alarm" in status_str:
            raise RobotException(
                "Не удалось снять Alarm перед синхронизацией настроек робота "
                f"(текущий статус: '{status_str}')"
            )

    def _query_status(self) -> str:
        """Отправляет '?' и возвращает строку статуса станка."""
        self._send_command("?")
        status_response = self._read_response(timeout=0.5)
        return " ".join(status_response) if status_response else ""

    def _synchronize_robot_settings(self) -> List[str]:
        """
        Сверяет настройки контроллера с robot_config.json.
        """
        config = self._load_robot_settings_config()
        current_settings = self._read_grbl_settings()
        changed_commands: List[str] = []

        for key, expected_value in config["settings"].items():
            actual_value = current_settings.get(key)
            if actual_value is None:
                raise RobotException(
                    f"Контроллер не вернул параметр ${key} в ответ на $$"
                )

            if not self._settings_values_equal(actual_value, expected_value):
                command = f"${key}={expected_value}"
                self._send_command_and_wait_for_ok(command)
                changed_commands.append(command)

        current_startup_blocks = self._read_startup_blocks()
        for key, expected_value in config["startup_blocks"].items():
            actual_value = current_startup_blocks.get(key)
            if actual_value is None:
                raise RobotException(
                    f"Контроллер не вернул startup-block $N{key} в ответ на $N"
                )

            if not self._startup_blocks_equal(actual_value, expected_value):
                command = f"$N{key}={expected_value}"
                self._send_command_and_wait_for_ok(command)
                changed_commands.append(command)

        self._validate_robot_settings(config)
        return changed_commands

    def _read_grbl_settings(self) -> Dict[str, str]:
        response_lines = self._send_command_and_wait_for_ok("$$")
        settings: Dict[str, str] = {}
        pattern = re.compile(r"^\$(\d+)=(.*)$")

        for line in response_lines:
            match = pattern.match(line)
            if match:
                settings[match.group(1)] = match.group(2).strip()

        return settings

    def _read_startup_blocks(self) -> Dict[str, str]:
        response_lines = self._send_command_and_wait_for_ok("$N")
        startup_blocks: Dict[str, str] = {}
        pattern = re.compile(r"^\$N(\d+)=(.*)$")

        for line in response_lines:
            match = pattern.match(line)
            if match:
                startup_blocks[match.group(1)] = match.group(2).strip()

        return startup_blocks

    def _validate_robot_settings(self, config: Dict[str, Dict[str, str]]) -> None:
        actual_settings = self._read_grbl_settings()
        actual_startup_blocks = self._read_startup_blocks()
        errors: List[str] = []

        for key, expected_value in config["settings"].items():
            actual_value = actual_settings.get(key)
            if actual_value is None:
                errors.append(f"${key}: параметр не получен от контроллера")
            elif not self._settings_values_equal(actual_value, expected_value):
                errors.append(
                    f"${key}: ожидалось {expected_value}, получено {actual_value}"
                )

        for key, expected_value in config["startup_blocks"].items():
            actual_value = actual_startup_blocks.get(key)
            if actual_value is None:
                errors.append(f"$N{key}: startup-block не получен от контроллера")
            elif not self._startup_blocks_equal(actual_value, expected_value):
                errors.append(
                    f"$N{key}: ожидалось '{expected_value}', получено '{actual_value}'"
                )

        if errors:
            raise RobotException(
                "Настройки робота не соответствуют robot_config.json:\n"
                + "\n".join(errors)
            )

    def _send_command_and_wait_for_ok(
            self,
            command: str,
            timeout: float = 3.0,
    ) -> List[str]:
        if not self._is_connected():
            raise RobotException("Нет активного подключения к манипулятору")

        try:
            command_bytes = f"{command}\n".encode("ascii")
            bytes_written = self._connection.write(command_bytes)
            self._connection.flush()

            if bytes_written != len(command_bytes):
                raise RobotException(
                    f"Отправлено неполное количество байт: "
                    f"{bytes_written}/{len(command_bytes)}"
                )

            response_lines: List[str] = []
            start_time = time.time()

            while time.time() - start_time < timeout:
                raw_line = self._connection.readline()
                if not raw_line:
                    continue

                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                if line.lower() == "ok":
                    return response_lines

                if line.lower().startswith("error"):
                    raise RobotException(
                        f"Робот отклонил команду '{command}': {line}"
                    )

                response_lines.append(line)

            raise RobotException(
                f"Таймаут ожидания ответа ok на команду: {command}"
            )

        except SerialException as error:
            self._close_connection_after_error()
            raise RobotException(
                f"Ошибка связи с манипулятором при команде {command}: {error}"
            ) from error

    @staticmethod
    def _settings_values_equal(actual_value: str, expected_value: str) -> bool:
        try:
            return Decimal(actual_value) == Decimal(expected_value)
        except InvalidOperation:
            return actual_value.strip() == expected_value.strip()

    @staticmethod
    def _startup_blocks_equal(actual_value: str, expected_value: str) -> bool:
        """
        Сравнивает startup-block без зависимости от пробелов.
        """

        def normalize(command: str) -> str:
            command = command.upper().replace(" ", "")
            return command

        return normalize(actual_value) == normalize(expected_value)

    def move_to_coordinates(
            self,
            x: Optional[float] = None,
            y: Optional[float] = None,
            z: Optional[float] = None,
            feed_rate: int = 1000,
    ) -> bool:
        self.connect()

        if not self._ensure_device_type():
            raise RobotException("Устройство Манипулятор не идентифицировано")

        if not self._ensure_homed():
            raise RobotException("Не удалось выполнить калибровку манипулятора")

        if x is not None:
            if x > self._extreme_coordinates["x_max"] or x < self._extreme_coordinates["x_min"]:
                raise RobotException(
                    f"Координата X={x} выходит за пределы рабочей области "
                    f"[{self._extreme_coordinates['x_min']}, "
                    f"{self._extreme_coordinates['x_max']}]"
                )
        if y is not None:
            if y > self._extreme_coordinates["y_max"] or y < self._extreme_coordinates["y_min"]:
                raise RobotException(
                    f"Координата Y={y} выходит за пределы рабочей области "
                    f"[{self._extreme_coordinates['y_min']}, "
                    f"{self._extreme_coordinates['y_max']}]"
                )
        if z is not None:
            if z > self._extreme_coordinates["z_max"] or z < self._extreme_coordinates["z_min"]:
                raise RobotException(
                    f"Координата Z={z} выходит за пределы рабочей области "
                    f"[{self._extreme_coordinates['z_min']}, "
                    f"{self._extreme_coordinates['z_max']}]"
                )

        command_parts = ["G0"]
        if x is not None:
            command_parts.append(f"X{x}")
        if y is not None:
            command_parts.append(f"Y{y}")
        if z is not None:
            command_parts.append(f"Z{z}")
        command_parts.append(f"F{feed_rate}")
        gcode_command = " ".join(command_parts)

        try:
            logger.info("Отправка команды перемещения: %s", gcode_command)
            if not self._send_command(gcode_command):
                raise RobotException(
                    f"Не удалось отправить команду перемещения: {gcode_command}"
                )

            self._wait_for_idle(timeout=30, poll_interval=0.05)
            return True
        except RobotException:
            raise
        except Exception as error:
            logger.error(
                "Ошибка перемещения манипулятора в координаты (%s; %s, %s): %s",
                x,
                y,
                z,
                str(error),
            )
            raise RobotException(
                f"Ошибка перемещения манипулятора в координаты ({x}; {y}, {z})"
            ) from error

    def home(self) -> bool:
        self.connect()

        if not self._ensure_device_type():
            raise RobotException("Устройство Манипулятор не идентифицировано")

        try:
            logger.info("Отправка команды калибровки на порт %s", self._port)

            if not self._send_command("$H"):
                raise RobotException("Не удалось отправить команду калибровки")

            logger.info("Команда калибровки отправлена, ожидание завершения...")
            self._wait_for_idle(timeout=30, poll_interval=0.1)

            self.is_homed = True
            logger.info("Калибровка успешно завершена")
            return True

        except RobotException:
            raise
        except Exception as error:
            raise RobotException(f"Ошибка при калибровке: {str(error)}") from error

    def _identify_device(self) -> bool:
        try:
            response = self._send_command_and_wait_for_ok("$$")
            if response and any("$" in line for line in response[:10]):
                self._device_type = "crystal"
                logger.info("Определено устройство: Кристалл")
                return True

            logger.warning("Тип устройства не определен")
            return False
        except Exception as error:
            logger.error("Ошибка идентификации устройства: %s", str(error))
            return False

    def _send_command(self, command: str) -> bool:
        if not self._is_connected():
            raise RobotException("Нет активного подключения к манипулятору")

        try:
            command_bytes = f"{command}\n".encode("utf-8")
            bytes_written = self._connection.write(command_bytes)

            if bytes_written != len(command_bytes):
                raise RobotException(
                    f"Отправлено неполное количество байт: "
                    f"{bytes_written}/{len(command_bytes)}"
                )
            return True
        except serial.SerialException as error:
            logger.error("Ошибка Serial при отправке команды %s: %s", command, error)
            self._close_connection_after_error()
            raise RobotException(
                f"Ошибка связи с манипулятором: потеряно соединение с портом {self._port}"
            ) from error
        except RobotException:
            raise
        except Exception as error:
            raise RobotException(
                f"Неожиданная ошибка при отправке команды: {str(error)}"
            ) from error

    def _read_response(self, timeout: float = 0.5) -> Optional[List[str]]:
        if not self._is_connected():
            return None

        try:
            collected_lines: List[str] = []
            start_time = time.time()
            last_data_time = start_time
            has_data = False

            while time.time() - start_time < timeout:
                try:
                    raw_line = self._connection.readline()
                except SerialException as error:
                    logger.error("Ошибка чтения строки: %s", error)
                    break

                if raw_line:
                    has_data = True
                    last_data_time = time.time()
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if line:
                        collected_lines.append(line)
                    continue

                if has_data and (time.time() - last_data_time) > 0.1:
                    break

                time.sleep(0.01)

            clean_response = self._clean_response(collected_lines)
            return clean_response if clean_response else ([] if has_data else None)
        except Exception as error:
            logger.error("Ошибка при чтении ответа: %s", error)
            return None

    @staticmethod
    def _clean_response(response_lines: List[str]) -> List[str]:
        filtered = []
        skip_patterns = ["Not SD printing", "T:", "Cap:", "ok"]

        for line in response_lines:
            if not line:
                continue
            if any(line.startswith(pattern) for pattern in skip_patterns):
                continue
            filtered.append(line)

        return filtered

    def _wait_for_idle(self, timeout: float = 30, poll_interval: float = 0.1) -> bool:
        start_time = time.time()
        failed_sends = 0
        alarm_retried = False

        while time.time() - start_time < timeout:
            try:
                if not self._send_command("?"):
                    failed_sends += 1
                if failed_sends > 10:
                    raise RobotException("Потеря связи со станцией")
                time.sleep(poll_interval)
            except RobotException:
                raise

            failed_sends = 0
            status_response = self._read_response(timeout=0.5)

            if status_response:
                status_str = " ".join(status_response)

                if "Idle" in status_str:
                    logger.debug("Станок в состоянии Idle")
                    logger.debug("Получена строка: %s", status_response)
                    return True

                if "Alarm" in status_str:
                    if not alarm_retried:
                        logger.warning("Станок в состоянии Alarm, выполняю $X: %s", status_str)
                        alarm_retried = True
                        self._send_command("$X")
                        time.sleep(0.3)
                        continue

                    logger.error("Повторный Alarm после $X: %s", status_str)
                    return False

            time.sleep(poll_interval)

        logger.error("Таймаут ожидания Idle (%.1f сек)", timeout)
        self._close_connection_after_error()
        raise RobotException(
            "Таймаут ожидания завершения операции — станок не отвечает"
        )

    def _close_connection_after_error(self) -> None:
        """Закрывает соединение и сбрасывает калибровку после ошибки связи."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
        self._connection = None
        self._reset_homed_on_disconnect()

    def _is_connected(self) -> bool:
        return self._connection is not None and self._connection.is_open

    def _ensure_device_type(self) -> bool:
        if self._device_type != "crystal":
            logger.error("Устройство не идентифицировано или не является кристаллом")
            return False
        return True

    @classmethod
    def get_instance(
            cls,
            config: Optional["ConfigManager"] = None,
            port_finder: Optional["PortFinder"] = None,
            port_finder_config: Optional["PortFinderConfig"] = None,
            baudrate: int = 115200,
            timeout_connection: float = 0.05,
            max_retries: int = 3,
    ) -> "RobotController":
        if cls._instance is None:
            if config is None:
                raise ValueError(
                    "RobotController не инициализирован. "
                    "При первом вызове get_instance() необходимо передать config"
                )
            cls._instance = cls(
                config=config,
                port_finder=port_finder,
                port_finder_config=port_finder_config,
                baudrate=baudrate,
                timeout_connection=timeout_connection,
                max_retries=max_retries,
            )
        return cls._instance

    @classmethod
    def has_instance(cls) -> bool:
        return cls._instance is not None

    @classmethod
    def reset_instance(cls) -> None:
        if cls._instance is not None:
            if cls._instance._is_connected():
                cls._instance.disconnect()
            cls._instance = None
            cls._initialized = False
            logger.info("Экземпляр RobotController сброшен")