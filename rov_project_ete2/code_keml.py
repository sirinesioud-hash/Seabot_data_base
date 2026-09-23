"""

DESCRIPTION:
    This script serves as a standalone database test harness designed to validate 
    video-telemetry frame-level synchronization and schema ingestion into 
    PostgreSQL prior to full ROS 2 system integration.

KEY FEATURES:
    1. Video Metadata Extraction:
       Uses OpenCV (`cv2`) to analyze input video stream properties including 
       Frame Rate (FPS) and total duration.
       
    2. Spatial-Temporal Alignment:
       Calculates the absolute real-world GPS time ($t_{\text{abs}} = t_0 + \Delta t$) 
       and relative video offset (HH:MM:SS) for second-by-second sampling.
       
    3. PostGIS Ingestion:
       Constructs native spatial geometry points using `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` 
       and batches synchronized rows into the TimescaleDB `rov_telemetry` hypertable.

DATABASE TARGET:
    Table: public.rov_telemetry
    Columns: time (PK/TimescaleDB index), mission_id, video_timestamp, distance_meters, geom

DEPENDENCIES:
    - OpenCV (cv2)
    - psycopg2
    - PostgreSQL with TimescaleDB & PostGIS extensions enabled
===============================================================================
"""
import cv2  # OpenCV: For analyzing video metadata
import psycopg2  # PostgreSQL Driver: To send data to TimescaleDB
from datetime import datetime, timedelta

# 1. DATABASE CONFIGURATION
# This tells Python where your pgAdmin/TimescaleDB is running on your computer.
DB_CONFIG = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",  # Your local pgAdmin password
    "host": "localhost",
    "port": "5432"
}


def sync_and_insert_data(video_path, mock_sensor_data, mission_id, start_time_str):
    """
    Step-by-step pipeline to extract video time, pair it with coordinates and 
    ultrasonic distance, and save it to TimescaleDB.
    """
    # Parse the real-world start time of the dive (GPS reference time)
    # TimescaleDB requires this absolute clock to partition the data.
    base_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")

    # Step A: Connect to PostgreSQL/TimescaleDB
    print("Connecting to TimescaleDB...")
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Step B: Open the video file using OpenCV
    print(f"Opening video file: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Could not open video file.")
        return

    # Step C: Read video properties
    # We need the Frame Rate (FPS) to know how many frames represent 1 second of diving.
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_seconds = int(total_frames / fps)

    print(f"Video Loaded: {fps} FPS | Duration: {duration_seconds} seconds")

    # Step D: Loop through the video, second by second, and sync sensor data
    print("Starting synchronization and database write...")
    for second in range(duration_seconds):
        
        # 1. Calculate the relative video timestamp (Format: HH:MM:SS)
        # This is what we display on the video player in our app.
        video_offset = str(timedelta(seconds=second))

        # 2. Calculate the absolute real-world GPS time
        # This is what TimescaleDB uses to index and slice the hypertable.
        absolute_time = base_time + timedelta(seconds=second)

        # 3. Pull sensor data matching this exact second
        # If no data exists for this second, we default to 0.0 values.
        sensor_entry = mock_sensor_data.get(
            second, 
            {"distance": 0.0, "lat": 0.0, "lon": 0.0}
        )

        # 4. Prepare our SQL Command
        # ST_SetSRID and ST_MakePoint are PostGIS functions that convert 
        # longitude and latitude into a single geographic "Point" coordinate.
        query = """
            INSERT INTO rov_telemetry (time, mission_id, video_timestamp, distance_meters, geom)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326));
        """

        # Execute the query with our calculated values
        cursor.execute(query, (
            absolute_time,
            mission_id,
            video_offset,
            sensor_entry["distance"],
            sensor_entry["lon"],  # Longitude ALWAYS goes first in PostGIS!
            sensor_entry["lat"]   # Latitude second
        ))

    # Commit (save) the changes permanently to the database
    conn.commit()
    print(f"Sync complete! {duration_seconds} rows successfully saved.")

    # Cleanup resources
    cap.release()
    cursor.close()
    conn.close()

# Example Execution
if __name__ == "__main__":
    # Mock data representing sensor files (Time in seconds -> USBL coordinates + Ultrasonic distance)
    # When your ROV operates, it will log coordinates and ultrasonic distances like this:
    sample_sensor_logs = {
        0: {"distance": 2.50, "lat": 35.77912, "lon": -5.81234},
        1: {"distance": 2.48, "lat": 35.77913, "lon": -5.81235},
        2: {"distance": 2.45, "lat": 35.77915, "lon": -5.81237},
    }

    # Run the script: Pass video, logs, the mission name, and the exact real-world start time of the dive
    # sync_and_insert_data("my_test_video.mp4", sample_sensor_logs, "MISSION-001", "2026-07-03 10:00:00")
    pas

