import os
import json
import builtins
from pathlib import Path
from collections import OrderedDict
from typing import Dict, Any, Optional
from project.application.addition.logger import logger

# Сохраняем прямую ссылку на функцию open
_open = builtins.open

FILE_TEMPLATES: Dict[str, OrderedDict[str, Any]] = {
    "camera_config.json": OrderedDict([
        ("sensor_width_px", 5496),
        ("sensor_height_px", 3672),
        ("fov_width_mm", 4.72),
        ("fov_height_mm", 3.45),
        ("mm_to_px", 1250.0),
        ("px_to_mm", 0.0008),
        ("vendor", "ND"),
        ("model_name", "NS-2000UC")
    ]),

    "coordinates.json": OrderedDict([
        ("current_coordinate_of_the_station_by_x", 0),
        ("current_coordinate_of_the_station_by_y", 0),
        ("current_coordinate_of_the_station_by_z", 0),
        ("x_minimum", 0),
        ("x_maximum", 380),
        ("y_minimum", 0),
        ("y_maximum", 380),
        ("z_minimum", -80),
        ("z_maximum", 0),
        ("x_coordinate_of_the_first_cell", 0),
        ("y_coordinate_of_the_first_cell", 0),
        ("z_coordinate_of_the_first_cell", 0)
    ]),

    "delegation.json": OrderedDict([
        ("delegated_users", [])
    ]),

    "launch.json": OrderedDict([
        ("distance_between_vertical_centers_of_cells", 3.62),
        ("distance_between_horizontal_centers_of_cells", 2.9),
        ("symbols_need_check", ["P", "p"])
    ]),

    "measure.json": OrderedDict([
        ("measure_units", "Миллиметры (1 мм)"),
        ("translation_coefficient", 0.3)
    ]),

    "panel_switches.json": OrderedDict([
        ("scale_buttons_panel", 1.0),
        ("movement_step", 0.1),
        ("move_to_first_ref_die_switch", True),
    ]),

    "picture.json": OrderedDict([
        ("brightness", 50),
        ("contrast", 50),
        ("saturation", 50),
        ("grain_level", 50),
        ("red_filter", 100),
        ("green_filter", 100),
        ("blue_filter", 100)
    ]),

    "protocol.json": OrderedDict([
        ("input_file_path", "~"),
        ("protocol_path", "~"),
        ("main_folder_path", "Пластина"),
        ("after_AOI_folder_name", "После_АОИ"),
        ("before_AOI_folder_name", "До_АОИ"),
        ("defective_dice_folder_name", "Бракованные_кристаллы_Фотографии"),
        ("after_AOI_excel_protocol_file_name", "Карта_годности_после_АОИ.xlsx"),
        ("before_AOI_excel_protocol_file_name", "Карта_годности_до_АОИ.xlsx"),
        ("json_protocol_file_name", "Отчёт.json"),
        ("symbol_colors", OrderedDict([
            ("FV", "A34117"),
            ("PV", "627F0F"),
            ("F", "C71C27"),
            ("f", "D93641"),
            ("P", "31F01F"),
            ("p", "68E85D"),
            ("D", "FFFFFF"),
            ("S", "ECF01F"),
            ("M", "F3E5AB"),
            ("T", "F5DEB3")
        ]))
    ]),

    "robot_config.json": OrderedDict([
        ("settings", OrderedDict([
            ("0", "10"),
            ("1", "255"),
            ("2", "0"),
            ("3", "6"),
            ("4", "0"),
            ("5", "0"),
            ("6", "0"),
            ("10", "1"),
            ("11", "0.010"),
            ("12", "0.002"),
            ("13", "0"),
            ("20", "1"),
            ("21", "1"),
            ("22", "1"),
            ("23", "3"),
            ("24", "250.000"),
            ("25", "4000.000"),
            ("26", "230"),
            ("27", "3.000"),
            ("30", "1000"),
            ("31", "0"),
            ("32", "0"),
            ("100", "80.000"),
            ("101", "80.000"),
            ("102", "800.000"),
            ("110", "15000.000"),
            ("111", "15000.000"),
            ("112", "3000.000"),
            ("120", "1500.000"),
            ("121", "1500.000"),
            ("122", "900.000"),
            ("130", "430.000"),
            ("131", "390.000"),
            ("132", "90.000")
        ])),
        ("startup_blocks", OrderedDict([
            ("0", "G21 G90 G54 G92 X0 Y0 Z0"),
        ]))
    ]),

    "theme.json": OrderedDict([
        ("theme", "dark")
    ]),

    "models.json": OrderedDict([
        ("defects", [
            OrderedDict([
                ("black_point", OrderedDict([
                    ("name", "Загрязнение"),
                    ("color", [255, 0, 0]),
                    ("description", "Частица грязи малых размеров (до 0.1 мм)"),
                    ("versions", [
                        OrderedDict([
                            ("id_version", 1),
                            ("description_version", "Модель, обученная на YOLO 12 и "
                                                    "тренированная на изображениях 1280х720"),
                            ("path", "project\\algorithms\\neural_network\\models\\fixed_particle.pt"),
                            ("conf", "0.5")
                        ])
                    ])
                ])),
                ("cutting_error", OrderedDict([
                    ("name", "Ошибка реза"),
                    ("color", [255, 255, 0]),
                    ("description", "Черные линии трещин от неправильного реза на границе рабочей зоны кристалла"),
                    ("versions", [
                        OrderedDict([
                            ("id_version", 1),
                            ("description_version", "Модель, обученная на YOLO 12 и "
                                                    "тренированная на изображениях 400х600"),
                            ("path", "project\\algorithms\\neural_network\\models\\cutting_error.pt"),
                            ("conf", "0.5")
                        ])
                    ])
                ]))
            ])
        ])
    ])
}

