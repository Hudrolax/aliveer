import threading
import requests
from datetime import datetime
from time import sleep

class CheckInternetConnection:
    CHECKTIME = 300
    SITES_FOR_CHECKING = []
    SITES_FOR_CHECKING.append('https://www.google.com')
    SITES_FOR_CHECKING.append('http://www.ru')

    def __init__(self):
        self._last_recieve_time = datetime.now()
        self._check_thread = threading.Thread(target=self._threaded_check_func, args=(), daemon=True)
        self._check_thread.start()

    def internet_is_available(self):
        if (datetime.now() - self._last_recieve_time).total_seconds() > self.CHECKTIME:
            return False
        else:
            return True

    def _check_site(self, site):
        try:
            content = requests.get(site, timeout=5).content.decode()
            print(f'{site} is ok')
            return True
        except:
            if __name__ == '__main__':
                print(f'{site} is offline')
            return False

    def _threaded_check_func(self):
        while True:
            for _site in self.SITES_FOR_CHECKING:
                if self._check_site(_site):
                    self._last_recieve_time = datetime.now()
                    break
                else:
                    print(f'Error connection. Reboot network things in {round(self.CHECKTIME-(datetime.now() - self._last_recieve_time).total_seconds())} seconds.')
            sleep(20)

class NetworkThingsRebooter:
    TIME_BETWEEN_REBOOTING = 600

    def __init__(self, arduino, things_rel_number):
        self._arduino = arduino
        self._things_rel_number = things_rel_number
        self._last_reboot_time = datetime(2007, 12, 6, 16, 29, 43, 79043)
        self._check_connection = CheckInternetConnection()

    def check_and_reboot(self, bot, telegram_users):
        if not self._check_connection.internet_is_available() \
                and (datetime.now() - self._last_reboot_time).total_seconds() > self.TIME_BETWEEN_REBOOTING:
            for user in telegram_users:
                bot.send_message(user.ID, 'Перезагрузил Kerio, т.к. чего-то не вижу интернета.')

            self._arduino.RelDef(self._things_rel_number, True)
            sleep(10)
            self._arduino.RelDef(self._things_rel_number, False)
            self._last_reboot_time = datetime.now()


if __name__ == '__main__':
    check_connection_object = CheckInternetConnection()
    while True:
        sleep(1)