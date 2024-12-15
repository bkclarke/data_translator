import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import json
import os
import socket
import threading
import time

# Global variables
stop_event = threading.Event()  # Event to stop the listener thread
stopped_flag = threading.Event()  # Event to stop blinking indicators
listener_thread = None
listener_running = False  # Track if the listener is running
lock = threading.Lock()  # Lock for thread safety
file_path = ""
calibration_data = {}
udp_host = '0.0.0.0'  # Default UDP host
udp_receive_port = 16008  # Default receive port for Fluorometer
udp_broadcast_port = 16009  # Default broadcast port for Fluorometer
udp_receive_port_par = 16010  # Default receive port for PAR
udp_broadcast_port_par = 16011  # Default broadcast port for PAR

# Function to load calibration data from a JSON file
def load_calibration(file_path):
    if not os.path.isfile(file_path):  # Check if the file exists
        messagebox.showerror("Error", f"File '{file_path}' not found!")
        return None
    
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            return data
    except json.JSONDecodeError:
        messagebox.showerror("Error", "Error parsing the calibration JSON file! Please check the file format.")
        return None
    except Exception as e:
        messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        return None

# Function to save calibration data back to the JSON file
def save_calibration(file_path, calibration_data):
    try:
        with open(file_path, 'w') as file:
            json.dump(calibration_data, file, indent=4)
        messagebox.showinfo("Success", "Calibration data saved successfully.")
    except Exception as e:
        messagebox.showerror("Error", f"Error saving calibration file: {e}")

# Function to update calibration data when the user modifies the fields
def update_calibration():
    global calibration_data  # Ensure that the global calibration_data is used

    try:
        scale_factor = float(scale_factor_entry.get())
        dark_counts = float(dark_counts_entry.get())
        multiplier = float(multiplier_entry.get())
        calibration_constant = float(calibration_constant_entry.get())
        offset = float(offset_entry.get())
        
        calibration_data["fluorometer"] = {
            "scale_factor": scale_factor,
            "dark_counts": dark_counts
        }

        calibration_data["par"] = {
            "multiplier": multiplier,
            "calibration_constant": calibration_constant,
            "offset": offset
        }

        save_calibration(file_path, calibration_data)

    except ValueError:
        messagebox.showerror("Input Error", "Please enter valid numeric values for the calibration coefficients.")

# Function to populate the fields with the current calibration data
def populate_fields():
    global calibration_data  # Ensure that the global calibration_data is used

    if "fluorometer" not in calibration_data or "par" not in calibration_data:
        messagebox.showerror("Error", "Calibration data is missing required fields.")
        return

    scale_factor_entry.delete(0, tk.END)
    scale_factor_entry.insert(0, calibration_data["fluorometer"]["scale_factor"])
    
    dark_counts_entry.delete(0, tk.END)
    dark_counts_entry.insert(0, calibration_data["fluorometer"]["dark_counts"])

    multiplier_entry.delete(0, tk.END)
    multiplier_entry.insert(0, calibration_data["par"]["multiplier"])

    calibration_constant_entry.delete(0, tk.END)
    calibration_constant_entry.insert(0, calibration_data["par"]["calibration_constant"])

    offset_entry.delete(0, tk.END)
    offset_entry.insert(0, calibration_data["par"]["offset"])

# Function to open a file dialog and select a file path
def select_file():
    global file_path, calibration_data  # Ensure that the global variables are used
    file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
    
    if file_path:
        calibration_data = load_calibration(file_path)  # Update the global calibration_data
        if calibration_data is not None:
            populate_fields()

# Function to update the status of the indicators
def update_indicator(light, color):
    light.config(bg=color)

# Function to create the blinking circle (one-time blink)
def blink_circle(canvas, circle_id, color1="green", color2="red", blink_duration=500):
    current_color = canvas.itemcget(circle_id, "fill")
    new_color = color1 if current_color == color2 else color2
    canvas.itemconfig(circle_id, fill=new_color)
    
    canvas.after(blink_duration, canvas.itemconfig, circle_id, {"fill": color2})  # Reverts to red after blink_duration

# UDP Listening and Broadcasting Script
def load_calibration_data_for_udp():
    global file_path
    return load_calibration(file_path)

def calibrate_fluorometer(raw_data, calibration_params):
    scale_factor = calibration_params["scale_factor"]
    dark_counts = calibration_params["dark_counts"]
    processed_data = scale_factor * (raw_data - dark_counts)
    return processed_data

def calibrate_par(voltage, calibration_params):
    multiplier = calibration_params["multiplier"]
    calibration_constant = calibration_params["calibration_constant"]
    offset = calibration_params["offset"]

    # Calculate the PAR value based on the provided equation
    par_value = multiplier * ((109 * 10 ** (voltage - offset)) / calibration_constant)
    return par_value

