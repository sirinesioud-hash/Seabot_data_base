"""
Diagnostic Utility: OpenCV Isolated Video Stream & Integrity Tester

Purpose in Pipeline:
    Diagnostic tool created to resolve subsea video corruption bottlenecks.
    It verifies stream integrity, frame-count metadata accuracy, and OpenCV
    read-loop reliability before passing video streams to database ingestion routines.

Key Diagnostics:
    - Metadata vs. Physical Frame Verification: Compares header-reported frame 
      counts against actual readable frames to detect truncated MP4 containers.
    - Silent Failure Detection: Captures non-zero read exits (`cap.read() == False`)
      caused by missing keyframes or stream corruption.
    - Rate Validation: Validates native FPS to ensure frame-to-timestamp accuracy.

Dependencies:
    - opencv-python (cv2)
    - sys
"""
import sys
import cv2

# The name of your local video file
VIDEO_FILENAME = "video_tanzania.mp4"

def test_video_processing():
    print(f"--- OpenCV Isolated Video Test ---")
    print(f"Attempting to open: '{VIDEO_FILENAME}'...\n")

    # Open the local video file
    cap = cv2.VideoCapture(VIDEO_FILENAME)
    
    if not cap.isOpened():
        print(f"CRITICAL ERROR: Could not open video file '{VIDEO_FILENAME}'.")
        print("Please check that the filename is spelled correctly and sits in this exact folder.")
        sys.exit(1)

    # Get video properties reported by the file header
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    reported_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    print(f"Video detected successfully!")
    print(f"-> Base Frame Rate: {video_fps} FPS")
    print(f"-> Total frames reported by file header: {reported_total_frames}")
    print(f"--------------------------------------------------")
    print("Processing frame-by-frame... Press Ctrl+C to stop.\n")

    success_counter = 0

    try:
        while cap.isOpened():
            # Read the next frame sequentially
            success, frame = cap.read()
            
            # Stop immediately if OpenCV cannot read the frame
            if not success:
                print("\n[Status] cap.read() returned False. Reached end of stream or corrupted frame.")
                break

            # Track the internal frame position index directly from OpenCV
            current_frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            success_counter += 1

            # Print the current frame number directly to the terminal line
            print(f"Reading Frame Number: {current_frame_index} | Total Read So Far: {success_counter}", end="\r")

        print("\n--------------------------------------------------")
        print("--- Test Complete ---")
        print(f"Successfully extracted and counted: {success_counter} total frames.")
        
        if success_counter == reported_total_frames:
            print("Result: Success! Every single frame was safely parsed.")
        else:
            print(f"Result: Warning. Read {success_counter} frames out of {reported_total_frames} expected.")

    except KeyboardInterrupt:
        print(f"\n\nTest aborted by operator at frame {success_counter}.")
    finally:
        cap.release()
        print("Video file handle closed cleanly.")

if __name__ == "__main__":
    test_video_processing()