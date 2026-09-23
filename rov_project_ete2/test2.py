#!/usr/bin/env python3
"""
ROV Control & Telemetry Dashboard
Unifies Node 1 (Mission Setup) and Node 2 (Telemetry Ingestion) into a Streamlit GUI.
Includes Anode/CP Potential Node calculations based on pipeline element proximity.
"""

import math
import random
import threading
import time
from dave_interfaces.msg import Location
from geometry_msgs.msg import PointStamped
import pandas as pd
import psycopg2
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan, NavSatFix
from std_msgs.msg import Float32
import streamlit as st

# Database Parameters
DB_PARAMS = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",
    "host": "localhost",
    "port": 5432,
}


# ==========================================
# ROS 2 BACKGROUND WORKER NODE
# ==========================================
class StreamlitROSNode(Node):

    def __init__(self):
        super().__init__("streamlit_rov_node")

        # Telemetry State Variables
        self.base_lat = None
        self.base_lon = None
        self.latest_lat = None
        self.latest_lon = None
        self.latest_depth = None
        self.latest_dist = None
        self.latest_cp_voltage = 0.900  # Default healthy value in Volts
        self.has_usbl_data = False

        self.recording_active = False
        self.active_mission_id = None
        self.start_time = time.time()
        self.frame_number = 0.0

        # --- Yellow Pipeline Coordinates Definition ---
        self.pipe_base = (10.0, 0.0, -93.9)

        self.pipe_relative_poses = [
            (-7.5, 0.0, 0.0),   # pipe_left
            (7.5, 0.0, 0.0),    # pipe_right
            (0.0, 0.0, 0.0),    # inner_dark_core
            (0.0, 0.0, -0.12),  # curved_bottom_shell
            (-1.4, 0.0, 0.05),  # torn_lip_left
            (1.4, 0.0, 0.05),   # torn_lip_right
            (-1.6, 0.0, 0.0),   # flange_left
            (1.6, 0.0, 0.0),    # flange_right
            (-1.6, -0.4, -0.6), # supp_L1
            (-1.6, 0.4, -0.6),  # supp_L2
            (1.6, -0.4, -0.6),  # supp_R1
            (1.6, 0.4, -0.6),   # supp_R2
            (17.5, 0.0, 0.0),   # ext_right_straight
            (21.5, 0.0, 0.0),   # right_elbow_joint
            (22.5, 1.0, 0.0),   # ext_right_curve1
            (24.5, 3.2, 0.0),   # ext_right_curve2
            (26.0, 8.0, 0.0),   # ext_right_long_run
            (13.5, -0.4, -0.6), # supp_R3
            (13.5, 0.4, -0.6),  # supp_R4
            (26.0, 8.0, -0.6),  # supp_R5
            (-17.5, 0.0, 0.0),  # ext_left_straight
            (-21.5, 0.0, 0.0),  # left_elbow_joint
            (-22.5, -1.0, 0.0), # ext_left_curve1
            (-24.5, -3.2, 0.0), # ext_left_curve2
            (-26.0, -8.0, 0.0), # ext_left_long_run
            (-13.5, -0.4, -0.6),# supp_L3
            (-13.5, 0.4, -0.6), # supp_L4
            (-26.0, -8.0, -0.6),# supp_L5
        ]

        self.pipeline_world_points = [
            (self.pipe_base[0] + dx, self.pipe_base[1] + dy, self.pipe_base[2] + dz)
            for dx, dy, dz in self.pipe_relative_poses
        ]

        # --- Publishers ---
        self.anode_pub = self.create_publisher(Float32, "/anode_reading", 10)

        # --- Subscriptions ---
        self.create_subscription(
            NavSatFix,
            "/mavros/global_position/global",
            self.base_gps_cb,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            Location,
            "/USBL/transceiver_manufacturer_168/transponder_location_cartesian",
            self.usbl_cb,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            LaserScan,
            "/model/bluerov2/multibeam_sonar/point_cloud",
            self.sonar_cb,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            PointStamped,
            "/model/bluerov2/sea_pressure_depth",
            self.depth_cb,
            qos_profile_sensor_data,
        )

        try:
            self.db_conn = psycopg2.connect(**DB_PARAMS)
            self.db_conn.autocommit = True
            self.db_cursor = self.db_conn.cursor()
        except Exception as e:
            self.get_logger().error(f"PostgreSQL connection error: {e}")

        self.create_timer(0.1, self.db_insert_loop)

    def calculate_cp_potential(self, rov_x, rov_y, rov_z):
        min_dist = float("inf")
        for px, py, pz in self.pipeline_world_points:
            dist = math.sqrt((rov_x - px) ** 2 + (rov_y - py) ** 2 + (rov_z - pz) ** 2)
            if dist < min_dist:
                min_dist = dist

        if min_dist <= 3.5:
            voltage = round(random.uniform(0.500, 0.650), 3)
        else:
            voltage = round(random.uniform(0.800, 1.050), 3)

        return voltage

    def base_gps_cb(self, msg: NavSatFix):
        if msg.latitude == 0.0 and msg.longitude == 0.0:
            return

        self.base_lat = msg.latitude
        self.base_lon = msg.longitude

        if not self.has_usbl_data:
            self.latest_lat = self.base_lat
            self.latest_lon = self.base_lon

    def usbl_cb(self, msg: Location):
        if (
            self.base_lat is None
            or self.base_lon is None
            or (self.base_lat == 0.0 and self.base_lon == 0.0)
        ):
            return

        self.has_usbl_data = True
        x_east = msg.x
        y_north = msg.y
        z_depth = msg.z if hasattr(msg, "z") else (self.latest_depth if self.latest_depth else -93.9)

        self.latest_lat = self.base_lat + (y_north / 111111.0)
        self.latest_lon = self.base_lon + (
            x_east / (111111.0 * math.cos(math.radians(self.base_lat)))
        )

        self.latest_cp_voltage = self.calculate_cp_potential(x_east, y_north, z_depth)

        cp_msg = Float32()
        cp_msg.data = float(self.latest_cp_voltage)
        self.anode_pub.publish(cp_msg)

    def sonar_cb(self, msg: LaserScan):
        range_min = msg.range_min if msg.range_min > 0 else 0.0
        range_max = msg.range_max if msg.range_max > 0 else float("inf")

        valid_ranges = [
            r
            for r in msg.ranges
            if not math.isinf(r)
            and not math.isnan(r)
            and range_min <= r <= range_max
        ]
        if valid_ranges:
            self.latest_dist = round(sum(valid_ranges) / len(valid_ranges), 2)
        else:
            self.latest_dist = None

    def depth_cb(self, msg: PointStamped):
        self.latest_depth = round(msg.point.z, 2)

    def start_recording(self, mission_id):
        self.active_mission_id = mission_id
        self.recording_active = True
        self.start_time = time.time()
        self.frame_number = 0.0

    def stop_recording(self):
        self.recording_active = False

    def db_insert_loop(self):
        if not self.recording_active or self.active_mission_id is None:
            return

        if self.latest_lat is None or self.latest_depth is None:
            return

        current_time = time.time()
        elapsed_seconds = round(current_time - self.start_time, 2)
        self.frame_number += 3.0

        sonar_val = self.latest_dist if self.latest_dist is not None else 0.0
        cp_val = self.latest_cp_voltage if self.latest_cp_voltage is not None else 0.900

        try:
            insert_query = """
            INSERT INTO public.rov_telemetry (
                "time", mission_id, video_timestamp, distance_meters, geom, depth_meters, frame_number, cp_potential_volts
            ) VALUES (
                TO_TIMESTAMP(%s), %s, (%s || ' seconds')::INTERVAL, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s
            );
            """
            self.db_cursor.execute(
                insert_query,
                (
                    current_time,
                    self.active_mission_id,
                    elapsed_seconds,
                    sonar_val,
                    self.latest_lon,
                    self.latest_lat,
                    self.latest_depth,
                    int(self.frame_number),
                    cp_val,
                ),
            )
        except Exception as e:
            self.get_logger().error(f"DB Ingestion error: {e}")


