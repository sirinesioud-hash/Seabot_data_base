#!/usr/bin/env python3
"""
===============================================================================
MODULE: Subsea ROV Inspection Portal & Visual Telemetry Dashboard
FILE: app.py (Client Web Portal)
===============================================================================

Purpose in Pipeline:
    Serves as the client-facing presentation and inspection analytics layer of 
    the spatial-temporal data pipeline. It authenticates client users against 
    relational database tables, extracts spatial geometries via PostGIS queries, 
    renders interactive trajectory maps and hydrostatic depth profiles, and 
    generates formal IMCA R 004 PDF inspection reports and CSV audit logs.
===============================================================================
"""

import io
import math
import os
import time
import folium
import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st
from streamlit_folium import st_folium

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
DB_CONFIG = {
    "dbname": "rov_db",
    "user": "postgres",
    "password": "sirinesioud",  # Update with your DB password if changed
    "host": "localhost",
    "port": 5432,
}


def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        st.error(f"Database Connection Error: {e}")
        return None


# ==========================================
# 2. MATH & IMCA REPORTING HELPERS
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
    """Generates an IMCA R 004 / IOGP SSDM Compliant PDF Report buffer for client handover."""
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

    # Section 3: Telemetry Matrix
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

    if "cp_potential_volts" in df_sorted.columns:
        df_sorted["cp_key"] = df_sorted["cp_potential_volts"].round(3)
    else:
        df_sorted["cp_key"] = 0.0

    df_sorted["block_id"] = (df_sorted["cp_key"] != df_sorted["cp_key"].shift()).cumsum()

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
# 3. AUTHENTICATION & QUERY FUNCTIONS
# ==========================================
def verify_client(company_name, passcode):
    """Verifies client credentials from public.clients."""
    conn = get_db_connection()
    if not conn:
        return None

    query = """
    SELECT client_id, company_name 
    FROM public.clients 
    WHERE LOWER(company_name) = LOWER(%s) AND passcode_hash = %s;
    """
    cursor = conn.cursor()
    cursor.execute(query, (company_name, passcode))
    client = cursor.fetchone()
    conn.close()
    return client


def get_client_missions(client_id):
    """Fetch missions assigned to the logged-in client."""
    conn = get_db_connection()
    query = """
    SELECT mission_id, mission_date, video_link 
    FROM public.missions 
    WHERE client_id = %s 
    ORDER BY mission_date DESC;
    """
    df = pd.read_sql(query, conn, params=(client_id,))
    conn.close()
    return df


def get_mission_telemetry(mission_id):
    """Fetch telemetry, CP potential & PostGIS Lat/Lon coordinates for a specific mission."""
    conn = get_db_connection()
    query = """
    SELECT 
        time,
        mission_id,
        frame_number,
        video_timestamp::text AS video_timestamp,
        distance_meters,
        depth_meters,
        cp_potential_volts,
        ST_X(geom) AS longitude,
        ST_Y(geom) AS latitude
    FROM public.rov_telemetry
    WHERE mission_id = %s
    ORDER BY time ASC;
    """
    df = pd.read_sql(query, conn, params=(mission_id,))
    conn.close()
    return df


# ==========================================
# 4. STREAMLIT APP INITIALIZATION & STYLING
# ==========================================
st.set_page_config(
    page_title="Subsea ROV Client Portal",
    page_icon="🌊",
    layout="wide",
)

