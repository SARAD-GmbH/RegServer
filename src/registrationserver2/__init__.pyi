"""Stub for type checking of registrationsserver2"""
from typing import Any, Optional, Pattern

from thespian.actors import ActorSystem  # type: ignore

actor_system: ActorSystem
home: Optional[str]
theLogger: Any
formatter: Any
matchid: Pattern[str]
FILE_PATH_AVAILABLE: str
FILE_PATH_HISTORY: str
PATH_AVAILABLE: str
PATH_HISTORY: str
FOLDER_AVAILABLE: str
FOLDER_HISTORY: str
RESERVE_KEYWORD: str
FREE_KEYWORD: str
