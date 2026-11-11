"""Run CadQuery scripts with parameters.

A script is plain Python. It may call ``param(name, default)`` to declare a
tunable parameter and must assign the final CadQuery object to ``result``.

This is a restricted execution environment (limited builtins and imports) meant to
prevent accidents, not to contain hostile code. Only run scripts you trust.
"""
from __future__ import annotations

import builtins
import math
import traceback
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq
import numpy as np

from . import tolerances

ALLOWED_IMPORTS = {"cadquery", "math", "numpy", "typing", "printcad.tolerances", "printcad"}

_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int",
    "isinstance", "len", "list", "map", "max", "min", "pow", "print", "range", "reversed",
    "round", "set", "sorted", "str", "sum", "tuple", "zip", "True", "False", "None",
    "ValueError", "TypeError", "Exception", "ArithmeticError", "RuntimeError", "complex",
    "bytes", "slice", "repr", "format", "hasattr", "getattr", "callable", "iter", "next",
    "object", "type", "property", "staticmethod", "classmethod", "super", "chr", "ord",
    "hash", "frozenset", "KeyError", "IndexError", "AttributeError", "StopIteration",
    "NotImplementedError", "ZeroDivisionError", "AssertionError",
]


class ScriptError(Exception):
    """Raised when a script fails to run or does not produce a valid result."""


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if level != 0 or (name not in ALLOWED_IMPORTS and root not in ALLOWED_IMPORTS):
        raise ImportError(f"Import of '{name}' is not allowed in PrintCAD scripts")
    if root == "printcad" and name not in ("printcad", "printcad.tolerances"):
        raise ImportError(f"Import of '{name}' is not allowed in PrintCAD scripts")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _safe_builtins() -> dict[str, Any]:
    safe = {n: getattr(builtins, n) for n in _SAFE_BUILTIN_NAMES if hasattr(builtins, n)}
    safe["__import__"] = _restricted_import
    safe["__build_class__"] = builtins.__build_class__
    safe["__name__"] = "printcad_script"
    return safe


@dataclass
class ParamSpec:
    name: str
    default: Any
    value: Any
    type: str
    min: float | None = None
    max: float | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "default": self.default,
            "value": self.value,
            "type": self.type,
            "min": self.min,
            "max": self.max,
        }


@dataclass
class RunResult:
    shape: cq.Shape
    params: list[ParamSpec] = field(default_factory=list)
    stdout: str = ""


def _coerce(name: str, default: Any, raw: Any) -> Any:
    try:
        if isinstance(default, bool):
            if isinstance(raw, str):
                return raw.strip().lower() in ("1", "true", "yes", "on")
            return bool(raw)
        if isinstance(default, int):
            f = float(raw)
            if f != int(f):
                raise ValueError("not an integer")
            return int(f)
        if isinstance(default, float):
            return float(raw)
        return str(raw)
    except (TypeError, ValueError) as exc:
        raise ScriptError(f"Parameter '{name}' has invalid value {raw!r}: {exc}") from None


def _type_name(default: Any) -> str:
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    return "str"


def _extract_shape(result: Any) -> cq.Shape:
    if isinstance(result, cq.Assembly):
        return result.toCompound()
    if isinstance(result, cq.Workplane):
        shapes = [o for o in result.vals() if isinstance(o, cq.Shape)]
        if not shapes:
            raise ScriptError("'result' Workplane contains no solids or shapes")
        return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    if isinstance(result, cq.Shape):
        return result
    raise ScriptError(
        f"'result' must be a CadQuery Workplane, Shape or Assembly, got {type(result).__name__}"
    )


def run_script(script: str, params: dict[str, Any] | None = None) -> RunResult:
    """Execute `script` with user parameter overrides and return the resulting shape."""
    overrides = dict(params or {})
    specs: dict[str, ParamSpec] = {}
    out: list[str] = []

    def param(name: str, default: Any, min: float | None = None, max: float | None = None):
        if name in specs:
            return specs[name].value
        value = _coerce(name, default, overrides[name]) if name in overrides else default
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if min is not None and value < min:
                raise ScriptError(f"Parameter '{name}'={value} is below the minimum {min}")
            if max is not None and value > max:
                raise ScriptError(f"Parameter '{name}'={value} is above the maximum {max}")
        specs[name] = ParamSpec(name, default, value, _type_name(default), min, max)
        return value

    def _print(*args, **kwargs):
        out.append(" ".join(str(a) for a in args))

    builtins_ns = _safe_builtins()
    builtins_ns["print"] = _print
    ns: dict[str, Any] = {
        "__builtins__": builtins_ns,
        "cq": cq,
        "math": math,
        "np": np,
        "tolerances": tolerances,
        "param": param,
        "params": overrides,
    }
    try:
        code = compile(script, "<printcad-script>", "exec")
    except SyntaxError as exc:
        raise ScriptError(f"Syntax error on line {exc.lineno}: {exc.msg}") from None
    try:
        exec(code, ns)  # noqa: S102 - intentional, see module docstring
    except ScriptError:
        raise
    except Exception as exc:  # script bugs are reported to the user
        tb = traceback.extract_tb(exc.__traceback__)
        line = next((f.lineno for f in reversed(tb) if f.filename == "<printcad-script>"), None)
        where = f" (line {line})" if line else ""
        raise ScriptError(f"{type(exc).__name__}: {exc}{where}") from None
    if "result" not in ns:
        raise ScriptError("Script must assign the final model to a variable named 'result'")
    shape = _extract_shape(ns["result"])
    return RunResult(shape=shape, params=list(specs.values()), stdout="\n".join(out))
