import time
import ctypes
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Tuple

from project.application.addition.logger import logger
from project.station.spacemouse.spacemouse_config import SpaceMouseConfig, SpaceMouseSettings

_DLL_DIR_HANDLES: List[object] = []


@dataclass(frozen=True)
class SpaceMouseState:
    """
    Состояние SpaceMouse.

    Attributes:
        x (float): Смещение по оси X
        y (float): Смещение по оси Y
        z (float): Смещение по оси Z
        roll (float): Вращение вокруг оси X
        pitch (float): Вращение вокруг оси Y
        yaw (float): Вращение вокруг оси Z
        buttons (Tuple[int, ...]): Состояние кнопок
    """
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    buttons: Tuple[int, ...] = ()


SpaceMouseListener = Callable[['SpaceMouseState'], None]


class SpaceMouseAdapter:
    """
    Адаптер для работы с SpaceMouse (ленивая инициализация).

    Attributes:
        _deadzone (float): Мёртвая зона для осей
        _connected (bool): Флаг подключения устройства
        _listeners (List[SpaceMouseListener]): Список слушателей состояния
        _device: Объект устройства pyspacemouse
        _polling_thread: Поток опроса устройства
        _running (bool): Флаг работы потока
    """

    _DLL_DIR_HANDLES: List[object] = []
    _HAS_SPACEMOUSE: bool = False

    def __init__(self) -> None:
        """
        Инициализация адаптера SpaceMouse.
        Загружает конфигурацию и готовится к подключению.
        """
        self._config = SpaceMouseConfig()
        self._deadzone: float = self._config.settings.deadzone
        self._connected: bool = False
        self._listeners: List[SpaceMouseListener] = []
        self._device = None
        self._polling_thread = None
        self._running: bool = False

    @classmethod
    def _prepare_hidapi(cls) -> None:
        """
        Подготавливает загрузку hidapi.dll для Windows.
        Ищет библиотеку в папке dlls/hidapi/win-x64 относительно корня проекта.
        """
        if os.name != "nt":
            return

        # project/station/spacemouse/spacemouse_adapter.py -> parents[3] = Milandr
        package_root = Path(__file__).resolve().parents[3]
        dll_dir = package_root / "dlls" / "hidapi" / "win-x64"
        dll_path = dll_dir / "hidapi.dll"

        if not dll_path.exists():
            logger.warning(f"hidapi.dll не найдена по пути: {dll_path}")
            return

        try:
            if hasattr(os, "add_dll_directory"):
                cls._DLL_DIR_HANDLES.append(os.add_dll_directory(str(dll_dir)))
            ctypes.CDLL(str(dll_path))
            logger.info(f"hidapi загружена из {dll_path}")
        except Exception as e:
            logger.warning(f"Не удалось загрузить hidapi из {dll_path}: {e}", exc_info=True)

    @classmethod
    def _check_spacemouse_available(cls) -> bool:
        """
        Проверяет доступность pyspacemouse и загружает hidapi.

        Returns:
            bool: True если SpaceMouse доступна
        """
        if cls._HAS_SPACEMOUSE:
            return True

        cls._prepare_hidapi()

        try:
            import pyspacemouse
            cls._pyspacemouse = pyspacemouse
            cls._HAS_SPACEMOUSE = True
            logger.info("SpaceMouse: библиотека pyspacemouse загружена")
            return True
        except ImportError:
            logger.warning("SpaceMouse: pyspacemouse не установлен")
            return False
        except Exception as e:
            logger.warning(f"SpaceMouse: ошибка загрузки pyspacemouse: {e}")
            return False

    @property
    def available(self) -> bool:
        """Доступна ли библиотека pyspacemouse."""
        return self._check_spacemouse_available()

    @property
    def connected(self) -> bool:
        """Подключено ли устройство."""
        return self._connected

    @property
    def settings(self) -> SpaceMouseSettings:
        """Возвращает текущие настройки."""
        return self._config.settings

    def subscribe(self, listener: SpaceMouseListener) -> None:
        """
        Добавляет слушателя состояния SpaceMouse.

        Args:
            listener: Функция, принимающая SpaceMouseState
        """
        self._listeners.append(listener)

    def open(self) -> bool:
        """
        Открывает соединение с SpaceMouse (ленивая инициализация).

        Returns:
            bool: True если подключение успешно, иначе False
        """
        if not self.available:
            logger.info("SpaceMouse: недоступна, подключение невозможно")
            return False

        if self._connected:
            logger.debug("SpaceMouse: уже подключена")
            return True

        try:
            self._device = self._pyspacemouse.open()
            self._connected = self._device is not None

            if self._connected:
                logger.info("SpaceMouse: устройство подключено")
                self._start_polling()
            else:
                logger.warning("SpaceMouse: устройство не найдено")

            return self._connected

        except Exception as e:
            logger.warning(f"SpaceMouse: не удалось открыть устройство: {e}", exc_info=True)
            self._device = None
            self._connected = False
            return False

    def close(self) -> None:
        """Закрывает соединение с SpaceMouse."""
        self._stop_polling()

        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass

        self._device = None
        self._connected = False
        logger.info("SpaceMouse: устройство отключено")

    def _start_polling(self) -> None:
        """Запускает поток опроса SpaceMouse."""
        if self._polling_thread is not None and self._polling_thread.is_alive():
            return

        self._running = True
        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._polling_thread.start()
        logger.debug("SpaceMouse: поток опроса запущен")

    def _stop_polling(self) -> None:
        """Останавливает поток опроса SpaceMouse."""
        self._running = False
        if self._polling_thread is not None and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=1.0)
        self._polling_thread = None
        logger.debug("SpaceMouse: поток опроса остановлен")

    def _polling_loop(self) -> None:
        """Цикл опроса SpaceMouse в отдельном потоке."""
        interval = self._config.settings.poll_interval_ms / 1000.0

        while self._running and self._connected:
            self._poll_once()
            time.sleep(interval)

    def _poll_once(self) -> None:
        """Однократный опрос SpaceMouse."""
        if not self._connected or self._device is None:
            return

        try:
            state = self._device.read()
            if state is None:
                return

            dz = self._deadzone
            result = SpaceMouseState(
                x=state.x if abs(state.x) > dz else 0.0,
                y=state.y if abs(state.y) > dz else 0.0,
                z=state.z if abs(state.z) > dz else 0.0,
                roll=state.roll if abs(state.roll) > dz else 0.0,
                pitch=state.pitch if abs(state.pitch) > dz else 0.0,
                yaw=state.yaw if abs(state.yaw) > dz else 0.0,
                buttons=tuple(state.buttons) if hasattr(state, "buttons") else (),
            )

            for listener in self._listeners:
                try:
                    listener(result)
                except Exception as e:
                    logger.error(f"SpaceMouse: ошибка в слушателе: {e}")

        except Exception as e:
            logger.debug(f"SpaceMouse: ошибка при опросе: {e}", exc_info=True)


spacemouse_adapter = SpaceMouseAdapter()
