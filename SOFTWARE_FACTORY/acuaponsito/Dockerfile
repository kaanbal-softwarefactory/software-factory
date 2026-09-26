# Acuaponsito Agent Runtime — contenedor mínimo (stdlib puro, sin pip)
FROM python:3.12-alpine

WORKDIR /app
COPY server.py .
COPY static ./static

# Monta tu repertorio de clips:  -v /ruta/animacion:/anim
ENV KAANBAL_ANIM_DIR=/anim
ENV ACUA_DATA_DIR=/data
ENV ACUA_PORT=4600
VOLUME ["/data", "/anim"]
EXPOSE 4600

CMD ["python", "server.py"]
