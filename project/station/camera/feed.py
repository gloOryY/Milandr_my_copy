import cv2
import numpy as np
import base64
import os
from PIL import Image, ImageDraw, ImageFont
from typing import List, Any, Optional, Tuple, Union
from project.application.addition.colors import color_mode
from project.configuration.config_manager import ConfigManager
from project.application.addition.logger import logger


def show_loading_image(text: str,
                       windows: Union[Any, List[Any]],
                       config: ConfigManager) -> None:
    """
    Показывает статичное изображение с текстом загрузки в указанных окнах.

    Args:
        text: Текст для отображения (например, "Манипулятор калибруется")
        windows: Окно или список окон, в которых нужно показать картинку
        config: Конфигурация (для определения цветовой схемы)
    """
    if windows is None:
        return

    # Приводим к списку
    if not isinstance(windows, (list, tuple)):
        windows = [windows]

    # Определяем размер окна (берём из первого доступного)
    width, height = 400, 400
    for w in windows:
        if hasattr(w, 'width') and hasattr(w, 'height'):
            width = int(w.width) if w.width else width
            height = int(w.height) if w.height else height
            break

    # Создаём статичный кадр
    frame = _create_static_loading_frame(text, config, width, height)

    # Кодируем в base64
    success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        logger.error("Ошибка кодирования изображения загрузки")
        return

    frame_base64 = base64.b64encode(buffer).decode('utf-8')

    # Устанавливаем в каждое окно
    for window in windows:
        if hasattr(window, 'src_base64'):
            window.src_base64 = frame_base64
            if hasattr(window, 'update'):
                window.update()


def hide_loading_image(windows: Union[Any, List[Any]]) -> None:
    """
    Очищает окна, убирая загрузочное изображение.

    Args:
        windows: Окно или список окон для очистки
    """
    if windows is None:
        return

    if not isinstance(windows, (list, tuple)):
        windows = [windows]

    for window in windows:
        if hasattr(window, 'src_base64'):
            window.src_base64 = ""
            if hasattr(window, 'update'):
                window.update()


# ----------------------------------------------------------------------
# Ниже – вспомогательные функции (без изменений, как в исходном feed.py)
# Они используются show_loading_image для создания изображения
# ----------------------------------------------------------------------

def _get_window_size(window: Optional[Any]) -> Tuple[int, int]:
    if hasattr(window, 'width') and hasattr(window, 'height'):
        width = int(window.width) if window.width else 400
        height = int(window.height) if window.height else 400
    else:
        width, height = 400, 400
    return width, height


def _create_static_loading_frame(display_text: str,
                                 config: ConfigManager,
                                 width: int = 400,
                                 height: int = 400) -> np.ndarray:
    if config is not None:
        colors = color_mode(config)
        bg_color = colors["inactive"]
        text_color = colors["text"]
        bg_bgr = _hex_to_bgr(bg_color)
        text_bgr = _hex_to_bgr(text_color)
    else:
        bg_bgr = (67, 78, 84)          # тёмный фон по умолчанию
        text_bgr = (236, 236, 236)     # светлый текст

    frame = np.full((height, width, 3), bg_bgr, dtype=np.uint8)
    _draw_russian_text(frame, display_text, width, height, text_bgr)
    return frame


def _hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return b, g, r


def _draw_russian_text(frame: np.ndarray,
                       text: str,
                       width: int = 400,
                       height: int = 400,
                       text_color: Tuple[int, int, int] = (255, 255, 255)) -> None:
    try:
        FONT_PATH = r"C:/Windows/Fonts/arial.ttf"
        if not os.path.exists(FONT_PATH):
            FONT_PATH = None

        max_text_width = int(width * 0.9)
        # Увеличенный базовый размер шрифта
        base_font_size = max(36, height // 15)

        pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_image)

        font_size = base_font_size
        wrapped_lines = []
        font = None

        for attempt in range(5):
            try:
                if FONT_PATH:
                    font = ImageFont.truetype(FONT_PATH, font_size)
                else:
                    font = ImageFont.load_default()

                wrapped_lines = []
                words = text.split(' ')
                current_line = []

                for word in words:
                    test_line = ' '.join(current_line + [word])
                    bbox = draw.textbbox((0, 0), test_line, font=font)
                    line_width = bbox[2] - bbox[0]

                    if line_width <= max_text_width:
                        current_line.append(word)
                    else:
                        if current_line:
                            wrapped_lines.append(' '.join(current_line))
                        current_line = [word]

                if current_line:
                    wrapped_lines.append(' '.join(current_line))

                if wrapped_lines:
                    # Увеличенный межстрочный интервал
                    line_spacing = font_size // 2   # было font_size // 4
                    total_height = len(wrapped_lines) * (bbox[3] - bbox[1] + line_spacing)
                    if total_height <= height * 0.8:
                        break

                font_size = max(18, font_size - 4)  # было max(12, ...)
            except Exception:
                font_size = max(18, font_size - 4)
                continue

        if not font:
            if FONT_PATH:
                font = ImageFont.truetype(FONT_PATH, base_font_size)
            else:
                font = ImageFont.load_default()

        total_text_height = 0
        line_heights = []
        line_spacing = font_size // 2  # финальный межстрочный интервал

        for line in wrapped_lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_height = bbox[3] - bbox[1]
            line_heights.append(line_height)
            total_text_height += line_height + line_spacing

        # Корректировка, чтобы не вычесть последний spacing
        if line_heights:
            total_text_height -= line_spacing

        y_position = (height - total_text_height) // 2

        for i, line in enumerate(wrapped_lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            x_position = (width - line_width) // 2

            draw.text((x_position, y_position), line, font=font, fill=text_color)
            y_position += line_heights[i] + line_spacing

        frame[:] = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    except Exception as e:
        logger.error(f"Ошибка отрисовки текста: {e}")