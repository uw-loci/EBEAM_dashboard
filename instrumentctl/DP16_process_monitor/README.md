# DP16 Driver Documentation:


## Purpose and functionality:


The DP16 monitors are being used to extract important tempature readings from various locations of the printer. Currently, their are 6 different monitors to display real-time information related to the Solenoids, top and bottom of chamber, and air tempature.  This information is being communicated over RS-485 through Modbus.


Libraries / Imports:




## Communications:


### Serial Port Configuration
| Setting | Value |
|---------|-------|
| Baud rate | 9600 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Slave Address | 1-6 (supports multiple units) |

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