import hashlib
import os
import sqlite3

from app.config import DB_PATH


def get_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    _seed_data(conn)
    conn.close()


def _create_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS rack_pdus (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        model TEXT,
        manufacturer TEXT,
        serial_number TEXT,
        firmware_version TEXT,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        rated_current_amps REAL,
        rated_voltage_volts REAL,
        rated_frequency_hz REAL,
        location_info TEXT
    );

    CREATE TABLE IF NOT EXISTS pdu_outlets (
        id TEXT NOT NULL,
        pdu_id TEXT NOT NULL,
        name TEXT,
        outlet_type TEXT,
        phase_wiring_type TEXT DEFAULT 'OnePhase3Wire',
        power_state TEXT DEFAULT 'On',
        rated_current_amps REAL,
        voltage_volts REAL,
        current_amps REAL,
        power_watts REAL,
        energy_kwh REAL,
        power_factor REAL,
        frequency_hz REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        branch_id TEXT,
        PRIMARY KEY (id, pdu_id)
    );

    CREATE TABLE IF NOT EXISTS pdu_mains (
        id TEXT NOT NULL,
        pdu_id TEXT NOT NULL,
        name TEXT,
        phase_wiring_type TEXT DEFAULT 'OnePhase3Wire',
        voltage_volts REAL,
        current_amps REAL,
        power_watts REAL,
        energy_kwh REAL,
        power_factor REAL,
        frequency_hz REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, pdu_id)
    );

    CREATE TABLE IF NOT EXISTS pdu_branches (
        id TEXT NOT NULL,
        pdu_id TEXT NOT NULL,
        name TEXT,
        phase_wiring_type TEXT DEFAULT 'OnePhase3Wire',
        rated_current_amps REAL,
        current_amps REAL,
        power_watts REAL,
        energy_kwh REAL,
        power_factor REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, pdu_id)
    );

    CREATE TABLE IF NOT EXISTS pdu_sensors (
        id TEXT NOT NULL,
        pdu_id TEXT NOT NULL,
        name TEXT,
        reading_type TEXT,
        reading REAL,
        reading_units TEXT,
        threshold_lower_caution REAL,
        threshold_lower_critical REAL,
        threshold_upper_caution REAL,
        threshold_upper_critical REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, pdu_id)
    );

    CREATE TABLE IF NOT EXISTS upss (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        model TEXT,
        manufacturer TEXT,
        serial_number TEXT,
        firmware_version TEXT,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        line_input_status TEXT DEFAULT 'Normal',
        rating_va REAL,
        rating_watts REAL,
        battery_charge_percent REAL,
        battery_runtime_minutes REAL,
        battery_status_state TEXT DEFAULT 'Enabled',
        battery_status_health TEXT DEFAULT 'OK',
        location_info TEXT
    );

    CREATE TABLE IF NOT EXISTS ups_outlets (
        id TEXT NOT NULL,
        ups_id TEXT NOT NULL,
        name TEXT,
        outlet_type TEXT,
        phase_wiring_type TEXT DEFAULT 'OnePhase3Wire',
        power_state TEXT DEFAULT 'On',
        rated_current_amps REAL,
        voltage_volts REAL,
        current_amps REAL,
        power_watts REAL,
        energy_kwh REAL,
        power_factor REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, ups_id)
    );

    CREATE TABLE IF NOT EXISTS ups_mains (
        id TEXT NOT NULL,
        ups_id TEXT NOT NULL,
        name TEXT,
        phase_wiring_type TEXT DEFAULT 'OnePhase3Wire',
        voltage_volts REAL,
        current_amps REAL,
        power_watts REAL,
        energy_kwh REAL,
        power_factor REAL,
        frequency_hz REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, ups_id)
    );

    CREATE TABLE IF NOT EXISTS ups_sensors (
        id TEXT NOT NULL,
        ups_id TEXT NOT NULL,
        name TEXT,
        reading_type TEXT,
        reading REAL,
        reading_units TEXT,
        threshold_lower_caution REAL,
        threshold_lower_critical REAL,
        threshold_upper_caution REAL,
        threshold_upper_critical REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, ups_id)
    );

    CREATE TABLE IF NOT EXISTS chassis (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        chassis_type TEXT DEFAULT 'Rack',
        model TEXT,
        manufacturer TEXT,
        serial_number TEXT,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        location_info TEXT,
        rack_units INTEGER
    );

    CREATE TABLE IF NOT EXISTS chassis_sensors (
        id TEXT NOT NULL,
        chassis_id TEXT NOT NULL,
        name TEXT,
        reading_type TEXT,
        reading REAL,
        reading_units TEXT,
        threshold_lower_caution REAL,
        threshold_lower_critical REAL,
        threshold_upper_caution REAL,
        threshold_upper_critical REAL,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        PRIMARY KEY (id, chassis_id)
    );

    CREATE TABLE IF NOT EXISTS managers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        manager_type TEXT DEFAULT 'RackManager',
        firmware_version TEXT,
        status_state TEXT DEFAULT 'Enabled',
        status_health TEXT DEFAULT 'OK',
        ipv4_address TEXT,
        hostname TEXT
    );

    CREATE TABLE IF NOT EXISTS event_subscriptions (
        id TEXT PRIMARY KEY,
        name TEXT,
        destination TEXT NOT NULL,
        protocol TEXT DEFAULT 'Redfish',
        context TEXT,
        event_types TEXT,
        status_state TEXT DEFAULT 'Enabled'
    );

    CREATE TABLE IF NOT EXISTS log_entries (
        id TEXT NOT NULL,
        owner_type TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        created TEXT NOT NULL,
        entry_type TEXT DEFAULT 'Event',
        severity TEXT DEFAULT 'OK',
        message TEXT,
        origin_of_condition TEXT,
        PRIMARY KEY (id, owner_type, owner_id)
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'Administrator'
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        token TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    """)
    conn.commit()


def _seed_data(conn):
    if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO accounts (id, username, password_hash, role) VALUES ('1', 'admin', ?, 'Administrator')",
            (hashlib.sha256("redfish".encode()).hexdigest(),),
        )
        conn.commit()

    if conn.execute("SELECT COUNT(*) FROM rack_pdus").fetchone()[0] > 0:
        return

    conn.execute("""
        INSERT INTO rack_pdus
            (id, name, model, manufacturer, serial_number, firmware_version,
             rated_current_amps, rated_voltage_volts, rated_frequency_hz, location_info)
        VALUES
            ('1', 'Rack PDU 1', 'PDU-48X-20A', 'DMTF', 'PDU-SN-123456', '1.2.0',
             30.0, 200.0, 50.0, '{"InfoFormat":"RackUnits","Info":"Rack1 U1"}')
    """)

    conn.executemany("""
        INSERT INTO pdu_outlets
            (id, pdu_id, name, outlet_type, phase_wiring_type, power_state,
             rated_current_amps, voltage_volts, current_amps, power_watts,
             energy_kwh, power_factor, frequency_hz, branch_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [
        ('A1','1','Outlet A1','IEC_60320_C13','OnePhase3Wire','On', 15.0,100.0, 3.2, 320.0, 1523.5,0.97,50.0,'Branch1'),
        ('A2','1','Outlet A2','IEC_60320_C13','OnePhase3Wire','On', 15.0,100.0, 4.1, 410.0, 2015.2,0.98,50.0,'Branch1'),
        ('A3','1','Outlet A3','IEC_60320_C13','OnePhase3Wire','On', 15.0,100.0, 2.8, 280.0, 1205.8,0.96,50.0,'Branch1'),
        ('A4','1','Outlet A4','IEC_60320_C13','OnePhase3Wire','Off',15.0,  0.0, 0.0,   0.0,    0.0,1.00,50.0,'Branch1'),
        ('B1','1','Outlet B1','IEC_60320_C13','OnePhase3Wire','On', 15.0,100.0, 5.0, 500.0, 2500.0,0.99,50.0,'Branch2'),
        ('B2','1','Outlet B2','IEC_60320_C13','OnePhase3Wire','On', 15.0,100.0, 3.5, 350.0, 1750.0,0.97,50.0,'Branch2'),
        ('B3','1','Outlet B3','IEC_60320_C13','OnePhase3Wire','On', 15.0,100.0, 2.0, 200.0,  980.5,0.95,50.0,'Branch2'),
        ('B4','1','Outlet B4','IEC_60320_C13','OnePhase3Wire','Off',15.0,  0.0, 0.0,   0.0,    0.0,1.00,50.0,'Branch2'),
    ])

    conn.execute("""
        INSERT INTO pdu_mains
            (id, pdu_id, name, phase_wiring_type, voltage_volts, current_amps,
             power_watts, energy_kwh, power_factor, frequency_hz)
        VALUES ('Main1','1','Main Circuit 1','OnePhase3Wire',100.0,21.1,2060.0,9975.0,0.97,50.0)
    """)

    conn.executemany("""
        INSERT INTO pdu_branches
            (id, pdu_id, name, phase_wiring_type, rated_current_amps,
             current_amps, power_watts, energy_kwh, power_factor)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, [
        ('Branch1','1','Branch Circuit 1','OnePhase3Wire',20.0,10.1,1010.0,4744.5,0.97),
        ('Branch2','1','Branch Circuit 2','OnePhase3Wire',20.0,10.5,1050.0,5230.5,0.97),
    ])

    conn.executemany("""
        INSERT INTO pdu_sensors
            (id, pdu_id, name, reading_type, reading, reading_units,
             threshold_lower_caution, threshold_lower_critical,
             threshold_upper_caution, threshold_upper_critical)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [
        ('Current1', '1','Input Current',  'Current',     21.1,  'A',  None,None, 25.0, 30.0),
        ('Voltage1', '1','Input Voltage',  'Voltage',    100.2,  'V',  85.0,80.0,110.0,115.0),
        ('Power1',   '1','Input Power',    'Power',      2060.0, 'W',  None,None,5500.0,6000.0),
        ('Energy1',  '1','Energy Consumed','EnergykWh',  9975.0, 'kWh',None,None, None, None),
        ('Freq1',    '1','Input Frequency','Frequency',    50.0, 'Hz', 47.0,45.0,  53.0, 55.0),
        ('Temp1',    '1','PDU Temperature','Temperature',  28.5, 'Cel',None,None,  40.0, 55.0),
    ])

    conn.execute("""
        INSERT INTO upss
            (id, name, model, manufacturer, serial_number, firmware_version,
             line_input_status, rating_va, rating_watts,
             battery_charge_percent, battery_runtime_minutes, location_info)
        VALUES
            ('1','UPS 1','UPS-5000VA','DMTF','UPS-SN-789012','2.1.0',
             'Normal',5000.0,4500.0,95.0,45.0,
             '{"InfoFormat":"RackUnits","Info":"Rack1 U42"}')
    """)

    conn.executemany("""
        INSERT INTO ups_outlets
            (id, ups_id, name, outlet_type, phase_wiring_type, power_state,
             rated_current_amps, voltage_volts, current_amps, power_watts, energy_kwh, power_factor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [
        ('OUT1','1','UPS Output 1','IEC_60320_C19','OnePhase3Wire','On', 20.0,100.0, 8.5, 850.0,4200.0,0.98),
        ('OUT2','1','UPS Output 2','IEC_60320_C19','OnePhase3Wire','On', 20.0,100.0, 7.2, 720.0,3600.0,0.97),
        ('OUT3','1','UPS Output 3','IEC_60320_C19','OnePhase3Wire','On', 20.0,100.0, 6.0, 600.0,3000.0,0.96),
        ('OUT4','1','UPS Output 4','IEC_60320_C19','OnePhase3Wire','Off',20.0,  0.0, 0.0,   0.0,   0.0,1.00),
    ])

    conn.execute("""
        INSERT INTO ups_mains
            (id, ups_id, name, phase_wiring_type, voltage_volts, current_amps,
             power_watts, energy_kwh, power_factor, frequency_hz)
        VALUES ('Main1','1','AC Input 1','OnePhase3Wire',100.0,24.5,2400.0,11800.0,0.98,50.0)
    """)

    conn.executemany("""
        INSERT INTO ups_sensors
            (id, ups_id, name, reading_type, reading, reading_units,
             threshold_lower_caution, threshold_lower_critical,
             threshold_upper_caution, threshold_upper_critical)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [
        ('InputPower',   '1','Input Power',    'Power',   2400.0,'W',   None,None,4000.0,4500.0),
        ('OutputPower',  '1','Output Power',   'Power',   2170.0,'W',   None,None,4000.0,4500.0),
        ('BattVoltage',  '1','Battery Voltage','Voltage',   48.2,'V',   42.0,40.0,  52.0, 54.0),
        ('BattCharge',   '1','Battery Charge', 'Percent',   95.0,'%',   20.0,10.0,  None, None),
        ('InputVoltage', '1','Input Voltage',  'Voltage',  100.1,'V',   85.0,80.0, 110.0,115.0),
        ('OutputVoltage','1','Output Voltage', 'Voltage',  100.0,'V',   85.0,80.0, 110.0,115.0),
    ])

    conn.execute("""
        INSERT INTO chassis
            (id, name, chassis_type, model, manufacturer, serial_number, location_info, rack_units)
        VALUES
            ('Rack1','Server Rack 1','Rack','RACK-42U','DMTF','RACK-SN-345678',
             '{"InfoFormat":"BayNumber","Info":"1"}',42)
    """)

    conn.executemany("""
        INSERT INTO chassis_sensors
            (id, chassis_id, name, reading_type, reading, reading_units,
             threshold_lower_caution, threshold_lower_critical,
             threshold_upper_caution, threshold_upper_critical)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, [
        ('Temp1',    'Rack1','Rack Inlet Temp',   'Temperature', 22.5,'Cel',None,None, 35.0, 45.0),
        ('Temp2',    'Rack1','Rack Middle Temp',  'Temperature', 26.0,'Cel',None,None, 40.0, 50.0),
        ('Temp3',    'Rack1','Rack Outlet Temp',  'Temperature', 30.5,'Cel',None,None, 45.0, 55.0),
        ('Temp4',    'Rack1','Rack Top Temp',     'Temperature', 32.0,'Cel',None,None, 45.0, 55.0),
        ('Humidity1','Rack1','Rack Humidity 1',   'Humidity',    45.0,'%',  20.0,10.0, 80.0, 90.0),
        ('Humidity2','Rack1','Rack Humidity 2',   'Humidity',    47.5,'%',  20.0,10.0, 80.0, 90.0),
        ('TotalPower','Rack1','Rack Total Power', 'Power',     4230.0,'W',  None,None,8000.0,10000.0),
    ])

    conn.execute("""
        INSERT INTO managers
            (id, name, manager_type, firmware_version, ipv4_address, hostname)
        VALUES
            ('BMC','Rack Management Controller','RackManager','1.0.0','192.168.1.1','rack-bmc-1')
    """)

    conn.commit()
