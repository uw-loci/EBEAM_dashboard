import ctypes
import numpy as np
from picosdk.ps2000a import ps2000a as ps
from picosdk.functions import adc2mV, assert_pico_ok
import os
import csv
import time
import serial
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from instrumentctl.power_supply_9104 import PowerSupply9104

def initialize_scope():
    chandle = ctypes.c_int16()
    status = {}
    status["openunit"] = ps.ps2000aOpenUnit(ctypes.byref(chandle), None)
    assert_pico_ok(status["openunit"])
    return chandle, status

def setup_channel(chandle, channel, channel_range):
    status = ps.ps2000aSetChannel(chandle, channel, 1, 1, channel_range, 0)
    assert_pico_ok(status)
    return status

def capture_block(chandle, channel, voltage_range, samples=5000):
    preTriggerSamples = 0
    postTriggerSamples = samples
    timebase = 8
    timeIntervalns = ctypes.c_float()
    returnedMaxSamples = ctypes.c_int32()
    oversample = ctypes.c_int16(0)
    
    ps.ps2000aGetTimebase2(chandle, timebase, samples, ctypes.byref(timeIntervalns),
                           oversample, ctypes.byref(returnedMaxSamples), 0)
    
    ps.ps2000aRunBlock(chandle, preTriggerSamples, postTriggerSamples, timebase,
                       oversample, None, 0, None, None)
    
    ready = ctypes.c_int16(0)
    while ready.value == 0:
        status = ps.ps2000aIsReady(chandle, ctypes.byref(ready))
    
    buffer = (ctypes.c_int16 * samples)()
    ps.ps2000aSetDataBuffers(chandle, channel, ctypes.byref(buffer), None, samples, 0, 0)
    
    cmaxSamples = ctypes.c_int32(samples)
    overflow = ctypes.c_int16()
    ps.ps2000aGetValues(chandle, 0, ctypes.byref(cmaxSamples), 0, 0, 0, ctypes.byref(overflow))
    
    maxADC = ctypes.c_int16()
    ps.ps2000aMaximumValue(chandle, ctypes.byref(maxADC))
    
    values = adc2mV(buffer, voltage_range, maxADC)
    times = np.linspace(0, (cmaxSamples.value - 1) * timeIntervalns.value, cmaxSamples.value)
    
    return times, values

def characterize_power_supply(voltage_range, step, power_supply, scope_chandle):
    channel = 0  # Channel A
    channel_range = 7  # PS2000A_2V
    setup_channel(scope_chandle, channel, channel_range)
    
    set_voltages = np.arange(0, voltage_range + step, step)
    results = []
    
    for set_voltage in set_voltages:
        if power_supply:
            # Set power supply voltage
            power_supply.set_voltage(3, set_voltage)
            power_supply.set_output(1)  # Turn on output
            time.sleep(0.5)  # Wait for voltage to stabilize
        
        # Measure with PicoScope
        _, values = capture_block(scope_chandle, channel, channel_range)
        measured_voltage = np.mean(values) / 1000  # Convert mV to V
        
        if power_supply:
            # Get actual voltage from power supply
            ps_voltage, _, _ = power_supply.get_voltage_current_mode()
        else:
            ps_voltage = None
        
        results.append({
            'set_voltage': set_voltage,
            'measured_voltage': measured_voltage,
            'ps_reported_voltage': ps_voltage
        })
        
        print(f"Set: {set_voltage:.3f}V, Measured: {measured_voltage:.3f}V, PS Reported: {ps_voltage:.3f}V" if ps_voltage else f"Set: {set_voltage:.3f}V, Measured: {measured_voltage:.3f}V")
    
    return results

def save_to_csv(results, filename='power_supply_characterization.csv'):
    with open(filename, 'w', newline='') as csvfile:
        fieldnames = ['set_voltage', 'measured_voltage', 'ps_reported_voltage']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    
    print(f"Results saved to {filename}")

def find_available_com_ports():
    available_ports = []
    for i in range(256):
        try:
            port = f'COM{i}'
            s = serial.Serial(port)
            available_ports.append(port)
            s.close()
        except serial.SerialException:
            pass
    return available_ports

# Main execution
if __name__ == "__main__":
    power_supply = None
    
    # Try to find and connect to the power supply
    available_ports = find_available_com_ports()
    print(f"Available COM ports: {', '.join(available_ports)}")
    
    for port in available_ports:
        try:
            power_supply = PowerSupply9104(port)
            print(f"Successfully connected to power supply on {port}")
            break
        except serial.SerialException:
            print(f"Failed to connect to power supply on {port}")
    
    if not power_supply:
        print("Warning: No power supply connected. Proceeding with PicoScope measurements only.")
    
    # Initialize PicoScope
    try:
        scope_chandle, _ = initialize_scope()
    except:
        print("Error: Unable to initialize PicoScope. Please check the connection.")
        sys.exit(1)
    
    # Characterization parameters
    voltage_range = 1.4
    step = 0.02 # minimum 9104 power supply 
    
    try:
        results = characterize_power_supply(voltage_range, step, power_supply, scope_chandle)
        save_to_csv(results)
    except Exception as e:
        print(f"An error occurred during characterization: {e}")
    finally:
        if power_supply:
            power_supply.set_output(0)  # Turn off output
            power_supply.close()
        ps.ps2000aStop(scope_chandle)
        ps.ps2000aCloseUnit(scope_chandle)

print("Characterization complete. Check the CSV file for results.")