#!/usr/bin/env bash
# Prepara una VM Oracle Cloud (Ubuntu 22.04/24.04, ARM o x86) para instagod:
# instala Docker + Compose, abre 80/443 en el firewall local de Ubuntu (Oracle
# trae iptables restrictivo además del Security List de la VCN) y crea /opt/instagod.
# Uso (en la VM, como ubuntu):  sudo bash bootstrap_oracle.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Ejecuta con sudo"; exit 1; fi

echo "▶ Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker ubuntu || true
systemctl enable --now docker

echo "▶ Firewall local (iptables de la imagen de Oracle): abre 80 y 443"
# Oracle inserta un REJECT al final de INPUT; las reglas nuevas van ANTES (-I).
for p in 80 443; do
  iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null || \
    iptables -I INPUT 6 -p tcp --dport "$p" -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then
  netfilter-persistent save
else
  apt-get install -y -qq iptables-persistent >/dev/null 2>&1 && netfilter-persistent save || true
fi

echo "▶ Swap 4G (protege al worker de OOM en el render)"
if ! swapon --show | grep -q swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "▶ /opt/instagod"
mkdir -p /opt/instagod/data /opt/instagod/out /opt/instagod/secrets
chown -R ubuntu:ubuntu /opt/instagod
# uid 1000 dentro del contenedor == ubuntu en la VM → permisos de escritura en data/

echo "✓ Listo. Cierra sesión y vuelve a entrar para usar docker sin sudo."
echo "  Siguiente: clonar el repo en /opt/instagod, copiar .env y data/, docker compose up -d --build"
