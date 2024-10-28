import os 
import sys
# os.chdir("../../instrumentctl")
# os.chdir("")
print(os.getcwd())  # Check if it’s the expected directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)


from instrumentctl.g9_driver import G9Driver
import time

g9 = G9Driver.G9Driver(port='COM11')

responses = []

for _ in range(5):
    try:
        g9.send_command() 

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
