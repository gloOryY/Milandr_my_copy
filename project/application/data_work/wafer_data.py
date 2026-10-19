from flet import *
import math
import string
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Callable, Union, Any
from threading import Lock
from project.application.addition.logger import logger


class DieStatus(Enum):
    """ Статус кристалла """
    GOOD = "Годен"
    BAD = "Негоден"
    SKIP = "Пропустить"
    NEED_CHECK = "Нужно проверить"
    DUMMY = "Фиктивный"


class DieVisual:
    """
    Визуальное представление одного кристалла.

    Attributes:
        draw_x (float): координата X для отрисовки на Canvas
        draw_y (float): координата Y для отрисовки на Canvas
        _color (Optional[str]): Внутреннее хранилище цвета
        shape (str): Форма отрисовки ("square" или "circle")
        paint_ref (Optional[Any]): Ссылка на Paint объект для обновления цвета
    """

    def __init__(self, draw_x: float, draw_y: float) -> None:
        """
        Инициализация визуального представления кристалла.

        Args:
            draw_x: координата X для отрисовки на Canvas
            draw_y: координата Y для отрисовки на Canvas
        """
        self.draw_x: float = draw_x
        self.draw_y: float = draw_y

        # Визуальные свойства
        self._color: Optional[str] = None
        self.shape: str = "square"

        self.paint_ref: Optional[Paint] = None

    @property
    def color(self) -> str:
        """ Возвращает текущий цвет. """
        if self._color:
            return self._color
        return Colors.GREY

    @color.setter
    def color(self, value):
        """
        Устанавливает цвет
        :param value: новый цвет
        """
        self._color = value
        if self.paint_ref:
            self.paint_ref.color = value

    def __str__(self) -> str:
        """ Строковое представление. """
        return f"DieVisual ({self.draw_x:.1f},{self.draw_y:.1f})"


