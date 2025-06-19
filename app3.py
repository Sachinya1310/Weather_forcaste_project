from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from apscheduler.schedulers.background import BackgroundScheduler
import pyodbc
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret"

# API & DB configuration
VC_API_KEYS = [
    '6NSHBH2VCR2BPN6WMYRGLL4JX',
    '77EEYBH9HP5EFD3QJ44M7DX39',
    'E9VD8EY5W25NQJ4ATLYE4NB42',
    '7BSCDLVXUSBKW49LU5LNCJQYV',
    'JFSSVCVP2PZV6FL2HRPLMADAT',
    'DSR5VPHEX7JAARV7BET5TST9T',
    '9QE7RYKNFAR488VSFEP7MRZDG',
    'P8VTN4UHMDAMQHTFF9XMLQNMC',
    '2ECCLNJ89FMCU53G6VWLQCU5Q'
]

DB_SERVER = '172.18.25.38'
DB_USER = 'sa'
DB_PASSWORD = 'wwilscada@4444'
DB_NAME = 'Weatherforecast'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database connection
def get_db_connection():
    try:
        conn = pyodbc.connect(
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={DB_SERVER};DATABASE={DB_NAME};UID={DB_USER};PWD={DB_PASSWORD};"
            f"Trusted_Connection=no;"
        )
        conn.autocommit = True
        return conn
    except pyodbc.Error as e:
        print(f"Database connection error: {e}")
        raise

# Convert wind direction from degrees to compass direction
def convert_wind_direction(degrees):
    try:
        degrees = float(degrees)
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        idx = round(degrees / 45) % 8
        return directions[idx]
    except:
        return 'Unknown'

# Fetch weather data using rotating API keys
def get_weather_data(lat, lon):
    today = datetime.now().date()
    end_date = today + timedelta(days=4)  # 5-day forecast

    for key in VC_API_KEYS:
        url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}/{today}/{end_date}?unitGroup=metric&key={key}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            print(f"✅ Success with API key: {key}")
            return response.json()
        except Exception as e:
            print(f"⚠️ API key {key} failed: {e}")
            continue

    # If all keys fail
    raise Exception("❌ All API keys failed to retrieve weather data.")

@app.route("/", methods=["GET"])
def home():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT State FROM [dbo].[WEC_All_Data_2] WHERE State IS NOT NULL AND State != ''")
        states = [row[0] for row in cursor.fetchall()]
        return render_template("index.html", states=states)
    except Exception as e:
        return f"<h2>Error loading states: {e}</h2>"
    finally:
        if conn:
            conn.close()

@app.route("/view_data", methods=["GET"])
def view_data():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'WeatherData2'")
        if cursor.fetchone()[0] == 0:
            return "<h2>WeatherData2 table not found.</h2>"

        cursor.execute("SELECT * FROM [dbo].[WeatherData2] ORDER BY Createdon DESC")
        records = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
        return render_template("view_data.html", weather_data=records)
    except Exception as e:
        return f"<h2>Error loading weather data: {e}</h2>"
    finally:
        if conn:
            conn.close()

@app.route("/test_db")
def test_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME(), SCHEMA_NAME()")
        db_info = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'WeatherData2'")
        table_exists = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM [dbo].[WeatherData2]")
        record_count = cursor.fetchone()[0]

        cursor.execute("SELECT TOP 1 * FROM [dbo].[WeatherData2]")
        sample = cursor.fetchone()

        return render_template("db_test.html", db_name=db_info[0], schema=db_info[1],
                               table_exists=table_exists, record_count=record_count, sample=sample)
    except Exception as e:
        return f"<h2>Database test failed: {str(e)}</h2>"
    finally:
        if conn:
            conn.close()

# Background job to save weather data
def save_weather_data():
    conn = None
    try:
        print(f"\n⏳ Starting weather update at {datetime.now()}")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT State, LOCNO, PlantNo, Latitude, Longitude 
            FROM [dbo].[WEC_All_Data_2] 
            WHERE Latitude IS NOT NULL AND Longitude IS NOT NULL
        """)
        records = cursor.fetchall()

        inserted = 0
        for record in records:
            state, locno, plantno, lat, lon = record
            try:
                data = get_weather_data(lat, lon)
                
                # Process each day in the forecast
                for day_data in data['days']:
                    forecast_date = datetime.strptime(day_data['datetime'], '%Y-%m-%d')
                    
                    insert_data = (
                        state, locno, plantno, lat, lon,
                        day_data.get("windspeed", 0.0),
                        day_data.get("windgust", 0.0),
                        convert_wind_direction(day_data.get("winddir", 0)),
                        day_data.get("conditions", "Unknown"),
                        day_data.get("temp", 0.0),
                        day_data.get("tempmin", 0.0),
                        day_data.get("tempmax", 0.0),
                        day_data.get("humidity", 0.0),
                        day_data.get("precip", 0.0),
                        datetime.now(),  # Current timestamp
                        forecast_date   # Forecast date
                    )
                    
                    cursor.execute("""
                        INSERT INTO [dbo].[WeatherData2] (
                            State, LOCNO, PlantNo, Latitude, Longitude, WindSpeed, WindGust,
                            WindDir, Conditions, Temp, Tempmin, Tempmax, Humidity, Precip, 
                            Createdon, ForecastDate
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, insert_data)
                    inserted += 1
                    
            except Exception as inner_e:
                print(f"[Error] Skipped {state}-{locno}: {inner_e}")
                continue

        print(f"✅ Inserted {inserted} weather records at {datetime.now()}")
    except Exception as e:
        print(f"❌ Background job error: {e}")
    finally:
        if conn:
            conn.close()

@app.route('/dashboard', methods=["GET"])
def dashboard():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get distinct states
        cursor.execute("SELECT DISTINCT State FROM [dbo].[WEC_All_Data_2] WHERE State IS NOT NULL AND State != ''")
        states = [row[0] for row in cursor.fetchall()]

        # Get distinct PlantNo
        cursor.execute("SELECT DISTINCT PlantNo FROM [dbo].[WEC_All_Data_2] WHERE PlantNo IS NOT NULL AND PlantNo != ''")
        plants = [row[0] for row in cursor.fetchall()]

        # Get distinct LOCNO
        cursor.execute("SELECT DISTINCT LOCNO FROM [dbo].[WEC_All_Data_2] WHERE LOCNO IS NOT NULL AND LOCNO != ''")
        locnos = [row[0] for row in cursor.fetchall()]

        return render_template('dashboard.html', states=states, plants=plants, locnos=locnos)

    except Exception as e:
        return f"<h2>Error loading dashboard data: {e}</h2>"
    finally:
        if conn:
            conn.close()



#Schedule background job # type: ignore
scheduler = BackgroundScheduler()
scheduler.add_job(save_weather_data)
scheduler.start()

if __name__ == '__main__':
    app.run(debug=True)
