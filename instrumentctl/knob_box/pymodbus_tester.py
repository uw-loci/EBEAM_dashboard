from pymodbus.client import ModbusSerialClient
import time
import logging
logging.basicConfig()
logging.getLogger("pymodbus").setLevel(logging.DEBUG)
logging.getLogger("pymodbus.transaction").setLevel(logging.DEBUG)

PORT = "COM13"      # Change if needed
BAUDRATE = 9600
SLAVE_IDS = [1,2,3,4]

client = ModbusSerialClient(
    port=PORT,
    baudrate=BAUDRATE,
    bytesize=8,
    parity='N',
    stopbits=1,
    timeout=0.3
)

if not client.connect():
    print("Failed to connect to Modbus device")
    exit(1)

print("Connected")

try:
    slave_id = SLAVE_IDS[0]
    print(f"\n--- Polling Slave {slave_id} ---")

    input_regs_ok = 0
    discretes_ok = 0
    total_reads = 10

    for i in range(total_reads):
        # ---- Read 5 Input Registers (0-4) ----
        rr = client.read_input_registers(
            address=0,
            count=5,
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

        # ---- Read 19 Registers (5-23) ----
        rr = client.read_input_registers(
            address=5,
            count=19,
            slave=slave_id
        )

        if rr is None:
            print("No response")
        elif rr.isError():
            print("Error response:", rr)
        else:
            discretes_ok
            raw = rr.encode()            # bytes
            print("Raw bytes:", raw.hex())

    input_regs_pct = (input_regs_ok / total_reads) * 100.0
    discretes_pct = (discretes_ok / total_reads) * 100.0

    print("\n--- Read Success Summary ---")
    print(f"Input registers: {input_regs_ok}/{total_reads} ({input_regs_pct:.1f}%)")
    print(f"Discrete inputs: {discretes_ok}/{total_reads} ({discretes_pct:.1f}%)")

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    client.close()
    print("Connection closed")
