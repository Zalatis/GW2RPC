import ctypes
import os.path
import subprocess

rpc_path = "gw2rpc.exe"
gw2_64_path = "../../Gw2-64.exe"
gw2_path = "../../Gw2.exe"
tasklist = subprocess.check_output(['tasklist'], shell=True)


def Mbox(title, text, style):
    return ctypes.windll.user32.MessageBoxW(0, text, title, style)


def check_gw():
    if os.path.isfile(gw2_64_path):
        if b"Gw2-64.exe" not in tasklist:
            subprocess.Popen([gw2_64_path])
            print("Started 64")
    elif os.path.isfile(gw2_path):
        if b"Gw2.exe" not in tasklist:
            subprocess.Popen([gw2_path])
            print("Started 32")
    else:
        Mbox('Erreur', 'GW2 non trouvé. Veuillez déplacer les fichiers RPC dans '
             'addons\RPC\ situé dans le dossier d\'installation de GW2.', 0)


def check_rpc():
    if os.path.isfile(rpc_path):
        if b"gw2rpc.exe" not in tasklist:
            subprocess.Popen([rpc_path])
            print("RPC Lancé")
    else:
        Mbox('Erreur', 'gw2rpc.exe non trouvé. Veuillez déplacer les fichiers RPC dans '
             'addons\RPC\ situé dans le dossier d\'installation de GW2.', 0)


if __name__ == "__main__":
    check_gw()
    check_rpc()
