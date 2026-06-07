import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os
import json

from solar_calc import run_simulation

st.set_page_config(page_title="Солнечная электростанция", layout="wide")

# Стили (кнопки бело-серые)
st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #2b1b4e 0%, #5b4c7a 30%, #e0c3b0 70%, #f9e4b7 100%); background-attachment: fixed; }
    
    .stButton > button {
        background-color: #f8f9fa;
        border: 2px solid #1c047b;
        border-radius: 30px;
        color: #1c047b;
        font-weight: bold;
        transition: 0.2s;
    }
    .stButton > button:hover {
        background-color: #e9ecef;
        border-color: #0a0138;
        color: #0a0138;
    }
    
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

# ---------- КОМПОНЕНТ ЯНДЕКС.КАРТЫ С ОБРАТНОЙ СВЯЗЬЮ ----------
def yandex_map_with_callback(lat, lon, zoom=10, map_height=500):
    """
    Отображает Яндекс.Карту с перетаскиваемым маркером.
    При клике на карту или перетаскивании маркера координаты отправляются обратно в Streamlit.
    """
    component_id = "yandex_map"
    component_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://api-maps.yandex.ru/2.1/?apikey=6a8e96f6-7181-4031-aa17-e187f6cc0843&lang=ru_RU"></script>
        <style>
            html, body, #map {{ width: 100%; height: {map_height}px; margin: 0; padding: 0; }}
        </style>
    </head>
    <body>
        <div id="map"></div>
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

                function sendCoords() {{
                    var coords = placemark.geometry.getCoordinates();
                    var data = {{ lat: coords[0], lon: coords[1] }};
                    // Отправляем данные обратно в Streamlit
                    Streamlit.setComponentValue(JSON.stringify(data));
                }}

                placemark.events.add("dragend", function (e) {{
                    var coords = placemark.geometry.getCoordinates();
                    currentCoords = {{ lat: coords[0], lon: coords[1] }};
                    sendCoords();
                }});

                map.events.add("click", function (e) {{
                    var coords = e.get("coords");
                    currentCoords = {{ lat: coords[0], lon: coords[1] }};
                    placemark.geometry.setCoordinates(coords);
                    sendCoords();
                }});

                // Принудительно отправляем начальные координаты
                sendCoords();
            }}

            ymaps.ready(init);
        </script>
    </body>
    </html>
    """
    # Возвращаем значение из компонента
    from streamlit.components.v1 import components
    return components.declare_component(component_id, html=component_html)

# Регистрируем компонент
yandex_map = yandex_map_with_callback

# ---------- ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ ----------
if 'lat' not in st.session_state:
    st.session_state.lat = 50.739537   # Холдоми
if 'lon' not in st.session_state:
    st.session_state.lon = 136.567232
if 'show_map' not in st.session_state:
    st.session_state.show_map = True
if 'calculation_done' not in st.session_state:
    st.session_state.calculation_done = False

# ---------- БОКОВАЯ ПАНЕЛЬ ----------
with st.sidebar:
    st.title("⚙️ Параметры системы")
    st.markdown("---")
    
    st.subheader("📍 Местоположение")
    lat = st.number_input("Широта", value=st.session_state.lat, format="%.6f")
    lon = st.number_input("Долгота", value=st.session_state.lon, format="%.6f")
    
    if st.button("🌄 Сбросить координаты"):
        st.session_state.lat = 50.739537
        st.session_state.lon = 136.567232
        st.rerun()
    
    tz = st.selectbox("Часовой пояс", ["Asia/Vladivostok", "Europe/Moscow", "Asia/Yekaterinburg", "UTC"], index=0)
    
    # ... (остальные поля без изменений) ...
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
    params = { ... }  # собираем параметры как раньше
    with st.spinner("Идёт расчёт..."):
        try:
            pdf_path, df_results = run_simulation(params)
            st.session_state['pdf_path'] = pdf_path
            st.session_state['df_results'] = df_results
            st.session_state['calculation_done'] = True
            st.success("✅ Расчёт завершён!")
        except Exception as e:
            st.error(f"Ошибка: {e}")

# ---------- КАРТА (показываем до расчёта) ----------
if not st.session_state.calculation_done and st.session_state.show_map:
    st.subheader("🗺️ Яндекс.Карта – выберите точку")
    # Вызываем компонент и получаем координаты
    map_value = yandex_map(lat=st.session_state.lat, lon=st.session_state.lon)
    if map_value:
        try:
            data = json.loads(map_value)
            new_lat = data['lat']
            new_lon = data['lon']
            if abs(new_lat - st.session_state.lat) > 1e-6 or abs(new_lon - st.session_state.lon) > 1e-6:
                st.session_state.lat = new_lat
                st.session_state.lon = new_lon
                st.rerun()  # обновляем поля ввода
        except:
            pass
    st.caption("💡 Передвиньте маркер или кликните по карте – координаты обновятся автоматически")

# ---------- РЕЗУЛЬТАТЫ ----------
if st.session_state.get('calculation_done', False):
    # ... отображение графиков и PDF ...
    pass
else:
    st.markdown('<p style="color: #1c047b; background-color: transparent;">📌 Введите все параметры и нажмите «ЗАПУСТИТЬ РАСЧЁТ»</p>', unsafe_allow_html=True)
