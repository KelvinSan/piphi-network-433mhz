FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/integration/src \
    PORT=8090

WORKDIR /integration

COPY pyproject.toml README.md /integration/

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python - <<'PY'
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as pyproject_file:
    dependencies = tomllib.load(pyproject_file)["project"]["dependencies"]

subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "--no-cache-dir", *dependencies]
)
PY

COPY src /integration/src

EXPOSE 8090

CMD ["python", "-m", "uvicorn", "piphi_network_433mhz.app:app", "--host", "0.0.0.0", "--port", "8090"]
