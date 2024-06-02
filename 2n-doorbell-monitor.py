#!/usr/bin/python3
import configparser
import argparse
import logging
import os
import signal
import sys
from pyVoIP.VoIP import VoIPPhone, InvalidStateError
import requests
import urllib3
import telegram
from telegram import InputFile
import asyncio
import datetime

urllib3.disable_warnings()

async def send_telegram():
    bot = telegram.Bot(token=BOT_TOKEN)
    text_message = "Someone has rung the doorbell at " + datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y")
    await bot.send_message(chat_id=GROUP_CHAT_ID, text=text_message)

    with open(image_file_path, 'rb') as image_file:
        await bot.send_photo(chat_id=GROUP_CHAT_ID, photo=InputFile(image_file))

    logging.info("[TG] Message and image sent successfully.")

def fetch_camera_snapshot(base_url, username, password):
    login_url = f"{base_url}/api/auth/login"
    snapshot_url = f"{base_url}/api/camera/snapshot"

    with requests.Session() as session:
        login_response = session.post(login_url, json={'user': username, 'password': password}, verify=False)
        if login_response.status_code == 200:
            sid = login_response.json().get('result', {}).get('sid')
            if not sid:
                logging.error("[2N] Failed to retrieve session ID (sid).")
                return
        else:
            logging.error(f"[2N] Login failed. Status code: {login_response.status_code}, Response: {login_response.text}")
            return

        params = {'sid': sid, 'width': 640, 'height': 480, 'source': 'internal', 'time': 0}
        snapshot_response = session.get(snapshot_url, params=params, verify=False)
        if snapshot_response.status_code == 200:
            with open(image_file_path, 'wb') as file:
                file.write(snapshot_response.content)
            logging.info(f"[2N] Snapshot saved as {image_file_path}")
        else:
            logging.error(f"[2N] Failed to fetch snapshot. Status code: {snapshot_response.status_code}, Response: {snapshot_response.text}")

def answer(call):
    try:
        call_from = call.request.headers['From']['number']
        #call.deny()
        # ^^^-- there's a bug in PyVoIP that needs to be looked at before we can do that
        logging.info(f"[SIP] Call received from: {call_from}")
        if call_from == sip_expected_from:
            logging.info("[SIP] Trying to fetch snapshot from doorbell")
            fetch_camera_snapshot(base_url, username, password)
            logging.info("[SIP] Sending information to telegram")
            asyncio.run(send_telegram())
    except InvalidStateError:
        pass

def daemonize():

    logging.info(f"Forking in the background...")

    if os.fork():
        sys.exit()

    os.setsid()

    if os.fork():
        sys.exit()

    sys.stdout.flush()
    sys.stderr.flush()

    with open('/dev/null', 'rb', 0) as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open('/dev/null', 'ab', 0) as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())

    with open(PID_FILE, 'w') as f:
    f.write(str(os.getpid()))
    atexit.register(lambda: os.remove(PID_FILE))

def handle_signal(signal, frame):
    global phone
    phone.stop()
    sys.exit(0)

def main(mode, config_path):
    global phone, base_url, username, password, sip_expected_from, BOT_TOKEN, GROUP_CHAT_ID, image_file_path, PID_FILE

    # Read configuration
    config = configparser.ConfigParser()
    config.read(config_path)

    base_url = config['DEFAULT']['2n_base_url']
    username = config['DEFAULT']['2n_username']
    password = config['DEFAULT']['2n_password']
    sip_username = config['DEFAULT']['sip_username']
    sip_password = config['DEFAULT']['sip_password']
    sip_domain = config['DEFAULT']['sip_domain']
    sip_expected_from = config['DEFAULT']['sip_expected_from']
    sip_myip = config['DEFAULT']['sip_myip']
    sip_myport = int(config['DEFAULT']['sip_myport'])
    sip_port = int(config['DEFAULT']['sip_port'])
    BOT_TOKEN = config['DEFAULT']['telegram_bot_token']
    GROUP_CHAT_ID = config['DEFAULT']['telegram_chat_id']
    image_file_path = config['DEFAULT']['image_file_path']
    log_file = config['DEFAULT']['log_file']
    PID_FILE = config['DEFAULT']['pid_file']

    if mode == 'daemon':
        daemonize()
        logging.basicConfig(filename=log_file, level=logging.INFO, force=True)
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
        logging.info(f"Registering SIP Extension.")
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
        logging.info(f"Registering SIP Extension. Hit ^C to exit.")

    phone = VoIPPhone(sip_domain, sip_port, sip_username, sip_password, callCallback=answer, myIP=sip_myip, sipPort=sip_myport, rtpPortLow=10000, rtpPortHigh=20000)
    phone.start()
    
    while True:
        signal.pause()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Doorbell Monitor Script')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-f', '--foreground', action='store_const', const='foreground', dest='mode', help='Run in foreground mode')
    group.add_argument('-d', '--daemon', action='store_const', const='daemon', dest='mode', help='Run in daemon mode')
    parser.add_argument('-c', '--config', type=str, default='config.ini', help='Path to the config file')
    args = parser.parse_args()
    main(args.mode, args.config)
