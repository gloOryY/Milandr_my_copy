from typing import Optional, Dict, Any, Union


class BaseException(Exception):
    """
    Базовый класс для всех исключений системы.
    Предоставляет единый интерфейс для работы с ошибками.

    Attributes:
        message (str): Сообщение об ошибке
        details (Dict[str, Any]): Дополнительные детали ошибки
        error_name (str): Имя/код ошибки для идентификации
    """
    def __init__(self,
                 message: str = "Ошибка системы",
                 details: Optional[Dict[str, Any]] = None,
                 error_name: Optional[str] = None) -> None:
        """
        Инициализация базового исключения.

        Args:
            message: Сообщение об ошибке
            details: Дополнительные детали ошибки (словарь)
            error_name: Имя/код ошибки для идентификации
        """
        self.message: str = message
        self.details: Dict[str, Any] = details or {}
        self.error_name: str = error_name or "UNKNOWN_ERROR"
        super().__init__(self.message)

    def __str__(self) -> str:
        """ Строковое представление ошибки. """
        return self.message

    def get_full_info(self) -> str:
        """ Возвращает полную информацию об ошибке с деталями. """
        if self.details:
            return f"{self.message} | Детали: {self.details} | Код: {self.error_name}"
        return f"{self.message} | Код: {self.error_name}"

    def to_dict(self) -> Dict[str, Any]:
        """ Преобразует ошибку в словарь для логирования/сериализации. """
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details,
            'error_name': self.error_name
        }


class RobotException(BaseException):
    """Исключения робота."""

    def __init__(self,
                 message: str = "Ошибка Манипулятора",
                 details: Optional[Dict[str, Any]] = None,
                 error_name: str = "ROBOT_ERROR") -> None:
        super().__init__(message, details, error_name)


class CameraException(BaseException):
    """Исключения, связанные с работой камеры."""

    def __init__(self,
                 message: str = "Ошибка Камеры",
                 camera_id: Optional[int] = None,
                 details: Optional[Dict[str, Any]] = None,
                 error_name: str = "CAMERA_ERROR") -> None:

        if camera_id is not None:
            details = details or {}
            details['camera_id'] = camera_id
            message = f"{message} (камера {camera_id})"

        super().__init__(message, details, error_name)

    @property
    def camera_id(self) -> Optional[int]:
        """ Возвращает ID камеры из деталей ошибки. """
        return self.details.get('camera_id')


class ValidationException(BaseException):
    """Исключения валидации данных."""

    def __init__(self,
                 message: str = "Ошибка Валидации",
                 details: Optional[Dict[str, Any]] = None,
                 error_name: str = "VALIDATION_ERROR") -> None:
        super().__init__(message, details, error_name)


class ProtocolException(BaseException):
    """Исключения генерации или изменения протокольных данных."""

    def __init__(self,
                 message: str = "Ошибка генерации протоколов",
                 details: Optional[Dict[str, Any]] = None,
                 error_name: str = "PROTOCOL_ERROR") -> None:
        super().__init__(message, details, error_name)


class KnownSystemException(BaseException):
    """Базовый класс для известных (обрабатываемых) системных исключений."""

    def __init__(self,
                 message: str = "Известная системная ошибка",
                 details: Optional[Dict[str, Any]] = None,
                 error_name: str = "SYSTEM_ERROR") -> None:
        super().__init__(message, details, error_name)