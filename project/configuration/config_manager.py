from typing import Any, Union, Dict
from threading import Lock
from project.configuration.worker import read_from_json, write_to_json


def _save_coordinates(file_path, data, keys, fields):
    """ Сохраняет координаты в JSON-файл. """
    for key, field in zip(keys, fields):
        write_to_json(file_path, key, data[field])


def _load_coordinates(file_path, keys, fields):
    """ Загружает координаты из JSON-файла. """
    return {
        field: read_from_json(file_path, key)
        for key, field in zip(keys, fields)
    }


def _load_settings(file_path, keys, fields):
    """ Загружает настройки из JSON-файла. """
    return {
        field: read_from_json(file_path, key)
        for key, field in zip(keys, fields)
    }


def _save_settings(file_path, data, keys, fields):
    """ Сохраняет настройки в JSON-файл. """
    for key, field in zip(keys, fields):
        write_to_json(file_path, key, data[field])


class ConfigManager:
    """
    Класс ConfigManager хранит состояние конфигурации приложения во время его выполнения.
    Реализован как Singleton для обеспечения единственного экземпляра конфигурации.

    Передаёт конфигурационные данные во время выполнения приложения,
    и все необходимые для него вспомогательные методы.

    Attributes:
        _instance (Optional['ConfigManager']): Единственный экземпляр класса
        _initialized (bool): Флаг инициализации экземпляра
        _lock (Lock): Блокировка для потокобезопасности
        auto_save_rules (Dict[str, Dict]): Правила автосохранения для атрибутов
        current_coordinates (Dict[str, float]): Текущие координаты робота
        extreme_coordinates (Dict[str, float]): Предельные координаты рабочей области робота
        coordinate_of_the_first_cell (Dict[str, float]): Координаты референсного кристалла
        wafer_params (Dict[str, float]): Параметры пластины с кристаллами (расстояния)
        picture_parameters (Dict[str, Union[int, float]]): Настроечные параметры изображения
        scale_buttons_panel (float): Размер кнопок-кристаллов
        movement_step (float): Шаг перемещения робота во вкладке "Калибровка системы"
        move_to_first_ref_die_switch (bool): Переключатель на первый кристалл после калибровке во вкладке "Калибровка"
        translation_coefficient (float): Коэффициент пересчета
        current_measure_unit (str): Текущая единица измерения
        current_theme (str): Текущая тема приложения
        symbols_need_check (List[str]): Виды кристаллов для проверки
        input_file_path (str): Путь к входному файлу
        protocol_path (str): Путь к файлу протокола
        sharpness_ideal (float): Идеальное значение резкости
        page: Объект страницы (Flet page)
    """

    _instance: Any = None
    _initialized: bool = False
    _lock: Lock = Lock()

    def __new__(cls, *args, **kwargs) -> 'ConfigManager':
        """
        Контролирует создание экземпляра класса.
        Если экземпляр уже существует, возвращает его, иначе создает новый.

        Returns:
            ConfigManager: Единственный экземпляр класса
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, page: Any) -> None:
        """
        Инициализация менеджера конфигурации.
        При повторном вызове __init__ после создания экземпляра,
        инициализация не выполняется повторно (благодаря флагу _initialized).

        Args:
            page: Объект страницы Flet
        """
        # Предотвращаем повторную инициализацию
        if ConfigManager._initialized:
            return

        self.auto_save_rules = {}
        self._load_all_configs()

        self.sharpness_ideal = 0
        self.page = page

        # Устанавливаем флаг инициализации
        ConfigManager._initialized = True

    @classmethod
    def get_instance(cls, page: Any = None) -> 'ConfigManager':
        """
        Получение единственного экземпляра ConfigManager.
        Если экземпляр еще не создан, создает его с переданными параметрами.
        Если экземпляр уже существует, возвращает его (параметры игнорируются).

        Args:
            page: Объект страницы Flet (обязателен при первом вызове)

        Returns:
            ConfigManager: Единственный экземпляр менеджера конфигурации

        Raises:
            ValueError: Если экземпляр еще не создан и не передан page
        """
        with cls._lock:
            if cls._instance is None:
                if page is None:
                    raise ValueError(
                        "ConfigManager не инициализирован. "
                        "При первом вызове get_instance() необходимо передать page"
                    )
                cls._instance = cls(page=page)
        return cls._instance

    @classmethod
    def has_instance(cls) -> bool:
        """
        Проверяет, создан ли уже экземпляр ConfigManager.

        Returns:
            bool: True если экземпляр существует, иначе False
        """
        return cls._instance is not None

    @classmethod
    def reset_instance(cls) -> None:
        """
        Сбрасывает Singleton экземпляр.
        Используется в основном для тестирования или при необходимости
        полного пересоздания менеджера конфигурации с новыми параметрами.
        """
        with cls._lock:
            if cls._instance is not None:
                # Сохраняем все настройки перед сбросом
                for name, value in cls._instance.__dict__.items():
                    if name in cls._instance.auto_save_rules and not name.startswith('_'):
                        cls._instance.auto_save_attribute(name, value)
                cls._instance = None
                cls._initialized = False

    def _load_all_configs(self) -> None:
        """ Загружает все конфигурации при инициализации. """

        self.current_coordinates = _load_coordinates(
            "project/configuration/coordinates.json",
            keys=("current_coordinate_of_the_station_by_x",
                  "current_coordinate_of_the_station_by_y",
                  "current_coordinate_of_the_station_by_z"),
            fields=("x", "y", "z"))

        self.coordinate_of_the_first_cell = _load_coordinates(
            "project/configuration/coordinates.json",
            keys=("x_coordinate_of_the_first_cell",
                  "y_coordinate_of_the_first_cell",
                  "z_coordinate_of_the_first_cell"),
            fields=("x", "y", "z"))

        self.extreme_coordinates = _load_coordinates(
            "project/configuration/coordinates.json",
            keys=("x_minimum",
                  "x_maximum",
                  "y_minimum",
                  "y_maximum",
                  "z_minimum",
                  "z_maximum"),
            fields=("x_min", "x_max", "y_min", "y_max", "z_min", "z_max"))

        self.wafer_params = _load_settings(
            "project/configuration/launch.json",
            keys=("distance_between_horizontal_centers_of_cells",
                  "distance_between_vertical_centers_of_cells"),
            fields=("x_distance", "y_distance"))

        self.picture_parameters = _load_settings(
            "project/configuration/picture.json",
            keys=("brightness", "contrast", "saturation", "grain_level",
                  "red_filter", "green_filter", "blue_filter"),
            fields=("brightness", "contrast", "saturation", "grain_level",
                    "red_filter", "green_filter", "blue_filter"))

        self.scale_buttons_panel = read_from_json(
            "project/configuration/panel_switches.json",
            "scale_buttons_panel")

        self.movement_step = read_from_json(
            "project/configuration/panel_switches.json",
            "movement_step")

        self.move_to_first_ref_die_switch = read_from_json(
            "project/configuration/panel_switches.json",
            "move_to_first_ref_die_switch")

        self.translation_coefficient = read_from_json(
            "project/configuration/measure.json",
            "translation_coefficient")

        self.current_measure_unit = read_from_json(
            "project/configuration/measure.json",
            "measure_units")

        self.current_theme = read_from_json(
            "project/configuration/theme.json",
            "theme")

        self.symbols_need_check = read_from_json(
            "project/configuration/launch.json",
            "symbols_need_check")

        self.input_file_path = read_from_json(
            "project/configuration/protocol.json",
            "input_file_path")

        self.protocol_path = read_from_json(
            "project/configuration/protocol.json",
            "protocol_path")

        # Настройка правил автосохранения
        self._setupauto_save_rules()

    def _setupauto_save_rules(self):
        """Настраивает правила автоматического сохранения для атрибутов. """

        # Простые атрибуты (сохраняются целиком)
        self.auto_save_rules.update({
            'scale_buttons_panel': {
                'file': "project/configuration/panel_switches.json",
                'key': "scale_buttons_panel",
                'type': 'simple'
            },
            'movement_step': {
                'file': "project/configuration/panel_switches.json",
                'key': "movement_step",
                'type': 'simple'
            },
            'move_to_first_ref_die_switch': {
                'file': "project/configuration/panel_switches.json",
                'key': "move_to_first_ref_die_switch",
                'type': 'simple'
            },
            'translation_coefficient': {
                'file': "project/configuration/measure.json",
                'key': "translation_coefficient",
                'type': 'simple'
            },
            'current_measure_unit': {
                'file': "project/configuration/measure.json",
                'key': "measure_units",
                'type': 'simple'
            },
            'current_theme': {
                'file': "project/configuration/theme.json",
                'key': "theme",
                'type': 'simple'
            },
            'symbols_need_check': {
                'file': "project/configuration/launch.json",
                'key': "symbols_need_check",
                'type': 'simple'
            },
            'input_file_path': {
                'file': "project/configuration/protocol.json",
                'key': "input_file_path",
                'type': 'simple'
            },
            'protocol_path': {
                'file': "project/configuration/protocol.json",
                'key': "protocol_path",
                'type': 'simple'
            },
        })

        # Сложные атрибуты-словари (требуют специальной обработки)
        self.auto_save_rules.update({
            'current_coordinates': {
                'type': 'coordinates',
                'file': "project/configuration/coordinates.json",
                'keys': ("current_coordinate_of_the_station_by_x",
                         "current_coordinate_of_the_station_by_y",
                         "current_coordinate_of_the_station_by_z"),
                'fields': ("x", "y", "z"),
                'save_func': _save_coordinates
            },
            'coordinate_of_the_first_cell': {
                'type': 'coordinates',
                'file': "project/configuration/coordinates.json",
                'keys': ("x_coordinate_of_the_first_cell",
                         "y_coordinate_of_the_first_cell",
                         "z_coordinate_of_the_first_cell"),
                'fields': ("x", "y", "z"),
                'save_func': _save_coordinates
            },
            'wafer_params': {
                'type': 'settings',
                'file': "project/configuration/launch.json",
                'keys': ("distance_between_horizontal_centers_of_cells",
                         "distance_between_vertical_centers_of_cells"),
                'fields': ("x_distance", "y_distance"),
                'save_func': _save_settings
            },
            'picture_parameters': {
                'type': 'settings',
                'file': "project/configuration/picture.json",
                'keys': ("brightness", "contrast", "saturation", "grain_level",
                         "red_filter", "green_filter", "blue_filter"),
                'fields': ("brightness", "contrast", "saturation", "grain_level",
                           "red_filter", "green_filter", "blue_filter"),
                'save_func': _save_settings
            },
        })

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Перехватывает установку всех атрибутов.
        Если атрибут есть в правилах автосохранения, сохраняет его в JSON.

        Args:
            name: Имя атрибута
            value: Значение атрибута
        """
        super().__setattr__(name, value)

        if hasattr(self, 'auto_save_rules') and name in self.auto_save_rules:
            self.auto_save_attribute(name, value)

    def auto_save_attribute(self, name: str, value: Any) -> None:
        """
        Сохраняет атрибут в JSON согласно правилам.

        Args:
            name: Имя атрибута
            value: Значение атрибута
        """
        rule = self.auto_save_rules[name]

        if rule['type'] == 'simple':
            # Простое сохранение
            write_to_json(rule['file'], rule['key'], value)

        elif rule['type'] in ('coordinates', 'settings'):
            # Сохранение словаря с помощью специальной функции
            rule['save_func'](
                rule['file'],
                value,
                rule['keys'],
                rule['fields']
            )

    def update_picture_parameter(self, key: str, value: Union[int, float]) -> None:
        """ Обновляет параметр изображения и сохраняет в JSON. """
        self.picture_parameters[key] = value
        self._save_picture_parameters()

    def update_picture_parameters(self, updates_dict: Dict[str, Union[int, float]]) -> None:
        """ Обновляет несколько параметров изображения одновременно. """
        for key, value in updates_dict.items():
            self.picture_parameters[key] = value
        self._save_picture_parameters()

    def _save_picture_parameters(self) -> None:
        """ Сохраняет все параметры изображения в JSON. """
        _save_settings(
            "project/configuration/picture.json",
            data=self.picture_parameters,
            keys=("brightness", "contrast", "saturation", "grain_level",
                  "red_filter", "green_filter", "blue_filter"),
            fields=("brightness", "contrast", "saturation", "grain_level",
                    "red_filter", "green_filter", "blue_filter")
        )

    def __del__(self) -> None:
        """ Деструктор - сохраняет конфигурацию при удалении объекта. """
        if hasattr(self, 'auto_save_rules'):
            for name, value in self.__dict__.items():
                if name in self.auto_save_rules and not name.startswith('_'):
                    self.auto_save_attribute(name, value)
