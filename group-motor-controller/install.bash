echo "  Starting installation :"
REAL_USER=${SUDO_USER:-$USER}

# Docker installation script
echo "Starting Docker installation script..."
sudo rm -f /etc/apt/sources.list.d/docker.list
echo "Updating package lists and installing prerequisites..."
sudo apt update
sudo apt install -y ca-certificates curl gnupg
echo "Setting up Docker keyrings and repository..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
echo "Removing old Docker buildx plugin if it exists..."
sudo apt remove -y docker-buildx
sudo apt update
echo "Installing Docker packages..."
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
echo "Adding user ${REAL_USER} to the Docker group..."
sudo usermod -aG docker ${REAL_USER}
echo "Fixing Docker socket permissions..."
sudo chown root:docker /var/run/docker.sock
sudo chmod 660 /var/run/docker.sock
echo "f /var/run/docker.sock 0660 root docker -" | sudo tee /etc/tmpfiles.d/docker-socket.conf > /dev/null
echo "Docker installation complete."
# pour vérifier :
cat /etc/apt/sources.list.d/docker.list

# Git clone
echo "Cloning demo repository..."
git clone https://github.com/D-RACE-raspberrypi/demo-repository.git
echo "Demo repository cloned."
# pour vérifier :
cat demo-repository/rpi-serv/docker-compose.yml | grep image

# Service
echo "Setting up rpi-serv systemd service..."
sudo tee /etc/systemd/system/rpi-serv.service > /dev/null <<EOL
[Unit]
Description=Démarrage automatique du projet Docker Compose
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/drace/demo-repository/rpi-serv
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
EOL
echo "rpi-serv systemd service setup complete."
sudo systemctl daemon-reload
sudo systemctl enable rpi-serv.service
echo "rpi-serv service started."
# pour vérifier :


# add dtoverlay for pwm
echo "Adding dtoverlay for PWM..."
sudo sed -i '/^dtoverlay=pwm2-chan/d' /boot/config.txt
echo "dtoverlay=pwm2-chan" | sudo tee -a /boot/config.txt
echo "dtoverlay for PWM added."
# pour vérifier : 
cat /boot/config.txt | grep dtoverlay=pwm2-chan

echo "Fixing permanent Wi-Fi interface names (udev)..."

# 1. Récupérer dynamiquement les adresses MAC des deux puces Wi-Fi
MAC_INTERNAL=$(cat /sys/class/net/wlan0/address 2>/dev/null)
MAC_EXTERNAL=$(cat /sys/class/net/wlan1/address 2>/dev/null)

# 2. Si deux puces sont détectées, on fige leurs rôles pour éviter l'inversion au reboot
if [ ! -z "$MAC_INTERNAL" ] && [ ! -z "$MAC_EXTERNAL" ]; then
    sudo tee /etc/udev/rules.d/70-persistent-net.rules > /dev/null <<EOL
# Carte Wi-Fi Principale (Client ou Hôte selon votre proto)
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="$MAC_INTERNAL", NAME="wlan0"

# Carte Wi-Fi Dédiée au Point d'Accès (drace_serv)
SUBSYSTEM=="net", ACTION=="add", DRIVERS=="?*", ATTR{address}=="$MAC_EXTERNAL", NAME="wlan1"
EOL
    echo "Udev rules created successfully."
else
    echo "Warning: Less than two Wi-Fi interfaces detected. Skipping permanent naming."
fi

# 3. Forcer le pays Wi-Fi

echo "Setting Wi-Fi Country to FR..."
sudo raspi-config nonint do_wifi_country FR
echo "Wi-Fi Country set to FR."
echo "Isolating wlan1 from host network management..."
# Pour NetworkManager
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/99-ignore-wlan1.conf > /dev/null <<EOL
[keyfile]
unmanaged-devices=interface-name:wlan1
EOL
sudo systemctl restart NetworkManager || true

# Pour l'ancien dhcpcd (au cas où)
if [ -f /etc/dhcpcd.conf ]; then
    sudo sed -i '/denyinterfaces wlan1/d' /etc/dhcpcd.conf
    echo "denyinterfaces wlan1" | sudo tee -a /etc/dhcpcd.conf
    sudo systemctl restart dhcpcd || true
fi


# End of installation script
echo "  Installation script complete."

# Build le Docker container
echo "Building rpi-serv Docker container..."
sudo docker compose -f /home/drace/demo-repository/rpi-serv/docker-compose.yml build
echo "rpi-serv Docker container built."

# Lance le docker 
echo "Starting rpi-serv Docker container..."
sudo docker compose -f /home/drace/demo-repository/rpi-serv/docker-compose.yml up -d
echo "rpi-serv Docker container started."

# reboot pour finir :
echo "Un redémarrage est nécessaire pour appliquer les configurations du groupe Docker et du PWM."
read -p "Souhaitez-vous redémarrer le Raspberry Pi maintenant ? (y/n) " reponse
if [[ "$reponse" =~ ^[YyLlOo] ]]; then
    echo "Fermeture des sessions et redémarrage en cours..."
    sudo pkill -u ${REAL_USER} -f sshdd || true
    sudo sleep 1
    sudo reboot
fi