import flet.canvas as cnv
from flet import *
from flet.core.column import Column
from flet.core.row import Row
import string
from typing import Optional, Dict, Tuple, List, Any, Union, Set

from project.application.addition.dialogs import show_error, show_warning
from project.application.addition.photo_viewer import open_file_in_viewer
from project.application.data_work.wafer_data import WaferMap, Die, DieStatus, DieVisual
from project.configuration.config_manager import ConfigManager
from project.application.addition.logger import logger
from project.application.addition.exceptions import KnownSystemException


class WaferMapVisual:
    """
    Визуальное представление пластины с кристаллами.

    Attributes:
        _config: Экземпляр класса конфигураций
        _page: Объект страницы Flet
        _application_colors: Цветовая схема приложения
        wafer_map (Optional[WaferMap]): Экземпляр модели данных пластины
        _canvas_ref (Optional[cnv.Canvas]): Ссылка на Canvas для обновления
        _selected_die (Optional[Die]): Текущий выбранный кристалл
        _pending_reference_selection (Optional[str]): Выбранный статус до сохранения
        _original_colors (Dict[Tuple[int, int], str]): Оригинальные цвета кристаллов
        _reference_coords (Dict[str, Optional[Tuple[int, int]]]): Координаты референсных кристаллов
        _reference_text_shapes (Dict[Tuple[int, int], cnv.Text]): Текстовые элементы референсных кристаллов

        _SQUARE_SIZE (int): Размер квадрата кристалла
        _POINT_RADIUS (int): Радиус точки для круглых кристаллов
        _CELL_SIZE (int): Размер ячейки
        _SPACING (int): Отступ между ячейками
        _HIGHLIGHT_COLOR (str): Цвет подсветки
        _REFERENCE_COLOR_SELECTED (str): Цвет выбранного референсного кристалла
        _REFERENCE_COLOR (str): Цвет референсного кристалла

        save_buttons_container (Optional[Container]): Контейнер с кнопками сохранения
        reference_dropdown (Optional[Dropdown]): Выпадающий список для выбора референсного кристалла
        dialog_stack (Optional[Stack]): Стек диалогового окна
        dialog_container (Optional[Container]): Контейнер диалога

        _view_width (int): Ширина Canvas
        _view_height (int): Длина Canvas
        inspection_active (bool): Флаг активности инспекции

    """

    def __init__(self, application_colors: Dict[str, str], config: 'ConfigManager') -> None:
        """
        Инициализация визуального представления пластины.

        Args:
            application_colors: Dict[str, str]
            config: Экземпляр класса конфигураций
        """
        self._config: Any = config
        self._page: Any = config.page
        self._application_colors: Any = application_colors

        self.wafer_map: Optional['WaferMap'] = None
        self._canvas_ref: Optional[cnv.Canvas] = None

        self._selected_die: Optional['Die'] = None
        self._pending_reference_selection: Optional[str] = None
        self._original_colors: Dict[Tuple[int, int], str] = {}

        self._reference_coords: Dict[str, Optional[Tuple[int, int]]] = {
            "first": None,
            "second": None
        }
        self._reference_text_shapes: Dict[Tuple[int, int], cnv.Text] = {}

        # Параметры отрисовки (константы)
        self._SQUARE_SIZE: int = 14
        self._POINT_RADIUS: int = 7
        self._CELL_SIZE: int = 14
        self._SPACING: int = 5

        # Цвета:
        self._HIGHLIGHT_COLOR: str = Colors.WHITE
        self._REFERENCE_COLOR_SELECTED: str = Colors.BLUE_100
        self._REFERENCE_COLOR: str = Colors.BLUE_300

        # Ссылки на элементы диалога
        self._save_buttons_container: Optional[Container] = None
        self._reference_dropdown: Optional[Dropdown] = None
        self._dialog_stack: Optional[Stack] = None
        self._dialog_container: Optional[Container] = None

        self._view_width: int = 600
        self._view_height: int = 600

        self.inspection_active: bool = False
        self._dialog_is_open: bool = False

    def generate_visual(self, wafer_map: 'WaferMap' = None, scale_value: float = None) -> Row | None:
        """
        Создает визуальное представление на основе переданной модели данных пластины.
        Если передан scale_value, применяет новый масштаб.

        Args:
            wafer_map: Экземпляр модели данных пластины
            scale_value: Значение масштаба (1.0, 1.5, 2.0) или None для использования текущего

        Returns:
            Row: Визуальное представление пластины с кристаллами
        """
        try:
            if wafer_map is not None:
                self.wafer_map = wafer_map

            if not self.wafer_map:
                raise KnownSystemException(message="Модель данных пластины не установлена")

            first_ref_die, second_ref_die = None, None

            if scale_value is not None:
                scale_params = {
                    1.0: {
                        "square_size": 10,
                        "point_radius": 5,
                        "cell_size": 10,
                        "spacing": 3
                    },
                    1.5: {
                        "square_size": 14,
                        "point_radius": 7,
                        "cell_size": 14,
                        "spacing": 5
                    },
                    2.0: {
                        "square_size": 18,
                        "point_radius": 9,
                        "cell_size": 18,
                        "spacing": 8
                    }
                }

                if scale_value not in scale_params:
                    scale_value = 1.5

                params = scale_params[scale_value]

                # Проверяем, не установлены ли уже такие параметры
                if wafer_map is None and (self._SQUARE_SIZE == params["square_size"] and
                                          self._POINT_RADIUS == params["point_radius"] and
                                          self._CELL_SIZE == params["cell_size"] and
                                          self._SPACING == params["spacing"]):
                    logger.debug(f"Масштаб {scale_value}x уже установлен")
                    return None

                # Сохраняем ссылки на референсные кристаллы перед перегенерацией
                first_ref_die = self.wafer_map.orientation.first_reference_die if self.wafer_map else None
                second_ref_die = self.wafer_map.orientation.second_reference_die if self.wafer_map else None

                # Применяем новые параметры масштаба
                self._SQUARE_SIZE = params["square_size"]
                self._POINT_RADIUS = params["point_radius"]
                self._CELL_SIZE = params["cell_size"]
                self._SPACING = params["spacing"]

                # Очищаем словари перед перегенерацией
                self._original_colors.clear()
                self._reference_text_shapes.clear()
                self._reference_coords = {
                    "first": None,
                    "second": None
                }

            total_rows = self.wafer_map.total_rows
            total_cols = self.wafer_map.total_cols

            # Вычисляем размеры Canvas
            canvas_width = total_cols * (self._CELL_SIZE + self._SPACING)
            canvas_height = total_rows * (self._CELL_SIZE + self._SPACING)

            shapes = []  # Создаем фигуры для Canvas

            # Проходим по всей матрице Die и создаем визуальные элементы
            for row_idx in range(total_rows):
                for col_idx in range(total_cols):
                    # Координаты для отрисовки на Canvas
                    draw_x = col_idx * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2
                    draw_y = row_idx * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2

                    die = self.wafer_map.die_matrix[row_idx][col_idx]
                    die_visual = DieVisual(draw_x=draw_x, draw_y=draw_y)

                    die.die_visual = die_visual
                    die_visual.shape = "square"

                    # Определяем цвет на основе статуса
                    if die.status == DieStatus.SKIP:
                        die_visual.color = Colors.GREY
                    elif die.status == DieStatus.NEED_CHECK:
                        die_visual.color = Colors.YELLOW
                    elif die.status == DieStatus.GOOD:
                        die_visual.color = Colors.GREEN
                    elif die.status == DieStatus.BAD:
                        die_visual.color = Colors.RED
                    else:
                        die_visual.shape = "circle"
                        die_visual.color = self._application_colors["inactive"]

                    # Создаем фигуру для Canvas и сохраняем ссылку на Paint
                    shape, paint = self._create_shape(
                        draw_x=draw_x,
                        draw_y=draw_y,
                        shape=die_visual.shape,
                        color=die_visual.color
                    )
                    # Сохраняем ссылку на Paint в объекте DieVisual
                    die_visual.paint_ref = paint
                    shapes.append(shape)

            grid_view = self._create_canvas_and_view(shapes, canvas_width, canvas_height)

            # Восстанавливаем референсные кристаллы если они были сохранены
            if scale_value is not None:
                if first_ref_die:
                    # Напрямую устанавливаем референсный цвет, не сохраняя оригинальный
                    self._set_cell_as_reference(first_ref_die, "1")
                    self._reference_coords["first"] = (first_ref_die.row, first_ref_die.col)

                if second_ref_die:
                    self._set_cell_as_reference(second_ref_die, "2")
                    self._reference_coords["second"] = (second_ref_die.row, second_ref_die.col)

                logger.info(f"Масштаб изменен на {scale_value}x, визуальная модель перегенерирована")
            else:
                logger.info("Визуальная модель пластины с кристаллами сгенерировалась")

            return grid_view

        except Exception as e:
            error_message = "Ошибка при создании визуальной модели пластины с кристаллами"
            logger.error(f"{error_message}: {e}")
            raise KnownSystemException(message=error_message)

    def update_symbols_need_check(self, new_symbols_need_check: Set[str]) -> bool:
        """
        Сравнивает config.symbols_need_check с symbols_need_check пластины
        и обновляет статусы и цвета для кристаллов при необходимости.

        Args:
            new_symbols_need_check: Множество символов, которые нужно проверить

        Returns:
            bool: True если были изменения, False если списки идентичны
        """
        if not self.wafer_map:
            logger.warning("Пластина не загружена, обновление статусов невозможно")
            return False
        old_symbols_need_check = set(self.wafer_map.symbols_need_check) if self.wafer_map.symbols_need_check else set()

        if old_symbols_need_check == new_symbols_need_check:
            logger.debug("Список детектируемых объектов не изменился")
            return False

        self.wafer_map.symbols_need_check = list(new_symbols_need_check)

        changes_made = False
        for row in range(self.wafer_map.total_rows):
            for col in range(self.wafer_map.total_cols):
                die = self.wafer_map.die_matrix[row][col]
                if not die or not die.symbol:
                    continue

                first_char = die.symbol.translate(str.maketrans('', '', string.digits))

                if first_char in new_symbols_need_check and first_char not in old_symbols_need_check:
                    die.update_die_status(DieStatus.NEED_CHECK)
                    self.update_visual_die(die, False)
                    self._update_original_color_for_die(die)
                    changes_made = True

                elif first_char not in new_symbols_need_check and first_char in old_symbols_need_check:
                    die.update_die_status(DieStatus.SKIP)
                    self.update_visual_die(die, False)
                    changes_made = True

        if changes_made and self._canvas_ref:
            self._canvas_ref.update()
            self.wafer_map.update_stats()
            logger.info("Статусы кристаллов обновлены в соответствии с новыми символами для проверки")

        return changes_made

    def update_visual_die(self,
                          die: 'Die',
                          is_need_update_canvas: bool = True) -> bool:
        """
        Обновляет цвет кристалла только если он отличается от текущего.

        Args:
            die: Объект Die (модель кристалла)
            is_need_update_canvas: Метка на обновление canvas

        Returns:
            bool: True если цвет был изменен, иначе False
        """
        if not die or not die.die_visual:
            return False

        if die.status == DieStatus.BAD:
            target_color = Colors.RED
        elif die.status == DieStatus.GOOD:
            target_color = Colors.GREEN
        elif die.status == DieStatus.NEED_CHECK:
            target_color = Colors.YELLOW
        elif die.status == DieStatus.SKIP:
            target_color = Colors.GREY
        elif die.status == DieStatus.DUMMY:
            target_color = self._application_colors["inactive"]
            die.die_visual.shape = "circle"
        else:
            target_color = self._application_colors["inactive"]
            die.die_visual.shape = "circle"

        # Проверяем, нужно ли обновлять
        if die.die_visual.color != target_color:
            die.die_visual.color = target_color
            if die.die_visual.paint_ref:
                die.die_visual.paint_ref.color = target_color

            self._update_original_color_for_die(die)

            if is_need_update_canvas and self._canvas_ref:
                self._canvas_ref.update()

            return True

        return False

    def _update_original_color_for_die(self, die: 'Die') -> None:
        """Обновляет сохраненный оригинальный цвет кристалла."""
        if not die or not die.die_visual:
            return

        key = (die.row, die.col)
        if key in self._original_colors:
            self._original_colors[key] = die.die_visual.color

    def _create_shape(self,
                      draw_x: float,
                      draw_y: float,
                      shape: str,
                      color: str
                      ) -> Tuple[Union[cnv.Rect, cnv.Circle], Paint]:
        """
        Создает фигуру для Canvas и возвращает фигуру и ссылку на Paint.

        Args:
            draw_x: Координата x в canvas-полотне
            draw_y: Координата y в canvas-полотне
            shape: Форма графического элемента
            color: Цвет графического элемента

        Returns:
            Tuple[Union[cnv.Rect, cnv.Circle], Paint]: Фигура и объект Paint
        """
        paint = Paint(color=color, style=PaintingStyle.FILL)

        if shape == "square":
            rect_x = draw_x - self._SQUARE_SIZE / 2
            rect_y = draw_y - self._SQUARE_SIZE / 2

            shape_obj = cnv.Rect(
                x=rect_x,
                y=rect_y,
                width=self._SQUARE_SIZE,
                height=self._SQUARE_SIZE,
                paint=paint
            )
        else:  # circle
            shape_obj = cnv.Circle(
                x=draw_x,
                y=draw_y,
                radius=self._POINT_RADIUS,
                paint=paint
            )

        return shape_obj, paint

    def _create_canvas_and_view(self,
                                shapes: List[Any],
                                width: float,
                                height: float) -> Row:
        """
        Создает Canvas и связанные элементы, возвращает grid_view.

        Args:
            shapes: Массив созданных графических элементов
            width: Ширина Canvas
            height: Длина Canvas

        Returns:
            Row: Визуальное представление пластины с кристаллами
        """
        self._canvas_ref = cnv.Canvas(
            shapes=shapes,
            width=width,
            height=height,
        )

        gesture_detector = GestureDetector(
            content=self._canvas_ref,
            on_tap_down=lambda e: self._on_canvas_tap(e.local_x, e.local_y),
            mouse_cursor=MouseCursor.CLICK,
        )

        interactive_viewer = InteractiveViewer(
            content=gesture_detector,
            width=width,
            height=height,
            pan_enabled=True,
            scale_enabled=False,
            boundary_margin=Margin(1, 1,
                                   max(0, int(width - self._view_width)),
                                   max(0, int(height - self._view_height))),
            clip_behavior=ClipBehavior.HARD_EDGE,
        )

        grid_view = Row(
            controls=[
                Column(
                    controls=[interactive_viewer],
                )
            ],
        )

        return grid_view

    def _on_canvas_tap(self, x: float, y: float) -> None:
        """
        Обработчик кликов на Canvas.

        Args:
            x: Координата x нажатия на canvas
            y: Координата y нажатия на canvas
        """
        if self.inspection_active:
            logger.debug("Инспекция активна, открытие диалога кристалла заблокировано")
            return

        if self._dialog_is_open:
            logger.debug("Диалог уже открыт, игнорируем повторный клик")
            return

        if not self.wafer_map:
            return

        try:
            col_idx = int(x // (self._CELL_SIZE + self._SPACING))
            row_idx = int(y // (self._CELL_SIZE + self._SPACING))
        except ZeroDivisionError:
            return

        # Проверяем границы массива
        if not (0 <= row_idx < self.wafer_map.total_rows and
                0 <= col_idx < self.wafer_map.total_cols):
            return

        die = self.wafer_map.die_matrix[row_idx][col_idx]

        # Если ячейка пустая или нет визуального представления, игнорируем
        if not die or not die.die_visual:
            return

        # Проверяем попадание в квадрат
        center_x = col_idx * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2
        center_y = row_idx * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2

        square_left = center_x - self._SQUARE_SIZE / 2
        square_right = center_x + self._SQUARE_SIZE / 2
        square_top = center_y - self._SQUARE_SIZE / 2
        square_bottom = center_y + self._SQUARE_SIZE / 2

        if not (square_left <= x <= square_right and square_top <= y <= square_bottom):
            return

        # Обновляем выбранный кристалл
        self._selected_die = die
        self.highlight_die(die)  # Подсвечиваем выбранный кристалл
        self._open_die_dialog(die)  # Открываем диалог кристалла

    def highlight_die(self, die: 'Die'):
        """ Подсвечивает кристалл белым цветом. """
        if not die or not die.die_visual:
            return

        die_visual = die.die_visual

        key = (die.row, die.col)
        if key not in self._original_colors:
            self._original_colors[key] = die.die_visual.color

        if die_visual.color == self._REFERENCE_COLOR:
            highlight_color = self._REFERENCE_COLOR_SELECTED
        else:
            highlight_color = self._HIGHLIGHT_COLOR

        die_visual.color = highlight_color
        die_visual.paint_ref.color = highlight_color

        if self._canvas_ref:
            self._canvas_ref.update()

    def _restore_die_color(self, die: 'Die', is_need_update_canvas: bool = True) -> None:
        """ Восстанавливает оригинальный цвет кристалла. """
        if not die or not die.die_visual:
            return

        die_visual = die.die_visual

        if die_visual.color == self._REFERENCE_COLOR_SELECTED:
            die_visual.color = self._REFERENCE_COLOR
            die_visual.paint_ref.color = self._REFERENCE_COLOR
        else:
            # Восстанавливаем оригинальный цвет из словаря по координатам
            key = (die.row, die.col)
            if key in self._original_colors:
                original_color = self._original_colors[key]
                die_visual.color = original_color
                die_visual.paint_ref.color = original_color

            # Удаляем запись из словаря
            if key in self._original_colors:
                del self._original_colors[key]

        if is_need_update_canvas and self._canvas_ref:
            self._canvas_ref.update()

    def _update_reference_visualization(self, die: 'Die') -> None:
        """ Обновляет визуализацию референсных кристаллов после их изменения. """
        if not die or not die.die_visual or not self._canvas_ref:
            return

        is_first_ref = die == self.wafer_map.orientation.first_reference_die
        is_second_ref = die == self.wafer_map.orientation.second_reference_die

        ref_type = None
        text_number = None
        if is_first_ref:
            ref_type = "first"
            text_number = "1"
        elif is_second_ref:
            ref_type = "second"
            text_number = "2"

        if ref_type:  # Если уже есть референсный кристалл с такой цифрой, сбрасываем его
            old_coords = self._reference_coords[ref_type]
            if old_coords and old_coords != (die.row, die.col):
                self._reset_reference_cell(old_coords[0], old_coords[1])

            self._make_cell_reference(die, text_number)  # Обновляем текущий кристалл как референсный
            self._reference_coords[ref_type] = (die.row, die.col)  # Сохраняем новые координаты
        else:  # Кристалл не референсный - сбрасываем его вид, если он был референсным
            was_first_ref = self._reference_coords["first"] == (die.row, die.col)
            was_second_ref = self._reference_coords["second"] == (die.row, die.col)

            if was_first_ref or was_second_ref:
                self._reset_reference_cell(die.row, die.col)
                # Сбрасываем координаты
                if was_first_ref:
                    self._reference_coords["first"] = None
                else:
                    self._reference_coords["second"] = None

        if self._canvas_ref:
            self._canvas_ref.update()

    def _make_cell_reference(self, die: 'Die', text_number: str) -> None:
        """
        Преобразует кристалл в референсный вид.

        Args:
            die: Объект Die (модель кристалла)
            text_number: Номер референсного кристалла
        """
        if not die or not die.die_visual:
            return

        key = (die.row, die.col)
        die_visual = die.die_visual

        # Сохраняем оригинальный цвет перед изменением на референсный
        if key not in self._original_colors:
            self._original_colors[key] = die_visual.color

        die_visual.color = self._REFERENCE_COLOR_SELECTED
        die_visual.paint_ref.color = self._REFERENCE_COLOR_SELECTED

        # Создаем или обновляем текстовый элемент
        draw_x = die.col * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2
        draw_y = die.row * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2

        if key in self._reference_text_shapes:
            # Обновляем существующий текст
            text_shape = self._reference_text_shapes[key]
            text_shape.text = text_number
            text_shape.x = draw_x - 4  # Центрирование по горизонтали
            text_shape.y = draw_y - 8  # Центрирование по вертикали
            text_shape.style = TextStyle(
                size=12,
                weight=FontWeight.BOLD,
                color=Colors.BLACK
            )
        else:
            text_shape = cnv.Text(
                x=draw_x - 4,  # Центрирование по горизонтали
                y=draw_y - 8,  # Центрирование по вертикали
                text=text_number,
                style=TextStyle(
                    size=12,
                    weight=FontWeight.BOLD,
                    color=Colors.BLACK
                )
            )
            self._canvas_ref.shapes.append(text_shape)
            self._reference_text_shapes[key] = text_shape

    def _set_cell_as_reference(self, die: 'Die', text_number: str) -> None:
        """
        Устанавливает кристалл как референсный без сохранения оригинального цвета.
        Используется при восстановлении референсных кристаллов после перегенерации.

        Args:
            die: Объект Die (модель кристалла)
            text_number: Номер референсного кристалла
        """
        if not die or not die.die_visual:
            return

        key = (die.row, die.col)
        die_visual = die.die_visual

        # Устанавливаем референсный цвет
        die_visual.color = self._REFERENCE_COLOR
        die_visual.paint_ref.color = self._REFERENCE_COLOR

        # Создаем или обновляем текстовый элемент
        draw_x = die.col * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2
        draw_y = die.row * (self._CELL_SIZE + self._SPACING) + self._CELL_SIZE / 2

        if key in self._reference_text_shapes:
            # Обновляем существующий текст
            text_shape = self._reference_text_shapes[key]
            text_shape.text = text_number
            text_shape.x = draw_x - 4
            text_shape.y = draw_y - 8
            text_shape.style = TextStyle(
                size=12,
                weight=FontWeight.BOLD,
                color=Colors.BLACK
            )
        else:
            text_shape = cnv.Text(
                x=draw_x - 4,
                y=draw_y - 8,
                text=text_number,
                style=TextStyle(
                    size=12,
                    weight=FontWeight.BOLD,
                    color=Colors.BLACK
                )
            )
            self._canvas_ref.shapes.append(text_shape)
            self._reference_text_shapes[key] = text_shape

    def _reset_reference_cell(self, row: int, col: int) -> None:
        """
        Сбрасывает референсный кристалл в оригинальный вид.

        Args:
            row: Строка искомого кристалла
            col: Столбец искомого кристалла
        """
        key = (row, col)
        die = self.wafer_map.die_matrix[row][col]

        if die and die.die_visual:
            die_visual = die.die_visual

            # Восстанавливаем цвет из original_colors
            if key in self._original_colors:
                original_color = self._original_colors[key]
                die_visual.color = original_color
                if die_visual.paint_ref:
                    die_visual.paint_ref.color = original_color
            else:
                # Если нет сохраненного цвета, определяем на основе статуса
                if die.status == DieStatus.SKIP:
                    default_color = Colors.GREY
                elif die.status == DieStatus.NEED_CHECK:
                    default_color = Colors.YELLOW
                elif die.status == DieStatus.GOOD:
                    default_color = Colors.GREEN
                elif die.status == DieStatus.BAD:
                    default_color = Colors.RED
                else:
                    default_color = self._application_colors["inactive"]

                die_visual.color = default_color
                if die_visual.paint_ref:
                    die_visual.paint_ref.color = default_color

        # Удаляем текстовый элемент
        if key in self._reference_text_shapes:
            text_shape = self._reference_text_shapes[key]
            if self._canvas_ref and text_shape in self._canvas_ref.shapes:
                self._canvas_ref.shapes.remove(text_shape)
            del self._reference_text_shapes[key]

        # Удаляем из original_colors если есть
        if key in self._original_colors:
            del self._original_colors[key]

        if self._canvas_ref:
            self._canvas_ref.update()

    def reset_all_reference_visualization(self) -> None:
        """ Сбрасывает визуализацию всех референсных кристаллов. """
        if not self.wafer_map or not self._canvas_ref:
            logger.warning("Невозможно сбросить визуализацию: wafer_map или canvas_ref не инициализированы")
            return

        reset_count = 0
        for key in list(self._reference_text_shapes.keys()):
            row, col = key
            self._reset_reference_cell(row, col)
            reset_count += 1

        # Очищаем словари
        self._reference_coords = {
            "first": None,
            "second": None
        }
        self._original_colors.clear()
        self._reference_text_shapes.clear()

        if self._canvas_ref:
            self._canvas_ref.update()

        logger.debug(f"Визуализация {reset_count} референсных кристаллов сброшена")

    def _open_die_dialog(self, die: 'Die') -> None:
        """ Метод открытия диалогового окна с детальной информацией о кристалле. """
        if self._dialog_is_open:
            logger.debug("Попытка открыть диалог, когда он уже открыт")
            return

        self._dialog_is_open = True
        self._create_dialog(die)

        # Всегда скрываем кнопки сохранения при открытии диалога
        self.save_buttons_container.visible = False
        self._pending_reference_selection = None

        self._page.update()

    def _create_dialog(self, die: 'Die') -> None:
        """ Создает диалоговое окно для отображения информации кристалла. """

        dialog_width = 560
        base_height = 420  # Базовая высота для стандартного набора полей
        defect_row_height = 28  # Высота одной строки дефекта

        color_text = self._application_colors["text"]

        # Заголовок
        header = Row(
            controls=[
                Text(f"Информация кристалла №{die.id}",
                     size=24,
                     weight=FontWeight.BOLD,
                     color=color_text,
                     text_align=TextAlign.LEFT
                     ),
                IconButton(
                    icon=Icons.PHOTO_FILTER,
                    icon_color=color_text,
                    icon_size=30,
                    tooltip="Открыть изображение кристалла с фильтрами",
                    on_click=lambda e: open_file_in_viewer(
                        die.file_frame_filtered_path,
                        page=self._page,
                        config=self._config
                    ),
                    padding=padding.all(0),
                    visible=(die.file_frame_original_path != ""),
                ),
                IconButton(
                    icon=Icons.IMAGE,
                    icon_color=color_text,
                    icon_size=30,
                    tooltip="Открыть оригинальное изображение кристалла",
                    on_click=lambda e: open_file_in_viewer(
                        die.file_frame_original_path,
                        page=self._page,
                        config=self._config
                    ),
                    padding=padding.all(0),
                    visible=(die.file_frame_original_path != ""),
                ),
                IconButton(
                    icon=Icons.MY_LOCATION,
                    icon_color=color_text,
                    icon_size=30,
                    tooltip="Переместиться на кристалл",
                    on_click=lambda e: self._move_to_die(die),
                    padding=padding.all(0),
                    visible=die.has_physical_coords(),
                ),
            ],
            alignment=MainAxisAlignment.CENTER,
            vertical_alignment=CrossAxisAlignment.CENTER,
            spacing=5,
        )

        # Строки с информацией
        label_width = 320
        die_info = [
            Row([
                Container(
                    content=Text("Кристалл №:", color=color_text, size=22),
                    width=label_width,
                    padding=padding.only(right=2),
                ),
                Text(f"{die.id}", color=color_text, size=22),
            ]),
            Row([
                Container(
                    content=Text("Статус:", color=color_text, size=22),
                    width=label_width,
                    padding=padding.only(right=2),
                ),
                Text(f"{die.status.value}", color=color_text, size=22),
            ]),
            Row([
                Container(
                    content=Text("Символ на карте годности:", color=color_text, size=22),
                    width=label_width,
                    padding=padding.only(right=2),
                ),
                Text(f"{die.symbol}", color=color_text, size=22),
            ]),
            Row([
                Container(
                    content=Text("Позиция на карте годности:", color=color_text, size=22),
                    width=label_width,
                    padding=padding.only(right=2),
                ),
                Text(f"[{die.col + 1}, {die.row + 1}]", color=color_text, size=22),
            ]),
            Row([
                Container(
                    content=Text("Физические координаты в мм:", color=color_text, size=22),
                    width=label_width,
                    padding=padding.only(right=2),
                ),
                Text(
                    value=(
                        f"({die.physical_x:.2f}; {die.physical_y:.2f})"
                        if die.physical_x is not None and die.physical_y is not None
                        else "не определены"
                    ),
                    color=color_text,
                    size=22
                ),
            ]),
        ]

        # Секция с информацией о дефектах
        if die.defects_info and len(die.defects_info) > 0:
            # Заголовок секции дефектов
            defects_header = Container(
                content=Text("Обнаруженные дефекты:",
                             size=22,
                             weight=FontWeight.BOLD,
                             color=color_text),
                padding=padding.only(top=10, bottom=5),
            )

            # Список дефектов
            defects_list = []
            for defect in die.defects_info:
                defect_name = defect.get('name', 'Неизвестный дефект')
                defect_count = defect.get('count', 0)
                defect_color = defect.get('color', [255, 0, 0])

                # Проверяем, есть ли отрицательные значения в цвете
                has_negative = any(c < 0 for c in defect_color)

                if has_negative:
                    # Если есть отрицательные значения — только текст без цветного квадратика
                    defect_row = Row(
                        controls=[
                            Text(f"• {defect_name}:",
                                 size=22,
                                 color=color_text,
                                 weight=FontWeight.W_500),
                            Text(f"{defect_count} шт.",
                                 size=22,
                                 color=color_text),
                        ],
                        spacing=10,
                        vertical_alignment=CrossAxisAlignment.CENTER,
                    )
                else:
                    # Если все значения неотрицательные — показываем цветной квадратик
                    color_hex = f"#{defect_color[0]:02x}{defect_color[1]:02x}{defect_color[2]:02x}"

                    defect_row = Row(
                        controls=[
                            Container(
                                width=16,
                                height=16,
                                bgcolor=color_hex,
                                border=border.all(1, Colors.BLACK),
                                border_radius=2,
                            ),
                            Text(f"{defect_name}:",
                                 size=22,
                                 color=color_text,
                                 weight=FontWeight.W_500),
                            Text(f"{defect_count} шт.",
                                 size=22,
                                 color=color_text),
                        ],
                        spacing=10,
                        vertical_alignment=CrossAxisAlignment.CENTER,
                    )

                defects_list.append(defect_row)

            # Добавляем секцию дефектов в die_info
            die_info.append(defects_header)
            die_info.extend(defects_list)

            # Вычисляем высоту диалога с учётом количества дефектов
            defects_count = len(die.defects_info)
            dialog_height = base_height + defects_count * defect_row_height
        else:
            dialog_height = base_height

        # Текущий статус референсного кристалла
        current_reference_status = "Нет"
        if die == self.wafer_map.orientation.first_reference_die:
            current_reference_status = "Первый"
        elif die == self.wafer_map.orientation.second_reference_die:
            current_reference_status = "Второй"

        # Выпадающий список
        self.reference_dropdown = Dropdown(
            label="Референсный кристалл",
            hint_text="Выберите статус",
            width=220,
            text_size=18,
            options=[
                dropdown.Option("Нет"),
                dropdown.Option("Первый"),
                dropdown.Option("Второй"),
            ],
            value=current_reference_status,
            color=self._application_colors["text"],
            bgcolor=self._application_colors["top_bar"],
            border_color=self._application_colors["text"],
            focused_border_color=self._application_colors["active"],
            label_style=TextStyle(color=self._application_colors["text"], size=22),
            on_change=lambda e: self._on_dropdown_change(e.control.value),
        )

        # Кнопки сохранения/отмены
        save_btn = ElevatedButton(
            text="Сохранить",
            on_click=lambda e: self._save_reference_selection(die),
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=20),
                overlay_color=self._application_colors["hover"],
                bgcolor=Colors.GREEN,
                color=self._application_colors["text"],
                text_style=TextStyle(size=22, weight=FontWeight.BOLD),
                animation_duration=300,
            ),
            width=140,
            height=48,
        )

        cancel_btn = ElevatedButton(
            text="Отмена",
            on_click=lambda e: self._cancel_reference_selection(),
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=20),
                overlay_color=self._application_colors["hover"],
                bgcolor=self._application_colors["inactive"],
                color=self._application_colors["text"],
                text_style=TextStyle(size=22, weight=FontWeight.BOLD),
                animation_duration=300,
            ),
            width=140,
            height=48,
        )

        # Контейнер для кнопок сохранения
        self.save_buttons_container = Container(
            content=Row(
                controls=[save_btn, cancel_btn],
                alignment=MainAxisAlignment.CENTER,
                spacing=60,
            ),
            visible=False,  # Скрыт по умолчанию
            alignment=alignment.center,  # Центрирование содержимого
        )

        # Кнопка закрытия
        close_btn = ElevatedButton(
            text="Закрыть",
            on_click=lambda e: self._close_dialog_and_reset(die),
            style=ButtonStyle(
                shape=RoundedRectangleBorder(radius=20),
                overlay_color=self._application_colors["hover"],
                bgcolor=self._application_colors["inactive"],
                color=color_text,
                text_style=TextStyle(size=22, weight=FontWeight.BOLD),
                animation_duration=300,
            ),
            width=140,
            height=48,
        )

        # Контейнер управления (выпадающий список + кнопка закрытия)
        die_selection = Container(
            content=Row(
                controls=[
                    Container(
                        content=self.reference_dropdown,
                        padding=padding.only(right=20),
                    ),
                    close_btn,
                ],
                alignment=MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=CrossAxisAlignment.CENTER,
            ),
            width=dialog_width - 40,
        )

        # Основная структура диалога
        dialog = Column(
            controls=[
                # Заголовок
                Container(
                    content=header,
                    alignment=alignment.center,
                    padding=padding.only(bottom=16),
                ),
                # Информация о кристалле (включая дефекты)
                Column(
                    controls=die_info,
                    spacing=2,
                    tight=True,
                    scroll=ScrollMode.AUTO,
                ),
                Container(
                    content=self.save_buttons_container,
                    expand=True,
                    alignment=alignment.center,
                    padding=padding.symmetric(vertical=8),
                ),
                die_selection,
            ],
            expand=True,
            spacing=0,
        )

        # Stack с диалогом
        self.dialog_stack = Stack(
            controls=[
                # Затемняющий фон
                Container(
                    width=self._page.width,
                    height=self._page.height,
                    bgcolor=Colors.with_opacity(0.3, Colors.BLACK),
                    on_click=lambda e: self._close_dialog_and_reset(die),
                ),
                # Диалоговое окно
                Container(
                    width=dialog_width,
                    height=dialog_height,
                    bgcolor=self._application_colors["background"],
                    border_radius=10,
                    border=border.all(2, color_text),
                    padding=20,
                    left=self._page.width / 2 + 330,
                    top=self._page.height / 2 - dialog_height / 2,
                    content=dialog,
                )
            ]
        )

        self.dialog_container = self.dialog_stack.controls[1]
        self._page.overlay.append(self.dialog_stack)

        logger.debug(f"Было открыто окно с информации кристалла: {die.id}")

    def _on_dropdown_change(self, selection: str) -> None:
        """
        Обработчик изменения выпадающего списка.

        Args:
            selection: Выбранный статус текущего кристалла
        """
        current_status = "Нет"
        if self._selected_die == self.wafer_map.orientation.first_reference_die:
            current_status = "Первый"
        elif self._selected_die == self.wafer_map.orientation.second_reference_die:
            current_status = "Второй"

        if selection == current_status:
            self.save_buttons_container.visible = False
            self._pending_reference_selection = None
        else:
            self._pending_reference_selection = selection
            self.save_buttons_container.visible = True

        self._page.update()

    def _save_reference_selection(self, die: 'Die') -> None:
        """
        Сохраняет выбранный статус референсного кристалла.

        Args:
            die: Объект Die (модель кристалла)
        """
        try:
            ret, error_message = False, None
            if self._pending_reference_selection == "Первый":
                ret, error_message = self.wafer_map.orientation.update_first_reference_die(die)
                logger.debug(f"Кристалл {self._selected_die.id} установлен как Первый референсный")

            elif self._pending_reference_selection == "Второй":
                ret, error_message = self.wafer_map.orientation.update_second_reference_die(die)
                logger.debug(f"Кристалл {self._selected_die.id} установлен как Второй референсный")

            else:
                if die == self.wafer_map.orientation.first_reference_die:
                    self.wafer_map.orientation.reset_first_reference_die()
                elif die == self.wafer_map.orientation.second_reference_die:
                    self.wafer_map.orientation.reset_second_reference_die()

            self._pending_reference_selection = None
            self.save_buttons_container.visible = False
            self._update_reference_visualization(die)  # Обновляем визуализацию референсных кристаллов

            self._close_dialog_and_reset(self._selected_die)

            if not ret and error_message is not None:
                show_warning("Предупреждение", error_message, self._page, self._config)

        except Exception as e:
            logger.error(f"Ошибка при сохранении референсного кристалла: {e}")
            show_error(title="Ошибка сохранения референсного кристалла",
                       message="Точная ошибка не известна",
                       page=self._page,
                       config=self._config)

    def _cancel_reference_selection(self) -> None:
        """ Отменяет выбор референсного кристалла. """
        current_reference_status = "Нет"
        if self._selected_die == self.wafer_map.orientation.first_reference_die:
            current_reference_status = "Первый"
        elif self._selected_die == self.wafer_map.orientation.second_reference_die:
            current_reference_status = "Второй"

        self.reference_dropdown.value = current_reference_status
        self._pending_reference_selection = None
        self.save_buttons_container.visible = False
        self._page.update()

    def _move_to_die(self, die: 'Die') -> None:
        """ Метод для перемещения робота на кристалл. """
        logger.info(f"Кнопка 'Переместиться на кристалл' нажата для кристалла {die.id}")
        self._close_dialog_and_reset(die)
        self.wafer_map.move_to_die(die=die)

    def _close_dialog_and_reset(self, die: 'Die') -> None:
        """Закрывает диалог и восстанавливает цвет кристалла."""
        if self._selected_die:
            self._restore_die_color(die)

        self._pending_reference_selection = None
        self._dialog_is_open = False
        self._close_dialog()

    def _close_dialog(self) -> None:
        """ Закрывает кастомный диалог. """
        page = self._page
        if page and page.overlay and hasattr(self, 'dialog_stack'):
            # Удаляем диалог из overlay
            if self.dialog_stack in page.overlay:
                page.overlay.remove(self.dialog_stack)
            page.update()
