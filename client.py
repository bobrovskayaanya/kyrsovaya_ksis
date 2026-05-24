import pygame
import socket
import threading
import json
import sys
import os
import math
from game_logic import validate_number, format_result

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
BUFFER_SIZE = 4096

def _parse_connect_port(port_text: str) -> tuple[int | None, str | None]:
    s = port_text.strip()
    if not s:
        return None, None
    try:
        p = int(s)
    except ValueError:
        return None, "Введён некорректный порт: укажите целое число"
    if not (1 <= p <= 65535):
        return None, "Введён некорректный порт: допустимы значения от 1 до 65535"
    return p, None

def _validate_ipv4_literal(host: str) -> str | None:
    host = host.strip()
    if not host or host.lower() == "localhost":
        return None
    if any(c not in "0123456789." for c in host):
        return None
    parts = host.split(".")
    if len(parts) != 4:
        return "Введён некорректный IP: нужно четыре числа через точку (например 192.168.0.1)"
    for part in parts:
        if not part.isdigit():
            return "Введён некорректный IP: в каждой части допустимы только цифры"
        if len(part) > 1 and part.startswith("0"):
            return "Введён некорректный IP: уберите лишние нули в начале чисел"
        if int(part) > 255:
            return "Введён некорректный IP: каждое число не больше 255"
    return None

def _humanize_connect_error(err: str) -> str:
    low = err.lower()
    if "timed out" in low or "timeout" in low:
        return "Таймаут: сервер не ответил. Проверьте IP, порт и сеть."
    if "refused" in low or "10061" in err:
        return (
            "Подключение отклонено: неверный порт или сервер не запущен. "
            "Оба игрока должны указать один и тот же IP и порт сервера."
        )
    if "10051" in err or "unreachable" in low:
        return "Сеть недоступна: проверьте IP-адрес."
    if "getaddrinfo" in low or "11001" in err or "11002" in err:
        return "Не удалось определить адрес: проверьте IP или имя хоста."
    if "10049" in err or "10048" in err:
        return "Ошибка адреса или порт занят на этой машине."
    return "Не удалось подключиться к серверу"

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (160, 160, 160)
DARK_GRAY = (80, 80, 80)
LIGHT_GRAY = (220, 220, 220)
GREEN = (76, 175, 80)
GREEN_DARK = (46, 125, 50)
GREEN_LIGHT = (165, 214, 167)
RED = (229, 57, 53)
RED_DARK = (183, 28, 28)
YELLOW = (255, 214, 0)
ORANGE = (255, 152, 0)
BLUE = (33, 150, 243)

WINDOW_W = 700
WINDOW_H = 600
FPS = 60

END_SCREEN_STATUS_Y = 458
END_SCREEN_STATUS_H = 54
END_SCREEN_BTN_Y = 538

