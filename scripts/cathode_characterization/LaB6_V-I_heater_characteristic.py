import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import UnivariateSpline

# Data for Heater Current vs. Heater Voltage
heater_voltage_current_data = [
    (0, 8.61260838995737E-05),
    (0.19640028122802944, 0.01198382938832876),
    (0.44874150456995565, 0.023881532692758167),
    (1.0892898992266233, 0.05362784157487677),
    (2.234586360440591, 0.1101306538551674),
    (3.3024513709866423, 0.17253925474572274),
    (3.8852214670728844, 0.22003984063744997),
    (4.604776189360207, 0.31494668385282365),
    (4.974314506679168, 0.36536325287086924),
    (5.168943051324117, 0.3979763299742205),
    (5.324527771267871, 0.41873681743613766),
    (5.557937661120226, 0.4513580970236697),
    (5.635762831028828, 0.463218889149285),
    (5.888563393484885, 0.4958442699789076),
    (6.102582610733537, 0.5284614483243493),
    (6.277623623154442, 0.5521871338176703),
    (6.588924302788847, 0.599630302320131),
    (7.367176001874855, 0.7182382235762828),
    (7.9898429810171105, 0.8160856573705177),
    (8.067733770799158, 0.8309075462854463),
    (8.593250527302555, 0.9198511835012888),
    (9.041204593391143, 1.0087784157487696),
    (9.488896179985941, 1.0858612608389966),
    (9.995153503632531, 1.1807229903913754),
    (10.520801499882824, 1.2755888211858446),
    (11.066037028357162, 1.379342043590344),
    (11.572163112256854, 1.4682815795640962),
    (12.020117178345444, 1.557208811811577),
    (12.252542770096086, 1.5454153639594091),
    (12.40845558940708, 1.5809796109678929)
]

I_data = np.array([point[0] for point in heater_voltage_current_data])
V_data = np.array([point[1] for point in heater_voltage_current_data])

# Fit a spline to the data
# spline = UnivariateSpline(I_data, V_data, s=0)  # s=0 ensures the spline goes through all points

# Generate a range of heater currents for plotting
# I_range = np.linspace(min(I_data), max(I_data), 500)
# V_spline = spline(I_range)

# Print the spline coefficients and knots
# coefficients = spline.get_coeffs()
# knots = spline.get_knots()
# print("Spline Coefficients:", coefficients)
# print("Spline Knots:", knots)

# Plot the data and the fitted spline
plt.scatter(I_data, V_data, label='ES-440 Data')
# plt.plot(I_range, V_spline, label='Fitted Spline', color='red')
plt.plot(I_data, V_data, label='Linear Interpolation', color='red')
plt.xlabel('Heater Current [A]')
plt.ylabel('Heater Voltage [V]')
plt.title("ES-440 V-I Characteristic")
plt.xlim(-0.5, 15.0)
plt.ylim(-0.1, 1.9)
plt.grid(visible=True)
plt.legend()
plt.show()