"""GPIO Control for Jetson Nano"""

import logging
import threading
from .gpio_devices_config import get_gpio_outputs_config, get_gpio_inputs_config

logger = logging.getLogger(__name__)

# Try to import Jetson.GPIO, fallback to mock for development
GPIO_AVAILABLE = False
try:
    import Jetson.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    logger.warning("Jetson.GPIO not available, using mock GPIO")
    GPIO_AVAILABLE = False


class GPIOController:
    """Control GPIO pins on Jetson Nano"""

    def __init__(self):
        global GPIO_AVAILABLE
        self.outputs_config = get_gpio_outputs_config()
        self.inputs_config = get_gpio_inputs_config()
        self.output_states = {name: False for name in self.outputs_config.keys()}
        self._state_lock = threading.RLock()
        self.gpio_available = GPIO_AVAILABLE
        
        if self.gpio_available:
            try:
                GPIO.setmode(GPIO.BOARD)
                for output in self.outputs_config.values():
                    # Initialize to logical OFF safely while honoring active_low polarity.
                    initial_level = GPIO.HIGH if bool(output.get("active_low", False)) else GPIO.LOW
                    GPIO.setup(output["pin"], GPIO.OUT, initial=initial_level)

                for input_cfg in self.inputs_config.values():
                    try:
                        GPIO.setup(input_cfg["pin"], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                    except TypeError:
                        # Compatibility fallback for builds without pull_up_down support.
                        GPIO.setup(input_cfg["pin"], GPIO.IN)

                logger.info("GPIO initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize GPIO: {e}")
                GPIO_AVAILABLE = False
                self.gpio_available = False
        else:
            logger.warning("GPIO runtime unavailable; LED operations will be rejected")

    def set_output(self, output_name: str, is_on: bool) -> bool:
        """Set an output ON/OFF by logical name."""
        if output_name not in self.outputs_config:
            logger.warning("Unknown GPIO output requested: %s", output_name)
            return False

        try:
            if not self.gpio_available:
                logger.warning("Ignoring output request (%s): GPIO runtime unavailable", output_name)
                return False

            pin = self.outputs_config[output_name]["pin"]
            active_low = bool(self.outputs_config[output_name].get("active_low", False))
            gpio_level = GPIO.LOW if (is_on and active_low) else GPIO.HIGH if (not is_on and active_low) else GPIO.HIGH if is_on else GPIO.LOW
            GPIO.output(pin, gpio_level)
            with self._state_lock:
                self.output_states[output_name] = bool(is_on)
            logger.info(
                "%s turned %s (BOARD pin %s, active_low=%s, gpio_level=%s)",
                output_name,
                "ON" if is_on else "OFF",
                pin,
                active_low,
                "LOW" if gpio_level == GPIO.LOW else "HIGH",
            )
            return True
        except Exception as e:
            logger.error("Failed to set output %s: %s", output_name, e)
            return False

    def turn_output_on(self, output_name: str) -> bool:
        """Turn a named output on."""
        return self.set_output(output_name, True)

    def turn_output_off(self, output_name: str) -> bool:
        """Turn a named output off."""
        return self.set_output(output_name, False)

    def toggle_output(self, output_name: str) -> bool:
        """Toggle a named output state."""
        with self._state_lock:
            current_state = self.output_states.get(output_name, False)
        return self.set_output(output_name, not current_state)

    def get_outputs_state(self) -> dict:
        """Get current runtime GPIO state for all outputs."""
        input_signals = {}

        for name, cfg in self.inputs_config.items():
            signal_on = self.read_input_signal(name)
            input_signals[name] = {
                "label": cfg["label"],
                "pin": cfg["pin"],
                "active_low": bool(cfg.get("active_low", False)),
                "signal": signal_on,
            }

        return {
            "gpio_available": self.gpio_available,
            "outputs": {
                name: {
                    "label": cfg["label"],
                    "pin": cfg["pin"],
                    "active_low": bool(cfg.get("active_low", False)),
                    "on": self.output_states.get(name, False),
                }
                for name, cfg in self.outputs_config.items()
            },
            "inputs": input_signals,
        }

    def any_output_on(self) -> bool:
        with self._state_lock:
            return any(bool(v) for v in self.output_states.values())

    def force_all_outputs_off(self, reason: str = "watchdog") -> bool:
        """Best-effort fail-safe OFF for all configured outputs."""
        if not self.gpio_available:
            logger.warning("Fail-safe OFF requested (%s) but GPIO unavailable", reason)
            return False

        success = True
        for name in self.outputs_config.keys():
            if not self.set_output(name, False):
                success = False

        logger.warning("Fail-safe OFF executed for all outputs. reason=%s success=%s", reason, success)
        return success

    def read_input_signal(self, input_name: str) -> bool:
        """Read a named digital input signal from GPIO."""
        if input_name not in self.inputs_config:
            logger.warning("Unknown GPIO input requested: %s", input_name)
            return False

        if not self.gpio_available:
            return False

        try:
            pin = self.inputs_config[input_name]["pin"]
            raw_high = bool(GPIO.input(pin) == GPIO.HIGH)
            active_low = bool(self.inputs_config[input_name].get("active_low", False))
            return (not raw_high) if active_low else raw_high
        except Exception as e:
            logger.error("Failed to read GPIO input %s: %s", input_name, e)
            return False

    # -------- Legacy LED methods (kept for backward compatibility) --------
    def led_on(self) -> bool:
        """Legacy endpoint compatibility: maps LED ON to exhaust blower ON."""
        return self.turn_output_on("exhaust_blower")

    def led_off(self) -> bool:
        """Legacy endpoint compatibility: maps LED OFF to exhaust blower OFF."""
        return self.turn_output_off("exhaust_blower")

    def toggle_led(self) -> bool:
        """Legacy endpoint compatibility: maps LED toggle to exhaust blower toggle."""
        return self.toggle_output("exhaust_blower")

    def get_led_state(self) -> dict:
        """Legacy state shape compatibility plus production outputs payload."""
        state = self.get_outputs_state()
        state["led_on"] = self.output_states.get("exhaust_blower", False)
        return state

    def cleanup(self):
        """Clean up GPIO"""
        try:
            if self.gpio_available:
                GPIO.cleanup()
                logger.info("GPIO cleanup completed")
        except Exception as e:
            logger.error(f"Failed to cleanup GPIO: {e}")


# Global GPIO controller instance
gpio_controller = None


def get_gpio_controller() -> GPIOController:
    """Get or create GPIO controller"""
    global gpio_controller
    if gpio_controller is None:
        gpio_controller = GPIOController()
    return gpio_controller
