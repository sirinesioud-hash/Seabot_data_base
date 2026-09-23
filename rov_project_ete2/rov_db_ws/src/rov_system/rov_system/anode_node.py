#!/usr/bin/env python3
"""
ROS 2 Anode Reading Simulator Node
Publishes CP potential readings according to pipeline zone proximity:
- Away from pipeline: -0.650 V to -0.700 V
- Near main core elements (Group 1): -0.700 V to -0.850 V
- Near right extension elements (Group 2): -0.850 V to -1.050 V
"""

import math
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Float32
from dave_interfaces.msg import Location

# Parent Pipeline Base Pose
PARENT_X = 10.0
PARENT_Y = 0.0
PARENT_Z = -93.9  # Depth ~ 93.9 m

# Group 1: First 7 Core / Main Elements (-0.700 V to -0.850 V zone)
GROUP_1_RELATIVE = [
    (-7.5, 0.0),   # pipe_left
    (7.5, 0.0),    # pipe_right
    (0.0, 0.0),    # inner_dark_core / curved_bottom_shell
    (-1.4, 0.0),   # torn_lip_left
    (1.4, 0.0),    # torn_lip_right
    (-1.6, 0.0),   # flange_left
    (1.6, 0.0),    # flange_right
]

# Group 2: Right Side Extension Network (-0.850 V to -1.050 V zone)
GROUP_2_RELATIVE = [
    (17.5, 0.0),
    (21.5, 0.0),
    (22.5, 1.0),
    (24.5, 3.2),
    (26.0, 8.0),
    (13.5, -0.4),
    (13.5, 0.4),
]

# Compute absolute world coordinates
GROUP_1_WORLD = [(PARENT_X + rx, PARENT_Y + ry) for rx, ry in GROUP_1_RELATIVE]
GROUP_2_WORLD = [(PARENT_X + rx, PARENT_Y + ry) for rx, ry in GROUP_2_RELATIVE]

# Proximity tolerances
Z_TOLERANCE = 3.0   # Meters depth allowance
XY_TOLERANCE = 2.5  # Horizontal distance allowance

# Assigned Target Values (Volts vs Ag/AgCl)
VAL_AWAY = -0.675      # Middle of -0.650 V to -0.700 V
VAL_GROUP_1 = -0.775   # Middle of -0.700 V to -0.850 V
VAL_GROUP_2 = -0.950   # Middle of -0.850 V to -1.050 V


class AnodeReadingPublisher(Node):

    def __init__(self):
        super().__init__("anode_reading_publisher")

        # Subscriber to ROV position
        self.sub_usbl = self.create_subscription(
            Location,
            "/USBL/transceiver_manufacturer_168/transponder_location_cartesian",
            self.usbl_callback,
            qos_profile_sensor_data,
        )

        # Publisher for anode topic
        self.pub_anode = self.create_publisher(
            Float32,
            "/anode_reading",
            10,
        )

        self.get_logger().info("Anode Reading Node started with zoned voltage thresholds.")

    def usbl_callback(self, msg: Location):
        usbl_x = msg.x
        usbl_y = msg.y
        usbl_z = msg.z

        # Check Z proximity (handles positive 93.9 and negative -93.9 coordinates)
        z_match = abs(abs(usbl_z) - abs(PARENT_Z)) <= Z_TOLERANCE

        voltage_reading = VAL_AWAY  # Default output when away from all targets

        if z_match:
            # Check Group 2 elements first (-0.850 V to -1.050 V range)
            near_group_2 = False
            for wx, wy in GROUP_2_WORLD:
                dist = math.sqrt((usbl_x - wx) ** 2 + (usbl_y - wy) ** 2)
                if dist <= XY_TOLERANCE:
                    near_group_2 = True
                    break

            if near_group_2:
                voltage_reading = VAL_GROUP_2
            else:
                # Check Group 1 elements (-0.700 V to -0.850 V range)
                near_group_1 = False
                for wx, wy in GROUP_1_WORLD:
                    dist = math.sqrt((usbl_x - wx) ** 2 + (usbl_y - wy) ** 2)
                    if dist <= XY_TOLERANCE:
                        near_group_1 = True
                        break

                if near_group_1:
                    voltage_reading = VAL_GROUP_1

        msg_out = Float32()
        msg_out.data = float(voltage_reading)
        self.pub_anode.publish(msg_out)


def main(args=None):
    rclpy.init(args=args)
    node = AnodeReadingPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()