import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from project.configuration.config_manager import ConfigManager
from project.application.data_work.wafer_map_bin_parser import WaferMapBinParser
from project.application.data_work.wafer_data import WaferMap, Die, DieStatus
from project.application.addition.logger import logger
from project.application.addition.exceptions import ProtocolException


class WaferMapFactory:
    """ Фабрика для создания экземпляров WaferMap из различных источников. """

    @staticmethod
    def from_bin_parser(parser: 'WaferMapBinParser',
                        config: Optional[ConfigManager] = None) -> 'WaferMap':
        """
        Создает WaferMap из бинарного парсера.

        Args:
            parser: Экземпляр парсера бинарных данных
            config: Экземпляр класса конфигураций

        Returns:
            WaferMap: Созданный экземпляр модели данных пластины
        """
        header_info: Dict[str, Any] = parser.header_info
        die_data: List[Dict[str, Any]] = parser.die_data

        # Получаем базовые параметры
        wafer_id = header_info.get('wafer_ID', 'Не задано')
        orig_cols = header_info.get('map_area_col_size', 0)
        orig_rows = header_info.get('map_area_row_size', 0)
        first_die_X = header_info.get('first_die_X', 0)
        first_die_Y = header_info.get('first_die_Y', 0)
        rotation_angle = header_info.get('standard_orientation', 0)

        # Создаем временную матрицу
        temp_matrix = WaferMapFactory._create_temp_matrix(orig_rows, orig_cols, die_data)

        # Применяем поворот
        rotated_matrix, new_rows, new_cols = WaferMapFactory._apply_rotation(
            temp_matrix, orig_rows, orig_cols, rotation_angle
        )

        # Создаем или получаем экземпляр WaferMap
        wafer_map = WaferMapFactory._get_or_create_wafer_map(
            wafer_id, new_rows, new_cols, first_die_X, first_die_Y
        )
        wafer_map.orientation.check_die_prev_ref()

        # Настраиваем конфигурацию
        if config is not None:
            wafer_map.symbols_need_check = config.symbols_need_check.copy() if config.symbols_need_check else []
            wafer_map.cell_size_x_mm = config.wafer_params.get("x_distance", 0)
            wafer_map.cell_size_y_mm = config.wafer_params.get("y_distance", 0)

        # Заполняем матрицу
        WaferMapFactory._fill_matrix(wafer_map, rotated_matrix, new_rows, new_cols)

        wafer_map.update_stats()

        logger.debug(f"Преобразование данных от парсера в модель прошло успешно")
        return wafer_map

    @staticmethod
    def from_json_protocol(json_file_path: str) -> WaferMap:
        """
        Создает WaferMap из json-файла протокола.

        Args:
            json_file_path: Путь к JSON файлу протокола

        Returns:
            WaferMap: Созданный экземпляр модели данных пластины

        Raises:
            ProtocolException: При ошибках чтения или парсинга JSON файла
        """
        try:
            json_path = Path(json_file_path)
            if not json_path.exists():
                error_message = f"JSON файл не найден: {json_file_path}"
                logger.error(error_message)
                raise ProtocolException(message=error_message)

            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            # Извлекаем основные параметры пластины
            wafer_id = json_data.get("wafer_id", "")
            total_rows = json_data.get("total_rows", 0)
            total_cols = json_data.get("total_cols", 0)
            first_die_X = json_data.get("first_die_X", 0)
            first_die_Y = json_data.get("first_die_y", 0)

            # Создаем или получаем экземпляр WaferMap
            wafer_map = WaferMapFactory._get_or_create_wafer_map(
                wafer_id, total_rows, total_cols, first_die_X, first_die_Y
            )
            wafer_map.orientation.check_die_prev_ref()

            wafer_map.symbols_need_check = json_data.get("symbols_need_check", [])
            wafer_map.cell_size_x_mm = json_data.get("cell_size_x_mm", 0)
            wafer_map.cell_size_y_mm = json_data.get("cell_size_y_mm", 0)

            # Получаем список кристаллов из JSON
            dice_data = json_data.get("dices_info", [])
            if not dice_data:
                logger.warning(f"В JSON файле отсутствуют данные о кристаллах: {json_file_path}")
                return wafer_map

            # Создаем матрицу кристаллов
            wafer_map.die_matrix = [[None for _ in range(total_cols)] for _ in range(total_rows)]

            die_prev_ref_id = json_data.get("die_prev_ref_id", None)

            # Заполняем матрицу кристаллами
            for die_info in dice_data:
                try:
                    die_id = die_info.get("id", 0)
                    map_x = die_info.get("map_x", 0)
                    map_y = die_info.get("map_y", 0)
                    die_coord_x = die_info.get("die_coordinator_values_x", 0)
                    die_coord_y = die_info.get("die_coordinator_values_y", 0)
                    physical_x = die_info.get("physical_x")
                    physical_y = die_info.get("physical_y")
                    symbol = die_info.get("symbol", "D")
                    symbol_old = die_info.get("symbol_old", "D")
                    status_str = die_info.get("status")

                    # Восстанавливаем статус кристалла из строки
                    status = None
                    if status_str:
                        try:
                            status = DieStatus(status_str)
                        except ValueError:
                            logger.warning(f"Неизвестный статус кристалла '{status_str}' для die_id={die_id}")

                    # Восстанавливаем информацию о дефектах
                    defects_info = die_info.get("defects_info", [])
                    if not isinstance(defects_info, list):
                        logger.warning(
                            f"Неверный формат defects_info для die_id={die_id},"
                            f"ожидался список, получен {type(defects_info)}")
                        defects_info = []

                    # Индексы строки и столбца (0-based)
                    row = map_y - 1 if map_y > 0 else 0
                    col = map_x - 1 if map_x > 0 else 0

                    # Корректировка, если индексы выходят за пределы
                    if row >= total_rows:
                        row = total_rows - 1
                    if col >= total_cols:
                        col = total_cols - 1

                    die = Die(
                        id=die_id,
                        row=row,
                        col=col,
                        map_x=die_coord_x,
                        map_y=die_coord_y,
                        physical_x=physical_x,
                        physical_y=physical_y,
                        symbol=symbol,
                        symbol_old=symbol_old,
                        status=status,
                        defects_info=defects_info
                    )

                    # Устанавливаем пути к изображениям, если они есть
                    file_frame_original = die_info.get("file_frame_original_path", "")
                    file_frame_filtered = die_info.get("file_frame_filtered_path", "")

                    if file_frame_original:
                        die.file_frame_original_path = file_frame_original
                    if file_frame_filtered:
                        die.file_frame_filtered_path = file_frame_filtered

                    if die_prev_ref_id == die_id:
                        wafer_map.set_die_prev_ref(die)

                    wafer_map.add_die(die)

                except Exception as e:
                    logger.error(f"Ошибка при загрузке кристалла из JSON: {e}, данные: {die_info}")
                    continue

            # Обновляем статистику
            wafer_map.update_stats()

            logger.info(f"WaferMap успешно создан из JSON: {json_file_path}")
            return wafer_map

        except json.JSONDecodeError as e:
            error_message = f"Ошибка парсинга JSON файла {json_file_path}: {e}"
            logger.error(error_message)
            raise ProtocolException(message=error_message)
        except Exception as e:
            error_message = f"Неизвестная ошибка при создании WaferMap из JSON {json_file_path}: {e}"
            logger.error(error_message)
            raise ProtocolException(message=error_message)

    @staticmethod
    def _create_temp_matrix(rows: int, cols: int,
                            die_data: List[Dict[str, Any]]) -> List[List[Optional[Die]]]:
        """ Создает временную матрицу из данных парсера. """
        temp_matrix = [[None for _ in range(cols)] for _ in range(rows)]

        for die_index, die_info in enumerate(die_data):
            orig_row = die_index // cols
            orig_col = die_index % cols

            die = Die(
                id=die_index + 1,
                row=orig_row,
                col=orig_col,
                map_x=die_info.get('die_coordinator_values_x', 0),
                map_y=die_info.get('die_coordinator_values_y', 0),
                physical_x=die_info.get('physical_x', None),
                physical_y=die_info.get('physical_y', None),
                symbol=die_info.get('symbol', 'D'),
                symbol_old=die_info.get('symbol', 'D'),
            )
            temp_matrix[orig_row][orig_col] = die

        return temp_matrix

    @staticmethod
    def _apply_rotation(matrix: List[List[Optional[Die]]],
                        rows: int, cols: int,
                        rotation_angle: int) -> tuple:
        """ Применяет поворот к матрице. """
        if rotation_angle == 90:
            rotated = [[None for _ in range(rows)] for _ in range(cols)]
            for i in range(rows):
                for j in range(cols):
                    rotated[j][rows - 1 - i] = matrix[i][j]
            return rotated, cols, rows

        elif rotation_angle == 180:
            rotated = [[None for _ in range(cols)] for _ in range(rows)]
            for i in range(rows):
                for j in range(cols):
                    rotated[rows - 1 - i][cols - 1 - j] = matrix[i][j]
            return rotated, rows, cols

        elif rotation_angle == 270:
            rotated = [[None for _ in range(rows)] for _ in range(cols)]
            for i in range(rows):
                for j in range(cols):
                    rotated[cols - 1 - j][i] = matrix[i][j]
            return rotated, cols, rows

        else:
            return matrix, rows, cols

    @staticmethod
    def _get_or_create_wafer_map(wafer_id: str, rows: int, cols: int,
                                 first_die_X: int, first_die_Y: int) -> 'WaferMap':
        """ Получает существующий или создает новый экземпляр WaferMap. """
        if WaferMap.has_instance():
            wafer_map = WaferMap.get_instance()
            wafer_map.reset_data()
            wafer_map.wafer_id = wafer_id
            wafer_map.total_rows = rows
            wafer_map.total_cols = cols
            wafer_map.first_die_X = first_die_X
            wafer_map.first_die_Y = first_die_Y
            return wafer_map
        else:
            return WaferMap.get_instance(
                wafer_id=wafer_id,
                total_rows=rows,
                total_cols=cols,
                first_die_X=first_die_X,
                first_die_Y=first_die_Y
            )

    @staticmethod
    def _fill_matrix(wafer_map: 'WaferMap', matrix: List[List[Optional[Die]]], rows: int, cols: int) -> None:
        """ Заполняет матрицу WaferMap данными. """
        wafer_map.die_matrix = [[None for _ in range(cols)] for _ in range(rows)]
        die_counter = 1

        for row in range(rows):
            for col in range(cols):
                die = matrix[row][col]
                if die is not None:
                    defects_info = die.defects_info if (hasattr(die, 'defects_info')
                                                        and isinstance(die.defects_info, list)) else []

                    new_die = Die(
                        id=die_counter,
                        row=row,
                        col=col,
                        map_x=die.map_x,
                        map_y=die.map_y,
                        physical_x=die.physical_x,
                        physical_y=die.physical_y,
                        symbol=die.symbol,
                        symbol_old=die.symbol,
                        defects_info=defects_info
                    )
                    wafer_map.add_die(new_die)
                    die_counter += 1