def generate_nmea_sentence(sensor_type, raw_data, processed_data, timestamp):
    if sensor_type == 'fluorometer':
        sentence = f"$FLUO,{raw_data:.2f},{processed_data:.2f},{timestamp}"
    elif sensor_type == 'par':
        sentence = f"$PAR,{raw_data:.2f},{processed_data:.2f},{timestamp}"
    else:
        raise ValueError("Unknown sensor type")
    
    checksum = 0
    for char in sentence[1:]:
        checksum ^= ord(char)
    checksum_str = f"{checksum:02X}"
    return f"{sentence}*{checksum_str}"

# The actual listening function for UDP data
def listen_udp(host, port, stop_event, received_indicator_canvas, received_circle, broadcasted_indicator_canvas, broadcasted_circle, stopped_flag, lock, sensor_type="fluorometer"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"Listening on {host}:{port} for UDP packets...")

    # Set a timeout on the socket so it will not block indefinitely
    sock.settimeout(1)  # Timeout in seconds

    while not stop_event.is_set():
        try:
            raw_data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
            parsed_values = raw_data.decode('utf-8').strip().split(',')
            voltage = float(parsed_values[6])  # Assuming voltage is the 7th element
            print(f"Extracted voltage value: {voltage}")
            blink_circle(received_indicator_canvas, received_circle, blink_duration=500)  # Blink when data is received
            process_and_broadcast_data(voltage, broadcasted_indicator_canvas, broadcasted_circle, stopped_flag, sensor_type)
        except socket.timeout:
            # Handle socket timeout, which allows us to check the stop_event
            continue
        except (ValueError, IndexError) as e:
            print(f"Error parsing data: {e}. Ignoring message.")
    
    sock.close()  # Close the socket when finished
    print("Listener thread stopped.")

def process_and_broadcast_data(voltage, broadcasted_indicator_canvas, broadcasted_circle, stopped_flag, sensor_type="fluorometer"):
    calibration_data = load_calibration_data_for_udp()
    if calibration_data is None:
        return

    # Process the fluorometer or PAR data
    if sensor_type == "fluorometer":
        processed_data = calibrate_fluorometer(voltage, calibration_data["fluorometer"])
    elif sensor_type == "par":
        processed_data = calibrate_par(voltage, calibration_data["par"])
    
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    
    # Create NMEA sentence for both fluorometer and PAR sensor
    nmea_sentence = generate_nmea_sentence(sensor_type, voltage, processed_data, timestamp)
    broadcast_data(nmea_sentence, broadcasted_indicator_canvas, broadcasted_circle, stopped_flag)

def broadcast_data(nmea_sentence, broadcasted_indicator_canvas, broadcasted_circle, stopped_flag):
    broadcast_ip = '255.255.255.255'  # Broadcast address for the local network
    broadcast_port = udp_broadcast_port if "FLUO" in nmea_sentence else udp_broadcast_port_par  # Determine broadcast port based on sensor type

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(nmea_sentence.encode('utf-8'), ('255.255.255.255', broadcast_port))
    print(f"Broadcasted NMEA sentence: {nmea_sentence}")
    
    blink_circle(broadcasted_indicator_canvas, broadcasted_circle, blink_duration=500)  # Blink when data is broadcasted

# Event-based start/stop for the UDP listener thread
def start_udp_listener(received_indicator_canvas, received_circle, broadcasted_indicator_canvas, broadcasted_circle, status_label, sensor_type="fluorometer"):
    global stop_event, stopped_flag, listener_thread, listener_running, lock
    if listener_running:
        messagebox.showwarning("Warning", "UDP Listener is already running.")
        return

    stop_event.clear()  # Reset the stop event
    stopped_flag.clear()  # Reset the stopped_flag
    listener_running = True
    listener_thread = threading.Thread(target=listen_udp, args=(udp_host, udp_receive_port if sensor_type == "fluorometer" else udp_receive_port_par, stop_event, received_indicator_canvas, received_circle, broadcasted_indicator_canvas, broadcasted_circle, stopped_flag, lock, sensor_type), daemon=True)
    listener_thread.start()

    # Update the status label and icon
    status_label.config(text=f"UDP Listener: {sensor_type} Running", bg="green")

def stop_udp_listener(status_label):
    global stop_event, stopped_flag, listener_thread, listener_running
    if not listener_running:
        messagebox.showwarning("Warning", "UDP Listener is not running.")
        return
    
    stop_event.set()  # Signal the thread to stop
    stopped_flag.set()  # Set stopped_flag to stop the blinking

    # Make sure the thread has finished properly before updating the status label
    try:
        listener_thread.join(timeout=5)  # Wait for up to 5 seconds for the thread to finish
    except RuntimeError as e:
        print(f"Error joining the thread: {e}")
    finally:
        if listener_thread.is_alive():
            print("The listener thread is still running after the timeout.")
            stop_event.set()  # Forcefully stop it if necessary
            listener_thread.join()  # Ensure it stops

        listener_running = False
        status_label.config(text="UDP Listener: Stopped", bg="red")

