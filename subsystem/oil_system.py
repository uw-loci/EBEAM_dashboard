# oil_system.py
import tkinter as tk
from tkinter import font as tkFont
import math

class TemperatureBar(tk.Canvas):
    def __init__(self, parent, name: str, height: int = 200, width: int = 45):
        super().__init__(parent, height=height, width=width, highlightthickness=0)
        self.name = name
        self.height = height
        self.width = width
        self.bar_width = 20
        self.value = 0

        self.pack_propagate(False)
        
        # Create title
        self.create_text(
            0, 
            8, 
            text=name, 
            font=('Arial', 8, 'bold'), 
            anchor='w'
        )

        # Create initial value display
        self.create_text(
            width + 26, 
            8, 
            text="--°C",
            font=('Arial', 8, 'bold'),
            anchor='e',  # Left-align the value
            tags='value'
        )
        
        # Create scale
        self.create_scale()
        
    def create_scale(self):
        # Scale line
        scale_x = self.width - 15
        top_y = 23
        bottom_y = self.height - 25
        scale_height = bottom_y - top_y
        
        self.create_line(scale_x, top_y, scale_x, bottom_y)
        
        # Scale marks and labels
        for i in range(0, 101, 20):
            y = bottom_y - (i/100) * scale_height
            self.create_line(scale_x-2, y, scale_x+2, y)
            
            # Add offset for "0" label
            label_y = y
            if i == 0:  # For the "0" label only
                label_y = y - 4  # Move it up by 4 pixels
            
            self.create_text(
                scale_x-6, 
                label_y, 
                text=str(i), 
                anchor='e', 
                font=('Arial', 7),
                tags='scale_labels'
            )
            
        self.scale_top = top_y
        self.scale_bottom = bottom_y
        
    def update_value(self, value: float):
        """Update the temperature bar with a new value."""
        self.delete('bar')
        
        # Calculate bar height
        bar_height = ((value/100) * (self.scale_bottom - self.scale_top))
        
        # Calculate color based on temperature
        color = self.get_temperature_color(value)
        
        # Draw bar
        self.create_rectangle(
            10,
            self.scale_bottom - bar_height,
            10 + self.bar_width,
            self.scale_bottom,
            fill=color,
            tags='bar'
        )
        
        # Ensure labels stay on top of the bar
        self.tag_raise('scale_labels')

        # Update value label
        self.delete('value')
        self.create_text(
            self.width + 26, 
            8,
            text=f"{value:.1f}°C",
            font=('Arial', 8, 'bold'),
            anchor='e',
            tags='value'
        )
        
    def get_temperature_color(self, temp: float) -> str:
        """Return a color based on temperature value."""
        if temp < 30:
            return '#0000FF'  # Blue for cold
        elif temp < 50:
            return '#00FF00'  # Green for normal
        elif temp < 70:
            return '#FFA500'  # Orange for warm
        else:
            return '#FF0000'  # Red for hot