def write_to_json(file_path: str, key: str, value: any) -> bool:
    try:
        path = Path(file_path)
        if not path.exists():
            data = {}
        else:
            with _open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

        data[key] = value

        with _open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Неожиданная ошибка в функции write_to_json для файла {file_path}: {e}")
        return False


def read_from_json(path: str, key: str) -> Optional[Any]:
    """
    Читает данные из JSON файла по указанному ключу.

    Args:
        path: Путь к файлу, из которого будут прочитаны данные
        key: Ключ, по которому будет извлечено значение

    Returns:
        Optional[Any]: Значение по указанному ключу, если ключ существует.
                       Иначе None
    """

    def is_valid_json_file(json_path: str) -> bool:
        """ Проверяет, существует ли файл и является ли он валидным JSON-файлом. """
        if not os.path.exists(json_path):
            return False

        try:
            with open(json_path, 'r', encoding='utf-8') as file:
                json.load(file)
            return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False

    def validate_and_repair_json(json_path: str) -> bool:
        """ Проверяет и восстанавливает JSON файл, добавляя недостающие поля из шаблона. """
        filename = os.path.basename(json_path)
        if filename not in FILE_TEMPLATES:
            logger.error(f"Нет шаблона для файла {filename}")
            return False

        template = FILE_TEMPLATES[filename]

        # Если файла нет или он невалиден, файл создаётся заново
        if not is_valid_json_file(json_path):
            try:
                with open(json_path, 'w', encoding="utf-8") as file:
                    json.dump(template, file, indent=4, ensure_ascii=False)
                return True
            except Exception as e:
                logger.error(f"Ошибка при создании файла {json_path}: {e}")
                return False

        # Считывание существующих данных
        try:
            with open(json_path, 'r', encoding='utf-8') as file:
                existing_data = json.load(file)
        except Exception as e:
            logger.error(f"Ошибка при чтении файла {json_path}: {e}")
            return False

        def rebuild_dict_with_template(current_data: Dict[str, Any],
                                       template_data: OrderedDict[str, Any]) -> OrderedDict[str, Any]:
            """ Перестраивает словарь в соответствии с шаблоном, сохраняя порядок ключей. """
            result = OrderedDict()
            for template_key, template_value in template_data.items():
                if template_key in current_data:
                    current_value = current_data[template_key]
                    if isinstance(template_value, OrderedDict) and isinstance(current_value, dict):
                        result[template_key] = rebuild_dict_with_template(current_value, template_value)
                    else:
                        result[template_key] = current_value
                else:
                    result[template_key] = template_value

            return result

        # Перестраивание данных в соответствии с шаблоном
        if isinstance(existing_data, dict) and isinstance(template, OrderedDict):
            rebuilt_data = rebuild_dict_with_template(existing_data, template)
            if rebuilt_data != existing_data:
                try:
                    with open(json_path, 'w', encoding="utf-8") as file:
                        json.dump(rebuilt_data, file, indent=4, ensure_ascii=False)
                    return True
                except Exception as e:
                    logger.error(f"Ошибка при обновлении файла {json_path}: {e}")
                    return False
        else:
            try:
                with open(json_path, 'w', encoding="utf-8") as file:
                    json.dump(template, file, indent=4, ensure_ascii=False)
                return True
            except Exception as e:
                logger.error(f"Ошибка при пересоздании файла {json_path}: {e}")
                return False

        return True

    # Проверка и восстановление файла при необходимости
    if not validate_and_repair_json(path):
        logger.error(f"Не удалось восстановить файл {path}")
        return None

    # Считывание файла
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при чтении файла {path}: {e}")
        return None

    return data.get(key, None)
