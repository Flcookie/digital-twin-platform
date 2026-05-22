#!/bin/bash

echo "set nocompatible" > /home/robot/.vimrc
echo "set backspace=indent,eol,start" >> /home/robot/.vimrc
echo "set nocompatible" | sudo tee /root/.vimrc > /dev/null
echo "set backspace=indent,eol,start" | sudo tee -a /root/.vimrc > /dev/null

sudo raspi-config
sudo usermod -a -G dialout robot
sudo vi /etc/systemd/timesyncd.conf

pip config set global.break-system-packages true
pip install "adafruit-circuitpython-pn532==2.4.1" --no-deps
pip install "Adafruit-Blinka==8.47.0" --no-deps
pip install "adafruit-circuitpython-busdevice==5.2.9" --no-deps
pip install "adafruit-circuitpython-typing==1.11.0" --no-deps
pip install "Adafruit-PlatformDetect==3.74.0" --no-deps
pip install "Adafruit-PureIO==1.1.11" --no-deps
pip install "binho-host-adapter==0.1.6" --no-deps
pip install "pyftdi==0.55.4" --no-deps
pip install "rpi-ws281x==5.0.0" --no-deps
pip install "sysv-ipc==1.1.0" --no-deps
pip install "adafruit-circuitpython-requests==4.1.6" --no-deps
pip install "pyusb==1.2.1" --no-deps
pip install "adafruit-circuitpython-connectionmanager==3.1.1" --no-deps
pip install "buildhat==0.7.0" --no-deps
pip install "paho.mqtt==1.6.1" --no-deps

mkdir -p Python
echo "@reboot rm -f /home/robot/Python/program.pid" | crontab -
