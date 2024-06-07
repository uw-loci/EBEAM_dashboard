import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, LogFormatterExponent

# Data: tuples of (heater current [A], true temperature [K])
data = [
    (6.060869565217391, 1038.1399484306926),
    (7.313768115942029, 1333.2657597581576),
    (8.002173913043478, 1456.3207966568862),
    (8.552898550724636, 1537.5869120654397),
    (9.007246376811594, 1621.2572241486619),
    (9.447826086956521, 1658.2946563528049),
    (9.957246376811595, 1717.4535431670668),
    (9.971014492753623, 1737.0925580154708),
    (10.494202898550723, 1806.0745087578907),
    (10.494202898550723, 1781.5346314572776),
    (11.017391304347825, 1870.1484840401884),
    (11.513043478260869, 1899.8524050858005),
    (11.994927536231883, 1951.6351026940515),
    (12.352898550724637, 2018.0777096114518),
    (12.366666666666665, 1991.0909575886901)
]

I_data = np.array([point[0] for point in data])
temp_data = np.array([point[1] for point in data])

# Ensure x data (I_data) is strictly increasing
sorted_indices = np.argsort(I_data)
I_data = I_data[sorted_indices]
temp_data = temp_data[sorted_indices]

# Plot the data and the linear interpolation
fig, ax1 = plt.subplots()

ax1.scatter(I_data, temp_data, label='Data')
ax1.plot(I_data, temp_data, label='Linear Interpolation', color='red')
ax1.set_xlabel('Heater Current [A]')
ax1.set_xlim(3.5, 13.0)
ax1.set_ylabel('True Temperature [K]')
ax1.set_ylim(900, 2300)
ax1.grid(True)

# Create secondary y-axis for Celsius
ax2 = ax1.twinx()
ax2.set_ylabel('Temperature [°C]')
ax2.set_ylim(900 - 273.15, 2300 - 273.15)  # Convert Kelvin to Celsius

# Add legend
ax1.legend(loc='upper left')

plt.show()