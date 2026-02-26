"""
sim_gui.py — Material-style dark-themed simulator GUI.

Shows live status of every simulated instrument in a card-based layout.
Operators can toggle interlock inputs, nudge temperatures, toggle PSU
outputs, and change BCON channel modes — all of which the dashboard sees
in real-time via the virtual serial links.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import threading
from typing import Any

# ---------------------------------------------------------------------------
#  Material Design colour palette
# ---------------------------------------------------------------------------
MD_BG           = "#1E1E2E"    # surface
MD_CARD         = "#2A2A3C"    # card
MD_CARD_BORDER  = "#3A3A4C"
MD_PRIMARY      = "#7C4DFF"    # deep purple accent
MD_PRIMARY_DARK = "#651FFF"
MD_GREEN        = "#00E676"
MD_RED          = "#FF5252"
MD_AMBER        = "#FFD740"
MD_TEXT         = "#E0E0E0"
MD_TEXT_DIM     = "#9E9E9E"
MD_TEXT_DARK    = "#616161"
MD_CHIP_BG      = "#3A3A4C"
MD_ENTRY_BG     = "#353548"
MD_ENTRY_FG     = "#E0E0E0"


def _configure_styles():
    """Register ttk styles once."""
    style = ttk.Style()
    style.theme_use("clam")

    style.configure("Card.TFrame", background=MD_CARD)
    style.configure("Surface.TFrame", background=MD_BG)
    style.configure("Card.TLabel", background=MD_CARD, foreground=MD_TEXT,
                     font=("Segoe UI", 10))
    style.configure("CardTitle.TLabel", background=MD_CARD, foreground=MD_PRIMARY,
                     font=("Segoe UI", 12, "bold"))
    style.configure("CardSubtitle.TLabel", background=MD_CARD, foreground=MD_TEXT_DIM,
                     font=("Segoe UI", 9))
    style.configure("Surface.TLabel", background=MD_BG, foreground=MD_TEXT,
                     font=("Segoe UI", 10))
    style.configure("Header.TLabel", background=MD_BG, foreground=MD_TEXT,
                     font=("Segoe UI", 16, "bold"))
    style.configure("Subtitle.TLabel", background=MD_BG, foreground=MD_TEXT_DIM,
                     font=("Segoe UI", 10))
    style.configure("Green.TLabel", background=MD_CARD, foreground=MD_GREEN,
                     font=("Segoe UI", 10, "bold"))
    style.configure("Red.TLabel", background=MD_CARD, foreground=MD_RED,
                     font=("Segoe UI", 10, "bold"))
    style.configure("Amber.TLabel", background=MD_CARD, foreground=MD_AMBER,
                     font=("Segoe UI", 10))
    style.configure("Value.TLabel", background=MD_CARD, foreground="#FFFFFF",
                     font=("Consolas", 13, "bold"))

    # Buttons
    style.configure("Accent.TButton", background=MD_PRIMARY, foreground="#FFFFFF",
                     font=("Segoe UI", 10, "bold"), padding=(12, 6))
    style.map("Accent.TButton",
              background=[("active", MD_PRIMARY_DARK), ("pressed", MD_PRIMARY_DARK)])
    style.configure("Toggle.TButton", background=MD_CHIP_BG, foreground=MD_TEXT,
                     font=("Segoe UI", 9), padding=(8, 4))
    style.map("Toggle.TButton",
              background=[("active", "#4A4A5C")])

    # Scales
    style.configure("Card.Horizontal.TScale", background=MD_CARD,
                     troughcolor=MD_ENTRY_BG)

    # Notebook
    style.configure("Dark.TNotebook", background=MD_BG)
    style.configure("Dark.TNotebook.Tab", background=MD_CARD, foreground=MD_TEXT_DIM,
                     font=("Segoe UI", 10), padding=(14, 6))
    style.map("Dark.TNotebook.Tab",
              background=[("selected", MD_PRIMARY)],
              foreground=[("selected", "#FFFFFF")])


# ---------------------------------------------------------------------------
#  Reusable card widget
# ---------------------------------------------------------------------------

class Card(ttk.Frame):
    """Rounded-corner card container (approximated with a solid background)."""

    def __init__(self, parent, title: str = "", **kw):
        super().__init__(parent, style="Card.TFrame", padding=12, **kw)
        if title:
            ttk.Label(self, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(4, 8))


class IndicatorDot(tk.Canvas):
    """Small coloured circle — green / red / amber."""

    def __init__(self, parent, size=14, **kw):
        super().__init__(parent, width=size, height=size,
                         bg=MD_CARD, highlightthickness=0, **kw)
        self._size = size
        self._oval = self.create_oval(2, 2, size - 2, size - 2, fill=MD_TEXT_DARK, outline="")

    def set_color(self, color: str):
        self.itemconfig(self._oval, fill=color)


# ---------------------------------------------------------------------------
#  Per-instrument card panels
# ---------------------------------------------------------------------------

class VTRXCard(Card):
    def __init__(self, parent, sim):
        super().__init__(parent, title="VTRX — Vacuum System")
        self.sim = sim
        # Pressure readout
        row = ttk.Frame(self, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Pressure:", style="Card.TLabel").pack(side="left")
        self.pressure_lbl = ttk.Label(row, text="—", style="Value.TLabel")
        self.pressure_lbl.pack(side="right")

        # Switch indicators
        self.indicators: dict[str, tuple[IndicatorDot, ttk.Label]] = {}
        switch_names = [
            ("pumps_power", "Pumps Power"),
            ("turbo_rotor", "Turbo Rotor"),
            ("turbo_vent_open", "Turbo Vent"),
            ("gauge_972b_power", "972b Gauge"),
            ("turbo_gate_open", "Turbo Gate Open"),
            ("argon_gate_open", "Argon Gate Open"),
        ]
        grid = ttk.Frame(self, style="Card.TFrame")
        grid.pack(fill="x", pady=(8, 0))
        for i, (key, label) in enumerate(switch_names):
            r, c = divmod(i, 3)
            f = ttk.Frame(grid, style="Card.TFrame")
            f.grid(row=r, column=c, padx=6, pady=3, sticky="w")
            dot = IndicatorDot(f)
            dot.pack(side="left", padx=(0, 4))
            lbl = ttk.Label(f, text=label, style="Card.TLabel")
            lbl.pack(side="left")
            self.indicators[key] = (dot, lbl)

        # Pressure slider
        ttk.Label(self, text="Set Pressure (log10 Torr):", style="CardSubtitle.TLabel").pack(anchor="w", pady=(8, 2))
        self.pressure_scale = ttk.Scale(self, from_=-9, to=-1, orient="horizontal",
                                         style="Card.Horizontal.TScale",
                                         command=self._on_scale)
        self.pressure_scale.set(-5.3)
        self.pressure_scale.pack(fill="x")

    def _on_scale(self, val):
        p = 10 ** float(val)
        with self.sim.lock:
            self.sim.state["pressure"] = p

    def refresh(self):
        with self.sim.lock:
            p = self.sim.state["pressure"]
            for key, (dot, _) in self.indicators.items():
                val = self.sim.state.get(key, False)
                dot.set_color(MD_GREEN if val else MD_RED)
        self.pressure_lbl.config(text=f"{p:.2E} Torr")


class PSUCard(Card):
    """Card for one BK Precision 9104 power supply simulator."""

    def __init__(self, parent, sim, label: str):
        super().__init__(parent, title=f"PSU — {label}")
        self.sim = sim

        # Output status
        row = ttk.Frame(self, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Output:", style="Card.TLabel").pack(side="left")
        self.out_dot = IndicatorDot(row)
        self.out_dot.pack(side="left", padx=4)
        self.out_lbl = ttk.Label(row, text="OFF", style="Red.TLabel")
        self.out_lbl.pack(side="left")

        # Readings
        for attr, unit in [("voltage", "V"), ("current", "A")]:
            r = ttk.Frame(self, style="Card.TFrame")
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=f"{attr.title()} Read:", style="Card.TLabel").pack(side="left")
            lbl = ttk.Label(r, text="0.00", style="Value.TLabel")
            lbl.pack(side="right")
            setattr(self, f"{attr}_lbl", lbl)

        # Setpoint display
        for attr, unit in [("voltage_set", "V"), ("current_set", "A")]:
            r = ttk.Frame(self, style="Card.TFrame")
            r.pack(fill="x", pady=1)
            nice = attr.replace("_", " ").title()
            ttk.Label(r, text=f"{nice}:", style="CardSubtitle.TLabel").pack(side="left")
            lbl = ttk.Label(r, text="0.00", style="Amber.TLabel")
            lbl.pack(side="right")
            setattr(self, f"{attr}_lbl", lbl)

    def refresh(self):
        with self.sim.lock:
            s = dict(self.sim.state)
        on = s.get("output_on", False)
        self.out_dot.set_color(MD_GREEN if on else MD_RED)
        self.out_lbl.config(text="ON" if on else "OFF",
                            style="Green.TLabel" if on else "Red.TLabel")
        self.voltage_lbl.config(text=f"{s.get('voltage_read', 0):.2f} V")
        self.current_lbl.config(text=f"{s.get('current_read', 0):.3f} A")
        self.voltage_set_lbl.config(text=f"{s.get('voltage_set', 0):.2f} V")
        self.current_set_lbl.config(text=f"{s.get('current_set', 0):.2f} A")


class E5CNCard(Card):
    def __init__(self, parent, sim):
        super().__init__(parent, title="E5CN — Temp Controllers")
        self.sim = sim
        self.temp_lbls = {}
        self.scales = {}
        names = {1: "Clamp A", 2: "Clamp B", 3: "Clamp C"}
        for unit in (1, 2, 3):
            r = ttk.Frame(self, style="Card.TFrame")
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=f"{names[unit]}:", style="Card.TLabel").pack(side="left")
            lbl = ttk.Label(r, text="—", style="Value.TLabel")
            lbl.pack(side="right")
            self.temp_lbls[unit] = lbl
            sc = ttk.Scale(self, from_=-20, to=500, orient="horizontal",
                            style="Card.Horizontal.TScale",
                            command=lambda v, u=unit: self._on_scale(u, v))
            sc.set(25)
            sc.pack(fill="x", pady=(0, 4))
            self.scales[unit] = sc

    def _on_scale(self, unit, val):
        with self.sim.lock:
            self.sim.state[f"temp_{unit}"] = float(val)

    def refresh(self):
        with self.sim.lock:
            for unit in (1, 2, 3):
                t = self.sim.state.get(f"temp_{unit}", 0)
                self.temp_lbls[unit].config(text=f"{t:.1f} °C")


class InterlocksCard(Card):
    def __init__(self, parent, sim):
        super().__init__(parent, title="G9SP — Interlocks")
        self.sim = sim
        self.toggles: dict[str, tuple[IndicatorDot, tk.Button]] = {}
        nice_names = {
            "e_stop_int_a": "E-STOP Int A", "e_stop_int_b": "E-STOP Int B",
            "e_stop_ext_a": "E-STOP Ext A", "e_stop_ext_b": "E-STOP Ext B",
            "door_a": "Door A", "door_b": "Door B",
            "vacuum_power": "Vacuum Power", "vacuum_pressure": "Vacuum Press.",
            "high_oil": "High Oil", "low_oil": "Low Oil",
            "water": "Water", "hvolt_on": "HVolt ON", "g9sp_active": "G9SP Active",
        }
        grid = ttk.Frame(self, style="Card.TFrame")
        grid.pack(fill="x", pady=4)
        for i, (key, label) in enumerate(nice_names.items()):
            r, c = divmod(i, 3)
            f = ttk.Frame(grid, style="Card.TFrame")
            f.grid(row=r, column=c, padx=4, pady=3, sticky="w")
            dot = IndicatorDot(f)
            dot.pack(side="left", padx=(0, 4))
            btn = tk.Button(f, text=label, bg=MD_CHIP_BG, fg=MD_TEXT,
                            activebackground="#4A4A5C", activeforeground=MD_TEXT,
                            relief="flat", font=("Segoe UI", 9), bd=0, padx=6, pady=2,
                            command=lambda k=key: self._toggle(k))
            btn.pack(side="left")
            self.toggles[key] = (dot, btn)

    def _toggle(self, key):
        with self.sim.lock:
            self.sim.state[key] = not self.sim.state.get(key, True)

    def refresh(self):
        with self.sim.lock:
            for key, (dot, btn) in self.toggles.items():
                val = self.sim.state.get(key, True)
                dot.set_color(MD_GREEN if val else MD_RED)


class DP16Card(Card):
    def __init__(self, parent, sim):
        super().__init__(parent, title="DP16 — Process Monitors")
        self.sim = sim
        self.temp_lbls = {}
        names = {1: "Solenoid 1", 2: "Solenoid 2", 3: "Chamber Top",
                 4: "Chamber Bot", 5: "Air Temp"}
        for unit in range(1, 6):
            r = ttk.Frame(self, style="Card.TFrame")
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=f"{names[unit]}:", style="Card.TLabel").pack(side="left")
            lbl = ttk.Label(r, text="—", style="Value.TLabel")
            lbl.pack(side="right")
            self.temp_lbls[unit] = lbl
        ttk.Label(self, text="Adjust temps with slider:", style="CardSubtitle.TLabel").pack(anchor="w", pady=(6, 2))
        self.offset_scale = ttk.Scale(self, from_=-20, to=80, orient="horizontal",
                                       style="Card.Horizontal.TScale",
                                       command=self._on_offset)
        self.offset_scale.set(30)
        self.offset_scale.pack(fill="x")

    def _on_offset(self, val):
        base = float(val)
        with self.sim.lock:
            self.sim.state["temp_1"] = base + 2
            self.sim.state["temp_2"] = base + 3.5
            self.sim.state["temp_3"] = base - 1
            self.sim.state["temp_4"] = base
            self.sim.state["temp_5"] = base - 8

    def refresh(self):
        with self.sim.lock:
            for unit in range(1, 6):
                t = self.sim.state.get(f"temp_{unit}", 0)
                self.temp_lbls[unit].config(text=f"{t:.1f} °C")


class BCONCard(Card):
    def __init__(self, parent, sim):
        super().__init__(parent, title="BCON — Beam Pulse Controller")
        self.sim = sim
        # System state
        row = ttk.Frame(self, style="Card.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="System State:", style="Card.TLabel").pack(side="left")
        self.state_lbl = ttk.Label(row, text="READY", style="Green.TLabel")
        self.state_lbl.pack(side="right")

        row2 = ttk.Frame(self, style="Card.TFrame")
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Armed:", style="Card.TLabel").pack(side="left")
        self.armed_dot = IndicatorDot(row2)
        self.armed_dot.pack(side="right", padx=4)

        row3 = ttk.Frame(self, style="Card.TFrame")
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="Interlock:", style="Card.TLabel").pack(side="left")
        self.il_dot = IndicatorDot(row3)
        self.il_dot.pack(side="right", padx=4)
        # Toggle interlock
        btn = tk.Button(row3, text="Toggle", bg=MD_CHIP_BG, fg=MD_TEXT,
                        activebackground="#4A4A5C", activeforeground=MD_TEXT,
                        relief="flat", font=("Segoe UI", 9), bd=0, padx=6, pady=2,
                        command=self._toggle_interlock)
        btn.pack(side="right", padx=4)

        # Per-channel
        self.ch_lbls = {}
        modes = {0: "OFF", 1: "DC", 2: "PULSE", 3: "TRAIN"}
        for ch in (1, 2, 3):
            f = ttk.Frame(self, style="Card.TFrame")
            f.pack(fill="x", pady=2)
            ttk.Label(f, text=f"CH{ch}:", style="Card.TLabel").pack(side="left")
            mode_lbl = ttk.Label(f, text="OFF", style="Card.TLabel")
            mode_lbl.pack(side="left", padx=8)
            en_dot = IndicatorDot(f)
            en_dot.pack(side="right", padx=4)
            ttk.Label(f, text="EN:", style="CardSubtitle.TLabel").pack(side="right")
            out_dot = IndicatorDot(f)
            out_dot.pack(side="right", padx=4)
            ttk.Label(f, text="OUT:", style="CardSubtitle.TLabel").pack(side="right")
            self.ch_lbls[ch] = {"mode": mode_lbl, "en": en_dot, "out": out_dot}

    def _toggle_interlock(self):
        with self.sim.lock:
            self.sim.state["interlock_ok"] = not self.sim.state.get("interlock_ok", True)

    def refresh(self):
        modes = {0: "OFF", 1: "DC", 2: "PULSE", 3: "TRAIN"}
        sys_states = {0: ("READY", "Green.TLabel"), 1: ("SAFE_INTLK", "Amber.TLabel"),
                      2: ("SAFE_WDG", "Amber.TLabel"), 3: ("FAULT", "Red.TLabel")}
        with self.sim.lock:
            s = dict(self.sim.state)
        ss = s.get("sys_state", 0)
        txt, sty = sys_states.get(ss, ("UNKNOWN", "Card.TLabel"))
        self.state_lbl.config(text=txt, style=sty)
        self.armed_dot.set_color(MD_GREEN if s.get("armed") else MD_TEXT_DARK)
        self.il_dot.set_color(MD_GREEN if s.get("interlock_ok") else MD_RED)
        for ch in (1, 2, 3):
            m = s.get(f"ch{ch}_mode", 0)
            self.ch_lbls[ch]["mode"].config(text=modes.get(m, "?"))
            self.ch_lbls[ch]["en"].set_color(MD_GREEN if s.get(f"ch{ch}_enabled") else MD_TEXT_DARK)
            self.ch_lbls[ch]["out"].set_color(
                MD_AMBER if s.get(f"ch{ch}_output", 0) else MD_TEXT_DARK)


# ---------------------------------------------------------------------------
#  Main GUI window
# ---------------------------------------------------------------------------

class SimulatorGUI:
    """Top-level Material-style simulator window."""

    REFRESH_MS = 250

    def __init__(self, simulators: dict):
        """*simulators* is a dict name → BaseSimulator instance."""
        self.simulators = simulators
        self.root = tk.Tk()
        self.root.title("EBEAM Hardware Simulator")
        self.root.configure(bg=MD_BG)
        self.root.geometry("1200x880")
        self.root.minsize(900, 600)

        _configure_styles()

        # Header
        header = ttk.Frame(self.root, style="Surface.TFrame")
        header.pack(fill="x", padx=16, pady=(12, 0))
        ttk.Label(header, text="⚡  EBEAM Hardware Simulator",
                  style="Header.TLabel").pack(side="left")
        ttk.Label(header, text="Material Dark  •  All instruments virtual",
                  style="Subtitle.TLabel").pack(side="right")

        # Port info bar
        port_bar = ttk.Frame(self.root, style="Surface.TFrame")
        port_bar.pack(fill="x", padx=16, pady=(4, 8))
        port_text_parts = []
        for name, sim in simulators.items():
            port_text_parts.append(f"{name}: {sim.pair.slave_path}")
        ttk.Label(port_bar, text="  |  ".join(port_text_parts),
                  style="Subtitle.TLabel", wraplength=1160).pack(anchor="w")

        # Scrollable card area
        canvas = tk.Canvas(self.root, bg=MD_BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        self.cards_frame = ttk.Frame(canvas, style="Surface.TFrame")
        self.cards_frame.bind("<Configure>",
                              lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=8, pady=4)
        # Mouse-wheel scroll
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

        self.cards: list = []
        self._build_cards()
        self._schedule_refresh()

    # -- Build cards --------------------------------------------------------

    def _build_cards(self):
        sims = self.simulators
        # Use a 2-column responsive grid
        col = 0
        row_idx = 0

        def place(card_widget):
            nonlocal col, row_idx
            card_widget.grid(row=row_idx, column=col, padx=10, pady=8, sticky="nsew")
            self.cards_frame.grid_columnconfigure(col, weight=1)
            col += 1
            if col >= 2:
                col = 0
                row_idx += 1

        if "VTRX" in sims:
            c = VTRXCard(self.cards_frame, sims["VTRX"])
            place(c)
            self.cards.append(c)

        for key, label in [("CathodeA", "Cathode A"), ("CathodeB", "Cathode B"),
                           ("CathodeC", "Cathode C")]:
            if key in sims:
                c = PSUCard(self.cards_frame, sims[key], label)
                place(c)
                self.cards.append(c)

        if "E5CN" in sims:
            c = E5CNCard(self.cards_frame, sims["E5CN"])
            place(c)
            self.cards.append(c)

        if "G9SP" in sims:
            c = InterlocksCard(self.cards_frame, sims["G9SP"])
            place(c)
            self.cards.append(c)

        if "DP16" in sims:
            c = DP16Card(self.cards_frame, sims["DP16"])
            place(c)
            self.cards.append(c)

        if "BCON" in sims:
            c = BCONCard(self.cards_frame, sims["BCON"])
            place(c)
            self.cards.append(c)

    # -- Periodic refresh ---------------------------------------------------

    def _schedule_refresh(self):
        for card in self.cards:
            try:
                card.refresh()
            except Exception:
                pass
        self.root.after(self.REFRESH_MS, self._schedule_refresh)

    # -- Lifecycle ----------------------------------------------------------

    def mainloop(self):
        self.root.mainloop()