class PressureGauge(tk.Canvas):
    def __init__(self, parent, **kwargs):
        # Extract custom parameters, use defaults if not provided
        self.min_value = kwargs.pop('min_value', 0)
        self.max_value = kwargs.pop('max_value', 10)
        self.major_ticks = kwargs.pop('major_ticks', 11)
        self.radius = kwargs.pop('radius', 120)
        self.width = kwargs.pop('width', 300)
        self.height = kwargs.pop('height', 200)
        
        # Initialize canvas
        super().__init__(parent, width=self.width, height=self.height, 
                        bg=parent.cget('bg'), highlightthickness=0)
        
        # Gauge parameters
        self.center_x = self.width // 2
        self.center_y = self.height // 2 + 10
        self.start_angle = 150   # Start from 30 degrees after horizontal
        self.end_angle = 30    # End at 150 degrees
        self.current_value = 0
        
        self.draw_gauge()
        self.create_text(self.center_x, self.height - 45, 
                        text="Oil Pressure", font=('Helvetica', 10, 'bold'))

    def draw_gauge(self):
        """Draw the basic gauge elements"""
        self.delete("gauge")
        
        outer_radius = self.radius
        inner_radius = self.radius * 0.80
        bg_color = self.cget('bg')
        
        # Draw the background arc (white/light gray)
        arc_width = (outer_radius - inner_radius)
        mid_radius = (outer_radius + inner_radius) / 2
        
        # Draw colored ranges - 10 equal segments
        segment_count = 10
        overlap = 2  # Add half a degree overlap between segments
        total_span = 120 + (segment_count - 1) * overlap  # Adjust total span to account for overlaps
        segment_span = total_span / segment_count

        for i in range(segment_count):
            intensity = i / (segment_count - 1)  # 0 to 1
            start = self.start_angle - (i * (segment_span - overlap))
            extent = -segment_span
            color = self.get_gradient_color(intensity)
            
            self.create_arc(
                self.center_x - mid_radius,
                self.center_y - mid_radius,
                self.center_x + mid_radius,
                self.center_y + mid_radius,
                start=start,
                extent=extent,
                style="arc",
                width=arc_width,
                outline=color,
                tags="gauge"
            )
        
        # Draw outer and inner border arcs
        self.create_arc(
            self.center_x - outer_radius,
            self.center_y - outer_radius,
            self.center_x + outer_radius,
            self.center_y + outer_radius,
            start=self.start_angle,
            extent=-120,
            style="arc",
            width=2,
            outline='black',
            tags="gauge"
        )
        
        self.create_arc(
            self.center_x - inner_radius,
            self.center_y - inner_radius,
            self.center_x + inner_radius,
            self.center_y + inner_radius,
            start=self.start_angle,
            extent=-120,
            style="arc",
            width=2,
            outline='black',
            tags="gauge"
        )
        
        # Draw tick marks and labels
        for i in range(self.major_ticks):
            value = self.min_value + (self.max_value - self.min_value) * i / (self.major_ticks - 1)
            angle = math.radians(self.start_angle - (120 * i / (self.major_ticks - 1)))
            
            # Calculate points for tick marks
            outer_x = self.center_x + outer_radius * math.cos(angle)
            outer_y = self.center_y - outer_radius * math.sin(angle)
            inner_x = self.center_x + (inner_radius) * math.cos(angle)
            inner_y = self.center_y - (inner_radius) * math.sin(angle)
            
            # Draw tick mark
            self.create_line(outer_x, outer_y, inner_x, inner_y, 
                           width=2, tags="gauge", fill='black')
            
            # Add label
            label_radius = outer_radius + 15
            label_x = self.center_x + label_radius * math.cos(angle)
            label_y = self.center_y - label_radius * math.sin(angle)
            self.create_text(label_x, label_y, text=str(int(value)), 
                           font=('Helvetica', 8), tags="gauge")
        
        self.draw_needle(self.current_value)


    def get_gradient_color(self, intensity):
        """Get color for gradient from green to red"""
        red = int(255 * intensity)
        green = int(255 * (1 - intensity))
        return f'#{red:02x}{green:02x}00'
    
    def draw_needle(self, value):
        """Draw the needle pointing to the specified value"""
        self.delete("needle")
        
        # Calculate angle for the current value
        angle_range = 120
        value_range = self.max_value - self.min_value
        angle = math.radians(self.start_angle - 
                           (angle_range * (value - self.min_value) / value_range))
        
        # Calculate needle points
        needle_length = self.radius * 0.9
        back_length = self.radius * 0.2
        
        # Needle tip
        tip_x = self.center_x + needle_length * math.cos(angle)
        tip_y = self.center_y - needle_length * math.sin(angle)
        
        # Needle back
        back_angle = angle + math.pi
        back_x = self.center_x + back_length * math.cos(back_angle)
        back_y = self.center_y - back_length * math.sin(back_angle)
        
        # Draw needle
        self.create_line(back_x, back_y, tip_x, tip_y, 
                        fill='red', width=2, tags="needle")
        
        # Draw center hub
        hub_radius = 5
        self.create_oval(self.center_x - hub_radius, 
                        self.center_y - hub_radius,
                        self.center_x + hub_radius, 
                        self.center_y + hub_radius,
                        fill='red', tags="needle")
    
    def set(self, value):
        """Update the gauge to show the specified value"""
        # Constrain value to valid range
        self.current_value = max(self.min_value, min(value, self.max_value))
        self.draw_needle(self.current_value)


class OilSubsystem:
    def __init__(self, parent, logger=None):
        self.parent = parent
        self.logger = logger
        self._pressure = 3.5 # TODO: Remove this. mock only
        self._temperature = 30.0 # remove this. mock only
        self.setup_gui()
        self.read_sensor_data()

    def setup_gui(self):
        self.frame = tk.Frame(self.parent)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Frame for the temperature gauge
        temp_frame = tk.Frame(self.frame, width=70)
        temp_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(15, 0))
        temp_frame.pack_propagate(False)

        self.temp_gauge = TemperatureBar(temp_frame, "Temp:")
        self.temp_gauge.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0,0))

        # Frame for the oil pressure gauge
        dial_frame = tk.Frame(self.frame)
        dial_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=0)

        # Create and configure the dial
        self.oil_gauge = PressureGauge(
            dial_frame,
            min_value=0,
            max_value=10,
            major_ticks=11,
            width=175,
            height=200,
            radius=80
        )
        self.oil_gauge.pack(padx=0, pady=5)

    def update_oil_pressure(self, new_pressure):
        """Update the dial to reflect new oil pressure readings."""
        if 0 <= new_pressure <= 10:  # Ensure the value is within the valid range
            self.oil_gauge.set(new_pressure)
        else:
            print("Received out-of-range oil pressure value:", new_pressure)

    def update_oil_temperature(self, new_temperature):
        """Update the temperature gauge to reflect new oil temperature readings."""
        self.temp_gauge.update_value(new_temperature)

    def read_sensor_data(self):
        """Simulate reading from a sensor."""
        # TODO: Implement this
        import random
        # Random walk simulation
        self._pressure += random.uniform(-0.2, 0.2)
        self._pressure = max(0, min(10, self._pressure))
        
        self._temperature += random.uniform(-1.0, 1.0)
        self._temperature = max(50, min(90, self._temperature))
        
        self.update_oil_pressure(self._pressure)
        self.update_oil_temperature(self._temperature)
        
        self.parent.after(500, self.read_sensor_data)
