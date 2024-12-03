import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, LogFormatterExponent

# Data: tuples of (heater current [A], emission current [A])
data = [
    (6.063635202489499, 3.5634435379830975e-7),
    (7.313077126277623, 0.0004097450160926957),
    (8.000853442945596, 0.003609566092382709),
    (8.551488154850544, 0.011841289422557685),
    (9.005657688098534, 0.03626227722650753),
    (9.460323611631207, 0.057213732751388344),
    (9.942401309773663, 0.1124463385705633),
    (9.969785507145406, 0.1453268127546631),
    (10.479578329516062, 0.23723784436234613),
    (10.493173907868801, 0.3068218594573748),
    (11.016672617544348, 0.5590162481568721),
    (11.512814707086187, 0.7595590289861436),
    (11.99505786865687, 1.19674864245435),
    (12.33930453108535, 2.2002182031514392),
    (12.38089100604667, 1.6351410760506893)
]

I_data = np.array([point[0] for point in data])
V_data = np.array([point[1] for point in data])

# Ensure x data (I_data) is strictly increasing
sorted_indices = np.argsort(I_data)
I_data = I_data[sorted_indices]
V_data = V_data[sorted_indices]

# Plot the data and the linear interpolation
fig, ax = plt.subplots()

ax.scatter(I_data, V_data, label='ES-440 Data')
ax.plot(I_data, V_data, label='Linear Interpolation', color='red')
ax.set_xlabel('Heater Current [A]')
ax.set_xlim(3.5, 13.0)

# Move y-axis to the right side and set it to logarithmic scale
ax.yaxis.set_label_position("right")
ax.yaxis.tick_right()
ax.set_yscale('log')
ax.set_ylim(6e-8, 80)
ax.set_ylabel('Emission Current [A]')
ax.grid(True)

# Set y-axis ticks to show intermediate points
#ax.yaxis.set_major_locator(LogLocator(base=10.0, numticks=10))
#ax.yaxis.set_major_formatter(LogFormatterExponent(base=10.0))
ax.yaxis.set_minor_locator(LogLocator(subs='auto', numticks=10))

# Add legend
ax.legend(loc='upper left')

plt.show()