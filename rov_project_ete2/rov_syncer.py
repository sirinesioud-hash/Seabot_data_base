
"""
ROV Synchronizer & Standalone Mission Telemetry Logger

Purpose in Pipeline:
    Serves as the standalone database execution harness and synchronization engine. 
    It manages client profile lookup/creation, registers new subsea missions, and 
    executes frame-locked, multi-rate telemetry logging into PostgreSQL (TimescaleDB + PostGIS).

Key Functionality:
    - Relational Client Verification: Queries `public.clients` for existing client 
      profiles or inserts new entities returning auto-incremented Primary Keys (`client_id`).
    - Mission Lifecycle Registration: Binds active dives to `public.missions` via 
      `client_id` Foreign Key and links video asset paths (`video_link`).
    - Multi-Rate Telemetry Gating: Downsamples video streams (30 FPS) to simulate 
      heterogeneous sensor rates—10 Hz depth/distance logging and 1 Hz USBL positioning updates.
    - Mathematical Frame Synchronization: Maps current frame indices to exact relative 
      video timestamps (`timedelta(seconds=current_frame/video_fps)`).
    - PostGIS Spatial Ingestion: Formats WGS 84 spatial coordinates into PostGIS geometries 
      using `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` for the `rov_telemetry` hypertable.

Dependencies:
    - opencv-python (cv2)
    - psycopg2
    - datetime, timedelta, random, sys, time
"""
import sys
import time
from datetime import datetime, timedelta
import random
import psycopg2
import cv2 

# Database Connection Configuration
DB_CONFIG = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",  
    "host": "localhost",
    "port": "5432"
}

VIDEO_FILENAME = "yo_voy.mp4" 

def get_or_create_client(cursor, company_name, email, passcode_hash):
    """
    Checks if a client exists using your exact verified database columns.
    """
    # 1. Matches your column: company_name
    check_query = "SELECT client_id FROM public.clients WHERE company_name = %s;"
    cursor.execute(check_query, (company_name,))
    result = cursor.fetchone()
    
    if result:
        print(f"-> Found existing client: '{company_name}' (ID: {result[0]})")
        return result[0]
    else:
        print(f"-> Client '{company_name}' not found. Creating a new profile...")
        # 2. FIXED: Matches your exact columns: company_name, email, passcode_hash
        insert_client_query = """
        INSERT INTO public.clients (company_name, email, passcode_hash) 
        VALUES (%s, %s, %s) 
        RETURNING client_id;
        """
        cursor.execute(insert_client_query, (company_name, email, passcode_hash))
        new_client_id = cursor.fetchone()[0]
        return new_client_id


def create_new_mission(cursor, client_id):
    """
    Inserts a new mission row using your verified columns: client_id, mission_date, video_link.
    """
    # FIXED: Replaced mission_name and start_date with your actual columns: mission_date and video_link
    insert_mission_query = """
    INSERT INTO public.missions (client_id, mission_date, video_link) 
    VALUES (%s, %s, %s) 
    RETURNING mission_id;
    """
    cursor.execute(insert_mission_query, (client_id, datetime.now().date(), VIDEO_FILENAME))
    mission_id = cursor.fetchone()[0]
    return mission_id


def run_mission_stream():
    print("--- ROV Mission Control Initialization ---")
    
    # Collect data from operator
    company_name = input("Enter Client Name: ").strip()
    email = input("Enter Client Email: ").strip()
    passcode_hash = input("Enter Client Passcode: ").strip()
    
    if not company_name or not email or not passcode_hash:
        print("\nError: All fields (Name, Email, Passcode) are required.")
        sys.exit(1)

    # Open the video file
    cap = cv2.VideoCapture(VIDEO_FILENAME)
    if not cap.isOpened():
        print(f"Error: Could not open video file '{VIDEO_FILENAME}'.")
        sys.exit(1)

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if video_fps == 0:
        video_fps = 30.0  # Fallback safety
        
    frame_interval_10hz = max(1, int(video_fps / 10))
    frame_interval_1hz = max(1, int(video_fps))
    frame_duration = 1.0 / video_fps

    # Initial Simulation Metrics
    current_lat = 35.824500
    current_lon = 10.123400
    current_depth = 50.0
    current_distance = 0.0

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # 1. Run look up / creation using verified schema
        client_id = get_or_create_client(cursor, company_name, email, passcode_hash)
        conn.commit()  

        # 2. Start the new mission
        print("Registering new mission record in database...")
        generated_mission_id = create_new_mission(cursor, client_id)
        conn.commit()  
        
        print(f"Success! Created Mission ID: {generated_mission_id}")
        print("Starting frame-locked telemetry logger...\nPress Ctrl+C to abort.")

        while cap.isOpened():

            success, frame = cap.read()
            
            if not success:
                print("\nVideo processing complete.")
                break

            current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))

            # --- 10Hz TELEMETRY LOGGING GATING ---
            if current_frame % frame_interval_10hz == 0:
                current_depth += random.uniform(-0.5, 0.5)
                current_depth = max(10.0, min(150.0, current_depth))
                current_distance += random.uniform(0.05, 0.11)

                # --- 1Hz LOCATION UPDATE GATING ---
                if current_frame % frame_interval_1hz == 0:
                    current_lon += random.uniform(-0.0001, 0.0001)
                    current_lat += random.uniform(-0.0001, 0.0001)

                seconds_passed = current_frame / video_fps
                video_timestamp = timedelta(seconds=seconds_passed)
                current_wall_time = datetime.now()

                insert_telemetry_query = """
                INSERT INTO public.rov_telemetry (
                    "time", 
                    mission_id, 
                    video_timestamp, 
                    distance_meters, 
                    depth_meters, 
                    geom,
                    frame_number
                ) VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s);
                """

                record_data = (
                    current_wall_time,
                    generated_mission_id,
                    video_timestamp,
                    round(current_distance, 2),
                    round(current_depth, 2),
                    current_lon,
                    current_lat,
                    current_frame
                )

                cursor.execute(insert_telemetry_query, record_data)
                conn.commit()

                print(f"[Mission #{generated_mission_id} | Frame #{current_frame:05d}] Saved -> Depth: {current_depth:.2f}m | Distance: {current_distance:.2f}m", end="\r")

            time.sleep(frame_duration)

    except KeyboardInterrupt:
        print("\n\nMission aborted by operator.")
    except Exception as e:
        print(f"\nDatabase Error: {e}")
        if 'conn' in locals():
            conn.rollback()
    finally:
        cap.release()
        if 'cursor' in locals() and not cursor.closed:
            cursor.close()
        if 'conn' in locals() and not conn.closed:
            conn.close()
        print("Connections closed cleanly.")

if __name__ == "__main__":
    run_mission_stream()