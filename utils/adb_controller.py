"""
Исправленный класс ADBController для управления эмулятором Android через ADB.
Использует subprocess для прямого вызова adb команд.
"""
import time
import io
import os
import subprocess
from PIL import Image
from loguru import logger


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
        self.device_id = device_id or f"emulator-{port}"
        self.connected = False

        # Путь к ADB (попробуем найти автоматически)
        self.adb_path = self._find_adb_path()

        logger.info(f"ADBController инициализирован для {self.device_id}")
        logger.info(f"Используется ADB: {self.adb_path}")

    def _find_adb_path(self):
        """Попытка найти путь к adb.exe"""
        # Стандартные пути для adb
        possible_paths = [
            "adb",  # Если adb в PATH
            "adb.exe",
            r"C:\Users\%USERNAME%\AppData\Local\Android\Sdk\platform-tools\adb.exe",
            r"C:\Android\platform-tools\adb.exe",
            # Путь LDPlayer
            r"C:\LDPlayer\LDPlayer4.0\adb.exe",
            r"C:\LDPlayer\LDPlayer9\adb.exe",
        ]

        for path in possible_paths:
            try:
                # Проверяем, работает ли команда
                result = subprocess.run([path, "version"],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return path
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        # Если не найден, используем просто "adb"
        logger.warning("ADB путь не найден, используется 'adb' из PATH")
        return "adb"

    def _run_adb_command(self, command, timeout=10, binary=False):
        """
        Выполнить ADB команду

        Args:
            command (list): Список аргументов команды
            timeout (int): Таймаут выполнения
            binary (bool): True для бинарных данных (скриншоты)

        Returns:
            tuple: (success, stdout, stderr)
        """
        try:
            full_command = [self.adb_path, "-s", self.device_id] + command

            result = subprocess.run(
                full_command,
                capture_output=True,
                text=not binary,  # Если binary=True, то text=False
                timeout=timeout
            )

            success = result.returncode == 0
            return success, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            logger.error(f"Таймаут выполнения команды: {command}")
            return False, b"" if binary else "", "Timeout"
        except Exception as e:
            logger.error(f"Ошибка выполнения команды {command}: {e}")
            return False, b"" if binary else "", str(e)

    def connect(self):
        """
        Подключение к ADB устройству

        Returns:
            bool: True если подключение успешно
        """
        try:
            # Сначала проверяем, что ADB сервер запущен
            success, stdout, stderr = self._run_adb_command(["start-server"])
            if not success:
                logger.warning(f"Не удалось запустить ADB сервер: {stderr}")

            # Проверяем, что устройство доступно
            if self.check_connection():
                self.connected = True
                logger.info(f"Успешно подключен к {self.device_id}")
                return True
            else:
                logger.error(f"Устройство {self.device_id} не найдено")

                # Показываем список доступных устройств
                success, stdout, stderr = self._run_adb_command(["devices"])
                if success:
                    logger.info(f"Доступные устройства:\n{stdout}")

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
            self.connected = False
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
            # Простая команда для проверки связи
            success, stdout, stderr = self._run_adb_command(["shell", "echo", "test"])

            return success and "test" in stdout

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
            if not self.connected:
                logger.error("Устройство не подключено")
                return False

            # Выполняем тап через input tap
            success, stdout, stderr = self._run_adb_command(["shell", "input", "tap", str(x), str(y)])

            if success:
                # Пауза для стабильности
                time.sleep(duration / 1000.0)
                logger.debug(f"Тап по координатам ({x}, {y}) на {self.device_id}")
                return True
            else:
                logger.error(f"Ошибка выполнения тапа: {stderr}")
                return False

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
            if not self.connected:
                logger.error("Устройство не подключено")
                return False

            # Выполняем свайп через input swipe
            success, stdout, stderr = self._run_adb_command([
                "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration)
            ])

            if success:
                # Пауза для завершения анимации
                time.sleep(duration / 1000.0 + 0.5)
                logger.debug(f"Свайп от ({x1}, {y1}) до ({x2}, {y2}) на {self.device_id}")
                return True
            else:
                logger.error(f"Ошибка выполнения свайпа: {stderr}")
                return False

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
            if not self.connected:
                logger.error("Устройство не подключено")
                return None

            # Получаем скриншот через screencap (бинарные данные)
            success, png_data, stderr = self._run_adb_command(["exec-out", "screencap", "-p"], binary=True)

            if success and png_data:
                # Преобразуем бинарные данные в PIL Image
                image = Image.open(io.BytesIO(png_data))
                logger.debug(f"Скриншот получен с {self.device_id}, размер: {image.size}")
                return image
            else:
                logger.error(f"Не удалось получить скриншот: {stderr}")

                # Пробуем альтернативный способ
                return self._screenshot_alternative()

        except Exception as e:
            logger.error(f"Ошибка получения скриншота с {self.device_id}: {e}")
            return self._screenshot_alternative()

    def _screenshot_alternative(self):
        """Альтернативный способ получения скриншота"""
        try:
            # Сохраняем скриншот на устройстве, затем скачиваем
            temp_path = "/sdcard/temp_screenshot.png"

            # Делаем скриншот на устройстве
            success1, _, stderr1 = self._run_adb_command(["shell", "screencap", "-p", temp_path])
            if not success1:
                logger.error(f"Не удалось сделать скриншот на устройстве: {stderr1}")
                return None

            # Скачиваем файл как бинарные данные
            success2, png_data, stderr2 = self._run_adb_command(["exec-out", "cat", temp_path], binary=True)
            if success2 and png_data:
                # Удаляем временный файл
                self._run_adb_command(["shell", "rm", temp_path])

                # Преобразуем в изображение
                image = Image.open(io.BytesIO(png_data))
                logger.debug(f"Альтернативный скриншот получен, размер: {image.size}")
                return image

            logger.error(f"Не удалось скачать скриншот: {stderr2}")
            return None

        except Exception as e:
            logger.error(f"Ошибка альтернативного скриншота: {e}")
            return None

    def get_device_info(self):
        """
        Получить информацию об устройстве

        Returns:
            dict: Словарь с информацией об устройстве
        """
        try:
            if not self.connected:
                return {"connected": False}

            info = {
                "connected": True,
                "device_id": self.device_id,
                "host": self.host,
                "port": self.port
            }

            # Получаем дополнительную информацию
            try:
                success, stdout, _ = self._run_adb_command(["shell", "getprop", "ro.build.version.release"])
                if success:
                    info["android_version"] = stdout.strip()

                success, stdout, _ = self._run_adb_command(["shell", "getprop", "ro.product.model"])
                if success:
                    info["model"] = stdout.strip()

                success, stdout, _ = self._run_adb_command(["shell", "wm", "size"])
                if success:
                    info["resolution"] = stdout.strip()
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
            if not self.connected:
                logger.error("Устройство не подключено")
                return False

            success, stdout, stderr = self._run_adb_command(["shell", "monkey", "-p", package_name, "1"])

            if success:
                logger.info(f"Запуск приложения {package_name} на {self.device_id}")
                # Пауза для загрузки
                time.sleep(3)
                return True
            else:
                logger.error(f"Ошибка запуска приложения: {stderr}")
                return False

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

    # Создаем контроллер для порта 5556 (ваш эмулятор)
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

            # Тестируем тап (безопасные координаты в центре экрана)
            width, height = screenshot.size
            center_x, center_y = width // 2, height // 2

            logger.info(f"Тестируем тап по центру экрана ({center_x}, {center_y})")
            if controller.tap(center_x, center_y):
                logger.info("✓ Тап выполнен успешно")
            else:
                logger.error("✗ Ошибка выполнения тапа")

        else:
            logger.error("✗ Не удалось получить скриншот")

        # Отключаемся
        controller.disconnect()
        logger.info("✓ Отключение успешно")

        return True
    else:
        logger.error("✗ Не удалось подключиться")
        return False


if __name__ == "__main__":
    test_adb_controller()