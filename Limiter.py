import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import soundfile as sf
import sounddevice as sd
import pyloudnorm as pyln

import sys
from pathlib import Path

from Limiter_Engine import process_file, render_preview


APP_BG = "#121212"
PANEL_BG = "#1b1b1b"
PANEL_ALT = "#222222"
TEXT = "#e8e8e8"
MUTED_TEXT = "#a8a8a8"
ACCENT = "#6aa9ff"
WAVE_BG = "#0b0b0b"
WAVE_LINE = "#8f8f8f"
WAVE_LIMITED = "#78b8ff"
WAVE_CENTER = "#333333"
PLAYHEAD = "#ffffff"
GR_LINE = "#ffbf69"
GR_HOT = "#ff7070"
GR_BG = "#15110b"
DIVIDER = "#444444"

def resource_path(relative_path):
    try:
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        base_path = Path(__file__).parent

    return base_path / relative_path

class LimiterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WAV Limiter")

        try:
            self.root.iconbitmap(default=str(resource_path("Limiter.ico")))
        except tk.TclError as error:
            print(f"Could not load window icon: {error}")
            
        self.root.geometry("1380x960")
        self.root.minsize(1180, 900)
        self.root.configure(bg=APP_BG)

        self.configure_style()

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()

        self.target_lufs = tk.StringVar(value="-14")
        self.ceiling_db = tk.StringVar(value="-1.0")
        self.lookahead_ms = tk.StringVar(value="5")
        self.release_ms = tk.StringVar(value="80")
        self.max_allowed_reduction_db = tk.StringVar(value="4.0")
        self.output_subtype = tk.StringVar(value="PCM_24")

        self.playing = False
        self.preview_rendering = False
        self.play_thread = None
        self.meter_queue = queue.Queue()
        self.position_lock = threading.Lock()

        self.playback_position = 0
        self.playback_current_peak_db = -120.0
        self.playback_highest_peak_db = -120.0

        self.loaded_playback_audio = None
        self.loaded_playback_sample_rate = None
        self.loaded_playback_mode = None
        self.loaded_gain_reduction_trace = None

        self.waveform_peaks = None
        self.waveform_gr_peaks = None
        self.waveform_playhead_id = None

        self.current_gain_reduction_db = 0.0
        self.max_preview_gain_reduction_db = 0.0
        self.current_gr_trace_scale_db = 0.0

        self.build_ui()

    def configure_style(self):
        style = ttk.Style()

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.option_add("*TCombobox*Listbox.background", "#111111")
        self.root.option_add("*TCombobox*Listbox.foreground", "#e8e8e8")
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#244b78")
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        style.configure(
            ".",
            background=APP_BG,
            foreground=TEXT,
            fieldbackground=PANEL_ALT,
            bordercolor=PANEL_ALT,
            lightcolor=PANEL_ALT,
            darkcolor=PANEL_ALT,
            font=("Segoe UI", 10),
        )

        style.configure("TFrame", background=APP_BG)
        style.configure("Panel.TFrame", background=PANEL_BG)
        style.configure("TLabel", background=APP_BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=APP_BG, foreground=MUTED_TEXT)
        style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
        style.configure("MutedPanel.TLabel", background=PANEL_BG, foreground=MUTED_TEXT)
        style.configure("Title.TLabel", background=APP_BG, foreground=TEXT, font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=APP_BG, foreground=MUTED_TEXT, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=PANEL_BG, foreground=TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("Meter.TLabel", background=PANEL_BG, foreground=TEXT, font=("Consolas", 11, "bold"))
        style.configure("Status.TLabel", background=PANEL_BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))

        style.configure(
            "TLabelframe",
            background=PANEL_BG,
            foreground=TEXT,
            bordercolor="#333333",
            relief="solid",
        )

        style.configure(
            "TLabelframe.Label",
            background=PANEL_BG,
            foreground=TEXT,
            font=("Segoe UI", 10, "bold"),
        )

        style.configure("TButton", background=PANEL_ALT, foreground=TEXT, padding=(10, 6), borderwidth=1)
        style.map("TButton", background=[("active", "#303030"), ("pressed", "#3a3a3a")], foreground=[("disabled", "#777777")])

        style.configure("Accent.TButton", background="#244b78", foreground=TEXT, padding=(12, 7), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#2e5f98"), ("pressed", "#1e3f66")])

        style.configure("Danger.TButton", background="#5a2424", foreground=TEXT, padding=(12, 7))
        style.map("Danger.TButton", background=[("active", "#743030"), ("pressed", "#3f1818")])

        style.configure("TEntry", fieldbackground="#111111", foreground=TEXT, insertcolor=TEXT, bordercolor="#444444", padding=4)
        style.configure(
            "TCombobox",
            fieldbackground="#111111",
            background="#111111",
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor="#444444",
            darkcolor="#111111",
            lightcolor="#111111",
            selectbackground="#244b78",
            selectforeground="#ffffff",
            padding=4,
        )

        style.map(
    "TCombobox",
    fieldbackground=[
        ("readonly", "#111111"),
        ("focus", "#111111"),
        ("active", "#111111"),
    ],
    background=[
        ("readonly", "#111111"),
        ("focus", "#111111"),
        ("active", "#222222"),
    ],
    foreground=[
        ("readonly", TEXT),
        ("focus", TEXT),
        ("active", TEXT),
    ],
    arrowcolor=[
        ("readonly", TEXT),
        ("focus", TEXT),
        ("active", TEXT),
    ],
)

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#0f0f0f",
            background=ACCENT,
            bordercolor="#333333",
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
    
    def build_ui(self):
        self.main = ttk.Frame(self.root, style="TFrame")
        self.main.pack(fill="both", expand=True, padx=14, pady=12)

        self.build_header()
        self.build_file_section()
        self.build_main_grid()
        self.build_playback_section()
        self.build_waveform_section()
        self.build_report_section()

    def build_header(self):
        header = ttk.Frame(self.main, style="TFrame")
        header.pack(fill="x", pady=(0, 10))

        ttk.Label(header, text="Python WAV Limiter", style="Title.TLabel").pack(anchor="w")

    def build_file_section(self):
        file_frame = ttk.LabelFrame(self.main, text="1. Files")
        file_frame.pack(fill="x", pady=(0, 10))

        file_inner = ttk.Frame(file_frame, style="Panel.TFrame")
        file_inner.pack(fill="x", padx=10, pady=10)

        ttk.Label(file_inner, text="Input WAV", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(file_inner, textvariable=self.input_path, width=120).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(file_inner, text="Browse", command=self.browse_input).grid(row=0, column=2, padx=(8, 0), pady=5)

        ttk.Label(file_inner, text="Output WAV", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(file_inner, textvariable=self.output_path, width=120).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Button(file_inner, text="Save As", command=self.browse_output).grid(row=1, column=2, padx=(8, 0), pady=5)

        file_inner.columnconfigure(1, weight=1)

    def build_main_grid(self):
        grid = ttk.Frame(self.main, style="TFrame")
        grid.pack(fill="x", pady=(0, 10))

        self.build_settings_panel(grid)
        self.build_help_panel(grid)

        grid.columnconfigure(0, weight=2)
        grid.columnconfigure(1, weight=1)

    def build_settings_panel(self, parent):
        settings = ttk.LabelFrame(parent, text="2. Limiter Settings")
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        inner = ttk.Frame(settings, style="Panel.TFrame")
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        self.add_setting_row(inner, 0, "Target LUFS", self.target_lufs, "Final loudness goal. Example: -14, -12, -10.")
        self.add_setting_row(inner, 1, "Ceiling dBFS", self.ceiling_db, "Sample-peak ceiling. -1.0 is a good starting point.")
        self.add_setting_row(inner, 2, "Lookahead ms", self.lookahead_ms, "How early the limiter sees peaks. 3–8 ms is often the best.")
        self.add_setting_row(inner, 3, "Release ms", self.release_ms, "How quickly limiting recovers. 80–150 ms is often the best.")
        self.add_setting_row(inner, 4, "Max reduction dB", self.max_allowed_reduction_db, "Safety limit. Backs off gain if limiting would exceed this.")

        ttk.Label(inner, text="Output format", style="Panel.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 2))

        subtype_menu = ttk.Combobox(inner, textvariable=self.output_subtype, values=["PCM_24", "PCM_16", "FLOAT"], state="readonly", width=14)
        subtype_menu.grid(row=5, column=1, sticky="w", pady=(8, 2))

        ttk.Label(inner, text="PCM_24 is recommended for normal high-quality WAV export.", style="MutedPanel.TLabel").grid(
            row=5, column=2, sticky="w", padx=(12, 0), pady=(8, 2)
        )

        preset_row = ttk.Frame(inner, style="Panel.TFrame")
        preset_row.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        ttk.Label(preset_row, text="Presets:", style="Panel.TLabel").pack(side="left", padx=(0, 8))

        ttk.Button(preset_row, text="Clean", command=lambda: self.apply_preset(-14.0, -1.0, 5.0, 100.0, 3.0, "PCM_24")).pack(side="left", padx=(0, 6))
        ttk.Button(preset_row, text="Loud Clean", command=lambda: self.apply_preset(-11.0, -1.0, 5.0, 110.0, 4.0, "PCM_24")).pack(side="left", padx=(0, 6))
        ttk.Button(preset_row, text="Aggressive", command=lambda: self.apply_preset(-9.0, -1.0, 5.0, 130.0, 6.0, "PCM_24")).pack(side="left", padx=(0, 6))
        ttk.Button(preset_row, text="Safety Ceiling", command=lambda: self.apply_preset(-99.0, -1.0, 5.0, 80.0, 2.0, "PCM_24")).pack(side="left", padx=(0, 6))

        button_row = ttk.Frame(inner, style="Panel.TFrame")
        button_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(14, 0))

        ttk.Button(button_row, text="Export Limited WAV", command=self.start_processing, style="Accent.TButton").pack(side="left")

        self.progress = ttk.Progressbar(button_row, mode="indeterminate", length=260, style="Horizontal.TProgressbar")
        self.progress.pack(side="left", padx=(14, 0))

        self.export_status_label = ttk.Label(button_row, text="Ready", style="MutedPanel.TLabel")
        self.export_status_label.pack(side="left", padx=(12, 0))

        inner.columnconfigure(2, weight=1)

    def add_setting_row(self, parent, row, label, variable, hint):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable, width=14).grid(row=row, column=1, sticky="w", pady=4)
        ttk.Label(parent, text=hint, style="MutedPanel.TLabel").grid(row=row, column=2, sticky="w", padx=(12, 0), pady=4)

    def build_help_panel(self, parent):
        help_frame = ttk.LabelFrame(parent, text="What Each Mode Means")
        help_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        inner = ttk.Frame(help_frame, style="Panel.TFrame")
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        lines = [
            ("Original", "Plays the input WAV exactly as loaded."),
            ("Limited Preview", "Processes in memory using the current settings, then plays it."),
            ("Export", "Writes the limited version to the selected output WAV."),
            ("Current peak", "Peak of the most recent audio block."),
            ("Highest peak", "Highest sample peak since play/seek."),
            ("Current GR", "Limiter gain reduction at the current playback position."),
            ("Max GR", "Hardest limiting moment in the current limited preview."),
            ("GR trace", "Lower orange/red trace showing where limiting happens."),
            ("Active LUFS", "Rolling short-term loudness estimate, not the whole-song LUFS."),
        ]

        for i, (name, desc) in enumerate(lines):
            ttk.Label(inner, text=name, style="Header.TLabel").grid(row=i, column=0, sticky="nw", pady=4)
            ttk.Label(inner, text=desc, style="MutedPanel.TLabel", wraplength=360).grid(row=i, column=1, sticky="nw", padx=(10, 0), pady=4)

    def build_playback_section(self):
        playback = ttk.LabelFrame(self.main, text="3. Playback and Meters")
        playback.pack(fill="x", pady=(0, 10))

        inner = ttk.Frame(playback, style="Panel.TFrame")
        inner.pack(fill="x", padx=10, pady=10)

        controls = ttk.Frame(inner, style="Panel.TFrame")
        controls.pack(fill="x", pady=(0, 8))

        ttk.Button(controls, text="Play Original", command=self.start_original_playback).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Play Limited Preview", command=self.start_limited_preview, style="Accent.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Stop", command=self.stop_playback, style="Danger.TButton").pack(side="left", padx=(0, 12))

        self.playback_mode_label = ttk.Label(controls, text="Mode: --", style="Status.TLabel")
        self.playback_mode_label.pack(side="left", padx=(8, 0))

        self.playback_status_label = ttk.Label(controls, text="Stopped", style="MutedPanel.TLabel")
        self.playback_status_label.pack(side="left", padx=(16, 0))

        self.preview_progress = ttk.Progressbar(controls, mode="indeterminate", length=150, style="Horizontal.TProgressbar")
        self.preview_progress.pack(side="right", padx=(12, 0))

        self.preview_progress_label = ttk.Label(controls, text="Preview idle", style="MutedPanel.TLabel")
        self.preview_progress_label.pack(side="right", padx=(12, 0))

        meter_grid = ttk.Frame(inner, style="Panel.TFrame")
        meter_grid.pack(fill="x", pady=(4, 0))

        self.active_lufs_label = ttk.Label(meter_grid, text="Active LUFS: --", style="Meter.TLabel")
        self.active_lufs_label.grid(row=0, column=0, sticky="w", padx=(0, 24), pady=4)

        self.current_peak_label = ttk.Label(meter_grid, text="Current peak: --", style="Meter.TLabel")
        self.current_peak_label.grid(row=0, column=1, sticky="w", padx=(0, 24), pady=4)

        self.highest_peak_label = ttk.Label(meter_grid, text="Highest peak since play/seek: --", style="Meter.TLabel")
        self.highest_peak_label.grid(row=0, column=2, sticky="w", padx=(0, 24), pady=4)

        self.playback_time_label = ttk.Label(meter_grid, text="00:00 / 00:00", style="Meter.TLabel")
        self.playback_time_label.grid(row=0, column=3, sticky="e", pady=4)

        self.current_gr_label = ttk.Label(meter_grid, text="Current GR: --", style="Meter.TLabel")
        self.current_gr_label.grid(row=1, column=0, sticky="w", padx=(0, 24), pady=4)

        self.max_gr_label = ttk.Label(meter_grid, text="Max GR in preview: --", style="Meter.TLabel")
        self.max_gr_label.grid(row=1, column=1, sticky="w", padx=(0, 24), pady=4)

        meter_grid.columnconfigure(3, weight=1)

    def build_waveform_section(self):
        waveform_frame = ttk.LabelFrame(self.main, text="4. Interactive Waveform + Gain Reduction Trace")
        waveform_frame.pack(fill="x", pady=(0, 10))

        inner = ttk.Frame(waveform_frame, style="Panel.TFrame")
        inner.pack(fill="x", padx=10, pady=10)

        top_row = ttk.Frame(inner, style="Panel.TFrame")
        top_row.pack(fill="x", pady=(0, 6))

        self.waveform_info_label = ttk.Label(
            top_row,
            text="No waveform loaded.",
            style="MutedPanel.TLabel",
        )
        self.waveform_info_label.pack(side="left")

        self.waveform_scale_label = ttk.Label(
            top_row,
            text="GR scale: --",
            style="MutedPanel.TLabel",
        )
        self.waveform_scale_label.pack(side="right")

        self.waveform_canvas = tk.Canvas(
            inner,
            height=230,
            bg=WAVE_BG,
            highlightthickness=1,
            highlightbackground="#444444",
            cursor="hand2",
        )
        self.waveform_canvas.pack(fill="x")

        bottom_row = ttk.Frame(inner, style="Panel.TFrame")
        bottom_row.pack(fill="x", pady=(6, 0))

        ttk.Label(
            bottom_row,
            text="Click or drag the waveform to seek. The lower trace appears only for limited preview and shows where the limiter is reducing gain.",
            style="MutedPanel.TLabel",
        ).pack(side="left")

        ttk.Label(
            bottom_row,
            text="Orange/red = stronger gain reduction",
            style="MutedPanel.TLabel",
        ).pack(side="right")

        self.waveform_canvas.bind("<Button-1>", self.waveform_seek)
        self.waveform_canvas.bind("<B1-Motion>", self.waveform_seek)
        self.waveform_canvas.bind("<ButtonRelease-1>", self.waveform_seek)

    def build_report_section(self):
        report_frame = ttk.LabelFrame(self.main, text="5. Export Report")
        report_frame.pack(fill="both", expand=True)

        inner = ttk.Frame(report_frame, style="Panel.TFrame")
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        self.report_text = tk.Text(inner, height=10, wrap="word", bg="#0f0f0f", fg=TEXT, insertbackground=TEXT, relief="flat", font=("Consolas", 10))
        self.report_text.pack(fill="both", expand=True)

        self.report_text.insert(tk.END, "No export yet.\n\nPlay original to hear the raw input, play limited preview to hear the processed preview, or export limited WAV to write the final file.")

    def browse_input(self):
        path = filedialog.askopenfilename(title="Select input WAV", filetypes=[("WAV files", "*.wav"), ("All files", "*.*")])

        if path:
            self.input_path.set(path)
            self.output_path.set(path[:-4] + "_limited.wav" if path.lower().endswith(".wav") else path + "_limited.wav")
            self.clear_loaded_preview()
            self.report_text.delete("1.0", tk.END)
            self.report_text.insert(tk.END, "Input loaded.\n\nPlay original to inspect the raw file, or play limited preview to hear the limiter using the current settings.")

    def browse_output(self):
        path = filedialog.asksaveasfilename(title="Choose output WAV", defaultextension=".wav", filetypes=[("WAV files", "*.wav"), ("All files", "*.*")])
        if path:
            self.output_path.set(path)

    def clear_loaded_preview(self):
        self.loaded_playback_audio = None
        self.loaded_playback_sample_rate = None
        self.loaded_playback_mode = None
        self.loaded_gain_reduction_trace = None
        self.current_gain_reduction_db = 0.0
        self.max_preview_gain_reduction_db = 0.0
        self.current_gr_trace_scale_db = 0.0
        self.preview_rendering = False

        if hasattr(self, "waveform_canvas"):
            self.waveform_canvas.delete("all")

        self.waveform_playhead_id = None
        self.waveform_peaks = None
        self.waveform_gr_peaks = None
        self.playback_time_label.config(text="00:00 / 00:00")
        self.active_lufs_label.config(text="Active LUFS: --")
        self.current_peak_label.config(text="Current peak: --")
        self.highest_peak_label.config(text="Highest peak since play/seek: --")
        self.current_gr_label.config(text="Current GR: --")
        self.max_gr_label.config(text="Max GR in preview: --")
        self.preview_progress.stop()
        self.preview_progress_label.config(text="Preview idle")
        self.waveform_info_label.config(text="No waveform loaded.")
        self.waveform_scale_label.config(text="GR scale: --")
        self.playback_mode_label.config(text="Mode: --")
        self.playback_status_label.config(text="Stopped")

    def apply_preset(self, target_lufs, ceiling_db, lookahead_ms, release_ms, max_reduction_db, output_subtype):
        self.target_lufs.set(str(target_lufs))
        self.ceiling_db.set(str(ceiling_db))
        self.lookahead_ms.set(str(lookahead_ms))
        self.release_ms.set(str(release_ms))
        self.max_allowed_reduction_db.set(str(max_reduction_db))
        self.output_subtype.set(output_subtype)
        self.export_status_label.config(text="Preset loaded")

    def get_current_limiter_settings(self):
        target_lufs = float(self.target_lufs.get())
        ceiling_db = float(self.ceiling_db.get())
        lookahead_ms = float(self.lookahead_ms.get())
        release_ms = float(self.release_ms.get())
        max_allowed_reduction_db = float(self.max_allowed_reduction_db.get())
        return target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db

    def start_processing(self):
        try:
            input_path = self.input_path.get().strip()
            output_path = self.output_path.get().strip()

            if not input_path:
                messagebox.showerror("Missing input", "Choose an input WAV file.")
                return
            if not output_path:
                messagebox.showerror("Missing output", "Choose an output WAV file.")
                return

            target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db = self.get_current_limiter_settings()
            output_subtype = self.output_subtype.get()

        except ValueError:
            messagebox.showerror("Invalid settings", "Make sure all numeric settings are valid numbers.")
            return

        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, "Exporting limited WAV...\n")
        self.export_status_label.config(text="Exporting...")
        self.progress.start()

        thread = threading.Thread(
            target=self.process_in_thread,
            args=(input_path, output_path, target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db, output_subtype),
            daemon=True,
        )
        thread.start()

    def process_in_thread(self, input_path, output_path, target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db, output_subtype):
        try:
            report = process_file(
                input_path=input_path,
                output_path=output_path,
                target_lufs=target_lufs,
                ceiling_db=ceiling_db,
                lookahead_ms=lookahead_ms,
                release_ms=release_ms,
                max_allowed_reduction_db=max_allowed_reduction_db,
                output_subtype=output_subtype,
            )
            self.root.after(0, lambda: self.show_report(report))
        except Exception as error:
            self.root.after(0, lambda: self.show_error(error))

    def show_report(self, report):
        self.progress.stop()
        self.export_status_label.config(text="Export complete")

        safety_note = "Yes" if report.get("safety_limited") else "No"
        interpretation = (
            "The safety limit reduced the applied gain. The file was not pushed all the way to the target LUFS because that would have required more limiting than allowed."
            if report.get("safety_limited")
            else "The limiter stayed within the max reduction safety limit."
        )

        text = f"""
EXPORT REPORT
-------------

Input:
{report["input_path"]}

Output:
{report["output_path"]}

Sample rate:
{report["sample_rate"]} Hz

Output format:
{report["output_subtype"]}

LOUDNESS AND PEAKS
------------------
Original LUFS:          {report["original_lufs"]:.2f}
Original sample peak:   {report["original_peak"]:.4f} dBFS

Target LUFS:            {report["target_lufs"]:.2f}
Requested gain:         {report["requested_gain"]:.2f} dB
Applied gain:           {report["applied_gain"]:.2f} dB

LIMITER SAFETY
--------------
Max allowed reduction:  {report["max_allowed_reduction"]:.2f} dB
Actual max reduction:   {report["max_reduction"]:.2f} dB
Safety limited gain:    {safety_note}

FINAL RESULT
------------
Final LUFS:             {report["final_lufs"]:.2f}
Final sample peak:      {report["final_peak"]:.4f} dBFS

INTERPRETATION
--------------
{interpretation}

Note:
This limiter currently uses sample-peak limiting, not true-peak oversampling.
"""

        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, text)
        messagebox.showinfo("Finished", "Limited WAV export complete.")

    def show_error(self, error):
        self.progress.stop()
        self.preview_progress.stop()
        self.preview_progress_label.config(text="Preview idle")
        self.preview_rendering = False
        self.export_status_label.config(text="Export failed")
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, f"Error:\n{error}")
        messagebox.showerror("Processing failed", str(error))

    def start_original_playback(self):
        self.start_playback(mode="original")

    def start_limited_preview(self):
        self.start_playback(mode="limited")

    def start_playback(self, mode: str):
        if self.playing:
            self.stop_playback()

        input_path = self.input_path.get().strip()

        if not input_path:
            messagebox.showerror("Missing input", "Choose an input WAV file first.")
            return

        try:
            target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db = self.get_current_limiter_settings()
        except ValueError:
            messagebox.showerror("Invalid settings", "Make sure all numeric settings are valid numbers.")
            return

        self.playing = False
        self.preview_rendering = mode == "limited"
        self.playback_current_peak_db = -120.0
        self.playback_highest_peak_db = -120.0
        self.current_gain_reduction_db = 0.0
        self.max_preview_gain_reduction_db = 0.0

        with self.position_lock:
            self.playback_position = 0

        self.active_lufs_label.config(text="Active LUFS: --")
        self.current_peak_label.config(text="Current peak: --")
        self.highest_peak_label.config(text="Highest peak since play/seek: --")
        self.current_gr_label.config(text="Current GR: --")
        self.max_gr_label.config(text="Max GR in preview: --")
        self.playback_status_label.config(text="Loading...")

        if mode == "original":
            self.playback_mode_label.config(text="Mode: Original")
            self.preview_progress.stop()
            self.preview_progress_label.config(text="Original playback")
        else:
            self.playback_mode_label.config(text="Mode: Limited Preview")
            self.preview_progress_label.config(text="Rendering preview...")
            self.preview_progress.start(10)

        self.play_thread = threading.Thread(
            target=self.playback_worker,
            args=(input_path, mode, target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db),
            daemon=True,
        )

        self.play_thread.start()
        self.root.after(50, self.update_playback_meter)

    def stop_playback(self):
        self.playing = False
        self.preview_rendering = False

        try:
            sd.stop()
        except Exception:
            pass

        self.preview_progress.stop()
        self.playback_status_label.config(text="Stopped")

        if self.loaded_playback_mode == "limited":
            self.preview_progress_label.config(text="Preview stopped")
        else:
            self.preview_progress_label.config(text="Preview idle")

    def playback_worker(self, input_path, mode, target_lufs, ceiling_db, lookahead_ms, release_ms, max_allowed_reduction_db):
        try:
            if mode == "limited":
                self.meter_queue.put({"status": "Rendering limited preview...", "preview_rendering": True})

                audio, sample_rate, preview_report, gain_reduction_trace = render_preview(
                    input_path=input_path,
                    target_lufs=target_lufs,
                    ceiling_db=ceiling_db,
                    lookahead_ms=lookahead_ms,
                    release_ms=release_ms,
                    max_allowed_reduction_db=max_allowed_reduction_db,
                )

                self.loaded_gain_reduction_trace = gain_reduction_trace
                self.max_preview_gain_reduction_db = float(np.max(gain_reduction_trace)) if len(gain_reduction_trace) else 0.0

                status_text = (
                    f"Limited preview ready | LUFS {preview_report['final_lufs']:.2f}, "
                    f"sample peak {preview_report['final_peak']:.4f} dBFS, "
                    f"max GR {self.max_preview_gain_reduction_db:.2f} dB"
                )

                self.meter_queue.put(
                    {
                        "status": status_text,
                        "preview_done": True,
                        "max_gain_reduction": self.max_preview_gain_reduction_db,
                    }
                )

            else:
                self.meter_queue.put({"status": "Playing original input"})
                audio, sample_rate = sf.read(input_path, always_2d=True, dtype="float32")
                self.loaded_gain_reduction_trace = None
                self.max_preview_gain_reduction_db = 0.0

            audio = np.asarray(audio, dtype=np.float32)
            if audio.ndim == 1:
                audio = audio[:, None]

            self.loaded_playback_audio = audio
            self.loaded_playback_sample_rate = sample_rate
            self.loaded_playback_mode = mode

            self.meter_queue.put(
                {
                    "waveform_audio": audio,
                    "sample_rate": sample_rate,
                    "waveform_mode": mode,
                    "waveform_gain_reduction_trace": self.loaded_gain_reduction_trace,
                    "waveform_max_gain_reduction": self.max_preview_gain_reduction_db,
                }
            )

            self.preview_rendering = False
            self.playing = True

            block_size = 2048
            meter_window_seconds = 3.0
            meter_window_samples = int(sample_rate * meter_window_seconds)

            rolling_buffer = np.zeros((0, audio.shape[1]), dtype=np.float32)
            meter = pyln.Meter(sample_rate)

            def callback(outdata, frames, time, status):
                nonlocal rolling_buffer

                if not self.playing:
                    raise sd.CallbackStop

                with self.position_lock:
                    start = self.playback_position
                    end = start + frames
                    self.playback_position = end

                chunk = audio[start:end]

                if len(chunk) < frames:
                    pad = np.zeros((frames - len(chunk), audio.shape[1]), dtype=np.float32)
                    chunk = np.vstack([chunk, pad])
                    self.playing = False

                outdata[:] = chunk

                chunk_peak = np.max(np.abs(chunk))
                current_peak_db = 20 * np.log10(chunk_peak) if chunk_peak > 0 else -120.0
                self.playback_current_peak_db = current_peak_db

                if current_peak_db > self.playback_highest_peak_db:
                    self.playback_highest_peak_db = current_peak_db

                rolling_buffer = np.vstack([rolling_buffer, chunk])
                if len(rolling_buffer) > meter_window_samples:
                    rolling_buffer = rolling_buffer[-meter_window_samples:]

                active_lufs = None
                if len(rolling_buffer) >= int(sample_rate * 0.5):
                    try:
                        active_lufs = meter.integrated_loudness(rolling_buffer)
                    except Exception:
                        active_lufs = None

                current_gain_reduction = None
                if self.loaded_gain_reduction_trace is not None:
                    gr_start = max(0, start)
                    gr_end = min(len(self.loaded_gain_reduction_trace), end)
                    current_gain_reduction = float(np.max(self.loaded_gain_reduction_trace[gr_start:gr_end])) if gr_end > gr_start else 0.0

                with self.position_lock:
                    current_position = self.playback_position

                self.meter_queue.put(
                    {
                        "active_lufs": active_lufs,
                        "current_peak": self.playback_current_peak_db,
                        "highest_peak": self.playback_highest_peak_db,
                        "current_gain_reduction": current_gain_reduction,
                        "max_gain_reduction": self.max_preview_gain_reduction_db,
                        "position": current_position,
                        "total": len(audio),
                        "sample_rate": sample_rate,
                        "done": not self.playing,
                    }
                )

            with sd.OutputStream(samplerate=sample_rate, channels=audio.shape[1], dtype="float32", blocksize=block_size, callback=callback):
                while self.playing:
                    with self.position_lock:
                        if self.playback_position >= len(audio):
                            break
                    sd.sleep(100)

            self.playing = False
            self.meter_queue.put({"done": True})

        except Exception as error:
            self.playing = False
            self.preview_rendering = False
            self.meter_queue.put({"error": str(error), "done": True})

    def update_playback_meter(self):
        try:
            while True:
                data = self.meter_queue.get_nowait()

                if "error" in data:
                    self.playback_status_label.config(text="Error")
                    self.preview_progress.stop()
                    self.preview_progress_label.config(text="Preview idle")
                    self.preview_rendering = False
                    messagebox.showerror("Playback error", data["error"])
                    return

                if data.get("preview_rendering"):
                    self.preview_rendering = True
                    self.preview_progress.start(10)
                    self.preview_progress_label.config(text="Rendering preview...")

                if "status" in data:
                    self.playback_status_label.config(text=data["status"])

                if data.get("preview_done"):
                    self.preview_rendering = False
                    self.preview_progress.stop()
                    self.preview_progress_label.config(text="Preview ready")

                if "waveform_audio" in data:

                    self.root.after(
                        20,
                        lambda a=data["waveform_audio"],
                        sr=data["sample_rate"],
                        mode=data.get("waveform_mode"),
                        gr=data.get("waveform_gain_reduction_trace"),
                        max_gr=data.get("waveform_max_gain_reduction", 0.0): self.draw_waveform(
                            a,
                            sr,
                            mode,
                            gr,
                            max_gr,
                        ),
                    )

                active_lufs = data.get("active_lufs")
                current_peak = data.get("current_peak")
                highest_peak = data.get("highest_peak")
                current_gain_reduction = data.get("current_gain_reduction")
                max_gain_reduction = data.get("max_gain_reduction")
                position = data.get("position")
                total = data.get("total")
                sample_rate = data.get("sample_rate")

                if active_lufs is not None and np.isfinite(active_lufs):
                    self.active_lufs_label.config(text=f"Active LUFS: {active_lufs:.2f}")
                elif "active_lufs" in data:
                    self.active_lufs_label.config(text="Active LUFS: --")

                if current_peak is not None:
                    self.current_peak_label.config(text=f"Current peak: {current_peak:.4f} dBFS")

                if highest_peak is not None:
                    self.highest_peak_label.config(text=f"Highest peak since play/seek: {highest_peak:.4f} dBFS")

                if current_gain_reduction is not None:
                    self.current_gr_label.config(text=f"Current GR: {current_gain_reduction:.2f} dB")
                elif "current_gain_reduction" in data:
                    self.current_gr_label.config(text="Current GR: --")

                if max_gain_reduction is not None:
                    self.max_gr_label.config(text=f"Max GR in preview: {max_gain_reduction:.2f} dB")

                if position is not None and total is not None and sample_rate is not None:
                    self.update_playhead(position, total)
                    self.update_time_label(position, total, sample_rate)

                if data.get("done"):
                    self.playback_status_label.config(text="Stopped")
                    self.preview_rendering = False
                    self.preview_progress.stop()
                    self.preview_progress_label.config(text="Preview complete" if self.loaded_playback_mode == "limited" else "Preview idle")

        except queue.Empty:
            pass

        if self.playing or self.preview_rendering:
            self.root.after(100, self.update_playback_meter)

    def draw_waveform(self, audio, sample_rate, mode=None, gain_reduction_trace=None, max_gain_reduction=0.0):
        self.waveform_canvas.delete("all")
        self.waveform_canvas.update_idletasks()

        width = self.waveform_canvas.winfo_width()
        height = self.waveform_canvas.winfo_height()

        if width <= 20:
            width = 1200
        if height <= 20:
            height = 230

        if mode is None:
            mode = self.loaded_playback_mode

        if gain_reduction_trace is None:
            gain_reduction_trace = self.loaded_gain_reduction_trace

        audio_area_height = int(height * 0.64)
        gr_area_top = audio_area_height + 10
        gr_area_height = height - gr_area_top - 8

        mono = np.max(np.abs(audio), axis=1)
        samples_per_pixel = max(1, int(np.ceil(len(mono) / width)))

        center_y = audio_area_height // 2
        scale_y = audio_area_height * 0.44

        self.waveform_canvas.create_rectangle(0, 0, width, height, fill=WAVE_BG, outline=WAVE_BG)
        self.waveform_canvas.create_line(0, center_y, width, center_y, fill=WAVE_CENTER)

        if mode == "limited":
            self.waveform_info_label.config(text="Waveform: Limited Preview audio. Lower trace: limiter gain reduction.")
        else:
            self.waveform_info_label.config(text="Waveform: Original input audio. No gain-reduction trace is applied.")

        wave_color = WAVE_LIMITED if mode == "limited" else WAVE_LINE

        for x in range(width):
            start = x * samples_per_pixel
            end = min(start + samples_per_pixel, len(mono))
            if start >= len(mono):
                break

            segment = mono[start:end]
            peak = float(np.max(segment)) if len(segment) else 0.0
            y1 = center_y - peak * scale_y
            y2 = center_y + peak * scale_y
            self.waveform_canvas.create_line(x, y1, x, y2, fill=wave_color)

        self.waveform_canvas.create_line(0, audio_area_height + 4, width, audio_area_height + 4, fill=DIVIDER)
        self.waveform_canvas.create_rectangle(0, gr_area_top, width, height, fill=GR_BG, outline=GR_BG)

        if mode == "limited":
            self.draw_gain_reduction_trace(
                width,
                gr_area_top,
                gr_area_height,
                samples_per_pixel,
                gain_reduction_trace,
                max_gain_reduction,
            )
        else:
            self.waveform_scale_label.config(text="GR scale: not available for Original playback")

        self.waveform_playhead_id = self.waveform_canvas.create_line(0, 0, 0, height, fill=PLAYHEAD, width=2)
        self.update_time_label(0, len(audio), sample_rate)

    def draw_gain_reduction_trace(self, width, gr_area_top, gr_area_height, samples_per_pixel, gr_trace=None, max_gain_reduction=0.0):
        if gr_trace is None:
            gr_trace = self.loaded_gain_reduction_trace
        if gr_trace is None or len(gr_trace) == 0:
            self.waveform_scale_label.config(text="GR scale: trace missing")
            return

        trace_max = float(np.max(gr_trace))
        user_max = float(self.max_allowed_reduction_db.get() or 1.0)
        scale_max = max(0.25, trace_max, float(max_gain_reduction or 0.0), user_max)

        baseline = gr_area_top + gr_area_height - 5
        top_margin = gr_area_top + 22
        usable_height = max(1, baseline - top_margin)

        self.current_gr_trace_scale_db = scale_max
        self.waveform_scale_label.config(
            text=f"GR scale: 0 to {scale_max:.1f} dB | max detected: {trace_max:.2f} dB"
        )

        self.waveform_canvas.create_line(0, baseline, width, baseline, fill="#5a4630")

        if trace_max <= 0.0001:
            self.waveform_scale_label.config(text="GR scale: no gain reduction detected in this preview")
            return

        gr_peaks = []

        for x in range(width):
            start = x * samples_per_pixel
            end = min(start + samples_per_pixel, len(gr_trace))
            if start >= len(gr_trace):
                break

            value = float(np.max(gr_trace[start:end])) if end > start else 0.0
            gr_peaks.append(value)

            if value <= 0.0001:
                continue

            normalized = min(1.0, value / scale_max)
            y = baseline - normalized * usable_height

            if baseline - y < 2:
                y = baseline - 2

            color = GR_HOT if value >= scale_max * 0.75 else GR_LINE
            self.waveform_canvas.create_line(x, baseline, x, y, fill=color)

        self.waveform_gr_peaks = np.asarray(gr_peaks, dtype=np.float32)

    def update_playhead(self, position, total):
        if total <= 0:
            return

        width = self.waveform_canvas.winfo_width()
        height = self.waveform_canvas.winfo_height()

        if width <= 1:
            return

        x = int((position / total) * width)
        x = max(0, min(width - 1, x))

        if self.waveform_playhead_id is None:
            self.waveform_playhead_id = self.waveform_canvas.create_line(x, 0, x, height, fill=PLAYHEAD, width=2)
        else:
            self.waveform_canvas.coords(self.waveform_playhead_id, x, 0, x, height)

    def waveform_seek(self, event):
        audio = self.loaded_playback_audio
        if audio is None:
            return

        width = self.waveform_canvas.winfo_width()
        if width <= 1:
            return

        x = max(0, min(width - 1, event.x))
        ratio = x / width

        new_position = int(ratio * len(audio))
        new_position = max(0, min(len(audio) - 1, new_position))

        with self.position_lock:
            self.playback_position = new_position

        self.playback_current_peak_db = -120.0
        self.playback_highest_peak_db = -120.0
        self.current_gain_reduction_db = 0.0

        self.current_peak_label.config(text="Current peak: --")
        self.highest_peak_label.config(text="Highest peak since play/seek: --")
        self.current_gr_label.config(text="Current GR: --")

        self.update_playhead(new_position, len(audio))

        if self.loaded_playback_sample_rate:
            self.update_time_label(new_position, len(audio), self.loaded_playback_sample_rate)

    def update_time_label(self, position, total, sample_rate):
        current_seconds = position / sample_rate
        total_seconds = total / sample_rate
        self.playback_time_label.config(text=f"{self.format_time(current_seconds)} / {self.format_time(total_seconds)}")

    def format_time(self, seconds):
        seconds = max(0, int(seconds))
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"


def main():
    root = tk.Tk()
    app = LimiterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
