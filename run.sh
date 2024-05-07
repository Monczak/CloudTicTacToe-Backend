#!/bin/bash

openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 365 -nodes -subj "/CN=cloudtictactoe.com"
poetry run hypercorn --bind 0.0.0.0:$SERVER_PORT --certfile cert.pem --keyfile key.pem src/app:app