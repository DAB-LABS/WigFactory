#!/usr/bin/env python3
"""Every built climate integration on both Home Assistant climate shapes.

Home Assistant 2026.11 serves a climate entity's temperatures as
``native_temperature_unit`` and ``native_target_temperature``. It warns when
an entity class provides one of the older names (``_attr_temperature_unit``,
``temperature_unit``, ``target_temperature`` and the rest), and again when
the entity reads or writes one, and the older names stop working in
2027.11. Earlier releases have only the older names. A generated climate
integration picks one set at import, from whether ``ClimateEntity`` has
``native_temperature_unit``.

Home Assistant is not installed here, so this file builds the parts of it a
climate integration imports, with two ``ClimateEntity`` shapes: one like
2026.6 to 2026.10, and one like 2026.11, whose older names report every use
the way Home Assistant's deprecation helper does. Then, for every
``custom_components/<domain>/climate.py`` this repository has built, on each
shape:

- the entity class provides exactly one set of names, never both, and no
  older ``_attr_`` shorthand;
- setting the entry up, turning the unit on at a temperature, turning it off,
  changing the temperature while off, and restoring a saved state all work;
- the unit, the setpoint after each step and the restored setpoint read the
  same on both shapes, through the names Home Assistant reads on each;
- on the 2026.11 shape nothing reports a deprecated name at any point.

The 2026.11 shape is checked first against a class that does provide the
older names, so a shape that has stopped reporting cannot pass everything.

    .venv/bin/python verify/test_climate_names.py

Exit 0 means every integration behaved on both shapes.
"""

from __future__ import annotations

import asyncio
import enum
import importlib
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

C = "°C"

# Saved by version 0.1.0 of the first climate integration, the shape every
# integration built from the climate template stores. A release that can no
# longer read it would forget every user's setpoint on update.
SAVED_STATE = {
    "hvac_mode": "cool",
    "last_on_mode": "cool",
    "fan_mode": None,
    "swing_mode": None,
    "temperature": 26.0,
}

NATIVE = ("native_temperature_unit", "native_target_temperature")
LEGACY = ("temperature_unit", "target_temperature")
LEGACY_ATTRS = ("_attr_temperature_unit", "_attr_target_temperature")


# --- what both shapes share --------------------------------------------------


class HVACMode(enum.StrEnum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    HEAT_COOL = "heat_cool"
    AUTO = "auto"
    DRY = "dry"
    FAN_ONLY = "fan_only"


class ClimateEntityFeature(enum.IntFlag):
    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    TARGET_HUMIDITY = 4
    FAN_MODE = 8
    PRESET_MODE = 16
    SWING_MODE = 32
    AUX_HEAT = 64
    TURN_OFF = 128
    TURN_ON = 256
    SWING_HORIZONTAL_MODE = 512


class UnitOfTemperature(enum.StrEnum):
    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class Platform(enum.StrEnum):
    BUTTON = "button"
    CLIMATE = "climate"
    EVENT = "event"
    FAN = "fan"
    LIGHT = "light"
    MEDIA_PLAYER = "media_player"


class HomeAssistantError(Exception):
    pass


class ConfigEntryError(HomeAssistantError):
    pass


class ServiceValidationError(HomeAssistantError):
    pass


class HomeAssistant:
    pass


class ConfigEntry:
    """Only what an entity reads off its entry."""

    def __class_getitem__(cls, item: Any) -> type:
        return cls

    def __init__(self) -> None:
        self.entry_id = "entry1"
        self.data = {"infrared_entity_id": "infrared.bench"}
        self.options: dict[str, Any] = {}
        self.runtime_data: Any = None


class Entity:
    hass: Any = None

    def async_write_ha_state(self) -> None:
        self.writes = getattr(self, "writes", 0) + 1

    async def async_added_to_hass(self) -> None:
        return None


class InfraredEmitterConsumerEntity(Entity):
    async def _send_command(self, command: Any) -> None:
        self.sent = [*getattr(self, "sent", []), command]


class ExtraStoredData:
    def as_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class _Stored(ExtraStoredData):
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.data)


class RestoreEntity(Entity):
    restore: dict[str, Any] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    async def async_get_last_extra_data(self) -> ExtraStoredData | None:
        return None if self.restore is None else _Stored(self.restore)


