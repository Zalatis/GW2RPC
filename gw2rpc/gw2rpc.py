import ctypes
import logging
import os
import sys
import threading
import time
import webbrowser
import math

import psutil
import requests
from infi.systray import SysTrayIcon

from .api import APIError, api  # TODO
from .character import Character
from .mumble import MumbleData
from .rpc import DiscordRPC
from .settings import config

VERSION = 2.0

GW2RPC_BASE_URL = "https://gw2rpc.info/api/v1/"

GW2RPC_APP_ID = "385475290614464513"

log = logging.getLogger()


class GameNotRunningError(Exception):
    pass


worlds = {
    'NA': [
        'Anvil Rock', 'Blackgate', 'Borlis Pass', 'Crystal Desert',
        'Darkhaven', "Devona's Rest", 'Dragonbrand', 'Ehmry Bay',
        'Eredon Terrace', "Ferguson's Crossing", 'Fort Aspenwood',
        'Gate of Madness', 'Henge of Denravi', 'Isle of Janthir',
        'Jade Quarry', 'Kaineng', 'Maguuma', 'Northern Shiverpeaks',
        'Sanctum of Rall', 'Sea of Sorrows', "Sorrow's Furnace",
        'Stormbluff Isle', 'Tarnished Coast', "Yak's Bend"
    ],
    'EU': [
        'Aurora Glade', 'Blacktide', 'Desolation', 'Far Shiverpeaks',
        'Fissure of Woe', 'Gandara', "Gunnar's Hold", 'Piken Square',
        'Ring of Fire', 'Ruins of Surmia', "Seafarer's Rest", 'Underworld',
        'Vabbi', 'Whiteside Ridge', 'Arborstone [FR]', 'Augury Rock [FR]',
        'Fort Ranik [FR]', 'Jade Sea [FR]', 'Vizunah Square [FR]',
        "Abaddon's Mouth [DE]", 'Drakkar Lake [DE]', 'Dzagonur [DE]',
        'Elona Reach [DE]', 'Kodash [DE]', "Miller's Sound [DE]",
        'Riverside [DE]', 'Baruch Bay [SP]'
    ]
}


def create_msgbox(description, *, title='GW2RPC', code=0):
    MessageBox = ctypes.windll.user32.MessageBoxW
    return MessageBox(None, description, title, code)