# Enhanced High-Contrast Theme (Eliminating dim unhovered states)
st.markdown("""
    <style>
    /* Main App Background */
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
    
    /* Force Sidebar to Dark Navy with High Contrast */
    section[data-testid="stSidebar"] {
        background-color: #121824 !important;
        border-right: 1px solid #1E293B !important;
    }
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        color: #F8FAFC !important;
        font-weight: 600 !important;
    }
    
    /* Typography & Hierarchy */
    html, body, p, label {
        font-size: 1.4rem !important;
        color: #CBD5E1 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    h1 { 
        font-size: 3.2rem !important; 
        font-weight: 800 !important; 
        color: #FFFFFF !important;
        margin-bottom: 0.5rem !important;
    }
    h2 { 
        font-size: 2.2rem !important; 
        font-weight: 700 !important; 
        color: #FFFFFF !important;
        border-bottom: 1px solid #1E293B !important;
        padding-bottom: 10px !important;
        margin-top: 1.5rem !important;
    }
    h3 { 
        font-size: 1.7rem !important; 
        font-weight: 600 !important; 
        color: #94A3B8 !important;
    }
    
    /* Form Inputs */
    .stTextInput label, .stNumberInput label, .stSelectbox label {
        font-size: 1.4rem !important;
        font-weight: 700 !important;
        color: #FFFFFF !important;
    }
    .stTextInput input, .stNumberInput input {
        font-size: 1.4rem !important;
        padding: 12px !important;
        height: 55px !important;
        box-sizing: border-box !important;
        background-color: #182030 !important;
        color: #FFFFFF !important;
        border: 1px solid #334155 !important;
        border-radius: 6px !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus {
        border-color: #3B82F6 !important;
        box-shadow: 0 0 0 1px #3B82F6 !important;
    }
    
    /* Form Container Styling */
    div[data-testid="stForm"] {
        background-color: #121824 !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
        padding: 24px !important;
    }

    /* ALL BUTTONS (Action, Download, and Form Submit) - Permanently Bright & High-Contrast */
    .stButton button, 
    .stDownloadButton button, 
    div[data-testid="stFormSubmitButton"] button {
        font-size: 1.4rem !important;
        font-weight: 700 !important;
        padding: 0.8rem 1.6rem !important;
        border-radius: 6px !important;
        min-height: 55px !important;
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        border: 1px solid #3B82F6 !important;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.3) !important;
        opacity: 1 !important;
    }
    .stButton button:hover, 
    .stDownloadButton button:hover, 
    div[data-testid="stFormSubmitButton"] button:hover {
        background-color: #1D4ED8 !important;
        border-color: #60A5FA !important;
        box-shadow: 0 6px 10px -1px rgba(37, 99, 235, 0.5) !important;
    }
    
    /* Telemetry Metric Cards */
    [data-testid="stMetricValue"] {
        font-size: 2.3rem !important;
        font-weight: 800 !important;
        color: #38BDF8 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 1.2rem !important;
        font-weight: 600 !important;
        color: #94A3B8 !important;
        white-space: normal !important;
        word-wrap: break-word !important;
    }
    [data-testid="stMetric"] {
        background-color: #121824 !important;
        border: 1px solid #1E293B !important;
        border-radius: 8px !important;
        padding: 16px !important;
    }
    
    /* EXPANDER: Permanently Bold & High-Contrast (No dim unhovered state) */
    div[data-testid="stExpander"] {
        background-color: #121824 !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
        margin-top: 15px !important;
    }
    div[data-testid="stExpander"] summary {
        background-color: #182030 !important;
        color: #FFFFFF !important;
        font-size: 1.3rem !important;
        font-weight: 700 !important;
        border-radius: 6px !important;
        padding: 12px 18px !important;
    }
    div[data-testid="stExpander"] summary:hover {
        background-color: #1E293B !important;
        color: #38BDF8 !important;
    }
    div[data-testid="stExpander"] summary svg {
        fill: #38BDF8 !important;
    }

    /* Data Tables & Alerts */
    .stDataFrame, div[data-testid="stTable"] {
        font-size: 1.2rem !important;
        background-color: #121824 !important;
        border: 1px solid #1E293B !important;
        border-radius: 6px !important;
    }
    .stAlert {
        font-size: 1.3rem !important;
        background-color: #121824 !important;
        border: 1px solid #1E293B !important;
        color: #F8FAFC !important;
    }
    </style>
""", unsafe_allow_html=True)

# Manage session state for client authentication
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "client_info" not in st.session_state:
    st.session_state["client_info"] = None

# ==========================================
# 5. USER INTERFACE FLOW
# ==========================================

