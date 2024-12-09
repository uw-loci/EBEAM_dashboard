from pymodbus.client import ModbusSerialClient as ModbusClient
import time

client = ModbusClient(
    port="COM5",
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=.1
)
unit_numbers={1,2,3,4,5}
if not client.is_socket_open():
    try:
        if client.connect():
            time.sleep(0.2)
            if hasattr(client, 'socket'):
                client.socket.reset_input_buffer()
        else:
            print("Failed to connect, no exception thrown")

    except Exception as e:
        print(f'Failed to connect: {e}')

for _ in range(2):
     for unit in unit_numbers:
        status = client.read_holding_registers(
            address=0x240,
            count=1,
            slave=4
        )
        if not status.isError() and status.registers[0] == 6:
            response = client.read_holding_registers(
                address=0x210,
                count=2,
                slave=4
            )
            if response and not response.isError():
                temperature = response.registers[0]
                code = status.registers[0]
                print(temperature, code)


      