# Initialize the Tkinter window
root = tk.Tk()
root.title("Calibration Editor with UDP Control")

# Create a tabbed interface (using ttk.Notebook)
notebook = ttk.Notebook(root)
notebook.pack(fill='both', expand=True)

# Calibration Tab
calibration_tab = ttk.Frame(notebook)
notebook.add(calibration_tab, text="Calibration")

# Calibration controls (load, update, save)
load_button = tk.Button(calibration_tab, text="Load Calibration File", command=select_file)
load_button.grid(row=0, columnspan=2)

tk.Label(calibration_tab, text="Fluorometer Scale Factor:").grid(row=1, column=0, sticky="e")
scale_factor_entry = tk.Entry(calibration_tab)
scale_factor_entry.grid(row=1, column=1)

tk.Label(calibration_tab, text="Fluorometer Dark Counts:").grid(row=2, column=0, sticky="e")
dark_counts_entry = tk.Entry(calibration_tab)
dark_counts_entry.grid(row=2, column=1)

tk.Label(calibration_tab, text="PAR Multiplier:").grid(row=3, column=0, sticky="e")
multiplier_entry = tk.Entry(calibration_tab)
multiplier_entry.grid(row=3, column=1)

tk.Label(calibration_tab, text="PAR Calibration Constant:").grid(row=4, column=0, sticky="e")
calibration_constant_entry = tk.Entry(calibration_tab)
calibration_constant_entry.grid(row=4, column=1)

tk.Label(calibration_tab, text="PAR Offset:").grid(row=5, column=0, sticky="e")
offset_entry = tk.Entry(calibration_tab)
offset_entry.grid(row=5, column=1)

save_button = tk.Button(calibration_tab, text="Save Calibration", command=update_calibration)
save_button.grid(row=6, columnspan=2)

# UDP Control Tab
udp_tab = ttk.Frame(notebook)
notebook.add(udp_tab, text="UDP Control")

# Fluorometer UDP Section
received_indicator_canvas = tk.Canvas(udp_tab, width=20, height=20)
received_indicator_canvas.grid(row=0, column=0)
received_circle = received_indicator_canvas.create_oval(5, 5, 15, 15, fill="red")
tk.Label(udp_tab, text="Received (Fluorometer)").grid(row=0, column=1)

broadcasted_indicator_canvas = tk.Canvas(udp_tab, width=20, height=20)
broadcasted_indicator_canvas.grid(row=1, column=0)
broadcasted_circle = broadcasted_indicator_canvas.create_oval(5, 5, 15, 15, fill="red")
tk.Label(udp_tab, text="Broadcasted (Fluorometer)").grid(row=1, column=1)

fluorometer_status_label = tk.Label(udp_tab, text="Fluorometer UDP Listener: Stopped", bg="red", width=20)
fluorometer_status_label.grid(row=2, columnspan=2)

start_button_fluorometer = tk.Button(udp_tab, text="Start UDP Listener (Fluorometer)", command=lambda: start_udp_listener(received_indicator_canvas, received_circle, broadcasted_indicator_canvas, broadcasted_circle, fluorometer_status_label, "fluorometer"))
start_button_fluorometer.grid(row=3, columnspan=2)

stop_button_fluorometer = tk.Button(udp_tab, text="Stop UDP Listener (Fluorometer)", command=lambda: stop_udp_listener(fluorometer_status_label))
stop_button_fluorometer.grid(row=4, columnspan=2)

# PAR UDP Section
received_indicator_canvas_par = tk.Canvas(udp_tab, width=20, height=20)
received_indicator_canvas_par.grid(row=5, column=0)
received_circle_par = received_indicator_canvas_par.create_oval(5, 5, 15, 15, fill="red")
tk.Label(udp_tab, text="Received (PAR)").grid(row=5, column=1)

broadcasted_indicator_canvas_par = tk.Canvas(udp_tab, width=20, height=20)
broadcasted_indicator_canvas_par.grid(row=6, column=0)
broadcasted_circle_par = broadcasted_indicator_canvas_par.create_oval(5, 5, 15, 15, fill="red")
tk.Label(udp_tab, text="Broadcasted (PAR)").grid(row=6, column=1)

par_status_label = tk.Label(udp_tab, text="PAR UDP Listener: Stopped", bg="red", width=20)
par_status_label.grid(row=7, columnspan=2)

start_button_par = tk.Button(udp_tab, text="Start UDP Listener (PAR)", command=lambda: start_udp_listener(received_indicator_canvas_par, received_circle_par, broadcasted_indicator_canvas_par, broadcasted_circle_par, par_status_label, "par"))
start_button_par.grid(row=8, columnspan=2)

stop_button_par = tk.Button(udp_tab, text="Stop UDP Listener (PAR)", command=lambda: stop_udp_listener(par_status_label))
stop_button_par.grid(row=9, columnspan=2)

root.mainloop()




