#!/usr/bin/env python3
"""
Node 1: Handles client setup and serves the mission_id over a ROS 2 service (/get_active_mission).
"""

import sys
import psycopg2
import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

DB_PARAMS = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",
    "host": "localhost",
    "port": 5432
}

class MissionSetupNode(Node):
    def __init__(self):
        super().__init__('mission_setup_node')

        self.mission_id = None

        # Create ROS 2 Service Server
        self.srv = self.create_service(
            Trigger,
            '/get_active_mission',
            self.get_mission_id_callback
        )

        try:
            self.conn = psycopg2.connect(**DB_PARAMS)
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()
            self.get_logger().info("💾 Setup Node connected to PostgreSQL!")
        except Exception as e:
            self.get_logger().error(f"❌ DB connection failed: {e}")
            raise e

        self.run_interactive_setup()

    def run_interactive_setup(self):
        print("\n" + "=" * 50)
        print("          ROV MISSION INITIALIZATION SETUP          ")
        print("=" * 50)

        try:
            company_name = input("👉 Enter Company Name: ").strip()
            if not company_name:
                company_name = "Default Client"

            self.cursor.execute(
                "SELECT client_id FROM public.clients WHERE company_name ILIKE %s;", 
                (company_name,)
            )
            result = self.cursor.fetchone()

            if result:
                client_id = result[0]
                print(f"✅ [Case 1] Client '{company_name}' found! (ID: {client_id})")
            else:
                print(f"⚠️  [Case 2] Client '{company_name}' not found. Registering new client:")
                email = input("👉 Enter Email: ").strip()
                passcode = input("👉 Enter Passcode: ").strip()

                insert_client_sql = """
                INSERT INTO public.clients (company_name, email, passcode_hash)
                VALUES (%s, %s, %s) RETURNING client_id;
                """
                self.cursor.execute(insert_client_sql, (company_name, email, passcode))
                client_id = self.cursor.fetchone()[0]
                print(f"🎉 New client created successfully! (ID: {client_id})")

            video_link = input("👉 Enter Video Link Filename (e.g., dive_video_01.mp4): ").strip()
            if not video_link:
                video_link = "dave2_mission_video.mp4"

            insert_mission_sql = """
            INSERT INTO public.missions (client_id, mission_date, video_link)
            VALUES (%s, CURRENT_DATE, %s) RETURNING mission_id;
            """
            self.cursor.execute(insert_mission_sql, (client_id, video_link))
            self.mission_id = self.cursor.fetchone()[0]

            print("\n" + "=" * 50)
            print(f"🚀 Mission #{self.mission_id} registered in DB!")
            print("📡 Service '/get_active_mission' is active and listening for Node 2...")
            print("=" * 50 + "\n")
            
            self.get_logger().info(f"Ready to serve active mission_id: #{self.mission_id}")

        except (KeyboardInterrupt, EOFError):
            print("\n\n⛔ Setup cancelled.")
            sys.exit(0)

    def get_mission_id_callback(self, request, response):
        """ Service callback that returns the registered mission_id to Node 2 """
        if self.mission_id is not None:
            response.success = True
            response.message = str(self.mission_id)
            self.get_logger().info(f"📤 Served Mission ID #{self.mission_id} to Node 2!")
        else:
            response.success = False
            response.message = "No active mission ID registered yet."
        return response

    def destroy_node(self):
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MissionSetupNode()
    try:
        # Keep node spinning so the service server stays active to answer Node 2
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()