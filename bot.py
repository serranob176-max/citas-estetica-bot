import calendar
import datetime
import re
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

from config import TELEGRAM_TOKEN, ADMIN_CHAT_ID, HORARIO_ATENCION
from servicios import SERVICIOS_FIJOS, SERVICIOS_A_CONSULTA
from calendar_utils import (
    obtener_horarios_disponibles, crear_evento, eliminar_evento,
    obtener_citas_cliente, obtener_citas_proximas, marcar_recordatorio,
)

# Estados de la conversación de agendamiento
NOMBRE, TELEFONO, SERVICIO, FECHA, HORA, CONFIRMAR = range(6)

TODOS_LOS_SERVICIOS = list(SERVICIOS_FIJOS.keys()) + SERVICIOS_A_CONSULTA

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]
DIAS_SEMANA_ES = ["L", "M", "M", "J", "V", "S", "D"]

PALABRAS_AFIRMATIVAS = [
    "si", "sí", "sip", "sipi", "sep", "simon", "simón",
    "va", "vale", "dale", "ok", "okay", "okey", "oki", "oky",
    "claro", "correcto", "afirmativo", "confirmo", "confirmado",
    "yes", "adelante", "asi es", "así es", "de una", "sale",
]

def es_afirmativo(texto: str) -> bool:
    texto = texto.strip().lower()
    patron = r"^(" + "|".join(re.escape(p) for p in PALABRAS_AFIRMATIVAS) + r")\b"
    return bool(re.match(patron, texto))

def limpiar_numero_whatsapp(telefono: str) -> str:
    solo_digitos = "".join(filter(str.isdigit, telefono))
    if len(solo_digitos) == 10:
        solo_digitos = "52" + solo_digitos
    return solo_digitos

def boton_contacto(username, telefono: str):
    if username:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 Abrir chat en Telegram", url=f"https://t.me/{username}")
        ]])
    numero_wa = limpiar_numero_whatsapp(telefono)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 Contactar por WhatsApp", url=f"https://wa.me/{numero_wa}")
    ]])

def generar_calendario(anio: int, mes: int, prefijo_nav="NAV", prefijo_dia="DIA") -> InlineKeyboardMarkup:
    hoy = datetime.date.today()
    filas = []

    mes_anterior = mes - 1 if mes > 1 else 12
    anio_mes_anterior = anio if mes > 1 else anio - 1
    mes_siguiente = mes + 1 if mes < 12 else 1
    anio_mes_siguiente = anio if mes < 12 else anio + 1

    filas.append([
        InlineKeyboardButton("◀", callback_data=f"{prefijo_nav}|{anio_mes_anterior}|{mes_anterior}"),
        InlineKeyboardButton(f"{MESES_ES[mes]} {anio}", callback_data="IGNORE"),
        InlineKeyboardButton("▶", callback_data=f"{prefijo_nav}|{anio_mes_siguiente}|{mes_siguiente}"),
    ])
    filas.append([InlineKeyboardButton(d, callback_data="IGNORE") for d in DIAS_SEMANA_ES])

    cal = calendar.Calendar(firstweekday=0)
    for semana in cal.monthdayscalendar(anio, mes):
        fila = []
        for dia in semana:
            if dia == 0:
                fila.append(InlineKeyboardButton(" ", callback_data="IGNORE"))
                continue
            fecha = datetime.date(anio, mes, dia)
            if fecha < hoy or fecha.weekday() not in HORARIO_ATENCION:
                fila.append(InlineKeyboardButton(f"·{dia}", callback_data="IGNORE"))
            else:
                fila.append(InlineKeyboardButton(str(dia), callback_data=f"{prefijo_dia}|{anio}|{mes}|{dia}"))
        filas.append(fila)

    return InlineKeyboardMarkup(filas)
# ----------------------- Flujo de agendamiento -----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Soy el asistente de citas.\n"
        "Escribe /agendar para reservar tu cita.\n"
        "Escribe /miscitas para ver o modificar tus citas.\n"
        "Escribe /info para horarios, ubicación y políticas."
    )

async def agendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Vamos a agendar tu cita! ¿Cuál es tu nombre?")
    return NOMBRE

async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre"] = update.message.text
    await update.message.reply_text("¿Cuál es tu número de teléfono?")
    return TELEFONO

async def recibir_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telefono = update.message.text
    solo_digitos = "".join(filter(str.isdigit, telefono))

    if len(solo_digitos) < 10:
        await update.message.reply_text(
            "Ese número no parece válido. Escribe tu teléfono a 10 dígitos, "
            "ej. 7221234567"
        )
        return TELEFONO

    context.user_data["telefono"] = telefono
    teclado = ReplyKeyboardMarkup(
        [[s] for s in TODOS_LOS_SERVICIOS], one_time_keyboard=True, resize_keyboard=True
    )
    await update.message.reply_text("¿Qué servicio deseas?", reply_markup=teclado)
    return SERVICIO

