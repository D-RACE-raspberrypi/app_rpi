# trixie : Debian 13 pour fournir libgpiod v2 (libgpiod3 / libgpiod-dev >= 2.0)
FROM debian:trixie-slim AS build
RUN apt-get update && apt-get install -y gcc make libgpiod-dev
WORKDIR /app
COPY include/ include/
COPY src/ src/
RUN gcc -Wall -Wextra -O2 -Iinclude src/server.c src/car.c src/moteur.c src/servo.c src/utils.c -o serveur_pi -lgpiod

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends hostapd dnsmasq iproute2 \
    libgpiod3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app/serveur_pi .
RUN sudo pinctrl set 12 a0 2>/dev/null || true && sudo pinctrl set 13 a0 2>/dev/null || true
CMD ["./serveur_pi", "5000"]