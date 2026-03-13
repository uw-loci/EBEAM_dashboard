from pymodbus.client import ModbusSerialClient
import time

PORT = "COM13"      # Change if needed
BAUDRATE = 9600
SLAVE_IDS = [4]

client = ModbusSerialClient(
    port=PORT,
    baudrate=BAUDRATE,
    bytesize=8,
    parity='N',
    stopbits=1,
    timeout=2
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
    total_reads = 100

    for i in range(total_reads):
        # ---- Read 5 Input Registers (0-4) ----
        rr = client.read_input_registers(
            address=0,
            count=5,
            slave=slave_id
        )

        # if rr.isError():
        #     print(f"[{i + 1}/{total_reads}] Input register error:", rr)
        if not rr.isError():
            input_regs_ok += 1

        time.sleep(0.5)

        # ---- Read 19 Registers (5-23) ----
        rr = client.read_input_registers(
            address=5,
            count=19,
            slave=slave_id
        )

        # if rr.isError():
        #     print(f"[{i + 1}/{total_reads}] Discrete input error:", rr)
        # else:
        if not rr.isError():
            discretes_ok += 1

        time.sleep(0.1)

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