async def recibir_servicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    servicio = update.message.text
    context.user_data["servicio"] = servicio
    context.user_data["username_tg"] = update.effective_user.username

    if servicio in SERVICIOS_A_CONSULTA:
        d = context.user_data
        await update.message.reply_text(
            "Este servicio requiere que platiquemos en persona para definir "
            "detalles y precio. Ya registré tus datos, en breve te contactamos "
            "para agendar tu valoración.",
            reply_markup=ReplyKeyboardRemove(),
        )
        aviso_admin = (
            f"📋 Nueva solicitud de valoración\n\n"
            f"Nombre: {d['nombre']}\n"
            f"Teléfono: {d['telefono']}\n"
            f"Servicio de interés: {servicio}\n\n"
            f"Contacta al cliente para agendar la valoración."
        )
        boton = boton_contacto(d.get("username_tg"), d["telefono"])
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=aviso_admin, reply_markup=boton)
        return ConversationHandler.END

    await update.message.reply_text("Elige una fecha:", reply_markup=ReplyKeyboardRemove())
    hoy = datetime.date.today()
    await update.message.reply_text(
        "📅 Selecciona el día:", reply_markup=generar_calendario(hoy.year, hoy.month)
    )
    return FECHA

async def calendario_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "IGNORE":
        return FECHA

    partes = data.split("|")

    if partes[0] == "NAV":
        anio, mes = int(partes[1]), int(partes[2])
        await query.edit_message_text("📅 Selecciona el día:", reply_markup=generar_calendario(anio, mes))
        return FECHA

    anio, mes, dia = int(partes[1]), int(partes[2]), int(partes[3])
    fecha = datetime.date(anio, mes, dia)
    context.user_data["fecha"] = fecha

    servicio = context.user_data["servicio"]
    duracion_min = SERVICIOS_FIJOS[servicio]["duracion_min"]
    disponibles = obtener_horarios_disponibles(fecha, duracion_min)

    if not disponibles:
        await query.edit_message_text(
            f"No hay horarios disponibles el {fecha.strftime('%d/%m/%Y')}. Elige otra fecha:",
            reply_markup=generar_calendario(anio, mes),
        )
        return FECHA

    context.user_data["horarios_disponibles"] = disponibles
    opciones = [h.strftime("%H:%M") for h in disponibles]
    teclado = ReplyKeyboardMarkup([[o] for o in opciones], one_time_keyboard=True, resize_keyboard=True)
    await query.edit_message_text(f"Fecha seleccionada: {fecha.strftime('%d/%m/%Y')}")
    await context.bot.send_message(
        chat_id=query.message.chat_id, text="Estos son los horarios disponibles:", reply_markup=teclado
    )
    return HORA

async def recibir_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_hora = update.message.text
    disponibles = context.user_data.get("horarios_disponibles", [])
    opciones_validas = {h.strftime("%H:%M"): h for h in disponibles}

    if texto_hora not in opciones_validas:
        await update.message.reply_text(
            "Esa hora no es válida o ya no está disponible. Elige una de las opciones mostradas."
        )
        return HORA

    context.user_data["hora_dt"] = opciones_validas[texto_hora]
    d = context.user_data
    servicio_info = SERVICIOS_FIJOS[d["servicio"]]
    resumen = (
        f"Confirma tu cita:\n\n"
        f"Nombre: {d['nombre']}\n"
        f"Teléfono: {d['telefono']}\n"
        f"Servicio: {d['servicio']}\n"
        f"Fecha: {d['fecha'].strftime('%d/%m/%Y')}\n"
        f"Hora: {texto_hora}\n"
        f"Duración: {servicio_info['duracion_min']} min\n"
        f"Costo: ${servicio_info['precio']}\n\n"
        f"Escribe SI para confirmar o NO para cancelar."
    )
    await update.message.reply_text(resumen, reply_markup=ReplyKeyboardRemove())
    return CONFIRMAR

