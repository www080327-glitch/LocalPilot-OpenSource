"""Bounded request/reply transport to the offline tokenizer subprocess."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time


def tokenizer_fingerprint(directory):
    names = ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json",
             "vocab.json", "vocab.txt", "merges.txt", "tokenizer.model", "sentencepiece.bpe.model",
             "chat_template.jinja", "config.json")
    files = {name: hashlib.sha256((Path(directory) / name).read_bytes()).hexdigest()
             for name in names if (Path(directory) / name).is_file()}
    if not files:
        raise ValueError("No recognized tokenizer/template files are available")
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TokenizerProcess:
    def __init__(self, python, directory, *, timeout=30, script=None, stderr_path=None):
        self.timeout = timeout
        self.script = Path(script or Path(__file__).with_name("harbor_token_counter.py"))
        self.python, self.directory = str(python), str(directory)
        self.stderr_path = Path(stderr_path) if stderr_path else None
        self.process = None
        self._stderr = None

    def count(self, payload):
        if self.process is None:
            self._start()
        try:
            value = json.loads(self._exchange(json.dumps(payload, ensure_ascii=False).encode() + b"\n"))
            if not isinstance(value, dict) or type(value.get("input_tokens")) is not int or value["input_tokens"] < 0:
                reason = value.get("error", "invalid count") if isinstance(value, dict) else "invalid response"
                raise ValueError("Tokenizer refused request: " + str(reason))
            return value["input_tokens"]
        except BaseException:
            self.close()
            raise

    def _start(self):
        if self.stderr_path:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr = self.stderr_path.open("ab")
        environment = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "LANG", "TMPDIR"}}
        environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
        try:
            self.process = subprocess.Popen([self.python, str(self.script), self.directory],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr or subprocess.DEVNULL,
                bufsize=0, env=environment)
        except BaseException:
            if self._stderr:
                self._stderr.close()
                self._stderr = None
            raise
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)

    def _exchange(self, request):
        deadline = time.monotonic() + self.timeout
        sent, response = 0, bytearray()
        with selectors.DefaultSelector() as poll:
            poll.register(self.process.stdin, selectors.EVENT_WRITE)
            poll.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Offline tokenizer did not finish within its timeout")
                for key, _ in poll.select(remaining):
                    if key.fileobj is self.process.stdin:
                        sent += os.write(key.fd, request[sent:sent + 65536])
                        if sent == len(request):
                            poll.unregister(key.fileobj)
                    else:
                        part = os.read(key.fd, 65536)
                        if not part:
                            raise RuntimeError("Offline tokenizer exited without a complete response")
                        response.extend(part)
                        if len(response) > 65536:
                            raise ValueError("Offline tokenizer response is unexpectedly large")
                        if b"\n" in response:
                            line, remainder = response.split(b"\n", 1)
                            if remainder.strip():
                                raise ValueError("Offline tokenizer returned unsolicited output")
                            return line

    def close(self):
        if self.process is not None:
            process, self.process = self.process, None
            process.stdin.close()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            process.stdout.close()
        if self._stderr:
            self._stderr.close()
            self._stderr = None
