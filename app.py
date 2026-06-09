import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os
from streamlit_folium import st_folium
import folium 
from folium.plugins import Geocoder
from folium.elements import Element
from folium import DivIcon

from solar_calc import run_simulation

st.set_page_config(page_title="Солнечная электростанция", layout="wide")

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #2b1b4e 0%, #5b4c7a 30%, #e0c3b0 70%, #f9e4b7 100%);
        background-attachment: fixed;
    }
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
    .coord-text {
        background-color: rgba(255,255,255,0.7);
        padding: 8px 15px;
        border-radius: 15px;
        font-family: monospace;
        font-size: 16px;
        text-align: center;
        margin-top: 10px;
        color: #1c047b;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ---------- ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ ----------
if 'lat' not in st.session_state:
    st.session_state.lat = 50.739537
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
    lat_input = st.number_input("Широта", value=st.session_state.lat, format="%.6f")
    lon_input = st.number_input("Долгота", value=st.session_state.lon, format="%.6f")
    if lat_input != st.session_state.lat or lon_input != st.session_state.lon:
        st.session_state.lat = lat_input
        st.session_state.lon = lon_input
        st.rerun()
    
    if st.button("🌄 Сбросить координаты"):
        st.session_state.lat = 50.739537
        st.session_state.lon = 136.567232
        st.rerun()
    
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
    roof_length = st.number_input("Длина крыши (м)", value=25.0)
    roof_width = st.number_input("Ширина крыши (м)", value=25.0)
    
    # Начальный SOC
    initial_battery_soc = st.slider("Начальный заряд АКБ (%)", 0, 100, 50) / 100.0

# ---------- ОСНОВНАЯ ОБЛАСТЬ ----------
st.markdown("# 🌞 Моделирование солнечной электростанции")
st.markdown("### Заполните параметры в боковой панели, затем нажмите кнопку ниже")

def validate_inputs(params_dict):
    """Возвращает список строк с ошибками. Если пуст – валидация пройдена."""
    errors = []
    
    # 1. Даты
    start = datetime.strptime(params_dict['start_date'][:10], "%Y-%m-%d")
    end   = datetime.strptime(params_dict['end_date'][:10], "%Y-%m-%d")
    if start > end:
        errors.append("❌ Дата начала не может быть позже даты окончания. Исправьте период моделирования.")
    
    # 2. Координаты и пояс (проверка попадания в допустимые диапазоны)
    if not (-90 <= params_dict['lat'] <= 90):
        errors.append("❌ Широта должна быть от -90 до 90.")
    if not (-180 <= params_dict['lon'] <= 180):
        errors.append("❌ Долгота должна быть от -180 до 180.")
    
    # 3. Положительные значения для мощностей, напряжений, токов
    positive_fields = {
        'max_load_power_kw': 'Макс. нагрузка (кВт)',
        'max_load_work_hours': 'Рабочие часы',
        'battery_nominal_ah': 'Ёмкость АКБ (А·ч)',
        'battery_voltage': 'Рабочее напряжение АКБ (В)',
        'charge_voltage': 'Напряжение заряда (В)',
        'inverter_nominal_power': 'Номинальная мощность инвертора (кВт)',
        'inverter_battery_voltage_nominal': 'Ном. напряжение АКБ инвертора (В)',
        'inverter_battery_voltage_min': 'Мин. напряжение АКБ инвертора (В)',
        'inverter_battery_voltage_max': 'Макс. напряжение АКБ инвертора (В)',
        'inverter_max_battery_charge_current': 'Макс. ток заряда (А)',
        'inverter_max_battery_discharge_current': 'Макс. ток разряда (А)',
        'inverter_mppt_min': 'Мин. MPPT напряжение (В)',
        'inverter_mppt_max': 'Макс. MPPT напряжение (В)',
        'inverter_pv_max_voltage': 'Макс. входное PV (В)',
        'inverter_pv_start_voltage': 'Пусковое PV (В)',
        'inverter_pv_nominal_power': 'Ном. входная PV мощность (Вт)',
        'inverter_pv_max_current_per_mppt': 'Макс. ток на MPPT (А)',
        'inverter_pv_max_isc_per_mppt': 'Макс. Isc на MPPT (А)',
        'numberbattery_1': 'Начальное кол-во АКБ',
        'photoNOCT': 'NOCT (°C)',
        'roof_length': 'Длина крыши (м)',
        'roof_width': 'Ширина крыши (м)',
        'panel_Vmp': 'Рабочее напряжение панели (В)',
        'panel_Voc': 'Напр. холостого хода (В)',
        'panel_Imp': 'Ток в точке макс. мощности (А)',
        'panel_Isc': 'Ток КЗ (А)',
        'photoCellWidth': 'Ширина ячейки (м)',
        'photoCellHigh': 'Высота ячейки (м)',
        'photoCellNum': 'Количество ячеек',
    }
    for field, label in positive_fields.items():
        if params_dict[field] <= 0:
            errors.append(f"❌ {label} должно быть положительным числом.")
    
    # 4. Коэффициенты (0..1)
    ratio_fields = {
        'photoEfficiency': 'КПД панели',
        'k_min_SoC': 'Мин. SoC',
        'k_mode_battery': 'Коэфф. доступной ёмкости',
        'inverter_efficiency': 'КПД инвертора',
        'k_cable_pv': 'Потери DC кабель',
        'k_cable_batt': 'Потери кабель АКБ',
        'k_cable_ac': 'Потери AC сторона',
        'reserve_factor_inverter': 'Запас мощности инвертора',
    }
    for field, label in ratio_fields.items():
        val = params_dict[field]
        if not (0 < val <= 1):   # reserve_factor обычно >1, но он тоже ограничен 0..1 в виджете? В исходном коде нет min/max, но по логике запас не меньше 1. Валидацию поправим отдельно.
            if field == 'reserve_factor_inverter':
                if val < 1:
                    errors.append(f"❌ Запас мощности инвертора должен быть ≥1.")
            else:
                errors.append(f"❌ {label} должно быть в диапазоне (0, 1].")
    
    # 5. Температурный коэффициент (отрицательный, обычно от -0.01 до 0)
    if not (-1 <= params_dict['k_photoEffTemp'] <= 0):
        errors.append("❌ Температурный коэффициент должен быть отрицательным (например, -0.0029).")
    
    # 6. Ток заряда АКБ (kCharge) – положительный, обычно до 1
    if not (0 < params_dict['kCharge'] <= 1):
        errors.append("❌ Макс. ток заряда (от ёмкости) должен быть в (0, 1].")
    
    # 7. Логические пары «min < max»
    if params_dict['inverter_battery_voltage_min'] >= params_dict['inverter_battery_voltage_max']:
        errors.append("❌ Мин. напряжение АКБ инвертора должно быть меньше максимального.")
    if params_dict['inverter_mppt_min'] >= params_dict['inverter_mppt_max']:
        errors.append("❌ Мин. MPPT напряжение должно быть меньше максимального.")
    if params_dict['inverter_pv_start_voltage'] >= params_dict['inverter_pv_max_voltage']:
        errors.append("❌ Пусковое PV напряжение должно быть меньше максимального входного PV.")
    
    # Номинальное напряжение АКБ инвертора должно лежать между min и max
    nom = params_dict['inverter_battery_voltage_nominal']
    vmin = params_dict['inverter_battery_voltage_min']
    vmax = params_dict['inverter_battery_voltage_max']
    if not (vmin < nom < vmax):
        errors.append("❌ Ном. напряжение АКБ инвертора должно быть между минимальным и максимальным.")
    
    # 8. Интервалы часов нагрузки (начало <= конец)
    if params_dict['load_min_start_hour'] > params_dict['load_min_end_hour']:
        errors.append("❌ Начало мин. нагрузки не может быть позже её конца.")
    if params_dict['load_max_start_hour'] > params_dict['load_max_end_hour']:
        errors.append("❌ Начало макс. нагрузки не может быть позже её конца.")
    if params_dict['load_normal_start_hour'] > params_dict['load_normal_end_hour']:
        errors.append("❌ Начало обычной нагрузки не может быть позже её конца.")
    
    # Дополнительно: если максимальная нагрузка вне рабочих часов? (опционально)
    # Можно проверить, что часы макс. нагрузки укладываются в рабочие часы, но это не обязательно.
    
    return errors


if st.button("🚀 ЗАПУСТИТЬ РАСЧЁТ", use_container_width=True):
    # Сначала собираем параметры
    params = {
        'lat': st.session_state.lat,
        'lon': st.session_state.lon,
        'timezone': tz,
        'start_date': start_str,
        'end_date': end_str,
        'max_load_power_kw': max_load_power_kw,
        'max_load_work_hours': max_load_work_hours,
        'load_min_start_hour': load_min_start,
        'load_min_end_hour': load_min_end,
        'load_max_start_hour': load_max_start,
        'load_max_end_hour': load_max_end,
        'load_normal_start_hour': load_normal_start,
        'load_normal_end_hour': load_normal_end,
        'photoEfficiency': photoEfficiency,
        'k_photoEffTemp': k_photoEffTemp,
        'photoNOCT': photoNOCT,
        'panel_Vmp': panel_Vmp,
        'panel_Voc': panel_Voc,
        'panel_Imp': panel_Imp,
        'panel_Isc': panel_Isc,
        'photoCellWidth': photoCellWidth,
        'photoCellHigh': photoCellHigh,
        'photoCellNum': photoCellNum,
        'numberbattery_1': numberbattery_1,
        'charge_voltage': charge_voltage,
        'battery_nominal_ah': battery_nominal_ah,
        'battery_voltage': battery_voltage,
        'k_min_SoC': k_min_SoC,
        'k_mode_battery': k_mode_battery,
        'kCharge': kCharge,
        'inverter_nominal_power': inverter_nominal_power,
        'inverter_efficiency': inverter_efficiency,
        'inverter_battery_voltage_nominal': inverter_battery_voltage_nominal,
        'inverter_battery_voltage_min': inverter_battery_voltage_min,
        'inverter_battery_voltage_max': inverter_battery_voltage_max,
        'inverter_max_battery_charge_current': inverter_max_battery_charge_current,
        'inverter_max_battery_discharge_current': inverter_max_battery_discharge_current,
        'inverter_mppt_min': inverter_mppt_min,
        'inverter_mppt_max': inverter_mppt_max,
        'inverter_pv_max_voltage': inverter_pv_max_voltage,
        'inverter_pv_start_voltage': inverter_pv_start_voltage,
        'inverter_mppt_count': inverter_mppt_count,
        'inverter_pv_nominal_power': inverter_pv_nominal_power,
        'inverter_pv_max_current_per_mppt': inverter_pv_max_current_per_mppt,
        'inverter_pv_max_isc_per_mppt': inverter_pv_max_isc_per_mppt,
        'max_inverters_in_parallel': max_inverters_in_parallel,
        'k_cable_pv': k_cable_pv,
        'k_cable_batt': k_cable_batt,
        'k_cable_ac': k_cable_ac,
        'reserve_factor_inverter': reserve_factor_inverter,
        'roof_length': roof_length,
        'roof_width': roof_width,
        'initial_battery_soc': initial_battery_soc
    }
    
    # Валидация
    errors = validate_inputs(params)
    if errors:
        for err in errors:
            st.error(err)
        st.stop()   # Прерываем выполнение кнопки, дальше код не идёт
        # Альтернативно можно не вызывать st.stop(), а просто не выполнять расчёт,
        # но st.stop() останавливает весь скрипт на этом месте, не меняя состояние.
        # Это корректно, потому что мы не хотим менять show_map и запускать расчёт.
        
    # Если ошибок нет – скрываем карту и запускаем расчёт
    st.session_state.show_map = False
    
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
    st.subheader("🗺️ Кликните по карте, чтобы выбрать местоположение")
    
    m = folium.Map(
        location=[st.session_state.lat, st.session_state.lon],
        zoom_start=8,
        tiles='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        attr=' '   # на всякий случай чистая строка
    )
    folium.Marker(
        location=[st.session_state.lat, st.session_state.lon],
        tooltip='Текущая точка',
        icon=DivIcon(
            html='<div style="font-size: 24px; color: #e74c3c;">⭐</div>',
            icon_size=(24, 24),
            icon_anchor=(12, 24)
        )
    ).add_to(m)
    m.add_child(Geocoder(position='topright', collapsed=True, placeholder='🔍 Поиск города...'))
    
    # --- Скрываем всё, что отображается в нижней части карты ---
    # Скрываем только контрол атрибуции
    m.get_root().header.add_child(
        Element('<style>.leaflet-control-attribution { display: none !important; }</style>')
    )
    
    # Отображаем карту
    map_data = st_folium(m, width='100%', height=500)
    
    # Кнопка сброса вида
    col_btn, _ = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 Сбросить вид карты"):
            st.session_state.lat = 50.739537
            st.session_state.lon = 136.567232
            st.rerun()
    
    # Обработка клика или перетаскивания маркера
    if map_data and map_data.get('last_clicked'):
        clicked_lat = map_data['last_clicked']['lat']
        clicked_lon = map_data['last_clicked']['lng']
        # Обновляем только если координаты изменились
        if abs(clicked_lat - st.session_state.lat) > 1e-8 or abs(clicked_lon - st.session_state.lon) > 1e-8:
            st.session_state.lat = clicked_lat
            st.session_state.lon = clicked_lon
            st.rerun()
    elif map_data and map_data.get('last_object_clicked') and map_data['last_object_clicked'].get('latlng'):
        # Если перетащили маркер
        marker_lat = map_data['last_object_clicked']['latlng'][0]
        marker_lon = map_data['last_object_clicked']['latlng'][1]
        if abs(marker_lat - st.session_state.lat) > 1e-8 or abs(marker_lon - st.session_state.lon) > 1e-8:
            st.session_state.lat = marker_lat
            st.session_state.lon = marker_lon
            st.rerun()
    
    # Отображаем текущие координаты (с карты или из сессии)
    st.markdown(f'<div class="coord-text">📍 Текущие координаты: широта {st.session_state.lat:.6f}, долгота {st.session_state.lon:.6f}</div>', unsafe_allow_html=True)
    st.caption("💡 Кликните по карте – координаты автоматически обновятся в полях ввода.")

# ---------- РЕЗУЛЬТАТЫ ----------
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
    st.markdown('<p style="color: #1c047b; background-color: transparent;">📌 Введите все параметры и нажмите «ЗАПУСТИТЬ РАСЧЁТ»</p>', unsafe_allow_html=True)
