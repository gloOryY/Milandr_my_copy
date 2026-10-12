import queue
import threading
from project.application.addition.logger import logger


class RobotCommandQueue:
    """
    Простая очередь команд для робота.
    Выполняет команды последовательно в одном фоновом потоке,
    который запускается только при появлении задач и завершается когда очередь пуста.
    """

    def __init__(self):
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._worker_thread = None

    def put(self, command, error_callback=None):
        """
        Добавляет команду в очередь.

        Args:
            command: Функция для выполнения
            error_callback: Функция для обработки ошибок (принимает Exception)
        """
        self._queue.put((command, error_callback))
        self._ensure_worker_running()

    def _ensure_worker_running(self):
        """Запускает обработчик, если он ещё не запущен."""
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(target=self._worker, daemon=True)
                self._worker_thread.start()

    def _worker(self):
        """Обработчик очереди — работает пока есть задачи."""
        while True:
            try:
                command, error_callback = self._queue.get(timeout=1.0)
            except queue.Empty:
                # Очередь пуста — выходим
                break

            try:
                command()
            except Exception as e:
                logger.error(f"Ошибка при выполнении команды робота: {e}")
                if error_callback:
                    try:
                        error_callback(e)
                    except Exception:
                        pass
            finally:
                self._queue.task_done()

        # Поток завершается сам когда очередь опустела


# Глобальный экземпляр
robot_command_queue = RobotCommandQueue()