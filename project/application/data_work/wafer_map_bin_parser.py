import struct
from typing import Dict, Any, List, Optional
from project.application.addition.exceptions import KnownSystemException, ValidationException
from project.application.addition.logger import logger


class WaferMapBinParser:
    """
    Класс-парсер для бинарного файла с электрических тестов спецификации:
    Edition of A-PM-90A / UF Series Map Data

    Attributes:
        _file_path (str): Путь к бинарному файлу
        _data (Optional[bytes]): Содержимое файла в виде байтов
        header_info (Dict[str, Any]): Информация из заголовка файла
        die_data (List[Dict[str, Any]]): Список данных по каждому кристаллу
        _offset (int): Текущая позиция при чтении файла
        _strict_validation_check (bool): Флаг строгой валидации
    """

    def __init__(self, file_path: str, strict_validation_check: bool = False) -> None:
        """
        Инициализация парсера бинарного файла карты годности.

        Args:
            file_path: Путь к бинарному файлу
            strict_validation_check: Флаг строгой валидации (если True, при ошибках валидации выбрасывается исключение)
        """
        self._file_path: str = file_path
        self._data: Optional[bytes] = None
        self.header_info: Dict[str, Any] = {}
        self.die_data: List[Dict[str, Any]] = []
        self._offset: int = 0
        self._strict_validation_check: bool = strict_validation_check

        if strict_validation_check:
            logger.debug("Режим строгой валидации файла карты годности ВКЛЮЧЁН")
        else:
            logger.debug("Режим строгой валидации файла карты годности ВЫКЛЮЧЕН")

    def parse(self) -> None:
        """
        Парсинг файла с валидацией.

        Raises:
            ValidationException: Если заголовочная или основная информация файла не прошло валидацию
        """
        self._read_binary()
        self._parse_header()

        logger.debug(f"Cчетчики в заголовке: "
                     f"PASS={self.header_info['total_pass_dice']}, FAIL={self.header_info['total_fail_dice']}")

        if self._strict_validation_check:
            error_message = self._validate_header()
            if error_message != "":
                error_message = f"Ошибка в валидации заголовка: {error_message}"
                logger.error(error_message)
                raise ValidationException(message=error_message)

        self._parse_test_result_per_die()

        logger.info(f"Парсинг файла карты годности завершен успешно. Кристаллов: {len(self.die_data)}")

    def _read_binary(self) -> None:
        """
        Чтение бинарного файла.

        Raises:
            ValidationException: Если заголовочная или основная информация файла не прошло валидацию
            KnownSystemException: Если возникли проблемы работы с файлом
        """
        try:
            with open(self._file_path, 'rb') as f:
                self.data = f.read()

            if not self.data:
                raise ValidationException(message="Файл карты годности пуст")

            if self._strict_validation_check:
                len_file_data = len(self.data)
                if len_file_data < 235:
                    error_message = f"Неверный размер файла: {len_file_data} байт. Минимальное количество байт: 235"
                    logger.error(error_message)
                    raise ValidationException(message=error_message)

            logger.debug(f"Бинарный файл карты годности прочитан. Размер: {len(self.data)} байт")

        except FileNotFoundError:
            logger.error(f"Файл карты годности не найден: {self._file_path}")
            raise KnownSystemException(message=f"Файл карты годности не найден: {self._file_path}")
        except PermissionError:
            logger.error(f"Файл карты годности не найден: {self._file_path}")
            raise KnownSystemException(message=f"Нет доступа к файлу карты годности: {self._file_path}")
        except Exception as e:
            logger.error(f"Ошибка при чтении файла карты годности: {e}")
            raise KnownSystemException(message=f"Ошибка при чтении файла карты годности")

    def _parse_header(self):
        """ Парсинг заголовочной информации (только требуемые поля). """
        header = {}

        self._offset += 20  # 1. Operator Name (20 bytes)
        self._offset += 16  # 2. Device Name (16 bytes)
        self._offset += 2  # 3. Wafer Size (2 bytes)
        self._offset += 2  # 4. Machine No. (2 bytes)
        self._offset += 4  # 5. Index Size X (4 bytes)
        self._offset += 4  # 6. Index Size Y (4 bytes)

        # 7. Standard Orientation (Flat Direction) - 2 bytes (0-359°)
        header['standard_orientation'] = self._parse_motorola_short(self._read_bytes(2))

        self._offset += 1  # 8. Final Editing Machine type - 1 byte
        self._offset += 1  # 9. Map Version (1 byte)

        # 10. Map data area row size (2 bytes) - это Map_area_col_size
        header['map_area_col_size'] = self._parse_motorola_short(self._read_bytes(2))

        # 11. Map data area line size (2 bytes) - это Map_area_row_size
        header['map_area_row_size'] = self._parse_motorola_short(self._read_bytes(2))

        self._offset += 4  # 12. Map Data Form (Group Management) (4 bytes)

        # 13. Wafer ID (21 bytes)
        header['wafer_ID'] = self._parse_string(self._read_bytes(21), 21, strip=True)

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

        # 33. First Die Coordinator X (4 bytes) - знаковое
        header['first_die_X'] = self._parse_signed_int(self._read_bytes(4))

        # 34. First Die Coordinator Y (4 bytes) - знаковое
        header['first_die_Y'] = self._parse_signed_int(self._read_bytes(4))

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

        # 45. Total pass dice - 2 bytes
        header['total_pass_dice'] = self._parse_motorola_short(self._read_bytes(2))

        # 46. Total fail dice - 2 bytes
        header['total_fail_dice'] = self._parse_motorola_short(self._read_bytes(2))

        self._offset += 4  # 47. Test Die Information Address (4 bytes)
        self._offset += 4  # 48. Number of line category data (4 bytes)
        self._offset += 4  # 49. Line category address (4 bytes)
        self._offset += 2  # 50. Map File Configuration (2 bytes)
        self._offset += 2  # 51. Max. Multi Site (2 bytes)
        self._offset += 2  # 52. Max. Categories (2 bytes)
        self._offset += 2  # 53. Пропускаем зарезервированные байты (2 bytes)

        self.header_info = header
        logger.debug(f"Заголовок распарсен. Размер заголовка: {self._offset} байт")

    def _validate_header(self) -> str:
        """
        Валидация заголовка файла

        Returns:
            str: Ошибка валидации в виде строки (или пустая строка в случае успешной валидации)
        """

        # Проверка размеров области карты
        row_size = self.header_info.get('map_area_col_size', 0)
        col_size = self.header_info.get('map_area_row_size', 0)
        total_dice = row_size * col_size

        if not (row_size > 0 and col_size > 0):
            return f"Некорректные размеры области карты: {row_size}x{col_size}. Должны быть положительные числа."
        else:
            if total_dice > 30000:  # Проверка разумности размеров
                return (f"Слишком большое количество кристаллов: {total_dice} ({row_size}x{col_size}). "
                        f"Допустимое количество: 30000")

        # Проверка целостности данных (ожидаемый размер файла)
        expected_size = self._offset + (row_size * col_size * 6)
        if len(self.data) < expected_size:
            return (f"Недостаточно данных в файле. "
                    f"Ожидалось: {expected_size} байт. Фактически: {len(self.data)} байт. "
                    f"Не хватает: {expected_size - len(self.data)} байт")

        # Проверка стандартной ориентации пластины
        orientation = self.header_info.get('standard_orientation', -1)
        if not (0 <= orientation <= 359):
            return f"Некорректная ориентация пластины: {orientation}. Допустимый диапазон: 0-359 гр."

        # Проверка First Die Coordinator
        first_x = self.header_info.get('first_die_X', 0)
        first_y = self.header_info.get('first_die_Y', 0)

        # Проверка разумных значений координат (типично ±10000)
        if abs(first_x) > 1000 or abs(first_y) > 1000:
            return f"Большие значения координат первого кристалла: X={first_x}, Y={first_y}"

        # Проверка Total pass dice
        total_pass_dice = self.header_info.get('total_pass_dice', -1)
        if total_pass_dice < 0:
            return (f"Некорректное количество кристаллов, прошедших проверку: {total_pass_dice}. "
                    f"Должно быть положительное число.")

        # Проверка Total fail dice
        total_fail_dice = self.header_info.get('total_fail_dice', -1)
        if total_fail_dice < 0:
            return (f"Некорректное количество кристаллов, НЕ прошедших проверку: {total_fail_dice}. "
                    f"Должно быть положительное число.")

        # Проверка Wafer ID
        wafer_id = self.header_info.get('wafer_ID', '')
        if not wafer_id or len(wafer_id.strip()) == 0:
            return f"Пустой Wafer ID"

        return ""

    def _parse_test_result_per_die(self) -> None:
        """
        Парсинг Test Result per Die
        согласно спецификации Edition of A-PM-90A / UF Series Map Data  (6 байт на кристалл)

        Raises:
            ValidationException: Если информация о кристаллах не прошла валидацию
        """

        # Получаем размеры области карты
        col_size = self.header_info.get('map_area_col_size', 0)
        row_size = self.header_info.get('map_area_row_size', 0)

        if not (row_size > 0 and col_size > 0):
            error_message = f"Не определены размеры области карты: ({col_size} строчек, {row_size} столбцов)"
            logger.error(error_message)
            raise ValidationException(message=error_message)

        total_dice = col_size * row_size
        self.die_data = []
        invalid_die_count = 0

        # Получаем координаты первого кристалла из заголовка
        first_die_x = self.header_info.get('first_die_X', 0)
        first_die_y = self.header_info.get('first_die_Y', 0)

        for die_index in range(total_dice):
            die_info = {}

            # Рассчитываем ожидаемые координаты на основе позиции кристалла в сетке
            # Индексы идут построчно, слева направо, сверху вниз
            row = die_index // col_size  # номер строки (0-based)
            col = die_index % col_size  # номер столбца (0-based)

            # Ожидаемые координаты: отталкиваемся от координат первого кристалла
            expected_x = first_die_x + col
            expected_y = first_die_y + row

            try:
                die_bytes = self._read_bytes(6)  # Читаем 6 байт данных для каждого кристалла

                # Разбираем на 3 слова по 2 байта (Motorola big-endian)
                word1 = struct.unpack('>H', die_bytes[0:2])[0]
                word2 = struct.unpack('>H', die_bytes[2:4])[0]
                word3 = struct.unpack('>H', die_bytes[4:6])[0]

                dummy_data = (word2 >> 9) & 0b1  # Dummy Data (except wafer) (бит 9)
                die_property = (word2 >> 14) & 0b11  # Die Property (биты 15-14)
                die_test_result = (word1 >> 14) & 0b11  # Die Test Result (биты 15-14)
                reprobing_result = (word1 >> 10) & 0b11  # Re-Probing Result (биты 11-10)
                category = (word3 & 0x3F)  # Category Data (биты 5-0) - 6 бит для значений 0-63

                die_info['symbol'] = self._determine_symbol(
                    dummy_data=dummy_data,
                    die_property=die_property,
                    die_test_result=die_test_result,
                    reprobing_result=reprobing_result,
                    category=category
                )

                # Die Coordinator Values X (биты 8-0)
                coord_x_value = word1 & 0x1FF  # 9 бит
                # Проверка знака (бит 8 - знаковый бит)
                if coord_x_value & 0x100:  # Если установлен бит знака
                    coord_x_value = -((coord_x_value ^ 0x1FF) + 1)  # Дополнение до двух

                # Die Coordinator Value Y (биты 8-0)
                coord_y_value = word2 & 0x1FF  # 9 бит
                # Проверка знака (бит 8 - знаковый бит)
                if coord_y_value & 0x100:  # Если установлен бит знака
                    coord_y_value = -((coord_y_value ^ 0x1FF) + 1)  # Дополнение до двух

                coord_x_sign_bit = (word2 >> 11) & 0b1  # Code Bit of Coordinator Value X (бит 11)
                coord_y_sign_bit = (word2 >> 10) & 0b1  # Code Bit of Coordinator Value Y (бит 10)

                # Применяем знак к координатам
                coord_x_final = -coord_x_value if coord_x_sign_bit == 1 else coord_x_value
                coord_y_final = -coord_y_value if coord_y_sign_bit == 1 else coord_y_value

                # Сохраняем только финальные координаты
                die_info['die_coordinator_values_x'] = coord_x_final
                die_info['die_coordinator_values_y'] = coord_y_final

                # Формируем словарь raw_data для валидации
                validation_result = self._validate_die_data(raw_data={
                    'dummy_data': dummy_data,
                    'die_property': die_property,
                    'die_test_result': die_test_result,
                    'reprobing_result': reprobing_result,
                    'category': category,

                    'coord_x_value': coord_x_value,
                    'coord_y_value': coord_y_value,
                    'coord_x_sign_bit': coord_x_sign_bit,
                    'coord_y_sign_bit': coord_y_sign_bit,
                    'coord_x_final': coord_x_final,
                    'coord_y_final': coord_y_final,

                    'word1': word1,
                    'word2': word2,
                    'word3': word3
                })
                if validation_result != "":
                    raise Exception(f"Ошибка валидации: {validation_result}")

            except struct.error or Exception as e:
                if self._strict_validation_check:
                    error_message = f"Ошибка валидации кристалла: {die_index} (строка {row}, столбец {col})"
                    logger.error(f"{error_message}: {e}")
                    raise ValidationException(message=error_message)
                else:
                    invalid_die_count += 1
                    logger.warning(
                        f"Не удалось распаковать байты кристалла {die_index} (строка {row}, столбец {col}): {e}")

                    # Валидируем текущий кристалл
                    die_info = {
                        'symbol': "f",
                        'die_coordinator_values_x': expected_x,
                        'die_coordinator_values_y': expected_y
                    }
                    logger.debug(f"Данные по кристаллу {die_index} были дополнены")

            self.die_data.append(die_info)

        logger.debug(f"Парсинг завершен. Успешно: {len(self.die_data) - invalid_die_count}, "
                     f"Ошибки: {invalid_die_count}")

    def _validate_die_data(self, raw_data: Dict[str, Any]) -> str:
        """
        Валидация данных кристалла с учетом спецификации форматов карт.

        Args:
            raw_data: Словарь данных для валидации

        Returns:
            str: Ошибка валидации в виде строки (или пустая строка в случае успешной валидации)
        """
        # 1. Проверка Dummy Data
        dummy_data = raw_data.get('dummy_data', 0)
        if dummy_data not in (0, 1):
            return f"Некорректный Dummy Data: {dummy_data} (ожидается 0 или 1)"

        # 2. Проверка Die Property
        die_property = raw_data.get('die_property', 0)
        # 0=Skip Die, 1=Probing Die, 2=Compulsory Marking Die
        if die_property not in (0, 1, 2):
            return f"Некорректное свойство кристалла: {die_property} (ожидается 0,1,2)"

        # 3. Проверка Die Test Result
        die_test_result = raw_data.get('die_test_result', 0)
        # Согласно спецификации: 0=Not Tested, 1=Pass, 2=Fail 1, 3=Fail 2
        if not (0 <= die_test_result <= 3):
            return f"Некорректный результат теста: {die_test_result} (ожидается 0..3)"

        # 4. Проверка Re-Probing Result
        reprobing_result = raw_data.get('reprobing_result', 0)
        # 0=Not Re-Probed, 1=Passed at re-probing, 2=Failed at re-probing, 3=Reserved
        if not (0 <= reprobing_result <= 3):
            return f"Некорректный Re-Probing Result: {reprobing_result} (ожидается 0..3)"

        # 5. Проверка Category Data
        category = raw_data.get('category', 0)
        # 0-1023 для поддержки всех форматов
        if not (0 <= category <= 1023):
            return f"Некорректная категория: {category} (ожидается 0..1023)"

        # 6. Проверка координат
        # Die Coordinator Values: 9 бит без знака (0-511)
        coord_x = raw_data.get('coord_x_value', 0)
        if not (0 <= coord_x <= 511):
            return f"Координата X вне диапазона: {coord_x} (ожидается 0..511)"

        coord_y = raw_data.get('coord_y_value', 0)
        if not (0 <= coord_y <= 511):
            return f"Координата Y вне диапазона: {coord_y} (ожидается 0..511)"

        # 7. Проверка знаковых битов
        # Code Bit of Coordinator Value: 0=+data, 1=-data
        sign_x = raw_data.get('coord_x_sign_bit', 0)
        if sign_x not in (0, 1):
            return f"Некорректный знаковый бит X: {sign_x} (ожидается 0 или 1)"

        sign_y = raw_data.get('coord_y_sign_bit', 0)
        if sign_y not in (0, 1):
            return f"Некорректный знаковый бит Y: {sign_y} (ожидается 0 или 1)"

        # 8. Проверка финальных координат (9 бит со знаком: -256..255)
        # Это комбинация coord_x_value и coord_x_sign_bit
        x_final = raw_data.get('coord_x_final', 0)
        if not (-256 <= x_final <= 255):
            return f"Финальная координата X вне диапазона: {x_final} (ожидается -256..255)"

        y_final = raw_data.get('coord_y_final', 0)
        if not (-256 <= y_final <= 255):
            return f"Финальная координата Y вне диапазона: {y_final} (ожидается -256..255)"

        # 10. Проверка битовых полей word1, word2, word3 (если есть)
        # Согласно странице 19-20, это 16-битные слова
        for word_key in ['word1', 'word2', 'word3']:
            if word_key in raw_data:
                word_value = raw_data.get(word_key, 0)
                # Проверка, что это 16-битное беззнаковое целое
                if not (0 <= word_value <= 0xFFFF):
                    return f"Некорректное значение {word_key}: {word_value} (ожидается 0..65535)"

        return ""

    def _determine_symbol(self,
                          dummy_data: int,
                          die_property: int,
                          die_test_result: int,
                          reprobing_result: int,
                          category: int) -> str:
        """
        Определяет символ на основе таблицы соответствия.

        Args:
            dummy_data: Параметр кристалла по спецификации
            die_property: Параметр кристалла по спецификации
            die_test_result: Параметр кристалла по спецификации
            reprobing_result: Параметр кристалла по спецификации
            category: Параметр кристалла по спецификации

        Returns:
            str: Символ-статус кристалла
        """
        patterns = [
            ([1, 0, 0, 0, 0], "D", True),
            ([0, 0, 0, 0, 0], "S", True),
            ([0, 2, 0, 0, 0], "M", True),
            ([0, 1, 0, 0, 0], "T", True),
            ([0, 1, 1, 0, None], "P", False),
            ([0, 1, 1, 1, None], "p", False),
            ([0, 1, [2, 3], 0, None], "f", False),
            ([0, 1, [2, 3], 2, None], "F", False),
        ]

        input_values = [dummy_data, die_property, die_test_result, reprobing_result, category]

        for pattern, symbol, letters_only in patterns:
            if self._match_pattern(input_values, pattern):
                if letters_only:
                    return symbol
                else:
                    return f"{symbol}{category}"

        return "D"

    def _match_pattern(self, input_values: List[int], pattern: List) -> bool:
        """ Сравнивает входные значения с шаблоном. """
        if len(input_values) != len(pattern):
            return False

        for i in range(len(input_values)):
            pattern_val = pattern[i]
            if pattern_val is None:
                continue

            input_val = input_values[i]

            if isinstance(pattern_val, list):
                if input_val not in pattern_val:
                    return False
            else:
                if input_val != pattern_val:
                    return False

        return True

    def _read_bytes(self, size: int) -> bytes:
        """ Чтение байтов с текущей позиции offset. """
        if self._offset + size > len(self.data):
            return b'\x00' * size
        result = self.data[self._offset:self._offset + size]
        self._offset += size
        return result

    def _parse_motorola_short(self, data: bytes) -> int:
        """ Чтение 2-байтового значения в формате Motorola (big-endian). """
        if len(data) < 2:
            return 0
        return struct.unpack('>H', data[:2])[0]

    def _parse_signed_int(self, data: bytes) -> int:
        """ Чтение 4-байтового знакового значения в формате Motorola (big-endian). """
        if len(data) < 4:
            return 0
        return struct.unpack('>i', data[:4])[0]

    def _parse_string(self, data: bytes, length: int, strip: bool = True) -> str:
        """ Чтение байтов в виде строки. """
        if len(data) < length:
            return ""

        decoded = data[:length].decode('ascii', errors='ignore')
        decoded = decoded.replace('\x00', '')
        if strip:
            return decoded.strip()
        else:
            return decoded
