# 🌊 Subsea ROV Spatial-Temporal Telemetry Pipeline & Inspection Portal

---

## Description

A real-time subsea telemetry ingestion, spatial-temporal synchronization, and inspection analytics system built under **ROS 2 Jazzy**, **PostgreSQL / PostGIS / TimescaleDB**, and **Streamlit**.

### 📌 Executive Overview

Offshore Remote Operated Vehicle (ROV) inspection dives generate high-frequency, multi-rate telemetry streams—including acoustic USBL positioning, hydrostatic depth, seabed altitude distance, and video frame indexing.

---

## Motivation

This repository implements an end-to-end real-time pipeline that:
1. **Simulates and Routes Multi-Rate Sensor Streams** across dedicated ROS 2 nodes.
2. **Throttles & Normalizes High-Frequency Acoustic Data** (downscaling raw acoustic USBL positioning to 1 Hz while maintaining 10 Hz depth/altitude and 30 FPS video sync).
3. **Persists Telemetry into Spatial-Temporal Databases** via a non-blocking gatekeeper synchronization engine that binds records to a 3-column composite primary key (`time`, `mission_id`, `frame_number`) with native PostGIS WGS 84 point geometries (`ST_SetSRID`, `ST_MakePoint`).
4. **Visualizes Inspection Dives via a Client Portal** featuring multi-tenant authentication, dynamic KPI metrics, interactive Folium trajectory maps, inverted Plotly subsea depth profiles, and raw CSV data downloads.

---

## Quick Start

### 🗄️ Database Schema (`schema.sql`)

The database architecture is designed for multi-tenant data isolation and high-speed time-series queries:

* **`public.clients`**: Stores client profiles (`client_id` PK, `company_name`, `email`, `passcode_hash`).
* **`public.missions`**: Tracks dive inspection metadata (`mission_id` PK, `client_id` FK, `mission_date`, `video_link`).
* **`public.rov_telemetry`**: TimescaleDB hypertable storing synchronized spatial-temporal records.
  * **Composite Primary Key**: `("time", mission_id, frame_number)`
  * **Geometry Column**: `geom GEOMETRY(Point, 4326)` indexed with PostGIS GiST spatial indexes.

---

## Usage

### 🏗️ System Architecture & Node Dynamics

The system operates across three dedicated ROS 2 nodes and a client presentation layer:
[ Raw Simulator Node ]
```text
                          [ Raw Simulator Node ]
                        (rov_simulator: 10 Hz / 30 FPS)
                                   │
                                   ▼
                /raw_usbl, /raw_depth, /raw_distance, /raw_camera
                                   │
                                   ▼
                         [ Publisher Node ]
                (rov_publisher: 1 Hz USBL Throttling)
                                   │
                                   ▼
                    /usbl, /depth, /distance, /camera
                                   │
                                   ▼
                       [ Subscriber Syncer Node ]
            (subscriber_syncer: Gatekeeper Pattern + PostGIS)
                                   │
                                   ▼
             ┌───────────────────────────────────────────┐
             │   PostgreSQL / TimescaleDB + PostGIS      │
             │  • public.clients                         │
             │  • public.missions                        │
             │  • public.rov_telemetry (Hypertable)      │
             └───────────────────────────────────────────┘
                                   │
                                   ▼
                         [ Streamlit Client Portal ]
                    (app.py: Folium + Plotly Analytics)
```
---

### 1. `rov_simulator` (Kinematics & Telemetry Simulator)
* **Function:** Models subsea ROV kinematic movement around a geographic origin (Tunis subsea region) and generates raw telemetry feeds.
* **Callback Execution Dynamics:** Timer-driven $10\text{ Hz}$ periodic loop (`0.1s` interval).
* **Frame Progression Math:** Increments frame indices by `3.0` per $0.1\text{s}$ tick to synchronously match a $30\text{ FPS}$ camera feed ($3.0 \text{ frames} / 0.1\text{s} = 30 \text{ FPS}$).

### 2. `rov_publisher` (Multi-Rate Router & Throttler)
* **Function:** Ingests raw topics and dispatches cleaned telemetry to output topics.
* **USBL Throttling Logic:** Uses nanosecond clock deltas ($\ge 10^9 \text{ ns}$) to rate-gate incoming high-frequency USBL acoustic data down to a standard $1\text{ Hz}$ sampling rate before broadcasting to `/usbl`.
* **Event-Driven Forwarding:** Relays depth meters ($10\text{ Hz}$), distance meters ($10\text{ Hz}$), and camera frame metadata ($30\text{ Hz}$) without blocking the executor queue.

### 3. `subscriber_syncer` (Database Synchronization Engine)
* **Function:** Interactively sets up client profiles and missions before writing incoming real-time telemetry to the database.
* **Asynchronous Cache & Gatekeeper Pattern:** Maintains an internal state cache (`latest_lat`, `latest_lon`, `latest_depth`, `latest_dist`) and suppresses SQL write execution until all core sensor streams dispatch their initial valid message payload.
* **Spatial Transformation:** Executes SQL inserts using `TO_TIMESTAMP()` for Epoch time formatting, `INTERVAL` casting for video offsets, and `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` for native PostGIS geographic points.

### 4. `timestamp_extractor.py` (Video Frame Engine)
* **Function:** Processes recorded inspection MP4 videos via OpenCV (`cv2`), extracting relative frame timestamps and previewing optical frame overlays.

### 5. `app.py` (Streamlit Client Web Portal)
* **Function:** Multi-tenant dashboard for client inspection analysis.
* **Geospatial Extraction:** Queries `public.rov_telemetry` using `ST_X(geom)` (Longitude) and `ST_Y(geom)` (Latitude).
* **Visuals:** Renders interactive dive tracks using Folium maps, displays hydrostatic depth vs seafloor altitude using Plotly line charts (with inverted Y-axes to show depth extending downward), and provides CSV reporting downloads.

---

## Contributing

Contributions, issues, and feature requests are welcome. Feel free to open a pull request or submit an issue to improve pipeline performance, add support for additional ROV sensor interfaces, or enhance spatial-temporal analytics capabilities.