class _ClimateBase(Entity):
    """The members both shapes have and nothing here is about."""

    _attr_fan_mode: str | None = None
    _attr_fan_modes: list[str] | None = None
    _attr_hvac_mode: HVACMode | None = None
    _attr_hvac_modes: list[HVACMode] = []
    _attr_swing_mode: str | None = None
    _attr_swing_modes: list[str] | None = None
    _attr_supported_features = ClimateEntityFeature(0)
    _attr_target_temperature_step: float | None = None

    @property
    def hvac_mode(self) -> HVACMode | None:
        return self._attr_hvac_mode

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return self._attr_hvac_modes

    @property
    def fan_mode(self) -> str | None:
        return self._attr_fan_mode

    @property
    def swing_mode(self) -> str | None:
        return self._attr_swing_mode

    @property
    def min_temp(self) -> float:
        return self._attr_min_temp

    @property
    def max_temp(self) -> float:
        return self._attr_max_temp

    def _valid_mode_or_raise(self, mode_type: str, mode: str, modes: list) -> None:
        if mode not in modes:
            raise ServiceValidationError(f"{mode_type} {mode} not in {modes}")


# --- the two shapes ----------------------------------------------------------


class LegacyClimateEntity(_ClimateBase):
    """Shaped like Home Assistant 2026.6 to 2026.10."""

    _attr_target_temperature: float | None = None
    _attr_current_temperature: float | None = None

    @property
    def temperature_unit(self) -> str:
        return self._attr_temperature_unit

    @property
    def target_temperature(self) -> float | None:
        return self._attr_target_temperature

    @property
    def current_temperature(self) -> float | None:
        return self._attr_current_temperature


REPORTS: list[str] = []


class _DeprecatedProperty:
    """An older property on the 2026.11 shape: reports each read."""

    def __init__(self, replacement: str) -> None:
        self.replacement = replacement

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        REPORTS.append(f"reads the deprecated {self.name}")
        return getattr(instance, self.replacement)

    def native_names(self) -> set[str]:
        return {self.replacement, f"_attr_{self.replacement}"}


class _DeprecatedAttr(_DeprecatedProperty):
    """An older _attr_ shorthand on the 2026.11 shape: reports reads and writes."""

    def __set__(self, instance: Any, value: Any) -> None:
        REPORTS.append(f"writes the deprecated {self.name}")
        setattr(instance, self.replacement, value)

    def native_names(self) -> set[str]:
        return {self.replacement}


class NativeClimateEntity(_ClimateBase):
    """Shaped like Home Assistant 2026.11."""

    _attr_native_target_temperature: float | None = None
    _attr_native_current_temperature: float | None = None

    @property
    def native_temperature_unit(self) -> str:
        return self._attr_native_temperature_unit

    @property
    def native_target_temperature(self) -> float | None:
        return self._attr_native_target_temperature

    @property
    def native_current_temperature(self) -> float | None:
        return self._attr_native_current_temperature

    temperature_unit = _DeprecatedProperty("native_temperature_unit")
    target_temperature = _DeprecatedProperty("native_target_temperature")
    current_temperature = _DeprecatedProperty("native_current_temperature")
    target_temperature_high = _DeprecatedProperty("native_target_temperature_high")
    target_temperature_low = _DeprecatedProperty("native_target_temperature_low")
    _attr_temperature_unit = _DeprecatedAttr("_attr_native_temperature_unit")
    _attr_target_temperature = _DeprecatedAttr("_attr_native_target_temperature")
    _attr_current_temperature = _DeprecatedAttr("_attr_native_current_temperature")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Serve and report each older name a subclass provides alone.

        The rule Home Assistant's migrate_deprecated_entity_members applies:
        the most derived class providing either name wins, only a class
        providing the older name alone is reported, and its value is then
        served under the native name, so an entity written for the older
        shape still works on this one while it is being reported.
        """
        super().__init_subclass__(**kwargs)
        base = NativeClimateEntity
        for name, alias in vars(base).items():
            if not isinstance(alias, _DeprecatedProperty):
                continue
            native = alias.native_names()
            provider = next(
                klass
                for klass in cls.__mro__
                if name in vars(klass) or not native.isdisjoint(vars(klass))
            )
            if provider is base or not native.isdisjoint(vars(provider)):
                continue
            if isinstance(alias, _DeprecatedAttr):
                setattr(cls, alias.replacement, inspect.getattr_static(cls, name))
                setattr(cls, name, alias)
            else:
                setattr(cls, alias.replacement, _Fallback(name))
            REPORTS.append(f"{cls.__name__} provides the deprecated {name}")


class _Fallback:
    """The native name, served from the older one a subclass provides."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return getattr(instance, self.name)


