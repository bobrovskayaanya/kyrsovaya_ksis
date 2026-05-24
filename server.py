import socket
import threading
import json
import sys
from game_logic import validate_number, calculate_bulls_and_cows

HOST = "0.0.0.0"
PORT = 5555
BUFFER_SIZE = 4096

def send_message(sock: socket.socket, msg: dict) -> bool:
    try:
        data = json.dumps(msg, ensure_ascii=False) + "\n"
        sock.sendall(data.encode("utf-8"))
        return True
    except (OSError, BrokenPipeError):
        return False

class GameServer:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.clients: list[socket.socket | None] = [None, None]
        self.client_addrs: list[tuple | None] = [None, None]
        self.secrets: list[str | None] = [None, None]
        self.ready: list[bool] = [False, False]
        self.current_turn: int = 0
        self.attempts: list[int] = [0, 0]
        self.game_active: bool = False
        self.first_guesser: int | None = None
        self.restart_votes: list[bool] = [False, False]
        self.lock = threading.Lock()
        self._all_disconnected = threading.Event()
        self.server_socket: socket.socket | None = None

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[Сервер] Запущен на {self.host}:{self.port}")
        try:
            while True:
                self._reset_game()
                self._all_disconnected.clear()
                print("[Сервер] Ожидание двух игроков...")
                player_index = 0
                while player_index < 2:
                    try:
                        client_sock, addr = self.server_socket.accept()
                        with self.lock:
                            self.clients[player_index] = client_sock
                            self.client_addrs[player_index] = addr
                        print(f"[Сервер] Игрок {player_index + 1} подключился: {addr}")
                        send_message(client_sock, {
                            "type": "init",
                            "player_id": player_index + 1,
                            "message": "Ожидание второго игрока..." if player_index == 0 else "Оба игрока подключены!"
                        })
                        t = threading.Thread(
                            target=self._handle_client,
                            args=(player_index,),
                            daemon=True
                        )
                        t.start()
                        player_index += 1
                    except OSError:
                        return
                if self.clients[0] and self.clients[1]:
                    print("[Сервер] Оба игрока подключены. Запрашиваем секретные числа.")
                    for i in range(2):
                        send_message(self.clients[i], {
                            "type": "request_secret",
                            "message": "Введите ваше секретное 4-значное число (цифры не повторяются):"
                        })
                self._all_disconnected.wait()
                print("[Сервер] Оба игрока отключились. Готов к новой партии.")
        except KeyboardInterrupt:
            self.stop()

    def _handle_client(self, player_index: int):
        sock = self.clients[player_index]
        buffer = ""
        try:
            while True:
                data = sock.recv(BUFFER_SIZE)
                if not data:
                    raise ConnectionResetError("Клиент отключился")
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            self._process_message(player_index, msg)
                        except json.JSONDecodeError:
                            print(f"[Сервер] Ошибка парсинга JSON от игрока {player_index + 1}: {line!r}")
        except (ConnectionResetError, OSError) as e:
            print(f"[Сервер] Игрок {player_index + 1} отключился: {e}")
            self._handle_disconnect(player_index)

    def _process_message(self, player_index: int, msg: dict):
        msg_type = msg.get("type")
        print(f"[Сервер] Сообщение от игрока {player_index + 1}: {msg}")
        if msg_type == "secret":
            self._handle_secret(player_index, msg.get("number", ""))
        elif msg_type == "guess":
            self._handle_guess(player_index, msg.get("number", ""))
        elif msg_type == "restart":
            self._handle_restart(player_index)

    def _handle_secret(self, player_index: int, number: str):
        valid, error = validate_number(number)
        if not valid:
            send_message(self.clients[player_index], {
                "type": "error",
                "message": error
            })
            return
        with self.lock:
            self.secrets[player_index] = number
            self.ready[player_index] = True
            print(f"[Сервер] Игрок {player_index + 1} загадал число.")
            both_ready = all(self.ready)
        if both_ready:
            self._start_game()

    def _start_game(self):
        with self.lock:
            self.game_active = True
            self.current_turn = 0
        print("[Сервер] Игра началась! Ход игрока 1.")
        for i in range(2):
            send_message(self.clients[i], {
                "type": "game_start",
                "message": "Игра началась!",
                "your_turn": i == 0
            })

    def _handle_guess(self, player_index: int, number: str):
        with self.lock:
            if not self.game_active:
                send_message(self.clients[player_index], {
                    "type": "error",
                    "message": "Игра ещё не началась"
                })
                return
            if self.current_turn != player_index:
                send_message(self.clients[player_index], {
                    "type": "error",
                    "message": "Сейчас не ваш ход"
                })
                return
        valid, error = validate_number(number)
        if not valid:
            send_message(self.clients[player_index], {
                "type": "error",
                "message": error
            })
            return
        opponent_index = 1 - player_index
        with self.lock:
            secret = self.secrets[opponent_index]
            self.attempts[player_index] += 1
            attempt_num = self.attempts[player_index]
        bulls, cows = calculate_bulls_and_cows(secret, number)
        print(f"[Сервер] Игрок {player_index + 1} пробует {number}: {bulls} быков, {cows} коров")
        send_message(self.clients[player_index], {
            "type": "result",
            "attempt": number,
            "attempt_num": attempt_num,
            "bulls": bulls,
            "cows": cows
        })
        send_message(self.clients[opponent_index], {
            "type": "opponent_result",
            "attempt": number,
            "attempt_num": attempt_num,
            "bulls": bulls,
            "cows": cows
        })
        with self.lock:
            in_last_chance = self.first_guesser is not None
            first_g = self.first_guesser
        if in_last_chance:
            if bulls == 4:
                self._end_game(None)
            else:
                self._end_game(first_g)
        else:
            if bulls == 4:
                self._handle_win(player_index)
            else:
                with self.lock:
                    self.current_turn = opponent_index
                send_message(self.clients[player_index], {
                    "type": "turn",
                    "your_turn": False
                })
                send_message(self.clients[opponent_index], {
                    "type": "turn",
                    "your_turn": True
                })

    def _handle_win(self, winner_index: int):
        opponent_index = 1 - winner_index
        if winner_index == 0:
            with self.lock:
                self.first_guesser = 0
                self.current_turn = opponent_index
            print("[Сервер] Игрок 1 угадал! Игроку 2 даётся последний шанс.")
            send_message(self.clients[0], {
                "type": "guessed",
                "message": "Вы угадали число! Сопернику даётся последний шанс..."
            })
            send_message(self.clients[1], {
                "type": "last_chance",
                "message": "Соперник угадал ваше число! У вас последний шанс!",
                "your_turn": True
            })
        else:
            self._end_game(1)

    def _end_game(self, winner_index: int | None):
        with self.lock:
            self.game_active = False
            secret_0 = self.secrets[0]
            secret_1 = self.secrets[1]
        if winner_index is None:
            print("[Сервер] Игра завершена! Ничья.")
            for i in range(2):
                send_message(self.clients[i], {
                    "type": "game_over",
                    "winner": None,
                    "you_win": False,
                    "draw": True,
                    "secret_player1": secret_0,
                    "secret_player2": secret_1,
                    "message": "Ничья! Оба угадали за одинаковое количество ходов!"
                })
        else:
            print(f"[Сервер] Игра завершена! Победил игрок {winner_index + 1}.")
            for i in range(2):
                won = (i == winner_index)
                send_message(self.clients[i], {
                    "type": "game_over",
                    "winner": winner_index + 1,
                    "you_win": won,
                    "draw": False,
                    "secret_player1": secret_0,
                    "secret_player2": secret_1,
                    "message": "Вы победили!" if won else "Вы проиграли."
                })

    def _handle_restart(self, player_index: int):
        opponent_index = 1 - player_index
        with self.lock:
            if self.restart_votes[player_index]:
                return
            self.restart_votes[player_index] = True
            both_voted = all(self.restart_votes)
        if both_voted:
            print("[Сервер] Оба игрока хотят сыграть снова. Перезапуск...")
            self._reset_game()
            for i in range(2):
                if self.clients[i]:
                    send_message(self.clients[i], {
                        "type": "request_secret",
                        "message": "Новая игра! Введите новое секретное число:"
                    })
        else:
            print(f"[Сервер] Игрок {player_index + 1} хочет сыграть снова. Ждём второго.")
            send_message(self.clients[player_index], {
                "type": "restart_waiting",
                "message": "Ожидание соперника..."
            })
            if self.clients[opponent_index]:
                send_message(self.clients[opponent_index], {
                    "type": "restart_requested",
                    "message": "Соперник хочет сыграть снова!"
                })

    def _reset_game(self):
        with self.lock:
            self.secrets = [None, None]
            self.ready = [False, False]
            self.current_turn = 0
            self.attempts = [0, 0]
            self.game_active = False
            self.first_guesser = None
            self.restart_votes = [False, False]

    def _handle_disconnect(self, player_index: int):
        opponent_index = 1 - player_index
        with self.lock:
            self.clients[player_index] = None
            was_active = self.game_active
            self.game_active = False
            both_gone = self.clients[0] is None and self.clients[1] is None
        if was_active and self.clients[opponent_index]:
            send_message(self.clients[opponent_index], {
                "type": "opponent_disconnected",
                "message": "Соперник отключился. Игра завершена."
            })
        if both_gone:
            self._all_disconnected.set()

    def stop(self):
        print("[Сервер] Остановка сервера...")
        with self.lock:
            for i, sock in enumerate(self.clients):
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass

if __name__ == "__main__":
    server = GameServer()
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
        print("[Сервер] Завершено.")
        sys.exit(0)