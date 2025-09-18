"""
Основной исполнитель для работы с одним эмулятором.
Выполняет последовательность игровых действий для одного аккаунта.
"""
import sys
import os
import time
import argparse
from datetime import datetime
from pathlib import Path
from loguru import logger

# Добавляем корневую папку проекта в путь для импорта модулей
sys.path.append(str(Path(__file__).parent))

from utils.adb_controller import ADBController

# Настройка логирования
logger.add("logs/bot_worker_{time}.log", rotation="100 MB", level="INFO")


class BotWorker:
    """Основной класс исполнителя бота для одного эмулятора"""

    def __init__(self, emulator_name, adb_port=5556):
        """
        Инициализация bot worker

        Args:
            emulator_name (str): Имя эмулятора
            adb_port (int): Порт ADB для подключения
        """
        self.emulator_name = emulator_name
        self.adb_port = adb_port
        self.controller = None
        self.start_time = datetime.now()

        logger.info(f"BotWorker инициализирован для {emulator_name} на порту {adb_port}")

        # Создаём папки для скриншотов если их нет
        os.makedirs("screenshots", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

    def connect_to_emulator(self):
        """
        Подключение к эмулятору

        Returns:
            bool: True если подключение успешно
        """
        try:
            logger.info(f"Подключение к эмулятору {self.emulator_name}...")

            self.controller = ADBController(port=self.adb_port)

            if self.controller.connect():
                logger.info(f"✓ Успешное подключение к {self.emulator_name}")

                # Получаем информацию об устройстве
                device_info = self.controller.get_device_info()
                logger.info(f"Информация об устройстве: {device_info}")

                return True
            else:
                logger.error(f"✗ Не удалось подключиться к {self.emulator_name}")
                return False

        except Exception as e:
            logger.error(f"Ошибка подключения к {self.emulator_name}: {e}")
            return False

    def take_screenshot(self, filename_suffix=""):
        """
        Сделать и сохранить скриншот

        Args:
            filename_suffix (str): Суффикс для имени файла

        Returns:
            str: Путь к сохранённому скриншоту или None
        """
        try:
            if not self.controller or not self.controller.connected:
                logger.error("Контроллер не подключен")
                return None

            logger.info("Получение скриншота...")
            screenshot = self.controller.screenshot()

            if screenshot:
                # Создаём уникальное имя файла
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                if filename_suffix:
                    filename = f"screenshot_{self.emulator_name}_{timestamp}_{filename_suffix}.png"
                else:
                    filename = f"screenshot_{self.emulator_name}_{timestamp}.png"

                filepath = os.path.join("screenshots", filename)
                screenshot.save(filepath)

                logger.info(f"✓ Скриншот сохранён: {filepath}")
                logger.info(f"Размер изображения: {screenshot.size}")

                return filepath
            else:
                logger.error("✗ Не удалось получить скриншот")
                return None

        except Exception as e:
            logger.error(f"Ошибка при создании скриншота: {e}")
            return None

    def check_emulator_status(self):
        """
        Проверить статус эмулятора

        Returns:
            bool: True если эмулятор отвечает
        """
        try:
            if not self.controller:
                return False

            return self.controller.check_connection()

        except Exception as e:
            logger.error(f"Ошибка проверки статуса эмулятора: {e}")
            return False

    def basic_test_actions(self):
        """
        Выполнить базовые тестовые действия
        """
        try:
            logger.info("Выполнение базовых тестовых действий...")

            # 1. Первый скриншот для анализа экрана
            initial_screenshot = self.take_screenshot("initial")
            if not initial_screenshot:
                logger.error("Не удалось получить начальный скриншот")
                return False

            # 2. Пауза для анализа
            logger.info("Анализ текущего состояния экрана...")
            time.sleep(2)

            # 3. Тестовый тап по центру экрана (безопасное действие)
            logger.info("Выполнение тестового тапа...")
            screenshot = self.controller.screenshot()
            if screenshot:
                width, height = screenshot.size
                center_x, center_y = width // 2, height // 2

                logger.info(f"Тап по центру экрана ({center_x}, {center_y})")
                if self.controller.tap(center_x, center_y):
                    logger.info("✓ Тестовый тап выполнен")

                    # Пауза после тапа
                    time.sleep(3)

                    # Скриншот после тапа
                    self.take_screenshot("after_tap")
                else:
                    logger.error("✗ Ошибка выполнения тестового тапа")

            # 4. Финальный скриншот
            self.take_screenshot("final")

            logger.info("✓ Базовые тестовые действия завершены")
            return True

        except Exception as e:
            logger.error(f"Ошибка выполнения тестовых действий: {e}")
            return False

    def process_account(self):
        """
        Основной процесс обработки аккаунта

        Returns:
            bool: True если обработка прошла успешно
        """
        try:
            logger.info(f"Начало обработки аккаунта {self.emulator_name}")

            # 1. Подключение к эмулятору
            if not self.connect_to_emulator():
                return False

            # 2. Проверка статуса
            if not self.check_emulator_status():
                logger.error("Эмулятор не отвечает")
                return False

            # 3. Выполнение базовых действий
            success = self.basic_test_actions()

            # 4. Подсчёт времени выполнения
            duration = datetime.now() - self.start_time
            logger.info(f"Время выполнения: {duration.total_seconds():.1f} секунд")

            return success

        except Exception as e:
            logger.error(f"Критическая ошибка обработки аккаунта {self.emulator_name}: {e}")
            return False

        finally:
            # Всегда отключаемся от эмулятора
            self.disconnect()

    def disconnect(self):
        """Отключение от эмулятора"""
        try:
            if self.controller:
                self.controller.disconnect()
                logger.info(f"Отключение от {self.emulator_name}")
        except Exception as e:
            logger.error(f"Ошибка отключения от {self.emulator_name}: {e}")


def main():
    """Главная функция bot_worker"""
    parser = argparse.ArgumentParser(description="Bot Worker для Beast Lord")
    parser.add_argument("--emulator", "-e", default="LDPlayer",
                       help="Имя эмулятора (по умолчанию: LDPlayer)")
    parser.add_argument("--port", "-p", type=int, default=5556,
                       help="ADB порт (по умолчанию: 5556)")
    parser.add_argument("--test", "-t", action="store_true",
                       help="Запустить в тестовом режиме")

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Beast Lord Bot Worker запущен")
    logger.info(f"Эмулятор: {args.emulator}")
    logger.info(f"Порт: {args.port}")
    logger.info(f"Тестовый режим: {args.test}")
    logger.info("=" * 60)

    # Создание и запуск worker
    worker = BotWorker(args.emulator, args.port)

    try:
        success = worker.process_account()

        if success:
            logger.info("✓ Bot Worker завершён успешно")
            sys.exit(0)
        else:
            logger.error("✗ Bot Worker завершён с ошибками")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Bot Worker остановлен пользователем (Ctrl+C)")
        worker.disconnect()
        sys.exit(2)
    except Exception as e:
        logger.error(f"Необработанная ошибка: {e}")
        worker.disconnect()
        sys.exit(3)


if __name__ == "__main__":
    main()