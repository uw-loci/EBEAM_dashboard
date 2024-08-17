import sys
import time
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from instrumentctl.power_supply_9104 import PowerSupply9104

def profile_command(ps, command_name, *args):
    start_time = time.time()
    result = getattr(ps, command_name)(*args)
    end_time = time.time()
    elapsed_time = (end_time - start_time) * 1000  # Convert to milliseconds
    return result, elapsed_time

def profile_method(method, *args):
    start_time = time.time()
    result = method(*args)
    end_time = time.time()
    elapsed_time = (end_time - start_time) * 1000  # Convert to milliseconds
    return result, elapsed_time

def main():
    if len(sys.argv) != 2:
        print("Usage: python cathode_heating_profiler.py <COM_PORT>")
        sys.exit(1)

    com_port = sys.argv[1]
    ps = PowerSupply9104(port=com_port)

    # Profile initialization sequence
    init_commands = [
        ("set_preset_selection", 3),
        ("get_preset_selection",),
        ("set_over_voltage_protection", "0100"),  
        ("get_over_voltage_protection",),
        ("set_over_current_protection", "0850"),
        ("get_over_current_protection",),
    ]

    print("\nInitialization Sequence Profiling:")
    print("-----------------------------------")
    for command in init_commands:
        command_name = command[0]
        args = command[1:]
        result, elapsed_time = profile_command(ps, command_name, *args)
        print(f"{command_name:<30} {elapsed_time:.2f} ms")
        print(f"  Result: {result}\n")

    # Profile update_data method (simulated)
    def update_data_simulation(ps):
        ps.get_voltage_current_mode()
        ps.get_settings(3)

    print("\nUpdate Data Method Profiling:")
    print("------------------------------")
    result, elapsed_time = profile_method(update_data_simulation, ps)
    print(f"update_data (simulated)        {elapsed_time:.2f} ms")

    # Profile set_target_current method (simulated)
    def set_target_current_simulation(ps, voltage, current):
        ps.set_voltage(3, voltage)
        ps.set_current(3, current)
        ps.get_settings(3)

    print("\nSet Target Current Method Profiling:")
    print("-------------------------------------")
    result, elapsed_time = profile_method(set_target_current_simulation, ps, 5.0, 1.0)  # Example values
    print(f"set_target_current (simulated) {elapsed_time:.2f} ms")

    # Profile initialize_power_supplies method (simulated)
    def initialize_power_supplies_simulation(ps):
        ps.set_preset_selection(3)
        ps.get_preset_selection()
        ps.set_over_voltage_protection("0100")
        ps.get_over_voltage_protection()
        ps.set_over_current_protection("0850")
        ps.get_over_current_protection()

    print("\nInitialize Power Supplies Method Profiling:")
    print("--------------------------------------------")
    result, elapsed_time = profile_method(initialize_power_supplies_simulation, ps)
    print(f"initialize_power_supplies (simulated) {elapsed_time:.2f} ms")

    # Profile other frequently used commands
    other_commands = [
        ("get_output_status",),
        ("set_output", "1"),
        ("set_output", "0"),
        ("get_voltage_current_mode",),
    ]

    print("\nMisc. Commands:")
    print("------------------------------------------")
    for command in other_commands:
        command_name = command[0]
        args = command[1:]
        result, elapsed_time = profile_command(ps, command_name, *args)
        print(f"{command_name:<30} {elapsed_time:.2f} ms")
        print(f"  Result: {result}\n")

    ps.close()

if __name__ == "__main__":
    main()