import serial
import time

ser = serial.Serial("COM11", 9600, parity=serial.PARITY_EVEN, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS, timeout=1)
# save data method
def saveData(data, Testnum):
    data = str(data)
    # print(data)
    with open(f'test{Testnum}.txt', "w") as f:
        # this works if it is in hex with or without leading 0x
        # binary = bin(int(data, base=16))[2:]
        f.write(data)

def saveBytes(bytes, Testnum):
    with open(f'bytes{Testnum}.txt', "wb") as f:
        # this works if it is in hex with or without leading 0x
        f.write(bytes)


always = b"0x4000000F4B034D0001"
# sum 00EB
data = b"00000000"
reserve = b"0000"
checkSum = b"00EB"
always2 = b"2A0D"

# message = b"4000000F4B034D000100000000000000EB2A0D"

message = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01\x00\x00\x00\x00\x00\x00\x12\x49\x2A\x0D' 
msg2 = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01\x00\x00\x00\x00\x00\x80\x01\x6B\x2A\x0D'
msg3 = b'\x40\x00\x00\x0F\x4B\x03\x4D\x00\x01\xFF\xFF\xFF\xFF\x00\x00\x04\xE7\x2A\x0D' 
# msg4 = b'\x21\x3a\xe3\x87\x40' 

message_split = [
    0x40,   #Start code
    0x00,
    0x00,
    0x0F,
    0x4B,
    0x03,
    0x3D,
    0X00,
    0X01,
    0x00, 0x00, 0x00, 0x00, # Optional Data
    0x00, 0x00,  #Reserved bytes
    0x00, 0x00EB,
    0x2A,
    0X0D
]



# print(ser.read(size=10))
_ = ser.write(message)
print(message)
print(_)

#data = ser.read_until(b'\x0D')
data = ser.read(size=198)

#print(ser.read(size=10))

ser.close()


print(data)


saveData(data, 2)