"""Stub file for type checking with Mypy"""
from typing import Any, Optional

from thespian.actors import Actor  # type: ignore


class RestApi(Actor):
    api: Any = ...
    class Dummy:
        @staticmethod
        def write(arg: Optional[Any] = ..., **kwargs: Any) -> None: ...
        @staticmethod
        def flush(arg: Optional[Any] = ..., **kwargs: Any) -> None: ...
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