# --- SCREEN 1: CLIENT LOGIN ---
if not st.session_state["logged_in"]:
    st.title("🔒 Subsea ROV Inspection Portal")
    st.caption("Secure Client Authentication & Inspection Review")

    col1, col2 = st.columns([1, 1.5])
    with col1:
        with st.form("client_login_form"):
            company_input = st.text_input(
                "Company Name", placeholder="e.g. TotalEnergies / BP"
            )
            passcode_input = st.text_input(
                "Passcode / Access Key", type="password"
            )
            login_btn = st.form_submit_button("Access Inspection Data", use_container_width=True)

            if login_btn and company_input:
                client = verify_client(company_input.strip(), passcode_input.strip())
                if client:
                    st.session_state["logged_in"] = True
                    st.session_state["client_info"] = {
                        "id": client[0],
                        "name": client[1],
                    }
                    st.rerun()
                else:
                    st.error("Invalid Company Name or Passcode.")

# --- SCREEN 2: MAIN DASHBOARD & DATA VIEWER ---
else:
    client_name = st.session_state["client_info"]["name"]
    client_id = st.session_state["client_info"]["id"]

    # --- SIDEBAR: HIGH CONTRAST CLIENT BADGE ---
    st.sidebar.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #1E293B, #0F172A); padding: 18px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);">
            <div style="font-size: 0.85rem; font-weight: 700; color: #38BDF8; text-transform: uppercase; letter-spacing: 0.08em;">CLIENT PORTAL</div>
            <div style="font-size: 1.9rem; font-weight: 800; color: #FFFFFF; margin-top: 4px; display: flex; align-items: center; gap: 8px;">
                🏢 <span style="color: #60A5FA;">{client_name}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["client_info"] = None
        st.rerun()

    st.title("🌊 Subsea ROV Telemetry & Inspection Dashboard")
    st.caption("Synchronized Spatial-Temporal Inspection Logs & Compliance Handover")

    # Fetch available missions for this authenticated client
    missions_df = get_client_missions(client_id)

    if missions_df.empty:
        st.warning("No inspection missions found for your account.")
    else:
        # Mission Selector Dropdown
        mission_options = {
            f"#{row['mission_id']} ({row['mission_date']})": row["mission_id"]
            for _, row in missions_df.iterrows()
        }
        selected_mission_label = st.sidebar.selectbox(
            "Select Dive Mission", list(mission_options.keys())
        )
        selected_mission_id = mission_options[selected_mission_label]

        # Retrieve video link for metadata
        selected_mission_row = missions_df[
            missions_df["mission_id"] == selected_mission_id
        ].iloc[0]
        video_file_link = selected_mission_row.get("video_link", "dive_video_01.mp4")

        # Load Telemetry from PostgreSQL
        telemetry_df = get_mission_telemetry(selected_mission_id)

        if telemetry_df.empty:
            st.info("No telemetry logs recorded for this mission yet.")
        else:
            # --- TOP METRICS ROW ---
            max_depth = telemetry_df["depth_meters"].max()
            avg_altitude = telemetry_df["distance_meters"].mean()
            total_frames = telemetry_df["frame_number"].max()
            dive_duration = (
                telemetry_df["video_timestamp"].iloc[-1]
                if "video_timestamp" in telemetry_df
                else "N/A"
            )

            # Average CP potential reading
            avg_cp = (
                telemetry_df["cp_potential_volts"].mean()
                if "cp_potential_volts" in telemetry_df
                and pd.notnull(telemetry_df["cp_potential_volts"].mean())
                else None
            )
            cp_metric_str = f"{avg_cp:.3f} V" if avg_cp is not None else "N/A"

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Max Subsea Depth", f"{max_depth:.2f} m" if pd.notnull(max_depth) else "N/A")
            m2.metric("Avg Seafloor Altitude", f"{avg_altitude:.2f} m" if pd.notnull(avg_altitude) else "N/A")
            m3.metric("Avg CP Potential", cp_metric_str)
            m4.metric("Total Recorded Frames", f"{total_frames:,}" if pd.notnull(total_frames) else "0")
            m5.metric("Dive Duration", f"{dive_duration}")

            st.markdown("---")

            # --- REPORT EXPORT ACTION ROW ---
            col_pdf_btn, col_csv_btn = st.columns([1, 1])

            with col_pdf_btn:
                pdf_report_bytes = generate_imca_pdf_report(
                    mission_id=selected_mission_id,
                    client_name=client_name,
                    video_link=video_file_link,
                    df_raw=telemetry_df,
                    logo_path="mare_custos_logo.jpeg",
                )
                st.download_button(
                    label="📄 Download Official IMCA R 004 Report (PDF)",
                    data=pdf_report_bytes,
                    file_name=f"IMCA_R004_Mission_{selected_mission_id}_{client_name}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )

            with col_csv_btn:
                csv_data = telemetry_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Export Raw Mission Telemetry (CSV)",
                    data=csv_data,
                    file_name=f"mission_{selected_mission_id}_telemetry.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            st.write(" ")

            # --- MAP & PROFILE CHARTS SIDE-BY-SIDE ---
            col_map, col_chart = st.columns([1, 1])

            with col_map:
                st.subheader("📍 PostGIS Seabed Trajectory Map")
                valid_coords = telemetry_df.dropna(subset=["latitude", "longitude"])

                if not valid_coords.empty:
                    start_lat = valid_coords["latitude"].iloc[0]
                    start_lon = valid_coords["longitude"].iloc[0]

                    # Folium Map with OpenStreetMap High-Clarity Tiles
                    m = folium.Map(
                        location=[start_lat, start_lon],
                        zoom_start=16,
                        tiles="OpenStreetMap",
                    )

                    # Draw ROV Trajectory Path
                    points = list(zip(valid_coords["latitude"], valid_coords["longitude"]))
                    folium.PolyLine(
                        points, color="#2563EB", weight=4, opacity=0.9
                    ).add_to(m)

                    # Add Start and End Markers
                    folium.Marker(
                        points[0],
                        popup="Dive Start",
                        icon=folium.Icon(color="green", icon="play"),
                    ).add_to(m)
                    folium.Marker(
                        points[-1],
                        popup="Dive End",
                        icon=folium.Icon(color="red", icon="stop"),
                    ).add_to(m)

                    # Automatically fill column width
                    st_folium(m, use_container_width=True, height=420)
                else:
                    st.warning("No valid geospatial coordinates recorded for this dive.")

            with col_chart:
                st.subheader("📈 Subsea Depth & Seafloor Profile")

                # Rename columns for clean, crisp legend text
                plot_df = telemetry_df.rename(
                    columns={
                        "depth_meters": "Depth (meters)",
                        "distance_meters": "Seafloor Distance (meters)",
                    }
                )

                fig = px.line(
                    plot_df,
                    x="frame_number",
                    y=["Depth (meters)", "Seafloor Distance (meters)"],
                    labels={
                        "value": "Meters",
                        "frame_number": "Frame Index",
                        "variable": "Sensor Metrics",
                    },
                    title="Hydrostatic Depth vs Seafloor Altitude Across Frames",
                    color_discrete_sequence=["#38BDF8", "#34D399"],
                )

                # Pure White & High-Contrast Styling on Chart Text & Legend
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#121824",
                    plot_bgcolor="#182030",
                    font=dict(color="#FFFFFF", size=13, family="sans-serif"),
                    title=dict(
                        font=dict(color="#FFFFFF", size=15, family="sans-serif")
                    ),
                    legend=dict(
                        title=dict(
                            text="<b>Sensor Metrics:</b>",
                            font=dict(color="#FFFFFF", size=13),
                        ),
                        font=dict(color="#FFFFFF", size=12),
                        bgcolor="#182030",
                        bordercolor="#334155",
                        borderwidth=1.5,
                        x=0.02,
                        y=0.98,
                    ),
                    xaxis=dict(
                        title=dict(text="<b>Frame Index</b>", font=dict(color="#FFFFFF", size=13)),
                        tickfont=dict(color="#F8FAFC", size=11),
                        gridcolor="#1E293B",
                    ),
                    yaxis=dict(
                        title=dict(text="<b>Meters</b>", font=dict(color="#FFFFFF", size=13)),
                        tickfont=dict(color="#F8FAFC", size=11),
                        gridcolor="#1E293B",
                        autorange="reversed",  # 0m surface at top
                    ),
                    margin=dict(l=20, r=20, t=50, b=20),
                )
                st.plotly_chart(fig, use_container_width=True)

            # --- RAW TELEMETRY AUDIT TABLE (Expander) ---
            with st.expander("📄 View Detailed Telemetry Log Table"):
                st.dataframe(telemetry_df, use_container_width=True)