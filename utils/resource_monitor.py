"""
Система мониторинга ресурсов для Beast Lord Bot.
Отслеживает загрузку CPU, RAM, диска и процессы LDPlayer для оптимального управления эмуляторами.
Интегрирован с LDConsoleManager и базой данных для адаптивного масштабирования.
"""
import time
import sqlite3
import psutil
import yaml
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class SystemLoad:
    """Структура данных о загрузке системы"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_available_gb: float
    disk_percent: float
    disk_free_gb: float
    ldplayer_processes: int
    ldplayer_memory_mb: float
    active_emulators: int
    load_level: str  # 'low', 'medium', 'high', 'critical'


@dataclass
class BatchRecommendation:
    """Рекомендации по батчевым операциям"""
    safe_to_start: bool
    optimal_batch_size: int
    max_batch_size: int
    recommended_profile: str
    warnings: List[str]
    actions_needed: List[str]


class ResourceMonitor:
    """Класс для мониторинга системных ресурсов и оптимизации работы эмуляторов"""

    def __init__(self, config_path="configs/ldconsole_settings.yaml", db_path="data/beast_lord.db"):
        """
        Инициализация системы мониторинга ресурсов

        Args:
            config_path (str): Путь к файлу конфигурации
            db_path (str): Путь к базе данных
        """
        self.config_path = Path(config_path)
        self.db_path = Path(db_path)

        # Кэш системных данных
        self.cache = {}
        self.cache_ttl = 30  # TTL кэша в секундах

        # Настройки по умолчанию
        self.default_thresholds = {
            'cpu_warning': 70,
            'cpu_critical': 85,
            'memory_warning': 75,
            'memory_critical': 90,
            'disk_warning': 85,
            'disk_critical': 95
        }

        # Загружаем конфигурацию
        self.config = self._load_config()
        self.thresholds = self._get_thresholds()

        # История измерений для трендового анализа
        self.history = []
        self.max_history_size = 100

        logger.info("ResourceMonitor инициализирован")
        logger.info(f"Пороги ресурсов: CPU {self.thresholds['cpu_warning']}/{self.thresholds['cpu_critical']}%, "
                    f"RAM {self.thresholds['memory_warning']}/{self.thresholds['memory_critical']}%")

        # Инициализируем базу данных
        self._init_database()

    def _load_config(self) -> Dict:
        """Загрузка конфигурации из YAML файла"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                logger.info(f"Конфигурация загружена из {self.config_path}")
                return config
            else:
                logger.warning(f"Файл конфигурации не найден: {self.config_path}")
                return {}
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            return {}

    def _get_thresholds(self) -> Dict:
        """Получение порогов ресурсов из конфигурации"""
        try:
            resource_thresholds = self.config.get('resource_thresholds', {})

            thresholds = {
                'cpu_warning': resource_thresholds.get('cpu_warning', self.default_thresholds['cpu_warning']),
                'cpu_critical': resource_thresholds.get('cpu_critical', self.default_thresholds['cpu_critical']),
                'memory_warning': resource_thresholds.get('memory_warning', self.default_thresholds['memory_warning']),
                'memory_critical': resource_thresholds.get('memory_critical',
                                                           self.default_thresholds['memory_critical']),
                'disk_warning': resource_thresholds.get('disk_warning', self.default_thresholds['disk_warning']),
                'disk_critical': resource_thresholds.get('disk_critical', self.default_thresholds['disk_critical'])
            }

            return thresholds
        except Exception as e:
            logger.error(f"Ошибка получения порогов из конфигурации: {e}")
            return self.default_thresholds

    def _init_database(self):
        """Инициализация таблиц базы данных"""
        try:
            # Создаём папку для БД если её нет
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(str(self.db_path)) as conn:
                # Создаём таблицу resource_usage если её нет
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS resource_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        total_cpu_percent REAL NOT NULL,
                        total_memory_percent REAL NOT NULL,
                        memory_available_gb REAL NOT NULL,
                        disk_percent REAL NOT NULL,
                        disk_free_gb REAL NOT NULL,
                        active_emulators INTEGER DEFAULT 0,
                        ldplayer_processes INTEGER DEFAULT 0,
                        ldplayer_memory_mb REAL DEFAULT 0,
                        system_load_level TEXT DEFAULT 'unknown'
                    )
                ''')

                # Создаём индекс по timestamp для быстрых запросов
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_resource_usage_timestamp 
                    ON resource_usage(timestamp)
                ''')

                conn.commit()
                logger.info("База данных инициализирована для мониторинга ресурсов")

        except Exception as e:
            logger.error(f"Ошибка инициализации базы данных: {e}")

    def get_system_load(self, use_cache=True) -> SystemLoad:
        """
        Получение текущей загрузки системы

        Args:
            use_cache (bool): Использовать кэш если данные свежие

        Returns:
            SystemLoad: Структура с данными о загрузке системы
        """
        try:
            # Проверяем кэш
            if use_cache and 'system_load' in self.cache:
                cached_data = self.cache['system_load']
                if (datetime.now() - cached_data['timestamp']).total_seconds() < self.cache_ttl:
                    logger.debug("Используем кэшированные данные о системе")
                    return cached_data['data']

            logger.debug("Получаем свежие данные о системе")

            # Получаем системные показатели
            cpu_percent = psutil.cpu_percent(interval=1)

            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_gb = memory.available / (1024 ** 3)

            disk = psutil.disk_usage('/')
            disk_percent = disk.used / disk.total * 100
            disk_free_gb = disk.free / (1024 ** 3)

            # Анализируем процессы LDPlayer
            ldplayer_info = self._analyze_ldplayer_processes()

            # Определяем уровень нагрузки
            load_level = self._determine_load_level(cpu_percent, memory_percent, disk_percent)

            # Создаём структуру данных
            system_load = SystemLoad(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_available_gb=memory_available_gb,
                disk_percent=disk_percent,
                disk_free_gb=disk_free_gb,
                ldplayer_processes=ldplayer_info['process_count'],
                ldplayer_memory_mb=ldplayer_info['total_memory_mb'],
                active_emulators=ldplayer_info['emulator_count'],
                load_level=load_level
            )

            # Сохраняем в кэш
            self.cache['system_load'] = {
                'timestamp': datetime.now(),
                'data': system_load
            }

            # Добавляем в историю для трендового анализа
            self._add_to_history(system_load)

            logger.debug(f"Загрузка системы: CPU {cpu_percent:.1f}%, RAM {memory_percent:.1f}%, "
                         f"Диск {disk_percent:.1f}%, LDPlayer процессов: {ldplayer_info['process_count']}, "
                         f"Уровень нагрузки: {load_level}")

            return system_load

        except Exception as e:
            logger.error(f"Ошибка получения загрузки системы: {e}")
            # Возвращаем загрузку по умолчанию при ошибке
            return SystemLoad(
                timestamp=datetime.now(),
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_available_gb=0.0,
                disk_percent=0.0,
                disk_free_gb=0.0,
                ldplayer_processes=0,
                ldplayer_memory_mb=0.0,
                active_emulators=0,
                load_level='unknown'
            )

    def _analyze_ldplayer_processes(self) -> Dict:
        """Анализ процессов LDPlayer в системе"""
        try:
            ldplayer_processes = []
            total_memory_mb = 0.0
            emulator_count = 0

            for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cmdline']):
                try:
                    name = proc.info['name'].lower()
                    if 'ldplayer' in name or 'ld9boxheadless' in name:
                        memory_mb = proc.info['memory_info'].rss / (1024 * 1024)
                        total_memory_mb += memory_mb

                        ldplayer_processes.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'memory_mb': memory_mb,
                            'cmdline': ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                        })

                        # Определяем эмуляторы (основные процессы, а не вспомогательные)
                        if 'ldplayer' in name and 'headless' not in name:
                            emulator_count += 1

                except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
                    continue

            logger.debug(f"Найдено LDPlayer процессов: {len(ldplayer_processes)}, "
                         f"эмуляторов: {emulator_count}, память: {total_memory_mb:.1f} MB")

            return {
                'process_count': len(ldplayer_processes),
                'emulator_count': emulator_count,
                'total_memory_mb': total_memory_mb,
                'processes': ldplayer_processes
            }

        except Exception as e:
            logger.error(f"Ошибка анализа процессов LDPlayer: {e}")
            return {
                'process_count': 0,
                'emulator_count': 0,
                'total_memory_mb': 0.0,
                'processes': []
            }

    def _determine_load_level(self, cpu_percent: float, memory_percent: float, disk_percent: float) -> str:
        """
        Определение уровня нагрузки системы

        Args:
            cpu_percent: Загрузка CPU в %
            memory_percent: Загрузка памяти в %
            disk_percent: Загрузка диска в %

        Returns:
            str: Уровень нагрузки ('low', 'medium', 'high', 'critical')
        """
        try:
            # Проверяем критический уровень
            if (cpu_percent >= self.thresholds['cpu_critical'] or
                    memory_percent >= self.thresholds['memory_critical'] or
                    disk_percent >= self.thresholds['disk_critical']):
                return 'critical'

            # Проверяем высокий уровень
            if (cpu_percent >= self.thresholds['cpu_warning'] or
                    memory_percent >= self.thresholds['memory_warning'] or
                    disk_percent >= self.thresholds['disk_warning']):
                return 'high'

            # Определяем средний и низкий уровни
            avg_load = (cpu_percent + memory_percent + disk_percent) / 3

            if avg_load > 50:
                return 'medium'
            else:
                return 'low'

        except Exception as e:
            logger.error(f"Ошибка определения уровня нагрузки: {e}")
            return 'unknown'

    def _add_to_history(self, system_load: SystemLoad):
        """Добавление измерения в историю для трендового анализа"""
        try:
            self.history.append(system_load)

            # Ограничиваем размер истории
            if len(self.history) > self.max_history_size:
                self.history.pop(0)

            logger.debug(f"Добавлено измерение в историю. Размер истории: {len(self.history)}")

        except Exception as e:
            logger.error(f"Ошибка добавления в историю: {e}")

    def is_safe_to_start_batch(self, batch_size: int = 1, profile: str = 'farming') -> BatchRecommendation:
        """
        Проверка безопасности запуска батча эмуляторов

        Args:
            batch_size (int): Размер планируемого батча
            profile (str): Профиль производительности эмуляторов

        Returns:
            BatchRecommendation: Рекомендации по батчевым операциям
        """
        logger.info(f"Проверка безопасности запуска батча: размер={batch_size}, профиль={profile}")

        try:
            # Получаем текущую загрузку системы
            system_load = self.get_system_load()

            warnings = []
            actions_needed = []
            safe_to_start = True
            recommended_profile = profile

            # Анализируем текущую нагрузку
            if system_load.load_level == 'critical':
                safe_to_start = False
                warnings.append(
                    f"Критическая нагрузка системы: CPU {system_load.cpu_percent:.1f}%, RAM {system_load.memory_percent:.1f}%")
                actions_needed.append("Остановить несрочные процессы")
                actions_needed.append("Снизить профили активных эмуляторов")

            elif system_load.load_level == 'high':
                warnings.append(
                    f"Высокая нагрузка системы: CPU {system_load.cpu_percent:.1f}%, RAM {system_load.memory_percent:.1f}%")

                # Рекомендуем более лёгкий профиль
                if profile == 'rushing':
                    recommended_profile = 'developing'
                    actions_needed.append("Снижен профиль с 'rushing' на 'developing'")
                elif profile == 'developing':
                    recommended_profile = 'farming'
                    actions_needed.append("Снижен профиль с 'developing' на 'farming'")

            # Проверяем доступную память
            min_memory_per_emulator = self._get_memory_requirement_by_profile(profile)
            total_memory_needed = min_memory_per_emulator * batch_size

            if system_load.memory_available_gb * 1024 < total_memory_needed:
                safe_to_start = False
                warnings.append(
                    f"Недостаточно памяти: нужно {total_memory_needed:.0f} MB, доступно {system_load.memory_available_gb * 1024:.0f} MB")
                actions_needed.append("Уменьшить размер батча или остановить процессы")

            # Проверяем тренды загрузки
            trend_analysis = self._analyze_trends()
            if trend_analysis['cpu_trend'] == 'increasing' and system_load.cpu_percent > 60:
                warnings.append("Загрузка CPU растёт - возможны проблемы")

            if trend_analysis['memory_trend'] == 'increasing' and system_load.memory_percent > 70:
                warnings.append("Потребление памяти растёт")

            # Определяем оптимальный размер батча
            optimal_batch_size = self.get_optimal_batch_size(profile)
            max_batch_size = self._get_max_safe_batch_size(system_load, profile)

            # Финальная проверка безопасности
            if batch_size > max_batch_size:
                safe_to_start = False
                warnings.append(
                    f"Запрашиваемый размер батча ({batch_size}) превышает максимально безопасный ({max_batch_size})")
                actions_needed.append(f"Уменьшить размер батча до {max_batch_size}")

            recommendation = BatchRecommendation(
                safe_to_start=safe_to_start,
                optimal_batch_size=optimal_batch_size,
                max_batch_size=max_batch_size,
                recommended_profile=recommended_profile,
                warnings=warnings,
                actions_needed=actions_needed
            )

            logger.info(f"Рекомендация по батчу: безопасно={safe_to_start}, оптимальный размер={optimal_batch_size}, "
                        f"рекомендуемый профиль={recommended_profile}")

            if warnings:
                for warning in warnings:
                    logger.warning(f"⚠️ {warning}")

            if actions_needed:
                for action in actions_needed:
                    logger.info(f"💡 Действие: {action}")

            return recommendation

        except Exception as e:
            logger.error(f"Ошибка проверки безопасности батча: {e}")
            # Возвращаем консервативную рекомендацию при ошибке
            return BatchRecommendation(
                safe_to_start=False,
                optimal_batch_size=1,
                max_batch_size=1,
                recommended_profile='farming',
                warnings=[f"Ошибка анализа: {str(e)}"],
                actions_needed=["Проверить систему мониторинга"]
            )

    def get_optimal_batch_size(self, profile: str = 'farming') -> int:
        """
        Расчёт оптимального размера батча на основе текущих ресурсов

        Args:
            profile (str): Профиль производительности

        Returns:
            int: Оптимальный размер батча
        """
        try:
            system_load = self.get_system_load()

            # Базовые размеры батчей по профилям
            base_batch_sizes = {
                'rushing': 2,
                'developing': 3,
                'farming': 5,
                'dormant': 8,
                'emergency': 1
            }

            base_size = base_batch_sizes.get(profile, 3)

            # Корректируем на основе загрузки системы
            if system_load.load_level == 'low':
                multiplier = 1.5
            elif system_load.load_level == 'medium':
                multiplier = 1.0
            elif system_load.load_level == 'high':
                multiplier = 0.6
            else:  # critical
                multiplier = 0.3

            optimal_size = int(base_size * multiplier)

            # Дополнительные ограничения по памяти
            memory_per_emulator = self._get_memory_requirement_by_profile(profile)
            max_by_memory = int(system_load.memory_available_gb * 1024 * 0.7 / memory_per_emulator)

            # Ограничения по активным эмуляторам
            current_emulators = system_load.active_emulators
            max_total_emulators = self._get_max_emulators_by_profile(profile)
            max_by_limit = max(0, max_total_emulators - current_emulators)

            # Берём минимум из всех ограничений
            final_size = max(1, min(optimal_size, max_by_memory, max_by_limit))

            logger.debug(f"Оптимальный размер батча для профиля '{profile}': {final_size} "
                         f"(базовый: {optimal_size}, по памяти: {max_by_memory}, по лимиту: {max_by_limit})")

            return final_size

        except Exception as e:
            logger.error(f"Ошибка расчёта оптимального размера батча: {e}")
            return 1  # Консервативное значение при ошибке

    def _get_memory_requirement_by_profile(self, profile: str) -> float:
        """Получение требований к памяти по профилю (в MB)"""
        memory_requirements = {
            'rushing': 4096,
            'developing': 3072,
            'farming': 2048,
            'dormant': 1024,
            'emergency': 4096
        }
        return memory_requirements.get(profile, 2048)

    def _get_max_emulators_by_profile(self, profile: str) -> int:
        """Максимальное количество эмуляторов для профиля"""
        max_emulators = {
            'rushing': 4,
            'developing': 6,
            'farming': 10,
            'dormant': 20,
            'emergency': 2
        }
        return max_emulators.get(profile, 5)

    def _get_max_safe_batch_size(self, system_load: SystemLoad, profile: str) -> int:
        """Максимальный безопасный размер батча"""
        try:
            if system_load.load_level == 'critical':
                return 0
            elif system_load.load_level == 'high':
                return 1
            elif system_load.load_level == 'medium':
                return 3
            else:  # low
                return self._get_max_emulators_by_profile(profile)

        except Exception as e:
            logger.error(f"Ошибка определения максимального размера батча: {e}")
            return 1

    def _analyze_trends(self) -> Dict:
        """Анализ трендов загрузки системы"""
        try:
            if len(self.history) < 5:
                return {
                    'cpu_trend': 'stable',
                    'memory_trend': 'stable',
                    'disk_trend': 'stable'
                }

            # Берём последние 10 измерений для анализа
            recent_history = self.history[-10:]

            # Анализируем тренды CPU
            cpu_values = [load.cpu_percent for load in recent_history]
            cpu_trend = self._calculate_trend(cpu_values)

            # Анализируем тренды памяти
            memory_values = [load.memory_percent for load in recent_history]
            memory_trend = self._calculate_trend(memory_values)

            # Анализируем тренды диска
            disk_values = [load.disk_percent for load in recent_history]
            disk_trend = self._calculate_trend(disk_values)

            return {
                'cpu_trend': cpu_trend,
                'memory_trend': memory_trend,
                'disk_trend': disk_trend
            }

        except Exception as e:
            logger.error(f"Ошибка анализа трендов: {e}")
            return {
                'cpu_trend': 'unknown',
                'memory_trend': 'unknown',
                'disk_trend': 'unknown'
            }

    def _calculate_trend(self, values: List[float]) -> str:
        """Расчёт тренда для списка значений"""
        try:
            if len(values) < 3:
                return 'stable'

            # Простой анализ тренда по первой и последней трети значений
            first_third = values[:len(values) // 3]
            last_third = values[-len(values) // 3:]

            first_avg = sum(first_third) / len(first_third)
            last_avg = sum(last_third) / len(last_third)

            diff_percent = (last_avg - first_avg) / first_avg * 100

            if diff_percent > 10:
                return 'increasing'
            elif diff_percent < -10:
                return 'decreasing'
            else:
                return 'stable'

        except Exception as e:
            logger.debug(f"Ошибка расчёта тренда: {e}")
            return 'stable'

    def log_system_state(self, additional_data: Optional[Dict] = None) -> bool:
        """
        Логирование текущего состояния системы в базу данных

        Args:
            additional_data (dict, optional): Дополнительные данные для логирования

        Returns:
            bool: True если логирование успешно
        """
        try:
            system_load = self.get_system_load()

            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute('''
                    INSERT INTO resource_usage (
                        timestamp, total_cpu_percent, total_memory_percent, 
                        memory_available_gb, disk_percent, disk_free_gb,
                        active_emulators, ldplayer_processes, ldplayer_memory_mb, 
                        system_load_level
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    system_load.timestamp,
                    system_load.cpu_percent,
                    system_load.memory_percent,
                    system_load.memory_available_gb,
                    system_load.disk_percent,
                    system_load.disk_free_gb,
                    system_load.active_emulators,
                    system_load.ldplayer_processes,
                    system_load.ldplayer_memory_mb,
                    system_load.load_level
                ))

                conn.commit()

            logger.debug(f"Состояние системы записано в БД: {system_load.load_level}, "
                         f"CPU {system_load.cpu_percent:.1f}%, RAM {system_load.memory_percent:.1f}%")

            return True

        except Exception as e:
            logger.error(f"Ошибка логирования состояния системы: {e}")
            return False

    def get_system_stats(self, hours_back: int = 1) -> Dict:
        """
        Получение статистики системы за определённый период

        Args:
            hours_back (int): Количество часов назад

        Returns:
            Dict: Статистика загрузки системы
        """
        try:
            cutoff_time = datetime.now() - timedelta(hours=hours_back)

            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM resource_usage 
                    WHERE timestamp >= ? 
                    ORDER BY timestamp DESC
                ''', (cutoff_time,))

                rows = cursor.fetchall()

            if not rows:
                return {'error': 'Нет данных за указанный период'}

            # Вычисляем статистику
            cpu_values = [row['total_cpu_percent'] for row in rows]
            memory_values = [row['total_memory_percent'] for row in rows]

            stats = {
                'period_hours': hours_back,
                'measurements_count': len(rows),
                'cpu': {
                    'avg': sum(cpu_values) / len(cpu_values),
                    'max': max(cpu_values),
                    'min': min(cpu_values)
                },
                'memory': {
                    'avg': sum(memory_values) / len(memory_values),
                    'max': max(memory_values),
                    'min': min(memory_values)
                },
                'load_levels': {}
            }

            # Подсчитываем распределение уровней нагрузки
            load_levels = [row['system_load_level'] for row in rows]
            for level in ['low', 'medium', 'high', 'critical']:
                count = load_levels.count(level)
                stats['load_levels'][level] = {
                    'count': count,
                    'percent': count / len(load_levels) * 100
                }

            logger.debug(f"Статистика за {hours_back}ч: {len(rows)} измерений, "
                         f"CPU {stats['cpu']['avg']:.1f}% (макс {stats['cpu']['max']:.1f}%), "
                         f"RAM {stats['memory']['avg']:.1f}% (макс {stats['memory']['max']:.1f}%)")

            return stats

        except Exception as e:
            logger.error(f"Ошибка получения статистики системы: {e}")
            return {'error': str(e)}

    def cleanup_old_records(self, days_to_keep: int = 7) -> int:
        """
        Очистка старых записей из базы данных

        Args:
            days_to_keep (int): Количество дней для хранения

        Returns:
            int: Количество удалённых записей
        """
        try:
            cutoff_time = datetime.now() - timedelta(days=days_to_keep)

            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute('''
                    DELETE FROM resource_usage 
                    WHERE timestamp < ?
                ''', (cutoff_time,))

                deleted_count = cursor.rowcount
                conn.commit()

            logger.info(f"Удалено старых записей из БД: {deleted_count} (старше {days_to_keep} дней)")
            return deleted_count

        except Exception as e:
            logger.error(f"Ошибка очистки старых записей: {e}")
            return 0

    def get_recommendations(self) -> List[str]:
        """
        Получение рекомендаций по оптимизации системы

        Returns:
            List[str]: Список рекомендаций
        """
        try:
            recommendations = []
            system_load = self.get_system_load()

            # Рекомендации по CPU
            if system_load.cpu_percent > self.thresholds['cpu_critical']:
                recommendations.append(
                    f"🚨 Критическая загрузка CPU ({system_load.cpu_percent:.1f}%) - немедленно остановить несрочные процессы")
            elif system_load.cpu_percent > self.thresholds['cpu_warning']:
                recommendations.append(
                    f"⚠️ Высокая загрузка CPU ({system_load.cpu_percent:.1f}%) - снизить профили эмуляторов")

            # Рекомендации по памяти
            if system_load.memory_percent > self.thresholds['memory_critical']:
                recommendations.append(
                    f"🚨 Критическая нехватка памяти ({system_load.memory_percent:.1f}%) - остановить эмуляторы")
            elif system_load.memory_percent > self.thresholds['memory_warning']:
                recommendations.append(
                    f"⚠️ Мало памяти ({system_load.memory_percent:.1f}%) - ограничить количество эмуляторов")

            # Рекомендации по диску
            if system_load.disk_percent > self.thresholds['disk_warning']:
                recommendations.append(
                    f"⚠️ Мало места на диске ({system_load.disk_percent:.1f}%) - очистить логи и кэши")

            # Рекомендации по процессам LDPlayer
            if system_load.ldplayer_processes > system_load.active_emulators * 3:
                recommendations.append(
                    f"🔧 Много процессов LDPlayer ({system_load.ldplayer_processes}) - проверить зависшие процессы")

            # Анализ трендов
            trends = self._analyze_trends()
            if trends['cpu_trend'] == 'increasing' and system_load.cpu_percent > 50:
                recommendations.append("📈 Загрузка CPU растёт - подготовиться к снижению нагрузки")

            if not recommendations:
                recommendations.append("✅ Система работает в нормальном режиме")

            return recommendations

        except Exception as e:
            logger.error(f"Ошибка получения рекомендаций: {e}")
            return [f"❌ Ошибка анализа системы: {str(e)}"]

    def emergency_shutdown_check(self) -> Tuple[bool, List[str]]:
        """
        Проверка необходимости экстренной остановки

        Returns:
            Tuple[bool, List[str]]: (нужна_остановка, список_причин)
        """
        try:
            system_load = self.get_system_load()
            emergency_reasons = []

            # Проверяем критические пороги
            if system_load.cpu_percent > 95:
                emergency_reasons.append(f"CPU перегружен: {system_load.cpu_percent:.1f}%")

            if system_load.memory_percent > 95:
                emergency_reasons.append(f"Память исчерпана: {system_load.memory_percent:.1f}%")

            if system_load.disk_percent > 98:
                emergency_reasons.append(f"Диск переполнен: {system_load.disk_percent:.1f}%")

            # Проверяем доступную память
            if system_load.memory_available_gb < 0.5:
                emergency_reasons.append(f"Критически мало свободной памяти: {system_load.memory_available_gb:.1f} GB")

            # Проверяем процессы LDPlayer
            if system_load.ldplayer_processes > 50:
                emergency_reasons.append(f"Слишком много процессов LDPlayer: {system_load.ldplayer_processes}")

            needs_shutdown = len(emergency_reasons) > 0

            if needs_shutdown:
                logger.critical(f"🚨 ТРЕБУЕТСЯ ЭКСТРЕННАЯ ОСТАНОВКА: {', '.join(emergency_reasons)}")

            return needs_shutdown, emergency_reasons

        except Exception as e:
            logger.error(f"Ошибка проверки экстренной остановки: {e}")
            return False, [f"Ошибка проверки: {str(e)}"]


def test_resource_monitor():
    """Тестирование системы мониторинга ресурсов"""
    logger.info("=== Тестирование ResourceMonitor ===")

    try:
        # Инициализация
        monitor = ResourceMonitor()

        # Тестирование получения загрузки системы
        logger.info("\n--- Тестирование получения загрузки системы ---")
        system_load = monitor.get_system_load()

        logger.info(f"📊 Текущая загрузка системы:")
        logger.info(f"  CPU: {system_load.cpu_percent:.1f}%")
        logger.info(f"  RAM: {system_load.memory_percent:.1f}% (свободно: {system_load.memory_available_gb:.1f} GB)")
        logger.info(f"  Диск: {system_load.disk_percent:.1f}% (свободно: {system_load.disk_free_gb:.1f} GB)")
        logger.info(f"  LDPlayer процессов: {system_load.ldplayer_processes}")
        logger.info(f"  Активных эмуляторов: {system_load.active_emulators}")
        logger.info(f"  Уровень нагрузки: {system_load.load_level}")

        # Тестирование проверки безопасности батча
        logger.info("\n--- Тестирование проверки безопасности батча ---")

        for profile in ['rushing', 'developing', 'farming']:
            recommendation = monitor.is_safe_to_start_batch(batch_size=3, profile=profile)

            logger.info(f"\n🎯 Профиль '{profile}':")
            logger.info(f"  Безопасно запускать: {'✅ Да' if recommendation.safe_to_start else '❌ Нет'}")
            logger.info(f"  Оптимальный размер батча: {recommendation.optimal_batch_size}")
            logger.info(f"  Максимальный размер батча: {recommendation.max_batch_size}")
            logger.info(f"  Рекомендуемый профиль: {recommendation.recommended_profile}")

            if recommendation.warnings:
                logger.info(f"  ⚠️ Предупреждения:")
                for warning in recommendation.warnings:
                    logger.info(f"    • {warning}")

            if recommendation.actions_needed:
                logger.info(f"  💡 Рекомендуемые действия:")
                for action in recommendation.actions_needed:
                    logger.info(f"    • {action}")

        # Тестирование логирования в БД
        logger.info("\n--- Тестирование логирования в БД ---")
        log_success = monitor.log_system_state()
        logger.info(f"Логирование в БД: {'✅ успешно' if log_success else '❌ ошибка'}")

        # Тестирование получения статистики
        logger.info("\n--- Тестирование получения статистики ---")
        stats = monitor.get_system_stats(hours_back=1)

        if 'error' not in stats:
            logger.info(f"📈 Статистика за последний час:")
            logger.info(f"  Измерений: {stats['measurements_count']}")
            logger.info(f"  CPU: среднее {stats['cpu']['avg']:.1f}%, макс {stats['cpu']['max']:.1f}%")
            logger.info(f"  RAM: среднее {stats['memory']['avg']:.1f}%, макс {stats['memory']['max']:.1f}%")
        else:
            logger.info(f"Статистика недоступна: {stats['error']}")

        # Тестирование рекомендаций
        logger.info("\n--- Тестирование рекомендаций ---")
        recommendations = monitor.get_recommendations()

        logger.info("💡 Рекомендации по оптимизации:")
        for rec in recommendations:
            logger.info(f"  {rec}")

        # Тестирование проверки экстренной остановки
        logger.info("\n--- Тестирование проверки экстренной остановки ---")
        needs_shutdown, reasons = monitor.emergency_shutdown_check()

        if needs_shutdown:
            logger.critical("🚨 ТРЕБУЕТСЯ ЭКСТРЕННАЯ ОСТАНОВКА:")
            for reason in reasons:
                logger.critical(f"  • {reason}")
        else:
            logger.info("✅ Экстренная остановка не требуется")

        logger.info("\n✅ Тестирование ResourceMonitor завершено успешно!")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования ResourceMonitor: {e}")
        return False


if __name__ == "__main__":
    # Настройка логирования для тестирования
    logger.add("logs/resource_monitor_test_{time}.log", rotation="10 MB", level="DEBUG")

    # Запуск тестирования
    success = test_resource_monitor()

    if success:
        print("\n✅ ResourceMonitor протестирован успешно!")
        print("📊 Проверьте логи для подробной информации")
    else:
        print("\n❌ Тестирование завершилось с ошибками!")
        print("📋 Проверьте логи для диагностики проблем")