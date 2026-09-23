#!/usr/bin/env python3
"""
===============================================================================
MODULE: Subsea ROV Operations & Engineering Analysis Portal
FILE: engineers_interface.py (Engineering Control & Reporting Interface)
===============================================================================

Purpose in Pipeline:
    Serves as the internal operational control, engineering analytics, and reporting
    layer of the spatial-temporal ROV survey pipeline. It enables subsea engineers
    and ROV operators to ingest raw survey logs, evaluate Cathodic Protection (CP)
    voltage health against IMCA compliance standards, aggregate high-frequency telemetry
    frames into condensed summary blocks, and dynamically render formal PDF inspection reports.

Key Functionality:
    - Telemetry Ingestion & Spatial Preprocessing: Ingests raw frame logs, computes
      inter-frame spatial deltas via Haversine distance calculations, and tracks total
      cumulative trajectory distance across the survey path.
    - Cathodic Protection (CP) Health Assessment: Evaluates CP potential readings against
      established subsea integrity thresholds to classify pipeline state.
    - Data Block Aggregation: Group-analyzes consecutive telemetry frames displaying
      identical CP voltage potentials into discrete, readable frame ranges.
    - Dynamic IMCA PDF Report Generation: Programmatically compiles multi-page,
      publication-grade IMCA uniform handover PDF reports using ReportLab.
    - Live Recording & Database Sync: Controls live recording state (START/STOP) and
      persists multi-rate sensor telemetry into PostgreSQL/TimescaleDB with PostGIS geometries.

Dependencies:
    - streamlit
    - rclpy, sensor_msgs, geometry_msgs, std_msgs, dave_interfaces
    - psycopg2, pandas, numpy
    - reportlab
===============================================================================
"""

import io
import math
import os
import threading
import time
import pandas as pd
import psycopg2
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan, NavSatFix
from geometry_msgs.msg import PointStamped
from std_msgs.msg import Float32
from dave_interfaces.msg import Location
import streamlit as st

# ReportLab Imports for PDF Generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================
DB_PARAMS = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",  # Update with your PostgreSQL password if different
    "host": "localhost",
    "port": 5432,
}


def get_db_connection():
    return psycopg2.connect(**DB_PARAMS)


