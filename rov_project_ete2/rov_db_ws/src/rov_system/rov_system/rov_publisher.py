"""


Purpose in Pipeline:
    Acts as the middle-layer data routing and rate-throttling node in the ROS 2 
    Jazzy architecture. It receives raw telemetry streams from the simulation environment 
    or sensor drivers, enforces 1 Hz frequency throttling on acoustic USBL positioning, 
    and dispatches clean, standardized ROS 2 topics for downstream database synchronization.

Key Functionality:
    - Multi-Topic Ingestion: Subscribes to raw sensor topics (/raw_usbl, /raw_depth, 
      /raw_distance, /raw_camera).
    - Explicit Rate Throttling: Uses clock nanosecond deltas (>= 1e9 ns) to throttle 
      high-frequency raw USBL acoustic data down to a standard 1 Hz sampling rate.
    - Topic Normalization & Dispatch: Relays cleaned messages onto output topics 
      (/usbl, /depth, /distance, /camera).
    - Event-Driven Forwarding: Implements non-blocking, event-driven callback forwarding 
      for high-rate telemetry (10 Hz) and camera frame indices (30 Hz).

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

from std_msgs.msg import Float64
from sensor_msgs.msg import NavSatFix
from geometry_msgs.msg import Point

class ROVPublisher(Node):
    def __init__(self):
        super().__init__('rov_publisher')
        
        # Subscribers (Listening to raw simulator data)
        self.create_subscription(NavSatFix, '/raw_usbl', self.usbl_callback, 10)
        self.create_subscription(Float64, '/raw_depth', self.depth_callback, 10)
        self.create_subscription(Float64, '/raw_distance', self.distance_callback, 10)
        self.create_subscription(Point, '/raw_camera', self.camera_callback, 10)
        
        # Clean outbound ROS 2 topic publishers
        self.clean_usbl_pub = self.create_publisher(NavSatFix, '/usbl', 10)
        self.clean_depth_pub = self.create_publisher(Float64, '/depth', 10)
        self.clean_dist_pub = self.create_publisher(Float64, '/distance', 10)
        self.clean_cam_pub = self.create_publisher(Point, '/camera', 10)
        
        # Timer tracking for 1Hz USBL throttling
        self.last_1hz_time = self.get_clock().now()
        
        self.get_logger().info('📡 Publisher Node online. Routing and throttling topics...')

    def usbl_callback(self, msg):
        now = self.get_clock().now()
        # Throttling USBL rate to 1Hz (once per 1,000,000,000 nanoseconds)
        if (now - self.last_1hz_time).nanoseconds >= 1e9:
            self.clean_usbl_pub.publish(msg)
            self.get_logger().info(f"⏱️  [1Hz] Dispatched Coordinates -> Lat: {msg.latitude:.6f}, Lon: {msg.longitude:.6f}")
            self.last_1hz_time = now

    def depth_callback(self, msg):
        self.clean_depth_pub.publish(msg)

    def distance_callback(self, msg):
        self.clean_dist_pub.publish(msg)

    def camera_callback(self, msg):
        self.clean_cam_pub.publish(msg)
        self.get_logger().info(f"⚡ [10Hz] Dispatched Frame #{int(msg.x)} | Video Time: {msg.y}s")


def main(args=None):
    rclpy.init(args=args)
    node = ROVPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()  