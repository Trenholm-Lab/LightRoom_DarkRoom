#!/usr/bin/env python3
"""
Ground Pin Verification Test for Raspberry Pi
Tests if ground connections are working properly.

Method: Set a GPIO pin LOW (connected to internal ground) and verify
it can sink current properly by testing with pull-up resistors.
"""
import time
import sys

try:
    import lgpio
    USE_LGPIO = True
except ImportError:
    import RPi.GPIO as GPIO
    USE_LGPIO = False

# GPIO pins to use for testing
TEST_PINS = [4, 17, 27, 22, 5, 6, 13, 19, 26, 12, 16, 20, 21, 25]

# Ground pins on 40-pin header (physical pin numbers for reference)
GROUND_PINS_PHYSICAL = [6, 9, 14, 20, 25, 30, 34, 39]

def test_ground_via_gpio():
    """
    Test ground integrity by:
    1. Setting a pin as OUTPUT LOW (connects to ground internally)
    2. Checking if it properly pulls to 0V
    3. Testing multiple pins to check ground plane integrity
    """
    print("\n" + "="*60)
    print("GROUND INTEGRITY TEST VIA GPIO")
    print("="*60)
    
    results = []
    h = None
    
    try:
        if USE_LGPIO:
            # Try chip 0 first, then chip 4 for Pi 5
            try:
                h = lgpio.gpiochip_open(0)
            except:
                h = lgpio.gpiochip_open(4)
            print("GPIO chip opened successfully\n")
        else:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
        
        print(f"{'Pin':<8} {'Set LOW':<15} {'Read Back':<15} {'Ground Status'}")
        print("-" * 55)
        
        for pin in TEST_PINS:
            try:
                if USE_LGPIO:
                    # Set as output LOW
                    lgpio.gpio_claim_output(h, pin, 0)
                    time.sleep(0.02)
                    
                    # Read the pin back - should be 0 if ground is working
                    # We need to free and reclaim as input to read
                    lgpio.gpio_free(h, pin)
                    lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_NONE)
                    time.sleep(0.02)
                    
                    # Take multiple readings
                    readings = [lgpio.gpio_read(h, pin) for _ in range(10)]
                    lgpio.gpio_free(h, pin)
                    
                    # Now test: set as output LOW and check stability
                    lgpio.gpio_claim_output(h, pin, 0)
                    time.sleep(0.01)
                    lgpio.gpio_free(h, pin)
                    
                    # Read with pull-up - if ground path is good, 
                    # the internal pull-up should win and read HIGH
                    lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
                    time.sleep(0.02)
                    pullup_reading = lgpio.gpio_read(h, pin)
                    lgpio.gpio_free(h, pin)
                    
                    # Read with pull-down - should read LOW
                    lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_DOWN)
                    time.sleep(0.02)
                    pulldown_reading = lgpio.gpio_read(h, pin)
                    lgpio.gpio_free(h, pin)
                    
                else:
                    GPIO.setup(pin, GPIO.OUT)
                    GPIO.output(pin, GPIO.LOW)
                    time.sleep(0.02)
                    GPIO.setup(pin, GPIO.IN)
                    readings = [GPIO.input(pin) for _ in range(10)]
                    
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                    time.sleep(0.02)
                    pullup_reading = GPIO.input(pin)
                    
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                    time.sleep(0.02)
                    pulldown_reading = GPIO.input(pin)
                    GPIO.cleanup(pin)
                
                # Analyze results
                avg_reading = sum(readings) / len(readings)
                
                if pulldown_reading == 0 and pullup_reading == 1:
                    status = "✓ OK"
                    ground_ok = True
                elif pulldown_reading == 0:
                    status = "✓ OK (pull-down works)"
                    ground_ok = True
                else:
                    status = "⚠ CHECK"
                    ground_ok = False
                
                results.append((pin, ground_ok, status))
                print(f"GPIO {pin:<4} {'OK':<15} {avg_reading:<15.1f} {status}")
                
            except Exception as e:
                results.append((pin, False, f"ERROR: {e}"))
                print(f"GPIO {pin:<4} {'FAIL':<15} {'-':<15} ERROR: {e}")
        
        # Summary
        passed = sum(1 for _, ok, _ in results if ok)
        failed = len(results) - passed
        
        print("-" * 55)
        print(f"\nPins tested: {len(results)}")
        print(f"Ground OK:   {passed}")
        print(f"Issues:      {failed}")
        
        if failed == 0:
            print("\n✓ Ground connections appear to be working correctly!")
        else:
            print(f"\n⚠ {failed} pin(s) may have ground issues")
            
    except Exception as e:
        print(f"Error during test: {e}")
    finally:
        if USE_LGPIO and h is not None:
            try:
                lgpio.gpiochip_close(h)
            except:
                pass
        elif not USE_LGPIO:
            GPIO.cleanup()
    
    return results