SHAPES = {"2026.6 to 2026.10": LegacyClimateEntity, "2026.11": NativeClimateEntity}


# --- Home Assistant, as far as a climate integration imports it -------------


def _module(name: str, **members: Any) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []  # every one can be a package
    module.__dict__.update(members)
    return module


def install_home_assistant(climate_entity: type) -> None:
    """Put a Home Assistant with this ClimateEntity shape in sys.modules."""
    modules = {
        "homeassistant": {},
        "homeassistant.components": {},
        "homeassistant.components.climate": {
            "ATTR_HVAC_MODE": "hvac_mode",
            "ClimateEntity": climate_entity,
            "ClimateEntityFeature": ClimateEntityFeature,
            "HVACMode": HVACMode,
        },
        "homeassistant.components.infrared": {
            "InfraredEmitterConsumerEntity": InfraredEmitterConsumerEntity,
        },
        "homeassistant.config_entries": {"ConfigEntry": ConfigEntry},
        "homeassistant.const": {
            "ATTR_TEMPERATURE": "temperature",
            "Platform": Platform,
            "UnitOfTemperature": UnitOfTemperature,
        },
        "homeassistant.core": {"HomeAssistant": HomeAssistant},
        "homeassistant.exceptions": {
            "ConfigEntryError": ConfigEntryError,
            "HomeAssistantError": HomeAssistantError,
            "ServiceValidationError": ServiceValidationError,
        },
        "homeassistant.helpers": {},
        "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
        "homeassistant.helpers.entity": {"Entity": Entity},
        "homeassistant.helpers.entity_platform": {
            "AddConfigEntryEntitiesCallback": Callable,
        },
        "homeassistant.helpers.restore_state": {
            "ExtraStoredData": ExtraStoredData,
            "RestoreEntity": RestoreEntity,
        },
    }
    for name, members in modules.items():
        sys.modules[name] = _module(name, **members)


# --- one integration on one shape -------------------------------------------


@dataclass
class Run:
    unit: str | None = None
    readings: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


class _Hass:
    """What an entry's setup calls on hass."""

    def __init__(self) -> None:
        self.config_entries = self

    async def async_add_executor_job(self, func: Callable, *args: Any) -> Any:
        return func(*args)

    async def async_forward_entry_setups(self, entry: Any, platforms: Any) -> bool:
        return True


def _purge(package: str) -> None:
    for name in list(sys.modules):
        if name == package or name.startswith(f"{package}."):
            del sys.modules[name]


def _read(entity: Any, names: tuple[str, str]) -> tuple[Any, Any]:
    """The unit and setpoint, read the way Home Assistant reads them."""
    return getattr(entity, names[0]), getattr(entity, names[1])


async def _exercise(package: str, shape: type, run: Run) -> None:
    pkg = importlib.import_module(package)
    climate = importlib.import_module(f"{package}.climate")
    entity_class = next(
        value
        for value in vars(climate).values()
        if isinstance(value, type)
        and issubclass(value, shape)
        and value.__module__ == climate.__name__
    )

    native = shape is NativeClimateEntity
    names = NATIVE if native else LEGACY
    provided = {n for n in (*NATIVE, *LEGACY) if n in vars(entity_class)}
    if native and provided != set(NATIVE):
        run.problems.append(f"provides {sorted(provided)}, wants {list(NATIVE)}")
    if not native and provided - set(LEGACY):
        run.problems.append(f"provides native names on the older shape: {provided}")
    for attr in LEGACY_ATTRS if native else ():
        if attr in vars(entity_class):
            run.problems.append(f"sets {attr} on the class")

    hass = _Hass()
    entry = ConfigEntry()
    if not await pkg.async_setup_entry(hass, entry):
        run.problems.append("the entry did not set up")
        return
    added: list[Any] = []
    await climate.async_setup_entry(hass, entry, added.extend)
    (entity,) = added
    entity.hass = hass

    run.unit, run.readings["start"] = _read(entity, names)

    mode = next(m for m in entity.hvac_modes if m != HVACMode.OFF)
    middle = (entity.min_temp + entity.max_temp) / 2
    await entity.async_set_temperature(temperature=middle, hvac_mode=mode)
    run.readings["on"] = _read(entity, names)[1]
    if not getattr(entity, "sent", None):
        run.problems.append("turning on at a temperature sent nothing")

    await entity.async_turn_off()
    await entity.async_set_temperature(temperature=entity.max_temp)
    run.readings["off, changed"] = _read(entity, names)[1]
    run.readings["saved"] = entity.extra_restore_state_data.as_dict()

    # A fresh entity, restoring what 0.1.0 saved.
    added.clear()
    await climate.async_setup_entry(hass, entry, added.extend)
    (restored,) = added
    restored.hass = hass
    restored.restore = SAVED_STATE
    await restored.async_added_to_hass()
    run.readings["restored"] = _read(restored, names)[1]
    run.readings["restored mode"] = restored.hvac_mode


