FROM python:3.14-slim

WORKDIR /app

# The dedicated Timefree worker runs as 10001:20000. A fresh shared socket
# volume inherits this private directory; the regular backend remains root as
# before and does not need a broader group or filesystem permission.
RUN mkdir -p /run/timefree \
    && chown 10001:20000 /run/timefree \
    && chmod 0770 /run/timefree

RUN pip install --no-cache-dir fastapi uvicorn

COPY app.py /app/app.py
COPY radioflix /app/radioflix

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
