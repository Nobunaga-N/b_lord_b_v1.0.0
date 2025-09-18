"""
Базовый класс ADBController для управления эмулятором Android через ADB.
Предоставляет основные методы для взаимодействия с устройством.
"""
import time
import io
import socket
import os
from PIL import Image
from loguru import logger
try:
    from adb_shell.adb_device import AdbDeviceTcp
    from adb_shell.exceptions import TcpTimeoutException
except ImportError:
    logger.warning("adb-shell не установлен, используется заглушка")
    AdbDeviceTcp = None
    TcpTimeoutException = None


class ADBController:
    """Контроллер для управления Android эмулятором через ADB"""

    def __init__(self, host='127.0.0.1', port=5555, device_id=None):
        """
        Инициализация ADB контроллера

        Args:
            host (str): IP адрес ADB сервера
            port (int): Порт для подключения
            device_id (str): ID устройства (опционально)
        """
        self.host = host
        self.port = port
        self.device_id = device_id or f"{host}:{port}"
        self.device = None
        self.connected = False

        logger.info(f"ADBController инициализирован для {self.device_id}")

    def connect(self):
        """
        Подключение к ADB устройству

        Returns:
            bool: True если подключение успешно
        """
        try:
            if AdbDeviceTcp is None:
                logger.error("adb-shell не установлен. Установите: pip install adb-shell")
                return False

            # Создаем TCP подключение к устройству
            self.device = AdbDeviceTcp(self.host, self.port)

            # Подключаемся (без rsa_keys для эмуляторов)
            self.device.connect()

            # Проверяем подключение
            if self.check_connection():
                self.connected = True
                logger.info(f"Успешно подключен к {self.device_id}")
                return True
            else:
                logger.error(f"Не удалось установить соединение с {self.device_id}")
                return False

        except Exception as e:
            logger.error(f"Ошибка подключения к {self.device_id}: {e}")
            return False

    def disconnect(self):
        """
        Отключение от устройства

        Returns:
            bool: True если отключение успешно
        """
        try:
            if self.device:
                self.device.close()
            self.connected = False
            self.device = None
            logger.info(f"Отключен от {self.device_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка отключения от {self.device_id}: {e}")
            return False

    def check_connection(self):
        """
        Проверка состояния подключения

        Returns:
            bool: True если устройство подключено и отвечает
        """
        try:
            if self.device is None:
                return False

            # Простая команда для проверки связи
            result = self.device.shell("echo test")
            return "test" in result

        except Exception as e:
            logger.error(f"Ошибка проверки подключения {self.device_id}: {e}")
            return False

    def tap(self, x, y, duration=100):
        """
        Выполнить тап по координатам

        Args:
            x (int): X координата
            y (int): Y координата
            duration (int): Длительность тапа в мс

        Returns:
            bool: True если тап выполнен успешно
        """
        try:
            if not self.connected or self.device is None:
                logger.error("Устройство не подключено")
                return False

            # Выполняем тап через input tap
            result = self.device.shell(f"input tap {x} {y}")

            # Пауза для стабильности
            time.sleep(duration / 1000.0)

            logger.debug(f"Тап по координатам ({x}, {y}) на {self.device_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка выполнения тапа на {self.device_id}: {e}")
            return False

    def swipe(self, x1, y1, x2, y2, duration=1000):
        """
        Выполнить свайп между двумя точками

        Args:
            x1, y1 (int): Начальные координаты
            x2, y2 (int): Конечные координаты
            duration (int): Длительность свайпа в мс

        Returns:
            bool: True если свайп выполнен успешно
        """
        try:
            if not self.connected or self.device is None:
                logger.error("Устройство не подключено")
                return False

            # Выполняем свайп через input swipe
            result = self.device.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}")

            # Пауза для завершения анимации
            time.sleep(duration / 1000.0 + 0.5)

            logger.debug(f"Свайп от ({x1}, {y1}) до ({x2}, {y2}) на {self.device_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка выполнения свайпа на {self.device_id}: {e}")
            return False

    def screenshot(self):
        """
        Сделать скриншот экрана устройства

        Returns:
            PIL.Image: Объект изображения или None при ошибке
        """
        try:
            if not self.connected or self.device is None:
                logger.error("Устройство не подключено")
                return None

            # Получаем скриншот
            png_data = self.device.screencap()

            if png_data:
                # Преобразуем в PIL Image
                image = Image.open(io.BytesIO(png_data))
                logger.debug(f"Скриншот получен с {self.device_id}, размер: {image.size}")
                return image
            else:
                logger.error(f"Не удалось получить скриншот с {self.device_id}")
                return None

        except Exception as e:
            logger.error(f"Ошибка получения скриншота с {self.device_id}: {e}")
            return None

    def get_device_info(self):
        """
        Получить информацию об устройстве

        Returns:
            dict: Словарь с информацией об устройстве
        """
        try:
            if not self.connected or self.device is None:
                return {"connected": False}

            info = {
                "connected": True,
                "device_id": self.device_id,
                "host": self.host,
                "port": self.port
            }

            # Получаем дополнительную информацию
            try:
                info["android_version"] = self.device.shell("getprop ro.build.version.release").strip()
                info["model"] = self.device.shell("getprop ro.product.model").strip()
                info["resolution"] = self.device.shell("wm size").strip()
            except:
                pass

            return info

        except Exception as e:
            logger.error(f"Ошибка получения информации об устройстве {self.device_id}: {e}")
            return {"connected": False, "error": str(e)}

    def start_app(self, package_name):
        """
        Запустить приложение по имени пакета

        Args:
            package_name (str): Имя пакета приложения

        Returns:
            bool: True если приложение запущено
        """
        try:
            if not self.connected or self.device is None:
                logger.error("Устройство не подключено")
                return False

            result = self.device.shell(f"monkey -p {package_name} 1")
            logger.info(f"Запуск приложения {package_name} на {self.device_id}")

            # Пауза для загрузки
            time.sleep(3)
            return True

        except Exception as e:
            logger.error(f"Ошибка запуска приложения {package_name} на {self.device_id}: {e}")
            return False

    def __enter__(self):
        """Контекстный менеджер - вход"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер - выход"""
        self.disconnect()


# Функция для быстрого тестирования
def test_adb_controller():
    """Тестовая функция для проверки работы ADBController"""
    logger.info("Начинаем тест ADBController")

    # Создаём папку для скриншотов если её нет
    os.makedirs("screenshots", exist_ok=True)

    # Создаем контроллер для порта 5556 (LDPlayer-1)
    controller = ADBController(port=5556)

    # Тестируем подключение
    if controller.connect():
        logger.info("✓ Подключение успешно")

        # Получаем информацию об устройстве
        info = controller.get_device_info()
        logger.info(f"Информация об устройстве: {info}")

        # Делаем скриншот
        screenshot = controller.screenshot()
        if screenshot:
            logger.info(f"✓ Скриншот получен, размер: {screenshot.size}")

            # Сохраняем скриншот для проверки
            screenshot.save("screenshots/test_screenshot.png")
            logger.info("✓ Скриншот сохранён в screenshots/test_screenshot.png")
        else:
            logger.error("✗ Не удалось получить скриншот")

        # Отключаемся
        controller.disconnect()
        logger.info("✓ Отключение успешно")
    else:
        logger.error("✗ Не удалось подключиться")


if __name__ == "__main__":
    test_adb_controller()