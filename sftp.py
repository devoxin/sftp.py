import stat
import sys
from typing import Any, Dict, Iterable, List, Tuple

from paramiko import AutoAddPolicy, SSHClient
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer
from prompt_toolkit.completion.base import CompleteEvent, Completion
from prompt_toolkit.document import Document
from rich.progress import (BarColumn, DownloadColumn, Progress, TextColumn,
                           TimeRemainingColumn, TransferSpeedColumn)


class CommandCompleter(Completer):
    def __init__(self, word_gen):
        self.word_gen = word_gen
        self._last_word_count = -1
        self._word_cache = []

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        line_words = document.current_line.split(' ')

        if len(line_words) != self._last_word_count:
            self._word_cache = self.word_gen(document, complete_event)
            self._last_word_count = len(line_words)

        words = self._word_cache
        word_before_cursor = document.get_word_before_cursor().lower()

        for a in words:
            if word_before_cursor in a.lower():
                yield Completion(text=a, start_position=-len(word_before_cursor), display=a, display_meta="")


class FTPClient:
    def __init__(self, host: str, user: str, password: str):
        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())
        client.connect(hostname=host, port=22, username=user, password=password)

        self._client = client.open_sftp()
        self._closed = False
        self._pwd = ''

    def get_words(self, document: Document, complete_event: CompleteEvent) -> Iterable[str]:
        words = document.current_line.split(' ')

        if len(words) == 1:
            return ['quit', 'ls', 'cd', 'get', 'download']

        if len(words) == 2:
            if words[0] == 'cd':
                return [f'"{entry.filename}"' if ' ' in entry.filename else entry.filename for entry in self._client.listdir_attr() if stat.S_ISDIR(entry.st_mode or 0)]

            if words[0] in ('get', 'download'):
                return [f'"{entry.filename}"' if ' ' in entry.filename else entry.filename for entry in self._client.listdir_attr() if stat.S_ISREG(entry.st_mode or 0)]

        return []

    def start_interactive(self):
        while not self._closed:
            try:
                self._pwd = self._client.getcwd() or ''
                line = prompt('# ', completer=CommandCompleter(self.get_words)).split(' ')
                cmd = line[0]
                args = self._parse_args(' '.join(line[1:])) if len(line) > 1 else []

                if cmd in ('q', 'quit', 'exit'):
                    self._closed = True
                elif cmd == 'ls':
                    self.ls()
                elif cmd == 'cd':
                    if len(args) > 0:
                        path = '/'.join([self._pwd, args[0]])
                        self._execute_safely(lambda: self._client.chdir(path))
                elif cmd in ('get', 'download'):
                    if not 1 <= len(args) <= 2:
                        print('invalid command format, use "get <file> [save_location]"')
                        continue

                    if len(args) == 2:
                        fname, save_path = args
                    else:
                        fname, save_path = args[0], f'./{fname}'

                    self.download_file(fname, save_path)
                else:
                    print('Unknown command')
            except KeyboardInterrupt:
                self._closed = True
                break

        self._client.close()

    def ls(self):
        for entry in sorted(self._client.listdir_attr(), key=self._ls_sort):
            if stat.S_ISDIR(entry.st_mode or 0):
                symbol = '📁'
            elif stat.S_ISREG(entry.st_mode or 0):
                symbol = '📄'
            else:
                symbol = '?'

            print(f'{symbol} {entry.filename}')

    def download_file(self, fname: str, save_path: str):
        progress = Progress(
            TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn()
        )

        task_id = progress.add_task("download", filename=fname, start=True)

        def progress_callback(received: int, total: int):
            progress.update(task_id, completed=received, total=total)

        try:
            with progress:
                self._client.get('/'.join([self._pwd, fname]), save_path, progress_callback)
        except IOError as err:
            print(str(err))

    def _ls_sort(self, item) -> Tuple[int, Dict[str, Any]]:
        if stat.S_ISDIR(item.st_mode):
            return (1, item.filename)

        if stat.S_ISREG(item.st_mode):
            return (2, item.filename)

        return (3, item.filename)
        
    def _parse_args(self, args) -> List[str]:
        parsed = []

        arg = ''
        escaping = False
        quote = None
        index = 0

        for char in list(args):
            index += 1

            if escaping:
                arg += char
                escaping = False
            elif char == '\\':
                escaping = True
            elif quote is not None and char == quote:
                quote = None
            elif quote is None and char in ('"', '\''):
                quote = char
            elif quote is None and char == ' ':
                if arg:
                    parsed.append(arg)

                arg = ''
            else:
                arg += char

        if quote is not None:
            raise ValueError(f'Unterminated quote at index {index}')

        if escaping:
            raise ValueError(f'Escape sequence is not followed by a character at index {index}')

        if arg:
            parsed.append(arg)

        return parsed

    def _execute_safely(self, cmd):
        try:
            return True, cmd()
        except IOError as err:
            print(str(err))

        return False, None

    def format_size(self, num, suffix='B'):
        for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
            if abs(num) < 1024.0:
                return f'{num:3.1f} {unit}{suffix}'

            num /= 1024.0

        return f'{num:.1f} Yi{suffix}'

if __name__ == '__main__':
    if len(sys.argv) == 4:
        host, username, password = sys.argv[1:]
    else:
        host = input('Server hostname: ')
        username = input('Username: ')
        password = input('Password: ')

    print('Connecting...')
    client = FTPClient(host, username, password)
    client.start_interactive()
