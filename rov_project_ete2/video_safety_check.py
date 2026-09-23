
"""
FFmpeg Backend Video Diagnostic & Corrupted Frame Probe Utility

Purpose in Pipeline:
    Serves as an isolated diagnostic tool to analyze video stream corruption,
    probe decoding recovery past broken frames, and generate detailed frame-by-frame 
    read logs (`video_diagnostic_report.txt`) using an explicit FFmpeg decoder backend.

Key Functionality:
    - Explicit Backend Decoding: Forces `cv2.CAP_FFMPEG` to override default system
      decoders and safely handle malformed MP4 container headers.
    - Fast Frame Seeking: Jumps directly to a targeted frame offset (`START_FRAME`) 
      to isolate specific points of failure without reading the entire stream.
    - Recovery Probing: Continues reading forward after a failed decode (`success == False`)
      to evaluate if stream recovery is possible or if truncation is permanent.
    - Diagnostic Logging: Exports a line-by-line audit trail of frame index accessibility.

Dependencies:
    - opencv-python (cv2)
    - sys
"""
import cv2
import sys
import time

VIDEO_FILENAME = "fixed2_video_tanzania.mp4"
START_FRAME = 13172
OUTPUT_LOG_FILE = "video_diagnostic_report.txt"  # The file where everything will be saved

def run_diagnostic():
    print(f"--- Starting Full Video Diagnostic Tool ---")
    print(f"Opening video file: {VIDEO_FILENAME} with explicit FFMPEG backend...")
    
    # INTEGRATED: Forcing the FFMPEG backend engine explicitly
    cap = cv2.VideoCapture(VIDEO_FILENAME, cv2.CAP_FFMPEG)
    
    if not cap.isOpened():
        print("Error: Could not open video file.")
        sys.exit(1)
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Total frames reported by header: {total_frames}")

    cap.set(cv2.CAP_PROP_POS_FRAMES, START_FRAME)
    
    diagnostic_logs = []
    print(f"Processing and saving to {OUTPUT_LOG_FILE}... Please wait.")
    
    while True:
        current_frame_id = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        success, frame = cap.read()
        
        log_line = f"{current_frame_id} | {success}"
        diagnostic_logs.append(log_line)
        
        if not success:
            while True:
                next_id = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) + 1
                next_success, _ = cap.read()
                
                if next_id == current_frame_id or next_id < 0:
                    break
                
                diagnostic_logs.append(f"{next_id} | {next_success}")
                if next_id >= total_frames:
                    break
                    
                current_frame_id = next_id
            break

    cap.release()
    
    # --- WRITE EVERYTHING TO A TEXT FILE ---
    with open(OUTPUT_LOG_FILE, "w") as f:
        f.write("============================= DIAGNOSTIC REPORT =============================\n")
        f.write("frame_id | success\n")
        f.write("-------------------\n")
        for log in diagnostic_logs:
            f.write(log + "\n")
        f.write("============================= END OF THE CODE =============================\n")
        
    print(f"\nSuccess! Go open the file '{OUTPUT_LOG_FILE}' to see all lines starting from 13172.")

if __name__ == "__main__":
    run_diagnostic()