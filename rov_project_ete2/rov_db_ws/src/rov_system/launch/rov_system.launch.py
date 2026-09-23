import os
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    # Substitute 'your_package_name' with your actual ROS 2 package name!
    PACKAGE_NAME = 'rov_system'

    # 1. Simulator Node
    simulator_node = Node(
        package=PACKAGE_NAME,
        executable='rov_simulator',  # Executable name defined in setup.py
        name='amerarov_simulator',
        output='screen'
    )

    # 2. Publisher / Throttler Node
    publisher_node = Node(
        package=PACKAGE_NAME,
        executable='rov_publisher',  # Executable name defined in setup.py
        name='rov_publisher',
        output='screen'
    )

    # 3. Database Subscriber / Syncer Node
    syncer_node = Node(
        package=PACKAGE_NAME,
        executable='rov_subscriber_syncer',  # Executable name defined in setup.py
        name='rov_subscriber_syncer',
        output='screen',
        emulate_tty=True  # Enables terminal focus so python input() works
    )

    return LaunchDescription([
        simulator_node,
        publisher_node,
        syncer_node
    ])