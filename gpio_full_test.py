#!/usr/bin/env python3
"""
Comprehensive GPIO Pin Test for Raspberry Pi
Tests all GPIO pins internally to check if the Pi's GPIO subsystem is working.
"""
import time
import sys

# Try lgpio first (modern library for Pi 5/Bookworm), fall back to RPi.GPIO
try:
    import lgpio
    USE_LGPIO = True
    print("Using lgpio library (modern, Pi 5 compatible)")
except ImportError:
    try:
        import RPi.GPIO as GPIO
        USE_LGPIO = False
        print("Using RPi.GPIO library")
    except ImportError:
        print("ERROR: No GPIO library available. Install lgpio or RPi.GPIO")
        sys.exit(1)

# All usable GPIO pins on the 40-pin header (BCM numbering)
# Excludes: GPIO0, GPIO1 (I2C EEPROM), 3.3V, 5V, GND pins
ALL_GPIO_PINS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

# Special pins that may have specific functions
SPECIAL_PINS = {
    2: "I2C SDA (has pull-up)",
    3: "I2C SCL (has pull-up)", 
    14: "UART TX",
    15: "UART RX",
    7: "SPI CE1",
    8: "SPI CE0",
    9: "SPI MISO",
    10: "SPI MOSI",
    11: "SPI SCLK",
    12: "PWM0",
    13: "PWM1",
    18: "PWM0 (ALT)",
    19: "PWM1 (ALT)",
}


class GPIOTester:
    def __init__(self):
        self.h = None
        self.results = {}
        
    def setup(self):
        if USE_LGPIO:
            try:
                self.h = lgpio.gpiochip_open(0)
                print(f"Opened GPIO chip 0 successfully")
                return True
            except Exception as e:
                # Try chip 4 for Pi 5
                try:
                    self.h = lgpio.gpiochip_open(4)
                    print(f"Opened GPIO chip 4 successfully (Pi 5)")
                    return True
                except:
                    print(f"ERROR: Could not open GPIO chip: {e}")
                    return False
        else:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            return True
    
    def cleanup(self):
        if USE_LGPIO and self.h is not None:
            try:
                lgpio.gpiochip_close(self.h)
            except:
                pass
        elif not USE_LGPIO:
            GPIO.cleanup()
    
    def test_pin_output(self, pin):
        """Test if a pin can be configured as output and set high/low"""
        try:
            if USE_LGPIO:
                # Claim as output, initial low
                lgpio.gpio_claim_output(self.h, pin, 0)
                time.sleep(0.01)
                
                # Set high and verify we can write
                lgpio.gpio_write(self.h, pin, 1)
                time.sleep(0.01)
                
                # Set low
                lgpio.gpio_write(self.h, pin, 0)
                time.sleep(0.01)
                
                # Free the pin
                lgpio.gpio_free(self.h, pin)
                return True, "Output OK"
            else:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)
                time.sleep(0.01)
                GPIO.output(pin, GPIO.LOW)
                time.sleep(0.01)
                GPIO.cleanup(pin)
                return True, "Output OK"
                
        except Exception as e:
            return False, f"Output FAIL: {e}"
    
    def test_pin_input(self, pin):
        """Test if a pin can be configured as input and read"""
        try:
            if USE_LGPIO:
                # Claim as input with pull-down
                lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_DOWN)
                time.sleep(0.02)
                val_down = lgpio.gpio_read(self.h, pin)
                lgpio.gpio_free(self.h, pin)
                
                # Claim as input with pull-up
                lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_UP)
                time.sleep(0.02)
                val_up = lgpio.gpio_read(self.h, pin)
                lgpio.gpio_free(self.h, pin)
                
                # With pull-down should read 0, with pull-up should read 1
                if val_down == 0 and val_up == 1:
                    return True, "Input OK (pull-up/down working)"
                elif val_down == 0:
                    return True, "Input OK (pull-down works, pull-up may have issue)"
                elif val_up == 1:
                    return True, "Input OK (pull-up works, pull-down may have issue)"
                else:
                    return False, f"Input issue: pull-down={val_down}, pull-up={val_up}"
                    
            else:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                time.sleep(0.02)
                val_down = GPIO.input(pin)
                
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                time.sleep(0.02)
                val_up = GPIO.input(pin)
                
                GPIO.cleanup(pin)
                
                if val_down == 0 and val_up == 1:
                    return True, "Input OK (pull-up/down working)"
                elif val_down == 0:
                    return True, "Input OK (pull-down works)"
                elif val_up == 1:
                    return True, "Input OK (pull-up works)"
                else:
                    return False, f"Input issue: pull-down={val_down}, pull-up={val_up}"
                    
        except Exception as e:
            return False, f"Input FAIL: {e}"
    
    def test_pin_stuck(self, pin):
        """Check if a pin appears to be stuck high or low"""
        try:
            if USE_LGPIO:
                # Read with no pull resistor (floating)
                lgpio.gpio_claim_input(self.h, pin, lgpio.SET_PULL_NONE)
                time.sleep(0.02)
                readings = []
                for _ in range(5):
                    readings.append(lgpio.gpio_read(self.h, pin))
                    time.sleep(0.005)
                lgpio.gpio_free(self.h, pin)
                
                # A floating pin might fluctuate; a stuck pin won't
                if all(r == 1 for r in readings):
                    return "WARNING: May be stuck HIGH or externally pulled up"
                elif all(r == 0 for r in readings):
                    return "WARNING: May be stuck LOW or externally pulled down"
                else:
                    return "Floating (normal)"
            else:
                GPIO.setup(pin, GPIO.IN)
                time.sleep(0.02)
                readings = []
                for _ in range(5):
                    readings.append(GPIO.input(pin))
                    time.sleep(0.005)
                GPIO.cleanup(pin)
                
                if all(r == 1 for r in readings):
                    return "WARNING: May be stuck HIGH"
                elif all(r == 0 for r in readings):
                    return "Note: Reading LOW (may be floating)"
                else:
                    return "Floating (normal)"
                    
        except Exception as e:
            return f"Check failed: {e}"
    
    def run_full_test(self, pins=None):
        """Run comprehensive test on all or specified pins"""
        if pins is None:
            pins = ALL_GPIO_PINS
        
        print("\n" + "="*70)
        print("RASPBERRY PI GPIO COMPREHENSIVE TEST")
        print("="*70)
        
        if not self.setup():
            return
        
        passed = 0
        failed = 0
        warnings = 0
        
        print(f"\nTesting {len(pins)} GPIO pins...\n")
        print(f"{'Pin':<6} {'Special Function':<25} {'Output':<15} {'Input':<35} {'Float Check'}")
        print("-" * 120)
        
        for pin in pins:
            special = SPECIAL_PINS.get(pin, "-")
            
            # Test output
            out_ok, out_msg = self.test_pin_output(pin)
            
            # Test input
            in_ok, in_msg = self.test_pin_input(pin)
            
            # Check if stuck
            stuck_msg = self.test_pin_stuck(pin)
            
            # Determine status
            if out_ok and in_ok:
                status = "✓ PASS"
                passed += 1
            else:
                status = "✗ FAIL"
                failed += 1
            
            if "WARNING" in stuck_msg:
                warnings += 1
            
            # Color coding for terminal
            if out_ok and in_ok:
                color = "\033[92m"  # Green
            else:
                color = "\033[91m"  # Red
            reset = "\033[0m"
            
            print(f"GPIO {pin:<3} {special:<25} {out_msg:<15} {in_msg:<35} {stuck_msg}")
            
            self.results[pin] = {
                'output': (out_ok, out_msg),
                'input': (in_ok, in_msg),
                'stuck': stuck_msg
            }
        
        print("-" * 120)
        print(f"\n{'='*70}")
        print("SUMMARY")
        print("="*70)
        print(f"Pins Tested: {len(pins)}")
        print(f"Passed:      {passed}")
        print(f"Failed:      {failed}")
        print(f"Warnings:    {warnings}")
        
        if failed == 0:
            print("\n✓ All GPIO pins appear to be functioning correctly!")
            print("  The internal GPIO hardware seems healthy.")
        else:
            print(f"\n✗ {failed} pin(s) failed testing!")
            print("  This could indicate:")
            print("  - Damaged GPIO pin(s)")
            print("  - External hardware still connected")
            print("  - Pin in use by another process/driver")
            
        if warnings > 0:
            print(f"\n⚠ {warnings} warning(s) detected")
            print("  Pins may have external connections or pull resistors")
        
        self.cleanup()
        return self.results