async def confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    respuesta = update.message.text.strip()
    d = context.user_data

    if not es_afirmativo(respuesta):
        await update.message.reply_text("Cita cancelada. Escribe /agendar para intentar de nuevo.")
        return ConversationHandler.END

    servicio_info = SERVICIOS_FIJOS[d["servicio"]]
    inicio = d["hora_dt"]

    # Revalidar disponibilidad: puede que alguien más haya tomado este horario
    # mientras el cliente llenaba el formulario.
    disponibles_actuales = obtener_horarios_disponibles(d["fecha"], servicio_info["duracion_min"])
    if inicio not in disponibles_actuales:
        await update.message.reply_text(
            "Justo se ocupó ese horario mientras confirmabas 😕. "
            "Elige otra fecha con /agendar."
        )
        return ConversationHandler.END

    try:
        crear_evento(
            nombre=d["nombre"],
            telefono=d["telefono"],
            servicio=d["servicio"],
            inicio=inicio,
            duracion_min=servicio_info["duracion_min"],
            precio=servicio_info["precio"],
            chat_id=update.effective_chat.id,
            username_tg=d.get("username_tg"),
        )
    except Exception as e:
        await update.message.reply_text(
            "Hubo un problema al agendar tu cita en el calendario. Intenta de nuevo más tarde."
        )
        print(f"Error creando evento: {e}")
        return ConversationHandler.END

    await update.message.reply_text("¡Cita confirmada! Te enviaremos un recordatorio antes de tu cita.")

    aviso_admin = (
        f"✅ Nueva cita agendada\n\n"
        f"Nombre: {d['nombre']}\n"
        f"Teléfono: {d['telefono']}\n"
        f"Servicio: {d['servicio']}\n"
        f"Fecha: {d['fecha'].strftime('%d/%m/%Y')}\n"
        f"Hora: {inicio.strftime('%H:%M')}\n"
        f"Costo: ${servicio_info['precio']}"
    )
    boton = boton_contacto(d.get("username_tg"), d["telefono"])
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=aviso_admin, reply_markup=boton)
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def manejador_errores(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Excepción no manejada: {context.error}")

    # Avisar al cliente, si sabemos a quién
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Ocurrió un error inesperado. Intenta de nuevo con /agendar o /miscitas.",
            )
        except Exception:
            pass

    # Avisarte a ti con el detalle técnico
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"⚠️ Error en el bot:\n{context.error}",
        )
    except Exception:
        pass
# ----------------------- Recordatorios automáticos -----------------------

