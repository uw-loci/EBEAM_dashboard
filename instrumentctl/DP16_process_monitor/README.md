# DP16 Driver Documentation:

The DP16Pt process monitors are being used to extract important tempature readings from various locations of the printer. Currently, their are 6 different monitors to display real-time information related to the Solenoids, top and bottom of chamber, and air tempature.  This information is being communicated over RS-485 through Modbus.


### Hardware Specifications
- Manufacturer: Omega
- Model: DP16PT-330-C24
- Datasheet [(link)](https://www.farnell.com/datasheets/2339803.pdf)
- Communication interface: Modbus RTU over RS485
- Resolution: 0.03 °C
- Reading Rate: 20 samples per second

### Serial Port Configuration
| Setting | Value |
|---------|-------|
| Baud rate | 9600 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Slave Address | 1-6 (supports multiple units) |

### Basic Usage
```python
>>> from instrumentctl import DP16ProcessMonitor


>>> monitor = DP16ProcessMonitor(port='COM6', unit_numbers=[1, 3])


>>> connected = monitor.connect()
>>> print(f"Connected: {connected}")

>>> temps = monitor.read_temperatures()
>>> print(temps)
>>> # Should show something like: {1: 23.5, 3: 23.8}

>>> monitor.disconnect()
```

### Modbus communication
Becuase we have multiple monitors and are trying to commincate to them over one serial port, we will be using an RS-485 and Modbus communication protocols.

Important Feature Code:

0x03 - Read Holding Registers
This code is used when calling the .read_holding_registers() method on a pyModbus SerialClient object.

```python
client.read_holding_registers(
    address=register_location,
    count=number_of_registers,
    slave=adress
)
```

0x04 - Read Input Registers
This code is used to read the input registers, inpur registers generally contain information to how the monitor is configured.

```python
client.read_input_registers(
    address=register_location,
    count=number_of_registers,
    slave=adress
)
```

0x10 - Write (idk how this works yet)

### Packages 

PC to Master
| Byte Offset |  Size   | Description                          |
|-------------|-------------------------|--------------------------------------|
| +0          |  1 byte | Slave address                        |
| +1          |  1 byte | Function Code          |
| +2          |  1 byte | Register adress       |
| optional    | N/a     | Writing data/Value |
| +3          |  2 byte |  CRC(Cyclic Redundancy check)         |


Master to PC
PC to Master
| Byte Offset |  Size   | Description                          |
|-------------|-------------------------|--------------------------------------|
| +0          |  1 byte | Slave address                        |
| +1          |  1 byte | Function Code          |
| +2          |  1 byte | Number Of Bytes       |
| optional    | N/a     | Writing data/Value |
| +4          |  2 byte |  CRC(Cyclic Redundancy check)         |