def check_gpio_chip_info():
    """Get information about available GPIO chips"""
    print("\n" + "="*70)
    print("GPIO CHIP INFORMATION")
    print("="*70)
    
    if USE_LGPIO:
        for chip_num in range(5):
            try:
                h = lgpio.gpiochip_open(chip_num)
                info = lgpio.gpio_get_chip_info(h)
                print(f"Chip {chip_num}: {info}")
                lgpio.gpiochip_close(h)
            except Exception as e:
                if chip_num == 0:
                    print(f"Chip {chip_num}: Not available ({e})")
    else:
        print("Using RPi.GPIO - chip info not available")
        print(f"RPi.GPIO version: {GPIO.VERSION}")
        try:
            print(f"Pi Revision: {GPIO.RPI_INFO}")
        except:
            pass


def check_system_info():
    """Check system information relevant to GPIO"""
    print("\n" + "="*70)
    print("SYSTEM INFORMATION")
    print("="*70)
    
    # Check Pi model
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().strip('\x00')
            print(f"Pi Model: {model}")
    except:
        print("Pi Model: Unknown")
    
    # Check kernel
    try:
        import subprocess
        result = subprocess.run(['uname', '-r'], capture_output=True, text=True)
        print(f"Kernel: {result.stdout.strip()}")
    except:
        pass
    
    # Check for GPIO conflicts
    try:
        import subprocess
        result = subprocess.run(['lsmod'], capture_output=True, text=True)
        gpio_modules = [line for line in result.stdout.split('\n') 
                       if 'gpio' in line.lower() or 'pwm' in line.lower() or 'spi' in line.lower() or 'i2c' in line.lower()]
        if gpio_modules:
            print("\nGPIO-related kernel modules loaded:")
            for mod in gpio_modules:
                print(f"  {mod.split()[0]}")
    except:
        pass


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("#  RASPBERRY PI GPIO DIAGNOSTIC TOOL")
    print("#  Tests internal GPIO functionality without external wiring")
    print("#"*70)
    
    # Check system info first
    check_system_info()
    check_gpio_chip_info()
    
    # Run the main GPIO test
    tester = GPIOTester()
    
    # Check if user wants to test specific pins
    if len(sys.argv) > 1:
        try:
            pins = [int(p) for p in sys.argv[1:]]
            print(f"\nTesting specific pins: {pins}")
            tester.run_full_test(pins)
        except ValueError:
            print("Usage: python gpio_full_test.py [pin1 pin2 ...]")
            print("Example: python gpio_full_test.py 12 18 19")
    else:
        tester.run_full_test()
    
    print("\nTest complete!")
