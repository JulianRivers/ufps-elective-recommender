import os
from flask import Flask, request, jsonify
from neo4j import GraphDatabase, basic_auth
from dotenv import load_dotenv # Opcional, para .env

from funtions import *

# Cargar variables de entorno (opcional)
load_dotenv()

app = Flask(__name__)

# --- Configuración de Neo4j ---
# Usa variables de entorno o valores por defecto si no están definidas
NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', 'password') # Cambia 'password' por tu contraseña por defecto si no usas .env

# Crear el driver de Neo4j una sola vez
# Es importante manejar la conexión de forma eficiente en producción
try:
    driver = GraphDatabase.driver(NEO4J_URI, auth=basic_auth(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity() # Comprueba la conexión al iniciar
    print("Conexión a Neo4j establecida.")
except Exception as e:
    print(f"Error al conectar a Neo4j: {e}")
    driver = None # Marcar como no conectado si falla

# --- Consulta Cypher ---
# Adaptada para usar parámetros y con coalesce para el tipo de electiva
RECOMMENDATION_QUERY = """
// Parámetros: $targetStudentId, $passingGrade
WITH $targetStudentId AS targetStudentId, $passingGrade AS passingGrade

// --- 1. Encontrar cursos aprobados por el estudiante y calcular créditos totales ---
MATCH (s:Student {studentId: targetStudentId})-[took_rel:TOOK]->(approved_course:Course)
WHERE took_rel.grade >= passingGrade
WITH s,
     collect(approved_course) AS approvedCoursesList,
     sum(coalesce(approved_course.credits, 0)) AS totalApprovedCredits // Usar coalesce si credits puede ser NULL

// --- 2. Encontrar electivas potenciales (profesionales, no cursadas) ---
MATCH (potential_elective:Course)
// Asegura que es electiva y NO Sociohumanística (o no tiene tipo definido explícitamente)
WHERE potential_elective.is_elective = true
  AND coalesce(potential_elective.elective_type, 'Professional') <> 'Sociohumanistic' // Asume 'Professional' si no hay tipo
  AND NOT (s)-[:TOOK]->(potential_elective)
  AND size(approvedCoursesList) > 0 // El estudiante debe haber aprobado al menos un curso

// --- 3. Verificar TODOS los prerrequisitos de CURSO ---
AND NOT EXISTS {
    MATCH (potential_elective)-[:REQUIRES]->(req:Course)
    WHERE NOT req IN approvedCoursesList
}

// --- 4. Verificar el requisito de CRÉDITOS MÍNIMOS (si existe) ---
AND (potential_elective.minCreditsRequired IS NULL OR totalApprovedCredits >= potential_elective.minCreditsRequired)

// --- 5. Calcular un puntaje basado en las notas de los prerrequisitos DIRECTOS ---
OPTIONAL MATCH (potential_elective)-[:REQUIRES]->(prereq_for_score:Course)<-[took_prereq_rel:TOOK]-(s)
// Agrupamos por electiva para calcular el promedio de notas de sus prerrequisitos
WITH potential_elective,
     avg(took_prereq_rel.grade) AS avgPrereqGradeScore

// --- 6. Devolver las electivas elegibles, ordenadas por el puntaje ---
RETURN potential_elective.courseId AS id_materia_recomendada,
       potential_elective.name AS nombre_materia,
       coalesce(avgPrereqGradeScore, 0.0) AS puntaje_recomendacion // Asigna puntaje 0 si no hay prerreqs o no se encontraron notas
ORDER BY puntaje_recomendacion DESC
"""
@app.route('/')
def hello_world():
    return 'Hola Mundo desde Flask!'

# --- Ruta de la API ---
@app.route('/recommendations/student/<string:student_id>', methods=['GET'])
def get_recommendations(student_id):
    """
    Endpoint para obtener recomendaciones de electivas profesionales para un estudiante.
    """
    if not driver:
        return jsonify({"error": "No se pudo conectar a la base de datos Neo4j"}), 500

    # Obtener parámetros opcionales de la URL (query parameters)
    try:
        # Nota mínima para considerar un curso aprobado
        passing_grade = float(request.args.get('passingGrade', 3.0))
    except ValueError:
        return jsonify({"error": "El parámetro 'passingGrade' debe ser un número."}), 400

    recommendations = []
    try:
        # Usar una sesión para ejecutar la consulta
        with driver.session() as session:
            result = session.run(RECOMMENDATION_QUERY,
                                 targetStudentId=student_id,
                                 passingGrade=passing_grade)

            # Procesar los resultados
            for record in result:
                recommendations.append({
                    "id": record["id_materia_recomendada"],
                    "name": record["nombre_materia"],
                    "score": record["puntaje_recomendacion"]
                })

        # Verificar si se encontraron recomendaciones
        if not recommendations:
             # Podríamos verificar primero si el estudiante existe para dar un mensaje más específico
             student_exists = check_student_exists(student_id)
             if not student_exists:
                  return jsonify({"message": f"Estudiante con ID '{student_id}' no encontrado."}), 404
             else:
                  return jsonify({"message": f"No se encontraron electivas recomendadas para el estudiante '{student_id}' que cumplan los criterios.", "recommendations": []}), 200


        return jsonify(recommendations)

    except Exception as e:
        # Manejo básico de errores (mejorar en producción)
        print(f"Error al ejecutar consulta para estudiante {student_id}: {e}")
        return jsonify({"error": "Ocurrió un error al procesar la solicitud."}), 500

def check_student_exists(student_id):
    """Función auxiliar para verificar si un estudiante existe."""
    if not driver: return False
    try:
        with driver.session() as session:
            result = session.run("MATCH (s:Student {studentId: $sid}) RETURN count(s) > 0 AS exists", sid=student_id)
            record = result.single()
            return record["exists"] if record else False
    except Exception as e:
        print(f"Error verificando existencia de estudiante {student_id}: {e}")
        return False # Asumir que no existe si hay error

# --- Manejo del cierre del driver ---
@app.teardown_appcontext
def close_neo4j_driver(exception=None):
    """Cierra el driver de Neo4j al terminar la aplicación."""
    # En una app real, la gestión del driver podría ser más sofisticada.
    # Este cierre aquí es más relevante si el driver se creara por request.
    # Si el driver es global, se cierra al detener el script Flask.
    pass # El driver global se cierra al final


# Consideración final: Cerrar el driver explícitamente al salir del script principal
# Esto es importante para liberar recursos correctamente.
# El bloque try/finally asegura que se intente cerrar incluso si hay errores al iniciar Flask.
try:
    # El código para iniciar la app (app.run) estaría aquí en un escenario real sin el if __name__ == '__main__'
    pass
finally:
    if driver:
        print("Cerrando conexión a Neo4j.")
        driver.close()
    

@app.route('/procesar-pdf', methods=['POST'])
def procesar_pdf_endpoint():
    if 'file' not in request.files:
        return jsonify({"error": "No se encontró el parámetro 'file' en la solicitud."}), 400
    
    archivo = request.files['file']
    
    if archivo.filename == '':
        return jsonify({"error": "No se seleccionó ningún archivo."}), 400
        
    if archivo and archivo.filename.lower().endswith('.pdf'):
        try:
            texto_extraido = extraer_texto_de_pdf(archivo.stream) 
            
            if texto_extraido is None:
                return jsonify({"error": "No se pudo extraer texto del PDF. El archivo podría estar corrupto o vacío."}), 500

            datos_parseados = parse_notas_desde_texto(texto_extraido)
            
            # Puedes añadir validaciones aquí si quieres, por ejemplo, si datos_parseados está muy vacío
            if not datos_parseados.get("informacion_estudiante") or not datos_parseados.get("informacion_estudiante").get("nombre"):
                 print("Advertencia (Flask Endpoint): La información del estudiante parece incompleta después del parseo.")
                 # Podrías devolver un error o una advertencia en el JSON aquí si es crítico

            return jsonify(datos_parseados), 200
            
        except Exception as e:
            # Loggear el error en el servidor
            app.logger.error(f"Error procesando el PDF: {e}", exc_info=True)
            return jsonify({"error": f"Ocurrió un error interno al procesar el PDF: {str(e)}"}), 500
    else:
        return jsonify({"error": "El archivo debe ser un PDF."}), 400

if __name__ == '__main__':
    app.run(debug=True)