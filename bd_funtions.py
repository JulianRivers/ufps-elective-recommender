from dotenv import load_dotenv
from flask import app # Opcional, para .env

from funtions import *

def _convertir_periodo_a_formato_semestre(periodo_str):
    match = re.search(r"(\w+)\s+período\s+de\s+(\d{4})", periodo_str, re.IGNORECASE)
    if match:
        periodo_tipo = match.group(1).lower()
        año = match.group(2)
        if "primer" in periodo_tipo: return f"{año}-1"
        elif "segundo" in periodo_tipo: return f"{año}-2"
    return periodo_str 

def registrar_estudiante_y_cursos_en_neo4j(driver_instance, datos_estudiante): # Renombrado el parámetro
    """
    Registra la información del estudiante y sus cursos en Neo4j.
    Usa la instancia del driver global pasada como argumento.
    """
    if not driver_instance: # Verificar si el driver global está disponible
        app.logger.error("El driver de Neo4j no está inicializado. No se pueden guardar datos.")
        return False

    info_personal = datos_estudiante.get("informacion_estudiante", {})
    historial = datos_estudiante.get("historial_academico", [])

    if not info_personal.get("codigo_estudiante") or not info_personal.get("nombre"):
        app.logger.error("Datos del estudiante incompletos para Neo4j (código o nombre faltante).")
        return False

    student_id = info_personal["codigo_estudiante"]
    student_name = info_personal["nombre"]

    try: # Envolver toda la operación de sesión en un try-except
        with driver_instance.session() as session: # Usar el driver_instance recibido
            query_estudiante = """
            MERGE (s:Student {studentId: $studentId})
            ON CREATE SET s.name = $studentName
            """
            session.run(query_estudiante, studentId=student_id, studentName=student_name)
            app.logger.info(f"Estudiante {student_id} - {student_name} procesado/creado en Neo4j.")

            for semestre_data in historial:
                periodo_original = semestre_data.get("periodo")
                cursos_semestre = semestre_data.get("cursos", [])
                for curso in cursos_semestre:
                    course_id = curso.get("codigo")
                    grade = curso.get("definitiva")
                    tipo_nota = curso.get("tipo_nota")
                    if not course_id or grade is None:
                        app.logger.warning(f"Curso con datos incompletos omitido para Neo4j: {curso}")
                        continue
                    
                    semester_taken = ""
                    if tipo_nota and tipo_nota.lower() == "vacacional" and periodo_original:
                        year_match = re.search(r"(\d{4})", periodo_original)
                        semester_taken = f"{year_match.group(1)}-V" if year_match else "FormatoDesconocido-V"
                    else:
                        semester_taken = _convertir_periodo_a_formato_semestre(periodo_original)

                    query_relacion = """
                    MATCH (s:Student {studentId: $studentId})
                    MATCH (c:Course {courseId: $courseId})
                    MERGE (s)-[r:TOOK {semester_taken: $semester_taken}]->(c)
                    ON CREATE SET r.grade = toFloat($grade)
                    ON MATCH SET r.grade = toFloat($grade)
                    """
                    try:
                        session.run(query_relacion, 
                                    studentId=student_id, courseId=course_id, 
                                    grade=grade, semester_taken=semester_taken)
                        app.logger.debug(f"Relación TOOK: {student_id} -> {course_id} (Sem: {semester_taken}, Nota: {grade})")
                    except Exception as e_rel:
                        app.logger.error(f"Error al crear relación TOOK para {student_id} -> {course_id} (Sem: {semester_taken}): {e_rel}")
        return True
    except Exception as e_session:
        app.logger.error(f"Error durante la sesión de Neo4j para {student_id}: {e_session}", exc_info=True)
        return False
