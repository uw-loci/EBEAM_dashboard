from pymodbus.client import ModbusSerialClient as ModbusClient
import time

client = ModbusClient(
    port="COM5",
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1
)

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
        
response = client.read_holding_registers(
    address=0x210,
    count=2,
    slave=4
)

print(response)

if response and not response.isError():
        temperature = response.registers[0]
        print(temperature)