# ==========================================
# 2. MATH & REPORTING HELPERS
# ==========================================
def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates distance between two GPS points in meters using the Haversine formula."""
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    R = 6371000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def evaluate_cp_health(val):
    """Evaluates Cathodic Protection potential voltage per ISO 15589-2 / NACE SP0169."""
    if val is None:
        return "NO DATA", "Sensor reading unavailable."
    if -1.15 <= val <= -0.85:
        return "HEALTHY", "Pipeline stable. Optimal protection."
    elif val > -0.85:
        return "CRITICAL ANOMALY", "Under-protected. Active corrosion risk."
    else:
        return "WARNING", "Over-protected. Risk of HISC / Coating delamination."


def generate_imca_pdf_report(
    mission_id,
    client_name,
    video_link,
    df_raw,
    logo_path="mare_custos_logo.jpeg",
):
    """Generates an IMCA R 004 / IOGP SSDM Compliant PDF Report buffer for engineering sign-off."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    styles = getSampleStyleSheet()

    # Document Styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=14,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        fontName="Helvetica-Bold",
        alignment=0,
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#475569"),
        fontName="Helvetica-Bold",
    )
    sec_heading = ParagraphStyle(
        "SecHeading",
        parent=styles["Heading2"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#1E3A8A"),
        fontName="Helvetica-Bold",
        spaceBefore=8,
        spaceAfter=4,
    )
    cell_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#1E293B"),
        fontName="Helvetica",
    )
    cell_style_bold = ParagraphStyle(
        "CellTextBold",
        parent=cell_style,
        fontName="Helvetica-Bold",
    )
    cell_header = ParagraphStyle(
        "CellHeader",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    elements = []

    # Document Header
    header_text_nodes = [
        Paragraph(
            "IMCA R 004 / IOGP SSDM COMPLIANT SUBSEA TELEMETRY LOG",
            subtitle_style,
        ),
        Paragraph(
            "INTERNATIONAL ROV TELEMETRY & PIPELINE INSPECTION LOG",
            title_style,
        ),
        Paragraph(
            "<b>SYSTEM IDENTIFIER:</b> ROV-LOG-PRO-V4 &nbsp;|&nbsp;"
            " <b>STANDARDIZATION:</b> IMCA R 004 & ISO 15589-2 / NACE SP0169",
            subtitle_style,
        ),
    ]

    if os.path.exists(logo_path):
        logo_img = RLImage(logo_path, width=140, height=35)
        header_table = Table(
            [[logo_img, header_text_nodes]], colWidths=[150, 385]
        )
        header_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ])
        )
        elements.append(header_table)
    else:
        elements.extend(header_text_nodes)

    elements.append(Spacer(1, 10))

    # Section 1: Operational & Asset Metadata
    elements.append(
        Paragraph("1. Survey Operation & Asset Metadata", sec_heading)
    )
    meta_data = [
        [
            Paragraph("<b>Asset Name:</b>", cell_style),
            Paragraph('24" North Sea Gas Export Interconnector', cell_style),
            Paragraph("<b>Survey Vessel:</b>", cell_style),
            Paragraph("MV / Deepwater Explorer", cell_style),
        ],
        [
            Paragraph("<b>Operator:</b>", cell_style),
            Paragraph("Global Marine Energy Corp.", cell_style),
            Paragraph("<b>ROV System:</b>", cell_style),
            Paragraph("Triton-X XL Work Class ROV", cell_style),
        ],
        [
            Paragraph("<b>Client Name:</b>", cell_style),
            Paragraph(str(client_name), cell_style),
            Paragraph("<b>Database Origin:</b>", cell_style),
            Paragraph("PostgreSQL Telemetry Core", cell_style),
        ],
        [
            Paragraph("<b>Mission ID:</b>", cell_style),
            Paragraph(f"#{mission_id}", cell_style),
            Paragraph("<b>Geodetic Datum:</b>", cell_style),
            Paragraph("WGS 84 / UTM Zone 31N", cell_style),
        ],
        [
            Paragraph("<b>Video File Ref:</b>", cell_style),
            Paragraph(str(video_link), cell_style),
            Paragraph("<b>Inspection Date:</b>", cell_style),
            Paragraph(time.strftime("%Y-%m-%d"), cell_style),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[100, 165, 100, 170])
    t_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    elements.append(t_meta)
    elements.append(Spacer(1, 8))

    # Section 2: Evaluation Criteria Standards
    elements.append(
        Paragraph("2. Engineering Evaluation & Threshold Criteria", sec_heading)
    )
    thresh_data = [
        [
            Paragraph("CP Potential Window (Ag/AgCl)", cell_header),
            Paragraph("Pipeline Health Classification", cell_header),
            Paragraph("Engineering Action Directive", cell_header),
        ],
        [
            Paragraph("-0.85V to -1.15V", cell_style_bold),
            Paragraph("FULLY PROTECTED (Healthy)", cell_style),
            Paragraph(
                "System at steady state. Continue standard baseline inspection path.",
                cell_style,
            ),
        ],
        [
            Paragraph("> -0.85V (e.g., -0.74V)", cell_style_bold),
            Paragraph("UNDER-PROTECTED (Critical Risk)", cell_style),
            Paragraph(
                "Active galvanic corrosion. Log anomaly immediately for sacrificial anode retrofit.",
                cell_style,
            ),
        ],
        [
            Paragraph("< -1.15V (e.g., -1.24V)", cell_style_bold),
            Paragraph("OVER-PROTECTED (Warning)", cell_style),
            Paragraph(
                "Risk of Hydrogen Induced Stress Cracking (HISC) and epoxy coating degradation.",
                cell_style,
            ),
        ],
    ]
    t_thresh = Table(thresh_data, colWidths=[120, 150, 265])
    t_thresh.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F0FDF4")),
            ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#FEF2F2")),
            ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#FFFBEB")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    elements.append(t_thresh)
    elements.append(Spacer(1, 8))

    # Section 3: Telemetry Matrix (Grouped Continuous Frames)
    elements.append(
        Paragraph(
            "3. Integrated Multi-Sensor Telemetry Log Matrix (IMCA Uniform Data Handover)",
            sec_heading,
        )
    )
    log_headers = [
        Paragraph("Timestamp /<br/>Video Frame ID", cell_header),
        Paragraph("GIS Coordinates<br/>(WGS84 Lon/Lat)", cell_header),
        Paragraph("Sensor Depth /<br/>Sonar Tracking", cell_header),
        Paragraph("Traveled Delta (Δ) /<br/>Total Cumulative", cell_header),
        Paragraph("CP Reading<br/>(Potential)", cell_header),
        Paragraph("Pipeline Health &<br/>Seabed Assessment", cell_header),
    ]

    log_rows = [log_headers]
    df_sorted = df_raw.sort_values(by="time", ascending=True).reset_index(drop=True)

    # 1. Calculate per-row delta and cumulative distance
    cum_dist = 0.0
    prev_lat, prev_lon = None, None
    deltas = []
    cum_dists = []

    for idx, row in df_sorted.iterrows():
        cur_lat = row.get("latitude")
        cur_lon = row.get("longitude")

        if prev_lat is not None and prev_lon is not None:
            delta = haversine_distance(prev_lat, prev_lon, cur_lat, cur_lon)
        else:
            delta = 0.0

        cum_dist += delta
        deltas.append(delta)
        cum_dists.append(cum_dist)
        prev_lat, prev_lon = cur_lat, cur_lon

    df_sorted["delta"] = deltas
    df_sorted["cum_dist"] = cum_dists

    # 2. Group consecutive rows that share the same CP voltage reading
    if "cp_potential_volts" in df_sorted.columns:
        df_sorted["cp_key"] = df_sorted["cp_potential_volts"].round(3)
    else:
        df_sorted["cp_key"] = 0.0

    df_sorted["block_id"] = (df_sorted["cp_key"] != df_sorted["cp_key"].shift()).cumsum()

    # 3. Process grouped blocks of continuous data
    for _, group in df_sorted.groupby("block_id"):
        first_row = group.iloc[0]
        last_row = group.iloc[-1]

        f_start = (
            int(first_row["frame_number"])
            if pd.notnull(first_row.get("frame_number"))
            else "N/A"
        )
        f_end = (
            int(last_row["frame_number"])
            if pd.notnull(last_row.get("frame_number"))
            else "N/A"
        )

        t_start = (
            str(first_row["time"]).split(" ")[-1][:8]
            if pd.notnull(first_row.get("time"))
            else "N/A"
        )
        t_end = (
            str(last_row["time"]).split(" ")[-1][:8]
            if pd.notnull(last_row.get("time"))
            else "N/A"
        )

        if len(group) == 1 or f_start == f_end:
            frame_str = f"Frame: #{f_start}"
            t_str = t_start
        else:
            frame_str = f"Frames: #{f_start} to #{f_end}"
            t_str = f"{t_start} - {t_end}"

        cur_lat = first_row.get("latitude")
        cur_lon = first_row.get("longitude")
        lon_str = f"Lon: {cur_lon:.6f} E" if cur_lon is not None else "Lon: N/A"
        lat_str = f"Lat: {cur_lat:.6f} N" if cur_lat is not None else "Lat: N/A"

        depth_val = first_row.get("depth_meters")
        depth_str = f"Depth: {depth_val:.2f} m" if pd.notnull(depth_val) else "Depth: N/A"
        sonar_val = first_row.get("distance_meters")
        sonar_str = f"Sonar: {sonar_val:.2f} m" if pd.notnull(sonar_val) else "Sonar: Lock"

        block_delta = group["delta"].sum()
        block_cum_dist = last_row["cum_dist"]

        cp_v = first_row.get("cp_potential_volts")
        cp_str = f"{cp_v:.3f} V" if pd.notnull(cp_v) else "N/A"

        health_tag, health_desc = evaluate_cp_health(cp_v)

        log_rows.append([
            Paragraph(f"{t_str}<br/>{frame_str}", cell_style),
            Paragraph(f"{lon_str}<br/>{lat_str}", cell_style),
            Paragraph(f"{depth_str}<br/>{sonar_str}", cell_style),
            Paragraph(
                f"Δ: +{block_delta:.1f} m<br/>Total: {block_cum_dist:.1f} m",
                cell_style,
            ),
            Paragraph(cp_str, cell_style_bold),
            Paragraph(f"<b>{health_tag}</b><br/>{health_desc}", cell_style),
        ])

    t_log = Table(log_rows, colWidths=[80, 95, 85, 90, 55, 130], repeatRows=1)
    t_log.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    elements.append(t_log)
    elements.append(Spacer(1, 10))

    # Section 4: Internal Technical Sign-Off Block
    elements.append(Paragraph("4. Technical Sign-Off", sec_heading))
    sign_data = [
        [Paragraph("<b>Lead Offshore Survey Engineer Verification:</b>", cell_style)],
        [Paragraph("Authorized Signature: __________________________________________________", cell_style)],
        [Paragraph("Date: ________________________", cell_style)],
    ]
    t_sign = Table(sign_data, colWidths=[535])
    t_sign.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#94A3B8")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    elements.append(t_sign)

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ==========================================
# 3. ROS 2 BACKGROUND WORKER NODE
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
        self.latest_cp_potential = None
        self.has_usbl_data = False

        self.recording_active = False
        self.active_mission_id = None
        self.start_time = time.time()
        self.frame_number = 0.0

        # Subscriptions to multi-rate sensor topics
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
        self.create_subscription(
            Float32,
            "/anode_reading",
            self.cp_cb,
            qos_profile_sensor_data,
        )

        # Database connection for ingestion thread
        self.db_conn = None
        try:
            self.db_conn = psycopg2.connect(**DB_PARAMS)
            self.db_conn.autocommit = True
        except Exception as e:
            self.get_logger().error(f"PostgreSQL connection error: {e}")

        # 10 Hz Timer Loop for database ingestion
        self.create_timer(0.1, self.db_insert_loop)

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
        self.latest_lat = self.base_lat + (y_north / 111111.0)
        self.latest_lon = self.base_lon + (
            x_east / (111111.0 * math.cos(math.radians(self.base_lat)))
        )

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

    def cp_cb(self, msg: Float32):
        val = float(msg.data)
        if not math.isnan(val) and not math.isinf(val):
            self.latest_cp_potential = round(val, 3)
        else:
            self.latest_cp_potential = None

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

        # Ensure minimal sensor lock before writing
        if self.latest_lat is None or self.latest_depth is None:
            return

        current_time = time.time()
        elapsed_seconds = round(current_time - self.start_time, 2)
        self.frame_number += 3.0

        sonar_val = self.latest_dist
        cp_val = self.latest_cp_potential

        try:
            # Auto-reconnect if database connection was interrupted
            if self.db_conn is None or self.db_conn.closed != 0:
                self.db_conn = psycopg2.connect(**DB_PARAMS)
                self.db_conn.autocommit = True

            # Use fresh context-managed cursor on every tick
            with self.db_conn.cursor() as cur:
                insert_query = """
                INSERT INTO public.rov_telemetry (
                    "time", mission_id, video_timestamp, distance_meters, geom, depth_meters, frame_number, cp_potential_volts
                ) VALUES (
                    TO_TIMESTAMP(%s), %s, (%s || ' seconds')::INTERVAL, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s
                );
                """
                cur.execute(
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
# 4. STREAMLIT APP INITIALIZATION & STYLING
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
    /* Fixed click-focus hierarchy: removed div/span overrides */
    html, body, p, label {
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
        box-sizing: border-box !important;
        background-color: #182030 !important;
        color: #FFFFFF !important;
        border: 1px solid #28354D !important;
        border-radius: 6px !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus {
        border-color: #2563EB !important;
        box-shadow: 0 0 0 1px #2563EB !important;
    }
    .stButton button, .stDownloadButton button {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        padding: 0.8rem 1.8rem !important;
        border-radius: 6px !important;
        min-height: 60px !important;
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        border: none !important;
    }
    .stButton button:hover, .stDownloadButton button:hover {
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
    if not rclpy.ok():
        rclpy.init()
    node = StreamlitROSNode()
    thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    thread.start()
    return node


ros_node = init_ros2()

if "client_info" not in st.session_state:
    st.session_state.client_info = None
if "active_mission_id" not in st.session_state:
    st.session_state.active_mission_id = None

# ==========================================
# 5. INTERFACE LAYOUT & TABS
# ==========================================
st.title("⚓ ROV Control")
st.caption("ROV Telemetry Control & Operational Dashboard")

tab1, tab2 = st.tabs(
    ["🚀 Mission Setup & Live Control", "📊 Database Explorer & PDF Generator"]
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
                    "SELECT client_id, email FROM public.clients WHERE company_name ILIKE %s;",
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
                        f"Client '{company_name}' not found. Register new client below."
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
                            "INSERT INTO public.clients (company_name, email, passcode_hash) "
                            "VALUES (%s, %s, %s) RETURNING client_id;",
                            (c_info["name"], email, passcode),
                        )
                        client_id = cur.fetchone()[0]
                    else:
                        client_id = c_info["id"]

                    cur.execute(
                        "INSERT INTO public.missions (client_id, mission_date, video_link) "
                        "VALUES (%s, CURRENT_DATE, %s) RETURNING mission_id;",
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
                    st.toast(f"Recording started for Mission #{m_id}", icon="🎥")

            with btn_col2:
                if st.button("⏹️ STOP RECORDING", use_container_width=True):
                    ros_node.stop_recording()
                    st.toast("Recording Stopped", icon="⏹️")

            st.write("---")
            st.subheader("Live Sensor Stream")

            m1, m2 = st.columns(2)
            m3, m4, m5 = st.columns(3)

            lat = f"{ros_node.latest_lat:.7f}" if ros_node.latest_lat else "N/A"
            lon = f"{ros_node.latest_lon:.7f}" if ros_node.latest_lon else "N/A"
            depth = f"{ros_node.latest_depth} m" if ros_node.latest_depth is not None else "N/A"
            sonar = f"{ros_node.latest_dist} m" if ros_node.latest_dist is not None else "N/A"
            cp_val = (
                f"{ros_node.latest_cp_potential:.3f} V"
                if ros_node.latest_cp_potential is not None
                else "N/A"
            )

            m1.metric("Current Latitude", lat)
            m2.metric("Current Longitude", lon)
            m3.metric("ROV Depth", depth)
            m4.metric("Sonar Distance", sonar)
            m5.metric("CP Potential", cp_val)

            if ros_node.recording_active:
                st.markdown(
                    "<span style='color: #22C55E;'>● RECORDING IN PROGRESS</span>",
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
# TAB 2: DATA & CLIENT EXPLORER & PDF GENERATOR
# ------------------------------------------
with tab2:
    conn = get_db_connection()

    st.subheader("Registered Clients")
    df_clients = pd.read_sql(
        "SELECT client_id, company_name, email FROM public.clients ORDER BY client_id DESC;",
        conn,
    )
    st.dataframe(df_clients, use_container_width=True)

    st.subheader("Registered Missions")
    df_missions = pd.read_sql(
        "SELECT mission_id, client_id, mission_date, video_link FROM public.missions ORDER BY mission_id DESC;",
        conn,
    )
    st.dataframe(df_missions, use_container_width=True)

    st.subheader("Recent Mission Telemetry Data & Engineering PDF Report")

    col_m, col_l, col_btn = st.columns([1, 1, 1.2])
    with col_m:
        mission_filter = st.number_input("Filter by Mission ID", value=1, step=1)
    with col_l:
        max_rows = st.select_slider(
            "Telemetry Records Limit",
            options=[100, 500, 1000, 5000, "ALL"],
            value=500,
        )

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
            cp_potential_volts,
            frame_number
        FROM public.rov_telemetry
        WHERE mission_id = %s
        ORDER BY "time" ASC;
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
            cp_potential_volts,
            frame_number
        FROM public.rov_telemetry
        WHERE mission_id = %s
        ORDER BY "time" ASC
        LIMIT %s;
        """
        params = (mission_filter, max_rows)

    df_telemetry = pd.read_sql(telemetry_query, conn, params=params)

    with col_btn:
        st.write(" ")
        st.write(" ")
        if not df_telemetry.empty:
            m_meta_query = """
            SELECT c.company_name, m.video_link 
            FROM public.missions m
            JOIN public.clients c ON m.client_id = c.client_id
            WHERE m.mission_id = %s;
            """
            cur_meta = conn.cursor()
            cur_meta.execute(m_meta_query, (mission_filter,))
            meta_res = cur_meta.fetchone()
            cur_meta.close()

            c_name = meta_res[0] if meta_res else "National Grid Authority"
            v_link = meta_res[1] if meta_res else "dive_video_01.mp4"

            pdf_bytes = generate_imca_pdf_report(
                mission_filter, c_name, v_link, df_telemetry
            )

            st.download_button(
                label="📄 Generate IMCA R 004 Report",
                data=pdf_bytes,
                file_name=f"IMCA_R004_Mission_{mission_filter}_Report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        else:
            st.button(
                "📄 Generate IMCA R 004 Report",
                disabled=True,
                use_container_width=True,
            )

    if not df_telemetry.empty:
        st.map(df_telemetry, latitude="latitude", longitude="longitude")
        st.dataframe(df_telemetry, use_container_width=True)
    else:
        st.info("No telemetry records found for this Mission ID.")

    conn.close()