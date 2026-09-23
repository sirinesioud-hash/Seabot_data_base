"""

Purpose in Pipeline:
    Serves as Node 3 in the ROS 2 Jazzy architecture—the spatial-temporal database 
    synchronization engine. It subscribes to throttled/cleaned sensor streams, 
    maintains an asynchronous state cache, applies a gatekeeper validation rule, 
    and writes frame-synchronized telemetry records into PostgreSQL/TimescaleDB with PostGIS geometry.

Key Functionality:
    - Interactive Mission Initialization: Prompts operator to verify/create client profiles 
      in `public.clients` and registers dive metadata in `public.missions`.
    - Asynchronous Memory Caching: Caches high-frequency and throttled sensor data 
      (lat, lon, depth, distance) in local state variables.
    - Gatekeeper Null-Safety Pattern: Suppresses database writes until all core sensor 
      streams have dispatched their initial valid payload (`latest_lat is not None`).
    - PostGIS Spatial Ingestion: Converts GPS/USBL longitudes and latitudes into PostGIS 
      geometries (`ST_SetSRID(ST_MakePoint(lon, lat), 4326)`).
    - TimescaleDB Integration: Formats wall-clock Unix epochs using `TO_TIMESTAMP()` and 
      converts frame time offsets into SQL interval objects (`INTERVAL`).

Dependencies:
    - rclpy (ROS 2 Python Client Library)
    - psycopg2 (PostgreSQL/TimescaleDB Driver)
    - std_msgs (Float64)
    - sensor_msgs (NavSatFix)
    - geometry_msgs (Point)
===============================================================================
"""
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
import psycopg2
import time

from std_msgs.msg import Float64
from sensor_msgs.msg import NavSatFix
from geometry_msgs.msg import Point

# Configuration parameters for your PostgreSQL / PostGIS database
DB_PARAMS = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",  # Put your actual database password here!
    "host": "localhost",
    "port": 5432
}

class ROVSubscriberSyncer(Node):
    def __init__(self):
        super().__init__('rov_subscriber_syncer')
        
        # 1. Connect to PostgreSQL
        try:
            self.conn = psycopg2.connect(**DB_PARAMS)
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()
            self.get_logger().info("💾 Connected successfully to PostgreSQL database!")
        except Exception as e:
            self.get_logger().error(f"❌ Database connection failed: {e}")
            raise e
            
        # 2. Interactive Client & Mission Setup
        self.mission_id = self.setup_client_and_mission()
        
        # 3. Subscriptions to throttled/processed telemetry topics
        self.create_subscription(NavSatFix, '/usbl', self.usbl_cb, 10)
        self.create_subscription(Float64, '/depth', self.depth_cb, 10)
        self.create_subscription(Float64, '/distance', self.distance_cb, 10)
        self.create_subscription(Point, '/camera', self.camera_cb, 10)
        
        # 4. Memory Cache (Initialized to None so we don't store dummy data)
        self.latest_lat = None
        self.latest_lon = None
        self.latest_depth = None
        self.latest_dist = None
        
        self.get_logger().info(f'📥 Syncer online for Mission #{self.mission_id}. Listening for telemetry...')

    def setup_client_and_mission(self):
        """Interactively handles client lookup, client creation, and mission initialization."""
        print("\n" + "=" * 50)
        print("          ROV MISSION INITIALIZATION SETUP          ")
        print("=" * 50)
        
        company_name = input("👉 Enter Company Name: ").strip()
        
        # 1. Check if the company already exists in DB
        self.cursor.execute("SELECT client_id FROM public.clients WHERE company_name = %s;", (company_name,))
        result = self.cursor.fetchone()
        
        if result:
            client_id = result[0]
            print(f"✅ Client company '{company_name}' found! (ID: {client_id})")
        else:
            # 2. Register a new client if missing
            print(f"⚠️  Client company '{company_name}' not found. Please provide additional details:")
            email = input("👉 Enter Email: ").strip()
            passcode = input("👉 Enter Passcode: ").strip()
            
            insert_client_sql = """
            INSERT INTO public.clients (company_name, email, passcode_hash)
            VALUES (%s, %s, %s) RETURNING client_id;
            """
            self.cursor.execute(insert_client_sql, (company_name, email, passcode))
            client_id = self.cursor.fetchone()[0]
            print(f"🎉 New client created successfully! (ID: {client_id})")
            
        # 3. Prompt for Video Link & Create Mission
        video_link = input("👉 Enter Video Link Filename (e.g., mission_video.mp4): ").strip()
        if not video_link:
            video_link = "default_mission_video.mp4"

        # ✅ FIXED: Uses mission_date and video_link (NO created_at)
        insert_mission_sql = """
        INSERT INTO public.missions (client_id, mission_date, video_link)
        VALUES (%s, CURRENT_DATE, %s) RETURNING mission_id;
        """
        self.cursor.execute(insert_mission_sql, (client_id, video_link))
        new_mission_id = self.cursor.fetchone()[0]
        
        print(f"🚀 Mission #{new_mission_id} created for Client '{company_name}' [Video: {video_link}].\n")
        print("=" * 50 + "\n")
        
        return new_mission_id

    # --- TOPIC CALLBACKS ---
    def usbl_cb(self, msg):
        self.latest_lat = msg.latitude
        self.latest_lon = msg.longitude

    def depth_cb(self, msg):
        self.latest_depth = msg.data

    def distance_cb(self, msg):
        self.latest_dist = msg.data

    def camera_cb(self, msg):
        frame_number = int(msg.x)
        video_time_secs = msg.y  # Float video timestamp in seconds
        
        # 🛡️ GATEKEEPER: Wait until first USBL and Depth messages arrive
        if self.latest_lat is None or self.latest_lon is None or self.latest_depth is None:
            self.get_logger().info("⌛ Waiting for initial USBL and Depth messages...")
            return

        try:
            # SQL Query matching public.rov_telemetry schema
            insert_query = """
            INSERT INTO public.rov_telemetry (
                "time", mission_id, video_timestamp, distance_meters, geom, depth_meters, frame_number
            ) VALUES (
                TO_TIMESTAMP(%s), %s, (%s || ' seconds')::INTERVAL, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s
            );
            """
            
            current_unix_time = time.time()
            
            self.cursor.execute(insert_query, (
                current_unix_time,   # %s #1 -> "time"
                self.mission_id,     # %s #2 -> mission_id
                video_time_secs,     # %s #3 -> video_timestamp
                self.latest_dist,    # %s #4 -> distance_meters
                self.latest_lon,     # %s #5 -> ST_MakePoint (X = Longitude)
                self.latest_lat,     # %s #6 -> ST_MakePoint (Y = Latitude)
                self.latest_depth,   # %s #7 -> depth_meters
                frame_number         # %s #8 -> frame_number
            ))
            self.get_logger().info(f"📥 Synced Frame #{frame_number} | Video: {video_time_secs}s | Depth: {self.latest_depth}m")
        except Exception as db_err:
            self.get_logger().warn(f"⚠️ Database insert failed: {db_err}")

    def destroy_node(self):
        """Clean closure of database connections on node exit."""
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    try:
        node = ROVSubscriberSyncer()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        rclpy.shutdown()

if __name__ == '__main__':
    main()