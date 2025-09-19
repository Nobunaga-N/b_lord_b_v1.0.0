"""
КАРДИНАЛЬНО ОБНОВЛЕННЫЙ Оркестратор для управления параллельными процессами bot_worker.
НОВАЯ ВЕРСИЯ с полной интеграцией LDConsoleManager, ResourceMonitor и адаптивным управлением.

НОВЫЙ WORKFLOW:
1. Planning Phase - анализ системы и планирование батча
2. Startup Phase - запуск эмуляторов через LDConsoleManager
3. Readiness Phase - ожидание готовности ADB
4. Processing Phase - выполнение игровых действий через bot_worker
5. Shutdown Phase - корректная остановка эмуляторов

КЛЮЧЕВЫЕ УЛУЧШЕНИЯ:
- Полная интеграция с LDConsoleManager для управления жизненным циклом эмуляторов
- Интеграция с ResourceMonitor для адаптивного управления ресурсами
- Умное планирование батчей на основе загрузки системы
- Автоматическое масштабирование размера батчей
- Детальная отчетность и статистика
- Улучшенные CLI команды с расширенным функционалом
"""
import sys
import os
import time
import signal
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import click
import psutil
from loguru import logger

# Добавляем корневую папку в путь для импорта
sys.path.append(str(Path(__file__).parent))

from utils.emulator_discovery import EmulatorDiscovery
from utils.ldconsole_manager import LDConsoleManager
from utils.resource_monitor import ResourceMonitor

# Настройка логирования
logger.add("logs/orchestrator_v2_{time}.log", rotation="100 MB", level="INFO")


@dataclass
class BatchPlan:
    """План выполнения батча эмуляторов"""
    emulators: List[Dict]
    batch_size: int
    recommended_profile: str
    estimated_duration: int  # в секундах
    resource_allocation: Dict
    warnings: List[str]
    can_execute: bool


@dataclass
class BatchResults:
    """Результаты выполнения батча"""
    plan: BatchPlan
    startup_results: Dict
    readiness_results: Dict
    processing_results: Dict
    shutdown_results: Dict
    total_duration: float
    success_rate: float
    emulators_processed: int
    errors: List[str]


