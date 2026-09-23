#!/usr/bin/env python3
"""
Node 2: Acts as a ROS 2 Service Client (/get_active_mission).
Blocks on startup until Node 1 returns the auto-generated mission_id, then starts inserting telemetry.
"""

import math
import time
import psycopg2
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from std_srvs.srv import Trigger
from sensor_msgs.msg import NavSatFix, LaserScan
from geometry_msgs.msg import PointStamped
from dave_interfaces.msg import Location

DB_PARAMS = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",
    "host": "localhost",
    "port": 5432
}

class RawDBIngestionNode(Node):
    def __init__(self):
        super().__init__('raw_db_ingestion_node')

        try:
            self.conn = psycopg2.connect(**DB_PARAMS)
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()
            self.get_logger().info("💾 Connected to PostgreSQL database!")
        except Exception as e:
            self.get_logger().error(f"❌ DB connection failed: {e}")
            raise e

        # Live State Caching
        self.mission_id = None
        self.base_lat = None
        self.base_lon = None
        self.latest_lat = None
        self.latest_lon = None
        self.latest_depth = None
        self.latest_dist = 0.0
        self.has_usbl_data = False

        self.start_time = time.time()
        self.frame_number = 0.0

        # Subscriptions
        self.create_subscription(NavSatFix, '/mavros/global_position/global', self.base_gps_cb, qos_profile_sensor_data)
        self.create_subscription(Location, '/USBL/transceiver_manufacturer_168/transponder_location_cartesian', self.usbl_cb, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/model/bluerov2/multibeam_sonar/point_cloud', self.sonar_cb, qos_profile_sensor_data)
        self.create_subscription(PointStamped, '/model/bluerov2/sea_pressure_depth', self.depth_cb, qos_profile_sensor_data)

        # Service Client: Connect to Node 1's Server
        self.client = self.create_client(Trigger, '/get_active_mission')
        self.request_mission_id()

        # Insertion Timer Loop (10 Hz)
        self.create_timer(0.1, self.db_insert_loop)

    def request_mission_id(self):
        """ Blocking call on startup to fetch active mission_id from Node 1 """
        self.get_logger().info("⌛ Waiting for Node 1 '/get_active_mission' service to become available...")
        while not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info("⌛ Service not available yet, waiting...")

        req = Trigger.Request()
        future = self.client.call_async(req)
        
        # Block spin until Node 1 responds
        rclpy.spin_until_future_complete(self, future)
        response = future.result()

        if response and response.success:
            self.mission_id = int(response.message)
            self.get_logger().info(f"🎯 Successfully linked to Node 1! Active Mission ID: #{self.mission_id}")
        else:
            self.get_logger().error("❌ Failed to retrieve mission_id from Node 1")

    def base_gps_cb(self, msg: NavSatFix):
        self.base_lat = msg.latitude
        self.base_lon = msg.longitude
        if not self.has_usbl_data:
            self.latest_lat = self.base_lat
            self.latest_lon = self.base_lon

    def usbl_cb(self, msg: Location):
        self.has_usbl_data = True
        if self.base_lat is None or self.base_lon is None:
            return
        x_east = msg.x
        y_north = msg.y
        self.latest_lat = self.base_lat + (y_north / 111111.0)
        self.latest_lon = self.base_lon + (x_east / (111111.0 * math.cos(math.radians(self.base_lat))))
        self.get_logger().info(f"📡 USBL Update -> Lat: {self.latest_lat:.6f}, Lon: {self.latest_lon:.6f} (USBL is getting called)")

    def sonar_cb(self, msg: LaserScan):
        valid_ranges = [r for r in msg.ranges if not math.isinf(r) and not math.isnan(r) and r > 0.0]
        self.latest_dist = round(sum(valid_ranges) / len(valid_ranges), 2) if valid_ranges else 0.0

    def depth_cb(self, msg: PointStamped):
        self.latest_depth = round(msg.point.z, 2)

    def db_insert_loop(self):
        if self.mission_id is None:
            return

        missing_topics = []
        if self.latest_lat is None or self.latest_lon is None:
            missing_topics.append("GPS Position")
        if self.latest_depth is None:
            missing_topics.append("Depth Sensor")

        if missing_topics:
            self.get_logger().info(f"⌛ Waiting for topic stream(s): {', '.join(missing_topics)}")
            return

        current_time = time.time()
        elapsed_video_seconds = round(current_time - self.start_time, 2)
        self.frame_number += 3.0

        try:
            insert_query = """
            INSERT INTO public.rov_telemetry (
                "time", mission_id, video_timestamp, distance_meters, geom, depth_meters, frame_number
            ) VALUES (
                TO_TIMESTAMP(%s), %s, (%s || ' seconds')::INTERVAL, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s
            );
            """

            self.cursor.execute(insert_query, (
                current_time,
                self.mission_id,
                elapsed_video_seconds,
                self.latest_dist,
                self.latest_lon,
                self.latest_lat,
                self.latest_depth,
                int(self.frame_number)
            ))

            self.get_logger().info(
                f"📥 [DB Insert] Mission #{self.mission_id} | Frame #{int(self.frame_number)} | "
                f"Lat: {self.latest_lat:.6f}, Lon: {self.latest_lon:.6f} | Depth: {self.latest_depth}m | Sonar: {self.latest_dist}m"
            )

        except Exception as e:
            self.get_logger().warn(f"⚠️ DB Insert Error: {e}")

    def destroy_node(self):
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RawDBIngestionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()