@dataclass
class Die:
    """
    Модель данных для одного кристалла.

    Attributes:
        id (int): Уникальный идентификатор кристалла (начинается с 1)
        row (int): Настоящий индекс строки (0-based)
        col (int): Настоящий индекс столбца (0-based)
        map_x (int): X координата с карты
        map_y (int): Y координата с карты
        physical_x (Optional[float]): Физическая координата X
        physical_y (Optional[float]): Физическая координата Y
        symbol (str): Символ из карты (D, S, M, T, P1, f2 и т.д.)
        symbol_old (str): Символ из карты (D, S, M, T, P1, f2 и т.д.) до инспекции
        status (Optional[DieStatus]): Статус кристалла
        die_visual (Optional[DieVisual]): Визуальное представление
        file_frame_original_path (str): Путь к оригинальному изображению
        file_frame_filtered_path (str): Путь к отфильтрованному изображению
        defects_info (List[Dict]): Список словарей с информацией о каждом типе дефектов
    """
    id: int

    row: int
    col: int

    map_x: int
    map_y: int

    physical_x: Optional[float] = None
    physical_y: Optional[float] = None

    symbol: str = ""
    symbol_old: str = ""
    status: Optional['DieStatus'] = None

    die_visual: Optional['DieVisual'] = None

    defects_info: List[Dict[str, Any]] = field(default_factory=list)

    file_frame_original_path: str = ""
    file_frame_filtered_path: str = ""

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Переопределяет установку атрибутов для автоматического округления координат.

        Args:
            name: Имя атрибута
            value: Значение атрибута
        """
        if name == 'physical_x' and value is not None:
            value = round(value, 2)
        elif name == 'physical_y' and value is not None:
            value = round(value, 2)
        super().__setattr__(name, value)

    def has_physical_coords(self) -> bool:
        """ Проверяет наличие физических координат у кристалла. """
        return self.physical_x is not None and self.physical_y is not None

    def update_die_status(self,
                          new_status: 'DieStatus',
                          defects_info: List[Dict[str, Any]] = None) -> bool:
        """
        Обновляет информацию о кристалле.

        Args:
            new_status: Новый статус кристалла
            defects_info (List[Dict]): Список словарей с информацией о каждом типе дефектов

        Returns:
            bool: True если цвет был изменен, иначе False
        """
        if not self or not self.die_visual:
            return False

        self.status = new_status

        # Определяем целевой цвет по статусу
        if self.status == DieStatus.BAD:
            self.symbol = "FV"

            if defects_info is not None:
                self.defects_info = defects_info

        elif self.status == DieStatus.GOOD:
            self.symbol = "PV"

        return True


class WaferMap:
    """
    Модель данных для всей пластины (Singleton).
    Хранит кристаллы в виде массива массивов для удобного доступа.

    Attributes:
        _instance (Optional['WaferMap']): Единственный экземпляр класса
        _lock (Lock): Блокировка для потокобезопасности
        _initialized (bool): Флаг инициализации экземпляра
        wafer_id (str): ID пластины
        total_rows (int): Общее количество строк
        total_cols (int): Общее количество столбцов
        first_die_X (int): Первая координата x (столбца)
        first_die_Y (int): Первая координата Y (строки)
        cell_size_x_mm (Optional[float]): Длина кристалла в мм
        cell_size_y_mm (Optional[float]): Ширина кристалла в мм
        die_matrix (List[List[Optional[Die]]]): Матрица кристаллов
        symbols_need_check (List[str]): Список символов для проверки
        status_stats (Dict[DieStatus, int]): Статистика по статусам
        stats (Dict[str, int]): Статистика по символам
        orientation (WaferMapOrientation): Данные ориентации пластины
        _is_coordinates_init (bool): Флаг инициализации координат
    """

    _instance: Optional['WaferMap'] = None
    _lock: Lock = Lock()
    _initialized: bool = False

    def __new__(cls, *args, **kwargs) -> 'WaferMap':
        """
        Контролирует создание экземпляра класса.
        Если экземпляр уже существует, возвращает его, иначе создает новый.

        Returns:
            WaferMap: Единственный экземпляр класса
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 wafer_id: str = "",
                 total_rows: int = 0,
                 total_cols: int = 0,
                 first_die_X: int = 0,
                 first_die_Y: int = 0) -> None:
        """
        Инициализация модели данных пластины.
        При повторном вызове __init__ после создания экземпляра,
        инициализация не выполняется повторно (благодаря флагу _initialized).

        Args:
            wafer_id: ID пластины
            total_rows: Общее количество строк
            total_cols: Общее количество столбцов
            first_die_X: Первая координата x (столбца)
            first_die_Y: Первая координата Y (строки)
        """
        if WaferMap._initialized and self.die_matrix:
            logger.debug("WaferMap уже инициализирован с данными, повторная инициализация пропущена")
            return

        if not WaferMap._initialized:
            logger.debug("WaferMap переинициализируется после сброса")

        self.wafer_id: str = wafer_id
        self.total_rows: int = total_rows
        self.total_cols: int = total_cols
        self.first_die_X: int = first_die_X
        self.first_die_Y: int = first_die_Y

        self.cell_size_x_mm: Optional[float] = None
        self.cell_size_y_mm: Optional[float] = None

        self.die_matrix: List[List[Optional[Die]]] = []
        self.symbols_need_check: List[str] = []
        self.status_stats: Dict[DieStatus, int] = {
            DieStatus.GOOD: 0,
            DieStatus.BAD: 0,
            DieStatus.SKIP: 0,
            DieStatus.NEED_CHECK: 0,
            DieStatus.DUMMY: 0,
        }
        self.stats: Dict[str, int] = {}

        self._is_coordinates_init: bool = False

        self.orientation = WaferMapOrientation(update_callback=self._on_orientation_changed)
        self.die_prev_ref: Optional[Die] = None
        self.protocol = None
        self._move_to_die_callback = None

        WaferMap._initialized = True

    @classmethod
    def get_instance(cls,
                     wafer_id: str = "",
                     total_rows: int = 0,
                     total_cols: int = 0,
                     first_die_X: int = 0,
                     first_die_Y: int = 0) -> 'WaferMap':
        """
        Получение единственного экземпляра WaferMap.
        Если экземпляр еще не создан, создает его с переданными параметрами.
        Если экземпляр уже существует, возвращает его (параметры игнорируются).

        Args:
            wafer_id: ID пластины
            total_rows: Общее количество строк
            total_cols: Общее количество столбцов
            first_die_X: Первая координата x (столбца)
            first_die_Y: Первая координата Y (строки)

        Returns:
            WaferMap: Единственный экземпляр модели данных пластины
        """
        if cls._instance is None:
            cls._instance = cls(
                wafer_id=wafer_id,
                total_rows=total_rows,
                total_cols=total_cols,
                first_die_X=first_die_X,
                first_die_Y=first_die_Y
            )
        return cls._instance

    @classmethod
    def has_instance(cls) -> bool:
        """
        Проверяет, создан ли уже экземпляр WaferMap.

        Returns:
            bool: True если экземпляр существует, иначе False
        """
        return cls._instance is not None

    @classmethod
    def reset_instance(cls) -> None:
        """
        Сбрасывает Singleton экземпляр.
        Используется в основном для тестирования.
        """
        with cls._lock:
            if cls._instance is not None:
                cls._instance = None
                cls._initialized = False
                logger.info("Экземпляр WaferMap сброшен")

    def set_die_prev_ref(self, die: Die):
        self.die_prev_ref = die
        if self.orientation:
            self.orientation.check_die_prev_ref()

    def _on_orientation_changed(self) -> Tuple[bool, Optional[str]]:
        """
        Callback для обновления координат при изменении ориентации.

        Returns:
            Tuple[bool, Optional[str]]: (успешно ли, сообщение об ошибке)
        """
        return self.update_die_coordinates()

    def determine_die_status(self, symbol: str) -> DieStatus:
        """ Определяет статус кристалла на основе символа, используя symbols_need_check пластины. """
        if not symbol:
            return DieStatus.SKIP

        first_char = symbol.translate(str.maketrans('', '', string.digits))
        if first_char == "D":
            return DieStatus.DUMMY

        if first_char == "FV":
            return DieStatus.BAD

        if first_char == "PV":
            return DieStatus.GOOD

        if self.symbols_need_check and first_char in self.symbols_need_check:
            return DieStatus.NEED_CHECK

        return DieStatus.SKIP

    def add_die(self, die: Die) -> bool:
        """
        Добавляет кристалл в модель и определяет его статус.

        Args:
            die: Объект кристалла

        Returns:
            bool: True в случае добавления кристалла в массив, иначе False
        """
        if 0 <= die.row < self.total_rows and 0 <= die.col < self.total_cols:
            if die.symbol:
                die.status = self.determine_die_status(die.symbol)

            self.die_matrix[die.row][die.col] = die
            return True

        return False

    def reset_data(self) -> None:
        """
        Полностью сбрасывает все данные пластины, но сохраняет экземпляр.
        Используется при загрузке новой карты годности.
        """
        if self.protocol is not None:
            try:
                self.protocol.update_protocol(self)
            except Exception as e:
                logger.error(f"Ошибка сохранения протокола: {e}")
            self.protocol.shutdown()

        self.wafer_id = ""
        self.total_rows = 0
        self.total_cols = 0
        self.first_die_X = 0
        self.first_die_Y = 0

        self.cell_size_x_mm = None
        self.cell_size_y_mm = None

        self.die_matrix = []
        self.symbols_need_check = []
        self.status_stats = {
            DieStatus.GOOD: 0,
            DieStatus.BAD: 0,
            DieStatus.SKIP: 0,
            DieStatus.NEED_CHECK: 0,
            DieStatus.DUMMY: 0,
        }
        self.stats = {}

        self._is_coordinates_init = False
        WaferMap._initialized = False

        self.orientation.reset()
        self.set_die_prev_ref(None)

        logger.debug("Данные WaferMap сброшены")

    def get_stats(self) -> Dict[str, int]:
        """Выдаёт статистику пластины."""
        if not self.stats:
            self.update_stats()
        return self.stats

    def update_stats(self) -> None:
        """Подсчитывает количество каждого уникального символа и статусов в пластине."""
        self.status_stats = {
            DieStatus.GOOD: 0,
            DieStatus.BAD: 0,
            DieStatus.SKIP: 0,
            DieStatus.NEED_CHECK: 0,
            DieStatus.DUMMY: 0,
        }
        self.stats = {}

        for row in range(self.total_rows):
            for col in range(self.total_cols):
                die = self.die_matrix[row][col]
                if die and die.symbol:
                    symbol = die.symbol.translate(str.maketrans('', '', string.digits))
                    self.stats[symbol] = self.stats.get(symbol, 0) + 1
                    self.status_stats[die.status] = self.status_stats.get(die.status, 0) + 1

    def get_total_pass_dice(self) -> int:
        """
        Возвращает суммарное количество годных кристаллов.
        Годный кристалл - это тот, у которого:
        - В symbol или symbol_old есть 'p' (или 'P')
        - И при этом НЕТ 'f' (или 'F') в symbol и symbol_old
        """
        pass_count = 0
        for row in range(self.total_rows):
            for col in range(self.total_cols):
                die = self.die_matrix[row][col]
                if not die:
                    continue

                # Проверяем, есть ли 'f' в symbol или symbol_old
                has_fail = False

                if die.symbol:
                    symbol_clean = die.symbol.translate(str.maketrans('', '', string.digits))
                    if 'f' in symbol_clean.lower():
                        has_fail = True

                if not has_fail and die.symbol_old:
                    symbol_old_clean = die.symbol_old.translate(str.maketrans('', '', string.digits))
                    if 'f' in symbol_old_clean.lower():
                        has_fail = True

                # Если есть 'f' - это брак, пропускаем
                if has_fail:
                    continue

                # Проверяем наличие 'p' в symbol
                has_pass = False
                if die.symbol:
                    symbol_clean = die.symbol.translate(str.maketrans('', '', string.digits))
                    if 'p' in symbol_clean.lower():
                        has_pass = True

                # Проверяем наличие 'p' в symbol_old
                if not has_pass and die.symbol_old:
                    symbol_old_clean = die.symbol_old.translate(str.maketrans('', '', string.digits))
                    if 'p' in symbol_old_clean.lower():
                        has_pass = True

                if has_pass:
                    pass_count += 1

        return pass_count

    def get_total_fail_dice(self) -> int:
        """
        Возвращает суммарное количество бракованных кристаллов.
        Негодный кристалл - это тот, у которого:
        - В symbol или symbol_old есть 'f' (или 'F')
        """
        fail_count = 0
        for row in range(self.total_rows):
            for col in range(self.total_cols):
                die = self.die_matrix[row][col]
                if not die:
                    continue

                # Проверяем наличие 'f' в symbol
                if die.symbol:
                    symbol_clean = die.symbol.translate(str.maketrans('', '', string.digits))
                    if 'f' in symbol_clean.lower():
                        fail_count += 1
                        continue

                # Проверяем наличие 'f' в symbol_old
                if die.symbol_old:
                    symbol_old_clean = die.symbol_old.translate(str.maketrans('', '', string.digits))
                    if 'f' in symbol_old_clean.lower():
                        fail_count += 1

        return fail_count

    # def get_count_dice_of_symbol(self, symbol: Union[str, List[str]]) -> int:
    #     """
    #     Возвращает количество кристаллов с указанным символом(ами).
    #
    #     Args:
    #         symbol: Один символ (str) или список символов (List[str])
    #
    #     Returns:
    #         int: Суммарное количество кристаллов для всех указанных символов
    #     """
    #     if not self.stats:
    #         self.update_stats()
    #
    #     if isinstance(symbol, list):
    #         return sum(self.stats.get(s, 0) for s in symbol)
    #     else:
    #         return self.stats.get(symbol, 0)

    def get_count_dice_of_status(self, status: Union[DieStatus, List[DieStatus]]) -> int:
        """
        Возвращает количество кристаллов с указанным статусом(ами).

        Args:
            status: Один статус (DieStatus) или список статусов (List[DieStatus])

        Returns:
            int: Суммарное количество кристаллов для всех указанных статусов
        """
        if not self.stats:
            self.update_stats()

        if isinstance(status, list):
            return sum(self.status_stats.get(s, 0) for s in status)
        else:
            return self.status_stats.get(status, 0)

    def validate(self) -> Tuple[bool, str]:
        """
        Валидирует данные.

        Returns:
            Tuple[bool, str]: (валидно ли, сообщение об ошибке)
        """
        if not self.die_matrix:
            return False, "Отсутствуют данные о кристаллах"

        if not (len(self.die_matrix) != 0 and len(self.die_matrix[0]) != 0):
            return False, "Пластина не содержит ни одного кристалла"

        if self.get_count_dice_of_status(DieStatus.NEED_CHECK) == 0:
            return False, "Пластина не содержит кристаллов, которые нужно проверить"

        if self.die_prev_ref is not None:
            self.orientation.update_first_reference_die(self.die_prev_ref)
            self.orientation.update_coordinates_of_first_reference_die(
                x=self.die_prev_ref.physical_x,
                y=self.die_prev_ref.physical_y
            )
        else:
            self.set_die_prev_ref(self.orientation.first_reference_die)

        return self.orientation.validate()

    def update_die_coordinates_by_reference_die(self,
                                                die: 'Die',
                                                die_real_coords: Tuple[float, float]) -> bool:
        """
        Обновляет физические координаты кристаллов на основе референсной точки и размеров ячеек.

        Args:
            die: Первый референсный кристалл (фиксированная точка привязки)
            die_real_coords: Реальные координаты первого референсного кристалла

        Returns:
            bool: True если координаты успешно обновлены
        """
        if die is None or die_real_coords is None or None in die_real_coords:
            return False

        if self.cell_size_x_mm is None or self.cell_size_y_mm is None:
            return False

        if self.cell_size_x_mm <= 0 or self.cell_size_y_mm <= 0:
            return False

        ref_row = die.row
        ref_col = die.col
        ref_x, ref_y = die_real_coords

        for row_idx in range(self.total_rows):
            for col_idx in range(self.total_cols):
                current_die = self.die_matrix[row_idx][col_idx]
                if current_die:
                    row_offset = row_idx - ref_row
                    col_offset = col_idx - ref_col

                    current_die.physical_x = ref_x + col_offset * self.cell_size_x_mm
                    current_die.physical_y = ref_y - row_offset * self.cell_size_y_mm

        self._is_coordinates_init = True
        return True

    def update_die_coordinates_AOI(self,
                                   first_die: Die,
                                   second_die: Die,
                                   second_die_coords: Tuple[float, float],
                                   traversal_path: List[Tuple[int, int]] = None) -> bool:
        """
        Обновляет физические координаты непроинспектированных кристаллов.
        Коррекция смещения (сдвиг всех непроинспектированных кристаллов)

        Args:
            first_die: Предыдущий референсный кристалл
            second_die: Текущий кристалл (становится новым референсным)
            second_die_coords: Фактические координаты текущего кристалла
            traversal_path: Путь обхода непроинспектированных кристаллов

        Returns:
            bool: True если координаты успешно обновлены
        """
        if first_die is None or second_die is None or traversal_path is None:
            return False

        if first_die == second_die:
            self.update_die_coordinates_by_reference_die(first_die, second_die_coords)
            return True

        # Координаты предыдущего референсного кристалла
        real_x1, real_y1 = first_die.physical_x, first_die.physical_y

        # Фактические координаты текущего кристалла (из центровки)
        real_x2, real_y2 = second_die_coords

        # Теоретические координаты текущего кристалла
        theoretical_x2 = second_die.physical_x
        theoretical_y2 = second_die.physical_y

        # Проверка допустимого диапазона расстояний
        actual_distance = math.hypot(real_x2 - real_x1, real_y2 - real_y1)
        theoretical_distance = math.hypot(theoretical_x2 - real_x1, theoretical_y2 - real_y1)

        half_width = self.cell_size_x_mm / 2.0
        half_height = self.cell_size_y_mm / 2.0
        max_deviation = math.hypot(half_width, half_height)

        min_allowed = max(0, theoretical_distance - max_deviation)
        max_allowed = theoretical_distance + max_deviation

        if not (min_allowed <= actual_distance <= max_allowed):
            logger.error(f"Расстояние вне допустимого диапазона!")
            return False

        # Смещение между теоретическими и фактическими координатами
        offset_x = real_x2 - theoretical_x2
        offset_y = real_y2 - theoretical_y2

        # Применяем смещение ко всем непроинспектированным кристаллам
        for pos in traversal_path:
            row, col = pos
            die = self.die_matrix[row][col]
            if die:
                die.physical_x += offset_x
                die.physical_y += offset_y

        self.die_prev_ref = second_die
        return True

    def update_die_coordinates(self, is_need_update: bool = False) -> Tuple[bool, Optional[str]]:
        """
        Обновляет физические координаты кристаллов на основе референсных точек и угла поворота между ними.

        Args:
            is_need_update: Метка на принудительное обновление без учета _is_coordinates_init

        Returns:
            Tuple[bool, Optional[str]]: (валидно ли, сообщение об ошибке)
        """
        if not self._is_coordinates_init or is_need_update:
            if not self.update_die_coordinates_by_reference_die(
                    die=self.orientation.first_reference_die,
                    die_real_coords=(self.orientation.x_coord_of_first_reference_die,
                                     self.orientation.y_coord_of_first_reference_die)
            ):
                return False, None

        if not (self.orientation.first_reference_die and self.orientation.second_reference_die
                and self.orientation.is_coordinates_of_first_reference_die()
                and self.orientation.is_coordinates_of_second_reference_die()):
            return False, None

        first_die = self.orientation.first_reference_die
        second_die = self.orientation.second_reference_die

        if not first_die or not second_die:
            error_message = "Референсные кристаллы не найдены в матрице"
            logger.error(error_message)
            return False, error_message

        real_x1 = self.orientation.x_coord_of_first_reference_die
        real_y1 = self.orientation.y_coord_of_first_reference_die
        real_x2 = self.orientation.x_coord_of_second_reference_die
        real_y2 = self.orientation.y_coord_of_second_reference_die

        model_x1 = first_die.physical_x
        model_y1 = first_die.physical_y
        model_x2 = second_die.physical_x
        model_y2 = second_die.physical_y

        real_vector_x = real_x2 - real_x1
        real_vector_y = real_y2 - real_y1
        model_vector_x = model_x2 - model_x1
        model_vector_y = model_y2 - model_y1

        # Проверка совпадения длин векторов
        TOLERANCE_MM = 1.0
        real_distance = math.hypot(real_vector_x, real_vector_y)
        model_distance = math.hypot(model_vector_x, model_vector_y)

        distance_dice = abs(real_distance - model_distance)
        if distance_dice > TOLERANCE_MM:
            error_message = f"Критическое несоответствие расстояний между референсными кристаллами: {distance_dice}"
            logger.error(error_message)
            return False, error_message

        real_angle = math.atan2(real_vector_y, real_vector_x)
        model_angle = math.atan2(model_vector_y, model_vector_x)

        rotation_angle = real_angle - model_angle
        self.orientation.update_rotation_angle(rotation_angle)

        for row_idx in range(self.total_rows):
            for col_idx in range(self.total_cols):
                die = self.die_matrix[row_idx][col_idx]
                if die:
                    rel_x = die.physical_x - model_x1
                    rel_y = die.physical_y - model_y1

                    rotated_x = rel_x * math.cos(rotation_angle) - rel_y * math.sin(rotation_angle)
                    rotated_y = rel_x * math.sin(rotation_angle) + rel_y * math.cos(rotation_angle)

                    die.physical_x = real_x1 + rotated_x
                    die.physical_y = real_y1 + rotated_y

        self.die_prev_ref = first_die
        return True, None

    def set_move_to_die_callback(self, callback: Callable[['Die'], None]) -> None:
        """
        Устанавливает callback для перемещения на кристалл.

        Args:
            callback: Функция, принимающая объект Die (кристалл), на который нужно переместиться
        """
        self._move_to_die_callback = callback

    def move_to_die(self, die: 'Die') -> None:
        """
        Вызывает callback для перемещения на кристалл.

        Args:
            die: Кристалл, в координаты которого нужно переместиться
        """
        if self._move_to_die_callback:
            self._move_to_die_callback(die)
        else:
            logger.warning("Callback для перемещения на кристалл не установлен")


