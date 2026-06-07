import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os

from solar_calc import run_simulation

st.set_page_config(page_title="Солнечная электростанция", layout="wide")

st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #2b1b4e 0%, #5b4c7a 30%, #e0c3b0 70%, #f9e4b7 100%); background-attachment: fixed; }
    .stButton > button { background-color: rgba(28,4,123,0.2); border: 2px solid #1c047b; border-radius: 30px; color: #1c047b; font-weight: bold; }
    .stButton > button:hover { background-color: rgba(28,4,123,0.4); }
    
    /* Убираем фон у st.info, текст делаем тёмно-синим */
    div[data-testid="stAlert"] {
        background-color: transparent !important;
        border-left-color: #1c047b !important;
        color: #1c047b !important;
    }
    div[data-testid="stAlert"] .stMarkdown {
        color: #1c047b !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------- ФУНКЦИЯ ЯНДЕКС.КАРТЫ ----------
def yandex_map_picker(lat, lon, zoom=10, map_height=500):
    """
    Отображает Яндекс.Карту с перетаскиваемым маркером.
    При нажатии кнопки координаты передаются через query params.
    """
    map_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://api-maps.yandex.ru/2.1/?apikey=6a8e96f6-7181-4031-aa17-e187f6cc0843&lang=ru_RU"></script>
        <style>
            html, body, #map {{ width: 100%; height: {map_height}px; margin: 0; padding: 0; }}
            .btn {{
                display: block;
                width: 100%;
                padding: 10px;
                margin-top: 10px;
                background-color: #1c047b;
                color: white;
                font-size: 16px;
                border: none;
                border-radius: 10px;
                cursor: pointer;
            }}
        </style>
    </head>
    <body>
        <div id="map"></div>
        <button class="btn" id="applyCoords">✅ Применить координаты в приложении</button>
        <script>
            var currentCoords = {{ lat: {lat}, lon: {lon} }};
            var map = null;
            var placemark = null;

            function init() {{
                map = new ymaps.Map("map", {{
                    center: [{lat}, {lon}],
                    zoom: {zoom},
                    controls: ["zoomControl", "fullscreenControl"]
                }});

                placemark = new ymaps.Placemark([{lat}, {lon}], {{
                    hintContent: "Выбранная точка"
                }}, {{
                    draggable: true
                }});

                map.geoObjects.add(placemark);

                placemark.events.add("dragend", function (e) {{
                    var coords = placemark.geometry.getCoordinates();
                    currentCoords = {{ lat: coords[0], lon: coords[1] }};
                }});

                map.events.add("click", function (e) {{
                    var coords = e.get("coords");
                    currentCoords = {{ lat: coords[0], lon: coords[1] }};
                    placemark.geometry.setCoordinates(coords);
                }});
            }}

            document.getElementById("applyCoords").addEventListener("click", function() {{
                var newUrl = window.location.protocol + "//" + window.location.host + window.location.pathname +
                            "?lat=" + currentCoords.lat.toFixed(6) + "&lon=" + currentCoords.lon.toFixed(6);
                window.location.href = newUrl;
            }});

            ymaps.ready(init);
        </script>
    </body>
    </html>
    """
    st.components.v1.html(map_html, height=map_height + 60)

# ---------- ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ ----------
if 'lat' not in st.session_state:
    st.session_state.lat = 50.739537
if 'lon' not in st.session_state:
    st.session_state.lon = 136.567232
if 'show_map' not in st.session_state:
    st.session_state.show_map = True
if 'calculation_done' not in st.session_state:
    st.session_state.calculation_done = False

# ---------- ПОЛУЧЕНИЕ КООРДИНАТ ИЗ URL (ПОСЛЕ НАЖАТИЯ КНОПКИ НА КАРТЕ) ----------
query_params = st.query_params
if 'lat' in query_params and 'lon' in query_params:
    try:
        new_lat = float(query_params['lat'])
        new_lon = float(query_params['lon'])
        # Обновляем session_state
        st.session_state.lat = new_lat
        st.session_state.lon = new_lon
        # Очищаем параметры, чтобы не применялись повторно
        st.query_params.clear()
        st.rerun()
    except:
        pass

# ---------- БОКОВАЯ ПАНЕЛЬ (все параметры) ----------
with st.sidebar:
    st.title("⚙️ Параметры системы")
    st.markdown("---")
    
    # 1. Местоположение и даты
    st.subheader("📍 Местоположение")
    lat = st.number_input("Широта", value=st.session_state.lat, format="%.6f")
    lon = st.number_input("Долгота", value=st.session_state.lon, format="%.6f")
    tz = st.selectbox("Часовой пояс", ["Asia/Vladivostok", "Europe/Moscow", "Asia/Yekaterinburg", "UTC"], index=0)
    
    st.subheader("📅 Период моделирования")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Дата начала", datetime(2026, 1, 1))
    with col2:
        end_date = st.date_input("Дата окончания", datetime(2026, 1, 7))
    start_str = start_date.strftime("%Y-%m-%dT00:00")
    end_str = end_date.strftime("%Y-%m-%dT23:59")
    
    # 2. Нагрузка
    st.subheader("🔌 Параметры нагрузки")
    max_load_power_kw = st.number_input("Максимальная нагрузка системы (кВт·ч)", value=175.0)
    max_load_work_hours = st.number_input("Рабочие часы предприятия (ч)", value=9.0)
    st.markdown("**Часы нагрузки (0-23)**")
    c1, c2 = st.columns(2)
    with c1:
        load_min_start = st.number_input("Начало мин. нагрузки", value=0, min_value=0, max_value=23, key="min_start")
        load_min_end = st.number_input("Конец мин. нагрузки", value=8, min_value=0, max_value=24, key="min_end")
    with c2:
        load_max_start = st.number_input("Начало макс. нагрузки", value=8, min_value=0, max_value=23, key="max_start")
        load_max_end = st.number_input("Конец макс. нагрузки", value=13, min_value=0, max_value=24, key="max_end")
    load_normal_start = st.number_input("Начало обычной нагрузки", value=13, min_value=0, max_value=23)
    load_normal_end = st.number_input("Конец обычной нагрузки", value=24, min_value=0, max_value=24)
    
    # 3. Панель
    st.subheader("☀️ Солнечная панель")
    photoEfficiency = st.number_input("КПД панели (0..1)", value=0.23, format="%.3f")
    k_photoEffTemp = st.number_input("Температурный коэффициент (%/°C)", value=-0.0029, format="%.4f")
    photoNOCT = st.number_input("NOCT (°C)", value=43.0)
    panel_Vmp = st.number_input("Рабочее напр-е (В)", value=45.40)
    panel_Voc = st.number_input("Напр-е холостого хода (В)", value=53.80)
    panel_Imp = st.number_input("Ток к точке макс. мощности (А)", value=10.14)
    panel_Isc = st.number_input("Ток короткого замыкания (А)", value=10.81)
    photoCellWidth = st.number_input("Ширина ячейки (м)", value=0.210)
    photoCellHigh = st.number_input("Высота ячейки (м)", value=0.210)
    photoCellNum = st.number_input("Количество ячеек", value=144, step=1)
    
    # 4. Аккумулятор
    st.subheader("🔋 Аккумулятор")
    numberbattery_1 = st.number_input("Начальное кол-во АКБ", value=1, step=1)
    charge_voltage = st.number_input("Напряжение заряда (В)", value=57.6)
    battery_nominal_ah = st.number_input("Ёмкость одного АКБ (А·ч)", value=100.0)
    battery_voltage = st.number_input("Рабочее напряжение (В)", value=51.2)
    k_min_SoC = st.number_input("Мин. SoC (0..1)", value=0.1, format="%.2f")
    k_mode_battery = st.number_input("Коэфф. доступной ёмкости", value=0.8)
    kCharge = st.number_input("Макс. ток заряда (от ёмкости)", value=0.3)
    
    # 5. Инвертор
    st.subheader("⚡ Инвертор")
    inverter_nominal_power = st.number_input("Номинальная мощность (кВт)", value=25.0)
    inverter_efficiency = st.number_input("КПД (0..1)", value=0.976, format="%.3f")
    inverter_battery_voltage_nominal = st.number_input("Ном. напряжение АКБ (В)", value=400)
    inverter_battery_voltage_min = st.number_input("Мин. напряжение АКБ (В)", value=160)
    inverter_battery_voltage_max = st.number_input("Макс. напряжение АКБ (В)", value=700)
    inverter_max_battery_charge_current = st.number_input("Макс. ток заряда (А)", value=50.0)
    inverter_max_battery_discharge_current = st.number_input("Макс. ток разряда (А)", value=50.0)
    inverter_mppt_min = st.number_input("Мин. MPPT напряжение (В)", value=150)
    inverter_mppt_max = st.number_input("Макс. MPPT напряжение (В)", value=850)
    inverter_pv_max_voltage = st.number_input("Макс. входное PV (В)", value=1000)
    inverter_pv_start_voltage = st.number_input("Пусковое PV (В)", value=180)
    inverter_mppt_count = st.number_input("Кол-во MPPT", value=2, step=1)
    inverter_pv_nominal_power = st.number_input("Ном. входная PV мощность (Вт)", value=40000)
    inverter_pv_max_current_per_mppt = st.number_input("Макс. ток на MPPT (А)", value=26.0)
    inverter_pv_max_isc_per_mppt = st.number_input("Макс. Isc на MPPT (А)", value=39.0)
    max_inverters_in_parallel = st.number_input("Макс. инверторов параллельно", value=10, step=1)
    
    # 6. Потери и запас
    st.subheader("📉 Потери")
    k_cable_pv = st.number_input("Потери DC кабель (0..1)", value=0.97, format="%.2f")
    k_cable_batt = st.number_input("Потери кабель АКБ", value=0.98)
    k_cable_ac = st.number_input("Потери AC сторона", value=0.99)
    reserve_factor_inverter = st.number_input("Запас мощности инвертора", value=1.2)
    
    # 7. Размеры крыши
    st.subheader("🏠 Размер крыши")
    roof_length = st.number_input("Длина крыши (м)", value=30.0)
    roof_width = st.number_input("Ширина крыши (м)", value=30.0)
    
    # Начальный SOC
    initial_battery_soc = st.slider("Начальный заряд АКБ (%)", 0, 100, 60) / 100.0

# ---------- ОСНОВНАЯ ОБЛАСТЬ ----------
st.markdown("# 🌞 Моделирование солнечной электростанции")
st.markdown("### Заполните параметры в боковой панели, затем нажмите кнопку ниже")

if st.button("🚀 ЗАПУСТИТЬ РАСЧЁТ", use_container_width=True):
    st.session_state.show_map = False
    params = {
        'lat': lat, 'lon': lon, 'timezone': tz,
        'start_date': start_str, 'end_date': end_str,
        'max_load_power_kw': max_load_power_kw, 'max_load_work_hours': max_load_work_hours,
        'load_min_start_hour': load_min_start, 'load_min_end_hour': load_min_end,
        'load_max_start_hour': load_max_start, 'load_max_end_hour': load_max_end,
        'load_normal_start_hour': load_normal_start, 'load_normal_end_hour': load_normal_end,
        'photoEfficiency': photoEfficiency, 'k_photoEffTemp': k_photoEffTemp, 'photoNOCT': photoNOCT,
        'panel_Vmp': panel_Vmp, 'panel_Voc': panel_Voc, 'panel_Imp': panel_Imp, 'panel_Isc': panel_Isc,
        'photoCellWidth': photoCellWidth, 'photoCellHigh': photoCellHigh, 'photoCellNum': photoCellNum,
        'numberbattery_1': numberbattery_1, 'charge_voltage': charge_voltage,
        'battery_nominal_ah': battery_nominal_ah, 'battery_voltage': battery_voltage,
        'k_min_SoC': k_min_SoC, 'k_mode_battery': k_mode_battery, 'kCharge': kCharge,
        'inverter_nominal_power': inverter_nominal_power, 'inverter_efficiency': inverter_efficiency,
        'inverter_battery_voltage_nominal': inverter_battery_voltage_nominal,
        'inverter_battery_voltage_min': inverter_battery_voltage_min,
        'inverter_battery_voltage_max': inverter_battery_voltage_max,
        'inverter_max_battery_charge_current': inverter_max_battery_charge_current,
        'inverter_max_battery_discharge_current': inverter_max_battery_discharge_current,
        'inverter_mppt_min': inverter_mppt_min, 'inverter_mppt_max': inverter_mppt_max,
        'inverter_pv_max_voltage': inverter_pv_max_voltage,
        'inverter_pv_start_voltage': inverter_pv_start_voltage,
        'inverter_mppt_count': inverter_mppt_count,
        'inverter_pv_nominal_power': inverter_pv_nominal_power,
        'inverter_pv_max_current_per_mppt': inverter_pv_max_current_per_mppt,
        'inverter_pv_max_isc_per_mppt': inverter_pv_max_isc_per_mppt,
        'max_inverters_in_parallel': max_inverters_in_parallel,
        'k_cable_pv': k_cable_pv, 'k_cable_batt': k_cable_batt, 'k_cable_ac': k_cable_ac,
        'reserve_factor_inverter': reserve_factor_inverter,
        'roof_length': roof_length, 'roof_width': roof_width,
        'initial_battery_soc': initial_battery_soc
    }
    with st.spinner("Идёт расчёт (может занять несколько минут)..."):
        try:
            pdf_path, df_results = run_simulation(params)
            st.session_state['pdf_path'] = pdf_path
            st.session_state['df_results'] = df_results
            st.session_state['calculation_done'] = True
            st.success("✅ Расчёт завершён!")
        except Exception as e:
            st.error(f"Ошибка при расчёте: {e}")

# ---------- КАРТА (показываем только до расчёта) ----------
if not st.session_state.calculation_done and st.session_state.show_map:
    st.subheader("🗺️ Яндекс.Карта – выберите точку")
    yandex_map_picker(
        lat=st.session_state.lat,
        lon=st.session_state.lon,
        zoom=10
    )
    st.caption("💡 Передвиньте маркер или кликните по карте, затем нажмите кнопку «Применить координаты»")

# ---------- ОТОБРАЖЕНИЕ РЕЗУЛЬТАТОВ ----------
if st.session_state.get('calculation_done', False):
    df = st.session_state['df_results']
    st.subheader("📊 Результаты моделирования")
    
    col_gr1, col_gr2 = st.columns(2)
    fig1, ax = plt.subplots(figsize=(8,4))
    ax.plot(df['datetime'], df['solar_energy'], label='Выработанная', color='blue')
    ax.plot(df['datetime'], df['load_energy_wh'], label='Необходимая', color='orange')
    ax.set_xlabel('Дата'); ax.set_ylabel('Вт·ч')
    ax.set_title('Выработанная и необходимая энергия')
    ax.grid(True); ax.legend()
    col_gr1.pyplot(fig1)
    
    fig2, ax = plt.subplots(figsize=(8,4))
    ax.plot(df['datetime'], df['battery_energy'], color='blue')
    ax.axhline(y=df['battery_min_energy_wh'].iloc[0], color='black', linestyle='--', label='Мин. порог')
    ax.set_xlabel('Дата'); ax.set_ylabel('Вт·ч')
    ax.set_title('Энергия в АКБ')
    ax.grid(True); ax.legend()
    col_gr2.pyplot(fig2)
    
    col_gr3, col_gr4 = st.columns(2)
    fig3, ax = plt.subplots(figsize=(8,4))
    ax.plot(df['datetime'], df['battery_charge_power_w'], label='Заряд от PV')
    ax.plot(df['datetime'], df['battery_discharge_power_w'], label='Разряд АКБ')
    ax.set_xlabel('Дата'); ax.set_ylabel('Вт')
    ax.set_title('Заряд и разряд АКБ')
    ax.grid(True); ax.legend()
    col_gr3.pyplot(fig3)
    
    fig4, ax = plt.subplots(figsize=(8,4))
    ax.plot(df['datetime'], df['balance_no_battery_w'], color='red', label='Баланс без АКБ')
    ax.fill_between(df['datetime'], 0, df['balance_no_battery_w'], where=(df['balance_no_battery_w']<0), color='red', alpha=0.3)
    ax.plot(df['datetime'], df['balance_with_battery_w'], color='green', linestyle='--', label='С АКБ')
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_xlabel('Дата'); ax.set_ylabel('Вт')
    ax.set_title('Дефицит генерации')
    ax.grid(True); ax.legend()
    col_gr4.pyplot(fig4)
    
    st.subheader("📈 Сводная статистика")
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Пиковый дефицит (после АКБ)", f"{df['deficit_after_battery_w'].max():.1f} Вт")
    col_s2.metric("Суммарное потребление из сети", f"{df['grid_energy_step_wh'].sum():.1f} Вт·ч")
    col_s3.metric("Конечный заряд АКБ", f"{df['battery_energy'].iloc[-1]:.1f} Вт·ч")
    
    with open(st.session_state['pdf_path'], 'rb') as f:
        pdf_bytes = f.read()
    st.download_button(
        label="📥 Скачать PDF-отчёт",
        data=pdf_bytes,
        file_name="отчёт_моделирования.pdf",
        mime="application/pdf",
        use_container_width=True
    )
else:
    st.markdown('<p style="color: #1c047b; background-color: transparent; margin: 10px 0;">📌 Введите все параметры и нажмите «ЗАПУСТИТЬ РАСЧЁТ»</p>', unsafe_allow_html=True)
