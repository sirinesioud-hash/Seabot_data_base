
"""


Purpose in Pipeline:
    Simulates subsea ROV operational kinematics, multi-rate sensor telemetry streams, 
    and camera frame indexing in a ROS 2 Jazzy environment. It generates mock acoustic 
    positioning (USBL), depth meters, seafloor altitude distance, and video frame count 
    payloads for downstream routing and database synchronization.

Key Functionality:
    - Timer-Driven Execution Loop: Instantiates a 10 Hz periodic timer callback 
      (`self.create_timer(0.1, ...)`) to drive synthetic sensor generation.
    - Kinematic & Environmental Drift Simulation: Models ROV positional drift around 
      a geographic origin (Tunis coordinates) and dynamically updates depth and altitude.
    - Synthetic Frame-Rate Math: Increments frame counters by 3.0 frames per 0.1s tick 
      to simulate a synchronous 30 FPS video stream ($3.0 \text{ frames} / 0.1\text{s} = 30 \text{ FPS}$).
    - Raw Topic Broadcasting: Publishes un-throttled raw telemetry payloads onto dedicated 
      ROS 2 topics (`/raw_usbl`, `/raw_depth`, `/raw_distance`, `/raw_camera`).

Dependencies:
    - rclpy (ROS 2 Python Client Library)
    - std_msgs (Float64)
    - sensor_msgs (NavSatFix)
    - geometry_msgs (Point)
===============================================================================
"""
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
import random
import time

# Import standard ROS 2 messages
from std_msgs.msg import Float64
from sensor_msgs.msg import NavSatFix
from geometry_msgs.msg import Point  # x=frame_number, y=video_timestamp

class ROVSimulator(Node):
    def __init__(self):
        super().__init__('amerarov_simulator')
        
        # Publishers for raw simulation data
        self.usbl_pub = self.create_publisher(NavSatFix, '/raw_usbl', 10)
        self.depth_pub = self.create_publisher(Float64, '/raw_depth', 10)
        self.dist_pub = self.create_publisher(Float64, '/raw_distance', 10)
        self.cam_pub = self.create_publisher(Point, '/raw_camera', 10)
        
        # Timer running at 10Hz (0.1 seconds interval)
        self.timer = self.create_timer(0.1, self.generate_telemetry)
        
        # Initial simulated coordinates (Tunis region)
        self.lat = 36.8065
        self.lon = 10.1815
        self.frame_number = 0.0
        self.start_time = time.time()
        
        self.get_logger().info('🤖 Simulator Node started. Generating mock ROV telemetry stream...')

    def generate_telemetry(self):
        current_time = time.time()
        elapsed_video_seconds = round(current_time - self.start_time, 2)
        
        # Simulate physical ROV movement and ocean floor changes
        self.lat += random.uniform(-0.00001, 0.00001)
        self.lon += random.uniform(-0.00001, 0.00001)
        depth = round(random.uniform(10.0, 50.0), 2)
        distance_to_floor = round(100.0 - depth + random.uniform(-0.5, 0.5), 2)
        self.frame_number += 3.0  # Simulating frame progression at ~30fps over 10Hz ticks
        
        # 1. Publish Camera (10Hz)
        cam_msg = Point()
        cam_msg.x = self.frame_number
        cam_msg.y = elapsed_video_seconds
        cam_msg.z = 0.0
        self.cam_pub.publish(cam_msg)
        
        # 2. Publish Depth (10Hz)
        depth_msg = Float64()
        depth_msg.data = depth
        self.depth_pub.publish(depth_msg)
        
        # 3. Publish Altitude Distance to seafloor (10Hz)
        dist_msg = Float64()
        dist_msg.data = distance_to_floor
        self.dist_pub.publish(dist_msg)
        
        # 4. Publish Raw USBL / GPS (10Hz generation)
        gps_msg = NavSatFix()
        gps_msg.header.stamp = self.get_clock().now().to_msg()
        gps_msg.latitude = self.lat
        gps_msg.longitude = self.lon
        self.usbl_pub.publish(gps_msg)


def main(args=None):
    rclpy.init(args=args)
    node = ROVSimulator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()