class WaferMapOrientation:
    """
    Данные для коррекции ориентации пластины.

    Связан с WaferMap через композицию - каждый экземпляр WaferMap имеет свой
    экземпляр WaferMapOrientation.
    """

    def __init__(self, update_callback: Optional[Callable[[], Tuple[bool, Optional[str]]]] = None):
        """
        Инициализация данных ориентации пластины.

        Args:
            update_callback: Функция для обновления координат WaferMap
        """
        self.x_coord_of_first_reference_die: Optional[float] = None
        self.y_coord_of_first_reference_die: Optional[float] = None
        self.z_coord_of_first_reference_die: Optional[float] = None

        self.x_coord_of_second_reference_die: Optional[float] = None
        self.y_coord_of_second_reference_die: Optional[float] = None

        self.first_reference_die: Optional[Die] = None
        self.second_reference_die: Optional[Die] = None

        self.rotation_angle: Optional[float] = None
        self.angle_deg: Optional[float] = None

        self._update_callback: Optional[Callable[[], Tuple[bool, Optional[str]]]] = update_callback
        self._listeners: List[Callable[[], None]] = []

    def validate(self) -> Tuple[bool, str]:
        """
        Валидирует данные.

        Returns:
            Tuple[bool, str]: (валидно ли, сообщение об ошибке)
        """
        if self.first_reference_die is None:
            return False, "Не выбран первый референсный кристалл"

        if not self.is_coordinates_of_first_reference_die():
            return False, "Не определены координаты первого референсного кристалла"

        if self.rotation_angle and not -180 <= self.rotation_angle <= 180:
            return False, "Угол поворота пластины должен быть в диапазоне от -180 до 180 градусов"

        return True, "Данные валидны"

    def _update_reference_die(self) -> Tuple[bool, Optional[str]]:
        """ Внутренний метод для обновления данных референсной ячейки. """
        ret, error_message = True, None
        if self._update_callback:
            ret, error_message = self._update_callback()
        self._notify_listeners()
        return ret, error_message

    def update_first_reference_die(self, die: Die) -> Tuple[bool, str]:
        """ Обновляет данные первого референсного кристалла. """
        if die == self.second_reference_die:
            self.reset_second_reference_die()
        self.first_reference_die = die
        return self._update_reference_die()

    def update_second_reference_die(self, die: Die) -> Tuple[bool, str]:
        """ Обновляет данные второго референсного кристалла. """
        if die == self.first_reference_die:
            self.reset_first_reference_die()
        self.second_reference_die = die
        return self._update_reference_die()

    def update_coordinates_of_first_reference_die(self, x: float, y: float, z: float = None) -> Tuple[bool, str]:
        """ Обновляет координаты первой референсной ячейки. """
        self.x_coord_of_first_reference_die = x
        self.y_coord_of_first_reference_die = y
        if z is not None:
            self.z_coord_of_first_reference_die = z
        return self._update_reference_die()

    def update_coordinates_of_second_reference_die(self, x: float, y: float) -> Tuple[bool, str]:
        """ Обновляет координаты второй референсной ячейки. """
        self.x_coord_of_second_reference_die = x
        self.y_coord_of_second_reference_die = y
        return self._update_reference_die()

    def update_rotation_angle(self, angle_rad: float) -> None:
        """ Обновляет угол поворота пластины. """
        self.rotation_angle = angle_rad

        angle_deg = math.degrees(angle_rad)
        normalized_angle = angle_deg % 360
        if normalized_angle > 180:
            normalized_angle -= 360

        self.angle_deg = normalized_angle
        self._notify_listeners()

    def is_coordinates_of_first_reference_die(self) -> bool:
        """ Проверяет, заданы ли координаты первого референсного кристалла. """
        return (self.x_coord_of_first_reference_die is not None
                and self.y_coord_of_first_reference_die is not None)

    def is_coordinates_of_second_reference_die(self) -> bool:
        """ Проверяет, заданы ли координаты второго референсного кристалла. """
        return (self.x_coord_of_second_reference_die is not None
                and self.y_coord_of_second_reference_die is not None)

    def is_first_reference_cell(self) -> bool:
        """ Проверяет, задан ли первый референсный кристалл. """
        return self.first_reference_die is not None

    def is_second_reference_cell(self) -> bool:
        """ Проверяет, задан ли второй референсный кристалл. """
        return self.second_reference_die is not None

    def reset(self) -> None:
        """ Сбрасывает значения к дефолтным. """
        self.reset_coordinates_of_first_reference_die(is_notify=False)
        self.reset_coordinates_of_second_reference_die(is_notify=False)
        self.reset_first_reference_die(is_notify=False)
        self.reset_second_reference_die(is_notify=False)
        self.reset_rotation_angle(is_notify=True)

    def reset_coordinates_of_first_reference_die(self, is_notify: bool = True) -> None:
        """ Сбрасывает координаты первого референсного кристалла. """
        self.x_coord_of_first_reference_die = None
        self.y_coord_of_first_reference_die = None
        self.z_coord_of_first_reference_die = None
        if is_notify:
            self._notify_listeners()

    def reset_coordinates_of_second_reference_die(self, is_notify: bool = True) -> None:
        """ Сбрасывает координаты второго референсного кристалла. """
        self.x_coord_of_second_reference_die = None
        self.y_coord_of_second_reference_die = None
        if is_notify:
            self._notify_listeners()

    def reset_first_reference_die(self, is_notify: bool = True) -> None:
        """Удаляет первый референсный кристалл. """
        self.first_reference_die = None
        if is_notify:
            self._notify_listeners()

    def reset_second_reference_die(self, is_notify: bool = True) -> None:
        """ Удаляет второй референсный кристалл. """
        self.second_reference_die = None
        if is_notify:
            self._notify_listeners()

    def reset_rotation_angle(self, is_notify: bool = True) -> None:
        """Сбрасывает угол поворота пластины."""
        self.rotation_angle = None
        if is_notify:
            self._notify_listeners()

    def add_listener(self, callback: Callable[[], None]) -> None:
        """ Добавляет слушателя на обновления данных. """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        """ Удаляет слушателя. """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self) -> None:
        """ Уведомляет всех слушателей об изменении. """
        for listener in self._listeners:
            try:
                listener()
            except Exception as e:
                logger.error(f"Ошибка в слушателе обновления: {e}")

    def check_die_prev_ref(self):
        self._notify_listeners()