def run_on_shape(integration: Path, shape: type) -> Run:
    """Import the integration fresh against one shape and drive it."""
    components = integration / "custom_components"
    (domain,) = [p.name for p in components.iterdir() if (p / "climate.py").exists()]
    install_home_assistant(shape)
    _purge(domain)
    sys.path.insert(0, str(components))
    REPORTS.clear()
    run = Run()
    try:
        asyncio.run(_exercise(domain, shape, run))
    except Exception as err:  # noqa: BLE001 -- the report says which, and where
        run.problems.append(f"{type(err).__name__}: {err}")
    finally:
        sys.path.remove(str(components))
        _purge(domain)
    if shape is NativeClimateEntity:
        run.problems.extend(f"Home Assistant 2026.11 reports: {r}" for r in REPORTS)
    return run


def check_integration(integration: Path) -> list[str]:
    runs = {label: run_on_shape(integration, shape) for label, shape in SHAPES.items()}
    problems = [
        f"on {label}: {line}" for label, run in runs.items() for line in run.problems
    ]
    if problems:
        return problems
    old, new = runs.values()
    if old.unit != C or new.unit != C:
        problems.append(f"declares {old.unit!r} and {new.unit!r}, wants {C!r}")
    if old.readings != new.readings:
        problems.append(f"the shapes disagree: {old.readings} against {new.readings}")
    restored = new.readings.get("restored")
    if restored != SAVED_STATE["temperature"]:
        problems.append(f"restored a setpoint of {restored} from {SAVED_STATE}")
    return problems


def check_the_shape() -> list[str]:
    """The 2026.11 shape reports a class that provides the older names."""
    install_home_assistant(NativeClimateEntity)
    REPORTS.clear()

    class _Old(NativeClimateEntity):
        _attr_temperature_unit = C

        def __init__(self) -> None:
            self._attr_target_temperature = 20.0

    _ = _Old().target_temperature
    wanted = {
        "_Old provides the deprecated _attr_temperature_unit",
        "writes the deprecated _attr_target_temperature",
        "reads the deprecated target_temperature",
    }
    missing = wanted - set(REPORTS)
    return [f"the 2026.11 shape did not report: {m}" for m in sorted(missing)]


def built_climate_integrations() -> list[Path]:
    found = []
    for climate in sorted(REPO_ROOT.glob("*/*/custom_components/*/climate.py")):
        integration = climate.parent.parent.parent
        if integration.relative_to(REPO_ROOT).parts[0] != "reference":
            found.append(integration)
    return found


def main() -> int:
    failures = 0
    scenarios: list[tuple[str, Callable[[], list[str]]]] = [
        ("the 2026.11 shape reports the older names", check_the_shape),
    ]
    for integration in built_climate_integrations():
        name = integration.relative_to(REPO_ROOT)
        scenarios.append(
            (f"{name} on both shapes", lambda i=integration: check_integration(i))
        )

    print("climate temperature names on Home Assistant 2026.10 and 2026.11 shapes\n")
    for title, scenario in scenarios:
        problems = scenario()
        if problems:
            failures += 1
            print(f"  FAIL  {title}")
            for line in problems:
                print(f"          {line}")
        else:
            print(f"  PASS  {title}")
    print()
    if len(scenarios) == 1:
        print("No built climate integration found.")
        return 1
    if failures:
        print(f"{failures} scenario(s) misbehaved.")
        return 1
    print("ALL SCENARIOS BEHAVE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
