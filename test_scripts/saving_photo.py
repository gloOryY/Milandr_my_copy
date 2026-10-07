import cv2
import datetime
from project.application.addition.logger import logger


def save_photo(frame_or_base64, frame_name):
    """Сохраняет фотографию, принимая либо numpy array, либо base64 строку"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"C:/Users/user/Desktop/Фотки/{frame_name}_{timestamp}.jpg"

    try:
        if isinstance(frame_or_base64, str):
            import base64
            import numpy as np

            img_data = base64.b64decode(frame_or_base64)
            nparr = np.frombuffer(img_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        else:
            frame = frame_or_base64

        if frame is None or frame.size == 0:
            logger.debug(f"Ошибка: пустое изображение для {frame_name}")
            return False

        success = cv2.imwrite(filename, frame)
        if success:
            logger.debug(f"Сохранён кадр: {filename}")
            return True
        else:
            logger.error(f"Ошибка сохранения: {filename}")
            return False

    except Exception as e:
        logger.error(f"Исключение при сохранении {frame_name}: {e}")
        return False


# def show_and_save_photo(left_column, cap, id_crystal, quarter, config_ctrl):
#     """
#     Захватывает кадр с камеры, отображает его в интерфейсе и сохраняет в файл.
#
#     :param left_column: Левая колонка интерфейса, куда будет выведено изображение.
#     :param cap: Объект видеопотока с камеры.
#     :param id_crystal: Идентификатор кристалла, используется для формирования имени файла.
#     :param quarter: Номер квартала, используется для формирования имени файла.
#     :returns:
#         2: Заглушка для успешного выполнения операции.
#     """
#
#     time.sleep(0.3)
#     img_base64, frame = capture_frame_to_base64(cap)
#
#     # Обновление интерфейса
#     left_column.src_base64 = img_base64
#     left_column.update()
#
#     file_path = "project/something/"
#     file_name = f"photo_crystal_{id_crystal}_quarter_{quarter}.jpg"
#
#     # Сохранение изображения в файл
#     save_photo(frame, file_path+file_name)
#
#     return 2