async def verificar_recordatorios(context: ContextTypes.DEFAULT_TYPE):
    citas = obtener_citas_proximas(horas_adelante=26)
    ahora = datetime.datetime.now()

    for cita in citas:
        if not cita["chat_id"]:
            continue
        horas_restantes = (cita["inicio"] - ahora).total_seconds() / 3600

        if 23.83 <= horas_restantes <= 24.17 and cita["recordatorio_24h"] != "si":
            await context.bot.send_message(
                chat_id=cita["chat_id"],
                text=f"🔔 Recordatorio: tienes una cita de {cita['servicio']} mañana a las {cita['inicio'].strftime('%H:%M')}.",
            )
            marcar_recordatorio(cita["event_id"], "recordatorio_24h")

        if 1.83 <= horas_restantes <= 2.17 and cita["recordatorio_2h"] != "si":
            await context.bot.send_message(
                chat_id=cita["chat_id"],
                text=f"🔔 Recordatorio: tu cita de {cita['servicio']} es hoy a las {cita['inicio'].strftime('%H:%M')} (en 2 horas).",
            )
            marcar_recordatorio(cita["event_id"], "recordatorio_2h")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    botones = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕒 Horarios", callback_data="FAQ_HORARIOS")],
        [InlineKeyboardButton("📍 Ubicación", callback_data="FAQ_UBICACION")],
        [InlineKeyboardButton("📋 Políticas", callback_data="FAQ_POLITICAS")],
        [InlineKeyboardButton("🛍️ Otros productos", callback_data="FAQ_PRODUCTOS")],
        [InlineKeyboardButton("📅 Agendar cita", callback_data="FAQ_AGENDAR")],
        [InlineKeyboardButton("📌 Mis citas", callback_data="FAQ_MISCITAS")],
    ])
    await update.message.reply_text("¿Qué te gustaría saber?", reply_markup=botones)

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    respuestas = {
        "FAQ_HORARIOS": (
            "🕒 Atendemos:\n"
            "Lunes, martes, viernes y domingo, de 3:00 pm a 6:00 pm."
        ),
        "FAQ_UBICACION": (
            "📍 Nos encontramos en:\n"
            "Calle Sur 10, esquina con Oriente 4, Col. Jardín, "
            "Valle de Chalco, Estado de México."
        ),
        "FAQ_POLITICAS": (
            "📋 Políticas:\n\n"
            "• Para servicios a domicilio, te pedimos avisar con al menos "
            "24 horas de anticipación si necesitas cancelar.\n"
            "• Los adelantos no son reembolsables.\n"
            "• Aceptamos pago por transferencia."
        ),
        "FAQ_PRODUCTOS": (
            "🛍️ También manejamos productos Jafra, Mary Kay y tratamientos "
            "capilares.\n\nPuedes apartar tu pedido dejando el 50% de anticipo."
        ),
    }
    if data == "FAQ_AGENDAR":
        await query.edit_message_text("¡Vamos a agendar tu cita! ¿Cuál es tu nombre?")
        return NOMBRE

    if data == "FAQ_MISCITAS":
        chat_id = query.from_user.id
        citas = obtener_citas_cliente(chat_id)
        if not citas:
            await query.edit_message_text("No tienes citas próximas agendadas.")
            return
        await query.edit_message_text("Aquí tienes tus citas:")
        for cita in citas:
            texto_cita = (
                f"📌 {cita['servicio']}\n"
                f"Fecha: {cita['inicio'].strftime('%d/%m/%Y')}\n"
                f"Hora: {cita['inicio'].strftime('%H:%M')}\n"
                f"Costo: ${cita['precio']}"
            )
            botones_cita = InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancelar", callback_data=f"MC_CANCEL|{cita['event_id']}"),
                InlineKeyboardButton("🔄 Reagendar", callback_data=f"MC_RESCHED|{cita['event_id']}"),
            ]])
            await context.bot.send_message(
                chat_id=query.message.chat_id, text=texto_cita, reply_markup=botones_cita
            )
        return

    texto = respuestas.get(data, "No encontré esa información.")
    botones_volver = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Volver al menú", callback_data="FAQ_MENU")
    ]])

    if data == "FAQ_MENU":
        botones = InlineKeyboardMarkup([
            [InlineKeyboardButton("🕒 Horarios", callback_data="FAQ_HORARIOS")],
            [InlineKeyboardButton("📍 Ubicación", callback_data="FAQ_UBICACION")],
            [InlineKeyboardButton("📋 Políticas", callback_data="FAQ_POLITICAS")],
            [InlineKeyboardButton("🛍️ Otros productos", callback_data="FAQ_PRODUCTOS")],
            [InlineKeyboardButton("📅 Agendar cita", callback_data="FAQ_AGENDAR")],
            [InlineKeyboardButton("📌 Mis citas", callback_data="FAQ_MISCITAS")],
        ])
        await query.edit_message_text("¿Qué te gustaría saber?", reply_markup=botones)
        return

    await query.edit_message_text(texto, reply_markup=botones_volver)
# ----------------------- /miscitas: cancelar y reagendar -----------------------

async def mis_citas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    citas = obtener_citas_cliente(chat_id)

    if not citas:
        await update.message.reply_text("No tienes citas próximas agendadas.")
        return

    for cita in citas:
        texto = (
            f"📌 {cita['servicio']}\n"
            f"Fecha: {cita['inicio'].strftime('%d/%m/%Y')}\n"
            f"Hora: {cita['inicio'].strftime('%H:%M')}\n"
            f"Costo: ${cita['precio']}"
        )
        botones = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancelar", callback_data=f"MC_CANCEL|{cita['event_id']}"),
            InlineKeyboardButton("🔄 Reagendar", callback_data=f"MC_RESCHED|{cita['event_id']}"),
        ]])
        await update.message.reply_text(texto, reply_markup=botones)

