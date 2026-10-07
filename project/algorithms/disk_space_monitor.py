"""
Модуль для мониторинга свободного места на диске во время инспекции.
Выводит предупреждения при нехватке памяти и останавливает процесс при критическом уровне.
"""

import shutil
import threading
from typing import Callable, Optional
import time

from project.application.addition.dialogs import show_error, show_warning
from project.application.addition.logger import logger


class DiskSpaceMonitor:
    """Класс для мониторинга свободного места на диске."""

    WARNING_THRESHOLD_GB = 20
    CRITICAL_THRESHOLD_GB = 1
    CHECK_INTERVAL_SECONDS = 30

    def __init__(self, disk_path: str = "C:/", config=None):
        """
        Инициализация монитора дискового пространства.

        Args:
            disk_path: Путь к диску для мониторинга (например, "C:/" или "D:/")
            config: Объект конфигурации приложения
        """
        self.disk_path = disk_path
        self.disk_letter = disk_path.rstrip("/").rstrip("\\")

        self.config = config
        self.page = config.page
        
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_callback: Optional[Callable] = None
        self._warning_shown = False

    def _get_free_space_gb(self) -> float:
        """
        Получить количество свободного места на диске в ГБ.

        Returns:
            Количество свободного места в гигабайтах
        """
        try:
            stat = shutil.disk_usage(self.disk_path)
            return stat.free / (1024 ** 3)
        except Exception as e:
            logger.error(f"Ошибка при получении информации о диске: {e}")
            return float('inf')

    def _monitor_loop(self):
        """Основной цикл мониторинга дискового пространства."""
        while self._monitoring:
            free_space_gb = self._get_free_space_gb()

            if free_space_gb < self.CRITICAL_THRESHOLD_GB:
                self._monitoring = False
                show_error(
                    title="Критическая ошибка",
                    message=f"Память на диске {self.disk_letter} закончилась ({free_space_gb}). Освободите диск",
                    page=self.page, config=self.config,
                )
                logger.error(f"Память на диске {self.disk_letter} закончилась: {free_space_gb}")
                
                if self._stop_callback:
                    self._stop_callback()
                break

            elif free_space_gb < self.WARNING_THRESHOLD_GB and not self._warning_shown:
                show_warning(
                    title="Предупреждение",
                    message=f"Освободите память на диске {self.disk_letter} \nОсталось: {free_space_gb:.1f} ГБ",
                    page=self.page,
                    config=self.config
                )
                logger.warning(f"Недостаток места на диске {self.disk_letter}: {free_space_gb:.1f} ГБ")
                self._warning_shown = True

            elif free_space_gb >= self.WARNING_THRESHOLD_GB:
                self._warning_shown = False

            time.sleep(self.CHECK_INTERVAL_SECONDS)

    def start_monitoring(self, stop_callback: Optional[Callable] = None):
        """
        Начать мониторинг дискового пространства в фоновом режиме.

        Args:
            stop_callback: Функция, которая будет вызвана при критическом уровне памяти
        """
        if self._monitoring:
            return

        self._stop_callback = stop_callback
        self._monitoring = True
        self._warning_shown = False
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.debug(f"Начат мониторинг диска {self.disk_letter}")

    def stop_monitoring(self):
        """Остановить мониторинг дискового пространства."""
        if self._monitoring:
            self._monitoring = False
            if self._monitor_thread:
                self._monitor_thread.join(timeout=2)
            logger.debug(f"Мониторинг диска {self.disk_letter} остановлен")

    def check_before_inspection(self) -> bool:
        """
        Проверить свободное место перед началом инспекции.

        Returns:
            True если достаточно места, False если критически мало
        """
        free_space_gb = self._get_free_space_gb()

        if free_space_gb < self.CRITICAL_THRESHOLD_GB:
            show_error(
                title="Критическая ошибка",
                message=f"Память на диске {self.disk_letter} закончилась ({free_space_gb}). Освободите диск",
                page=self.page, config=self.config,
            )
            logger.error(f"Память на диске {self.disk_letter} закончилась: {free_space_gb}")

            return False

        elif free_space_gb < self.WARNING_THRESHOLD_GB:
            show_warning(
                title="Предупреждение",
                message=f"Освободите память на диске {self.disk_letter} \nОсталось: {free_space_gb:.1f} ГБ "
                        f"\nПосле этого инспекция будет прдолжена",
                page=self.page,
                config=self.config
            )
            logger.warning(f"Недостаток места на диске {self.disk_letter}: {free_space_gb:.1f} ГБ")

        return True


def detect_inspection_disk() -> str:
    """
    Определить, на каком диске выполняется инспекция.

    Returns:
        Путь к диску (например, "C:/" или "D:/")
    """
    import os
    current_drive = os.path.splitdrive(os.getcwd())[0]
    return current_drive + "/"
