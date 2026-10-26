"""Built-in tools over the workspace. Each declares its effects honestly."""

from __future__ import annotations

from typing import Any

from .model import EffectSet, ToolSpec
from .registry import Registry
from .workspace import Workspace


def _set_value(ws: Workspace, args: dict[str, Any]) -> Any:
    ws.set(args["key"], args["value"])
    return args["value"]


def _increment(ws: Workspace, args: dict[str, Any]) -> Any:
    new = (ws.get(args["key"], 0) or 0) + args.get("by", 1)
    ws.set(args["key"], new)
    return new


def _copy_value(ws: Workspace, args: dict[str, Any]) -> Any:
    value = ws.get(args["src"])
    ws.set(args["dst"], value)
    return value


def _append_log(ws: Workspace, args: dict[str, Any]) -> Any:
    log = list(ws.get(args["key"], []) or [])
    log.append(args["item"])
    ws.set(args["key"], log)
    return len(log)


def _delete_key(ws: Workspace, args: dict[str, Any]) -> Any:
    existed = ws.get(args["key"]) is not None
    ws.delete(args["key"])
    return existed


def _read_value(ws: Workspace, args: dict[str, Any]) -> Any:
    return ws.get(args["key"])


def default_registry() -> Registry:
    reg = Registry()
    reg.register(ToolSpec(
        name="kv.set",
        capabilities=frozenset({"store.set"}),
        required_scopes=frozenset({"write"}),
        effects=lambda a: EffectSet(writes=frozenset({a["key"]})),
        func=_set_value,
    ))
    reg.register(ToolSpec(
        name="kv.increment",
        capabilities=frozenset({"math.increment"}),
        required_scopes=frozenset({"write"}),
        effects=lambda a: EffectSet(
            reads=frozenset({a["key"]}), writes=frozenset({a["key"]})
        ),
        func=_increment,
    ))
    reg.register(ToolSpec(
        name="kv.copy",
        capabilities=frozenset({"store.copy"}),
        required_scopes=frozenset({"write"}),
        effects=lambda a: EffectSet(
            reads=frozenset({a["src"]}), writes=frozenset({a["dst"]})
        ),
        func=_copy_value,
    ))
    reg.register(ToolSpec(
        name="kv.append",
        capabilities=frozenset({"log.append"}),
        required_scopes=frozenset({"write"}),
        effects=lambda a: EffectSet(
            reads=frozenset({a["key"]}), writes=frozenset({a["key"]})
        ),
        func=_append_log,
    ))
    reg.register(ToolSpec(
        name="kv.delete",
        capabilities=frozenset({"store.delete"}),
        required_scopes=frozenset({"admin"}),
        effects=lambda a: EffectSet(writes=frozenset({a["key"]})),
        func=_delete_key,
    ))
    reg.register(ToolSpec(
        name="kv.read",
        capabilities=frozenset({"store.read"}),
        required_scopes=frozenset({"read"}),
        effects=lambda a: EffectSet(reads=frozenset({a["key"]})),
        func=_read_value,
    ))
    return reg
