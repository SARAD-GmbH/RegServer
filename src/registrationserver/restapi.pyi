"""Stub file for type checking with Mypy"""
from typing import Any, Optional


class RestApi:
    api: Any = ...
    @staticmethod
    def get_list(): ...
    @staticmethod
    def get_device(did: Any): ...
    @staticmethod
    def reserve_device(did: Any): ...
    @staticmethod
    def free_device(did: Any): ...
    def run(
        self,
        host: Optional[Any] = ...,
        port: Optional[Any] = ...,
        debug: Optional[Any] = ...,
        load_dotenv: bool = ...,
    ) -> None: ...