# ==========================================
# STREAMLIT APP INITIALIZATION
# ==========================================
st.set_page_config(
    page_title="ROV Control Dashboard", page_icon="⚓", layout="wide"
)

st.markdown("""
    <style>
    .stApp { 
        background-color: #0B0E14 !important; 
        color: #F8FAFC !important; 
    }
    .main .block-container {
        max-width: 1600px !important;
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        margin: 0 auto !important;
    }
    html, body, p, div, label, span {
        font-size: 1.5rem !important;
        color: #CBD5E1 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    h1 { 
        font-size: 3.5rem !important; 
        font-weight: 800 !important; 
        color: #FFFFFF !important;
        margin-bottom: 0.5rem !important;
    }
    h2 { 
        font-size: 2.4rem !important; 
        font-weight: 700 !important; 
        color: #FFFFFF !important;
        border-bottom: 1px solid #1E293B !important;
        padding-bottom: 10px !important;
        margin-top: 1.5rem !important;
    }
    h3 { 
        font-size: 1.9rem !important; 
        font-weight: 600 !important; 
        color: #94A3B8 !important;
    }
    .stTextInput label, .stNumberInput label, .stSelectbox label {
        font-size: 1.6rem !important;
        font-weight: 600 !important;
        color: #94A3B8 !important;
    }
    .stTextInput input, .stNumberInput input {
        font-size: 1.5rem !important;
        padding: 14px !important;
        height: 60px !important;
        background-color: #182030 !important;
        color: #FFFFFF !important;
        border: 1px solid #28354D !important;
        border-radius: 6px !important;
    }
    .stButton button {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        padding: 0.8rem 1.8rem !important;
        border-radius: 6px !important;
        min-height: 60px !important;
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        border: none !important;
    }
    .stButton button:hover {
        background-color: #1D4ED8 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 3.2rem !important;
        font-weight: 800 !important;
        color: #38BDF8 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
        color: #94A3B8 !important;
    }
    [data-testid="stMetric"] {
        background-color: #121824 !important;
        border: 1px solid #1E293B !important;
        border-radius: 8px !important;
        padding: 20px !important;
    }
    button[data-baseweb="tab"] {
        font-size: 1.6rem !important;
        font-weight: 600 !important;
        padding: 14px 28px !important;
        background-color: transparent !important;
        color: #94A3B8 !important;
        border: none !important;
        border-bottom: 2px solid transparent !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: #121824 !important;
        color: #FFFFFF !important;
        border-bottom: 2px solid #2563EB !important;
        border-radius: 6px 6px 0 0 !important;
    }
    .stDataFrame, div[data-testid="stTable"] {
        font-size: 1.3rem !important;
        background-color: #121824 !important;
        border: 1px solid #1E293B !important;
        border-radius: 6px !important;
    }
    .stAlert {
        font-size: 1.4rem !important;
        background-color: #121824 !important;
        border: 1px solid #1E293B !important;
        color: #F8FAFC !important;
    }
    </style>
""", unsafe_allow_html=True)


