# DP16 Driver Documentation:


The DP16Pt process monitors are being used to extract important temperature readings from various locations of the printer. Currently, there are 6 different monitors to display real-time information related to the Solenoids, top and bottom of the chamber, and air temperature.  This information is being communicated over RS-485 through Modbus.




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
Because we have multiple monitors and are trying to communicate to them over one serial port, we will be using RS-485 and Modbus communication protocols.


Important Feature Code:


0x03 - Read Holding Registers
This code is used when calling the .read_holding_registers() method on a pyModbus SerialClient object.


```python
client.read_holding_registers(
    address=register_location,
    count=number_of_registers,
    slave=unit
)
```


0x04 - Read Input Registers
This code is used to read the input registers, input registers generally contain information to how the monitor is configured.


```python
client.read_input_registers(
    address=register_location,
    count=number_of_registers,
    slave=unit
)
```


0x10 - Write
This is used to write to mutable registers. This is most used to write in config specs to make sure the monitor is working as expected.


```python
client.write_register(
        address=register_location,
        value=val,
        slave=unit
    )


```


### Packages


PC to Master
| Byte Offset |  Size   | Description                          |
|-------------|-------------------------|--------------------------------------|
| +0          |  1 byte | Slave address                        |
| +1          |  1 byte | Function Code          |
| +2          |  1 byte | Register address       |
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




### Interactions with Registers


Follow is all the commands that are need to be sent, to each unit


Firstly on start up we write to register 0x0248 the READING_CONFIG, to make sure that the decimal is placed in the right location. Directly following this we write to the STATUS register at 0x0240 to make sure the monitor is in run mode.


After this we read 2 registers in the read process.


Firstly, we read what the STATUS register is, receiving a 0x0006 indicates that the monitor is in the running state and has not incurred any errors. Likely if an error has happened, take for example a loss of connection with the sensor, the monitor will switch to the operating state, this is indicated with receiving a 0x000A. If this is the case this information is sent to the frontend and is indicated with an orange bar.


After checking the STATUS register, we check the PROCCESS_VAL register. Which we have one of two outcomes, either the package is received and the information is sent to the frontend to update the thermometer, or the package is not received and will have to wait till the next clock cycle to retrieve the temperature data.

