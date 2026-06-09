# -*- coding: utf-8 -*-
import sqlite3
import pandas as pd
import numpy as np
import pytz
import os
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from tabulate import tabulate
import requests
import math
import warnings
from fpdf import FPDF

warnings.filterwarnings('ignore')

# ===================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ (будут переопределены из params) =====================
DEFAULT_LAT = 50.739537
DEFAULT_LON = 136.567232
LOCAL_BASE_PATH = os.getcwd()

def get_unique_filename(base_path, filename):
    return os.path.join(base_path, filename)

def download_file(file_name):
    file_path = os.path.join(LOCAL_BASE_PATH, file_name)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Файл {file_name} не найден в {LOCAL_BASE_PATH}.")
    return file_path

def upload_file_to_drive(file_name):
    pass

# ===================== ФУНКЦИИ ПАРСИНГА ОБЛАЧНОСТИ (без изменений) =====================
API_ARCHIVE  = "https://archive-api.open-meteo.com/v1/archive"
API_FORECAST = "https://api.open-meteo.com/v1/forecast"

def init_db(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS screenshots (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        site          TEXT    NOT NULL,
        datetime      TEXT    NOT NULL UNIQUE,
        datetime_utc  TEXT,
        clouds        REAL    NOT NULL,
        temperature   REAL    NOT NULL
    )""")
    conn.commit()
    cur.execute("PRAGMA table_info(screenshots)")
    existing = [r[1] for r in cur.fetchall()]
    if 'datetime_utc' not in existing:
        try:
            cur.execute("ALTER TABLE screenshots ADD COLUMN datetime_utc TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

def fetch_cloudcover(url, lat, lon, start_date, end_date):
    params = {
        "latitude":  lat,
        "longitude": lon,
        "hourly":    "cloudcover,temperature_2m",
        "start_date": start_date,
        "end_date":   end_date,
        "timezone":  "UTC"
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    times = data.get("hourly", {}).get("time", [])
    clouds = data.get("hourly", {}).get("cloudcover", [])
    temps  = data.get("hourly", {}).get("temperature_2m", [])
    records = list(zip(times, clouds, temps))
    records.sort(key=lambda x: x[0])
    return records

def insert_new(conn, site_url, records, start_utc=None, end_utc=None):
    DATA_TZ = pytz.UTC
    cur = conn.cursor()
    added = 0
    for t_iso, cloud, temp in records:
        if cloud is None or temp is None:
            continue
        if 'T' in t_iso:
            time_part = t_iso.split('T')[1]
            if len(time_part) == 5:
                t_full = t_iso + ":00"
            else:
                t_full = t_iso
        else:
            t_full = t_iso + "T00:00:00"
        try:
            dt_naive = datetime.fromisoformat(t_full)
            dt_utc = dt_naive.replace(tzinfo=pytz.UTC)
        except Exception:
            try:
                dt_naive = datetime.strptime(t_full, "%Y-%m-%dT%H:%M:%S")
                dt_utc = pytz.UTC.localize(dt_naive)
            except Exception:
                continue
        if start_utc is not None and dt_utc < start_utc:
            continue
        if end_utc is not None and dt_utc > end_utc:
            continue
        try:
            dt_local = dt_utc.astimezone(DATA_TZ)
        except Exception:
            dt_local = dt_utc
        dt_local_str = dt_local.strftime('%Y-%m-%d %H:%M:%S')
        dt_utc_str   = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
        cur.execute("SELECT 1 FROM screenshots WHERE datetime = ?", (dt_local_str,))
        if cur.fetchone():
            continue
        cur.execute(
            "INSERT INTO screenshots (site, datetime, datetime_utc, clouds, temperature) VALUES (?, ?, ?, ?, ?)",
            (site_url, dt_local_str, dt_utc_str, cloud, temp)
        )
        added += 1
    conn.commit()
    return added

def fetch_and_store_clouds(db_path, lat, lon, start_local_str, end_local_str, local_tz_str="Asia/Vladivostok"):
    """Загружает данные облачности и температуры из open-meteo и сохраняет в БД"""
    try:
        local_tz = pytz.timezone(local_tz_str)
    except:
        local_tz = pytz.UTC
    start_local_naive = datetime.fromisoformat(start_local_str)
    end_local_naive   = datetime.fromisoformat(end_local_str)
    start_local = local_tz.localize(start_local_naive)
    end_local   = local_tz.localize(end_local_naive)
    start_utc = start_local.astimezone(pytz.UTC)
    end_utc   = end_local.astimezone(pytz.UTC)
    db_path = os.path.expanduser(db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    today = datetime.now(pytz.UTC).date()
    req_start_date = start_local.date().isoformat()
    req_end_date   = end_local.date().isoformat()
    total_added = 0
    if start_utc.date() < today:
        arch_end = min(end_utc.date(), today - timedelta(days=1))
        arch_records = fetch_cloudcover(API_ARCHIVE, lat, lon, req_start_date, arch_end.isoformat())
        added = insert_new(conn, f"ARCHIVE {API_ARCHIVE}", arch_records, start_utc=start_utc, end_utc=end_utc)
        total_added += added
    if end_utc.date() >= today:
        fc_start = max(start_utc.date(), today)
        fc_records = fetch_cloudcover(API_FORECAST, lat, lon, fc_start.isoformat(), req_end_date)
        added = insert_new(conn, f"FORECAST {API_FORECAST}", fc_records, start_utc=start_utc, end_utc=end_utc)
        total_added += added
    conn.close()
    return db_path

# ===================== ФУНКЦИИ АСТРОНОМИИ И РАСЧЁТА ЭНЕРГИИ (копия из исходного кода) =====================
def _julian_day(dt):
    Y = dt.year; M = dt.month; D = dt.day + (dt.hour + dt.minute/60.0 + dt.second/3600.0)/24.0
    if M <= 2: Y -= 1; M += 12
    A = int(Y/100); B = 2 - A + int(A/4)
    JD = int(365.25*(Y + 4716)) + int(30.6001*(M+1)) + D + B - 1524.5
    return JD

def _sun_declination_and_hourangle(dt_utc, lon, lat):
    JD = _julian_day(dt_utc)
    d = JD - 2451545.0
    g = (357.529 + 0.98560028 * d) % 360
    q = (280.459 + 0.98564736 * d) % 360
    L = (q + 1.915 * math.sin(math.radians(g)) + 0.020 * math.sin(math.radians(2*g))) % 360
    eps = 23.439 - 3.56e-7 * d
    eps_rad = math.radians(eps); Lrad = math.radians(L)
    decl = math.asin(math.sin(eps_rad) * math.sin(Lrad))
    T = d / 36525.0
    GMST = (280.46061837 + 360.98564736629 * (JD - 2451545.0) + 0.000387933 * T**2 - T**3 / 38710000.0)
    LMST_deg = (GMST + lon) % 360
    H_deg = (LMST_deg - L) % 360
    H = math.radians(H_deg if H_deg <= 180 else H_deg - 360)
    return decl, H

def _sun_zenith_deg(dt_utc, lon, lat):
    decl, H = _sun_declination_and_hourangle(dt_utc, lon, lat)
    lat_rad = math.radians(lat)
    cos_zen = math.sin(lat_rad)*math.sin(decl) + math.cos(lat_rad)*math.cos(decl)*math.cos(H)
    cos_zen = max(min(cos_zen, 1.0), -1.0)
    return math.degrees(math.acos(cos_zen))

def _earth_distance_factor(dayofyear):
    return 1.0 + 0.033 * math.cos(2.0 * math.pi * (dayofyear / 365.0))

def _airmass_kasten(zenith_deg):
    if zenith_deg >= 90.0: return 9999.0
    z = zenith_deg
    return 1.0 / (math.cos(math.radians(z)) + 0.50572 * (96.07995 - z) ** -1.6364)

def optimal_tilt_azimuth(latitude):
    lat_abs = abs(latitude)
    tilt = lat_abs
    azimuth = 180.0 if latitude > 0 else 0.0 if latitude < 0 else 0.0
    return tilt, azimuth

def transpose_ghi_to_poa(dt_utc, ghi, lat, lon, tilt, azimuth, albedo=0.2, solar_constant=1361.0):
    zen = _sun_zenith_deg(dt_utc, lon, lat)
    cos_z = math.cos(math.radians(zen)) if zen < 90.0 else 0.0
    if cos_z <= 0 or ghi <= 0: return 0.0
    doy = dt_utc.timetuple().tm_yday
    dist_factor = _earth_distance_factor(doy)
    I0 = solar_constant * dist_factor * cos_z
    kt = ghi / I0 if I0 > 0 else 0.0; kt = max(kt, 0.0)
    if kt <= 0.35: fd = 1.0 - 0.249 * kt
    elif kt <= 0.75: fd = 1.557 - 1.84 * kt
    else: fd = 0.177
    fd = max(0.0, min(fd, 1.0))
    dhi = ghi * fd
    dni = (ghi - dhi) / cos_z if cos_z > 0 else 0.0
    decl, H = _sun_declination_and_hourangle(dt_utc, lon, lat)
    lat_rad = math.radians(lat); tilt_rad = math.radians(tilt); az_rad = math.radians(azimuth)
    cos_theta = (math.sin(decl) * math.sin(lat_rad) * math.cos(tilt_rad)
                 - math.sin(decl) * math.cos(lat_rad) * math.sin(tilt_rad) * math.cos(az_rad)
                 + math.cos(decl) * math.cos(lat_rad) * math.cos(tilt_rad) * math.cos(H)
                 + math.cos(decl) * math.sin(lat_rad) * math.sin(tilt_rad) * math.cos(az_rad) * math.cos(H)
                 + math.cos(decl) * math.sin(tilt_rad) * math.sin(az_rad) * math.sin(H))
    cos_theta = max(0.0, cos_theta)
    beam = dni * cos_theta
    diffuse = dhi * (1.0 + math.cos(tilt_rad)) / 2.0
    ground = ghi * albedo * (1.0 - math.cos(tilt_rad)) / 2.0
    poa = beam + diffuse + ground
    return max(poa, 0.0)

def calculate_solar_flux_and_save_to_db(file_name, latitude, longitude, photoEfficiency, k_photoEffTemp, photoNOCT, timezone='Asia/Vladivostok'):
    conn = sqlite3.connect(file_name)
    df = pd.read_sql_query("SELECT datetime_utc, clouds, temperature FROM screenshots", conn)
    conn.close()
    df['datetime'] = pd.to_datetime(df['datetime_utc'])
    df.sort_values('datetime', inplace=True); df.reset_index(drop=True, inplace=True)
    if 'temperature' not in df.columns: df['temperature'] = 25.0
    df['temperature'] = pd.to_numeric(df['temperature'], errors='coerce').fillna(25.0)
    if 'clouds' not in df.columns: df['clouds'] = 0.0
    df['clouds'] = pd.to_numeric(df['clouds'], errors='coerce').fillna(0.0)
    df['clouds'] = df['clouds'].clip(0, 100)
    solar_constant = 1361.0; tau = 0.2
    solar_flux_rows = []
    for idx, row in df.iterrows():
        dt = row['datetime']
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None: dt_utc = dt.tz_convert('UTC').replace(tzinfo=None)
        else: dt_utc = dt
        doy = dt_utc.timetuple().tm_yday
        zen = _sun_zenith_deg(dt_utc, longitude, latitude)
        cos_z = math.cos(math.radians(zen)) if zen < 90.0 else 0.0; cos_z = max(cos_z, 0.0)
        dist_factor = _earth_distance_factor(doy)
        albedo_coeff = 0.5 * (1.0 + 0.6 * math.sin(2.0 * math.pi * (doy - 172 - 91) / 365.0))
        reflected_factor = 1.0 + albedo_coeff
        I_ex = solar_constant * dist_factor * cos_z * reflected_factor; I_ex = max(I_ex, 0.0)
        airmass = _airmass_kasten(zen)
        atm_trans = math.exp(-tau * airmass) if airmass < 999 else 0.0
        I_surface = I_ex * atm_trans
        amb_temp = float(row.get('temperature', 25.0))
        cell_temp = amb_temp + (photoNOCT - 20.0) / 800.0 * I_surface
        temp_factor = 1.0 + k_photoEffTemp * (cell_temp - 25.0)
        solar_flux_value = I_surface * temp_factor
        if not np.isfinite(solar_flux_value): solar_flux_value = 0.0
        solar_flux_value = max(solar_flux_value, 0.0)
        try:
            tz_obj = pytz.timezone(timezone)
            datetime_local = dt_utc.replace(tzinfo=pytz.UTC).astimezone(tz_obj)
        except:
            datetime_local = pd.Timestamp(dt_utc).tz_localize('UTC').tz_convert(timezone)
        datetime_str = datetime_local.strftime('%Y-%m-%d %H:%M:%S')
        solar_flux_rows.append((datetime_str, float(solar_flux_value)))
    new_db_file = get_unique_filename(LOCAL_BASE_PATH, '1.2_ClearSky_Alb_del.db')
    conn_new = sqlite3.connect(new_db_file)
    cursor_new = conn_new.cursor()
    cursor_new.execute('''CREATE TABLE IF NOT EXISTS Solar_Flux (datetime TIMESTAMP, solar_flux FLOAT)''')
    cursor_new.executemany("INSERT INTO Solar_Flux (datetime, solar_flux) VALUES (?, ?)", solar_flux_rows)
    cursor_new.execute("UPDATE Solar_Flux SET solar_flux = 0 WHERE solar_flux IS NULL")
    conn_new.commit(); conn_new.close()
    return new_db_file

def calculate_cloudiness(solar_flux_file1, solar_flux_file2, timezone='Asia/Vladivostok'):
    cloudiness_db_file = get_unique_filename(LOCAL_BASE_PATH, '3.2_SimSolarFlux.db')
    conn1 = sqlite3.connect(solar_flux_file1); df1 = pd.read_sql_query("SELECT datetime, solar_flux FROM Solar_Flux", conn1); conn1.close()
    conn2 = sqlite3.connect(solar_flux_file2); df2 = pd.read_sql_query("SELECT datetime, clouds FROM screenshots", conn2); conn2.close()
    df1['datetime'] = pd.to_datetime(df1['datetime']); df1['solar_flux'] = df1['solar_flux'].astype(float)
    df2['datetime'] = pd.to_datetime(df2['datetime'], format='mixed'); df2['clouds'] = pd.to_numeric(df2['clouds'], errors='coerce').fillna(0)
    df_merged = pd.merge(df1, df2, on='datetime', how='inner')
    if len(df_merged) == 0: raise ValueError("Нет совпадающих записей")
    df_merged['cloudiness'] = df_merged['solar_flux'] * (1 - (df_merged['clouds'] / 105))
    df_cloudiness = df_merged[['datetime', 'cloudiness']].rename(columns={'cloudiness': 'solar_flux'})
    conn_cloudiness = sqlite3.connect(cloudiness_db_file)
    df_cloudiness.to_sql('Cloudiness', conn_cloudiness, if_exists='replace', index=False)
    conn_cloudiness.close()
    return cloudiness_db_file

# ===================== ОСНОВНАЯ ФУНКЦИЯ-ОБЁРТКА (запускает весь расчёт) =====================
def run_simulation(params):
    """
    params: словарь со всеми введёнными пользователем параметрами.
    Возвращает путь к сгенерированному PDF-отчёту.
    """
    # Извлекаем параметры
    lat = params['lat']; lon = params['lon']; local_tz = params.get('timezone', 'Asia/Vladivostok')
    start_str = params['start_date']; end_str = params['end_date']
    # Параметры нагрузки
    max_load_power_kw = params['max_load_power_kw']
    max_load_work_hours = params['max_load_work_hours']
    load_min_start_hour = params['load_min_start_hour']; load_min_end_hour = params['load_min_end_hour']
    load_max_start_hour = params['load_max_start_hour']; load_max_end_hour = params['load_max_end_hour']
    load_normal_start_hour = params['load_normal_start_hour']; load_normal_end_hour = params['load_normal_end_hour']
    # Панель
    photoEfficiency = params['photoEfficiency']; k_photoEffTemp = params['k_photoEffTemp']; photoNOCT = params['photoNOCT']
    panel_Vmp = params['panel_Vmp']; panel_Voc = params['panel_Voc']; panel_Imp = params['panel_Imp']; panel_Isc = params['panel_Isc']
    photoCellWidth = params['photoCellWidth']; photoCellHigh = params['photoCellHigh']; photoCellNum = params['photoCellNum']
    # Аккумулятор
    numberbattery_1 = params['numberbattery_1']; charge_voltage = params['charge_voltage']; battery_nominal_ah = params['battery_nominal_ah']; battery_voltage = params['battery_voltage']
    k_min_SoC = params.get('k_min_SoC', 0.1); k_mode_battery = params.get('k_mode_battery', 0.8); kCharge = params.get('kCharge', 0.3)
    # Инвертор
    inverter_nominal_power = params['inverter_nominal_power']; inverter_efficiency = params['inverter_efficiency']
    inverter_battery_voltage_nominal = params['inverter_battery_voltage_nominal']; inverter_battery_voltage_min = params['inverter_battery_voltage_min']; inverter_battery_voltage_max = params['inverter_battery_voltage_max']
    inverter_max_battery_charge_current = params['inverter_max_battery_charge_current']; inverter_max_battery_discharge_current = params['inverter_max_battery_discharge_current']
    inverter_mppt_min = params['inverter_mppt_min']; inverter_mppt_max = params['inverter_mppt_max']; inverter_pv_max_voltage = params['inverter_pv_max_voltage']; inverter_pv_start_voltage = params['inverter_pv_start_voltage']
    inverter_mppt_count = params['inverter_mppt_count']; inverter_pv_nominal_power = params['inverter_pv_nominal_power']
    inverter_pv_max_current_per_mppt = params['inverter_pv_max_current_per_mppt']; inverter_pv_max_isc_per_mppt = params['inverter_pv_max_isc_per_mppt']; max_inverters_in_parallel = params['max_inverters_in_parallel']
    # Потери
    k_cable_pv = params['k_cable_pv']; k_cable_batt = params['k_cable_batt']; k_cable_ac = params['k_cable_ac']
    reserve_factor_inverter = params.get('reserve_factor_inverter', 1.2)
    roof_length = params.get('roof_length', 30); roof_width = params.get('roof_width', 30)

    # ---------- 1. Получение данных облачности ----------
    db_clouds = get_unique_filename(LOCAL_BASE_PATH, '1.3_clouds_temp.db')
    fetch_and_store_clouds(db_clouds, lat, lon, start_str, end_str, local_tz)

    # ---------- 2. Расчёт производных величин нагрузки ----------
    def _interval_hours(start_h, end_h):
        start_h = int(start_h) % 24; end_h = int(end_h) % 24
        if end_h >= start_h: return end_h - start_h
        return (24 - start_h) + end_h
    load_min_hours = _interval_hours(load_min_start_hour, load_min_end_hour)
    load_max_hours = _interval_hours(load_max_start_hour, load_max_end_hour)
    load_normal_hours = _interval_hours(load_normal_start_hour, load_normal_end_hour)
    load_power_max_kw = max_load_power_kw / max_load_work_hours
    load_power_max_w = load_power_max_kw * 1000.0
    load_power_normal_w = 0.60 * load_power_max_w
    load_power_min_w = 0.10 * load_power_max_w
    def get_load_power_w(hour):
        hour = int(hour) % 24
        if load_min_start_hour <= hour < load_min_end_hour: return load_power_min_w
        elif load_max_start_hour <= hour < load_max_end_hour: return load_power_max_w
        else: return load_power_normal_w

    # ---------- 3. Раскладка панелей на крыше ----------
    min_panels_in_series = math.ceil(inverter_mppt_min / panel_Vmp)
    max_panels_in_series = math.floor(inverter_mppt_max / panel_Voc)
    max_panels_absolute = math.floor(inverter_pv_max_voltage / panel_Voc)
    def optimize_pv_on_roof(roof_length_m, roof_width_m, panel_length_m=1.762, panel_width_m=1.134, edge_margin_m=0.30, gap_m=0.02):
        def count_fit(roof_dim, panel_dim):
            usable_dim = roof_dim - 2 * edge_margin_m
            if usable_dim <= 0: return 0
            return max(0, math.floor((usable_dim + gap_m) / (panel_dim + gap_m)))
        candidates = []
        for orientation, dim_along_length, dim_along_width in [("portrait", panel_width_m, panel_length_m), ("landscape", panel_length_m, panel_width_m)]:
            cols = count_fit(roof_length_m, dim_along_length); rows = count_fit(roof_width_m, dim_along_width)
            total_panels = cols * rows
            used_length = cols * dim_along_length + max(0, cols - 1) * gap_m; used_width = rows * dim_along_width + max(0, rows - 1) * gap_m
            free_length = roof_length_m - 2 * edge_margin_m - used_length; free_width = roof_width_m - 2 * edge_margin_m - used_width
            valid_string_lengths = [s for s in range(min_panels_in_series, min(max_panels_in_series, cols) + 1) if cols % s == 0]
            if valid_string_lengths:
                panels_per_string = max(valid_string_lengths); strings_per_row = cols // panels_per_string; total_strings = rows * strings_per_row; electrical_ok = True
            else: panels_per_string = None; strings_per_row = None; total_strings = None; electrical_ok = False
            candidates.append({"orientation": orientation, "cols_along_length": cols, "rows_along_width": rows, "total_panels": total_panels,
                               "panels_per_string": panels_per_string, "strings_per_row": strings_per_row, "total_strings": total_strings,
                               "electrical_ok": electrical_ok, "used_length_m": round(used_length,3), "used_width_m": round(used_width,3),
                               "free_length_m": round(free_length,3), "free_width_m": round(free_width,3)})
        best = max(candidates, key=lambda x: (x["total_panels"], int(x["electrical_ok"]), -(x["total_strings"] if x["total_strings"] is not None else 10**9)))
        return best, candidates
    best_layout, _ = optimize_pv_on_roof(roof_length_m=roof_length, roof_width_m=roof_width)
    installed_panels = best_layout["total_panels"]
    photoCellSquare = photoCellWidth * photoCellHigh * photoCellNum * installed_panels

    # ---------- 4. Балансировка оборудования (как в исходном коде) ----------
    required_inverter_power = (max_load_power_kw) * reserve_factor_inverter
    required_inverter_power_w = required_inverter_power * 1000
    n_inv_by_load = math.ceil(required_inverter_power / inverter_nominal_power)
    if best_layout["electrical_ok"] and best_layout["total_strings"] is not None:
        total_strings = best_layout["total_strings"]
        max_strings_per_mppt = math.floor(inverter_pv_max_current_per_mppt / panel_Imp) if panel_Imp>0 else 1
        if max_strings_per_mppt < 1: max_strings_per_mppt = 1
        mppt_per_inv = inverter_mppt_count
        max_strings_per_inv = mppt_per_inv * max_strings_per_mppt
        n_inv_by_strings = math.ceil(total_strings / max_strings_per_inv)
        total_pv_power_kw = installed_panels * (panel_Vmp * panel_Imp) / 1000.0
        pv_power_per_inv_kw = inverter_pv_nominal_power / 1000.0
        n_inv_by_pv_power = math.ceil(total_pv_power_kw / pv_power_per_inv_kw)
        n_inv_by_pv = max(n_inv_by_strings, n_inv_by_pv_power)
    else:
        n_inv_by_pv = 1; total_strings = 0; max_strings_per_mppt = 1
    n_inverters_required = max(n_inv_by_load, n_inv_by_pv)
    if n_inverters_required > max_inverters_in_parallel:
        n_inverters_required = max_inverters_in_parallel

    # Адаптация конфигурации панелей (код из оригинала)
    if best_layout["electrical_ok"] and total_strings:
        pv_panels_min = math.ceil(max(inverter_mppt_min, inverter_pv_start_voltage) / panel_Vmp)
        pv_panels_max = math.floor(min(inverter_mppt_max, inverter_pv_max_voltage) / panel_Voc)
        adapted = False
        possible_lengths = [l for l in range(pv_panels_min, min(pv_panels_max, installed_panels)+1) if installed_panels % l == 0]
        possible_lengths.sort(reverse=True)
        for length in possible_lengths:
            strings = installed_panels // length
            strings_per_inv_test = math.ceil(strings / n_inverters_required)
            strings_per_mppt_test = math.ceil(strings_per_inv_test / inverter_mppt_count)
            if strings_per_mppt_test <= max_strings_per_mppt:
                panels_per_string = length; total_strings = strings; adapted = True; break
        if not adapted:
            for n_inv_try in range(n_inverters_required+1, max_inverters_in_parallel+1):
                for length in possible_lengths:
                    strings = installed_panels // length
                    strings_per_inv_test = math.ceil(strings / n_inv_try)
                    strings_per_mppt_test = math.ceil(strings_per_inv_test / inverter_mppt_count)
                    if strings_per_mppt_test <= max_strings_per_mppt:
                        n_inverters_required = n_inv_try; panels_per_string = length; total_strings = strings; adapted = True; break
                if adapted: break
        if not adapted:
            for remove_strings in range(1, total_strings):
                new_panels = installed_panels - panels_per_string * remove_strings
                if new_panels <= 0: break
                possible_lengths_red = [l for l in range(pv_panels_min, min(pv_panels_max, new_panels)+1) if new_panels % l == 0]
                possible_lengths_red.sort(reverse=True)
                for length in possible_lengths_red:
                    strings = new_panels // length
                    strings_per_inv_test = math.ceil(strings / n_inverters_required)
                    strings_per_mppt_test = math.ceil(strings_per_inv_test / inverter_mppt_count)
                    if strings_per_mppt_test <= max_strings_per_mppt:
                        installed_panels = new_panels; panels_per_string = length; total_strings = strings; adapted = True; break
                if adapted: break
        if adapted:
            best_layout["panels_per_string"] = panels_per_string
            best_layout["total_strings"] = total_strings
            best_layout["total_panels"] = installed_panels
        total_pv_power_kw = installed_panels * (panel_Vmp * panel_Imp) / 1000.0

    # Расчёт высоковольтной батареи
    n_inv = n_inverters_required
    battery_series_count_min = math.ceil(inverter_battery_voltage_min / battery_voltage)
    battery_series_count_max = math.floor(inverter_battery_voltage_max / battery_voltage)
    power_per_inv_w = required_inverter_power_w / n_inv
    battery_series_count_min_by_current = math.ceil(power_per_inv_w / (inverter_max_battery_discharge_current * battery_voltage * inverter_efficiency))
    battery_series_count = max(battery_series_count_min, battery_series_count_min_by_current)
    if battery_series_count > battery_series_count_max: battery_series_count = battery_series_count_max
    battery_bank_voltage = battery_series_count * battery_voltage
    battery_current_per_inv = power_per_inv_w / (battery_bank_voltage * inverter_efficiency)
    battery_string_current_limit = battery_nominal_ah * kCharge
    parallel_by_current = math.ceil(battery_current_per_inv / battery_string_current_limit)
    daily_energy_wh = (load_power_min_w * load_min_hours + load_power_normal_w * load_normal_hours + load_power_max_w * load_max_hours)
    daily_energy_per_inv = daily_energy_wh / n_inv
    usable_per_string_wh = (battery_series_count * battery_nominal_ah * battery_voltage * (1 - k_min_SoC) * k_mode_battery)
    parallel_by_energy = math.ceil(daily_energy_per_inv / usable_per_string_wh)
    battery_parallel_count_per_inv = max(parallel_by_current, parallel_by_energy, 1)
    numberbattery_per_inv = battery_series_count * battery_parallel_count_per_inv
    numberbattery_total = n_inv * numberbattery_per_inv
    battery_parallel_count = battery_parallel_count_per_inv * n_inv
    numberbattery = numberbattery_total
    battery_voltage_final = battery_bank_voltage
    nominal_capacity_battery = battery_nominal_ah * battery_parallel_count
    batteryCapacityLim = nominal_capacity_battery * (1 - k_min_SoC) * k_mode_battery
    batteryCapacity = nominal_capacity_battery * k_mode_battery
    maxChargeCurrent = nominal_capacity_battery * kCharge
    battery_DoD = nominal_capacity_battery * k_min_SoC * k_mode_battery
    battery_energy_max_wh = batteryCapacity * battery_bank_voltage
    battery_energy_control_min_wh = battery_DoD * battery_bank_voltage
    battery_floor_ah = 0.001; battery_energy_floor_wh = battery_floor_ah * battery_bank_voltage
    battery_charge_limit_w = maxChargeCurrent * charge_voltage
    battery_discharge_limit_w = n_inv * inverter_max_battery_discharge_current * battery_bank_voltage

    # ---------- 5. Солнечная энергия и облачность ----------
    solar_flux_file2 = db_clouds
    solar_flux_file1 = calculate_solar_flux_and_save_to_db(solar_flux_file2, lat, lon, photoEfficiency, k_photoEffTemp, photoNOCT, local_tz)
    cloudiness_db_file = calculate_cloudiness(solar_flux_file1, solar_flux_file2, local_tz)

    # ---------- 6. Баланс и дефицит (полностью из оригинала) ----------
    start_date = pd.to_datetime(start_str); end_date = pd.to_datetime(end_str)
    conn = sqlite3.connect(cloudiness_db_file)
    hes_data = pd.read_sql_query("SELECT * FROM Cloudiness", conn)
    conn.close()
    hes_data['datetime'] = pd.to_datetime(hes_data['datetime'])
    hes_data['solar_flux'] = pd.to_numeric(hes_data['solar_flux'], errors='coerce')
    hes_data = hes_data.dropna(subset=['datetime', 'solar_flux']).copy()
    filtered_hes_data = hes_data[(hes_data['datetime'] >= start_date) & (hes_data['datetime'] <= end_date)].copy().reset_index(drop=True)
    filtered_hes_data['datetime'] = filtered_hes_data['datetime'].dt.round('60min')
    filtered_hes_data['solar_flux'] = pd.to_numeric(filtered_hes_data['solar_flux'], errors='coerce').fillna(0.0)
    filtered_hes_data['load_power_current_w'] = filtered_hes_data['datetime'].dt.hour.apply(get_load_power_w)

    full_range = pd.date_range(start=filtered_hes_data['datetime'].min(), end=filtered_hes_data['datetime'].max(), freq='60min')
    full_range_date_df = pd.DataFrame({'datetime': full_range})
    full_range_filtered_hes_data = pd.merge(full_range_date_df, filtered_hes_data, on='datetime', how='left')
    full_range_filtered_hes_data = full_range_filtered_hes_data.drop_duplicates(subset='datetime').reset_index(drop=True)
    full_range_filtered_hes_data['hour_diff'] = (full_range_filtered_hes_data['datetime'] - full_range_filtered_hes_data['datetime'].shift()).dt.total_seconds() / 3600
    if len(full_range_filtered_hes_data) > 1: full_range_filtered_hes_data.loc[0, 'hour_diff'] = full_range_filtered_hes_data.loc[1, 'hour_diff']
    else: full_range_filtered_hes_data.loc[0, 'hour_diff'] = 1.0
    full_range_filtered_hes_data['solar_flux'] = pd.to_numeric(full_range_filtered_hes_data['solar_flux'], errors='coerce').interpolate().ffill().bfill().fillna(0.0)
    full_range_filtered_hes_data['load_power_current_w'] = full_range_filtered_hes_data['datetime'].dt.hour.apply(get_load_power_w)
    full_range_filtered_hes_data['load_energy_step_wh'] = full_range_filtered_hes_data['load_power_current_w'] * full_range_filtered_hes_data['hour_diff']
    full_range_filtered_hes_data['load_energy_wh'] = full_range_filtered_hes_data['load_energy_step_wh'].cumsum()

    numberpanel = installed_panels
    panel_active_area_m2 = photoCellWidth * photoCellHigh * photoCellNum
    pv_array_active_area_m2 = panel_active_area_m2 * numberpanel
    full_range_filtered_hes_data['solar_power_dc_w'] = full_range_filtered_hes_data['solar_flux'] * photoEfficiency * pv_array_active_area_m2
    full_range_filtered_hes_data['solar_power_after_pv_cable_w'] = full_range_filtered_hes_data['solar_power_dc_w'] * k_cable_pv
    full_range_filtered_hes_data['pv_ac_available_w'] = full_range_filtered_hes_data['solar_power_after_pv_cable_w'] * inverter_efficiency * k_cable_ac

    # Моделирование работы АКБ
    start_soc = params.get('initial_battery_soc', 0.6)
    full_range_filtered_hes_data['battery_energy'] = np.nan
    full_range_filtered_hes_data.loc[0, 'battery_energy'] = battery_energy_floor_wh + (battery_energy_max_wh - battery_energy_floor_wh) * start_soc
    for col in ['pv_to_load_w','pv_used_for_load_dc_w','pv_surplus_after_load_w','battery_charge_available_w','battery_charge_power_w',
                'battery_discharge_power_w','battery_power','battery_energy_step_wh','battery_ac_supply_w','served_power_w',
                'grid_import_w','grid_energy_step_wh','deficit_after_pv_w','deficit_after_battery_w','power_balance_w']:
        full_range_filtered_hes_data[col] = 0.0
    grid_charge_enabled = False
    for i in range(len(full_range_filtered_hes_data)):
        if i == 0: prev_energy = float(full_range_filtered_hes_data.at[i, 'battery_energy'])
        else: prev_energy = float(full_range_filtered_hes_data.at[i-1, 'battery_energy'])
        dt = float(full_range_filtered_hes_data.at[i, 'hour_diff']); dt = dt if pd.notna(dt) and dt>0 else 1.0
        solar_after_pv_cable_w = float(full_range_filtered_hes_data.at[i, 'solar_power_after_pv_cable_w'])
        pv_ac_available_w = float(full_range_filtered_hes_data.at[i, 'pv_ac_available_w'])
        load_current_w = float(full_range_filtered_hes_data.at[i, 'load_power_current_w'])
        pv_to_load_w = min(load_current_w, pv_ac_available_w)
        if inverter_efficiency * k_cable_ac > 0: pv_used_for_load_dc_w = pv_to_load_w / (inverter_efficiency * k_cable_ac)
        else: pv_used_for_load_dc_w = 0.0
        deficit_after_pv_w = max(load_current_w - pv_to_load_w, 0.0)
        pv_surplus_after_load_w = max(solar_after_pv_cable_w - pv_used_for_load_dc_w, 0.0)
        battery_charge_available_w = pv_surplus_after_load_w * k_cable_batt
        max_charge_possible_w = max((battery_energy_max_wh - prev_energy) / dt, 0.0)
        max_discharge_possible_w = max((prev_energy - battery_energy_floor_wh) / dt, 0.0)
        charge_from_pv = min(battery_charge_available_w, battery_charge_limit_w, max_charge_possible_w)
        if deficit_after_pv_w > 0:
            if inverter_efficiency * k_cable_batt * k_cable_ac > 0: required_discharge_w = deficit_after_pv_w / (inverter_efficiency * k_cable_batt * k_cable_ac)
            else: required_discharge_w = 0.0
            discharge_power_w = min(required_discharge_w, battery_discharge_limit_w, max_discharge_possible_w)
            battery_ac_supply_w = discharge_power_w * inverter_efficiency * k_cable_batt * k_cable_ac
        else: discharge_power_w = 0.0; battery_ac_supply_w = 0.0
        energy_after_discharge = prev_energy - discharge_power_w * dt
        if energy_after_discharge < battery_energy_floor_wh: energy_after_discharge = battery_energy_floor_wh
        if charge_from_pv > 0: grid_charge_enabled = False
        else:
            if energy_after_discharge <= battery_energy_control_min_wh: grid_charge_enabled = True
        if charge_from_pv > 0:
            charge_power_w = charge_from_pv; grid_charge_power = 0.0
        else:
            charge_power_w = 0.0
            if grid_charge_enabled:
                max_grid_charge = max((battery_energy_max_wh - energy_after_discharge) / dt, 0.0)
                grid_charge_power = min(battery_charge_limit_w, max_grid_charge)
            else: grid_charge_power = 0.0
        next_energy = energy_after_discharge + (charge_power_w + grid_charge_power) * dt
        if next_energy > battery_energy_max_wh: next_energy = battery_energy_max_wh
        if next_energy < battery_energy_floor_wh: next_energy = battery_energy_floor_wh
        served_power_w = pv_to_load_w + battery_ac_supply_w
        deficit_after_battery_w = max(load_current_w - served_power_w, 0.0)
        if k_cable_batt > 0: power_balance_w = solar_after_pv_cable_w - pv_used_for_load_dc_w - (charge_power_w / k_cable_batt)
        else: power_balance_w = solar_after_pv_cable_w - pv_used_for_load_dc_w
        full_range_filtered_hes_data.at[i, 'pv_to_load_w'] = pv_to_load_w
        full_range_filtered_hes_data.at[i, 'pv_used_for_load_dc_w'] = pv_used_for_load_dc_w
        full_range_filtered_hes_data.at[i, 'pv_surplus_after_load_w'] = pv_surplus_after_load_w
        full_range_filtered_hes_data.at[i, 'battery_charge_available_w'] = battery_charge_available_w
        full_range_filtered_hes_data.at[i, 'battery_charge_power_w'] = charge_power_w
        full_range_filtered_hes_data.at[i, 'battery_discharge_power_w'] = discharge_power_w
        full_range_filtered_hes_data.at[i, 'battery_energy'] = next_energy
        full_range_filtered_hes_data.at[i, 'battery_ac_supply_w'] = battery_ac_supply_w
        full_range_filtered_hes_data.at[i, 'served_power_w'] = served_power_w
        full_range_filtered_hes_data.at[i, 'grid_import_w'] = grid_charge_power
        full_range_filtered_hes_data.at[i, 'grid_energy_step_wh'] = grid_charge_power * dt
        full_range_filtered_hes_data.at[i, 'deficit_after_pv_w'] = deficit_after_pv_w
        full_range_filtered_hes_data.at[i, 'deficit_after_battery_w'] = deficit_after_battery_w
        full_range_filtered_hes_data['balance_no_battery_w'] = full_range_filtered_hes_data['pv_ac_available_w'] - full_range_filtered_hes_data['load_power_current_w']
        full_range_filtered_hes_data['balance_with_battery_w'] = full_range_filtered_hes_data['pv_ac_available_w'] + full_range_filtered_hes_data['battery_ac_supply_w'] - full_range_filtered_hes_data['load_power_current_w']
        # Добавить расчёт накопленной солнечной энергии
        full_range_filtered_hes_data['solar_energy_step_wh'] = full_range_filtered_hes_data['solar_power_after_pv_cable_w'] * full_range_filtered_hes_data['hour_diff']
        full_range_filtered_hes_data['solar_energy'] = full_range_filtered_hes_data['solar_energy_step_wh'].cumsum()

        # Добавить колонку с минимальным порогом энергии АКБ (для графика)
        full_range_filtered_hes_data['battery_min_energy_wh'] = battery_energy_control_min_wh

        # ===================== ДОПОЛНИТЕЛЬНЫЕ РАСЧЁТЫ ДЛЯ ПОЛНОГО ОТЧЁТА =====================
        # (переносим логику из оригинального скрипта)
    
        # --- Проверка совместимости оборудования ---
        total_inv_nominal_power = inverter_nominal_power * n_inverters_required
        inverter_power_ok = total_inv_nominal_power >= required_inverter_power
        battery_voltage_ok = inverter_battery_voltage_min <= battery_bank_voltage <= inverter_battery_voltage_max
        inverter_battery_current_ok = battery_current_per_inv <= inverter_max_battery_discharge_current
        total_battery_discharge_limit_a = battery_parallel_count * battery_nominal_ah * kCharge
        total_required_battery_current_a = battery_current_per_inv * n_inverters_required
        battery_current_ok = total_required_battery_current_a <= total_battery_discharge_limit_a
        usable_battery_energy_wh = battery_energy_max_wh - battery_energy_control_min_wh
        battery_energy_ok = usable_battery_energy_wh >= daily_energy_wh * 1.0  # autonomy days = 1
        pv_panels_min_per_string = math.ceil(max(inverter_mppt_min, inverter_pv_start_voltage) / panel_Vmp)
        pv_panels_max_per_string = math.floor(min(inverter_mppt_max, inverter_pv_max_voltage) / panel_Voc)
        pv_string_voltage_ok = pv_panels_min_per_string <= panels_per_string <= pv_panels_max_per_string
        if best_layout["electrical_ok"] and total_strings:
            strings_per_mppt_actual = math.ceil(total_strings / (n_inverters_required * inverter_mppt_count))
            pv_current_per_mppt = strings_per_mppt_actual * panel_Isc
            pv_current_ok = (pv_current_per_mppt <= inverter_pv_max_current_per_mppt and
                             pv_current_per_mppt <= inverter_pv_max_isc_per_mppt)
        else:
            pv_current_ok = False
        equipment_ok = (inverter_power_ok and battery_voltage_ok and inverter_battery_current_ok and
                        battery_current_ok and battery_energy_ok and pv_string_voltage_ok and pv_current_ok)
    
        # --- Ориентация панелей (оптимальный угол) ---
        tilt_opt, az_opt = optimal_tilt_azimuth(lat)
    
        # --- Периоды дефицита (без учёта АКБ) ---
        mask_deficit = full_range_filtered_hes_data['balance_no_battery_w'] < 0
        if mask_deficit.any():
            group_ids = (mask_deficit != mask_deficit.shift()).cumsum()
            deficit_periods = full_range_filtered_hes_data[mask_deficit].groupby(group_ids[mask_deficit])
            periods_list = []
            total_deficit_energy_wh = 0.0
            for _, period in deficit_periods:
                start_time = period['datetime'].iloc[0]
                end_time   = period['datetime'].iloc[-1]
                energy_wh = (-period['balance_no_battery_w'] * period['hour_diff']).sum()
                periods_list.append({'Начало дефицита': start_time, 'Конец дефицита': end_time, 'Энергия дефицита, Вт·ч': round(energy_wh, 2)})
                total_deficit_energy_wh += energy_wh
            deficit_df = pd.DataFrame(periods_list)
        else:
            deficit_df = pd.DataFrame()
            total_deficit_energy_wh = 0.0
    
        # --- Периоды низкого заряда АКБ ---
        def find_periods_at_or_below_threshold(df, datetime_col, energy_col, limit, eps=1e-9):
            tmp = df[[datetime_col, energy_col]].copy()
            tmp[datetime_col] = pd.to_datetime(tmp[datetime_col], errors='coerce')
            tmp[energy_col] = pd.to_numeric(tmp[energy_col], errors='coerce')
            tmp = tmp.dropna(subset=[datetime_col, energy_col]).sort_values(datetime_col).reset_index(drop=True)
            mask = tmp[energy_col] <= (limit + eps)
            if not mask.any():
                return []
            group_id = (mask != mask.shift()).cumsum()
            periods = []
            for _, g in tmp[mask].groupby(group_id[mask]):
                periods.append((g[datetime_col].iloc[0], g[datetime_col].iloc[-1]))
            return periods
    
        battery_control_min_periods = find_periods_at_or_below_threshold(
            full_range_filtered_hes_data, 'datetime', 'battery_energy', battery_energy_control_min_wh
        )
    
        # --- Подключения к электросети для зарядки АКБ ---
        mask_grid = full_range_filtered_hes_data['grid_import_w'] > 0
        if mask_grid.any():
            group_ids_grid = (mask_grid != mask_grid.shift()).cumsum()
            periods_grid = full_range_filtered_hes_data[mask_grid].groupby(group_ids_grid[mask_grid])
            connections = []
            for _, group in periods_grid:
                start_time = group['datetime'].iloc[0]
                end_time   = group['datetime'].iloc[-1]
                connections.append((start_time, end_time))
            connect_df = pd.DataFrame(connections, columns=['datetime_start', 'datetime_end'])
            connect_df['connection_number'] = range(1, len(connect_df) + 1)
            connect_df = connect_df[['connection_number', 'datetime_start', 'datetime_end']]
        else:
            connect_df = pd.DataFrame()
    
        # --- Дополнительные метрики для раздела "Дефицит и баланс" ---
        peak_pv_deficit_w = full_range_filtered_hes_data['deficit_after_pv_w'].max()
        peak_battery_deficit_w = full_range_filtered_hes_data['deficit_after_battery_w'].max()
        total_grid_energy_wh = full_range_filtered_hes_data['grid_energy_step_wh'].sum()
        total_battery_charge_wh = full_range_filtered_hes_data['battery_charge_power_w'].sum()
        total_battery_discharge_wh = full_range_filtered_hes_data['battery_discharge_power_w'].sum()
    
        # Количество панелей, активная площадь и т.д. (уже есть, но переопределим на всякий случай)
        numberpanel = installed_panels
        panel_active_area_m2 = photoCellWidth * photoCellHigh * photoCellNum
        pv_array_active_area_m2 = panel_active_area_m2 * numberpanel
        battery_series_count = battery_series_count  # уже есть
        battery_parallel_count = battery_parallel_count
        numberbattery = numberbattery_total

    # ---------- 7. Формирование PDF-отчёта (код из оригинала) ----------
    from fpdf import FPDF
    from tabulate import tabulate
    img_dir = '/tmp/report_images'
    os.makedirs(img_dir, exist_ok=True)

    # Функции сохранения графиков
    def save_energy_graph(data, filename):
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(data['datetime'], data['solar_energy'], label='Выработанная', color='blue')
        ax.plot(data['datetime'], data['load_energy_wh'], label='Необходимая', color='orange')
        ax.set_xlabel('Дата'); ax.set_ylabel('Вт·ч')
        ax.set_title('Выработанная и необходимая энергия')
        ax.grid(True); ax.legend()
        fig.tight_layout(); fig.savefig(filename); plt.close(fig)
    def save_battery_balance_graph(data, min_energy, filename):
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(data['datetime'], data['battery_energy'], color='blue')
        ax.axhline(y=min_energy, color='black', linestyle='--', label='Мин. порог')
        ax.set_xlabel('Дата'); ax.set_ylabel('Вт·ч')
        ax.set_title('Баланс энергии в АКБ')
        ax.grid(True); ax.legend()
        fig.tight_layout(); fig.savefig(filename); plt.close(fig)
    def save_charge_discharge_graph(data, filename):
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(data['datetime'], data['battery_charge_power_w'], label='Заряд от PV')
        ax.plot(data['datetime'], data['battery_discharge_power_w'], label='Разряд АКБ')
        ax.set_xlabel('Дата'); ax.set_ylabel('Вт')
        ax.set_title('Заряд и разряд АКБ')
        ax.grid(True); ax.legend()
        fig.tight_layout(); fig.savefig(filename); plt.close(fig)
    def save_grid_import_graph(data, filename):
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(data['datetime'], data['grid_import_w'], color='purple')
        ax.set_xlabel('Дата'); ax.set_ylabel('Вт')
        ax.set_title('Потребление из сети')
        ax.grid(True)
        fig.tight_layout(); fig.savefig(filename); plt.close(fig)
    def save_deficit_graph(data, filename):
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(data['datetime'], data['balance_no_battery_w'], color='red', linewidth=1, label='Без АКБ')
        ax.fill_between(data['datetime'], 0, data['balance_no_battery_w'], where=(data['balance_no_battery_w'] < 0), color='red', alpha=0.3, label='Дефицит без АКБ')
        ax.plot(data['datetime'], data['balance_with_battery_w'], color='green', linestyle='--', label='С АКБ')
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.set_xlabel('Дата'); ax.set_ylabel('Вт')
        ax.set_title('Дефицит генерации PV и покрытие АКБ')
        ax.grid(True); ax.legend()
        fig.tight_layout(); fig.savefig(filename); plt.close(fig)

    # Графики из облачности
    conn1 = sqlite3.connect(solar_flux_file1); df1 = pd.read_sql_query("SELECT * FROM Solar_Flux WHERE datetime BETWEEN ? AND ?", conn1, params=(start_str, end_str)); conn1.close()
    df1['datetime'] = pd.to_datetime(df1['datetime'])
    conn2 = sqlite3.connect(solar_flux_file2); df2 = pd.read_sql_query("SELECT * FROM screenshots WHERE datetime BETWEEN ? AND ?", conn2, params=(start_str, end_str)); conn2.close()
    df2['datetime'] = pd.to_datetime(df2['datetime'])
    conn3 = sqlite3.connect(cloudiness_db_file); df3 = pd.read_sql_query("SELECT * FROM Cloudiness WHERE datetime BETWEEN ? AND ?", conn3, params=(start_str, end_str)); conn3.close()
    df3['datetime'] = pd.to_datetime(df3['datetime'])

    # График 1: Солнечная энергия (df1)
    def save_plot1():
        # Приводим к datetime и фильтруем по периоду
        df1_filtered = df1.copy()
        df1_filtered['datetime'] = pd.to_datetime(df1_filtered['datetime'])
        start_dt = pd.to_datetime(start_str)
        end_dt = pd.to_datetime(end_str)
        df1_filtered = df1_filtered[(df1_filtered['datetime'] >= start_dt) & (df1_filtered['datetime'] <= end_dt)]
        # Удаляем дубликаты по времени и сортируем
        df1_filtered = df1_filtered.drop_duplicates(subset='datetime').sort_values('datetime').reset_index(drop=True)
        
        fig, ax = plt.subplots(figsize=(10,4))
        # Используем plot с маркерами для наглядности (но можно и без)
        ax.plot(df1_filtered['datetime'], df1_filtered['solar_flux'], linestyle='-', linewidth=1)
        ax.set_xlabel('Дата'); ax.set_ylabel('Solar flux (W/m²)')
        ax.set_title('Интенсивность солнечного потока (Clear Sky)')
        ax.grid(True)
        fig.tight_layout()
        fig.savefig(os.path.join(img_dir, 'solar_flux_clear.png'))
        plt.close(fig)
    
    # График 2: Облачность (df2)
    def save_plot2():
        df2f = df2.copy()
        df2f['clouds'] = pd.to_numeric(df2f['clouds'], errors='coerce')
        df2f = df2f.dropna(subset=['clouds'])
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(df2f['datetime'], df2f['clouds'], linestyle='-')
        ax.set_xlabel('Дата'); ax.set_ylabel('Облачность (%)')
        ax.set_title('Уровень облачности')
        ax.grid(True)
        fig.tight_layout(); fig.savefig(os.path.join(img_dir, 'cloudiness.png')); plt.close(fig)
    
    # График 3: Температура (df2)
    def save_plot3():
        df_temp = df2[['datetime', 'temperature']].copy()
        df_temp['temperature'] = pd.to_numeric(df_temp['temperature'], errors='coerce')
        df_temp = df_temp.dropna()
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(df_temp['datetime'], df_temp['temperature'], linestyle='-')
        ax.set_xlabel('Дата'); ax.set_ylabel('Температура (°C)')
        ax.set_title('Температура')
        ax.grid(True)
        fig.tight_layout(); fig.savefig(os.path.join(img_dir, 'temperature.png')); plt.close(fig)
    
    # График 4: Солнечная энергия с учётом облачности (df3)
    def save_plot4():
        df3_filtered = df3.copy()
        df3_filtered['datetime'] = pd.to_datetime(df3_filtered['datetime'])
        start_dt = pd.to_datetime(start_str)
        end_dt = pd.to_datetime(end_str)
        df3_filtered = df3_filtered[(df3_filtered['datetime'] >= start_dt) & (df3_filtered['datetime'] <= end_dt)]
        df3_filtered = df3_filtered.drop_duplicates(subset='datetime').sort_values('datetime').reset_index(drop=True)
        
        fig, ax = plt.subplots(figsize=(10,4))
        ax.plot(df3_filtered['datetime'], df3_filtered['solar_flux'], linestyle='-', linewidth=1)
        ax.set_xlabel('Дата'); ax.set_ylabel('Solar flux (W/m²)')
        ax.set_title('Интенсивность солнечного потока с учётом облачности')
        ax.grid(True)
        fig.tight_layout()
        fig.savefig(os.path.join(img_dir, 'solar_flux_cloudy.png'))
        plt.close(fig)
    
    save_plot1(); save_plot2(); save_plot3(); save_plot4()
    save_energy_graph(full_range_filtered_hes_data, os.path.join(img_dir, 'energy.png'))
    save_battery_balance_graph(full_range_filtered_hes_data, battery_energy_control_min_wh, os.path.join(img_dir, 'battery_balance.png'))
    save_charge_discharge_graph(full_range_filtered_hes_data, os.path.join(img_dir, 'charge_discharge.png'))
    save_grid_import_graph(full_range_filtered_hes_data, os.path.join(img_dir, 'grid_import.png'))
    save_deficit_graph(full_range_filtered_hes_data, os.path.join(img_dir, 'deficit.png'))

    # Создание PDF
    pdf = FPDF()
    pdf.add_page()
    font_path = os.path.join(os.path.dirname(__file__), 'DejaVuSans.ttf')
    pdf.add_font('DejaVu', '', font_path, uni=True)
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 10, 'Отчёт о моделировании солнечной электростанции', ln=True, align='C')
    pdf.ln(5)
    pdf.set_font('DejaVu', '', 10)
    pdf.cell(0, 8, f'Период: {start_str} – {end_str} | Широта {lat}°, долгота {lon}°', ln=True)
    
    # --- Параметры нагрузки ---
    pdf.ln(3)
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Параметры нагрузки', ln=True)
    pdf.set_font('DejaVu', '', 10)
    pdf.cell(0, 6, f'Максимальная нагрузка: {max_load_power_kw:.2f} кВт', ln=True)
    pdf.cell(0, 6, f'Рабочие часы: {max_load_work_hours:.2f} ч', ln=True)
    pdf.cell(0, 6, f'Нагрузка за 1 час: макс {load_power_max_w:.2f} Вт, средняя {load_power_normal_w:.2f} Вт, мин {load_power_min_w:.2f} Вт', ln=True)
    pdf.cell(0, 6, f'Суточная потребность: итого {daily_energy_wh:.2f} Вт·ч', ln=True)
    
    # --- Раскладка панелей ---
    pdf.ln(3)
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Раскладка панелей на крыше', ln=True)
    pdf.set_font('DejaVu', '', 10)
    pdf.cell(0, 6, f'Эффективная площадь панелей: {round(photoCellSquare, 2)} м²', ln=True)
    if isinstance(best_layout, dict):
        pdf.cell(0, 6, f'Ориентация: {best_layout.get("orientation", "N/A")}', ln=True)
        pdf.cell(0, 6, f'Панелей в линии: {best_layout.get("cols_along_length", "N/A")}', ln=True)
        pdf.cell(0, 6, f'Линий по ширине: {best_layout.get("rows_along_width", "N/A")}', ln=True)
        pdf.cell(0, 6, f'Панелей в строке: {best_layout.get("panels_per_string", "N/A")}', ln=True)
        pdf.cell(0, 6, f'Строк на линию: {best_layout.get("strings_per_row", "N/A")}', ln=True)
        pdf.cell(0, 6, f'Всего строк: {best_layout.get("total_strings", "N/A")}', ln=True)
        pdf.cell(0, 6, f'Всего панелей: {best_layout.get("total_panels", "N/A")}', ln=True)
    
    # --- Сбалансированное оборудование ---
    pdf.ln(3)
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Сбалансированное оборудование', ln=True)
    pdf.set_font('DejaVu', '', 10)
    pdf.cell(0, 6, f'Инверторов: {n_inverters_required}', ln=True)
    pdf.cell(0, 6, f'Панелей всего: {installed_panels}, в строке: {panels_per_string}, строк: {total_strings}', ln=True)
    mppt_per_inv = inverter_mppt_count
    strings_per_mppt_calc = math.ceil(total_strings / (n_inverters_required * mppt_per_inv)) if total_strings > 0 else 0
    pdf.cell(0, 6, f'Строк на MPPT: {strings_per_mppt_calc}', ln=True)
    pdf.cell(0, 6, f'Напряжение батарейного банка: {battery_bank_voltage:.2f} В', ln=True)
    pdf.cell(0, 6, f'Параллельных веток на инвертор: {battery_parallel_count_per_inv}, всего в системе: {battery_parallel_count}', ln=True)
    pdf.cell(0, 6, f'Всего аккумуляторов: {numberbattery_total}', ln=True)
    pdf.cell(0, 6, f'Номинальная ёмкость: {nominal_capacity_battery:.2f} А·ч', ln=True)
    pdf.cell(0, 6, f'Доступная ёмкость: {batteryCapacityLim:.2f} А·ч', ln=True)
    pdf.cell(0, 6, f'Фактическая ёмкость: {batteryCapacity:.2f} А·ч', ln=True)
    pdf.cell(0, 6, f'Минимально допустимая ёмкость: {battery_DoD:.2f} А·ч', ln=True)
    pdf.cell(0, 6, f'Энергия банка: {battery_energy_floor_wh:.2f}..{battery_energy_max_wh:.2f} Вт·ч', ln=True)
    
    # --- Проверка совместимости ---
    pdf.ln(3)
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Проверка совместимости', ln=True)
    pdf.set_font('DejaVu', '', 10)
    if 'equipment_ok' in globals():
        pdf.cell(0, 6, f'ВЫВОД: {"связка рабочая" if equipment_ok else "связка НЕ ПРОХОДИТ проверку"}', ln=True)
    
    # --- Ориентация солнечных панелей ---
    pdf.ln(3)
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Ориентация солнечных панелей', ln=True)
    pdf.set_font('DejaVu', '', 10)
    pdf.cell(0, 6, f'Оптимальная ориентация для широты {lat}°:', ln=True)
    pdf.cell(0, 6, f'  Угол наклона: {tilt_opt:.1f}°', ln=True)
    pdf.cell(0, 6, f'  Азимут: {az_opt:.1f}° (0=север, 180=юг)', ln=True)
    
  # --- Дефицит и баланс ---
    pdf.add_page()
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Дефицит и баланс', ln=True)
    pdf.set_font('DejaVu', '', 10)
    
    daily_actual = full_range_filtered_hes_data['load_energy_step_wh'].sum()
    pdf.cell(0, 6, f'Количество панелей: {numberpanel}', ln=True)
    pdf.cell(0, 6, f'Активная площадь массива: {pv_array_active_area_m2:.2f} м²', ln=True)
    pdf.cell(0, 6, f'Активная площадь одной панели: {panel_active_area_m2:.3f} м²', ln=True)
    pdf.cell(0, 6, f'Модулей АКБ в серии: {battery_series_count}, параллельных веток: {battery_parallel_count}, всего АКБ: {numberbattery}', ln=True)
    pdf.cell(0, 6, f'Напряжение банка: {battery_bank_voltage:.2f} В', ln=True)
    pdf.cell(0, 6, f'Доступная ёмкость: {batteryCapacityLim:.2f} А·ч, фактическая: {batteryCapacity:.2f} А·ч', ln=True)
    pdf.cell(0, 6, f'Мин. допустимая (контроль): {battery_DoD:.2f} А·ч', ln=True)
    pdf.cell(0, 6, f'Контрольный минимум энергии: {battery_energy_control_min_wh:.2f} Вт·ч', ln=True)
    pdf.cell(0, 6, f'Диапазон энергии АКБ: {battery_energy_floor_wh:.2f}..{battery_energy_max_wh:.2f} Вт·ч', ln=True)
    pdf.cell(0, 6, f'Суточная энергия нагрузки: {daily_actual:.2f} Вт·ч', ln=True)
    pdf.cell(0, 6, f'Макс. дефицит после PV: {peak_pv_deficit_w:.2f} Вт', ln=True)
    pdf.cell(0, 6, f'Макс. дефицит после АКБ: {peak_battery_deficit_w:.2f} Вт', ln=True)
    pdf.cell(0, 6, f'Потребление из сети: {total_grid_energy_wh:.2f} Вт·ч', ln=True)
    pdf.cell(0, 6, f'Суммарный заряд АКБ: {total_battery_charge_wh:.2f} Вт, разряд: {total_battery_discharge_wh:.2f} Вт', ln=True)
    if len(full_range_filtered_hes_data) > 0:
        start_e = full_range_filtered_hes_data.iloc[0]['battery_energy']
        end_e = full_range_filtered_hes_data.iloc[-1]['battery_energy']
        pdf.cell(0, 6, f'Начальный заряд: {start_e:.2f} Вт·ч, конечный: {end_e:.2f} Вт·ч', ln=True)
    
    # --- Графики (все) ---
    pdf.add_page()
    pdf.set_font('DejaVu', '', 12)
    pdf.cell(0, 8, 'Графики', ln=True)
    pdf.ln(2)
    
    graphs = [
        ('solar_flux_clear.png', 'Солнечный поток (Clear Sky)'),
        ('cloudiness.png', 'Облачность'),
        ('temperature.png', 'Температура'),
        ('solar_flux_cloudy.png', 'Солнечный поток с учётом облачности'),
        ('energy.png', 'Выработанная и необходимая энергия'),
        ('battery_balance.png', 'Баланс энергии в АКБ'),
        ('charge_discharge.png', 'Заряд и разряд АКБ'),
        ('grid_import.png', 'Потребление из сети'),
        ('deficit.png', 'Дефицит и покрытие АКБ'),
    ]
    
    for fname, title in graphs:
        path = os.path.join(img_dir, fname)
        if os.path.exists(path):
            pdf.set_font('DejaVu', '', 10)
            pdf.cell(0, 6, title, ln=True)
            pdf.image(path, x=10, w=190)
            pdf.ln(4)
    
    # --- Периоды дефицита (без АКБ) ---
    if 'deficit_df' in globals() and not deficit_df.empty:
        pdf.add_page()
        pdf.set_font('DejaVu', '', 12)
        pdf.cell(0, 8, 'Периоды дефицита энергии (без учёта АКБ)', ln=True)
        pdf.set_font('DejaVu', '', 8)
        pdf.multi_cell(0, 5, tabulate(deficit_df, headers='keys', tablefmt='grid', showindex=False))
        pdf.ln(2)
        pdf.set_font('DejaVu', '', 10)
        if 'total_deficit_energy_wh' in globals():
            pdf.cell(0, 6, f'Суммарный дефицит: {total_deficit_energy_wh:.2f} Вт·ч', ln=True)
    
    # --- Низкий заряд АКБ ---
    if 'battery_control_min_periods' in globals():
        pdf.ln(3)
        pdf.cell(0, 6, f'Периодов с энергией АКБ <= {battery_energy_control_min_wh:.2f} Вт·ч: {len(battery_control_min_periods)}', ln=True)
    
    # --- Подключения к сети ---
    if 'connect_df' in globals() and not connect_df.empty:
        pdf.ln(3)
        pdf.set_font('DejaVu', '', 12)
        pdf.cell(0, 8, 'Подключения к электросети для зарядки АКБ', ln=True)
        pdf.set_font('DejaVu', '', 8)
        pdf.multi_cell(0, 5, tabulate(connect_df, headers='keys', tablefmt='grid', showindex=False))

    pdf_output_path = os.path.join(LOCAL_BASE_PATH, 'отчёт_моделирования.pdf')
    pdf.output(pdf_output_path)
    return pdf_output_path, full_range_filtered_hes_data
