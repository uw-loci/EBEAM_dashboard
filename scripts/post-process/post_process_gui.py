import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
from typing import List, Dict, Any
import os
from pathlib import Path
# Import the post-processing functionality
from post_process import process_files

class LogProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EBEAM Log Post-Processor")
        self.root.geometry("600x300")
        
        # State variables
        self.current_step = 1
        self.selected_files: List[str] = []
        self.data_vars = {
            'voltage': tk.BooleanVar(value=True),
            'current': tk.BooleanVar(value=True),
            'temperature': tk.BooleanVar(value=True),
            'pressure': tk.BooleanVar(value=False)
        }
        self.output_vars = {
            'csv': tk.BooleanVar(value=True),
            'xlsx': tk.BooleanVar(value=False),
            'plot': tk.BooleanVar(value=True)
        }
        self.output_dir = tk.StringVar(value=os.path.join(os.getcwd(), "output"))

        # Create main container
        self.main_container = ttk.Frame(root)
        self.main_container.pack(expand=True, fill='both', padx=20, pady=10)

        # Create and setup the content area
        self.content_frame = ttk.Frame(self.main_container)
        self.content_frame.pack(expand=True, fill='both')

        # Create footer with navigation buttons
        self.footer = ttk.Frame(self.main_container)
        self.footer.pack(fill='x', pady=10)

        # Progress bar
        self.progress_var = tk.IntVar(value=25)
        self.progress = ttk.Progressbar(
            self.main_container,
            variable=self.progress_var,
            maximum=100,
            length=300
        )
        self.progress.pack(pady=10)

        # Navigation buttons
        self.back_btn = ttk.Button(
            self.footer,
            text="← Back",
            command=self.go_back,
            state='disabled'
        )
        self.back_btn.pack(side='left', padx=5)

        self.next_btn = ttk.Button(
            self.footer,
            text="Next →",
            command=self.go_next
        )
        self.next_btn.pack(side='right', padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Select log files to process")
        self.status = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor='w'
        )
        self.status.pack(side='bottom', fill='x')

        # Initialize first step
        self.show_step(1)

    def show_step(self, step: int):
        # Clear current content
        for widget in self.content_frame.winfo_children():
            widget.destroy()

        # Update progress bar
        self.progress_var.set(step * 25)

        if step == 1:
            self.create_file_selection()
            self.status_var.set("Step 1/4: Select log files to process")
            self.back_btn.configure(state='disabled')
            self.next_btn.configure(state='normal', text="Next →")
        
        elif step == 2:
            self.create_data_selection()
            self.status_var.set("Step 2/4: Select data types to extract")
            self.back_btn.configure(state='normal')
            self.next_btn.configure(state='normal', text="Next →")
        
        elif step == 3:
            self.create_output_selection()
            self.status_var.set("Step 3/4: Configure output options")
            self.back_btn.configure(state='normal')
            self.next_btn.configure(state='normal', text="Next →")
        
        elif step == 4:
            self.create_confirmation()
            self.status_var.set("Step 4/4: Confirm and process")
            self.back_btn.configure(state='normal')
            self.next_btn.configure(text="Start Processing")

    def create_file_selection(self):
        frame = ttk.LabelFrame(self.content_frame, text="Select Log Files")
        frame.pack(expand=True, fill='both', padx=10, pady=5)

        # File list
        self.file_listbox = tk.Listbox(frame, selectmode=tk.MULTIPLE)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5))

        # Populate existing selections
        for file in self.selected_files:
            self.file_listbox.insert(tk.END, os.path.basename(file))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="Add Files", command=self.add_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_files).pack(side=tk.LEFT, padx=5)

    def create_data_selection(self):
        frame = ttk.LabelFrame(self.content_frame, text="Select Data Types")
        frame.pack(expand=True, fill='both', padx=10, pady=5)

        for data_type, var in self.data_vars.items():
            ttk.Checkbutton(
                frame,
                text=data_type.capitalize(),
                variable=var
            ).pack(pady=5, padx=10, anchor='w')

    def create_output_selection(self):
        frame = ttk.LabelFrame(self.content_frame, text="Configure Output")
        frame.pack(expand=True, fill='both', padx=10, pady=5)

        # Output formats
        fmt_frame = ttk.LabelFrame(frame, text="Output Formats")
        fmt_frame.pack(fill='x', padx=10, pady=5)
        
        for fmt, var in self.output_vars.items():
            ttk.Checkbutton(
                fmt_frame,
                text=fmt.upper(),
                variable=var
            ).pack(pady=5, padx=10, anchor='w')

        # Output directory
        dir_frame = ttk.LabelFrame(frame, text="Output Directory")
        dir_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Entry(
            dir_frame,
            textvariable=self.output_dir,
            width=50
        ).pack(side=tk.LEFT, padx=5, pady=5)
        
        ttk.Button(
            dir_frame,
            text="Browse...",
            command=self.browse_output_dir
        ).pack(side=tk.LEFT, padx=5, pady=5)

    def create_confirmation(self):
        frame = ttk.LabelFrame(self.content_frame, text="Confirmation")
        frame.pack(expand=True, fill='both', padx=10, pady=5)

        # Summary text
        self.summary_text = tk.Text(frame, height=15, width=60)
        self.summary_text.pack(pady=10, padx=10)
        
        self.update_summary()

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select Log Files",
            filetypes=[("Log files", "*.txt"), ("All files", "*.*")]
        )
        for file in files:
            if file not in self.selected_files:
                self.selected_files.append(file)
                self.file_listbox.insert(tk.END, os.path.basename(file))

    def remove_files(self):
        selection = self.file_listbox.curselection()
        for index in reversed(selection):
            self.selected_files.pop(index)
            self.file_listbox.delete(index)

    def browse_output_dir(self):
        directory = filedialog.askdirectory(
            title="Select Output Directory",
            initialdir=self.output_dir.get()
        )
        if directory:
            self.output_dir.set(directory)

    def update_summary(self):
        summary = "Processing Summary:\n\n"
        
        summary += "Selected Files:\n"
        for file in self.selected_files:
            summary += f"  - {os.path.basename(file)}\n"
        
        summary += "\nData Types:\n"
        for data_type, var in self.data_vars.items():
            if var.get():
                summary += f"  - {data_type.capitalize()}\n"
        
        summary += "\nOutput Formats:\n"
        for fmt, var in self.output_vars.items():
            if var.get():
                summary += f"  - {fmt.upper()}\n"
        
        summary += f"\nOutput Directory:\n  {self.output_dir.get()}\n"
        
        self.summary_text.delete(1.0, tk.END)
        self.summary_text.insert(tk.END, summary)

    def go_back(self):
        if self.current_step > 1:
            self.current_step -= 1
            self.show_step(self.current_step)

    def go_next(self):
        if self.current_step < 4:
            self.current_step += 1
            self.show_step(self.current_step)
        elif self.current_step == 4:
            self.start_processing()

    def start_processing(self):
        if not self.selected_files:
            messagebox.showerror("Error", "Please select at least one file to process.")
            return
        
        if not any(var.get() for var in self.data_vars.values()):
            messagebox.showerror("Error", "Please select at least one data type.")
            return
        
        if not any(var.get() for var in self.output_vars.values()):
            messagebox.showerror("Error", "Please select at least one output format.")
            return

        # Disable navigation during processing
        self.back_btn.configure(state='disabled')
        self.next_btn.configure(state='disabled')

        # Collect processing parameters
        params = {
            'file_list': self.selected_files,
            'data_types': [dt for dt, var in self.data_vars.items() if var.get()],
            'output_formats': [fmt for fmt, var in self.output_vars.items() if var.get()],
            'output_dir': self.output_dir.get()
        }

        # Start processing in a separate thread
        thread = threading.Thread(target=self.run_processing, args=(params,))
        thread.daemon = True
        thread.start()

    def run_processing(self, params):
        try:
            self.status_var.set("Processing files...")
            # Call the imported process_files function
            process_files(
                params['file_list'],
                params['data_types'],
                params['output_formats'],
                params['output_dir']
            )
            self.status_var.set("Processing completed successfully!")
            messagebox.showinfo("Success", "Log processing completed successfully!")
        except Exception as e:
            self.status_var.set("Error during processing!")
            messagebox.showerror("Error", f"An error occurred during processing:\n{str(e)}")
        finally:
            # Re-enable navigation
            self.back_btn.configure(state='normal')
            self.next_btn.configure(state='normal')

def main():
    root = tk.Tk()
    app = LogProcessorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()