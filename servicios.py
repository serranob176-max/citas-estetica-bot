# servicios.py

SERVICIOS_FIJOS = {
    "Corte de cabello": {"duracion_min": 60, "precio": 80},
    "Depilado de ceja": {"duracion_min": 40, "precio": 80},
    "Tinte (tú traes el tinte)": {"duracion_min": 60, "precio": 80, "nota": "por tubo"},
    "Tinte (lo ponemos nosotros)": {"duracion_min": 60, "precio": 150, "nota": "por tubo"},
}

SERVICIOS_A_CONSULTA = [
    "Peinado",
    "Decoloración",
    "Base",
    "Mechas",
    "Rayos",
]