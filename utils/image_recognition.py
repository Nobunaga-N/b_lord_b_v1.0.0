"""
Модуль для распознавания изображений и поиска элементов интерфейса игры.
Использует OpenCV для поиска шаблонов на скриншотах.
"""
import time
import cv2
import numpy as np
from PIL import Image
from loguru import logger


class ImageRecognition:
    """Класс для работы с распознаванием изображений и шаблонов"""

    def __init__(self, confidence_threshold=0.8, debug_mode=False):
        """
        Инициализация модуля распознавания

        Args:
            confidence_threshold (float): Минимальная уверенность для совпадения (0-1)
            debug_mode (bool): Режим отладки для сохранения промежуточных результатов
        """
        self.confidence_threshold = confidence_threshold
        self.debug_mode = debug_mode

        logger.info(f"ImageRecognition инициализирован с порогом уверенности: {confidence_threshold}")

    def pil_to_cv2(self, pil_image):
        """
        Конвертация PIL изображения в OpenCV формат

        Args:
            pil_image: PIL.Image объект

        Returns:
            numpy.ndarray: Изображение в OpenCV формате (BGR)
        """
        # Конвертируем PIL в RGB, затем в numpy array
        rgb_image = np.array(pil_image.convert('RGB'))
        # OpenCV использует BGR, поэтому конвертируем RGB -> BGR
        bgr_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)
        return bgr_image

    def load_template(self, template_path):
        """
        Загрузка шаблона для поиска

        Args:
            template_path (str): Путь к файлу шаблона

        Returns:
            numpy.ndarray: Шаблон в формате OpenCV или None при ошибке
        """
        try:
            # Загружаем как PIL, затем конвертируем в OpenCV
            pil_template = Image.open(template_path)
            cv2_template = self.pil_to_cv2(pil_template)

            logger.debug(f"Шаблон загружен: {template_path}, размер: {cv2_template.shape}")
            return cv2_template

        except Exception as e:
            logger.error(f"Ошибка загрузки шаблона {template_path}: {e}")
            return None

    def find_template(self, screenshot, template, method=cv2.TM_CCOEFF_NORMED):
        """
        Поиск шаблона на скриншоте

        Args:
            screenshot: PIL.Image или путь к изображению
            template: numpy.ndarray или путь к шаблону
            method: Метод сравнения OpenCV (по умолчанию TM_CCOEFF_NORMED)

        Returns:
            dict: Результат поиска со структурой:
                {
                    'found': bool,
                    'confidence': float,
                    'location': (x, y),  # координаты верхнего левого угла
                    'center': (x, y),    # координаты центра
                    'size': (w, h)       # размер шаблона
                }
        """
        try:
            # Подготовка изображений
            if isinstance(screenshot, str):
                screenshot = Image.open(screenshot)

            if isinstance(screenshot, Image.Image):
                cv2_screenshot = self.pil_to_cv2(screenshot)
            else:
                cv2_screenshot = screenshot

            if isinstance(template, str):
                cv2_template = self.load_template(template)
                if cv2_template is None:
                    return self._empty_result()
            else:
                cv2_template = template

            # Выполняем поиск шаблона
            result = cv2.matchTemplate(cv2_screenshot, cv2_template, method)

            # Находим лучшее совпадение
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # Для большинства методов максимум означает лучшее совпадение
            if method in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED]:
                confidence = 1 - min_val
                match_location = min_loc
            else:
                confidence = max_val
                match_location = max_loc

            # Получаем размеры шаблона
            template_height, template_width = cv2_template.shape[:2]

            # Вычисляем центр найденного объекта
            center_x = match_location[0] + template_width // 2
            center_y = match_location[1] + template_height // 2

            # Проверяем, достаточна ли уверенность
            found = confidence >= self.confidence_threshold

            result_dict = {
                'found': found,
                'confidence': float(confidence),
                'location': match_location,
                'center': (center_x, center_y),
                'size': (template_width, template_height)
            }

            if found:
                logger.debug(f"✓ Шаблон найден с уверенностью {confidence:.3f} в позиции {match_location}")
            else:
                logger.debug(f"✗ Шаблон не найден (уверенность {confidence:.3f} < {self.confidence_threshold})")

            return result_dict

        except Exception as e:
            logger.error(f"Ошибка поиска шаблона: {e}")
            return self._empty_result()

    def click_template(self, screenshot, template, controller, click_offset=(0, 0)):
        """
        Поиск шаблона и клик по нему

        Args:
            screenshot: PIL.Image или путь к скриншоту
            template: numpy.ndarray или путь к шаблону
            controller: ADBController для выполнения клика
            click_offset: (x, y) смещение от центра для клика

        Returns:
            dict: Результат операции со структурой:
                {
                    'success': bool,
                    'found': bool,
                    'clicked': bool,
                    'confidence': float,
                    'click_position': (x, y)
                }
        """
        try:
            # Ищем шаблон
            search_result = self.find_template(screenshot, template)

            result = {
                'success': False,
                'found': search_result['found'],
                'clicked': False,
                'confidence': search_result['confidence'],
                'click_position': None
            }

            if not search_result['found']:
                logger.warning("Шаблон не найден для клика")
                return result

            # Вычисляем позицию для клика
            center_x, center_y = search_result['center']
            click_x = center_x + click_offset[0]
            click_y = center_y + click_offset[1]

            # Выполняем клик
            if controller.tap(click_x, click_y):
                result['success'] = True
                result['clicked'] = True
                result['click_position'] = (click_x, click_y)

                logger.info(f"✓ Клик выполнен по шаблону в позиции ({click_x}, {click_y})")
            else:
                logger.error("✗ Не удалось выполнить клик")

            return result

        except Exception as e:
            logger.error(f"Ошибка выполнения клика по шаблону: {e}")
            return {
                'success': False, 'found': False, 'clicked': False,
                'confidence': 0.0, 'click_position': None
            }

    def wait_for_template(self, controller, template, timeout=30, check_interval=2, take_new_screenshot=True):
        """
        Ожидание появления шаблона на экране с таймаутом

        Args:
            controller: ADBController для получения скриншотов
            template: numpy.ndarray или путь к шаблону
            timeout (int): Максимальное время ожидания в секундах
            check_interval (float): Интервал между проверками в секундах
            take_new_screenshot (bool): Делать новый скриншот на каждой итерации

        Returns:
            dict: Результат ожидания со структурой:
                {
                    'found': bool,
                    'elapsed_time': float,
                    'confidence': float,
                    'location': (x, y),
                    'center': (x, y)
                }
        """
        try:
            logger.info(f"Ожидание появления шаблона (таймаут: {timeout}s)...")

            start_time = time.time()
            screenshot = None

            while (time.time() - start_time) < timeout:
                # Получаем новый скриншот или используем предыдущий
                if take_new_screenshot or screenshot is None:
                    screenshot = controller.screenshot()
                    if not screenshot:
                        logger.warning("Не удалось получить скриншот для поиска")
                        time.sleep(check_interval)
                        continue

                # Ищем шаблон
                search_result = self.find_template(screenshot, template)

                if search_result['found']:
                    elapsed_time = time.time() - start_time
                    logger.info(f"✓ Шаблон найден за {elapsed_time:.1f} секунд")

                    result = search_result.copy()
                    result['elapsed_time'] = elapsed_time
                    return result

                # Пауза перед следующей проверкой
                time.sleep(check_interval)

                elapsed = time.time() - start_time
                logger.debug(f"Поиск... ({elapsed:.1f}s / {timeout}s)")

            # Таймаут истёк
            elapsed_time = time.time() - start_time
            logger.warning(f"✗ Таймаут ожидания шаблона ({elapsed_time:.1f}s)")

            return {
                'found': False,
                'elapsed_time': elapsed_time,
                'confidence': 0.0,
                'location': None,
                'center': None
            }

        except Exception as e:
            logger.error(f"Ошибка ожидания шаблона: {e}")
            return {
                'found': False,
                'elapsed_time': time.time() - start_time if 'start_time' in locals() else 0,
                'confidence': 0.0,
                'location': None,
                'center': None
            }

    def find_multiple_templates(self, screenshot, templates_dict, return_all=False):
        """
        Поиск нескольких шаблонов одновременно

        Args:
            screenshot: PIL.Image или путь к скриншоту
            templates_dict (dict): Словарь {'name': template_path_or_array}
            return_all (bool): Вернуть все найденные или только первый

        Returns:
            dict: Результаты поиска для каждого шаблона
        """
        try:
            results = {}

            for template_name, template in templates_dict.items():
                search_result = self.find_template(screenshot, template)
                search_result['template_name'] = template_name
                results[template_name] = search_result

                if search_result['found'] and not return_all:
                    # Возвращаем первый найденный, если return_all=False
                    logger.info(f"Найден шаблон: {template_name}")
                    return {template_name: search_result}

            found_count = sum(1 for r in results.values() if r['found'])
            logger.info(f"Найдено шаблонов: {found_count} из {len(templates_dict)}")

            return results

        except Exception as e:
            logger.error(f"Ошибка поиска множественных шаблонов: {e}")
            return {}

    def save_debug_image(self, screenshot, search_result, filename_suffix="debug"):
        """
        Сохранение отладочного изображения с выделенной областью

        Args:
            screenshot: PIL.Image
            search_result (dict): Результат поиска шаблона
            filename_suffix (str): Суффикс для имени файла
        """
        try:
            if not self.debug_mode:
                return

            if not search_result['found']:
                return

            import os
            from datetime import datetime

            # Конвертируем в OpenCV для рисования
            cv2_image = self.pil_to_cv2(screenshot)

            # Рисуем прямоугольник вокруг найденного объекта
            x, y = search_result['location']
            w, h = search_result['size']

            cv2.rectangle(cv2_image, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(cv2_image, search_result['center'], 5, (255, 0, 0), -1)

            # Сохраняем
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_{timestamp}_{filename_suffix}.png"
            filepath = os.path.join("screenshots", filename)

            cv2.imwrite(filepath, cv2_image)
            logger.debug(f"Отладочное изображение сохранено: {filepath}")

        except Exception as e:
            logger.error(f"Ошибка сохранения отладочного изображения: {e}")

    def _empty_result(self):
        """Возврат пустого результата при ошибках"""
        return {
            'found': False,
            'confidence': 0.0,
            'location': None,
            'center': None,
            'size': None
        }


# Вспомогательные функции для удобного использования

def find_template(screenshot, template, confidence_threshold=0.8):
    """
    Упрощённая функция поиска шаблона

    Args:
        screenshot: PIL.Image или путь к изображению
        template: путь к шаблону или OpenCV изображение
        confidence_threshold (float): Порог уверенности

    Returns:
        dict: Результат поиска
    """
    recognizer = ImageRecognition(confidence_threshold=confidence_threshold)
    return recognizer.find_template(screenshot, template)


def click_template(screenshot, template, controller, confidence_threshold=0.8, click_offset=(0, 0)):
    """
    Упрощённая функция поиска и клика по шаблону

    Args:
        screenshot: PIL.Image
        template: путь к шаблону
        controller: ADBController
        confidence_threshold (float): Порог уверенности
        click_offset (tuple): Смещение клика от центра

    Returns:
        dict: Результат операции
    """
    recognizer = ImageRecognition(confidence_threshold=confidence_threshold)
    return recognizer.click_template(screenshot, template, controller, click_offset)


def wait_for_template(controller, template, timeout=30, confidence_threshold=0.8):
    """
    Упрощённая функция ожидания шаблона

    Args:
        controller: ADBController
        template: путь к шаблону
        timeout (int): Таймаут в секундах
        confidence_threshold (float): Порог уверенности

    Returns:
        dict: Результат ожидания
    """
    recognizer = ImageRecognition(confidence_threshold=confidence_threshold)
    return recognizer.wait_for_template(controller, template, timeout)


# Тестовая функция
def test_image_recognition():
    """Тестирование модуля распознавания изображений"""
    logger.info("Тестирование ImageRecognition...")

    # Инициализация в debug режиме
    recognizer = ImageRecognition(confidence_threshold=0.7, debug_mode=True)

    # Создаём тестовый скриншот (для демонстрации)
    test_image = Image.new('RGB', (100, 100), color='red')

    logger.info("✓ ImageRecognition модуль готов к использованию")
    return True


if __name__ == "__main__":
    test_image_recognition()