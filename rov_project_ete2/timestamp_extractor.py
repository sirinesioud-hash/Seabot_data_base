
"""
Target Timestamp Frame Extractor & Manifest Generator

Purpose in Pipeline:
    Provides automated extraction of key inspection video frames at targeted 
    time offsets (MM:SS). Translates temporal offsets into discrete frame indices 
    to generate visual inspection snapshot evidence and structured manifest reports.

Key Functionality:
    - Mathematical Seeking: Applies exact frame calculation 
      (frame_id = int(FPS * total_seconds)) to convert time vectors into frame indices.
    - Direct Pointer Seeking: Teleports OpenCV read pointers directly using 
      `cv2.CAP_PROP_POS_FRAMES` without sequential frame reading overhead.
    - Snapshot Export: Saves extracted frame images into disk as JPEG files (`frame_MMm_SSs.jpg`).
    - Structured Manifest Reporting: Outputs a formatted audit file (`manifest.txt`) 
      mapping relative timestamps to internal frame numbers and file paths.

Dependencies:
    - opencv-python (cv2)
    - os, sys
"""
import os
import sys
import cv2

# Configuration
VIDEO_FILENAME = "yo_voy.mp4"
OUTPUT_DIR = "extracted_frames"

# The tuple containing your 10 target timestamps (minutes, seconds)
TARGET_TIMESTAMPS = (
    (0, 5),    # 00:05
    (0, 30),   # 00:15
    (1, 28),   # 00:28
    (1, 45),   # 00:45
    (2, 2),    # 01:02
    (3, 20),   # 01:20
    (3, 45),   # 01:45
    (4, 5),    # 02:05
    (5, 30),   # 02:30
    (6, 0)     # 03:00
)

def extract_specific_timestamps():
    print("--- ROV Target Frame Extraction Tool ---")
    
    # Create the output directory if it doesn't exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created directory: '{OUTPUT_DIR}'")

    # Open the video file
    cap = cv2.VideoCapture(VIDEO_FILENAME)
    if not cap.isOpened():
        print(f"CRITICAL ERROR: Could not open video file '{VIDEO_FILENAME}'.")
        sys.exit(1)

    # Fetch FPS to calculate exact frame matching math
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30.0  
    
    print(f"Video opened successfully. Base Frame Rate: {fps} FPS")
    print(f"Targeting {len(TARGET_TIMESTAMPS)} distinct timestamps sequentially...\n")

    # Path for your organized text report file inside the directory
    manifest_path = os.path.join(OUTPUT_DIR, "manifest.txt")
    
    # Open the text file to write your structured data report
    with open(manifest_path, "w") as manifest_file:
        manifest_file.write("=========================================================\n")
        manifest_file.write("             ROV EXTRACTION MISSION MANIFEST             \n")
        manifest_file.write("=========================================================\n")
        manifest_file.write(f"Source Video: {VIDEO_FILENAME}\n")
        manifest_file.write(f"Video FPS:    {fps}\n")
        manifest_file.write("---------------------------------------------------------\n")
        manifest_file.write(f"{'TIMESTAMP':<12} | {'FRAME ID':<10} | {'SAVED FILENAME':<25}\n")
        manifest_file.write("---------------------------------------------------------\n")

        # Loop through the 10 timestamp values successively
        for idx, (minutes, seconds) in enumerate(TARGET_TIMESTAMPS, start=1):
            # Apply the exact seeking formula calculation
            frame_id = int(fps * (minutes * 60 + seconds))
            
            # Format clean strings for filenames and logs
            timestamp_str = f"{minutes:02d}m_{seconds:02d}s"
            image_filename = f"frame_{timestamp_str}.jpg"
            image_save_path = os.path.join(OUTPUT_DIR, image_filename)

            # Teleport OpenCV directly to our calculated frame coordinate index
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
            
            # Capture the frame state
            ret, frame = cap.read()

            if ret:
                # Save the image frame directly as a standard, independent .jpg file
                cv2.imwrite(image_save_path, frame)
                
                # Format a log string for the text sheet
                log_entry = f"{minutes:02d}:{seconds:02d}{'':<7} | {frame_id:<10} | {image_filename:<25}\n"
                manifest_file.write(log_entry)
                
                print(f"[{idx}/10] Success! Target {minutes:02d}:{seconds:02d} -> Saved Frame ID: {frame_id}")
            else:
                error_entry = f"{minutes:02d}:{seconds:02d}{'':<7} | {frame_id:<10} | [FAILED TO EXTRACT]\n"
                manifest_file.write(error_entry)
                print(f"[{idx}/10] Failed! Timestamp {minutes:02d}:{seconds:02d} out of bounds.")

        manifest_file.write("=========================================================\n")

    cap.release()
    print(f"\n--- Complete! ---")
    print(f"All standard .jpg images and the manifest text file are ready inside: '{OUTPUT_DIR}/'")

if __name__ == "__main__":
    extract_specific_timestamps()