ARG PORT=8001

FROM python:3.11.7-alpine
ARG PORT

ENV SERVER_PORT=$PORT

ENV POETRY_VERSION=1.8.2
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VENV=/opt/poetry-venv
ENV POETRY_CACHE_DIR=/opt/.cache

RUN python3 -m venv $POETRY_VENV \
    && $POETRY_VENV/bin/pip install -U pip setuptools \
    && $POETRY_VENV/bin/pip install poetry==${POETRY_VERSION}

ENV PATH="${PATH}:${POETRY_VENV}/bin"

WORKDIR /app
COPY poetry.lock pyproject.toml run.sh /app/

RUN poetry install 

COPY ./src /app/src

ENTRYPOINT run.sh
EXPOSE $SERVER_PORT