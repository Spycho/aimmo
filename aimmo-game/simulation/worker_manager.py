import logging
import os
import subprocess
import threading
import time

import requests

LOGGER = logging.getLogger(__name__)


class WorkerManager(threading.Thread):
    daemon = True

    def __init__(self, game_state, users_url):
        self.game_state = game_state
        self.users_url = users_url
        self.user_codes = {}
        super(WorkerManager, self).__init__()

    def get_persistent_state(self, player_id):
        """Get the persistent state for a worker."""

        return None

    def create_worker(self, player_id):
        """Create a worker."""

        raise NotImplemented

    def remove_worker(self, player_id):
        """Remove a worker for the given player."""

        raise NotImplemented

    def run(self):
        while True:
            try:
                game_data = requests.get(self.users_url).json()
            except (requests.RequestException, ValueError) as err:
                LOGGER.error("Obtaining game data failed: %s", err)
            else:
                game = game_data['main']
                for user in game['users']:
                    if self.user_codes.get(user['id'], None) != user['code']:
                        # Remove avatar from the game, so it stops being called
                        # for turns
                        self.game_state.remove_avatar(user['id'])
                        # Get persistent state from worker
                        persistent_state = self.get_persistent_state(user['id'])
                        # Kill worker
                        self.remove_worker(user['id'])
                        # Spawn worker
                        worker_url = self.create_worker(user['id'])
                        # Initialise worker
                        requests.post("%s/initialise/" % worker_url, json={
                            'code': user['code'],
                            'options': {},
                            'persistent_state': persistent_state,
                        })
                        # Add avatar back into game
                        self.game_state.add_avatar(
                            user_id=user['id'], worker_url="%s/turn/" % worker_url)
                        self.user_codes[user['id']] = user['code']
                removed_user_ids = set(self.user_codes) - set(user['id'] for user in game['users'])
                for removed_user in removed_user_ids:
                    self.game_state.remove_avatar(removed_user)
                    self.remove_worker(removed_user)
                    del self.user_codes[removed_user]

            time.sleep(10)


class LocalWorkerManager(WorkerManager):
    """Relies on them already being created already."""

    host = '127.0.0.1'
    worker_path = os.path.join(
        os.path.dirname(__file__),
        '../../aimmo-game-worker/service.py',
    )

    def __init__(self, *args, **kwargs):
        self.workers = {}
        self.next_port = 1989
        super(LocalWorkerManager, self).__init__(*args, **kwargs)

    def create_worker(self, player_id):
        assert(player_id not in self.workers)
        self.next_port += 1
        process_args = [
            'python',
            self.worker_path,
            self.host,
            str(self.next_port),
        ]
        self.workers[player_id] = subprocess.Popen(process_args)
        worker_url = 'http://%s:%d' % (
            self.host,
            self.next_port,
        )
        LOGGER.info("Worker started for %s, listening at %s", player_id, worker_url)
        time.sleep(5)
        return worker_url

    def remove_worker(self, player_id):
        if player_id in self.workers:
            self.workers[player_id].kill()
            del self.workers[player_id]