@st.cache_resource
def init_ros2():
    rclpy.init()
    node = StreamlitROSNode()
    thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    thread.start()
    return node


ros_node = init_ros2()


def get_db_connection():
    return psycopg2.connect(**DB_PARAMS)


if "client_info" not in st.session_state:
    st.session_state.client_info = None
if "active_mission_id" not in st.session_state:
    st.session_state.active_mission_id = None

# ==========================================
# INTERFACE LAYOUT
# ==========================================
st.title("⚓ ROV Control")
st.caption("ROV Telemetry Control & Operational Dashboard")

tab1, tab2 = st.tabs(
    ["🚀 Mission Setup & Live Control", "📊 Database Explorer"]
)

# ------------------------------------------
# TAB 1: MISSION SETUP & RECORDING CONTROL
# ------------------------------------------
with tab1:
    col_setup, col_control = st.columns([1, 1])

    with col_setup:
        st.subheader("1. Client & Mission Setup")

        with st.form("client_check_form"):
            company_name = st.text_input(
                "Company Name", placeholder="e.g. DeepSea Corp"
            )
            submitted = st.form_submit_button("Verify Client")

            if submitted and company_name:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    "SELECT client_id, email FROM public.clients WHERE"
                    " company_name ILIKE %s;",
                    (company_name.strip(),),
                )
                res = cur.fetchone()

                if res:
                    st.session_state.client_info = {
                        "id": res[0],
                        "name": company_name,
                        "email": res[1],
                        "is_new": False,
                    }
                    st.success(f"Client found! (Client ID: {res[0]})")
                else:
                    st.session_state.client_info = {
                        "name": company_name,
                        "is_new": True,
                    }
                    st.warning(
                        f"Client '{company_name}' not found. Register new"
                        " client below."
                    )
                cur.close()
                conn.close()

        if st.session_state.client_info:
            c_info = st.session_state.client_info

            with st.form("mission_init_form"):
                if c_info["is_new"]:
                    st.write("**New Client Registration**")
                    email = st.text_input("Email")
                    passcode = st.text_input("Passcode", type="password")

                video_link = st.text_input(
                    "Video Link Filename", value="dive_video_01.mp4"
                )
                start_mission_btn = st.form_submit_button("Initialize Mission")

                if start_mission_btn:
                    conn = get_db_connection()
                    conn.autocommit = True
                    cur = conn.cursor()

                    if c_info["is_new"]:
                        cur.execute(
                            "INSERT INTO public.clients (company_name, email,"
                            " passcode_hash) VALUES (%s, %s, %s) RETURNING"
                            " client_id;",
                            (c_info["name"], email, passcode),
                        )
                        client_id = cur.fetchone()[0]
                    else:
                        client_id = c_info["id"]

                    cur.execute(
                        "INSERT INTO public.missions (client_id, mission_date,"
                        " video_link) VALUES (%s, CURRENT_DATE, %s) RETURNING"
                        " mission_id;",
                        (client_id, video_link),
                    )
                    m_id = cur.fetchone()[0]
                    st.session_state.active_mission_id = m_id
                    st.success(f"Mission #{m_id} Initialized and Ready!")
                    cur.close()
                    conn.close()

    with col_control:
        st.subheader("2. Telemetry Ingestion Control")

        if st.session_state.active_mission_id:
            m_id = st.session_state.active_mission_id
            st.info(f"**Active Mission Target:** #{m_id}")

            btn_col1, btn_col2 = st.columns(2)

            with btn_col1:
                if st.button("🔴 START RECORDING", use_container_width=True):
                    ros_node.start_recording(m_id)
                    st.toast(
                        f"Recording started for Mission #{m_id}", icon="🎥"
                    )

            with btn_col2:
                if st.button("⏹️ STOP RECORDING", use_container_width=True):
                    ros_node.stop_recording()
                    st.toast("Recording Stopped", icon="⏹️")

            st.write("---")
            st.subheader("Live Sensor Stream")

            m1, m2 = st.columns(2)
            m3, m4, m5 = st.columns(3)

            lat = (
                f"{ros_node.latest_lat:.7f}"
                if ros_node.latest_lat
                else "N/A"
            )
            lon = (
                f"{ros_node.latest_lon:.7f}"
                if ros_node.latest_lon
                else "N/A"
            )
            depth = (
                f"{ros_node.latest_depth} m"
                if ros_node.latest_depth is not None
                else "N/A"
            )
            sonar = (
                f"{ros_node.latest_dist} m"
                if ros_node.latest_dist is not None
                else "N/A"
            )
            cp_val = (
                f"{ros_node.latest_cp_voltage:.3f} V"
                if ros_node.latest_cp_voltage is not None
                else "N/A"
            )

            m1.metric("Current Latitude", lat)
            m2.metric("Current Longitude", lon)
            m3.metric("ROV Depth", depth)
            m4.metric("Sonar Distance", sonar)
            m5.metric("Anode CP Reading", cp_val)

            if ros_node.recording_active:
                st.markdown(
                    "<span style='color: #22C55E;'>● RECORDING IN"
                    " PROGRESS</span>",
                    unsafe_allow_html=True,
                )
                time.sleep(0.5)
                st.rerun()
            else:
                st.markdown(
                    "<span style='color: #EF4444;'>● RECORDING STOPPED</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.warning("Please setup or select a mission first.")

# ------------------------------------------
# TAB 2: DATA & CLIENT EXPLORER
# ------------------------------------------
with tab2:
    conn = get_db_connection()

    # 1. Registered Clients Table
    st.subheader("Registered Clients")
    df_clients = pd.read_sql(
        "SELECT client_id, company_name, email FROM public.clients ORDER BY"
        " client_id DESC;",
        conn,
    )
    st.dataframe(df_clients, use_container_width=True)

    # 2. Registered Missions Table
    st.subheader("Registered Missions")
    df_missions = pd.read_sql(
        "SELECT mission_id, client_id, mission_date, video_link FROM"
        " public.missions ORDER BY mission_id DESC;",
        conn,
    )
    st.dataframe(df_missions, use_container_width=True)

    # 3. Telemetry Ingestion Data & Filter Controls
    st.subheader("Recent Mission Telemetry Data")

    col_m, col_l = st.columns([1, 1])
    with col_m:
        mission_filter = st.number_input("Filter by Mission ID", value=1, step=1)
    with col_l:
        max_rows = st.select_slider(
            "Telemetry Records Limit",
            options=[100, 500, 1000, 5000, "ALL"],
            value=500,
        )

    # --- UPDATED SQL QUERY INCLUDING cp_potential_volts ---
    if max_rows == "ALL":
        telemetry_query = """
        SELECT 
            "time",
            mission_id,
            video_timestamp::text AS video_timestamp,
            ST_X(geom) as longitude,
            ST_Y(geom) as latitude,
            depth_meters,
            distance_meters,
            frame_number,
            cp_potential_volts
        FROM public.rov_telemetry
        WHERE mission_id = %s
        ORDER BY "time" DESC;
        """
        params = (mission_filter,)
    else:
        telemetry_query = """
        SELECT 
            "time",
            mission_id,
            video_timestamp::text AS video_timestamp,
            ST_X(geom) as longitude,
            ST_Y(geom) as latitude,
            depth_meters,
            distance_meters,
            frame_number,
            cp_potential_volts
        FROM public.rov_telemetry
        WHERE mission_id = %s
        ORDER BY "time" DESC
        LIMIT %s;
        """
        params = (mission_filter, max_rows)

    df_telemetry = pd.read_sql(telemetry_query, conn, params=params)

    if not df_telemetry.empty:
        st.map(df_telemetry, latitude="latitude", longitude="longitude")
        st.dataframe(df_telemetry, use_container_width=True)
    else:
        st.info("No telemetry records found for this Mission ID.")

    conn.close()