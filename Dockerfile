# Usar una imagen base de Python oficial
FROM python:3.9-slim

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar el archivo de requerimientos y luego instalar las dependencias
# Esto aprovecha el cache de Docker: si requirements.txt no cambia, este paso no se re-ejecuta
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código de la aplicación al directorio de trabajo
COPY . .

# Establecer variables de entorno para Flask
# FLASK_APP es el nombre de tu archivo principal (ej., app.py)
# FLASK_RUN_HOST para que escuche en todas las interfaces dentro del contenedor
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=8000
# ENV FLASK_ENV=development # O 'production' (aunque 'flask run' es más para desarrollo)

# Exponer el puerto en el que Flask correrá dentro del contenedor
EXPOSE 8000

# El comando para ejecutar la aplicación cuando el contenedor inicie
# Usamos "flask run" como solicitaste.
CMD ["flask", "run"]