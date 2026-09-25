# calendar_utils.py
import os
import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from config import CALENDAR_ID, HORARIO_ATENCION

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"
OFFSET_MEXICO = "-06:00"


""" def _preparar_archivos_desde_env():

    if not os.path.exists(CREDENTIALS_FILE):
        contenido = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if contenido:
            with open(CREDENTIALS_FILE, "w") as f:
                f.write(contenido)
    if not os.path.exists(TOKEN_FILE):
        contenido = os.getenv("GOOGLE_TOKEN_JSON")
        if contenido:
            with open(TOKEN_FILE, "w") as f:
                f.write(contenido)"""
def _preparar_archivos_desde_env():
    print("[DEBUG] GOOGLE_CREDENTIALS_JSON existe?", os.getenv("GOOGLE_CREDENTIALS_JSON") is not None)
    print("[DEBUG] GOOGLE_TOKEN_JSON existe?", os.getenv("GOOGLE_TOKEN_JSON") is not None)
    print("[DEBUG] Variables de entorno disponibles:", [k for k in os.environ.keys() if "GOOGLE" in k or "TELEGRAM" in k])
    
    if not os.path.exists(CREDENTIALS_FILE):
        contenido = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if contenido:
            with open(CREDENTIALS_FILE, "w") as f:
                f.write(contenido)
    if not os.path.exists(TOKEN_FILE):
        contenido = os.getenv("GOOGLE_TOKEN_JSON")
        if contenido:
            with open(TOKEN_FILE, "w") as f:
                f.write(contenido)


def get_service():
    _preparar_archivos_desde_env()
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def obtener_horarios_disponibles(fecha: datetime.date, duracion_min: int, ignorar_event_id: str = None):
    dia_semana = fecha.weekday()
    if dia_semana not in HORARIO_ATENCION:
        return []

    hora_inicio, hora_fin = HORARIO_ATENCION[dia_semana]
    inicio_dia = datetime.datetime.combine(fecha, datetime.time(hora_inicio, 0))
    fin_dia = datetime.datetime.combine(fecha, datetime.time(hora_fin, 0))

    service = get_service()
    eventos = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=inicio_dia.isoformat() + OFFSET_MEXICO,
        timeMax=fin_dia.isoformat() + OFFSET_MEXICO,
        singleEvents=True,
        orderBy="startTime",
    ).execute().get("items", [])

    ocupados = []
    for ev in eventos:
        if ignorar_event_id and ev.get("id") == ignorar_event_id:
            continue
        inicio_ev = ev.get("start", {})
        fin_ev = ev.get("end", {})
        if "dateTime" not in inicio_ev or "dateTime" not in fin_ev:
            continue
        ini = datetime.datetime.fromisoformat(inicio_ev["dateTime"]).replace(tzinfo=None)
        fin = datetime.datetime.fromisoformat(fin_ev["dateTime"]).replace(tzinfo=None)
        ocupados.append((ini, fin))

    disponibles = []
    cursor = inicio_dia
    paso = datetime.timedelta(minutes=15)
    duracion = datetime.timedelta(minutes=duracion_min)
    while cursor + duracion <= fin_dia:
        fin_bloque = cursor + duracion
        choca = any(cursor < ocup_fin and fin_bloque > ocup_ini for ocup_ini, ocup_fin in ocupados)
        if not choca:
            disponibles.append(cursor)
        cursor += paso
    return disponibles


def crear_evento(nombre, telefono, servicio, inicio: datetime.datetime, duracion_min: int,
                  precio, chat_id=None, username_tg=None):
    service = get_service()
    fin = inicio + datetime.timedelta(minutes=duracion_min)
    evento = {
        "summary": f"{servicio} - {nombre}",
        "description": f"Cliente: {nombre}\nTeléfono: {telefono}\nServicio: {servicio}\nCosto: ${precio}",
        "start": {"dateTime": inicio.isoformat(), "timeZone": "America/Mexico_City"},
        "end": {"dateTime": fin.isoformat(), "timeZone": "America/Mexico_City"},
        "extendedProperties": {
            "private": {
                "chat_id": str(chat_id) if chat_id else "",
                "username_tg": username_tg or "",
                "nombre": nombre,
                "telefono": telefono,
                "servicio": servicio,
                "precio": str(precio),
                "duracion_min": str(duracion_min),
                "recordatorio_24h": "no",
                "recordatorio_2h": "no",
            }
        },
    }
    return service.events().insert(calendarId=CALENDAR_ID, body=evento).execute()


def eliminar_evento(event_id):
    service = get_service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()


def obtener_citas_cliente(chat_id, dias_adelante=90):
    service = get_service()
    ahora = datetime.datetime.now()
    limite = ahora + datetime.timedelta(days=dias_adelante)
    eventos = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=ahora.isoformat() + OFFSET_MEXICO,
        timeMax=limite.isoformat() + OFFSET_MEXICO,
        singleEvents=True,
        orderBy="startTime",
    ).execute().get("items", [])

    citas = []
    for ev in eventos:
        props = ev.get("extendedProperties", {}).get("private", {})
        if props.get("chat_id") != str(chat_id):
            continue
        inicio_ev = ev.get("start", {})
        if "dateTime" not in inicio_ev:
            continue
        inicio = datetime.datetime.fromisoformat(inicio_ev["dateTime"]).replace(tzinfo=None)
        citas.append({
            "event_id": ev["id"],
            "inicio": inicio,
            "servicio": props.get("servicio", "Servicio"),
            "precio": props.get("precio", ""),
            "nombre": props.get("nombre", ""),
            "telefono": props.get("telefono", ""),
            "username_tg": props.get("username_tg") or None,
            "duracion_min": int(props.get("duracion_min", "60")),
        })
    return citas


def obtener_citas_proximas(horas_adelante=26):
    service = get_service()
    ahora = datetime.datetime.now()
    limite = ahora + datetime.timedelta(hours=horas_adelante)
    eventos = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=ahora.isoformat() + OFFSET_MEXICO,
        timeMax=limite.isoformat() + OFFSET_MEXICO,
        singleEvents=True,
        orderBy="startTime",
    ).execute().get("items", [])

    citas = []
    for ev in eventos:
        inicio_ev = ev.get("start", {})
        if "dateTime" not in inicio_ev:
            continue
        inicio = datetime.datetime.fromisoformat(inicio_ev["dateTime"]).replace(tzinfo=None)
        props = ev.get("extendedProperties", {}).get("private", {})
        citas.append({
            "event_id": ev["id"],
            "inicio": inicio,
            "servicio": props.get("servicio", ev.get("summary", "tu cita")),
            "chat_id": props.get("chat_id") or None,
            "recordatorio_24h": props.get("recordatorio_24h", "no"),
            "recordatorio_2h": props.get("recordatorio_2h", "no"),
        })
    return citas


def marcar_recordatorio(event_id, campo):
    service = get_service()
    evento = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
    props = evento.get("extendedProperties", {}).get("private", {})
    props[campo] = "si"
    service.events().patch(
        calendarId=CALENDAR_ID,
        eventId=event_id,
        body={"extendedProperties": {"private": props}},
    ).execute()