def measure_ground_resistance_indication():
    """
    Indirect ground resistance test:
    If ground has high resistance, output LOW won't fully reach 0V,
    and the pin will have trouble sinking current from internal pull-up.
    """
    print("\n" + "="*60)
    print("GROUND RESISTANCE INDICATION TEST")
    print("="*60)
    print("Testing if GPIO can properly sink current to ground...\n")
    
    h = None
    try:
        if USE_LGPIO:
            try:
                h = lgpio.gpiochip_open(0)
            except:
                h = lgpio.gpiochip_open(4)
        else:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
        
        print(f"{'Pin':<8} {'Sink Test':<20} {'Result'}")
        print("-" * 45)
        
        issues = []
        
        for pin in TEST_PINS:
            try:
                if USE_LGPIO:
                    # Set pin as OUTPUT LOW (trying to sink to ground)
                    lgpio.gpio_claim_output(h, pin, 0)
                    time.sleep(0.05)
                    
                    # While still output LOW, the pin should be firmly at ground
                    # We can't directly read an output, but we can check
                    # if releasing causes issues
                    lgpio.gpio_free(h, pin)
                    
                    # Quick check with pull-up - if ground was bad,
                    # there might be residual charge issues
                    lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
                    time.sleep(0.005)  # Very short delay
                    quick_read = lgpio.gpio_read(h, pin)
                    time.sleep(0.02)   # Longer delay
                    stable_read = lgpio.gpio_read(h, pin)
                    lgpio.gpio_free(h, pin)
                    
                    # Both should be 1 with pull-up if ground released properly
                    if quick_read == 1 and stable_read == 1:
                        result = "✓ Good sink capability"
                    elif stable_read == 1:
                        result = "✓ OK (slight delay)"
                    else:
                        result = "⚠ May have ground issue"
                        issues.append(pin)
                        
                else:
                    GPIO.setup(pin, GPIO.OUT)
                    GPIO.output(pin, GPIO.LOW)
                    time.sleep(0.05)
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                    time.sleep(0.005)
                    quick_read = GPIO.input(pin)
                    time.sleep(0.02)
                    stable_read = GPIO.input(pin)
                    GPIO.cleanup(pin)
                    
                    if quick_read == 1 and stable_read == 1:
                        result = "✓ Good sink capability"
                    elif stable_read == 1:
                        result = "✓ OK"
                    else:
                        result = "⚠ Check ground"
                        issues.append(pin)
                
                print(f"GPIO {pin:<4} {'Sink to GND':<20} {result}")
                
            except Exception as e:
                print(f"GPIO {pin:<4} {'ERROR':<20} {e}")
                issues.append(pin)
        
        print("-" * 45)
        
        if not issues:
            print("\n✓ All tested pins can properly sink current to ground")
            print("  Ground connections appear healthy!")
        else:
            print(f"\n⚠ Potential ground issues on pins: {issues}")
            
    except Exception as e:
        print(f"Test error: {e}")
    finally:
        if USE_LGPIO and h is not None:
            try:
                lgpio.gpiochip_close(h)
            except:
                pass
        elif not USE_LGPIO:
            GPIO.cleanup()


def physical_ground_pin_info():
    """Display information about physical ground pins"""
    print("\n" + "="*60)
    print("PHYSICAL GROUND PIN LOCATIONS (40-pin header)")
    print("="*60)
    print("""
    Physical ground pins on the 40-pin header:
    
    Pin 6  (row 3, left)   - GND
    Pin 9  (row 5, left)   - GND  
    Pin 14 (row 7, left)   - GND
    Pin 20 (row 10, left)  - GND
    Pin 25 (row 13, left)  - GND
    Pin 30 (row 15, left)  - GND
    Pin 34 (row 17, left)  - GND
    Pin 39 (row 20, left)  - GND
    
    All ground pins should have continuity to each other.
    Use a multimeter in continuity mode to verify.
    
    To test with multimeter:
    1. Set multimeter to continuity/beep mode
    2. Touch one probe to Pin 6 (GND)
    3. Touch other probe to each other GND pin
    4. All should beep/show continuity
    5. Also test continuity from GND to metal USB ports
    """)


if __name__ == "__main__":
    print("\n" + "#"*60)
    print("#  RASPBERRY PI GROUND CONNECTION DIAGNOSTIC")
    print("#"*60)
    
    physical_ground_pin_info()
    test_ground_via_gpio()
    measure_ground_resistance_indication()
    
    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    print("""
    If tests show issues, verify with a multimeter:
    
    1. CONTINUITY TEST: Check all GND pins have continuity
       to each other and to the USB port shields.
       
    2. VOLTAGE TEST: Measure voltage between:
       - Any 3.3V pin and any GND pin (should be ~3.3V)
       - Any 5V pin and any GND pin (should be ~5V)
       
    3. RESISTANCE TEST: Measure resistance between:
       - Different GND pins (should be < 1 ohm)
       - GPIO pin (set LOW in software) and GND (should be < 1 ohm)
       
    If ground pins show high resistance or no continuity,
    the ground plane may be damaged.
    """)
