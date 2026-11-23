# Viva Questions and Answers

1. **What is face recognition?**  
   It identifies a person by converting a face image into a numerical encoding and comparing it with stored encodings.

2. **How is a face detected?**  
   dlib/HOG face detection returns rectangular face locations in an RGB frame.

3. **What is a face encoding?**  
   It is a 128-number vector generated from face landmarks and appearance features.

4. **How does registration work?**  
   The GUI asks for a name and image, validates exactly one face, copies the image to `Known_Faces`, creates an encoding, and reloads known faces.

5. **Why is exactly one face required during registration?**  
   It prevents a person name from being associated with the wrong face or with multiple people.

6. **What tolerance is used?**  
   The configured threshold is `0.48`; a lower Euclidean distance means greater similarity.

7. **Why require three consecutive frames?**  
   It reduces transient false positives caused by a short pose, lighting, or detection fluctuation.

8. **What does unknown mean?**  
   No registered encoding is within the distance threshold for enough consecutive frames.

9. **How are known and unknown faces displayed?**  
   Known faces use a green rectangle and name; unknown faces use a red rectangle and `Unknown Person`.

10. **What is Euclidean distance here?**  
    It is the straight-line distance between 128-dimensional numerical encodings.

11. **Why may recognition fail under poor lighting?**  
    Lighting changes pixel appearance and can change the calculated encoding distance.

12. **Why may angles affect recognition?**  
    A side or tilted face is less similar to a frontal reference image.

13. **How is the webcam used safely?**  
    The worker starts only after the user chooses **Start Camera**.

14. **Why does the app use threads?**  
    Webcam reads and face processing run in a worker thread so Tkinter controls remain responsive.

15. **How is the live frame delivered to Tkinter?**  
    The worker locks and stores the latest frame, and the GUI polling loop redraws it.

16. **How is automatic capture scheduled?**  
    Each person's last capture time is stored by name using monotonic seconds.

17. **What is the default interval?**  
    Five seconds per recognized person.

18. **How are intervals independent?**  
    The scheduler stores a separate last-capture timestamp for each person name.

19. **What is the difference between manual and automatic capture?**  
    Manual capture is triggered by the button or SPACE; automatic capture follows the enabled interval.

20. **Why does manual capture require the camera?**  
    It prevents a photo action when no live frame exists.

21. **How does attendance duplicate prevention work?**  
    SQLite has a unique constraint on person name and local date.

22. **What attendance fields are stored?**  
    Person name, date in `YYYY-MM-DD`, and time in `HH:MM:SS`.

23. **How is unknown-person attendance prevented?**  
    Only confirmed known names are passed to `record_attendance`.

24. **How is CSV export implemented?**  
    `AttendanceStore.export_csv()` queries records and writes UTF-8 CSV with a header.

25. **How is SQLite thread safety handled?**  
    Attendance operations use a lock and open a fresh connection for each operation.

26. **How is camera cleanup implemented?**  
    The worker calls `capture.release()` in a `finally` block and the GUI requests shutdown on exit.

27. **Why is automatic capture off by default?**  
    It follows privacy by design: image saving is not enabled until the user explicitly enables it.

28. **What are the project limitations?**  
    Single-reference recognition, variable pose/lighting accuracy, camera availability, and no liveness detection.

29. **What is liveness detection?**  
    A technique for deciding whether a real, present person is in front of the camera rather than a photograph or replay.

30. **What future improvements are suitable?**  
    Multiple reference images, liveness checks, camera selection, calibrated thresholds, and stronger retention controls.
