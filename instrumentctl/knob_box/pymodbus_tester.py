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
    
        for slave_id in SLAVE_IDS:
            print(f"\n--- Polling Slave {slave_id} ---")

            # ---- Read 5 Input Registers (0–4) ----
            rr = client.read_input_registers(
                address=0,
                count=5,
                slave=slave_id
            )
            time.sleep(0.05)

            if rr.isError():
                print("Input register error:", rr)
            else:
                print("Input Registers:", rr.registers)

            # ---- Read 19 Registers (5–23) ----
            rr = client.read_input_registers(
                address=5,
                count=19,
                slave=slave_id
            )
            time.sleep(0.05)

            if rr.isError():
                print("Discrete input error:", rr)
            else:
                print("Discrete Inputs:", rr.registers)

            # Wait 1 second before moving to next slave
            time.sleep(1)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    client.close()
    print("Connection closed")