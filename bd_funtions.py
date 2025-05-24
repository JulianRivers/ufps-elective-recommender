import re

from flask import app

def _convertir_periodo_a_formato_semestre(periodo_str):
    match = re.search(r"(\w+)\s+período\s+de\s+(\d{4})", periodo_str, re.IGNORECASE)
    if match:
        periodo_tipo = match.group(1).lower()
        año = match.group(2)
        if "primer" in periodo_tipo: return f"{año}-1"
        elif "segundo" in periodo_tipo: return f"{año}-2"
    return periodo_str 

def registrar_estudiante_y_cursos_en_neo4j(driver_instance, datos_estudiante):
    """
    Registra la información del estudiante y sus cursos en Neo4j.
    Usa la instancia del driver global pasada como argumento.
    No realiza logging interno.
    """
    if not driver_instance:
        # print("Error: El driver de Neo4j no está inicializado.") # Podrías usar print si es para depuración rápida
        return False # O lanzar una excepción específica

    info_personal = datos_estudiante.get("informacion_estudiante", {})
    historial = datos_estudiante.get("historial_academico", [])

    if not info_personal.get("codigo_estudiante") or not info_personal.get("nombre"):
        # print("Error: Datos del estudiante incompletos para Neo4j.")
        return False # O lanzar una excepción

    student_id = info_personal["codigo_estudiante"]
    student_name = info_personal["nombre"]

    # El bloque try-except principal se mantiene para manejar errores de sesión de Neo4j
    # y devolver True/False, pero no logueará el error aquí.
    try:
        with driver_instance.session() as session:
            query_estudiante = """
            MERGE (s:Student {studentId: $studentId})
            ON CREATE SET s.name = $studentName
            """
            session.run(query_estudiante, studentId=student_id, studentName=student_name)
            # No hay logger.info aquí

            for semestre_data in historial:
                periodo_original = semestre_data.get("periodo")
                cursos_semestre = semestre_data.get("cursos", [])
                for curso in cursos_semestre:
                    course_id = curso.get("codigo")
                    grade = curso.get("definitiva")
                    tipo_nota = curso.get("tipo_nota")
                    if not course_id or grade is None:
                        # No hay logger.warning aquí
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
                    # El try-except interno para la relación se mantiene para que un error
                    # en un curso no detenga el procesamiento de otros, pero no loguea.
                    try:
                        session.run(query_relacion, 
                                    studentId=student_id, courseId=course_id, 
                                    grade=grade, semester_taken=semester_taken)
                        # No hay logger.debug aquí
                    except Exception as e_rel:
                        # No hay logger.error aquí
                        # Podrías decidir relanzar la excepción o simplemente continuar:
                        # print(f"Error procesando relación para curso {course_id}: {e_rel}") # Para depuración
                        pass # Continuar con el siguiente curso
        return True
    except Exception as e_session:
        # No hay logger.error aquí
        # La excepción se propagará si no la manejas aquí, o puedes devolver False.
        # print(f"Error general en sesión Neo4j: {e_session}") # Para depuración
        return False