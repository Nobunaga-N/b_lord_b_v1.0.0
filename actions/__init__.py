"""
Модуль игровых действий.
Содержит все действия, которые бот может выполнять в игре.
"""

# Импорт базовых действий
from .basic import BasicActions, enter_game, go_to_main_screen, check_shield

# Импорт других модулей (пока пустые, будут реализованы в следующих промптах)
# from .building import *
# from .combat import *
# from .resources import *
# from .alliance import *

# Список доступных действий для удобства
AVAILABLE_ACTIONS = [
    'enter_game',
    'go_to_main_screen',
    'check_shield',
    # Будут добавлены в следующих промптах:
    # 'upgrade_building',
    # 'hunt_monsters',
    # 'collect_resources',
    # 'help_alliance',
]

__all__ = [
    'BasicActions',
    'enter_game',
    'go_to_main_screen',
    'check_shield',
    'AVAILABLE_ACTIONS',
]