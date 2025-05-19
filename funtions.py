import pdfplumber
import re
import json
import io


# --- Tus funciones de extracción y parseo (exactamente como las tenías) ---
def extraer_texto_de_pdf(archivo_pdf_stream): # Modificado para aceptar un stream
    texto_completo = ""
    try:
        # pdfplumber.open() puede trabajar directamente con un stream de archivo
        with pdfplumber.open(archivo_pdf_stream) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    texto_completo += texto_pagina + "\n"
    except Exception as e:
        # En una API, es mejor loggear el error o devolver un mensaje de error más específico
        print(f"Error al leer el PDF: {e}")
        return None
    return texto_completo

def parse_notas_desde_texto(texto_ocr):
    if not texto_ocr:
        # print("No se pudo extraer texto del PDF o el texto está vacío.") # Se maneja en el endpoint
        return {
            "informacion_estudiante": {},
            "historial_academico": []
        }

    lines = texto_ocr.strip().split('\n')

    student_info = {
        "nombre": None,
        "codigo_estudiante": None,
        "promedio_general": None,
        "creditos_aprobados_pensum": None
    }
    academic_history = []
    current_semester_data = None

    course_pattern = re.compile(
        r"^(?P<code>\d{6,7})\s+(?P<materia>.+?)\s+(?P<tipo_nota>Definitiva|Vacacional)\s+(?P<definitiva>[\d\.]+)\s*(?P<habilitacion>-|[\d\.]*)?\s*$"
    )
    semester_pattern = re.compile(r"^(Primer|Segundo|Tercer|Cuarto|Quinto|Sexto|Septimo|Octavo|Noveno|Decimo|Undecimo|Duodecimo)\s+per[ií]odo\s+de\s+(\d{4})$", re.IGNORECASE)
    matricula_pattern = re.compile(r"^Matricula\s+honor\b\s*(.*)$", re.IGNORECASE)
    beca_pattern = re.compile(r"^Beca\b\s*(.*)$", re.IGNORECASE)

    potential_student_info_block = "\n".join(lines[:20])

    match_codigo = re.search(r"Código:\s*(\d+)", potential_student_info_block, re.IGNORECASE)
    if match_codigo:
        student_info["codigo_estudiante"] = match_codigo.group(1)
    else:
        for i, line_text in enumerate(lines[:20]):
            if "Código:" in line_text:
                val_on_line = line_text.split("Código:")[1].strip()
                if val_on_line and val_on_line.isdigit():
                    student_info["codigo_estudiante"] = val_on_line
                    break
                elif i + 1 < len(lines):
                    possible_code = lines[i+1].strip()
                    if possible_code.isdigit():
                        student_info["codigo_estudiante"] = possible_code
                        break
    
    match_nombre = re.search(r"Nombre:\s*(.+?)(?:\s*Promedio:|$)", potential_student_info_block, re.IGNORECASE | re.DOTALL)
    if match_nombre:
        student_info["nombre"] = match_nombre.group(1).strip()
    else:
        for i, line_text in enumerate(lines[:20]):
            if "Nombre:" in line_text:
                val_on_line = line_text.split("Nombre:")[1].strip()
                if val_on_line and not val_on_line.isdigit(): # Asegurarse que no es un número
                     student_info["nombre"] = val_on_line.split("Promedio:")[0].strip() # Por si Promedio está en la misma linea
                     break
                elif i + 1 < len(lines):
                    possible_name = lines[i+1].strip()
                    if possible_name and not possible_name.isdigit(): # Asegurarse que no es un número
                        student_info["nombre"] = possible_name.split("Promedio:")[0].strip()
                        break

    match_prom_cred = re.search(r"Promedio:\s*([\d\.]+)\s*Créditos\s+aprobados\s+Pensum:\s*(\d+)", potential_student_info_block, re.IGNORECASE | re.DOTALL)
    if match_prom_cred:
        try:
            student_info["promedio_general"] = float(match_prom_cred.group(1))
        except ValueError:
            print(f"Advertencia (Flask): No se pudo convertir el promedio '{match_prom_cred.group(1)}' a número.")
        try:
            student_info["creditos_aprobados_pensum"] = int(match_prom_cred.group(2))
        except ValueError:
            print(f"Advertencia (Flask): No se pudo convertir créditos pensum '{match_prom_cred.group(2)}' a número.")
    else:
        match_promedio = re.search(r"Promedio:\s*([\d\.]+)", potential_student_info_block, re.IGNORECASE)
        if match_promedio:
            try: student_info["promedio_general"] = float(match_promedio.group(1))
            except ValueError: print(f"Advertencia (Flask): No se pudo convertir el promedio '{match_promedio.group(1)}' a número.")
        
        match_creditos = re.search(r"Créditos\s+aprobados\s+Pensum:\s*(\d+)", potential_student_info_block, re.IGNORECASE)
        if match_creditos:
            try: student_info["creditos_aprobados_pensum"] = int(match_creditos.group(1))
            except ValueError: print(f"Advertencia (Flask): No se pudo convertir créditos pensum '{match_creditos.group(1)}' a número.")

    for line_idx, line in enumerate(lines):
        line = line.strip()
        if not line: continue

        if line.startswith("UF") or line.startswith("PS") or \
           "Universidad Francisco de Paula Santander" in line or \
           "División de Sistemas" in line or \
           "Reporte de Notas Semestrales" in line or \
           line.startswith("Generado:") or \
           line.startswith("pag ") or \
           line.lower().startswith("código materia tipo nota definitiva habilitación"):
            continue

        semester_match = semester_pattern.match(line)
        if semester_match:
            if current_semester_data: academic_history.append(current_semester_data)
            period_desc = semester_match.group(1).capitalize()
            year = semester_match.group(2)
            current_semester_data = {"periodo": f"{period_desc} período de {year}", "cursos": []}
            continue

        if current_semester_data:
            course_match = course_pattern.match(line)
            if course_match:
                data = course_match.groupdict()
                habilitacion_val = None
                if data["habilitacion"] and data["habilitacion"] != "-":
                    try: habilitacion_val = float(data["habilitacion"])
                    except ValueError: habilitacion_val = data["habilitacion"]
                materia_nombre = data["materia"].strip()
                if "matricula de honor" in materia_nombre.lower() or "beca de trabajo" in materia_nombre.lower():
                    continue
                current_semester_data["cursos"].append({
                    "codigo": data["code"], "materia": materia_nombre,
                    "tipo_nota": data["tipo_nota"],
                    "definitiva": float(data["definitiva"]) if data["definitiva"] else None,
                    "habilitacion": habilitacion_val
                })
                continue
            
            matricula_info_match = matricula_pattern.match(line)
            if matricula_info_match:
                matricula_descripcion = matricula_info_match.group(1).strip()
                if matricula_descripcion: current_semester_data["matricula_honor"] = matricula_descripcion
                continue

            beca_info_match = beca_pattern.match(line)
            if beca_info_match:
                beca_descripcion = beca_info_match.group(1).strip()
                if beca_descripcion : current_semester_data["beca"] = beca_descripcion
                continue
                
    if current_semester_data: academic_history.append(current_semester_data)

    # No es necesario imprimir advertencias aquí, se pueden manejar en la respuesta del endpoint si es necesario
    return {"informacion_estudiante": student_info, "historial_academico": academic_history}
# --- Fin de tus funciones ---