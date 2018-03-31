import sys, logging, time, nfc, mpd, yaml, threading

from token import Token

class Jukebox:
    def __init__(self, token_definition_path, hostname, port, timeout):
        self.current_token = None
        self.last_token_event = None
        self.logger = self.get_logger()
        self.nfc_client = self.get_nfc_client()
        self.tokens = self.get_tokens(token_definition_path)
        self.hostname = hostname
        self.port = port
        self.music_client = self.get_music_client(timeout)
        self.connect_music_client()
        self.lock = threading.Lock()

    def __delete__(self, instance):
        self.disconnect()
        del self.music_client
        del self.nfc_client

    def get_logger(self):
        logger = logging.getLogger("hudlow.jukebox")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(logging.StreamHandler(sys.stdout))

        return logger

    def get_nfc_client(self):
        self.create_token_event("initialize", None)

        return nfc.ContactlessFrontend('usb')

    def get_tokens(self, token_definition_path):
        with open(token_definition_path, 'r') as file:
            definitions = yaml.load(file)

            return Token.from_definitions(definitions)

    def get_music_client(self, timeout):
        music_client = mpd.MPDClient()
        music_client.timeout = timeout
        music_client.idletimeout = None

        return music_client

    def connect_music_client(self):
        self.music_client.connect(self.hostname, self.port)

    def ensure_music_client_connection(self):
        try:
            self.music_client.ping()
        except mpd.ConnectionError:
            self.logger.info("Reconnecting...")
            self.connect_music_client()

    def create_token_event(self, type, token):
        name = token.name if token != None else "None"
        self.last_token_event = (type, name, time.time())

        return self.last_token_event

    def disconnect(self):
        try:
            self.music_client.ping()
        except ConnectionError:
            return

        self.music_client.close()

    def start(self):
        self.nfc_client.connect(
            rdwr = {
                'on-connect': self.tag_connect,
                'on-release': self.tag_release,
                'beep-on-connect': True
            }
        )

    def queue_music_for(self, token):
        self.logger.info("Starting music for " + token.name)

        self.ensure_music_client_connection()
        self.music_client.clear()

        count = 0
        for playlist in token.playlists:
            length = len(self.music_client.listplaylistinfo(playlist[0]))
            
            self.music_client.load(playlist[0])

            if (playlist[0] == "shuffle"):
                self.music_client.shuffle(str(count) + ":" + str(count+length))

            count += length

        self.music_client.play()

    def stop_music(self):
        self.logger.info("Stopping music")

        self.ensure_music_client_connection()
        self.music_client.stop()
        self.music_client.clear()

    def tag_connect(self, tag):
        with self.lock:
            token = Token.find_token(tag)
            event = self.create_token_event("connect", token)

            if (token != self.current_token):
                self.current_token = token

                if (token != None):
                    self.queue_music_for(token)
                else:
                    self.stop_music()

            return True

    def tag_release(self, tag):
        with self.lock:
            token = Token.find_token(tag)
            event = self.create_token_event("release", token)

            thread = threading.Thread(target=self.check_if_token_gone, args=(event,))
            thread.start()

            return False

    def check_if_token_gone(self, event):
        time.sleep(3)

        with self.lock:
            if (self.last_token_event == event):
                self.current_token = None
                self.stop_music()
