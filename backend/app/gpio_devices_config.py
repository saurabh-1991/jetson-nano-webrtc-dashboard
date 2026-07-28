"""GPIO output device configuration for production controls.

Customize default BOARD pins here, or override each pin via environment variables:
- GPIO_EXHAUST_BLOWER_PIN
- GPIO_AIR_MIXER_BLOWER_PIN
- GPIO_LPG_BURNER_PIN
- GPIO_FLAME_INPUT_PIN
- GPIO_BURNER_TRIP_INPUT_PIN
"""

import os
import logging

logger = logging.getLogger(__name__)


GPIO_OUTPUTS_DEFAULT = {
    "exhaust_blower": {
        "label": "Exhaust Blower",
        "pin": 12,
        "env": "GPIO_EXHAUST_BLOWER_PIN",
        "active_low": True,
        "active_low_env": "GPIO_EXHAUST_BLOWER_ACTIVE_LOW",
    },
    "air_mixer_blower": {
        "label": "Air Mixer Blower",
        "pin": 16,
        "env": "GPIO_AIR_MIXER_BLOWER_PIN",
        "active_low": True,
        "active_low_env": "GPIO_AIR_MIXER_BLOWER_ACTIVE_LOW",
    },
    "lpg_burner": {
        "label": "LPG Burner",
        "pin": 18,
        "env": "GPIO_LPG_BURNER_PIN",
        "active_low": True,
        "active_low_env": "GPIO_LPG_BURNER_ACTIVE_LOW",
    },
}

GPIO_INPUTS_DEFAULT = {
    "flame": {
        "label": "Flame",
        "pin": 22,
        "env": "GPIO_FLAME_INPUT_PIN",
        "active_low": False,
        "active_low_env": "GPIO_FLAME_ACTIVE_LOW",
    },
    "burner_trip": {
        "label": "Burner Trip",
        "pin": 24,
        "env": "GPIO_BURNER_TRIP_INPUT_PIN",
        "active_low": True,
        "active_low_env": "GPIO_BURNER_TRIP_ACTIVE_LOW",
    },
}


def _parse_bool(default_value: bool, env_name: str) -> bool:
    raw = os.getenv(env_name)
    if raw is None or str(raw).strip() == "":
        return bool(default_value)

    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _parse_pin(name: str, default_pin: int, env_name: str) -> int:
    """Parse pin override from environment with safe fallback."""
    raw = os.getenv(env_name)
    if raw is None or str(raw).strip() == "":
        return int(default_pin)

    try:
        pin = int(raw)
        if pin <= 0:
            raise ValueError("pin must be positive")
        return pin
    except Exception:
        logger.warning(
            "Invalid %s=%r for %s, falling back to default pin %s",
            env_name,
            raw,
            name,
            default_pin,
        )
        return int(default_pin)


def get_gpio_outputs_config() -> dict:
    """Return runtime GPIO output config with env overrides applied."""
    config = {}
    default_outputs_active_low = _parse_bool(True, "GPIO_OUTPUTS_ACTIVE_LOW")

    for name, item in GPIO_OUTPUTS_DEFAULT.items():
        pin = _parse_pin(name, item["pin"], item["env"])
        config[name] = {
            "label": item["label"],
            "pin": pin,
            "active_low": _parse_bool(
                item.get("active_low", default_outputs_active_low),
                item.get("active_low_env", ""),
            ),
        }

    _warn_pin_conflicts(config)

    return config


def get_gpio_inputs_config() -> dict:
    """Return runtime GPIO input config with env overrides applied."""
    config = {}

    for name, item in GPIO_INPUTS_DEFAULT.items():
        pin = _parse_pin(name, item["pin"], item["env"])
        config[name] = {
            "label": item["label"],
            "pin": pin,
            "active_low": _parse_bool(item.get("active_low", False), item.get("active_low_env", "")),
        }

    _warn_pin_conflicts(config)

    return config


def _warn_pin_conflicts(config: dict):
    """Warn if duplicate pins are configured in the provided logical map."""
    used_pins = {}
    for name, item in config.items():
        pin = item["pin"]
        if pin in used_pins:
            logger.warning(
                "GPIO pin conflict: %s and %s are both configured to BOARD pin %s",
                used_pins[pin],
                name,
                pin,
            )
        else:
            used_pins[pin] = name
