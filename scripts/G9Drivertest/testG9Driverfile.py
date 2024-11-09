import os 
import sys
from instrumentctl.g9_driver import G9Driver
import time

g9 = G9Driver(port='COM11')

responses = []

for _ in range(5):
    try:
        g9.get_interlock_status() 

    except ConnectionError as e:
        print("ConnectionError:", e)
    except ValueError as e:
        print("ValueError:", e)

    print(g9.lastResponse)
    responses.append(g9.lastResponse)

    time.sleep(1)


with open("test.txt", "w") as f:
    for response in responses:
        f.write(f"{response}\n") 
