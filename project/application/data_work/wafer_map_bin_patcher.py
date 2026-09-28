import struct
from typing import Dict, Any, List, Optional
from project.application.addition.exceptions import KnownSystemException, ValidationException
from project.application.data_work.wafer_data import WaferMap, Die
from project.application.addition.logger import logger


class WaferMapBinPatcher:
    """
    Класс для патчинга бинарного файла карты годности.
    Читает существующий файл и модифицирует данные кристаллов на основе WaferMap.

    Attributes:
        new_data (Optional[bytes]): Содержимое файла в виде байтов
        _file_path (str): Путь к исходному бинарному файлу
        _header_info (Dict[str, Any]): Информация из заголовка файла
        _die_data (List[Dict[str, Any]]): Список данных по каждому кристаллу
        _offset (int): Текущая позиция при чтении файла
        _die_offsets (List[int]): Смещения каждого кристалла в файле
        _pass_dice_offset (int): Смещение поля Total pass dice в файле
        _fail_dice_offset (int): Смещение поля Total fail dice в файле 
    """
    # Константы для модификации
    MOD_DATA = {
        'dummy_data': 0,  # Dummy Data = 0 (2 word, бит 9)
        'die_property': 1,  # Die Property = 1 (2 word, биты 15-14)
        'die_test_result': 2,  # Die Test Result = 2 (1 word, биты 15-14)
        'reprobing_result': 0,  # Re-Probing Result = 0 (1 word, биты 11-10)
        'category': 62  # Category Data = 62 (3 word, биты 5-0)
    }

    def __init__(self, file_path: Optional[str]) -> None:
        """
        Инициализация патчера бинарного файла.

        Args:
            file_path: Путь к исходному бинарному файлу
        """
        self.new_data = None
        self._file_path = file_path
        self._header_info: Dict[str, Any] = {}
        self._die_data: List[Dict[str, Any]] = []
        self._offset = 0
        self._die_offsets: List[int] = []
        self._pass_dice_offset = 0
        self._fail_dice_offset = 0

    def patch(self, wafer_map: 'WaferMap', target_symbol: str = "FV") -> int:
        """
        Модифицирует бинарный файл на основе WaferMap.
        """
        self._read_binary()
        self._parse_header()
        self._parse_die_offsets()

        data = bytearray(self.new_data)

        col_size = self._header_info.get('map_area_col_size', 0)
        rotation_angle = self._header_info.get('standard_orientation', 0)

        # Создаем повернутую копию ТОЛЬКО матрицы кристаллов
        if rotation_angle in [90, 180, 270]:
            rotated_matrix = self._rotate_matrix(wafer_map.die_matrix,
                                                 wafer_map.total_rows,
                                                 wafer_map.total_cols,
                                                 rotation_angle)
            temp_rows = len(rotated_matrix)
            temp_cols = len(rotated_matrix[0]) if temp_rows > 0 else 0
        else:
            rotated_matrix = wafer_map.die_matrix
            temp_rows = wafer_map.total_rows
            temp_cols = wafer_map.total_cols

        modified_count = 0
        for row_idx in range(temp_rows):
            for col_idx in range(temp_cols):
                die = rotated_matrix[row_idx][col_idx]
                if die and die.symbol == target_symbol:
                    if "f" in die.symbol_old.lower():
                        continue

                    die_index = row_idx * col_size + col_idx
                    if die_index < len(self._die_offsets):
                        die_offset = self._die_offsets[die_index]
                        self._modify_die_data(data, die_offset)
                        modified_count += 1

        # Для подсчета статистики используем оригинальный wafer_map (не повернутый)
        self._update_header(data,
                            pass_count=wafer_map.get_total_pass_dice(),
                            fail_count=wafer_map.get_total_fail_dice())

        self.new_data = bytes(data)
        logger.info(f"Патчинг завершен. Модифицировано кристаллов: {modified_count}")

        return modified_count

    def _rotate_matrix(self, matrix, rows: int, cols: int, rotation_angle: int) -> List[List[Optional['Die']]]:
        """
        Поворачивает матрицу кристаллов без изменения исходной.

        Args:
            matrix: Исходная матрица кристаллов
            rows: Количество строк
            cols: Количество столбцов
            rotation_angle: Угол поворота (90, 180, 270)

        Returns:
            Повернутая матрица
        """
        if rotation_angle == 90:
            # Поворот на 90 градусов против часовой стрелки
            rotated = [[None for _ in range(rows)] for _ in range(cols)]
            for i in range(rows):
                for j in range(cols):
                    rotated[cols - 1 - j][i] = matrix[i][j]
            return rotated

        elif rotation_angle == 180:
            # Поворот на 180 градусов
            rotated = [[None for _ in range(cols)] for _ in range(rows)]
            for i in range(rows):
                for j in range(cols):
                    rotated[rows - 1 - i][cols - 1 - j] = matrix[i][j]
            return rotated

        elif rotation_angle == 270:
            # Поворот на 270 градусов против часовой стрелки
            rotated = [[None for _ in range(rows)] for _ in range(cols)]
            for i in range(rows):
                for j in range(cols):
                    rotated[j][rows - 1 - i] = matrix[i][j]
            return rotated

        else:
            return matrix

    def _modify_die_data(self, data: bytearray, die_offset: int) -> None:
        """
        Модифицирует данные одного кристалла по указанному смещению.

        Args:
            data: Байтовый массив для модификации
            die_offset: Смещение начала данных кристалла (6 байт)
        """
        # Читаем текущие 6 байт
        die_bytes = data[die_offset:die_offset + 6]

        # Распаковываем слова
        word1 = struct.unpack('>H', die_bytes[0:2])[0]
        word2 = struct.unpack('>H', die_bytes[2:4])[0]
        word3 = struct.unpack('>H', die_bytes[4:6])[0]

        # Модифицируем только нужные поля
        # Die Test Result (биты 15-14)
        word1 = (word1 & ~(0b11 << 14)) | (self.MOD_DATA['die_test_result'] << 14)

        # Re-Probing Result (биты 11-10)
        word1 = (word1 & ~(0b11 << 10)) | (self.MOD_DATA['reprobing_result'] << 10)

        # Dummy Data (бит 9)
        word2 = (word2 & ~(0b1 << 9)) | (self.MOD_DATA['dummy_data'] << 9)

        # Die Property (биты 15-14)
        word2 = (word2 & ~(0b11 << 14)) | (self.MOD_DATA['die_property'] << 14)

        # Category Data (биты 0-5)
        word3 = (word3 & ~0x3F) | (self.MOD_DATA['category'] & 0x3F)

        # Упаковываем обратно
        modified_bytes = struct.pack('>HHH', word1, word2, word3)

        # Записываем в массив "на место"
        data[die_offset:die_offset + 6] = modified_bytes

    def _update_header(self, data: bytearray, pass_count: int, fail_count: int) -> None:
        """
        Обновляет значения Total pass dice и Total fail dice в заголовке.

        Args:
            data: Байтовый массив для модификации
            pass_count: Новое количество годных кристаллов
            fail_count: Новое количество бракованных кристаллов
        """
        # Используем сохраненные смещения, а не константы
        data[self._pass_dice_offset:self._pass_dice_offset + 2] = struct.pack('>H', pass_count)
        data[self._fail_dice_offset:self._fail_dice_offset + 2] = struct.pack('>H', fail_count)

        logger.debug(
            f"Обновлены счетчики в заголовке: PASS={pass_count}, FAIL={fail_count}")

    def _read_binary(self) -> None:
        """
        Чтение бинарного файла.

        Raises:
            KnownSystemException: Ошибки обработки bin-файла
            ValidationException: Ошибки при валидации bin-файла
        """
        try:
            if self._file_path is None:
                error_message = "Не указан путь к выходному bin-файлу карты годности"
                logger.error(error_message)
                raise KnownSystemException(message=error_message)

            with open(self._file_path, 'rb') as f:
                self.new_data = f.read()

            if not self.new_data:
                raise ValidationException(message="bin-файл карты годности пуст")

            logger.debug(f"Бинарный файл прочитан. Размер: {len(self.new_data)} байт")

        except FileNotFoundError:
            error_message = f"Входной bin-файл не найден по пути: {self._file_path}"
            logger.error(error_message)
            raise KnownSystemException(message=error_message)
        except Exception as e:
            error_message = f"Ошибка при чтении входного bin-файла: {self._file_path}"
            logger.error(f"{error_message}: {e}")
            raise KnownSystemException(message=error_message)

    def _parse_header(self) -> None:
        """
        Парсинг заголовка для получения необходимой информации
        и правильного вычисления смещения до данных кристаллов.
        """
        header = {}

        # Пропускаем поля, которые не нужны для патчинга
        self._offset += 20  # 1. Operator Name (20 bytes)
        self._offset += 16  # 2. Device Name (16 bytes)
        self._offset += 2  # 3. Wafer Size (2 bytes)
        self._offset += 2  # 4. Machine No. (2 bytes)
        self._offset += 4  # 5. Index Size X (4 bytes)
        self._offset += 4  # 6. Index Size Y (4 bytes)

        # 7. Standard Orientation (Flat Direction) - 2 bytes (0-359°)
        header['standard_orientation'] = self._parse_motorola_short(self._read_bytes(2))

        self._offset += 1  # 8. Final Editing Machine type (1 byte)
        self._offset += 1  # 9. Map Version (1 byte)

        # 10. Map data area col size (2 bytes)
        header['map_area_col_size'] = self._parse_motorola_short(self._read_bytes(2))

        # 11. Map data area row size (2 bytes)
        header['map_area_row_size'] = self._parse_motorola_short(self._read_bytes(2))

        # Пропускаем поля, которые не нужны для патчинга до окончания заголовочной инф.
        self._offset += 4  # 12. Map Data Form (Group Management) (4 bytes)
        self._offset += 21  # 13. Map Data Form (Group Management) (4 bytes)
        self._offset += 1  # 14. Number of Probing (1 byte)
        self._offset += 18  # 15. Lot No. (18 bytes)
        self._offset += 2  # 16. Cassette No. (2 bytes)
        self._offset += 2  # 17. Slot No. (2 bytes)
        self._offset += 1  # 18. X coordinates increase direction (1 byte)
        self._offset += 1  # 19. Y coordinates increase direction (1 byte)
        self._offset += 1  # 20. Reference die setting procedures (1 byte)
        self._offset += 1  # 21. Reserved (1 byte)
        self._offset += 4  # 22. Target die position X (4 bytes)
        self._offset += 4  # 23. Target die position Y (4 bytes)
        self._offset += 2  # 24. Reference die coordinator X (2 bytes)
        self._offset += 2  # 25. Reference die coordinator Y (2 bytes)
        self._offset += 1  # 26. Probing start position (1 byte)
        self._offset += 1  # 27. Probing direction (1 byte)
        self._offset += 2  # 28. Reserved (2 bytes)
        self._offset += 4  # 29. Distance X to wafer center die origin (4 bytes)
        self._offset += 4  # 30. Distance Y to wafer center die origin (4 bytes)
        self._offset += 4  # 31. Coordinator X of wafer center die (4 bytes)
        self._offset += 4  # 32. Coordinator Y of wafer center die (4 bytes)
        self._offset += 4  # 33. First Die Coordinator X (4 bytes)
        self._offset += 4  # 34. First Die Coordinator Y (4 bytes)
        self._offset += 12  # 35. Wafer Testing Start Time Data (12 bytes)
        self._offset += 12  # 36. Wafer Testing End Time Data (12 bytes)
        self._offset += 12  # 37. Wafer Loading Time Data (12 bytes)
        self._offset += 12  # 38. Wafer Unloading Time Data (10 bytes)
        self._offset += 4  # 39. Machine No. (дополнительный) (4 bytes)
        self._offset += 4  # 40. Machine No. (ещё один) (4 bytes)
        self._offset += 4  # 41. Special Characters (4 bytes)
        self._offset += 1  # 42. Testing End Information (1 byte)
        self._offset += 1  # 43. Пропускаем зарезервированные байты (1 byte)
        self._offset += 2  # 44. Total tested dice (2 bytes)

        # 45. Total pass dice (2 bytes)
        self._pass_dice_offset = self._offset
        header['total_pass_dice'] = self._parse_motorola_short(self._read_bytes(2))

        # 46. Total fail dice (2 bytes)
        self._fail_dice_offset = self._offset
        header['total_fail_dice'] = self._parse_motorola_short(self._read_bytes(2))

        self._offset += 4  # 47. Test Die Information Address (4 bytes)
        self._offset += 4  # 48. Number of line category data (4 bytes)
        self._offset += 4  # 49. Line category address (4 bytes)
        self._offset += 2  # 50. Map File Configuration (2 bytes)
        self._offset += 2  # 51. Max. Multi Site (2 bytes)
        self._offset += 2  # 52. Max. Categories (2 bytes)
        self._offset += 2  # 53. Пропускаем зарезервированные байты (2 bytes)

        self._header_info = header
        logger.debug(f"Заголовок распарсен. Размер заголовка: {self._offset} байт")
        logger.debug(f"Размеры карты: {header.get('map_area_col_size')}x{header.get('map_area_row_size')}")
        logger.debug(
            f"Кол-во годных кристаллов: {header.get('total_pass_dice')}, "
            f"Кол-во не годных кристаллов: {header.get('total_fail_dice')}")

    def _parse_die_offsets(self) -> None:
        """ Вычисляет смещения каждого кристалла в файле. """
        if not self._header_info:
            self._parse_header()

        col_size = self._header_info.get('map_area_col_size', 0)
        row_size = self._header_info.get('map_area_row_size', 0)

        if col_size == 0 or row_size == 0:
            raise ValidationException("Не удалось определить размеры карты")

        total_dice = col_size * row_size
        data_start = self._offset

        self._die_offsets = []
        for die_index in range(total_dice):
            die_offset = data_start + (die_index * 6)  # 6 байт на кристалл
            self._die_offsets.append(die_offset)

        logger.debug(f"Вычислены смещения для {total_dice} кристаллов")

    def _read_bytes(self, size: int) -> bytes:
        """ Чтение байтов с текущей позиции. """
        if self._offset + size > len(self.new_data):
            return b'\x00' * size
        result = self.new_data[self._offset:self._offset + size]
        self._offset += size
        return result

    def _parse_motorola_short(self, data: bytes) -> int:
        """ Парсинг 2-байтового Motorola short. """
        if len(data) < 2:
            return 0
        return struct.unpack('>H', data[:2])[0]
