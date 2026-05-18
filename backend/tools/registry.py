import importlib
import pkgutil
from typing import Any, Optional

from .base import BaseTool

_TOOLS: dict[str, type[BaseTool]] = {}
_INSTANCES: dict[str, BaseTool] = {}
_LAZY_LOAD_PATHS: dict[str, str] = {}
_DISABLED: set[str] = set()


def register(tool_cls: type[BaseTool]) -> None:
    if not hasattr(tool_cls, "name") or not tool_cls.name:
        raise ValueError("Tool class must have a non-empty 'name' attribute")
    _TOOLS[tool_cls.name] = tool_cls


def register_module(module_path: str) -> None:
    module = importlib.import_module(module_path)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseTool) and attr is not BaseTool:
            register(attr)


def get_tool(name: str) -> Optional[BaseTool]:
    if name in _INSTANCES:
        return _INSTANCES[name] if name not in _DISABLED else None
    if name in _TOOLS:
        instance = _TOOLS[name]()
        _INSTANCES[name] = instance
        return instance if name not in _DISABLED else None
    if name in _LAZY_LOAD_PATHS:
        try:
            register_module(_LAZY_LOAD_PATHS[name])
            instance = _TOOLS[name]()
            _INSTANCES[name] = instance
            return instance if name not in _DISABLED else None
        except Exception:
            pass
    return None


def get_all_tools() -> dict[str, BaseTool]:
    for name in _TOOLS:
        if name not in _INSTANCES and name not in _DISABLED:
            try:
                _INSTANCES[name] = _TOOLS[name]()
            except Exception:
                pass
    return {k: v for k, v in _INSTANCES.items() if k not in _DISABLED}


def enable(name: str) -> None:
    _DISABLED.discard(name)


def disable(name: str) -> None:
    _DISABLED.add(name)


def lazy_register(name: str, module_path: str) -> None:
    _LAZY_LOAD_PATHS[name] = module_path


class ToolRegistry:
    _tools: dict[str, type[BaseTool]] = _TOOLS
    _instances: dict[str, BaseTool] = _INSTANCES
    _disabled: set[str] = _DISABLED

    @classmethod
    def auto_discover(cls, package_path: str = "backend.tools") -> None:
        import backend.tools as pkg
        for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            if modname in ("__init__", "base", "registry"):
                continue
            try:
                module = importlib.import_module(f"{package_path}.{modname}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, BaseTool) and attr is not BaseTool:
                        register(attr)
            except Exception:
                pass
