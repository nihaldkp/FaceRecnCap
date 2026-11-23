"""Tkinter desktop application for face recognition and attendance."""

from __future__ import annotations

import base64
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2

from attendance import AttendanceStore
from camera_module import CameraError, CameraWorker, PhotoCaptureStore
from face_recognition_module import FaceMatch, FaceRecognitionError, FaceRecognizer


PROJECT_DIR = Path(__file__).resolve().parent


class FaceRecognitionApp:
    """Desktop UI. Webcam access begins only after Start Camera is pressed."""

    BG = "#101820"
    PANEL = "#192630"
    ACCENT = "#24b8a6"
    ACCENT_SOFT = "#bfeee7"
    WARNING = "#f4ba64"
    ERROR = "#ef6b73"
    SUCCESS = "#6ed49a"
    TEXT = "#eef4f7"
    MUTED = "#a9bac4"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Face Recognition & Attendance")
        self.root.geometry("1120x780")
        self.root.minsize(900, 650)
        self.root.configure(bg=self.BG)

        self.known_faces_dir = PROJECT_DIR / "Known_Faces"
        self.captured_photos_dir = PROJECT_DIR / "Captured_Photos"
        self.attendance_dir = PROJECT_DIR / "Attendance_Records"
        for directory in (
            self.known_faces_dir,
            self.captured_photos_dir,
            self.attendance_dir,
            PROJECT_DIR / "assets",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.attendance = AttendanceStore(self.attendance_dir / "attendance.db")
        self.photo_store = PhotoCaptureStore(self.captured_photos_dir)
        self.recognizer = FaceRecognizer(self.known_faces_dir)
        self.worker: CameraWorker | None = None
        self.registration_queue: queue.Queue[tuple[bool, str]] = queue.Queue()
        self.registration_in_progress = False
        self.auto_capture_var = tk.BooleanVar(value=False)
        self.capture_interval_var = tk.StringVar(value="5")
        self.notice_var = tk.StringVar(value="Camera is off. Start it when you are ready.")
        self.camera_status_var = tk.StringVar(value="OFF")
        self.recognized_name_var = tk.StringVar(value="—")
        self.photo_count_var = tk.StringVar(value=str(self.photo_store.count))

        self._configure_style()
        self._build_ui()
        self.root.bind("<space>", self._handle_space_capture)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        try:
            warnings = self.recognizer.reload_known_faces()
            if warnings:
                self.notice_var.set("Some Known_Faces images were skipped; see registration requirements.")
        except FaceRecognitionError as exc:
            self.notice_var.set(str(exc))
        self._poll()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TButton",
            background="#263944",
            foreground=self.TEXT,
            borderwidth=0,
            padding=(13, 9),
            font=("Segoe UI", 10),
        )
        style.map("TButton", background=[("active", "#35515e"), ("disabled", "#27333a")])
        style.configure(
            "Accent.TButton",
            background=self.ACCENT,
            foreground="#071a1a",
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#43d2bf")])
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=self.BG, padx=26, pady=18)
        header.pack(fill="x")
        tk.Label(
            header,
            text="FACE RECOGNITION",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Live identification  •  Automatic photo capture  •  Daily attendance",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        content = tk.Frame(self.root, bg=self.BG, padx=22, pady=4)
        content.pack(fill="both", expand=True)
        video_panel = tk.Frame(content, bg="#0a1116", highlightthickness=1, highlightbackground="#304550")
        video_panel.pack(side="left", fill="both", expand=True)
        self.video_label = tk.Label(
            video_panel,
            text="Camera is off\n\nClick  Start Camera  when you are ready",
            bg="#0a1116",
            fg=self.MUTED,
            font=("Segoe UI", 15),
            justify="center",
            takefocus=True,
        )
        self.video_label.pack(fill="both", expand=True)

        side = tk.Frame(content, bg=self.PANEL, width=270, padx=18, pady=18)
        side.pack(side="right", fill="y", padx=(16, 0))
        side.pack_propagate(False)
        tk.Label(side, text="SESSION", bg=self.PANEL, fg=self.ACCENT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._info_row(side, "Recognized person", self.recognized_name_var)
        self._info_row(side, "Camera status", self.camera_status_var)
        self._info_row(side, "Captured photos", self.photo_count_var)

        tk.Frame(side, height=1, bg="#304550").pack(fill="x", pady=16)
        tk.Label(side, text="CAPTURE SETTINGS", bg=self.PANEL, fg=self.ACCENT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Checkbutton(side, text="Automatic capture", variable=self.auto_capture_var).pack(anchor="w", pady=(12, 8))
        interval = tk.Frame(side, bg=self.PANEL)
        interval.pack(fill="x")
        tk.Label(interval, text="Per-person interval (seconds)", bg=self.PANEL, fg=self.MUTED).pack(anchor="w")
        ttk.Spinbox(interval, from_=0.5, to=3600, increment=0.5, textvariable=self.capture_interval_var, width=12).pack(anchor="w", pady=(5, 0))
        tk.Label(
            side,
            text="Automatic photos are saved only while the camera is running and this setting is enabled.",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Segoe UI", 8),
            wraplength=230,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        controls = tk.Frame(self.root, bg=self.BG, padx=22, pady=14)
        controls.pack(fill="x")
        ttk.Button(controls, text="Start Camera", style="Accent.TButton", command=self.start_camera).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Stop Camera", command=self.stop_camera).pack(side="left", padx=4)
        ttk.Button(controls, text="Capture Photo", command=self.capture_photo).pack(side="left", padx=4)
        ttk.Button(controls, text="Register Face", command=self.register_face).pack(side="left", padx=4)
        ttk.Button(controls, text="View Attendance", command=self.view_attendance).pack(side="left", padx=4)
        ttk.Button(controls, text="Export CSV", command=self.export_attendance).pack(side="left", padx=4)
        ttk.Button(controls, text="Exit", command=self.close).pack(side="right")

        tk.Label(
            self.root,
            textvariable=self.notice_var,
            anchor="w",
            bg="#0c1419",
            fg=self.MUTED,
            padx=24,
            pady=9,
            font=("Segoe UI", 9),
        ).pack(fill="x", side="bottom")

    @staticmethod
    def _info_row(parent: tk.Widget, title: str, value: tk.StringVar) -> None:
        row = tk.Frame(parent, bg=FaceRecognitionApp.PANEL)
        row.pack(fill="x", pady=(14, 0))
        tk.Label(row, text=title, bg=FaceRecognitionApp.PANEL, fg=FaceRecognitionApp.MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(row, textvariable=value, bg=FaceRecognitionApp.PANEL, fg=FaceRecognitionApp.TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(3, 0))

    def start_camera(self) -> None:
        if self.worker is not None and self.worker.is_alive:
            return
        try:
            interval = float(self.capture_interval_var.get())
            if interval <= 0:
                raise ValueError("The capture interval must be greater than zero.")
            self.worker = CameraWorker(
                recognizer=self.recognizer,
                photo_store=self.photo_store,
                on_recognized=self.attendance.record_attendance,
                capture_interval=interval,
                auto_capture=self.auto_capture_var.get(),
            )
            self.worker.start()
            self.video_label.focus_set()
            self.camera_status_var.set("STARTING…")
            self.notice_var.set("Opening webcam. Camera access was requested by you.")
        except (ValueError, CameraError, FaceRecognitionError) as exc:
            self.camera_status_var.set("ERROR")
            self.notice_var.set(str(exc))
            messagebox.showerror("Unable to start camera", str(exc), parent=self.root)

    def stop_camera(self) -> None:
        if self.worker is None:
            self.camera_status_var.set("OFF")
            self.auto_capture_var.set(False)
            return
        stopped = self.worker.stop()
        self.camera_status_var.set("OFF" if stopped else "STOPPING…")
        self.auto_capture_var.set(False)
        self.notice_var.set("Camera stopped." if stopped else "Waiting for camera to release…")
        if stopped:
            self.video_label.configure(image="", text="Camera is off\n\nClick  Start Camera  when you are ready")
            self.video_label.image = None
            self.recognized_name_var.set("—")

    def capture_photo(self) -> None:
        if self.worker is None:
            messagebox.showinfo("Camera is off", "Start the camera before taking a photo.", parent=self.root)
            return
        try:
            path = self.worker.capture_manual()
            self.photo_count_var.set(str(self.photo_store.count))
            self.notice_var.set("Photo saved: " + path.name)
        except (CameraError, OSError, ValueError) as exc:
            self.notice_var.set(str(exc))
            messagebox.showerror("Photo not captured", str(exc), parent=self.root)

    def _handle_space_capture(self, _event) -> str | None:
        if self.worker is not None and self.worker.camera_active:
            self.capture_photo()
            return "break"
        return None

    def register_face(self) -> None:
        if self.registration_in_progress:
            return
        name = simpledialog.askstring("Register face", "Enter the person's name:", parent=self.root)
        if name is None:
            return
        image_path = filedialog.askopenfilename(
            parent=self.root,
            title="Select a clear image containing one face",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp"), ("All files", "*.*")],
        )
        if not image_path:
            return
        self.registration_in_progress = True
        self.notice_var.set("Validating and registering face…")

        def register() -> None:
            try:
                destination = self.recognizer.register_face(Path(image_path), name)
                self.registration_queue.put((True, destination.name))
            except (FaceRecognitionError, OSError, ValueError) as exc:
                self.registration_queue.put((False, str(exc)))

        threading.Thread(target=register, name="face-registration", daemon=True).start()

    def view_attendance(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Attendance Records")
        window.geometry("610x430")
        window.configure(bg=self.BG)
        columns = ("name", "date", "time")
        table = ttk.Treeview(window, columns=columns, show="headings")
        for column, title, width in (
            ("name", "Person", 260),
            ("date", "Date", 150),
            ("time", "Time", 150),
        ):
            table.heading(column, text=title)
            table.column(column, width=width, anchor="w")
        table.pack(fill="both", expand=True, padx=16, pady=16)
        for record in self.attendance.get_records():
            table.insert("", "end", values=record)

    def export_attendance(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export attendance",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="attendance.csv",
        )
        if not path:
            return
        try:
            count = self.attendance.export_csv(Path(path))
            self.notice_var.set(f"Exported {count} attendance record(s).")
            messagebox.showinfo("Export complete", f"Exported {count} record(s) to:\n{path}", parent=self.root)
        except OSError as exc:
            self.notice_var.set(f"CSV export failed: {exc}")
            messagebox.showerror("Export failed", str(exc), parent=self.root)

    def _draw_frame(self, frame, matches: tuple[FaceMatch, ...]) -> None:
        height, width = frame.shape[:2]
        display_width = max(1, self.video_label.winfo_width())
        display_height = max(1, self.video_label.winfo_height())
        scale = min(display_width / width, display_height / height, 1.0)
        shown = cv2.resize(frame, (int(width * scale), int(height * scale))) if scale < 1 else frame.copy()
        recognized_names: list[str] = []
        for match in matches:
            top, right, bottom, left = match.location
            top, right, bottom, left = (int(value * scale) for value in (top, right, bottom, left))
            color = (58, 205, 98) if match.is_known else (55, 75, 235)
            cv2.rectangle(shown, (left, top), (right, bottom), color, 2)
            label = match.name if match.is_known else "Unknown Person"
            cv2.putText(shown, label, (left, max(22, top - 9)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
            if match.is_known and match.name not in recognized_names:
                recognized_names.append(match.name)
        if not recognized_names:
            self.recognized_name_var.set("Unknown Person" if matches else "—")
        elif len(recognized_names) == 1:
            self.recognized_name_var.set(recognized_names[0])
        else:
            self.recognized_name_var.set(", ".join(recognized_names))
        success, encoded = cv2.imencode(".png", shown)
        if success:
            photo = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()).decode("ascii"))
            self.video_label.configure(image=photo, text="")
            self.video_label.image = photo

    def _poll(self) -> None:
        if self.worker is not None:
            try:
                interval = float(self.capture_interval_var.get())
                if interval <= 0:
                    raise ValueError
                self.worker.update_capture_settings(interval, self.auto_capture_var.get())
            except ValueError:
                self.notice_var.set("Enter a capture interval greater than zero.")
            if self.worker.camera_active:
                self.camera_status_var.set("ACTIVE")
                snapshot = self.worker.get_latest_snapshot()
                if snapshot is not None:
                    self._draw_frame(*snapshot)
            elif self.worker.is_alive:
                self.camera_status_var.set("STARTING…")
            elif self.camera_status_var.get() == "STOPPING…":
                self.camera_status_var.set("OFF")
                self.video_label.configure(image="", text="Camera is off\n\nClick  Start Camera  when you are ready")
                self.video_label.image = None
            error = self.worker.pop_error()
            if error:
                self.notice_var.set(error)
                if not self.worker.is_alive:
                    self.camera_status_var.set("ERROR")
                    messagebox.showerror("Camera error", error, parent=self.root)
            self.photo_count_var.set(str(self.photo_store.count))

        try:
            registered, result = self.registration_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.registration_in_progress = False
            if registered:
                self.notice_var.set(f"Registered {result}. Known faces have been reloaded.")
                messagebox.showinfo("Face registered", f"{result} was added to Known_Faces.", parent=self.root)
            else:
                self.notice_var.set(result)
                messagebox.showerror("Registration failed", result, parent=self.root)
        self.root.after(100, self._poll)

    def close(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    FaceRecognitionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
