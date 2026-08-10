FROM python:3.12-slim

RUN pip install --no-cache-dir \
    taxii2-client==2.3.0 \
    pymysql==1.2.0 \
    requests==2.34.2

USER 1000

CMD ["python"]