class SmartOrchestrator:
    """
    Умный оркестратор с полной интеграцией всех компонентов системы
    """

    def __init__(self):
        """Инициализация SmartOrchestrator"""
        logger.info("=== Инициализация SmartOrchestrator ===")

        # Основные компоненты системы
        self.discovery = EmulatorDiscovery()
        self.ldconsole_manager = None
        self.resource_monitor = None

        # Статистика и мониторинг
        self.session_stats = {
            'batches_executed': 0,
            'emulators_processed': 0,
            'total_errors': 0,
            'start_time': datetime.now(),
            'last_batch_time': None
        }

        # Флаги управления
        self.shutdown_requested = False
        self.emergency_shutdown = False

        logger.info("SmartOrchestrator инициализирован")

        # Инициализируем компоненты
        self._initialize_components()

    def _initialize_components(self):
        """Инициализация всех компонентов системы"""
        try:
            logger.info("Инициализация компонентов системы...")

            # 1. Инициализация LDConsoleManager
            try:
                self.ldconsole_manager = LDConsoleManager()
                health_check = self.ldconsole_manager.health_check()

                if health_check['healthy']:
                    logger.info("✅ LDConsoleManager инициализирован и готов к работе")
                else:
                    logger.error(f"❌ LDConsoleManager не готов: {health_check['issues']}")
                    raise Exception("LDConsoleManager не готов к работе")

            except Exception as e:
                logger.error(f"❌ Ошибка инициализации LDConsoleManager: {e}")
                raise

            # 2. Инициализация ResourceMonitor
            try:
                self.resource_monitor = ResourceMonitor()
                logger.info("✅ ResourceMonitor инициализирован")

            except Exception as e:
                logger.error(f"❌ Ошибка инициализации ResourceMonitor: {e}")
                raise

            # 3. Автообнаружение эмуляторов
            try:
                discovery_result = self.discovery.discover_and_save()
                if discovery_result['success']:
                    logger.info(f"✅ Автообнаружение: найдено {discovery_result['emulators_found']} эмуляторов")
                else:
                    logger.warning(f"⚠️ Проблемы с автообнаружением: {discovery_result['message']}")

            except Exception as e:
                logger.error(f"❌ Ошибка автообнаружения: {e}")
                # Не критично - продолжаем работу

            # 4. Настройка обработчиков сигналов для graceful shutdown
            self._setup_signal_handlers()

            logger.info("🎉 Все компоненты инициализированы успешно!")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка инициализации компонентов: {e}")
            raise

    def _setup_signal_handlers(self):
        """Настройка обработчиков сигналов для graceful shutdown"""

        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            logger.warning(f"🛑 Получен сигнал {signal_name} - инициируем graceful shutdown")
            self.shutdown_requested = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    # ===== НОВЫЙ WORKFLOW: 5 ФАЗ ОБРАБОТКИ БАТЧА =====

    def execute_smart_batch(self, profile_filter: Optional[str] = None,
                            max_emulators: Optional[int] = None) -> BatchResults:
        """
        ОСНОВНОЙ МЕТОД: Выполнение умного батча с 5-фазным workflow

        Args:
            profile_filter (str, optional): Фильтр по профилю эмуляторов
            max_emulators (int, optional): Максимальное количество эмуляторов

        Returns:
            BatchResults: Полные результаты выполнения батча
        """
        logger.info("🚀 === НАЧАЛО ВЫПОЛНЕНИЯ УМНОГО БАТЧА ===")
        batch_start_time = time.time()

        # Инициализация структуры результатов
        batch_results = BatchResults(
            plan=None,
            startup_results={},
            readiness_results={},
            processing_results={},
            shutdown_results={},
            total_duration=0.0,
            success_rate=0.0,
            emulators_processed=0,
            errors=[]
        )

        try:
            # === ФАЗА 1: ПЛАНИРОВАНИЕ ===
            logger.info("\n🎯 === ФАЗА 1: ПЛАНИРОВАНИЕ БАТЧА ===")

            plan = self._phase1_planning(profile_filter, max_emulators)
            batch_results.plan = plan

            if not plan.can_execute:
                logger.error("❌ Батч не может быть выполнен по результатам планирования")
                batch_results.errors.extend(plan.warnings)
                return batch_results

            logger.info(f"✅ План готов: {plan.batch_size} эмуляторов, профиль '{plan.recommended_profile}'")

            # === ФАЗА 2: ЗАПУСК ЭМУЛЯТОРОВ ===
            logger.info(f"\n🚀 === ФАЗА 2: ЗАПУСК {plan.batch_size} ЭМУЛЯТОРОВ ===")

            startup_results = self._phase2_startup(plan)
            batch_results.startup_results = startup_results

            if startup_results['started_successfully'] == 0:
                logger.error("❌ Ни одного эмулятора не запустилось - прерываем обработку")
                batch_results.errors.append("Не удалось запустить ни одного эмулятора")
                return batch_results

            logger.info(f"✅ Запущено эмуляторов: {startup_results['started_successfully']}/{plan.batch_size}")

            # === ФАЗА 3: ОЖИДАНИЕ ГОТОВНОСТИ ===
            logger.info(f"\n⏳ === ФАЗА 3: ОЖИДАНИЕ ГОТОВНОСТИ ADB ===")

            # Получаем индексы успешно запущенных эмуляторов
            started_emulator_indexes = [
                result['index'] for result in startup_results['results']
                if result['success'] and not result.get('already_running', False)
            ]

            readiness_results = self._phase3_readiness(started_emulator_indexes)
            batch_results.readiness_results = readiness_results

            ready_emulators = readiness_results['ready_emulators']
            if ready_emulators == 0:
                logger.error("❌ Ни одного эмулятора не готов к работе")
                batch_results.errors.append("Эмуляторы запустились, но ADB не готов")
                # Всё равно пробуем остановить то что запустили
                self._phase5_shutdown([emu['index'] for emu in plan.emulators])
                return batch_results

            logger.info(f"✅ Готово к работе эмуляторов: {ready_emulators}")

            # === ФАЗА 4: ОБРАБОТКА АККАУНТОВ ===
            logger.info(f"\n⚙️ === ФАЗА 4: ОБРАБОТКА ИГРОВЫХ АККАУНТОВ ===")

            # Получаем список готовых эмуляторов
            ready_emulator_data = []
            for result in readiness_results['results']:
                if result['ready']:
                    # Находим соответствующий эмулятор в плане
                    emulator_data = next(
                        (emu for emu in plan.emulators if emu['index'] == result['index']),
                        None
                    )
                    if emulator_data:
                        emulator_data['adb_port'] = result['adb_port']  # Обновляем ADB порт
                        ready_emulator_data.append(emulator_data)

            processing_results = self._phase4_processing(ready_emulator_data, plan)
            batch_results.processing_results = processing_results

            logger.info(f"✅ Обработано аккаунтов: {processing_results['processed_successfully']}")

            # === ФАЗА 5: ОСТАНОВКА ЭМУЛЯТОРОВ ===
            logger.info(f"\n🛑 === ФАЗА 5: ОСТАНОВКА ЭМУЛЯТОРОВ ===")

            # Останавливаем все эмуляторы из плана (те что запускали)
            emulator_indexes_to_stop = [emu['index'] for emu in plan.emulators]
            shutdown_results = self._phase5_shutdown(emulator_indexes_to_stop)
            batch_results.shutdown_results = shutdown_results

            logger.info(f"✅ Остановлено эмуляторов: {shutdown_results['stopped_successfully']}")

            # === ПОДСЧЕТ ФИНАЛЬНЫХ РЕЗУЛЬТАТОВ ===
            batch_results.total_duration = time.time() - batch_start_time
            batch_results.emulators_processed = processing_results.get('processed_successfully', 0)

            total_attempted = len(plan.emulators)
            if total_attempted > 0:
                batch_results.success_rate = (batch_results.emulators_processed / total_attempted) * 100
            else:
                batch_results.success_rate = 0.0

            # Обновляем статистику сессии
            self._update_session_stats(batch_results)

            logger.info(f"\n🎉 === БАТЧ ЗАВЕРШЕН ===")
            logger.info(f"⏱️ Общее время: {batch_results.total_duration:.1f} секунд")
            logger.info(
                f"📊 Обработано: {batch_results.emulators_processed}/{total_attempted} ({batch_results.success_rate:.1f}%)")

            return batch_results

        except Exception as e:
            logger.error(f"❌ Критическая ошибка выполнения батча: {e}")
            batch_results.errors.append(f"Критическая ошибка: {str(e)}")
            batch_results.total_duration = time.time() - batch_start_time
            return batch_results

        finally:
            # Логируем состояние системы после батча
            self._log_post_batch_system_state()

    def _phase1_planning(self, profile_filter: Optional[str], max_emulators: Optional[int]) -> BatchPlan:
        """
        ФАЗА 1: Планирование батча с анализом ресурсов и выбором эмуляторов
        """
        logger.info("🎯 Анализируем систему и планируем батч...")

        try:
            # 1. Получаем текущую загрузку системы
            system_load = self.resource_monitor.get_system_load()
            logger.info(
                f"💻 Система: CPU {system_load.cpu_percent:.1f}%, RAM {system_load.memory_percent:.1f}%, Нагрузка: {system_load.load_level}")

            # 2. Получаем список доступных эмуляторов
            available_emulators = self.discovery.get_enabled_emulators(
                profile_filter=profile_filter,
                running_only=False  # Включаем остановленные - мы их сами запустим
            )

            if not available_emulators:
                return BatchPlan(
                    emulators=[],
                    batch_size=0,
                    recommended_profile='farming',
                    estimated_duration=0,
                    resource_allocation={},
                    warnings=["Нет доступных эмуляторов для обработки"],
                    can_execute=False
                )

            logger.info(f"📱 Найдено доступных эмуляторов: {len(available_emulators)}")

            # 3. Определяем оптимальный профиль на основе системных ресурсов
            if not profile_filter:
                recommended_profile = self._determine_optimal_profile(system_load)
            else:
                recommended_profile = profile_filter

            logger.info(f"🎯 Рекомендуемый профиль: {recommended_profile}")

            # 4. Рассчитываем оптимальный размер батча
            optimal_batch_size = self.resource_monitor.get_optimal_batch_size(recommended_profile)

            # Применяем ограничение пользователя если задано
            if max_emulators:
                optimal_batch_size = min(optimal_batch_size, max_emulators)

            # Не можем обработать больше чем есть эмуляторов
            final_batch_size = min(optimal_batch_size, len(available_emulators))

            logger.info(f"📊 Размер батча: {final_batch_size} (оптимальный: {optimal_batch_size})")

            # 5. Выбираем эмуляторы для обработки (по приоритету)
            selected_emulators = available_emulators[:final_batch_size]

            # 6. Проверяем безопасность запуска
            safety_check = self.resource_monitor.is_safe_to_start_batch(
                batch_size=final_batch_size,
                profile=recommended_profile
            )

            warnings = safety_check.warnings.copy()
            can_execute = safety_check.safe_to_start

            if not can_execute:
                warnings.append("Система не готова к запуску батча")

            # 7. Рассчитываем оценку времени выполнения
            estimated_duration = self._estimate_batch_duration(final_batch_size, recommended_profile)

            # 8. Формируем план распределения ресурсов
            resource_allocation = {
                'total_cpu_cores': sum(self._get_cpu_requirement(recommended_profile) for _ in selected_emulators),
                'total_memory_mb': sum(self._get_memory_requirement(recommended_profile) for _ in selected_emulators),
                'profile_distribution': {recommended_profile: len(selected_emulators)}
            }

            plan = BatchPlan(
                emulators=selected_emulators,
                batch_size=final_batch_size,
                recommended_profile=recommended_profile,
                estimated_duration=estimated_duration,
                resource_allocation=resource_allocation,
                warnings=warnings,
                can_execute=can_execute
            )

            # Логируем план
            logger.info(f"📋 План батча сформирован:")
            logger.info(f"   🎮 Эмуляторы: {[emu['name'][:20] for emu in selected_emulators]}")
            logger.info(f"   ⚡ Профиль: {recommended_profile}")
            logger.info(f"   ⏱️ Время: ~{estimated_duration // 60} минут")
            logger.info(
                f"   💾 Ресурсы: CPU {resource_allocation['total_cpu_cores']} ядер, RAM {resource_allocation['total_memory_mb']} MB")
            logger.info(f"   ✅ Готов к выполнению: {'Да' if can_execute else 'Нет'}")

            if warnings:
                for warning in warnings:
                    logger.warning(f"   ⚠️ {warning}")

            return plan

        except Exception as e:
            logger.error(f"❌ Ошибка планирования батча: {e}")
            return BatchPlan(
                emulators=[],
                batch_size=0,
                recommended_profile='farming',
                estimated_duration=0,
                resource_allocation={},
                warnings=[f"Ошибка планирования: {str(e)}"],
                can_execute=False
            )

    def _phase2_startup(self, plan: BatchPlan) -> Dict:
        """
        ФАЗА 2: Запуск эмуляторов через LDConsoleManager
        """
        logger.info(f"🚀 Запускаем {plan.batch_size} эмуляторов...")

        try:
            # Применяем профили производительности перед запуском
            logger.info(f"⚙️ Применяем профиль производительности '{plan.recommended_profile}'...")

            emulator_indexes = [emu['index'] for emu in plan.emulators]

            # Применяем профиль к батчу (без перезапуска - эмуляторы ещё остановлены)
            profile_result = self.ldconsole_manager.apply_profile_to_batch(
                emulator_indexes=emulator_indexes,
                profile_name=plan.recommended_profile,
                restart_if_needed=False  # Эмуляторы остановлены, перезапуск не нужен
            )

            if profile_result['applied_successfully'] > 0:
                logger.info(f"✅ Профиль применён к {profile_result['applied_successfully']} эмуляторам")

            # Запускаем батч эмуляторов
            startup_result = self.ldconsole_manager.start_batch(
                emulator_indexes=emulator_indexes,
                max_parallel=3,  # Не более 3 одновременных запусков
                start_delay=5,  # 5 секунд между запусками
                timeout=90  # 90 секунд таймаут для каждого
            )

            return startup_result

        except Exception as e:
            logger.error(f"❌ Ошибка фазы запуска: {e}")
            return {
                'success': False,
                'started_successfully': 0,
                'already_running': 0,
                'failed': len(plan.emulators),
                'results': [],
                'error': str(e)
            }

    def _phase3_readiness(self, emulator_indexes: List[int]) -> Dict:
        """
        ФАЗА 3: Ожидание готовности ADB подключений
        """
        logger.info(f"⏳ Ожидаем готовности {len(emulator_indexes)} эмуляторов...")

        try:
            if not emulator_indexes:
                return {
                    'success': True,
                    'ready_emulators': 0,
                    'timeout_emulators': 0,
                    'failed_emulators': 0,
                    'results': []
                }

            # Ждём готовности батча с увеличенным таймаутом
            readiness_result = self.ldconsole_manager.wait_batch_ready(
                emulator_indexes=emulator_indexes,
                timeout=150,  # 2.5 минуты на готовность всех
                check_interval=5
            )

            return readiness_result

        except Exception as e:
            logger.error(f"❌ Ошибка фазы готовности: {e}")
            return {
                'success': False,
                'ready_emulators': 0,
                'timeout_emulators': len(emulator_indexes),
                'failed_emulators': 0,
                'results': [],
                'error': str(e)
            }

    def _phase4_processing(self, ready_emulators: List[Dict], plan: BatchPlan) -> Dict:
        """
        ФАЗА 4: Обработка игровых аккаунтов через bot_worker
        """
        logger.info(f"⚙️ Обрабатываем {len(ready_emulators)} готовых аккаунтов...")

        processing_results = {
            'processed_successfully': 0,
            'failed': 0,
            'results': [],
            'total_time': 0
        }

        if not ready_emulators:
            return processing_results

        start_time = time.time()

        try:
            # Используем ThreadPoolExecutor для параллельной обработки
            max_workers = min(3, len(ready_emulators))  # Не более 3 одновременно

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Создаём задачи для каждого эмулятора
                future_to_emulator = {}

                for emulator in ready_emulators:
                    future = executor.submit(self._process_single_emulator, emulator, plan)
                    future_to_emulator[future] = emulator

                # Собираем результаты
                for future in as_completed(future_to_emulator, timeout=1800):  # 30 минут общий таймаут
                    emulator = future_to_emulator[future]

                    try:
                        result = future.result(timeout=30)
                        result['emulator_name'] = emulator['name']
                        result['emulator_index'] = emulator['index']

                        processing_results['results'].append(result)

                        if result['success']:
                            processing_results['processed_successfully'] += 1
                            logger.info(
                                f"✅ Эмулятор {emulator['index']} ({emulator['name'][:20]}) обработан за {result['duration']:.1f}s")
                        else:
                            processing_results['failed'] += 1
                            logger.error(f"❌ Ошибка эмулятора {emulator['index']}: {result['error']}")

                    except Exception as e:
                        processing_results['failed'] += 1
                        processing_results['results'].append({
                            'emulator_name': emulator['name'],
                            'emulator_index': emulator['index'],
                            'success': False,
                            'duration': 0,
                            'error': f"Исключение обработки: {str(e)}"
                        })
                        logger.error(f"❌ Исключение при обработке эмулятора {emulator['index']}: {e}")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка фазы обработки: {e}")
            processing_results['error'] = str(e)

        finally:
            processing_results['total_time'] = time.time() - start_time

        return processing_results

    def _phase5_shutdown(self, emulator_indexes: List[int]) -> Dict:
        """
        ФАЗА 5: Корректная остановка эмуляторов
        """
        logger.info(f"🛑 Останавливаем {len(emulator_indexes)} эмуляторов...")

        try:
            if not emulator_indexes:
                return {
                    'success': True,
                    'stopped_successfully': 0,
                    'already_stopped': 0,
                    'failed': 0,
                    'results': []
                }

            # Останавливаем батч эмуляторов
            shutdown_result = self.ldconsole_manager.stop_batch(
                emulator_indexes=emulator_indexes,
                max_parallel=5,  # Можно останавливать быстрее чем запускать
                force=False,  # Сначала пробуем graceful
                timeout=30
            )

            # Если есть неудачи, пробуем принудительную остановку
            if shutdown_result['failed'] > 0:
                failed_indexes = [
                    result['index'] for result in shutdown_result['results']
                    if not result['success']
                ]

                if failed_indexes:
                    logger.warning(f"⚠️ Принудительно останавливаем {len(failed_indexes)} эмуляторов...")

                    force_shutdown = self.ldconsole_manager.stop_batch(
                        emulator_indexes=failed_indexes,
                        max_parallel=5,
                        force=True,  # Принудительная остановка
                        timeout=15
                    )

                    # Обновляем результаты
                    for force_result in force_shutdown['results']:
                        if force_result['success']:
                            # Находим соответствующий результат и обновляем его
                            for i, result in enumerate(shutdown_result['results']):
                                if result['index'] == force_result['index']:
                                    shutdown_result['results'][i] = force_result
                                    shutdown_result['stopped_successfully'] += 1
                                    shutdown_result['failed'] -= 1
                                    break

            return shutdown_result

        except Exception as e:
            logger.error(f"❌ Ошибка фазы остановки: {e}")
            return {
                'success': False,
                'stopped_successfully': 0,
                'already_stopped': 0,
                'failed': len(emulator_indexes),
                'results': [],
                'error': str(e)
            }

    def _process_single_emulator(self, emulator: Dict, plan: BatchPlan) -> Dict:
        """
        Обработка одного эмулятора через bot_worker
        """
        emulator_name = emulator['name']
        emulator_index = emulator['index']
        adb_port = emulator.get('adb_port')

        logger.info(f"🎮 Обрабатываем эмулятор {emulator_index} ({emulator_name[:30]})")

        start_time = time.time()

        try:
            # Проверяем что эмулятор всё ещё запущен и готов
            if not self.ldconsole_manager.is_running(emulator_index):
                return {
                    'success': False,
                    'duration': 0,
                    'error': 'Эмулятор неожиданно остановился'
                }

            # Запускаем bot_worker как subprocess
            cmd = [
                sys.executable, "bot_worker.py",
                "--emulator", emulator_name,
                "--port", str(adb_port)
            ]

            logger.debug(f"Команда bot_worker: {' '.join(cmd)}")

            # Запускаем с таймаутом
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900,  # 15 минут максимум на один эмулятор
                cwd=Path(__file__).parent
            )

            duration = time.time() - start_time
            success = process.returncode == 0

            if success:
                return {
                    'success': True,
                    'duration': duration,
                    'stdout': process.stdout,
                    'message': 'Обработка завершена успешно'
                }
            else:
                return {
                    'success': False,
                    'duration': duration,
                    'error': f'bot_worker завершился с кодом {process.returncode}',
                    'stderr': process.stderr[:500]  # Ограничиваем размер вывода
                }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return {
                'success': False,
                'duration': duration,
                'error': 'Таймаут выполнения bot_worker (15 минут)'
            }

        except Exception as e:
            duration = time.time() - start_time
            return {
                'success': False,
                'duration': duration,
                'error': f'Ошибка запуска bot_worker: {str(e)}'
            }

    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====

    def _determine_optimal_profile(self, system_load) -> str:
        """Определение оптимального профиля на основе загрузки системы"""
        if system_load.load_level == 'critical':
            return 'dormant'
        elif system_load.load_level == 'high':
            return 'farming'
        elif system_load.load_level == 'medium':
            return 'developing'
        else:  # low
            return 'rushing'

    def _get_cpu_requirement(self, profile: str) -> int:
        """Получение требования CPU для профиля"""
        requirements = {
            'rushing': 4, 'developing': 3, 'farming': 2,
            'dormant': 1, 'emergency': 4
        }
        return requirements.get(profile, 2)

    def _get_memory_requirement(self, profile: str) -> int:
        """Получение требования памяти для профиля (MB)"""
        requirements = {
            'rushing': 4096, 'developing': 3072, 'farming': 2048,
            'dormant': 1024, 'emergency': 4096
        }
        return requirements.get(profile, 2048)

    def _estimate_batch_duration(self, batch_size: int, profile: str) -> int:
        """Оценка времени выполнения батча в секундах"""
        # Базовое время на эмулятор по профилям
        base_times = {
            'rushing': 600,  # 10 минут - активная прокачка
            'developing': 360,  # 6 минут - сбалансированное развитие
            'farming': 180,  # 3 минуты - быстрый фарм
            'dormant': 120,  # 2 минуты - минимальные действия
            'emergency': 300  # 5 минут - экстренные задачи
        }

        base_time = base_times.get(profile, 300)

        # Добавляем время на запуск/остановку (фиксированное)
        startup_time = 120  # 2 минуты на запуск всего батча
        shutdown_time = 60  # 1 минута на остановку

        # Время обработки зависит от размера (параллельно, но с ограничениями)
        max_parallel = min(3, batch_size)
        processing_time = (batch_size / max_parallel) * base_time

        total_time = startup_time + processing_time + shutdown_time

        return int(total_time)

    def _update_session_stats(self, batch_results: BatchResults):
        """Обновление статистики сессии"""
        self.session_stats['batches_executed'] += 1
        self.session_stats['emulators_processed'] += batch_results.emulators_processed
        self.session_stats['total_errors'] += len(batch_results.errors)
        self.session_stats['last_batch_time'] = datetime.now()

        logger.info(f"📊 Статистика сессии: батчи {self.session_stats['batches_executed']}, "
                    f"эмуляторы {self.session_stats['emulators_processed']}, "
                    f"ошибки {self.session_stats['total_errors']}")

    def _log_post_batch_system_state(self):
        """Логирование состояния системы после батча"""
        try:
            system_load = self.resource_monitor.get_system_load()
            self.resource_monitor.log_system_state()

            logger.info(f"💻 Система после батча: CPU {system_load.cpu_percent:.1f}%, "
                        f"RAM {system_load.memory_percent:.1f}%, "
                        f"LDPlayer процессов {system_load.ldplayer_processes}")

            # Получаем рекомендации
            recommendations = self.resource_monitor.get_recommendations()
            for rec in recommendations[:3]:  # Показываем первые 3 рекомендации
                logger.info(f"💡 {rec}")

        except Exception as e:
            logger.error(f"Ошибка логирования состояния системы: {e}")

    # ===== МЕТОДЫ ДЛЯ ПРОДОЛЖИТЕЛЬНОЙ РАБОТЫ =====

    def run_continuous_mode(self, profile_filter: Optional[str] = None,
                            batch_interval: int = 3600, max_batches: Optional[int] = None):
        """
        Непрерывный режим работы с периодическим выполнением батчей

        Args:
            profile_filter (str, optional): Фильтр профиля эмуляторов
            batch_interval (int): Интервал между батчами в секундах
            max_batches (int, optional): Максимальное количество батчей
        """
        logger.info(f"🔄 Запуск непрерывного режима: интервал {batch_interval}s, фильтр '{profile_filter}'")

        batches_executed = 0

        try:
            while not self.shutdown_requested:
                # Проверяем лимит батчей
                if max_batches and batches_executed >= max_batches:
                    logger.info(f"✅ Достигнут лимит батчей: {max_batches}")
                    break

                # Проверяем экстренную остановку
                needs_emergency_shutdown, reasons = self.resource_monitor.emergency_shutdown_check()
                if needs_emergency_shutdown:
                    logger.critical(f"🚨 Экстренная остановка: {', '.join(reasons)}")
                    self.emergency_shutdown = True
                    break

                logger.info(f"\n🎯 === БАТЧ #{batches_executed + 1} ===")

                # Выполняем батч
                batch_results = self.execute_smart_batch(profile_filter=profile_filter)

                batches_executed += 1

                # Анализируем результаты
                if batch_results.success_rate < 50:
                    logger.warning(
                        f"⚠️ Низкий процент успеха ({batch_results.success_rate:.1f}%) - увеличиваем интервал")
                    sleep_time = batch_interval * 1.5
                else:
                    sleep_time = batch_interval

                # Пауза между батчами
                if batches_executed < max_batches or not max_batches:
                    logger.info(f"😴 Пауза {sleep_time / 60:.1f} минут до следующего батча...")

                    # Прерываемая пауза (проверяем shutdown каждые 30 секунд)
                    elapsed = 0
                    while elapsed < sleep_time and not self.shutdown_requested:
                        time.sleep(min(30, sleep_time - elapsed))
                        elapsed += 30

                        # Мини-проверка системы во время паузы
                        if elapsed % 300 == 0:  # Каждые 5 минут
                            system_load = self.resource_monitor.get_system_load()
                            logger.debug(
                                f"💻 Система в паузе: CPU {system_load.cpu_percent:.1f}%, RAM {system_load.memory_percent:.1f}%")

            logger.info(f"🏁 Непрерывный режим завершён: выполнено {batches_executed} батчей")

        except KeyboardInterrupt:
            logger.info("⏹️ Непрерывный режим прерван пользователем")
        except Exception as e:
            logger.error(f"❌ Ошибка непрерывного режима: {e}")

        finally:
            self._cleanup_after_session()

    def _cleanup_after_session(self):
        """Очистка после завершения сессии"""
        logger.info("🧹 Очистка после сессии...")

        try:
            # Останавливаем все запущенные эмуляторы
            all_emulators = self.ldconsole_manager.get_all_emulators_status()
            running_indexes = [
                index for index, info in all_emulators.items()
                if info['is_running']
            ]

            if running_indexes:
                logger.info(f"🛑 Останавливаем {len(running_indexes)} запущенных эмуляторов...")
                self.ldconsole_manager.stop_batch(running_indexes, force=True, timeout=30)

            # Очищаем старые логи
            self.resource_monitor.cleanup_old_records(days_to_keep=7)

            # Логируем финальную статистику
            session_duration = datetime.now() - self.session_stats['start_time']
            logger.info(f"📊 Финальная статистика сессии:")
            logger.info(f"   ⏱️ Длительность: {session_duration}")
            logger.info(f"   📦 Батчей выполнено: {self.session_stats['batches_executed']}")
            logger.info(f"   🎮 Эмуляторов обработано: {self.session_stats['emulators_processed']}")
            logger.info(f"   ❌ Всего ошибок: {self.session_stats['total_errors']}")

        except Exception as e:
            logger.error(f"❌ Ошибка очистки после сессии: {e}")

    def get_system_status(self) -> Dict:
        """Получение текущего статуса системы"""
        try:
            # Системные ресурсы
            system_load = self.resource_monitor.get_system_load()

            # Статус эмуляторов
            all_emulators = self.ldconsole_manager.get_all_emulators_status()
            enabled_emulators = self.discovery.get_enabled_emulators()

            running_count = sum(1 for info in all_emulators.values() if info['is_running'])

            # Health check компонентов
            ldconsole_health = self.ldconsole_manager.health_check()

            # Рекомендации
            recommendations = self.resource_monitor.get_recommendations()

            status = {
                'timestamp': datetime.now().isoformat(),
                'system': {
                    'cpu_percent': system_load.cpu_percent,
                    'memory_percent': system_load.memory_percent,
                    'memory_available_gb': system_load.memory_available_gb,
                    'load_level': system_load.load_level,
                    'ldplayer_processes': system_load.ldplayer_processes
                },
                'emulators': {
                    'total': len(all_emulators),
                    'running': running_count,
                    'enabled': len(enabled_emulators),
                    'available_for_batch': len(enabled_emulators)
                },
                'components': {
                    'ldconsole_healthy': ldconsole_health['healthy'],
                    'resource_monitor_active': True,
                    'discovery_ready': True
                },
                'session_stats': self.session_stats.copy(),
                'recommendations': recommendations[:5]  # Первые 5 рекомендаций
            }

            return status

        except Exception as e:
            logger.error(f"❌ Ошибка получения статуса системы: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


# ===== CLI КОМАНДЫ С РАСШИРЕННЫМ ФУНКЦИОНАЛОМ =====

@click.group()
@click.option('--debug', is_flag=True, help='Включить отладочный режим')
def cli(debug):
    """Beast Lord Smart Orchestrator v2 - Умное управление эмуляторами"""
    if debug:
        logger.add(sys.stdout, level="DEBUG")
        logger.info("🐛 Режим отладки включён")


@cli.command()
@click.option('--profile', help='Фильтр по профилю (rushing, developing, farming, dormant)')
@click.option('--max-emulators', type=int, help='Максимальное количество эмуляторов в батче')
@click.option('--dry-run', is_flag=True, help='Режим предпросмотра без реального выполнения')
def smart_batch(profile, max_emulators, dry_run):
    """Выполнить умный батч с 5-фазным workflow"""
    try:
        click.echo("🚀 === SMART ORCHESTRATOR V2 ===")

        # Инициализация
        orchestrator = SmartOrchestrator()

        if dry_run:
            click.echo("👁️ РЕЖИМ ПРЕДПРОСМОТРА (реальные действия не выполняются)")

            # Только планирование
            discovery = EmulatorDiscovery()
            discovery.load_config()
            resource_monitor = ResourceMonitor()

            # Имитируем планирование
            available_emulators = discovery.get_enabled_emulators(profile_filter=profile)
            system_load = resource_monitor.get_system_load()
            optimal_batch_size = resource_monitor.get_optimal_batch_size(profile or 'farming')

            if max_emulators:
                optimal_batch_size = min(optimal_batch_size, max_emulators)

            click.echo(f"\n📊 ПРЕДПРОСМОТР БАТЧА:")
            click.echo(
                f"  🖥️  Система: CPU {system_load.cpu_percent:.1f}%, RAM {system_load.memory_percent:.1f}%, Уровень: {system_load.load_level}")
            click.echo(f"  🎮 Доступно эмуляторов: {len(available_emulators)}")
            click.echo(f"  📦 Рекомендуемый размер батча: {optimal_batch_size}")
            click.echo(f"  ⚡ Профиль: {profile or 'auto-detect'}")

            safety_check = resource_monitor.is_safe_to_start_batch(optimal_batch_size, profile or 'farming')
            click.echo(f"  ✅ Безопасность запуска: {'Да' if safety_check.safe_to_start else 'Нет'}")

            if safety_check.warnings:
                click.echo("  ⚠️  Предупреждения:")
                for warning in safety_check.warnings:
                    click.echo(f"     • {warning}")

            return

        # Реальное выполнение
        results = orchestrator.execute_smart_batch(
            profile_filter=profile,
            max_emulators=max_emulators
        )

        # Отчёт о результатах
        click.echo(f"\n🎉 === РЕЗУЛЬТАТЫ ВЫПОЛНЕНИЯ ===")
        click.echo(f"⏱️  Общее время: {results.total_duration / 60:.1f} минут")
        click.echo(f"📊 Успешность: {results.success_rate:.1f}%")
        click.echo(f"🎮 Обработано эмуляторов: {results.emulators_processed}")

        if results.errors:
            click.echo("❌ Ошибки:")
            for error in results.errors[:5]:
                click.echo(f"   • {error}")

        if results.success_rate > 80:
            click.echo("✅ Батч выполнен успешно!")
        elif results.success_rate > 50:
            click.echo("⚠️ Батч выполнен с предупреждениями")
        else:
            click.echo("❌ Батч выполнен с ошибками")
            sys.exit(1)

    except KeyboardInterrupt:
        click.echo("\n⏹️ Выполнение прервано пользователем")
        sys.exit(130)
    except Exception as e:
        click.echo(f"❌ Ошибка выполнения: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--profile', help='Фильтр по профилю эмуляторов')
@click.option('--interval', type=int, default=3600,
              help='Интервал между батчами в секундах (по умолчанию: 3600 = 1 час)')
@click.option('--max-batches', type=int, help='Максимальное количество батчей (по умолчанию: бесконечно)')
def continuous(profile, interval, max_batches):
    """Непрерывный режим работы с периодическим выполнением батчей"""
    try:
        click.echo("🔄 === НЕПРЕРЫВНЫЙ РЕЖИМ ===")
        click.echo(f"⚙️ Интервал: {interval / 60:.1f} минут")
        click.echo(f"🎯 Профиль: {profile or 'auto-detect'}")
        if max_batches:
            click.echo(f"📦 Максимум батчей: {max_batches}")

        # Инициализация
        orchestrator = SmartOrchestrator()

        # Запуск непрерывного режима
        orchestrator.run_continuous_mode(
            profile_filter=profile,
            batch_interval=interval,
            max_batches=max_batches
        )

        click.echo("✅ Непрерывный режим завершён")

    except KeyboardInterrupt:
        click.echo("\n⏹️ Непрерывный режим остановлен")
        sys.exit(130)
    except Exception as e:
        click.echo(f"❌ Ошибка непрерывного режима: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--detailed', is_flag=True, help='Подробный статус')
def status(detailed):
    """Показать статус системы и эмуляторов"""
    try:
        orchestrator = SmartOrchestrator()
        status_data = orchestrator.get_system_status()

        if 'error' in status_data:
            click.echo(f"❌ Ошибка получения статуса: {status_data['error']}", err=True)
            return

        click.echo("📊 === СТАТУС СИСТЕМЫ ===")
        click.echo(f"🖥️  Система:")
        click.echo(f"   CPU: {status_data['system']['cpu_percent']:.1f}%")
        click.echo(
            f"   RAM: {status_data['system']['memory_percent']:.1f}% (свободно: {status_data['system']['memory_available_gb']:.1f} GB)")
        click.echo(f"   Уровень нагрузки: {status_data['system']['load_level']}")
        click.echo(f"   LDPlayer процессов: {status_data['system']['ldplayer_processes']}")

        click.echo(f"\n🎮 Эмуляторы:")
        click.echo(f"   Всего: {status_data['emulators']['total']}")
        click.echo(f"   Запущено: {status_data['emulators']['running']}")
        click.echo(f"   Включено: {status_data['emulators']['enabled']}")
        click.echo(f"   Доступно для батча: {status_data['emulators']['available_for_batch']}")

        click.echo(f"\n⚙️ Компоненты:")
        components = status_data['components']
        click.echo(f"   LDConsole: {'✅' if components['ldconsole_healthy'] else '❌'}")
        click.echo(f"   ResourceMonitor: {'✅' if components['resource_monitor_active'] else '❌'}")
        click.echo(f"   Discovery: {'✅' if components['discovery_ready'] else '❌'}")

        session_stats = status_data['session_stats']
        if session_stats['batches_executed'] > 0:
            click.echo(f"\n📊 Статистика сессии:")
            click.echo(f"   Батчей выполнено: {session_stats['batches_executed']}")
            click.echo(f"   Эмуляторов обработано: {session_stats['emulators_processed']}")
            click.echo(f"   Всего ошибок: {session_stats['total_errors']}")

        recommendations = status_data['recommendations']
        if recommendations:
            click.echo(f"\n💡 Рекомендации:")
            for rec in recommendations[:3]:
                click.echo(f"   {rec}")

        if detailed:
            # Показываем детальный статус эмуляторов
            discovery = EmulatorDiscovery()
            discovery.load_config()
            discovery.print_emulators_table(show_disabled=False)

    except Exception as e:
        click.echo(f"❌ Ошибка получения статуса: {e}", err=True)
        sys.exit(1)


# Добавляем старые CLI команды для обратной совместимости
@cli.command()
@click.option('--force', is_flag=True, help='Принудительное пересканирование')
def scan(force):
    """Сканировать эмуляторы LDPlayer"""
    try:
        # Используем старую логику из EmulatorDiscovery
        from orchestrator import cli as old_cli
        old_cli.commands['scan'].callback(force)
    except Exception as e:
        click.echo(f"❌ Ошибка сканирования: {e}", err=True)


@cli.command()
@click.option('--enabled-only', is_flag=True, help='Показать только включённые эмуляторы')
@click.option('--profile', help='Фильтр по профилю')
@click.option('--pattern', help='Фильтр по паттерну имени')
def list(enabled_only, profile, pattern):
    """Показать список эмуляторов"""
    try:
        # Используем старую логику
        from orchestrator import cli as old_cli
        old_cli.commands['list'].callback(enabled_only, profile, pattern)
    except Exception as e:
        click.echo(f"❌ Ошибка: {e}", err=True)


if __name__ == "__main__":
    # Если запускается напрямую, используем CLI
    cli()