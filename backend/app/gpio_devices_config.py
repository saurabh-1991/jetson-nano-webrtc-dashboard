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
    },
    "air_mixer_blower": {
        "label": "Air Mixer Blower",
        "pin": 16,
        "env": "GPIO_AIR_MIXER_BLOWER_PIN",
    },
    "lpg_burner": {
        "label": "LPG Burner",
        "pin": 18,
        "env": "GPIO_LPG_BURNER_PIN",
    },
}

GPIO_INPUTS_DEFAULT = {
    "flame": {
        "label": "Flame",
        "pin": 22,
        "env": "GPIO_FLAME_INPUT_PIN",
    },
    "burner_trip": {
        "label": "Burner Trip",
        "pin": 24,
        "env": "GPIO_BURNER_TRIP_INPUT_PIN",
    },
}


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

    for name, item in GPIO_OUTPUTS_DEFAULT.items():
        pin = _parse_pin(name, item["pin"], item["env"])
        config[name] = {
            "label": item["label"],
            "pin": pin,
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
