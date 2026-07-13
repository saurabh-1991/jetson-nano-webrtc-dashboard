"""GPIO Control for Jetson Nano"""

import logging
from .gpio_devices_config import get_gpio_outputs_config

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
        self.output_states = {name: False for name in self.outputs_config.keys()}
        self.gpio_available = GPIO_AVAILABLE
        
        if self.gpio_available:
            try:
                GPIO.setmode(GPIO.BOARD)
                for output in self.outputs_config.values():
                    GPIO.setup(output["pin"], GPIO.OUT, initial=GPIO.LOW)
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
            GPIO.output(pin, GPIO.HIGH if is_on else GPIO.LOW)
            self.output_states[output_name] = bool(is_on)
            logger.info("%s turned %s (BOARD pin %s)", output_name, "ON" if is_on else "OFF", pin)
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
        current_state = self.output_states.get(output_name, False)
        return self.set_output(output_name, not current_state)

    def get_outputs_state(self) -> dict:
        """Get current runtime GPIO state for all outputs."""
        return {
            "gpio_available": self.gpio_available,
            "outputs": {
                name: {
                    "label": cfg["label"],
                    "pin": cfg["pin"],
                    "on": self.output_states.get(name, False),
                }
                for name, cfg in self.outputs_config.items()
            }
        }

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
