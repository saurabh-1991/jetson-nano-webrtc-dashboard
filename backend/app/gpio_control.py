"""GPIO Control for Jetson Nano"""

import logging
from .config import GPIO_LED_PIN, GPIO_BUTTON_PIN

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
        self.led_pin = GPIO_LED_PIN
        self.button_pin = GPIO_BUTTON_PIN
        self.led_state = False
        self.gpio_available = GPIO_AVAILABLE
        
        if self.gpio_available:
            try:
                GPIO.setmode(GPIO.BOARD)
                GPIO.setup(self.led_pin, GPIO.OUT, initial=GPIO.LOW)
                GPIO.setup(self.button_pin, GPIO.IN)
                logger.info("GPIO initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize GPIO: {e}")
                GPIO_AVAILABLE = False
                self.gpio_available = False
        else:
            logger.warning("GPIO runtime unavailable; LED operations will be rejected")

    def led_on(self) -> bool:
        """Turn LED on"""
        try:
            if not self.gpio_available:
                logger.warning("Ignoring LED ON request: GPIO runtime unavailable")
                return False

            GPIO.output(self.led_pin, GPIO.HIGH)
            self.led_state = True
            logger.info("LED turned ON")
            return True
        except Exception as e:
            logger.error(f"Failed to turn LED on: {e}")
            return False

    def led_off(self) -> bool:
        """Turn LED off"""
        try:
            if not self.gpio_available:
                logger.warning("Ignoring LED OFF request: GPIO runtime unavailable")
                return False

            GPIO.output(self.led_pin, GPIO.LOW)
            self.led_state = False
            logger.info("LED turned OFF")
            return True
        except Exception as e:
            logger.error(f"Failed to turn LED off: {e}")
            return False

    def toggle_led(self) -> bool:
        """Toggle LED state"""
        if self.led_state:
            return self.led_off()
        else:
            return self.led_on()

    def get_led_state(self) -> dict:
        """Get current LED state"""
        return {
            "led_on": self.led_state,
            "gpio_available": self.gpio_available
        }

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
