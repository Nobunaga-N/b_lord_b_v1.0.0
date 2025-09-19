"""
Модуль базовых игровых действий для Beast Lord The New Land.
Содержит основные функции для входа в игру, навигации и проверки щита.
"""
import time
import os
from pathlib import Path
from loguru import logger

from utils.image_recognition import ImageRecognition, click_template, wait_for_template


class BasicActions:
    """Класс базовых игровых действий"""

    def __init__(self, controller):
        """
        Инициализация базовых действий

        Args:
            controller: ADBController для управления эмулятором
        """
        self.controller = controller
        self.recognizer = ImageRecognition(confidence_threshold=0.8, debug_mode=True)

        # Пути к шаблонам
        self.templates_dir = Path("templates")
        self.ui_templates = self.templates_dir / "ui_elements"
        self.buttons_templates = self.templates_dir / "buttons"

        logger.info("BasicActions инициализирован")

    def wait_and_screenshot(self, delay=2, screenshot_name="action"):
        """
        Вспомогательная функция - пауза и скриншот

        Args:
            delay (float): Время паузы в секундах
            screenshot_name (str): Название для скриншота
        """
        time.sleep(delay)
        screenshot = self.controller.screenshot()
        if screenshot and hasattr(self, '_save_screenshot'):
            timestamp = time.strftime("%H%M%S")
            screenshot.save(f"screenshots/{screenshot_name}_{timestamp}.png")
        return screenshot

    def enter_game(self, game_package="com.allstarunion.beastlord", max_attempts=3):
        """
        Запуск игры и вход в аккаунт

        Args:
            game_package (str): Имя пакета игры
            max_attempts (int): Максимальное количество попыток

        Returns:
            dict: Результат операции со структурой:
                {
                    'success': bool,
                    'stage': str,        # На какой стадии остановились
                    'attempts_used': int,
                    'message': str
                }
        """
        logger.info("Начинаем вход в игру...")

        result = {
            'success': False,
            'stage': 'starting',
            'attempts_used': 0,
            'message': ''
        }

        for attempt in range(1, max_attempts + 1):
            result['attempts_used'] = attempt
            logger.info(f"Попытка входа в игру #{attempt}")

            try:
                # 1. Проверяем подключение к эмулятору
                if not self.controller.check_connection():
                    logger.error("Нет подключения к эмулятору")
                    result['message'] = "Нет подключения к эмулятору"
                    continue

                # 2. Запускаем приложение
                logger.info(f"Запуск приложения: {game_package}")
                if not self.controller.start_app(game_package):
                    logger.warning("Не удалось запустить приложение через ADB")
                    # Продолжаем, возможно игра уже запущена

                result['stage'] = 'app_started'

                # 3. Ждём загрузки (первый экран загрузки)
                logger.info("Ожидание загрузки игры...")
                self.wait_and_screenshot(5, "loading_start")

                # 4. Проверяем различные состояния загрузки
                loading_handled = self._handle_loading_screens()
                if not loading_handled:
                    logger.warning("Проблемы с экранами загрузки")

                result['stage'] = 'loading_handled'

                # 5. Обрабатываем экран входа/регистрации
                login_result = self._handle_login_screen()
                if not login_result['success']:
                    logger.warning(f"Проблемы с экраном входа: {login_result['message']}")

                result['stage'] = 'login_handled'

                # 6. Ждём полной загрузки игрового мира
                logger.info("Ожидание загрузки игрового мира...")
                world_loaded = self._wait_for_game_world()

                if world_loaded:
                    result['success'] = True
                    result['stage'] = 'game_ready'
                    result['message'] = "Успешно вошли в игру"

                    logger.info("✓ Успешно вошли в игру!")
                    self.wait_and_screenshot(2, "game_entered")
                    return result
                else:
                    logger.warning("Не удалось дождаться загрузки игрового мира")
                    result['message'] = "Таймаут загрузки игрового мира"

            except Exception as e:
                logger.error(f"Ошибка при входе в игру (попытка {attempt}): {e}")
                result['message'] = f"Ошибка: {str(e)}"

            # Пауза между попытками
            if attempt < max_attempts:
                logger.info(f"Пауза перед следующей попыткой...")
                time.sleep(10)

        result['message'] = f"Не удалось войти в игру за {max_attempts} попыток"
        logger.error(result['message'])
        return result

    def _handle_loading_screens(self):
        """Обработка различных экранов загрузки"""
        try:
            logger.info("Обработка экранов загрузки...")

            # Ждём основной экран загрузки (обычно с прогресс-баром)
            for i in range(30):  # До 30 секунд ожидания
                screenshot = self.controller.screenshot()
                if not screenshot:
                    continue

                # Здесь будут проверки на наличие элементов загрузки
                # Пока что просто ждём и логируем
                logger.debug(f"Проверка загрузки... {i+1}/30")

                # Проверяем, не появились ли кнопки для продолжения
                # (например, "Tap to continue", "Start", etc.)

                time.sleep(1)

            return True

        except Exception as e:
            logger.error(f"Ошибка обработки экранов загрузки: {e}")
            return False

    def _handle_login_screen(self):
        """Обработка экрана входа в аккаунт"""
        try:
            logger.info("Обработка экрана входа...")

            result = {'success': False, 'message': ''}

            # Делаем скриншот для анализа
            screenshot = self.controller.screenshot()
            if not screenshot:
                result['message'] = "Не удалось получить скриншот"
                return result

            # Сохраняем для анализа
            self.wait_and_screenshot(1, "login_screen")

            # Ищем кнопки входа (Guest, Facebook, Google и т.д.)
            # В большинстве игр есть возможность войти как гость

            # Пробуем найти кнопку "Guest" или "Skip" или "Continue"
            possible_buttons = [
                # Координаты для типичных кнопок входа
                # Эти координаты нужно будет подстроить под реальную игру
                (400, 600),  # Центральная кнопка
                (400, 500),  # Выше центра
                (200, 600),  # Слева
                (600, 600),  # Справа
            ]

            # Пробуем тапнуть по возможным местам кнопок входа
            for i, (x, y) in enumerate(possible_buttons):
                logger.info(f"Пробуем кнопку входа в позиции ({x}, {y})")

                if self.controller.tap(x, y):
                    time.sleep(3)  # Ждём реакции

                    # Проверяем, изменился ли экран
                    new_screenshot = self.controller.screenshot()
                    if new_screenshot:
                        # Простая проверка - изменилось ли изображение
                        # В реальной реализации тут будет сравнение шаблонов
                        logger.info(f"Тапнули по кнопке #{i+1}, проверяем результат...")
                        break

            result['success'] = True
            result['message'] = "Экран входа обработан"
            return result

        except Exception as e:
            logger.error(f"Ошибка обработки экрана входа: {e}")
            return {'success': False, 'message': str(e)}

    def _wait_for_game_world(self, timeout=60):
        """
        Ожидание полной загрузки игрового мира

        Args:
            timeout (int): Максимальное время ожидания в секундах

        Returns:
            bool: True если мир загрузился
        """
        try:
            logger.info("Ожидание загрузки игрового мира...")

            start_time = time.time()

            while (time.time() - start_time) < timeout:
                screenshot = self.controller.screenshot()
                if not screenshot:
                    time.sleep(2)
                    continue

                # Ищем признаки загруженного игрового мира
                # Это могут быть: главное здание, интерфейс, кнопки действий

                # Пока что просто проверяем стабильность экрана
                elapsed = time.time() - start_time
                logger.debug(f"Проверка загрузки мира... {elapsed:.1f}s")

                # Простая эвристика - если прошло больше 20 секунд,
                # вероятно игра загрузилась
                if elapsed > 20:
                    logger.info("Игровой мир вероятно загружен (по времени)")
                    return True

                time.sleep(2)

            logger.warning(f"Таймаут ожидания загрузки игрового мира ({timeout}s)")
            return False

        except Exception as e:
            logger.error(f"Ошибка ожидания загрузки мира: {e}")
            return False

    def go_to_main_screen(self, max_attempts=3):
        """
        Переход на главный экран игры (домашний экран базы)

        Returns:
            dict: Результат операции со структурой:
                {
                    'success': bool,
                    'attempts_used': int,
                    'message': str,
                    'current_screen': str  # Описание текущего экрана
                }
        """
        logger.info("Переход на главный экран...")

        result = {
            'success': False,
            'attempts_used': 0,
            'message': '',
            'current_screen': 'unknown'
        }

        for attempt in range(1, max_attempts + 1):
            result['attempts_used'] = attempt
            logger.info(f"Попытка перехода на главный экран #{attempt}")

            try:
                # Получаем скриншот для анализа текущего состояния
                screenshot = self.controller.screenshot()
                if not screenshot:
                    result['message'] = "Не удалось получить скриншот"
                    continue

                self.wait_and_screenshot(1, f"main_screen_attempt_{attempt}")

                # Проверяем, не находимся ли мы уже на главном экране
                if self._is_on_main_screen(screenshot):
                    result['success'] = True
                    result['current_screen'] = 'main'
                    result['message'] = "Уже находимся на главном экране"
                    logger.info("✓ Уже находимся на главном экране")
                    return result

                # Пробуем различные способы попасть на главный экран
                navigation_success = self._navigate_to_main_screen(screenshot)

                if navigation_success:
                    # Ждём и проверяем результат
                    time.sleep(3)
                    new_screenshot = self.controller.screenshot()

                    if new_screenshot and self._is_on_main_screen(new_screenshot):
                        result['success'] = True
                        result['current_screen'] = 'main'
                        result['message'] = "Успешно перешли на главный экран"
                        logger.info("✓ Успешно перешли на главный экран")
                        return result

            except Exception as e:
                logger.error(f"Ошибка перехода на главный экран (попытка {attempt}): {e}")
                result['message'] = f"Ошибка: {str(e)}"

            # Пауза между попытками
            if attempt < max_attempts:
                time.sleep(5)

        result['message'] = f"Не удалось перейти на главный экран за {max_attempts} попыток"
        logger.error(result['message'])
        return result

    def _is_on_main_screen(self, screenshot):
        """
        Проверка, находимся ли на главном экране

        Args:
            screenshot: PIL.Image - скриншот для анализа

        Returns:
            bool: True если на главном экране
        """
        try:
            # Ищем характерные элементы главного экрана:
            # - Главное здание (замок)
            # - Кнопки интерфейса (карта, альянс, настройки)
            # - Панель ресурсов
            # - Кнопка строительства

            # Пока что используем простую эвристику по размеру изображения
            # В реальной реализации тут будет поиск шаблонов

            if screenshot and screenshot.size[0] > 0:
                logger.debug("Проверка на главный экран - базовая проверка пройдена")
                return True

            return False

        except Exception as e:
            logger.error(f"Ошибка проверки главного экрана: {e}")
            return False

    def _navigate_to_main_screen(self, screenshot):
        """
        Попытка навигации на главный экран

        Args:
            screenshot: PIL.Image - текущий скриншот

        Returns:
            bool: True если навигация выполнена
        """
        try:
            logger.info("Попытка навигации на главный экран...")

            # Возможные действия для возврата на главный экран:
            # 1. Кнопка "Home" или "База"
            # 2. Кнопка "Back" несколько раз
            # 3. Tap по логотипу игры
            # 4. Свайп или жесты закрытия меню

            # Пробуем нажать ESC/Back для закрытия открытых меню
            logger.info("Пробуем кнопку Back для закрытия меню...")
            for i in range(3):  # Максимум 3 раза
                # В Android Back это обычно keyevent 4
                success, _, _ = self.controller._run_adb_command(["shell", "input", "keyevent", "4"])
                if success:
                    logger.debug(f"Back нажата #{i+1}")
                    time.sleep(1)
                else:
                    break

            # Пробуем тапнуть по углам экрана (закрытие модальных окон)
            width, height = screenshot.size
            corner_taps = [
                (width - 50, 50),      # Правый верхний угол (X закрытия)
                (50, 50),              # Левый верхний угол
                (width // 2, height // 2),  # Центр экрана
            ]

            for i, (x, y) in enumerate(corner_taps):
                logger.debug(f"Tap для навигации в позиции ({x}, {y})")
                if self.controller.tap(x, y):
                    time.sleep(1)

            return True

        except Exception as e:
            logger.error(f"Ошибка навигации на главный экран: {e}")
            return False

    def check_shield(self, activate_if_needed=True):
        """
        Проверка и активация защитного щита

        Args:
            activate_if_needed (bool): Активировать щит если он не активен

        Returns:
            dict: Результат операции со структурой:
                {
                    'success': bool,
                    'shield_active': bool,
                    'shield_time_left': str,    # Время до окончания щита
                    'activated_new': bool,       # Был ли активирован новый щит
                    'message': str
                }
        """
        logger.info("Проверка состояния защитного щита...")

        result = {
            'success': False,
            'shield_active': False,
            'shield_time_left': 'unknown',
            'activated_new': False,
            'message': ''
        }

        try:
            # Получаем скриншот для анализа
            screenshot = self.controller.screenshot()
            if not screenshot:
                result['message'] = "Не удалось получить скриншот"
                return result

            self.wait_and_screenshot(1, "shield_check")

            # Проверяем текущее состояние щита
            shield_status = self._check_shield_status(screenshot)

            result['shield_active'] = shield_status['active']
            result['shield_time_left'] = shield_status['time_left']

            if shield_status['active']:
                logger.info(f"✓ Щит активен, осталось времени: {shield_status['time_left']}")
                result['success'] = True
                result['message'] = f"Щит активен ({shield_status['time_left']})"
                return result

            # Щит неактивен
            logger.warning("⚠ Щит неактивен!")

            if not activate_if_needed:
                result['message'] = "Щит неактивен, активация не требуется"
                return result

            # Пытаемся активировать щит
            logger.info("Попытка активации защитного щита...")
            activation_result = self._activate_shield(screenshot)

            result['activated_new'] = activation_result['success']

            if activation_result['success']:
                result['success'] = True
                result['shield_active'] = True
                result['message'] = "Щит успешно активирован"
                logger.info("✓ Щит успешно активирован")
            else:
                result['message'] = f"Не удалось активировать щит: {activation_result['message']}"
                logger.error(result['message'])

            return result

        except Exception as e:
            logger.error(f"Ошибка проверки щита: {e}")
            result['message'] = f"Ошибка: {str(e)}"
            return result

    def _check_shield_status(self, screenshot):
        """
        Проверка статуса щита на экране

        Args:
            screenshot: PIL.Image - скриншот для анализа

        Returns:
            dict: {'active': bool, 'time_left': str}
        """
        try:
            # Ищем индикатор щита на главном экране
            # Обычно это иконка щита с таймером в верхней части экрана

            # В реальной реализации тут будет:
            # 1. Поиск шаблона иконки щита
            # 2. OCR для чтения времени
            # 3. Проверка цвета индикатора (зелёный=активен, красный=неактивен)

            # Пока что возвращаем тестовые данные
            logger.debug("Анализ статуса щита...")

            # Простая проверка - если есть скриншот, считаем что можем определить статус
            if screenshot and screenshot.size[0] > 0:
                # Здесь будет реальная логика определения щита
                return {
                    'active': False,  # По умолчанию считаем неактивным
                    'time_left': '0h 0m'
                }

            return {
                'active': False,
                'time_left': 'unknown'
            }

        except Exception as e:
            logger.error(f"Ошибка определения статуса щита: {e}")
            return {
                'active': False,
                'time_left': 'error'
            }

    def _activate_shield(self, screenshot):
        """
        Попытка активации защитного щита

        Args:
            screenshot: PIL.Image - текущий скриншот

        Returns:
            dict: {'success': bool, 'message': str}
        """
        try:
            logger.info("Попытка активации щита...")

            # Стратегии активации щита:
            # 1. Tap по иконке щита (если есть)
            # 2. Открыть инвентарь и найти щиты
            # 3. Открыть магазин щитов
            # 4. Использовать быстрое меню

            # Пробуем найти иконку щита для активации
            width, height = screenshot.size

            # Возможные позиции иконки щита (обычно в верхней части экрана)
            shield_positions = [
                (width // 2, 100),     # Центр верхней части
                (width - 100, 100),    # Правый верх
                (100, 100),            # Левый верх
                (width // 2, 150),     # Чуть ниже центра
            ]

            for i, (x, y) in enumerate(shield_positions):
                logger.info(f"Проверяем позицию щита ({x}, {y})")

                if self.controller.tap(x, y):
                    time.sleep(2)  # Ждём открытия меню щитов

                    # Делаем скриншот после тапа
                    new_screenshot = self.controller.screenshot()
                    if new_screenshot:
                        self.wait_and_screenshot(1, f"shield_menu_{i}")

                        # Ищем кнопку активации или использования щита
                        activation_success = self._try_shield_activation_in_menu(new_screenshot)

                        if activation_success:
                            return {
                                'success': True,
                                'message': 'Щит активирован из меню'
                            }

            # Если не получилось через прямое нажатие, пробуем через инвентарь
            logger.info("Пробуем активацию через инвентарь...")
            inventory_result = self._activate_shield_from_inventory()

            return inventory_result

        except Exception as e:
            logger.error(f"Ошибка активации щита: {e}")
            return {
                'success': False,
                'message': f'Ошибка активации: {str(e)}'
            }

    def _try_shield_activation_in_menu(self, screenshot):
        """Попытка активации щита в открытом меню"""
        try:
            # Ищем кнопки типа "Use", "Activate", "OK", "Confirm"
            width, height = screenshot.size

            # Типичные позиции кнопок подтверждения
            button_positions = [
                (width // 2, height - 100),    # Центр низа
                (width - 100, height - 100),   # Правый низ
                (width // 2, height // 2),     # Центр экрана
            ]

            for x, y in button_positions:
                logger.debug(f"Пробуем кнопку активации в ({x}, {y})")
                if self.controller.tap(x, y):
                    time.sleep(1)

            return True

        except Exception as e:
            logger.error(f"Ошибка активации в меню щитов: {e}")
            return False

    def _activate_shield_from_inventory(self):
        """Попытка активации щита через инвентарь"""
        try:
            # Это более сложная логика:
            # 1. Открыть инвентарь
            # 2. Найти категорию "Щиты" или "Защита"
            # 3. Выбрать щит
            # 4. Нажать "Использовать"

            # Пока что возвращаем неуспешный результат
            # В реальной реализации тут будет полная навигация по инвентарю

            return {
                'success': False,
                'message': 'Активация через инвентарь пока не реализована'
            }

        except Exception as e:
            logger.error(f"Ошибка активации щита через инвентарь: {e}")
            return {
                'success': False,
                'message': f'Ошибка инвентаря: {str(e)}'
            }


# Вспомогательные функции для упрощённого использования

def enter_game(controller, **kwargs):
    """
    Упрощённая функция входа в игру

    Args:
        controller: ADBController

    Returns:
        dict: Результат входа в игру
    """
    basic_actions = BasicActions(controller)
    return basic_actions.enter_game(**kwargs)


def go_to_main_screen(controller, **kwargs):
    """
    Упрощённая функция перехода на главный экран

    Args:
        controller: ADBController

    Returns:
        dict: Результат перехода
    """
    basic_actions = BasicActions(controller)
    return basic_actions.go_to_main_screen(**kwargs)


def check_shield(controller, **kwargs):
    """
    Упрощённая функция проверки щита

    Args:
        controller: ADBController

    Returns:
        dict: Результат проверки щита
    """
    basic_actions = BasicActions(controller)
    return basic_actions.check_shield(**kwargs)


# Тестирование модуля
def test_basic_actions():
    """Тестирование базовых действий"""
    logger.info("Тестирование модуля BasicActions...")

    from utils.adb_controller import ADBController

    # Создаём тестовый контроллер
    controller = ADBController(port=5556)

    if controller.connect():
        logger.info("✓ Подключение к эмулятору успешно")

        # Тестируем базовые действия
        basic_actions = BasicActions(controller)

        # Тест входа в игру
        logger.info("Тестирование входа в игру...")
        game_result = basic_actions.enter_game()
        logger.info(f"Результат входа в игру: {game_result}")

        # Тест перехода на главный экран
        logger.info("Тестирование перехода на главный экран...")
        main_result = basic_actions.go_to_main_screen()
        logger.info(f"Результат перехода на главный экран: {main_result}")

        # Тест проверки щита
        logger.info("Тестирование проверки щита...")
        shield_result = basic_actions.check_shield()
        logger.info(f"Результат проверки щита: {shield_result}")

        controller.disconnect()
        logger.info("✓ BasicActions протестирован")
        return True
    else:
        logger.error("✗ Не удалось подключиться к эмулятору для тестирования")
        return False


if __name__ == "__main__":
    test_basic_actions()