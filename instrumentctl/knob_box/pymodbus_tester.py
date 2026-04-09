from pymodbus.client import ModbusSerialClient
import time
import logging
logging.basicConfig()
logging.getLogger("pymodbus").setLevel(logging.DEBUG)
logging.getLogger("pymodbus.transaction").setLevel(logging.DEBUG)

"""
This is a simple test script to read input registers from a Modbus slave device using pymodbus.
It is used to test the success rate of register reads while varying BAUD, TIMEOUT, and PACKET SIZE.
"""

PORT = "COM13"      # Change if needed
BAUDRATE = 9600
SLAVE_IDS = [1,2,3,4]
TIMEOUT = 0.3
REGISTER_COUNT = 6

client = ModbusSerialClient(
    port=PORT,
    baudrate=BAUDRATE,
    bytesize=8,
    parity='N',
    stopbits=1,
    timeout=TIMEOUT
)

if not client.connect():
    print("Failed to connect to Modbus device")
    exit(1)

print("Connected")

try:
    slave_id = SLAVE_IDS[0]
    print(f"\n--- Polling Slave {slave_id} ---")

    input_regs_ok = 0
    total_reads = 10

    for i in range(total_reads):
        # ---- Read Input Registers ----
        rr = client.read_input_registers(
            address=0,
            count=REGISTER_COUNT,
            slave=slave_id
        )

        if rr is None:
            print("No response")
        elif rr.isError():
            print("Error response:", rr)
        else:
            input_regs_ok += 1
            raw = rr.encode()            # bytes
            print("Raw bytes:", raw.hex())

        time.sleep(0.1)

    input_regs_pct = (input_regs_ok / total_reads) * 100.0

    print("\n--- Read Success Summary ---")
    print(f"Input registers: {input_regs_ok}/{total_reads} ({input_regs_pct:.1f}%)")

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    client.close()
    print("Connection closed")
