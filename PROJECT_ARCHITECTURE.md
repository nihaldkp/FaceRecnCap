# Project Architecture

## 1. Overall system architecture

```mermaid
flowchart LR
    U[Authorized user] --> GUI[Tkinter GUI - main.py]
    GUI -->|Start Camera| CW[CameraWorker thread]
    CW --> CAM[OpenCV VideoCapture]
    CAM --> FR[FaceRecognizer]
    RF[Known_Faces images] --> FR
    FR --> UI[Annotated frame and status]
    FR --> ATT[AttendanceStore]
    ATT --> DB[(SQLite attendance.db)]
    FR --> CAP[PhotoCaptureStore]
    CAP --> JPG[(Captured_Photos)]
    ATT --> CSV[CSV export]
```

## 2. Module responsibilities

| Module | Responsibility |
|---|---|
| `main.py` | Tkinter interface, user actions, webcam start/stop, frame display, registration queue, attendance and CSV controls |
| `face_recognition_module.py` | Reference-image validation, dlib/face-recognition encoding generation, tolerance matching, unknown classification, confirmation gate |
| `camera_module.py` | Webcam thread, frame snapshot, per-person capture scheduler, manual capture, photo storage |
| `attendance.py` | SQLite schema, duplicate-resistant insert, record query, UTF-8 CSV export |
| `tests/test_project.py` | Hardware-independent recognition, validation, capture, and scheduler tests |
| `tests/test_attendance.py` | SQLite duplicate and CSV tests |

## 3. Data flow diagram

```mermaid
flowchart TD
    A[Known_Faces image] --> B[Load and validate one face]
    B --> C[128-value face encoding]
    C --> D[In-memory encoding database]
    E[Webcam frame] --> F[Detect face locations]
    F --> G[Generate live encodings]
    D --> H[Euclidean distance comparison]
    G --> H
    H --> I{Distance <= 0.48 for 3 frames?}
    I -- Yes --> J[Confirmed known person]
    I -- No --> K[Unknown Person]
    J --> L[Attendance insert]
    J --> M{Manual or interval capture?}
    M -- Yes --> N[Timestamped JPEG]
    L --> O[SQLite]
    N --> P[Captured_Photos]
```

## 4. Recognition pipeline

```mermaid
sequenceDiagram
    participant GUI as Tkinter GUI
    participant CW as CameraWorker
    participant FR as FaceRecognizer
    participant FRLIB as dlib/face_recognition
    participant DB as SQLite

    GUI->>CW: Start Camera
    loop While camera is active
        CW->>CW: Read BGR frame
        CW->>FR: recognize(frame)
        FR->>FRLIB: Convert to RGB
        FRLIB-->>FR: Face locations
        FRLIB-->>FR: 128-value encodings
        FR->>FR: Compare distances and confirm 3 frames
        FR-->>CW: Known or unknown results
        CW->>GUI: Store latest frame and names
        alt Confirmed known person
            CW->>DB: Insert daily attendance
        end
    end
    GUI->>CW: Stop Camera
    CW->>CW: Release VideoCapture
```

## 5. Thread and resource behavior

- The camera loop runs in a daemon worker thread.
- Tkinter state is updated from the GUI polling loop.
- The worker stores frame data and results under locks.
- `CaptureScheduler` maintains separate monotonic timestamps per person.
- `VideoCapture.release()` runs in the worker's `finally` block.
- `Exit` and `Stop Camera` request worker shutdown.

## 6. Database design

Table: `attendance`

| Column | Type | Constraint |
|---|---|---|
| `id` | INTEGER | Primary key |
| `name` | TEXT | Not null |
| `attendance_date` | TEXT | `YYYY-MM-DD` |
| `attendance_time` | TEXT | `HH:MM:SS` |

Unique constraint: `(name, attendance_date)`.

## 7. Privacy boundaries

- Camera access is not initiated during initialization.
- Automatic capture defaults to OFF.
- Manual capture requires an active camera frame.
- Unknown people are not recorded or automatically captured.
- Existing files are never overwritten because filenames include microsecond timestamps.