async def miscitas_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.from_user.id

    if data.startswith("MC_CANCEL|"):
        event_id = data.split("|", 1)[1]
        botones = InlineKeyboardMarkup([[
            InlineKeyboardButton("Sí, cancelar", callback_data=f"MC_CANCEL_YES|{event_id}"),
            InlineKeyboardButton("No", callback_data="MC_DISMISS"),
        ]])
        await query.edit_message_text("¿Seguro que quieres cancelar esta cita?", reply_markup=botones)
        return

    if data == "MC_DISMISS":
        await query.edit_message_text("De acuerdo, no se hizo ningún cambio.")
        return

    if data.startswith("MC_CANCEL_YES|"):
        event_id = data.split("|", 1)[1]
        eliminar_evento(event_id)
        await query.edit_message_text("Tu cita fue cancelada.")
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=f"❌ El cliente canceló una cita (id: {event_id})"
        )
        return

    if data.startswith("MC_RESCHED|"):
        event_id = data.split("|", 1)[1]
        citas = obtener_citas_cliente(chat_id)
        cita = next((c for c in citas if c["event_id"] == event_id), None)
        if not cita:
            await query.edit_message_text("No encontré esa cita (quizás ya pasó o fue modificada).")
            return
        context.user_data["resched_event_id"] = event_id
        context.user_data["resched_cita"] = cita
        hoy = datetime.date.today()
        await query.edit_message_text(
            f"Elige la nueva fecha para tu cita de {cita['servicio']}:",
            reply_markup=generar_calendario(hoy.year, hoy.month, prefijo_nav="MC_RNAV", prefijo_dia="MC_RDIA"),
        )
        return

    if data.startswith("MC_RNAV|"):
        _, anio, mes = data.split("|")
        await query.edit_message_text(
            "Elige la nueva fecha:",
            reply_markup=generar_calendario(int(anio), int(mes), prefijo_nav="MC_RNAV", prefijo_dia="MC_RDIA"),
        )
        return

    if data.startswith("MC_RDIA|"):
        _, anio, mes, dia = data.split("|")
        fecha = datetime.date(int(anio), int(mes), int(dia))
        cita = context.user_data.get("resched_cita")
        event_id = context.user_data.get("resched_event_id")
        disponibles = obtener_horarios_disponibles(fecha, cita["duracion_min"], ignorar_event_id=event_id)

        if not disponibles:
            await query.edit_message_text(
                f"No hay horarios disponibles el {fecha.strftime('%d/%m/%Y')}. Elige otra fecha:",
                reply_markup=generar_calendario(int(anio), int(mes), prefijo_nav="MC_RNAV", prefijo_dia="MC_RDIA"),
            )
            return

        botones = [[InlineKeyboardButton(h.strftime("%H:%M"), callback_data=f"MC_RHORA|{h.isoformat()}")]
                   for h in disponibles]
        await query.edit_message_text(
            f"Horarios disponibles el {fecha.strftime('%d/%m/%Y')}:",
            reply_markup=InlineKeyboardMarkup(botones),
        )
        return

    if data.startswith("MC_RHORA|"):
        _, iso = data.split("|", 1)
        nueva_hora = datetime.datetime.fromisoformat(iso)
        context.user_data["resched_nueva_hora"] = nueva_hora
        cita = context.user_data["resched_cita"]
        botones = InlineKeyboardMarkup([[
            InlineKeyboardButton("Sí, confirmar", callback_data="MC_RCONFIRM_YES"),
            InlineKeyboardButton("No", callback_data="MC_DISMISS"),
        ]])
        await query.edit_message_text(
            f"¿Confirmas cambiar tu cita de {cita['servicio']} a {nueva_hora.strftime('%d/%m/%Y %H:%M')}?",
            reply_markup=botones,
        )
        return

    if data == "MC_RCONFIRM_YES":
        cita = context.user_data.get("resched_cita")
        event_id = context.user_data.get("resched_event_id")
        nueva_hora = context.user_data.get("resched_nueva_hora")

        eliminar_evento(event_id)
        crear_evento(
            nombre=cita["nombre"],
            telefono=cita["telefono"],
            servicio=cita["servicio"],
            inicio=nueva_hora,
            duracion_min=cita["duracion_min"],
            precio=cita["precio"],
            chat_id=chat_id,
            username_tg=cita.get("username_tg"),
        )
        await query.edit_message_text("¡Tu cita fue reagendada con éxito!")
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🔄 Cita reagendada\n\n"
                f"Cliente: {cita['nombre']}\n"
                f"Servicio: {cita['servicio']}\n"
                f"Nueva fecha: {nueva_hora.strftime('%d/%m/%Y %H:%M')}"
            ),
        )
        return


# ----------------------- Registro de handlers -----------------------

conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("agendar", agendar),
        CallbackQueryHandler(info_callback, pattern=r"^FAQ_AGENDAR$"),
    ],
    states={
        NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
        TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono)],
        SERVICIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_servicio)],
        FECHA: [CallbackQueryHandler(calendario_callback, pattern=r"^(NAV\||DIA\||IGNORE$)")],
        HORA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_hora)],
        CONFIRMAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirmar)],
    },
    fallbacks=[
        CommandHandler("cancelar", cancelar),
        CommandHandler("agendar", agendar),
    ],
    conversation_timeout=600,
)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("info", info))
app.add_handler(conv_handler)
app.add_handler(CommandHandler("miscitas", mis_citas))
app.add_handler(CallbackQueryHandler(miscitas_callback, pattern=r"^MC_"))
app.add_handler(CallbackQueryHandler(info_callback, pattern=r"^FAQ_"))
app.add_error_handler(manejador_errores)
app.job_queue.run_repeating(verificar_recordatorios, interval=600, first=10)


if __name__ == "__main__":
    app.run_polling()