class GameClient:
    def __init__(self):
        self.sock: socket.socket | None = None
        self.connected: bool = False
        self._recv_buffer: str = ""
        self._inbox: list[dict] = []
        self._inbox_lock = threading.Lock()

    def connect(self, host: str, port: int) -> tuple[bool, str]:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, port))
            self.sock.settimeout(None)
            self.connected = True
            t = threading.Thread(target=self._receive_loop, daemon=True)
            t.start()
            return True, ""
        except (ConnectionRefusedError, TimeoutError, OSError) as e:
            return False, str(e)

    def send(self, msg: dict) -> bool:
        if not self.connected or not self.sock:
            return False
        try:
            data = json.dumps(msg, ensure_ascii=False) + "\n"
            self.sock.sendall(data.encode("utf-8"))
            return True
        except OSError:
            self.connected = False
            return False

    def poll_messages(self) -> list[dict]:
        with self._inbox_lock:
            msgs = self._inbox[:]
            self._inbox.clear()
        return msgs

    def _receive_loop(self):
        while self.connected:
            try:
                data = self.sock.recv(BUFFER_SIZE)
                if not data:
                    raise ConnectionResetError("Сервер закрыл соединение")
                self._recv_buffer += data.decode("utf-8")
                while "\n" in self._recv_buffer:
                    line, self._recv_buffer = self._recv_buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            with self._inbox_lock:
                                self._inbox.append(msg)
                        except json.JSONDecodeError:
                            pass
            except (OSError, ConnectionResetError):
                self.connected = False
                with self._inbox_lock:
                    self._inbox.append({"type": "disconnected"})
                break

    def close(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

class InputField:
    def __init__(self, x: int, y: int, w: int, h: int,
                 font: pygame.font.Font, placeholder: str = ""):
        self.rect = pygame.Rect(x, y, w, h)
        self.font = font
        self.placeholder = placeholder
        self.text: str = ""
        self.active: bool = False
        self.max_len: int = 4

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.unicode.isdigit() and len(self.text) < self.max_len:
                self.text += event.unicode

    def draw(self, surface: pygame.Surface):
        bg = pygame.Surface((self.rect.w, self.rect.h), pygame.SRCALPHA)
        alpha = 235 if self.active else 200
        pygame.draw.rect(bg, (255, 255, 255, alpha), (0, 0, self.rect.w, self.rect.h),
                         border_radius=12)
        surface.blit(bg, self.rect)
        border_color = GREEN if self.active else (190, 190, 190)
        border_w = 2 if self.active else 1
        pygame.draw.rect(surface, border_color, self.rect, border_w, border_radius=12)
        disp = self.text if self.text else self.placeholder
        tc = (25, 25, 25) if self.text else (155, 155, 155)
        ts = self.font.render(disp, True, tc)
        surface.blit(ts, (self.rect.x + 12, self.rect.centery - ts.get_height() // 2))
        if self.active and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = self.rect.x + 12 + self.font.size(self.text)[0]
            pygame.draw.line(surface, (40, 40, 40),
                             (cx + 2, self.rect.y + 8),
                             (cx + 2, self.rect.bottom - 8), 2)

    def clear(self):
        self.text = ""

class Button:
    def __init__(self, x: int, y: int, w: int, h: int,
                 text: str, font: pygame.font.Font,
                 color=GREEN, hover_color=GREEN_DARK, radius: int = 14):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.font = font
        self.color = color
        self.hover_color = hover_color
        self.enabled = True
        self.radius = radius

    def draw(self, surface: pygame.Surface):
        mp = pygame.mouse.get_pos()
        hovered = self.rect.collidepoint(mp) and self.enabled
        base = (100, 100, 100) if not self.enabled else (self.hover_color if hovered else self.color)
        pygame.draw.rect(surface, base, self.rect, border_radius=self.radius)
        hl_h = self.rect.h // 2
        hl = pygame.Surface((self.rect.w - 4, hl_h), pygame.SRCALPHA)
        pygame.draw.rect(hl, (255, 255, 255, 45),
                         (0, 0, hl.get_width(), hl.get_height()),
                         border_radius=self.radius - 2)
        surface.blit(hl, (self.rect.x + 2, self.rect.y + 2))
        if hovered:
            pygame.draw.rect(surface, (255, 255, 255), self.rect, 2,
                             border_radius=self.radius)
        shadow = self.font.render(self.text, True, (0, 0, 0))
        txt = self.font.render(self.text, True, WHITE)
        tx = self.rect.centerx - txt.get_width() // 2
        ty = self.rect.centery - txt.get_height() // 2
        surface.blit(shadow, (tx + 1, ty + 1))
        surface.blit(txt, (tx, ty))

    def is_clicked(self, event: pygame.event.Event) -> bool:
        return (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos) and self.enabled)

class ScrollableHistory:
    def __init__(self, x: int, y: int, w: int, h: int, font: pygame.font.Font):
        self.rect = pygame.Rect(x, y, w, h)
        self.font = font
        self.lines: list[tuple[str, tuple, object]] = []
        self.scroll_offset = 0
        self.line_h = font.get_linesize() + 5

    def add(self, text: str, color=WHITE, icon=None):
        self.lines.append((text, color, icon))
        max_vis = self.rect.height // self.line_h
        if len(self.lines) > max_vis:
            self.scroll_offset = len(self.lines) - max_vis

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos()):
            max_scroll = max(0, len(self.lines) - self.rect.height // self.line_h)
            self.scroll_offset = max(0, min(max_scroll, self.scroll_offset - event.y))

    def draw(self, surface: pygame.Surface):
        bg = pygame.Surface((self.rect.w, self.rect.h), pygame.SRCALPHA)
        pygame.draw.rect(bg, (0, 0, 0, 155), (0, 0, self.rect.w, self.rect.h), border_radius=14)
        pygame.draw.rect(bg, (255, 255, 255, 30), (0, 0, self.rect.w, self.rect.h), 1, border_radius=14)
        surface.blit(bg, (self.rect.x, self.rect.y))
        clip = surface.get_clip()
        surface.set_clip(self.rect)
        start = self.scroll_offset
        max_vis = self.rect.height // self.line_h
        visible = self.lines[start:start + max_vis]
        for idx, (text, color, icon) in enumerate(visible):
            y = self.rect.y + idx * self.line_h + 7
            x = self.rect.x + 10
            if icon is not None:
                iy = y + (self.line_h - icon.get_height()) // 2
                surface.blit(icon, (x, iy))
                x += icon.get_width() + 7
            ts = self.font.render(text, True, color)
            surface.blit(ts, (x, y))
        surface.set_clip(clip)

STATE_CONNECT = "connect"
STATE_WAIT = "wait"
STATE_SECRET = "secret"
STATE_WAIT_START = "wait_start"
STATE_GAME = "game"
STATE_GAME_OVER = "game_over"
STATE_RESTART_WAIT = "restart_wait"

class GameUI:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption("Быки и коровы — сетевая игра")
        self.clock = pygame.time.Clock()
        self.font_large = pygame.font.SysFont("segoeui", 26, bold=True)
        self.font_medium = pygame.font.SysFont("segoeui", 20)
        self.font_small = pygame.font.SysFont("segoeui", 16)
        self.font_title = pygame.font.SysFont("segoeui", 38, bold=True)
        self.font_huge = pygame.font.SysFont("segoeui", 48, bold=True)
        self.bg_menu = self._load_bg("bg_menu.jpg")
        self.bg_game = self._load_bg("bg_game.jpg")
        self.icon_bull_sm = self._load_icon("bull.png", 22)
        self.icon_cow_sm = self._load_icon("cow.png", 22)
        self.icon_bull_md = self._load_icon("bull.png", 52)
        self.icon_cow_md = self._load_icon("cow.png", 52)
        self.icon_bull_big = self._load_icon("bull.png", 100)
        self.icon_cow_big = self._load_icon("cow.png", 100)
        self.client = GameClient()
        self.state: str = STATE_CONNECT
        self.player_id: int = 0
        self.my_turn: bool = False
        self.error_msg: str = ""
        self.status_msg: str = "Добро пожаловать!"
        self.game_over_msg: str = ""
        self.opponent_wants_restart: bool = False
        self.you_win: bool = False
        self.is_draw: bool = False
        self.history = ScrollableHistory(15, 82, 670, 395, self.font_small)
        self._build_connect_screen()
        cx = WINDOW_W // 2
        self.secret_input = InputField(170, 454, 220, 46, self.font_large, "напр. 1234")
        self.secret_btn = Button(405, 454, 175, 46, "Загадать",
                                 self.font_medium, GREEN, GREEN_DARK)
        self.guess_input = InputField(20, 497, 235, 46, self.font_large, "попытка")
        self.guess_btn = Button(267, 497, 175, 46, "Угадать",
                                self.font_medium, GREEN, GREEN_DARK)
        self.play_again_btn = Button(cx - 205, END_SCREEN_BTN_Y, 190, 50, "Играть снова",
                                     self.font_medium, GREEN, GREEN_DARK)
        self.exit_btn = Button(cx + 15, END_SCREEN_BTN_Y, 190, 50, "В меню",
                               self.font_medium, RED, RED_DARK)

    def _load_bg(self, filename: str):
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "assets", filename)
        if os.path.exists(path):
            img = pygame.image.load(path).convert()
            return pygame.transform.scale(img, (WINDOW_W, WINDOW_H))
        return None

    def _load_icon(self, filename: str, size: int):
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "assets", filename)
        if os.path.exists(path):
            img = pygame.image.load(path).convert_alpha()
            return pygame.transform.smoothscale(img, (size, size))
        return None

    def _draw_bg(self, bg):
        if bg:
            self.screen.blit(bg, (0, 0))
        else:
            self.screen.fill((30, 50, 20))

    def _draw_panel(self, x: int, y: int, w: int, h: int,
                    alpha: int = 175, color=(10, 12, 8), radius: int = 16):
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(surf, (*color, alpha), (0, 0, w, h), border_radius=radius)
        pygame.draw.rect(surf, (255, 255, 255, 40), (0, 0, w, h), 1, border_radius=radius)
        self.screen.blit(surf, (x, y))

    def _text(self, font, text: str, color, x: int, y: int, shadow=False):
        if shadow:
            sh = font.render(text, True, (0, 0, 0))
            self.screen.blit(sh, (x + 2, y + 2))
        surf = font.render(text, True, color)
        self.screen.blit(surf, (x, y))

    def _text_center(self, font, text: str, color, y: int, shadow=True):
        surf = font.render(text, True, color)
        x = WINDOW_W // 2 - surf.get_width() // 2
        if shadow:
            sh = font.render(text, True, (0, 0, 0))
            self.screen.blit(sh, (x + 2, y + 2))
        self.screen.blit(surf, (x, y))

    def _result_color(self) -> tuple:
        if self.is_draw:
            return YELLOW
        if self.you_win:
            return GREEN_LIGHT
        return (255, 120, 100)

    def _wrap_error_lines(self, text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        text = " ".join(text.split())
        if not text:
            return []
        lines: list[str] = []
        while text:
            if font.size(text)[0] <= max_width:
                lines.append(text)
                break
            lo, hi = 1, len(text)
            fit = 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if font.size(text[:mid])[0] <= max_width:
                    fit = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if fit < 1:
                fit = 1
            br = text.rfind(" ", 0, fit + 1)
            if br > max(1, fit // 4):
                piece = text[:br]
                text = text[br + 1:].lstrip()
            else:
                piece = text[:fit]
                text = text[fit:].lstrip()
            if piece:
                lines.append(piece)
        return lines

    def _draw_error_notice(self, top_y: int, max_width: int, center_x: int | None = None) -> int:
        if not self.error_msg:
            return 0
        cx = center_x if center_x is not None else WINDOW_W // 2
        font = self.font_small
        pad_x, pad_y = 14, 9
        line_h = font.get_linesize() + 1
        inner_w = max_width - pad_x * 2
        lines = self._wrap_error_lines(self.error_msg, font, max(inner_w, 80))
        text_w = max(font.size(L)[0] for L in lines)
        box_w = min(max_width, text_w + pad_x * 2)
        box_h = len(lines) * line_h + pad_y * 2
        left = max(8, cx - box_w // 2)
        if left + box_w > WINDOW_W - 8:
            left = WINDOW_W - 8 - box_w
        bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(bg, (55, 12, 12, 235), (0, 0, box_w, box_h), border_radius=12)
        pygame.draw.rect(bg, (*RED[:3], 200), (0, 0, box_w, box_h), 2, border_radius=12)
        self.screen.blit(bg, (left, top_y))
        y = top_y + pad_y
        for line in lines:
            t = font.render(line, True, (255, 230, 230))
            sh = font.render(line, True, (0, 0, 0))
            x = left + (box_w - t.get_width()) // 2
            self.screen.blit(sh, (x + 1, y + 1))
            self.screen.blit(t, (x, y))
            y += line_h
        return box_h

    def _draw_bulls_cows_rules_banner(self):
        rx, ry, rw, rh = 14, 8, WINDOW_W - 28, 138
        self._draw_panel(rx, ry, rw, rh, alpha=212, color=(4, 18, 10), radius=16)
        accent = pygame.Surface((rw - 8, 3), pygame.SRCALPHA)
        pygame.draw.rect(accent, (80, 200, 120, 160), (0, 0, accent.get_width(), 3), border_radius=2)
        self.screen.blit(accent, (rx + 4, ry + 34))
        self._text_center(self.font_medium, "Правила «Быки и коровы»", GREEN_LIGHT, ry + 10, shadow=True)
        rules_text = (
            "Каждый игрок загадывает своё число из 4 разных цифр — его не видит соперник. "
            "По очереди называют варианты чужого числа. После попытки сервер отвечает: "
            "бык — цифра угадана и стоит на своём месте; корова — цифра есть в числе, но не на этой позиции."
        )
        lines = self._wrap_error_lines(rules_text, self.font_small, rw - 32)[:4]
        yy = ry + 42
        lh = self.font_small.get_linesize() + 2
        for ln in lines:
            surf = self.font_small.render(ln, True, LIGHT_GRAY)
            self.screen.blit(surf, (rx + 16, yy))
            yy += lh
        iy = ry + rh - 26
        if self.icon_bull_sm and self.icon_cow_sm:
            self.screen.blit(self.icon_bull_sm, (rx + 18, iy))
            self._text(self.font_small, "— на месте", WHITE, rx + 44, iy + 3)
            self.screen.blit(self.icon_cow_sm, (rx + 200, iy))
            self._text(self.font_small, "— есть, не на месте", WHITE, rx + 226, iy + 3)
        else:
            self._text(self.font_small, "Бык — на месте  ·  Корова — есть, не на месте",
                       WHITE, rx + 16, iy + 3)

    def _draw_result_msg(self, y: int):
        text = self.game_over_msg
        rc = self._result_color()
        for font in (self.font_huge, self.font_title, self.font_large, self.font_medium):
            surf = font.render(text, True, rc)
            if surf.get_width() <= WINDOW_W - 130:
                x = WINDOW_W // 2 - surf.get_width() // 2 + 50
                sh = font.render(text, True, BLACK)
                self.screen.blit(sh, (x + 2, y + 2))
                self.screen.blit(surf, (x, y))
                return
        surf = self.font_small.render(text, True, rc)
        self.screen.blit(surf, (130, y))

    def _build_connect_screen(self):
        self.host_input = InputField(148, 418, 220, 44, self.font_large, "127.0.0.1")
        self.host_input.max_len = 15
        self.port_input = InputField(383, 418, 165, 44, self.font_large, "5555")
        self.port_input.max_len = 5
        self.connect_btn = Button(195, 518, 310, 52, "Подключиться",
                                  self.font_medium, GREEN, GREEN_DARK, radius=16)

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                else:
                    self._handle_event(event)
            if self.client.connected:
                for msg in self.client.poll_messages():
                    self._process_server_message(msg)
            self._draw()
            pygame.display.flip()
            self.clock.tick(FPS)
        self.client.close()
        pygame.quit()
        sys.exit(0)

    def _handle_event(self, event: pygame.event.Event):
        if self.state == STATE_CONNECT:
            self._handle_ip_input(event)
            self._handle_port_input(event)
            if self.connect_btn.is_clicked(event):
                self._do_connect()
        elif self.state == STATE_SECRET:
            self.secret_input.handle_event(event)
            if self.secret_btn.is_clicked(event):
                self._send_secret()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                self._send_secret()
        elif self.state == STATE_GAME:
            if self.my_turn:
                self.guess_input.handle_event(event)
                if self.guess_btn.is_clicked(event):
                    self._send_guess()
                if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                    self._send_guess()
            self.history.handle_event(event)
        elif self.state in (STATE_GAME_OVER, STATE_RESTART_WAIT):
            self.history.handle_event(event)
            if self.exit_btn.is_clicked(event):
                self._go_to_menu()
            if self.state == STATE_GAME_OVER and self.play_again_btn.is_clicked(event):
                self._send_restart()

    def _handle_ip_input(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.host_input.active = self.host_input.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.host_input.active:
            if event.key == pygame.K_BACKSPACE:
                self.host_input.text = self.host_input.text[:-1]
            elif (event.unicode.isdigit() or event.unicode == ".") \
                    and len(self.host_input.text) < self.host_input.max_len:
                self.host_input.text += event.unicode

    def _handle_port_input(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.port_input.active = self.port_input.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.port_input.active:
            if event.key == pygame.K_BACKSPACE:
                self.port_input.text = self.port_input.text[:-1]
            elif event.unicode.isdigit() and len(self.port_input.text) < self.port_input.max_len:
                self.port_input.text += event.unicode

    def _do_connect(self):
        host = self.host_input.text.strip() or DEFAULT_HOST
        ip_err = _validate_ipv4_literal(host)
        if ip_err:
            self.error_msg = ip_err
            return
        port, port_err = _parse_connect_port(self.port_input.text)
        if port_err:
            self.error_msg = port_err
            return
        if port is None:
            port = DEFAULT_PORT
        self.status_msg = f"Подключение к {host}:{port}..."
        self.error_msg = ""
        def _connect():
            ok, err = self.client.connect(host, port)
            if not ok:
                self.error_msg = _humanize_connect_error(err)
                self.status_msg = "Не удалось подключиться"
            else:
                self.state = STATE_WAIT
                self.status_msg = "Подключено. Ожидание игры..."
        threading.Thread(target=_connect, daemon=True).start()

    def _send_secret(self):
        number = self.secret_input.text.strip()
        valid, err = validate_number(number)
        if not valid:
            self.error_msg = err
            return
        self.client.send({"type": "secret", "number": number})
        self.secret_input.clear()
        self.error_msg = ""
        self.state = STATE_WAIT_START
        self.status_msg = "Число загадано. Ожидание соперника..."

    def _send_restart(self):
        self.client.send({"type": "restart"})
        self.state = STATE_RESTART_WAIT
        self.status_msg = "Ожидание соперника..."
        self.play_again_btn.enabled = False
        self.opponent_wants_restart = False

    def _go_to_menu(self):
        self.client.close()
        self.client = GameClient()
        self._reset_for_new_game()
        self._build_connect_screen()
        self.player_id = 0
        self.status_msg = "Добро пожаловать!"
        self.error_msg = ""
        self.state = STATE_CONNECT

    def _reset_for_new_game(self):
        self.my_turn = False
        self.error_msg = ""
        self.game_over_msg = ""
        self.opponent_wants_restart = False
        self.you_win = False
        self.is_draw = False
        self.guess_input.clear()
        self.secret_input.clear()
        self.guess_btn.enabled = False
        self.play_again_btn.enabled = True
        self.history.lines.clear()
        self.history.scroll_offset = 0

    def _send_guess(self):
        if not self.my_turn:
            return
        number = self.guess_input.text.strip()
        valid, err = validate_number(number)
        if not valid:
            self.error_msg = err
            return
        self.client.send({"type": "guess", "number": number})
        self.guess_input.clear()
        self.error_msg = ""
        self.my_turn = False
        self.guess_btn.enabled = False
        self.status_msg = "Ожидание ответа сервера..."

    def _process_server_message(self, msg: dict):
        t = msg.get("type")
        if t == "init":
            self.player_id = msg.get("player_id", 0)
            self.status_msg = msg.get("message", "")
            self.state = STATE_WAIT
        elif t == "request_secret":
            self._reset_for_new_game()
            self.state = STATE_SECRET
            self.status_msg = msg.get("message", "Введите секретное число:")
        elif t == "game_start":
            self.state = STATE_GAME
            self.my_turn = msg.get("your_turn", False)
            self._update_turn_status()
        elif t == "turn":
            self.my_turn = msg.get("your_turn", False)
            self.guess_btn.enabled = self.my_turn
            self._update_turn_status()
        elif t == "result":
            attempt = msg.get("attempt", "")
            bulls = msg.get("bulls", 0)
            cows = msg.get("cows", 0)
            num = msg.get("attempt_num", "?")
            text = f"#{num}  {format_result(attempt, bulls, cows)}"
            self.history.add(f"Вы:        {text}", YELLOW, self.icon_bull_sm)
        elif t == "opponent_result":
            attempt = msg.get("attempt", "")
            bulls = msg.get("bulls", 0)
            cows = msg.get("cows", 0)
            num = msg.get("attempt_num", "?")
            text = f"#{num}  {format_result(attempt, bulls, cows)}"
            self.history.add(f"Соперник:  {text}", ORANGE, self.icon_cow_sm)
        elif t == "guessed":
            self.status_msg = msg.get("message", "Вы угадали! Последний шанс соперника...")
            self.history.add("[ Вы угадали! Соперник делает последний ход ]", GREEN)
        elif t == "last_chance":
            self.my_turn = True
            self.guess_btn.enabled = True
            self.status_msg = msg.get("message", "Последний шанс!")
            self.history.add("[ Соперник угадал! Ваш последний шанс ]", ORANGE)
        elif t == "error":
            self.error_msg = msg.get("message", "Произошла ошибка")
        elif t == "game_over":
            self.state = STATE_GAME_OVER
            self.is_draw = msg.get("draw", False)
            self.you_win = msg.get("you_win", False)
            s1 = msg.get("secret_player1", "????")
            s2 = msg.get("secret_player2", "????")
            self.game_over_msg = msg.get("message", "Игра окончена")
            hc = YELLOW if self.is_draw else (GREEN_LIGHT if self.you_win else RED)
            self.history.add(f"[ КОНЕЦ: число игрока 1 - {s1}, игрока 2 - {s2} ]", hc)
            self.status_msg = self.game_over_msg
        elif t == "opponent_disconnected":
            self.state = STATE_GAME_OVER
            self.game_over_msg = msg.get("message", "Соперник отключился")
            self.status_msg = self.game_over_msg
            self.history.add("[ Соперник отключился. Игра завершена ]", RED)
        elif t == "restart_waiting":
            self.status_msg = msg.get("message", "Ожидание соперника...")
        elif t == "restart_requested":
            self.opponent_wants_restart = True
            self.status_msg = msg.get("message", "Соперник хочет сыграть снова!")
        elif t == "disconnected":
            self.error_msg = "Соединение с сервером потеряно"
            self.state = STATE_GAME_OVER
            self.game_over_msg = "Соединение потеряно"

    def _update_turn_status(self):
        if self.my_turn:
            self.status_msg = "Ваш ход! Введите попытку и нажмите «Угадать»."
            self.guess_btn.enabled = True
        else:
            self.status_msg = "Ход соперника. Ожидайте..."
            self.guess_btn.enabled = False

    def _draw(self):
        if self.state == STATE_CONNECT:
            self._draw_connect_screen()
        elif self.state in (STATE_WAIT, STATE_WAIT_START):
            self._draw_wait_screen()
        elif self.state == STATE_SECRET:
            self._draw_secret_screen()
        elif self.state == STATE_GAME:
            self._draw_game_screen()
        elif self.state == STATE_GAME_OVER:
            self._draw_game_over_screen()
        elif self.state == STATE_RESTART_WAIT:
            self._draw_restart_wait_screen()

    def _draw_connect_screen(self):
        self._draw_bg(self.bg_menu)
        px, py, pw, ph = 130, 362, 440, 212
        self._draw_panel(px, py, pw, ph, alpha=185)
        lbl = self.font_medium.render("Подключение к серверу", True, GREEN_LIGHT)
        self.screen.blit(lbl, (WINDOW_W // 2 - lbl.get_width() // 2, py + 14))
        pygame.draw.line(self.screen, (255, 255, 255),
                         (px + 20, py + 44), (px + pw - 20, py + 44), 1)
        self._text(self.font_small, "IP-адрес:", GRAY, px + 20, py + 52)
        self._text(self.font_small, "Порт:", GRAY, px + 258, py + 52)
        self.host_input.draw(self.screen)
        self.port_input.draw(self.screen)
        hint1 = self.font_small.render("Сначала запустите server.py", True, (140, 140, 140))
        self.screen.blit(hint1, (WINDOW_W // 2 - hint1.get_width() // 2, py + 464))
        for i, ln in enumerate(self._wrap_error_lines(
                "Порт по умолчанию 5555 (как в server.py и client.py); пустое поле — то же значение.",
                self.font_small, pw - 24)):
            h2 = self.font_small.render(ln, True, (118, 128, 118))
            self.screen.blit(h2, (WINDOW_W // 2 - h2.get_width() // 2, py + 482 + i * 18))
        self.connect_btn.draw(self.screen)
        if self.error_msg:
            self._draw_error_notice(312, max_width=min(640, WINDOW_W - 24))

    def _draw_wait_screen(self):
        self._draw_bg(self.bg_menu)
        icon = None
        if self.player_id == 1 and self.icon_bull_big:
            icon = self.icon_bull_big
        elif self.player_id == 2 and self.icon_cow_big:
            icon = self.icon_cow_big
        pw, ph = 370, 175
        px = WINDOW_W // 2 - pw // 2
        py = 290
        if icon:
            iw = icon.get_width()
            self.screen.blit(icon, (WINDOW_W // 2 - iw // 2, py - icon.get_height() - 8))
        self._draw_panel(px, py, pw, ph, alpha=190)
        if self.player_id:
            pid = self.font_large.render(f"Вы — Игрок {self.player_id}", True, GREEN_LIGHT)
            self.screen.blit(pid, (WINDOW_W // 2 - pid.get_width() // 2, py + 18))
        base = self.status_msg.rstrip(".")
        dots = "." * ((pygame.time.get_ticks() // 500) % 4)
        st = self.font_medium.render(base + dots, True, LIGHT_GRAY)
        self.screen.blit(st, (WINDOW_W // 2 - st.get_width() // 2, py + 65))
        cx_spin = WINDOW_W // 2
        cy_spin = py + 135
        t_val = pygame.time.get_ticks() / 500.0
        for i in range(8):
            angle = i * math.pi / 4 - t_val
            fade = 0.3 + 0.7 * ((i + int(t_val * 4)) % 8) / 7
            r = int(76 * fade + 30)
            g = int(175 * fade + 20)
            b = int(80 * fade + 20)
            dx = int(18 * math.cos(angle))
            dy = int(10 * math.sin(angle))
            pygame.draw.circle(self.screen, (r, g, b), (cx_spin + dx, cy_spin + dy), 4)

    def _draw_secret_screen(self):
        self._draw_bg(self.bg_game)
        self._draw_bulls_cows_rules_banner()
        px, py, pw, ph = 100, 154, 500, 432
        self._draw_panel(px, py, pw, ph, alpha=188)
        self._text_center(self.font_title, "Ваш ход: загадать число", WHITE, py + 14, shadow=True)
        icon = self.icon_bull_md if self.player_id == 1 else self.icon_cow_md
        pid = self.font_medium.render(f"Вы — Игрок {self.player_id}", True, GREEN_LIGHT)
        if icon:
            ix = WINDOW_W // 2 - (icon.get_width() + 10 + pid.get_width()) // 2
            self.screen.blit(icon, (ix, py + 58))
            self.screen.blit(pid, (ix + icon.get_width() + 10, py + 66))
        else:
            self.screen.blit(pid, (WINDOW_W // 2 - pid.get_width() // 2, py + 66))
        pygame.draw.line(self.screen, (150, 160, 150),
                         (px + 28, py + 108), (px + pw - 28, py + 108), 1)
        hints = [
            "Секретное число: ровно 4 разные цифры (например 1238).",
            "Соперник его не видит — угадывает по подсказкам быков и коров.",
        ]
        hy = py + 118
        for line in hints:
            s = self.font_small.render(line, True, GRAY)
            self.screen.blit(s, (WINDOW_W // 2 - s.get_width() // 2, hy))
            hy += 22
        fl = self.font_medium.render("Ваше секретное число:", True, LIGHT_GRAY)
        self.screen.blit(fl, (170, py + 276))
        self.secret_input.draw(self.screen)
        self.secret_btn.draw(self.screen)
        if self.error_msg:
            self._draw_error_notice(400, max_width=min(560, WINDOW_W - 40))

    def _draw_game_screen(self):
        self._draw_bg(self.bg_game)
        self._draw_panel(0, 0, WINDOW_W, 78, alpha=195, color=(5, 10, 3), radius=0)
        icon_l = self.icon_bull_md
        icon_r = self.icon_cow_md
        if icon_l:
            iy = 78 // 2 - icon_l.get_height() // 2
            self.screen.blit(icon_l, (10, iy))
        if icon_r:
            iy = 78 // 2 - icon_r.get_height() // 2
            self.screen.blit(icon_r, (WINDOW_W - icon_r.get_width() - 10, iy))
        status_color = GREEN_LIGHT if self.my_turn else ORANGE
        st = self.font_medium.render(self.status_msg, True, status_color)
        sx = WINDOW_W // 2 - st.get_width() // 2
        sh = self.font_medium.render(self.status_msg, True, BLACK)
        self.screen.blit(sh, (sx + 1, 30))
        self.screen.blit(st, (sx, 29))
        pid_s = self.font_small.render(f"Игрок {self.player_id}", True, GRAY)
        self.screen.blit(pid_s, (WINDOW_W - pid_s.get_width() - 70, 55))
        err_h = self._draw_error_notice(80, max_width=WINDOW_W - 28)
        hist_y0 = 82 + err_h + (8 if err_h else 0)
        self.history.rect = pygame.Rect(15, hist_y0, 670, 395)
        lbl = self.font_small.render("История ходов  (прокрутите колесом)", True, GRAY)
        self.screen.blit(lbl, (20, hist_y0 + 2))
        self.history.rect.y = hist_y0 + 21
        self.history.rect.h = max(120, 477 - self.history.rect.y)
        self.history.draw(self.screen)
        self._draw_panel(0, 480, WINDOW_W, 120, alpha=195, color=(5, 10, 3), radius=0)
        if self.my_turn:
            self.guess_input.draw(self.screen)
            self.guess_btn.draw(self.screen)
        else:
            wait = self.font_medium.render("Ждите хода соперника...", True, DARK_GRAY)
            self.screen.blit(wait, (20, 500))

    def _draw_game_over_screen(self):
        self._draw_bg(self.bg_game)
        self._draw_panel(0, 0, WINDOW_W, 105, alpha=200, color=(5, 10, 3), radius=0)
        big_icon = None
        if self.is_draw:
            big_icon = self.icon_bull_big
        elif self.you_win:
            big_icon = self.icon_bull_big
        else:
            big_icon = self.icon_cow_big
        if big_icon:
            self.screen.blit(big_icon, (15, 2))
        self._draw_result_msg(18)
        if self.opponent_wants_restart:
            note = self.font_small.render(
                "Соперник хочет сыграть снова! Нажмите «Играть снова».", True, YELLOW)
            self.screen.blit(note, (WINDOW_W // 2 - note.get_width() // 2, 76))
        self.history.rect = pygame.Rect(15, 110, 670, 400)
        lbl = self.font_small.render("История партии:", True, GRAY)
        self.screen.blit(lbl, (20, 112))
        self.history.rect.y = 130
        self.history.rect.h = END_SCREEN_BTN_Y - self.history.rect.y - 12
        self.history.draw(self.screen)
        self.play_again_btn.rect.y = END_SCREEN_BTN_Y
        self.exit_btn.rect.y = END_SCREEN_BTN_Y
        self.play_again_btn.draw(self.screen)
        self.exit_btn.draw(self.screen)

    def _draw_restart_status_bar(self):
        bar_y, bar_h = END_SCREEN_STATUS_Y, END_SCREEN_STATUS_H
        dots = "." * ((pygame.time.get_ticks() // 500) % 4)
        wait_text = f"Запрос отправлен. Ожидание соперника{dots}"
        self._draw_panel(0, bar_y, WINDOW_W, bar_h, alpha=190, color=(5, 10, 3), radius=0)
        wait = self.font_medium.render(wait_text, True, YELLOW)
        ty = bar_y + (bar_h - wait.get_height()) // 2
        self.screen.blit(wait, (WINDOW_W // 2 - wait.get_width() // 2, ty))

    def _draw_restart_wait_screen(self):
        self._draw_bg(self.bg_game)
        self._draw_panel(0, 0, WINDOW_W, 105, alpha=200, color=(5, 10, 3), radius=0)
        self._draw_result_msg(18)
        self.history.rect = pygame.Rect(15, 110, 670, 400)
        lbl = self.font_small.render("История партии:", True, GRAY)
        self.screen.blit(lbl, (20, 112))
        self.history.rect.y = 130
        self.history.rect.h = END_SCREEN_STATUS_Y - self.history.rect.y - 10
        self.history.draw(self.screen)
        self._draw_restart_status_bar()
        self.exit_btn.rect.y = END_SCREEN_BTN_Y
        self.exit_btn.draw(self.screen)

if __name__ == "__main__":
    ui = GameUI()
    ui.run()