class GW2RPC:
    def __init__(self):
        def fetch_registry():
            url = GW2RPC_BASE_URL + "registry"
            res = requests.get(url)
            if res.status_code != 200:
                log.error("Could not fetch the web registry")
                return None
            return res.json()

        def icon_path():
            try:
                return os.path.join(sys._MEIPASS, "icon.ico")
            except:
                return "icon.ico"

        def fetch_support_invite():
            try:
                return requests.get(GW2RPC_BASE_URL +
                                    "support").json()["support"]
            except:
                return None

        self.rpc = DiscordRPC(GW2RPC_APP_ID)
        self.game = MumbleData()
        self.registry = fetch_registry()
        self.support_invite = fetch_support_invite()
        menu_options = (("About", None, self.about), )
        if self.support_invite:
            menu_options += (("Join support server", None, self.join_guild), )
        self.systray = SysTrayIcon(
            icon_path(),
            "Guild Wars 2 with Discord",
            menu_options,
            on_quit=self.shutdown)
        self.systray.start()
        self.process = None
        self.last_map_info = None
        self.last_continent_info = None
        self.last_boss = None
        self.no_pois = set()
        self.check_for_updates()

    def shutdown(self, _=None):
        os._exit(0)  # Nuclear option

    def about(self, _):
        message = (
            "Version: {}\n\nhttps://gw2rpc.info\n\nBy Maselkov & "
            "N1TR0\nIcons by Zebban\nWebsite by Penemue".format(VERSION))
        threading.Thread(target=create_msgbox, args=[message]).start()

    def join_guild(self, _):
        try:
            webbrowser.open(self.support_invite)
        except webbrowser.Error:
            pass

    def check_for_updates(self):
        def get_build():
            url = GW2RPC_BASE_URL + "build"
            r = requests.get(url)
            try:
                return r.json()["build"]
            except:
                return None

        build = get_build()
        if not build:
            log.error("Could not retrieve build!")
            create_msgbox(
                "Could not check for updates - check your connection!")
            return
        if build > VERSION:
            log.info("New version found! Current: {} New: {}".format(
                VERSION, build))
            res = create_msgbox(
                "There is a new update for GW2 Rich Presence available. "
                "Would you like to be taken to the download page now?",
                code=68)
            if res == 6:
                webbrowser.open("https://gw2rpc.info/")

    def get_map_asset(self, map_info):
        map_id = map_info["id"]
        map_name = map_info["name"]
        region = map_info.get("region_name", "thanks_anet")
        if self.registry:
            if map_name == "Fractals of the Mists":
                for fractal in self.registry["fractals"]:
                    if fractal["id"] == map_id:
                        state = fractal["name"] + " fractal"
                        image = "fotm"
                        break
                else:
                    image = "fotm"
                    state = "Fractals of the Mists"
                name = "Fractals of the Mists"
            else:
                if map_name in self.registry["special"]:
                    image = self.registry["special"][map_name]
                elif map_id in self.registry["valid"]:
                    image = map_id
                elif region in self.registry["regions"]:
                    image = self.registry["regions"][region]
                else:
                    image = "default"
                name = map_name
                state = name
        else:
            special = {
                "Fractals of the Mists": "fotm",
                "Windswept Haven": "gh_haven",
                "Gilded Hollow": "gh_hollow",
                "Lost Precipice": "gh_precipice"
            }.get(map_info["name"])
            if special:
                return special
            if map_info["type"] == "Public":
                image = map_id
            else:
                valid_ids = [1062, 1149, 1156, 38, 1264]
                if map_id in valid_ids:
                    image = map_id
                else:
                    image = "default"
            name = map_name
            state = name
        return "in " + state, {"large_image": str(image), "large_text": name}

    def get_raid_assets(self, map_info, continent_info):
        def readable_id(_id):
            _id = _id.split("_")
            dont_capitalize = ("of", "the", "in")
            return " ".join([
                x.capitalize() if x not in dont_capitalize else x for x in _id
            ])

        boss, distance = self.find_closest_point(
            map_info,
            continent_info,
            iterable=self.registry["raids"][str(map_info["id"])],
            id_only=True)
        if boss["type"] == "boss":
            state = "fighting "
        else:
            state = "completing "
        if "radius" in boss:
            if distance > boss["radius"]:
                return self.get_map_asset(map_info)
        name = readable_id(boss["id"])
        state += name
        if self.last_boss:
            if not self.last_boss == boss["id"]:
                self.game.last_timestamp = int(time.time())
        self.last_boss = boss["id"]
        return state, {"large_image": boss["id"], "large_text": name}

    def get_activity(self):
        def get_region():
            world = api.world
            if world:
                for k, v in worlds.items():
                    if world in v:
                        return " [{}]".format(k)
            return ""

        data = self.game.get_mumble_data()
        if not data:
            return None
        map_id = data["map_id"]
        try:
            if self.last_map_info and map_id == self.last_map_info["id"]:
                map_info = self.last_map_info
            else:
                map_info = api.get_map_info(map_id)
                self.last_map_info = map_info
            character = Character(data)
        except APIError:
            log.exception("API Error!")
            self.last_map_info = None
            return None
        state, map_asset = self.get_map_asset(map_info)
        tag = character.guild_tag if config.display_tag else ""
        try:
            if map_id in self.no_pois:
                raise APIError(404)
            if (self.last_continent_info
                    and map_id == self.last_continent_info["id"]):
                continent_info = self.last_continent_info
            else:
                continent_info = api.get_continent_info(map_info)
                self.last_continent_info = continent_info
        except APIError:
            self.last_continent_info = None
            self.no_pois.add(map_id)
        details = character.name + tag
        if self.last_continent_info:
            if self.registry and str(map_id) in self.registry.get("raids", {}):
                state, map_asset = self.get_raid_assets(
                    map_info, continent_info)
            else:
                self.last_boss = None
                point, distance = self.find_closest_point(
                    map_info, continent_info)
                if point:
                    map_asset["large_text"] += " near " + point["name"]
        map_asset["large_text"] += get_region()
        activiy = {
            "state": state,
            "details": details,
            "timestamps": {
                'start': self.game.last_timestamp
            },
            "assets": {
                **map_asset, "small_image": character.profession_icon,
                "small_text": "{0.race} {0.profession}".format(character, tag)
            }
        }
        return activiy

    def in_character_selection(self):
        activity = {
            "state": "in character selection",
            "assets": {
                "large_image":
                "default",
                "large_text":
                "Character Selection",
                "small_image":
                "gw2rpclogo",
                "small_text":
                "GW2RPC Version {}\nhttps://gw2rpc.info".format(VERSION)
            }
        }
        return activity

    def find_closest_point(self,
                           map_info,
                           continent_info,
                           *,
                           iterable=None,
                           id_only=False):
        if not iterable:
            iterable = continent_info["points_of_interest"].values()
        position = self.game.get_position()
        crect = map_info["continent_rect"]
        mrect = map_info["map_rect"]
        x_coord = crect[0][0] + (position.x - mrect[0][0]) / 24
        y_coord = crect[0][1] + (mrect[1][1] - position.y) / 24
        lowest_distance = float("inf")
        point = None
        for item in iterable:
            if not id_only and "name" not in item:
                continue
            distance = (item["coord"][0] - x_coord)**2 + (
                item["coord"][1] - y_coord)**2
            if distance < lowest_distance:
                lowest_distance = distance
                point = item
        return point, math.sqrt(lowest_distance)

    def main_loop(self):
        def update_gw2_process():
            shutdown = False
            if self.process:
                if self.process.is_running():
                    return
                else:
                    if config.close_with_gw2:
                        shutdown = True
            for process in psutil.process_iter():
                name = process.name()
                if name in ("Gw2-64.exe", "Gw2.exe"):
                    self.process = process
                    return
            if shutdown:
                self.shutdown()
            self.process = None
            raise GameNotRunningError

        def start_rpc():
            while True:
                try:
                    self.rpc.start()
                    break
                except (FileNotFoundError, PermissionError) as e:
                    time.sleep(10)

        try:
            while True:
                try:
                    update_gw2_process()
                    if not self.game.memfile:
                        self.game.create_map()
                    if not self.rpc.running:
                        start_rpc()
                        log.debug("starting self.rpc")
                    data = self.get_activity()
                    if not data:
                        data = self.in_character_selection()
                    log.debug(data)
                    try:
                        self.rpc.send_rich_presence(data, self.process.pid)
                    except BrokenPipeError:
                        raise GameNotRunningError  # To start a new connection
                except GameNotRunningError:
                    #  TODO
                    self.game.close_map()
                    if self.rpc.running:
                        self.rpc.close()
                        log.debug("Killing RPC")
                time.sleep(15)
        except Exception as e:
            log.critical("GW2RPC has crashed", exc_info=e)
            create_msgbox(
                "GW2 Rich Presence has crashed.\nPlease check your "
                "log file and report this to the author!",
                code=16)
            self.shutdown()
