#!/usr/bin/env python3
# Dohyun AI - local desktop chat powered by Ollama
# No API key. Uses only Python standard library + Ollama's local HTTP API.

import json
import os
import queue
import threading
import urllib.request
import urllib.error
import uuid
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

APP_NAME = "Dohyun AI"
OLLAMA_URL = "http://localhost:11434"
DATA_DIR = Path.home() / ".dohyun_ai"
DATA_FILE = DATA_DIR / "chats.json"
DEFAULT_SYSTEM = (
    "너는 Dohyun AI라는 친절하고 정확한 한국어 AI 도우미야. "
    "사용자의 질문에 핵심부터 답하고, 모르는 내용은 아는 척하지 말고 불확실하다고 말해. "
    "필요하면 단계별로 설명하고, 읽기 쉽게 문단과 목록을 사용해."
)

BG = "#10131c"
PANEL = "#171c28"
PANEL2 = "#202738"
INPUT = "#252d40"
TEXT = "#edf1fa"
MUTED = "#9ba7bd"
ACCENT = "#8b7cff"
ACCENT_HOVER = "#7667ee"
USER_BUBBLE = "#34305b"
BOT_BUBBLE = "#1b2433"
GREEN = "#58c99a"
RED = "#ff7777"


class DohyunAI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1120x760")
        self.root.minsize(820, 580)
        self.root.configure(bg=BG)

        self.events = queue.Queue()
        self.busy = False
        self.stop_requested = False
        self.chats = []
        self.current_chat_id = None
        self.system_prompt = DEFAULT_SYSTEM
        self.model_var = tk.StringVar(value="qwen3:4b")
        self.status_var = tk.StringVar(value="Ollama 연결 확인 중…")
        self._load_data()
        self._build_ui()
        self._load_or_create_chat()
        self.root.after(100, self._poll_events)
        self.root.after(300, self.refresh_models)

    def _load_data(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self.chats = data.get("chats", [])
            self.system_prompt = data.get("system_prompt", DEFAULT_SYSTEM)
        except Exception:
            self.chats = []

    def _save_data(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"chats": self.chats, "system_prompt": self.system_prompt}
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=INPUT, background=PANEL2,
                        foreground=TEXT, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT)],
                  foreground=[("readonly", TEXT)])

        self.sidebar = tk.Frame(self.root, bg=PANEL, width=255)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=PANEL)
        brand.pack(fill="x", padx=18, pady=(22, 16))
        tk.Label(brand, text="✦", fg=ACCENT, bg=PANEL,
                 font=("Arial", 23, "bold")).pack(side="left")
        tk.Label(brand, text="  DOHYUN AI", fg=TEXT, bg=PANEL,
                 font=("Arial", 15, "bold")).pack(side="left")

        self._button(self.sidebar, "+  새 채팅", self.new_chat,
                     bg=ACCENT, hover=ACCENT_HOVER).pack(fill="x", padx=14, pady=(2, 16))

        tk.Label(self.sidebar, text="대화 기록", fg=MUTED, bg=PANEL,
                 font=("Arial", 9, "bold")).pack(anchor="w", padx=18, pady=(0, 8))
        self.chat_list = tk.Frame(self.sidebar, bg=PANEL)
        self.chat_list.pack(fill="both", expand=True, padx=9)

        bottom = tk.Frame(self.sidebar, bg=PANEL)
        bottom.pack(fill="x", padx=14, pady=14)
        self._button(bottom, "⚙  AI 설정", self.open_settings,
                     bg=PANEL2, hover="#303a50").pack(fill="x", pady=3)
        self._button(bottom, "↻  모델 새로고침", self.refresh_models,
                     bg=PANEL2, hover="#303a50").pack(fill="x", pady=3)
        tk.Label(bottom, text="LOCAL AI  •  API KEY NOT REQUIRED",
                 fg="#71809a", bg=PANEL, font=("Arial", 7, "bold")).pack(pady=(12, 0))

        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        top = tk.Frame(main, bg=BG, height=66)
        top.pack(fill="x", padx=26, pady=(16, 6))
        top.pack_propagate(False)
        title_area = tk.Frame(top, bg=BG)
        title_area.pack(side="left", fill="y")
        tk.Label(title_area, text="대화", fg=TEXT, bg=BG,
                 font=("Arial", 17, "bold")).pack(anchor="w", pady=(5, 0))
        tk.Label(title_area, textvariable=self.status_var, fg=MUTED, bg=BG,
                 font=("Arial", 9)).pack(anchor="w")

        model_area = tk.Frame(top, bg=BG)
        model_area.pack(side="right", pady=9)
        tk.Label(model_area, text="MODEL", fg=MUTED, bg=BG,
                 font=("Arial", 8, "bold")).pack(side="left", padx=(0, 8))
        self.model_combo = ttk.Combobox(model_area, textvariable=self.model_var,
                                        width=20, state="normal")
        self.model_combo.pack(side="left")

        self.chat_canvas = tk.Canvas(main, bg=BG, highlightthickness=0)
        self.chat_scroll = ttk.Scrollbar(main, orient="vertical", command=self.chat_canvas.yview)
        self.messages_frame = tk.Frame(self.chat_canvas, bg=BG)
        self.messages_window = self.chat_canvas.create_window((0, 0), window=self.messages_frame, anchor="nw")
        self.messages_frame.bind("<Configure>", self._on_messages_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)
        self.chat_canvas.configure(yscrollcommand=self.chat_scroll.set)
        self.chat_scroll.pack(side="right", fill="y", padx=(0, 8))
        self.chat_canvas.pack(side="left", fill="both", expand=True, padx=(22, 0), pady=(4, 8))

        composer = tk.Frame(main, bg=PANEL, highlightbackground="#30394c",
                            highlightthickness=1)
        composer.pack(fill="x", padx=28, pady=(4, 22))
        self.input_text = tk.Text(composer, height=3, wrap="word", bg=PANEL,
                                  fg=TEXT, insertbackground=TEXT, relief="flat",
                                  font=("Arial", 11), padx=14, pady=12,
                                  undo=True)
        self.input_text.pack(fill="x", padx=4, pady=(4, 0))
        self.input_text.bind("<Return>", self._enter_to_send)
        self.input_text.bind("<Shift-Return>", lambda e: None)
        bottom_row = tk.Frame(composer, bg=PANEL)
        bottom_row.pack(fill="x", padx=10, pady=(0, 8))
        tk.Label(bottom_row, text="Enter 전송 · Shift+Enter 줄바꿈",
                 fg=MUTED, bg=PANEL, font=("Arial", 8)).pack(side="left")
        self.send_button = self._button(bottom_row, "보내기  ➤", self.send_message,
                                        bg=ACCENT, hover=ACCENT_HOVER, padx=18)
        self.send_button.pack(side="right")

        self._render_chat_list()

    def _button(self, parent, text, command, bg=PANEL2, hover="#303a50", padx=12):
        return tk.Button(parent, text=text, command=command, bg=bg, fg=TEXT,
                         activebackground=hover, activeforeground=TEXT,
                         relief="flat", bd=0, padx=padx, pady=10,
                         font=("Arial", 10, "bold"), cursor="hand2")

    def _on_messages_configure(self, _event=None):
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.chat_canvas.itemconfigure(self.messages_window, width=event.width)

    def _enter_to_send(self, event):
        if not (event.state & 0x1):  # Shift not pressed
            self.send_message()
            return "break"
        return None

    def _load_or_create_chat(self):
        if self.chats:
            self.current_chat_id = self.chats[-1]["id"]
        else:
            self.new_chat()
            return
        self.render_messages()
        self._render_chat_list()

    def _current_chat(self):
        for chat in self.chats:
            if chat["id"] == self.current_chat_id:
                return chat
        return None

    def new_chat(self):
        if self.busy:
            return
        chat = {"id": str(uuid.uuid4()), "title": "새 대화",
                "messages": [], "updated": datetime.now().isoformat(timespec="seconds")}
        self.chats.append(chat)
        self.current_chat_id = chat["id"]
        self._save_data()
        self.render_messages()
        self._render_chat_list()
        self.input_text.focus_set()

    def select_chat(self, chat_id):
        if self.busy:
            return
        self.current_chat_id = chat_id
        self.render_messages()
        self._render_chat_list()

    def _render_chat_list(self):
        for child in self.chat_list.winfo_children():
            child.destroy()
        for chat in reversed(self.chats[-40:]):
            selected = chat["id"] == self.current_chat_id
            b = tk.Button(self.chat_list, text="  " + chat.get("title", "새 대화"),
                          command=lambda cid=chat["id"]: self.select_chat(cid),
                          anchor="w", bg=("#30304d" if selected else PANEL),
                          fg=TEXT if selected else MUTED, relief="flat", bd=0,
                          padx=10, pady=10, font=("Arial", 9),
                          activebackground="#30304d", activeforeground=TEXT,
                          cursor="hand2")
            b.pack(fill="x", pady=2)

    def render_messages(self):
        for child in self.messages_frame.winfo_children():
            child.destroy()
        chat = self._current_chat()
        if not chat or not chat["messages"]:
            welcome = tk.Frame(self.messages_frame, bg=BG)
            welcome.pack(expand=True, fill="both", pady=100)
            tk.Label(welcome, text="✦", fg=ACCENT, bg=BG,
                     font=("Arial", 38)).pack()
            tk.Label(welcome, text="무엇이든 물어보세요", fg=TEXT, bg=BG,
                     font=("Arial", 21, "bold")).pack(pady=(8, 5))
            tk.Label(welcome, text="Dohyun AI가 로컬에서 답변할게요.",
                     fg=MUTED, bg=BG, font=("Arial", 10)).pack()
        else:
            for msg in chat["messages"]:
                self._add_message_widget(msg["role"], msg["content"])
        self.root.after(80, lambda: self.chat_canvas.yview_moveto(1.0))

    def _add_message_widget(self, role, content):
        outer = tk.Frame(self.messages_frame, bg=BG)
        outer.pack(fill="x", padx=18, pady=9)
        is_user = role == "user"
        row = tk.Frame(outer, bg=BG)
        row.pack(anchor="e" if is_user else "w", fill="x")
        name = "나" if is_user else "Dohyun AI"
        bubble_color = USER_BUBBLE if is_user else BOT_BUBBLE
        bubble = tk.Frame(row, bg=bubble_color, padx=14, pady=11)
        bubble.pack(side="right" if is_user else "left", anchor="e" if is_user else "w")
        tk.Label(bubble, text=name, fg="#c5bbff" if is_user else GREEN,
                 bg=bubble_color, font=("Arial", 8, "bold")).pack(anchor="w")
        label = tk.Label(bubble, text=content, fg=TEXT, bg=bubble_color,
                         justify="left", anchor="w", wraplength=650,
                         font=("Arial", 10), padx=0, pady=5)
        label.pack(anchor="w")
        return label

    def _append_to_visible(self, role, content):
        widget = self._add_message_widget(role, content)
        self.root.after(50, lambda: self.chat_canvas.yview_moveto(1.0))
        return widget

    def refresh_models(self):
        def worker():
            try:
                req = urllib.request.Request(OLLAMA_URL + "/api/tags")
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode("utf-8"))
                names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                self.events.put(("models", names))
            except Exception as exc:
                self.events.put(("connection_error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def send_message(self):
        if self.busy:
            return
        prompt = self.input_text.get("1.0", "end").strip()
        if not prompt:
            return
        model = self.model_var.get().strip()
        if not model:
            messagebox.showwarning(APP_NAME, "사용할 모델 이름을 입력하거나 모델을 선택해 주세요.")
            return
        chat = self._current_chat()
        if not chat:
            self.new_chat()
            chat = self._current_chat()
        self.input_text.delete("1.0", "end")
        chat["messages"].append({"role": "user", "content": prompt})
        if chat["title"] == "새 대화":
            chat["title"] = prompt[:24] + ("…" if len(prompt) > 24 else "")
        self._append_to_visible("user", prompt)
        self._render_chat_list()
        self._save_data()

        self.busy = True
        self.stop_requested = False
        self.send_button.configure(text="생성 중…", state="disabled")
        self.status_var.set(f"{model} 답변 생성 중…")
        self._stream_text = ""
        self._stream_label = self._append_to_visible("assistant", "생각하는 중…")
        history = [{"role": m["role"], "content": m["content"]}
                   for m in chat["messages"]]
        system_prompt = self.system_prompt
        threading.Thread(target=self._chat_worker,
                         args=(model, history, system_prompt), daemon=True).start()

    def _chat_worker(self, model, history, system_prompt):
        body = {"model": model,
                "messages": [{"role": "system", "content": system_prompt}] + history,
                "stream": True}
        req = urllib.request.Request(
            OLLAMA_URL + "/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST")
        answer = ""
        try:
            with urllib.request.urlopen(req, timeout=600) as response:
                for raw in response:
                    if self.stop_requested:
                        break
                    if not raw.strip():
                        continue
                    item = json.loads(raw.decode("utf-8"))
                    piece = item.get("message", {}).get("content", "")
                    if piece:
                        answer += piece
                        self.events.put(("token", piece))
            if not answer:
                answer = "(응답이 생성되지 않았어요.)"
            self.events.put(("finished", answer))
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            self.events.put(("error", f"Ollama에 연결할 수 없어요.\nOllama가 실행 중인지 확인해 주세요.\n\n세부 정보: {reason}"))
        except Exception as exc:
            self.events.put(("error", f"오류가 발생했어요: {exc}"))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "models":
                    names = event[1]
                    self.model_combo["values"] = names
                    if names:
                        current = self.model_var.get()
                        if current not in names:
                            preferred = next((n for n in names if n.startswith("qwen3:4b")), names[0])
                            self.model_var.set(preferred)
                        self.status_var.set(f"연결됨 · 설치된 모델 {len(names)}개")
                    else:
                        self.status_var.set("연결됨 · 설치된 모델 없음")
                elif kind == "connection_error":
                    self.status_var.set("Ollama 연결 안 됨 · 설치/실행을 확인하세요")
                elif kind == "token":
                    chat = self._current_chat()
                    if chat:
                        # update last assistant bubble
                        self._stream_text += event[1]
                        if self._stream_label and self._stream_label.winfo_exists():
                            self._stream_label.configure(text=self._stream_text, wraplength=650)
                        self.root.after(20, lambda: self.chat_canvas.yview_moveto(1.0))
                elif kind == "finished":
                    self._finish_answer(event[1])
                elif kind == "error":
                    self._finish_answer("⚠ " + event[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish_answer(self, answer):
        chat = self._current_chat()
        if chat:
            # Replace the in-progress placeholder with the final answer.
            if chat["messages"] and chat["messages"][-1]["role"] == "user":
                chat["messages"].append({"role": "assistant", "content": answer})
            elif chat["messages"] and chat["messages"][-1]["role"] == "assistant":
                chat["messages"][-1]["content"] = answer
            self._save_data()
        if getattr(self, "_stream_label", None) and self._stream_label.winfo_exists():
            self._stream_label.configure(text=answer)
        self.busy = False
        self.send_button.configure(text="보내기  ➤", state="normal")
        self.status_var.set("준비됨")
        self._render_chat_list()


if __name__ == "__main__":
    root = tk.Tk()
    app = DohyunAI(root)
    root.mainloop()
