import cv2
import numpy as np
import time
from threading import Lock
from collections import deque
from typing import List, Optional, Tuple, Any, Dict

from project.configuration.worker import read_from_json
from project.station.camera.frame_process import get_exposure
from project.application.addition.exceptions import CameraException
from project.application.addition.logger import logger


class CameraManager:
    """
    Класс-менеджер для управления камерами с Galaxy SDK.
    Реализован как Singleton для обеспечения единственного экземпляра менеджера камер.

    Обеспечивает поиск, подключение, отключение и управление несколькими камерами.
    Поддерживает приоритетный доступ к камерам для разных окон.

    Attributes:
        _instance (Optional['CameraManager']): Единственный экземпляр класса
        _initialized (bool): Флаг инициализации экземпляра
        _device_manager: Менеджер устройств GXIPY
        _cameras (List[Camera]): Список объектов камер
        _is_possible_multiple_windows (bool): Разрешено ли использование камеры в нескольких окнах
    """

    _instance: Optional['CameraManager'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs) -> 'CameraManager':
        """
        Контролирует создание экземпляра класса.
        Если экземпляр уже существует, возвращает его, иначе создает новый.

        Returns:
            CameraManager: Единственный экземпляр класса
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, is_possible_multiple_windows: bool = False) -> None:
        """
        Инициализация менеджера камер.
        При повторном вызове __init__ после создания экземпляра,
        инициализация не выполняется повторно (благодаря флагу _initialized).

        Args:
            is_possible_multiple_windows: Флаг разрешения использования камеры в нескольких окнах
        """
        # Предотвращаем повторную инициализацию
        if CameraManager._initialized:
            logger.debug("CameraManager уже инициализирован, повторная инициализация пропущена")
            return

        self._device_manager: Optional[Any] = None
        self._cameras: List['CameraGXIPY'] = []
        self._is_possible_multiple_windows: bool = is_possible_multiple_windows

        # Устанавливаем флаг инициализации
        CameraManager._initialized = True

    @classmethod
    def get_instance(cls, is_possible_multiple_windows: bool = False) -> 'CameraManager':
        """
        Получение единственного экземпляра CameraManager.
        Если экземпляр еще не создан, создает его с переданными параметрами.
        Если экземпляр уже существует, возвращает его (параметры игнорируются).

        Args:
            is_possible_multiple_windows: Флаг разрешения использования камеры в нескольких окнах

        Returns:
            CameraManager: Единственный экземпляр менеджера камер
        """
        if cls._instance is None:
            cls._instance = cls(is_possible_multiple_windows=is_possible_multiple_windows)
        return cls._instance

    @classmethod
    def has_instance(cls) -> bool:
        """
        Проверяет, создан ли уже экземпляр CameraManager.

        Returns:
            bool: True если экземпляр существует, иначе False
        """
        return cls._instance is not None

    @classmethod
    def reset_instance(cls) -> None:
        """
        Сбрасывает Singleton экземпляр.
        Используется в основном для тестирования или при необходимости
        полного пересоздания менеджера камер с новыми параметрами.
        """
        if cls._instance is not None:
            # Если есть активные камеры, очищаем их
            if cls._instance._cameras:
                cls._instance.cleanup_all_cameras()
            cls._instance = None
            cls._initialized = False
            logger.info("Экземпляр CameraManager сброшен")

    def _init_device_manager(self) -> bool:
        """ Инициализация менеджера камер self._device_manager. """
        try:
            if self._device_manager is None:
                import gxipy as gx
                self._device_manager = gx.DeviceManager()
                logger.debug("DeviceManager инициализирован")
            else:
                logger.warning("DeviceManager уже был инициализирован")

            return True

        except Exception as e:
            logger.error(f"Ошибка инициализации менеджера камер DeviceManager: {e}")
            self._device_manager = None
            return False

    def find_all_cams(self,
                      number_of_cameras: int = 1,
                      is_necessary_number: bool = True) -> bool:
        """
        Поиск и подключение указанного количества камер.

        Args:
            number_of_cameras: Необходимое количество камер
            is_necessary_number: Требовать ли точное количество камер

        Returns:
            bool: True если найдено необходимое количество камер

        Raises:
            CameraException: При ошибках инициализации камер
        """
        idx_cam = 0
        if self._device_manager is None:
            if not self._init_device_manager():
                raise CameraException(message="Ошибка инициализации менеджера камер")

        try:
            self._device_manager.update_device_list()  # Обновление списка устройств
            device_info_list = self._device_manager.get_device_info()
            device_num = len(device_info_list)
            logger.debug(f"Найдено камер через open-gxipy: {device_num}")

            for idx_cam in range(min(device_num, number_of_cameras)):
                device = self._device_manager.open_device_by_index(idx_cam + 1)
                device_info = device_info_list[idx_cam]

                camera = CameraGXIPY(
                    device=device,
                    device_info=device_info,
                    index_order=idx_cam,
                    priority=0
                )
                self._cameras.append(camera)

                if device_info:
                    logger.debug(
                        f"Камера {device_info.get('model_name', 'Unknown')} "
                        f"(SN: {device_info.get('sn', 'Unknown')}) успешно инициализирована"
                    )
                else:
                    logger.debug(f"Камера {idx_cam} успешно инициализирована")

            return self._check_camera_count(number_of_cameras, is_necessary_number)

        except CameraException:
            raise

        except Exception as e:
            error_msg = str(e)
            if "-1004" in error_msg or "device has been open" in error_msg.lower():
                logger.error(f"Камера {idx_cam} открыта в другом приложении: {error_msg}")
                raise CameraException(message=f"Камера {idx_cam} открыта в другом приложении.\n"
                                              f"Закройте камеру и повторите операцию.")
            else:
                logger.error(f"Ошибка при поиске камер: {e}")
                raise CameraException(message="Ошибка инициализации камер")

    def _check_camera_count(self, number_of_cameras: int, is_necessary_number: bool) -> bool:
        """
        Проверка количества найденных камер.

        Args:
            number_of_cameras: Ожидаемое количество камер
            is_necessary_number: Требовать ли точное количество

        Returns:
            bool: True если количество соответствует требованиям
        """
        logger.info(f"Всего найдено и подключено: {len(self._cameras)} камер.")
        if len(self._cameras) == 0:
            logger.error("Камеры не найдены.")
            return False

        if is_necessary_number:
            if len(self._cameras) == number_of_cameras:
                return True
            else:
                logger.warning(f"Найдено и подключено только {len(self._cameras)} камер из {number_of_cameras}.")
                return False
        else:
            return True

    def connect_all_cams(self) -> Optional[List['CameraGXIPY']]:
        """
        Подключение всех найденных камер.
        """
        if not self._check_device_manager_and_cams():
            raise CameraException("Камеры не найдены")

        cameras = []
        for camera in self._cameras:
            try:
                connected_camera = self.connect_cam(camera.index_order)
                if connected_camera:
                    cameras.append(connected_camera)
            except Exception as e:
                logger.error(f"Ошибка в подключении к камере {camera.index_order}: {e}")
                raise CameraException(f"Ошибка в подключении к камере {camera.index_order}")

        return cameras if cameras else None

    def connect_cam(self, index_of_cam: int = 0, priority_window: int = 0) -> 'CameraGXIPY':
        """
        Подключение конкретной камеры по индексу с учетом приоритета.

        Args:
            index_of_cam: Индекс камеры
            priority_window: Приоритет окна, запрашивающего камеру

        Returns:
            Camera: Подключенный объект камеры

        Raises:
            CameraException: Если камера не найдена или не может быть подключена
        """
        if not self._check_device_manager_and_cams():
            raise CameraException("Камеры не найдены")

        camera = self._get_camera(index_of_cam)
        if camera is None:
            logger.error(f"Камера с индексом {index_of_cam} не найдена")
            raise CameraException(message=f"Камера не найдена {index_of_cam}", camera_id=index_of_cam)

        if self._is_possible_multiple_windows or not camera.is_busy:
            if camera.connect():
                return camera
            else:
                logger.error(f"Камеру с индексом {index_of_cam} невозможно подключить")
                raise CameraException(message=f"Камеру невозможно подключить {index_of_cam}", camera_id=index_of_cam)

        elif priority_window >= camera.priority:
            max_time_change_is_allowed_broadcast = 3
            if camera.is_allowed_broadcast:
                camera.is_allowed_broadcast = False

            start_time = time.time()
            while not camera.is_allowed_broadcast:
                time.sleep(0.1)
                if time.time() - start_time >= max_time_change_is_allowed_broadcast:
                    break

            if camera.connect():
                camera.priority = priority_window
                return camera
            else:
                logger.error(f"Камеру с индексом {index_of_cam} невозможно подключить")
                raise CameraException(message=f"Камеру невозможно подключить {index_of_cam}", camera_id=index_of_cam)
        else:
            logger.warning(f"Камеру с индексом {index_of_cam} нельзя подключить из-за малого приоритета")
            raise CameraException(
                message=f"Камеру {index_of_cam} нельзя подключить из-за возможной трансляции в другом фрейме",
                camera_id=index_of_cam
            )

    def get_connected_camera(self, index_of_cam: int = 0) -> Optional['CameraGXIPY']:
        """ Получение подключённой камеры по индексу. """
        if not self._check_device_manager_and_cams():
            raise CameraException("Камеры не найдены")

        camera = self._get_camera(index_of_cam)
        if camera is None:
            logger.error(f"Камера с индексом {index_of_cam} не найдена")
            raise CameraException(message=f"Камера {index_of_cam} не найдена", camera_id=index_of_cam)
        else:
            if camera.is_busy:
                return camera
            else:
                return self.connect_cam(index_of_cam)

    def disconnect_all_cams(self) -> bool:
        """ Отключение всех камер. """
        if not self._check_device_manager_and_cams():
            raise CameraException("Камеры не найдены")

        success = True
        for camera in self._cameras:
            self.connect_cam(index_of_cam=camera.index_order, priority_window=100)
            if not camera.disconnect():
                success = False

        return success

    def disconnect_cam(self, index_of_cam: int = 0) -> None:
        """ Отключение конкретной камеры по индексу. """
        if not self._check_device_manager_and_cams():
            raise CameraException("Камеры не найдены")

        camera = self._get_camera(index_of_cam)
        if camera is not None:
            camera.disconnect()

    def cleanup_all_cameras(self) -> bool:
        """ Корректное закрытие всех камер перед очисткой списка. """
        if not self._cameras:
            logger.debug("Нет камер для очистки")
            return True

        success_count = 0
        failed_indices = []

        cameras_copy = self._cameras[:]
        for camera in cameras_copy:
            try:
                success = camera.cleanup()
                if success:
                    success_count += 1
                    self._cameras.remove(camera)
                else:
                    failed_indices.append(camera.index_order)
            except Exception as e:
                logger.error(f"Исключение при очистке камеры {camera.index_order}: {e}")
                failed_indices.append(camera.index_order)

        total_cameras = len(cameras_copy)
        if failed_indices:
            logger.warning(f"Камеры с индексами {failed_indices} не очистились ({len(failed_indices)}/{total_cameras})")
            return False
        else:
            logger.debug(f"Все камеры ({success_count}/{total_cameras} шт.) успешно очистились")
            return True

    def _check_device_manager_and_cams(self) -> bool:
        """ Проверка наличия подключенных камер с обновлением списка. """

        if self._device_manager is None:
            if not self._init_device_manager():
                raise CameraException(message="Ошибка инициализации библиотеки для камеры")

        try:
            self._device_manager.update_device_list()
            device_info_list = self._device_manager.get_device_info()
            device_num = len(device_info_list)

            # Если количество камер изменилось
            if len(self._cameras) != device_num:
                logger.info(f"Количество камер изменилось: было {len(self._cameras)}, стало {device_num}")
                self.cleanup_all_cameras()
                return self.find_all_cams(device_num, False)

            return len(self._cameras) != 0

        except CameraException:
            raise

        except Exception as e:
            logger.error(f"Ошибка проверки камер: {e}")
            raise CameraException(message="Ошибка проверки камер")

    def _get_camera(self, index_of_cam: int = 0) -> Optional['CameraGXIPY']:
        """ Получение объекта камеры по индексу. """
        for camera in self._cameras:
            if camera.index_order == index_of_cam:
                return camera

        return None

    def __del__(self) -> None:
        """ Освобождение ресурсов при уничтожении объекта. """
        try:
            if self.cleanup_all_cameras():
                logger.debug(f"Деструктор CameraController сработал")
            else:
                raise
        except Exception as e:
            logger.error(f"Ошибка в деструкторе CameraController: {e}")


class CameraGXIPY:
    """
    Класс для управления отдельной камерой.

    Обеспечивает подключение, отключение, чтение кадров и настройку параметров камеры.

    Attributes:
        _device: Устройство камеры GXIPY
        _stream: Поток данных камеры
        device_info: Информация об устройстве
        index_order (int): Порядковый индекс камеры
        priority (int): Приоритет использования камеры
        is_busy (bool): Флаг занятости камеры
        is_allowed_broadcast (bool): Разрешена ли трансляция
        _exposure_level: Текущий уровень экспозиции
        _stream_lock (Lock): Блокировка для потокобезопасного доступа
    """

    _camera_config: Optional[Dict[str, Any]] = None
    _config_loaded: bool = False

    # === ХАРАКТЕРИСТИКИ КАМЕРЫ (константы для модели NS-2000UC) ===
    SENSOR_WIDTH_PX: int = 5496
    SENSOR_HEIGHT_PX: int = 3672
    FOV_WIDTH_MM: float = 4.72
    FOV_HEIGHT_MM: float = 3.45
    MM_TO_PX: float = 1250.0
    PX_TO_MM: float = 1 / 1250.0
    VENDOR: str = "ND"
    MODEL_NAME: str = "NS-2000UC"

    def __init__(self, device: Any,
                 device_info: Any,
                 index_order: int,
                 priority: int = 0) -> None:
        """
        Инициализация объекта камеры.
        """
        self._load_camera_config()

        self._device: Any = device
        self._stream: Any = self._device.data_stream[0]

        self.device_info: Any = device_info
        self.index_order: int = index_order
        self.priority: int = priority

        self.is_busy: bool = False
        self.is_allowed_broadcast: bool = True

        self._exposure_level: Optional[float] = None
        self._stream_lock: Lock = Lock()

        self._apply_initial_settings()

    def _apply_initial_settings(self) -> None:
        """
        Применение начальных параметров к камере.

        Raises:
            CameraException: При ошибках настройки камеры
        """
        device = self._device
        if device is not None:
            self._validate_camera()
            self._reset_settings()
            self._apply_camera_settings()
        else:
            logger.error(f"Камера не обнаружена")
            raise CameraException(message="Камера не обнаружена")

    def _validate_camera(self) -> None:
        """Валидация камеры."""
        try:
            vendor = self._get_parameter_camera("DeviceVendorName")
            model = self._get_parameter_camera("DeviceModelName")

            expected_vendor = self.__class__.VENDOR
            expected_model = self.__class__.MODEL_NAME

            # 1. Проверка производителя
            if not vendor or expected_vendor.upper() not in vendor.upper():
                error_message = f"Камера {vendor or 'Unknown'} не поддерживается. Требуется {expected_vendor}."
                logger.error(error_message)
                raise CameraException(message=error_message)

            # 2. Проверка серии
            if not model or not model.startswith(expected_model[:2]):
                error_message = (f"Серия камеры {model or 'Unknown'} не поддерживается. "
                                 f"Требуется серия {expected_model[:2]}.")
                logger.error(error_message)
                raise CameraException(message=error_message)

            # 3. Проверка конкретной модели
            if model != self.__class__.MODEL_NAME:
                logger.warning(f"Модель {model} не в списке протестированных, "
                               f"но серия поддерживается. Продолжаем работу.")

            logger.debug(f"Параметры камеры валидны: {vendor} - {model}")

        except CameraException:
            raise

        except Exception as e:
            logger.error(f"Ошибка валидации камеры: {e}")
            raise CameraException(message=f"Ошибка валидации камеры {self.index_order}")

    def _reset_settings(self):
        """
        Сброс параметров камеры к заводским настройкам.

        Raises:
            CameraException: При ошибке сброса настроек
        """
        try:
            self.disconnect()  # Остановка трансляции с камеры

            self._device.UserSetSelector.set(0)  # DEFAULT
            self._device.UserSetLoad.send_command()
            time.sleep(1)

            logger.debug(f"Параметры камеры {self.index_order} сброшены к заводским настройкам")

        except Exception as e:
            logger.error(f"Ошибка сброса к заводским настройкам: {e}")
            raise CameraException(message=f"Ошибка инициализации камеры {self.index_order}:\n"
                                          "Не удалось сбросить параметры к базовым настройкам")

    def _apply_camera_settings(self) -> None:
        """
        Установка параметров камеры для режима инспекции.

        Raises:
            CameraException: При ошибке установки параметров
        """
        try:
            # Установка параметров для камеры
            self._set_parameter_camera('ExposureAuto', 1)  # Continuous
            self._set_parameter_camera('ExpectedGrayValue', 110)
            self._set_parameter_camera('AutoExposureTimeMin', 12)
            self._set_parameter_camera('AutoExposureTimeMax', 1000)

            # Установка параметров для потока камеры
            self._set_parameter_stream('StreamBufferHandlingMode', 3)

            logger.debug(f"К камере {self.index_order} применены основные настройки AOI режима")

        except Exception as e:
            logger.error(f"Ошибка установки параметров камеры {self.index_order} для AOI режима: {e}")
            raise CameraException(message=f"Ошибка инициализации камеры {self.index_order}:\n"
                                          f"Не удалось установить настроичные параметры")

    def _set_parameter_camera(self, param_name: str, value: Any) -> bool:
        """
        Установка параметра камеры.

        Args:
            param_name: Название параметра камеры
            value: Новое значение для данного параметра

        Returns:
            bool: True если параметр успешно установлен
        """
        if hasattr(self._device, param_name):
            getattr(self._device, param_name).set(value)
            logger.debug(f"Камера {self.index_order}: установлен {param_name} = {value}")
            return True
        else:
            logger.warning(f"Камера {self.index_order}: параметр {param_name} не поддерживается")
            return False

    def _set_parameter_stream(self, param_name: str, value: Any) -> bool:
        """
        Установка параметра потока камеры.

        Args:
            param_name: Название параметра потока камеры
            value: Новое значение для данного параметра

        Returns:
            bool: True если параметр успешно установлен
        """
        if hasattr(self._stream, param_name):
            getattr(self._stream, param_name).set(value)
            logger.debug(f"Камера {self.index_order}: установлен параметр потока {param_name} = {value}")
            return True
        else:
            logger.warning(f"Камера {self.index_order}: параметр потока {param_name} не поддерживается")
            return False

    def _get_parameter_camera(self, param_name: str) -> Optional[Any]:
        """
        Получение значения параметра камеры.

        Args:
            param_name: Название параметра камеры

        Returns:
            Optional[Any]: Значение параметра или None
        """
        if hasattr(self._device, param_name):
            value = getattr(self._device, param_name).get()
            return value
        else:
            logger.warning(f"Камера {self.index_order}: параметр {param_name} не поддерживается")
            return None

    def _get_parameter_stream(self, param_name: str) -> Optional[Any]:
        """
        Получение значения параметра потока камеры.

        Args:
            param_name: Название параметра потока камеры

        Returns:
            Optional[Any]: Значение параметра или None
        """
        if hasattr(self._stream, param_name):
            value = getattr(self._stream, param_name).get()
            return value
        else:
            logger.warning(f"Камера {self.index_order}: параметр {param_name} не поддерживается")
            return None

    def connect(self) -> bool:
        """ Подключение камеры. """
        try:
            if self._device is None:
                logger.error(f"Камера {self.index_order}: устройство не инициализировано")
                return False

            if self.is_busy:
                logger.warning(f"Камера {self.index_order}: уже подключена")
                return True

            self._device.stream_on()
            self.is_busy = True

            logger.info(f"Камера {self.index_order} начала захват кадров")
            return True

        except Exception as e:
            logger.error(f"Ошибка подключения камеры {self.index_order}: {e}")
            self.is_busy = False
            return False

    def disconnect(self) -> None:
        """ Отключение камеры. """
        try:
            if self._device is not None and self.is_busy:
                self._device.stream_off()
                logger.info(f"Камера {self.index_order} остановлена")

            self._stream = self._device.data_stream[0] if self._device else None

        except Exception as e:
            logger.error(f"Ошибка отключения камеры {self.index_order}: {e}")
        finally:
            self.priority = 0
            self.is_busy = False
            self.is_allowed_broadcast = True

    def read_AOI(self,
                 max_attempts: int = 100,
                 number_frames_to_analyze: int = 10,
                 max_difference_exposure: int = 5
                 ) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Блокирующий метод чтения кадра с камеры с повторными попытками при автоэкспозиции.
        Применяется в процессе инспекции.

        Args:
            max_attempts: Максимальное количество попыток получить кадр
            number_frames_to_analyze: Количество фреймов для анализа перепадов экспозиции
            max_difference_exposure: Максимально допустимая разница в процентах
                                    между экспозициями в выборке

        Returns:
            Tuple[bool, Optional[np.ndarray]]: (success, frame)
        """

        def calculate_average_difference(values):
            """
            Вычисляет среднюю абсолютную разницу между последовательными элементами массива.
            """
            if not values or len(values) < 2:
                return 0.0

            differences = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
            return sum(differences) / len(differences) if differences else 0.0

        with self._stream_lock:
            frame_exposures = deque(maxlen=number_frames_to_analyze)
            attempt = 0
            while attempt < max_attempts:
                try:
                    raw_image = self._stream.get_image(50)

                    if raw_image is not None:
                        numpy_image = raw_image.get_numpy_array()

                        if numpy_image is not None and numpy_image.size > 0:
                            rgb_image = cv2.cvtColor(numpy_image, cv2.COLOR_BAYER_RG2RGB)

                            start_time = time.time()
                            get_exposure(rgb_image)
                            print(f"Время: {time.time() - start_time}")

                            if (self._exposure_level is not None
                                    and abs(self._exposure_level - get_exposure(rgb_image)) <= max_difference_exposure):
                                return True, rgb_image
                            else:
                                self._exposure_level = None
                                frame_exposures.append(get_exposure(rgb_image))

                                if len(frame_exposures) < number_frames_to_analyze:
                                    continue

                                if calculate_average_difference(frame_exposures) <= max_difference_exposure:
                                    self._exposure_level = np.mean(frame_exposures)
                                    return True, rgb_image

                        else:
                            frame_exposures.clear()
                    else:
                        frame_exposures.clear()

                    attempt += 1
                    delay = min(0.02 * attempt, 0.1)
                    time.sleep(delay)

                except CameraException:
                    raise
                except Exception as e:
                    logger.error(f"Ошибка при чтении кадра с камеры {self.index_order}: {e}")
                    raise CameraException(message=f"Неизвестная ошибка при чтении кадра с камеры {self.index_order}")

            logger.error(f"Не удалось получить кадр с камеры {self.index_order} после {max_attempts} попыток")
            return False, None

    def read_AOI_fast(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Блокирующий метод чтения кадра с камеры (одиночное чтение).

        Returns:
            Tuple[bool, Optional[np.ndarray]]: (success, frame)
        """
        with self._stream_lock:
            try:
                raw_image = self._device.data_stream[0].get_image(50)

                if raw_image is None:
                    logger.warning(f"Проблема обработки изображения с камеры {self.index_order}")
                    return False, None

                numpy_image = raw_image.get_numpy_array()
                rgb_image = cv2.cvtColor(numpy_image, cv2.COLOR_BAYER_RG2RGB)
                return True, rgb_image

            except CameraException:
                raise
            except Exception as e:
                logger.error(f"Ошибка при чтении кадра с камеры {self.index_order}: {e}")
                raise CameraException(message=f"Неизвестная ошибка при чтении кадра с камеры {self.index_order}")

        # logger.error(f"Не удалось получить кадр с камеры {self.index_order} после {max_attempts} попыток")
        # return False, None

    def read(self) -> tuple[bool, None] | None:
        """
        Метод чтения кадра с камеры (одиночное чтение).

        Returns:
            Tuple[bool, Optional[np.ndarray]]: (success, frame)
        """
        if not self._stream_lock.acquire(timeout=5.0):
            logger.warning(f"Таймаут ожидания доступа к камере {self.index_order}")
            return False, None

        try:
            raw_image = self._device.data_stream[0].get_image(50)

            if raw_image is None:
                logger.warning(f"Проблема обработки изображения с камеры {self.index_order}")
                return False, None

            numpy_image = raw_image.get_numpy_array()
            rgb_image = cv2.cvtColor(numpy_image, cv2.COLOR_BAYER_RG2RGB)
            return True, rgb_image

        except Exception as e:
            logger.error(f"Проблема обработки изображения с камеры {self.index_order}: {e}")
            return False, None
        finally:
            self._stream_lock.release()

    def cleanup(self) -> bool:
        """ Полное освобождение ресурсов камеры. """
        try:
            self.disconnect()
            if self._device is not None:
                self._device.close_device()
                self._device = None
                logger.debug(f"Камера {self.index_order}: ресурсы освобождены")
            else:
                logger.debug(f"Камера {self.index_order}: устройство уже было закрыто")

            return True

        except Exception as e:
            logger.error(f"Ошибка очистки ресурсов камеры {self.index_order}: {e}")
            return False

    def __del__(self) -> None:
        """ Освобождение ресурсов при уничтожении объекта. """
        try:
            if self.cleanup():
                logger.debug(f"Деструктор Camera {self.index_order} сработал")
            else:
                raise
        except Exception as e:
            logger.error(f"Ошибка в деструкторе Camera {self.index_order}: {e}")

    @classmethod
    def _load_camera_config(cls) -> None:
        """Загружает характеристики камеры из JSON файла и перезаписывает значения по умолчанию."""
        if cls._config_loaded:
            return

        config_path = "project/configuration/camera_config.json"

        try:
            cls.SENSOR_WIDTH_PX = read_from_json(config_path, "sensor_width_px") or cls.SENSOR_WIDTH_PX
            cls.SENSOR_HEIGHT_PX = read_from_json(config_path, "sensor_height_px") or cls.SENSOR_HEIGHT_PX
            cls.FOV_WIDTH_MM = read_from_json(config_path, "fov_width_mm") or cls.FOV_WIDTH_MM
            cls.FOV_HEIGHT_MM = read_from_json(config_path, "fov_height_mm") or cls.FOV_HEIGHT_MM
            cls.MM_TO_PX = read_from_json(config_path, "mm_to_px") or cls.MM_TO_PX
            cls.PX_TO_MM = read_from_json(config_path, "px_to_mm") or cls.PX_TO_MM
            cls.MODEL_NAME = read_from_json(config_path, "model_name") or cls.MODEL_NAME
            cls.VENDOR = read_from_json(config_path, "vendor") or cls.VENDOR

            logger.debug(f"Характеристики камеры загружены из {config_path}")

        except FileNotFoundError:
            logger.warning(f"Файл конфигурации камеры не найден: {config_path}. Используются значения по умолчанию.")
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации камеры: {e}. Используются значения по умолчанию.")
        finally:
            cls._config_loaded = True

    @classmethod
    def get_sensor_size_px(cls) -> Tuple[int, int]:
        """Возвращает размер сенсора в пикселях (ширина, высота)."""
        cls._load_camera_config()
        return cls.SENSOR_WIDTH_PX, cls.SENSOR_HEIGHT_PX

    @classmethod
    def get_fov_mm(cls) -> Tuple[float, float]:
        """Возвращает поле зрения в мм (ширина, высота)."""
        cls._load_camera_config()
        return cls.FOV_WIDTH_MM, cls.FOV_HEIGHT_MM

    @classmethod
    def get_px_to_mm(cls) -> float:
        """Возвращает коэффициент пересчёта пикселей в мм."""
        cls._load_camera_config()
        return cls.PX_TO_MM

    @classmethod
    def get_mm_to_px(cls) -> float:
        """Возвращает коэффициент пересчёта мм в пиксели."""
        cls._load_camera_config()
        return cls.MM_TO_PX
