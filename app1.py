from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import pyodbc
import requests
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret"

# Configuration
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

DB_CONFIG = {
    "server": "172.18.25.38",
    "user": "sa",
    "password": "wwilscada@4444",
    "database": "Weatherforecast"
}

def get_db_connection():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={DB_CONFIG['server']};DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['user']};PWD={DB_CONFIG['password']};Trusted_Connection=no;"
    )

def convert_wind_direction(degrees):
    try:
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        return directions[round(float(degrees) / 45) % 8]
    except:
        return 'Unknown'

def get_weather_icon(condition):
    condition = condition.lower()
    if 'sunny' in condition:
        return '01d'
    elif 'partly' in condition or 'cloudy' in condition:
        return '02d'
    elif 'rain' in condition:
        return '09d'
    elif 'storm' in condition or 'thunder' in condition:
        return '11d'
    elif 'snow' in condition:
        return '13d'
    elif 'fog' in condition or 'mist' in condition:
        return '50d'
    else:
        return '03d'

def fetch_weather_data(lat, lon):
    today = datetime.now().date()
    end_date = today + timedelta(days=4)
    for key in VC_API_KEYS:
        url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}/{today}/{end_date}?unitGroup=metric&key={key}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            print(f"✅ API key succeeded: {key}")
            return response.json()
        except:
            print(f"⚠️ API key failed: {key}")
    raise Exception("❌ All API keys failed.")


@app.route('/dashboard')  # This defines the URL endpoint
def dashboard():
    return render_template('dashboard.html')  # Renders your dashboard template

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/view_data")
def view_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM WeatherData2 ORDER BY Createdon DESC")
    data = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    return render_template("view_data.html", weather_data=data, get_weather_icon=get_weather_icon)

@app.route("/get_forecast_by_state")
def get_forecast_by_state():
    state = request.args.get("state")
    if not state:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 5 State, LOCNO, PlantNo, Conditions, Temp, TempMin, TempMax,
               WindSpeed, WindDir, ForecastDate
        FROM WeatherData2
        WHERE State = ?
        ORDER BY ForecastDate DESC
    """, (state,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "state": row.State,
            "locno": row.LOCNO,
            "plant": row.PlantNo,
            "condition": row.Conditions,
            "temp": row.Temp,
            "tempmin": row.TempMin,
            "tempmax": row.TempMax,
            "windspeed": row.WindSpeed,
            "winddir": row.WindDir,
            "date": row.ForecastDate.strftime('%Y-%m-%d'),
            "icon": get_weather_icon(row.Conditions)
        })
    return jsonify(result)

@app.route("/get_hierarchy")
def get_hierarchy():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT State, PlantNo, LOCNO
        FROM WEC_All_Data_2
        WHERE State IS NOT NULL AND PlantNo IS NOT NULL AND LOCNO IS NOT NULL
    """)
    rows = cursor.fetchall()
    conn.close()

    hierarchy = {}
    for state, plant, loc in rows:
        if state not in hierarchy:
            hierarchy[state] = {}
        if plant not in hierarchy[state]:
            hierarchy[state][plant] = []
        hierarchy[state][plant].append(f"LOCNO {loc}")
    return jsonify(hierarchy)

@app.route("/get_forecast")
def get_forecast():
    locno = request.args.get("locno")
    if not locno:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TOP 5 ForecastDate, Conditions, Temp
        FROM WeatherData2
        WHERE LOCNO = ?
        ORDER BY ForecastDate DESC
    """, (locno,))
    rows = cursor.fetchall()
    conn.close()

    forecast = []
    for row in rows:
        forecast.append({
            "day": row.ForecastDate.strftime('%A'),
            "condition": row.Conditions,
            "temp": row.Temp,
            "icon": get_weather_icon(row.Conditions)
        })
    return jsonify(forecast)



def save_weather_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    print(f"⏳ Running weather update at {datetime.now()}")
    cursor.execute("""
        SELECT DISTINCT State, LOCNO, PlantNo, Latitude, Longitude
        FROM WEC_All_Data_2
        WHERE Latitude IS NOT NULL AND Longitude IS NOT NULL
    """)
    records = cursor.fetchall()
    count = 0

    for state, locno, plantno, lat, lon in records:
        try:
            data = fetch_weather_data(lat, lon)
            for day in data["days"]:
                forecast_date = datetime.strptime(day["datetime"], "%Y-%m-%d")
                cursor.execute("""
                    INSERT INTO WeatherData2 (
                        State, LOCNO, PlantNo, Latitude, Longitude, WindSpeed, WindGust,
                        WindDir, Conditions, Temp, TempMin, TempMax, Humidity, Precip,
                        Createdon, ForecastDate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    state, locno, plantno, lat, lon,
                    day.get("windspeed", 0.0),
                    day.get("windgust", 0.0),
                    convert_wind_direction(day.get("winddir", 0)),
                    day.get("conditions", "Unknown"),
                    day.get("temp", 0.0),
                    day.get("tempmin", 0.0),
                    day.get("tempmax", 0.0),
                    day.get("humidity", 0.0),
                    day.get("precip", 0.0),
                    datetime.now(),
                    forecast_date
                ))
                count += 1
        except Exception as e:
            print(f"[Error] Skipped {state}-{locno}: {e}")
    conn.commit()
    conn.close()
    print(f"✅ Inserted {count} weather records.")

    




# Scheduler to run daily
# scheduler = BackgroundScheduler()
# scheduler.add_job(save_weather_data)
# scheduler.start()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=7738)

