import docker


class Terminal:
    def __init__(self, container):
        self.client = docker.from_env()
        try:
            result = self.client.api.exec_create(
                container, ['/bin/bash', '-i'], stdin=True, stdout=True, stderr=True,
                tty=True, workdir='/workspace/challenge', environment={'HOME': '/tmp', 'TERM': 'xterm-256color'}
            )
            self.exec_id = result['Id']
            self.socket = self.client.api.exec_start(self.exec_id, tty=True, socket=True)
        except Exception:
            self.client.close()
            raise

    def read(self):
        return self.socket.recv(8192)

    def write(self, data):
        self.socket.sendall(data.encode('utf-8'))

    def resize(self, columns, rows):
        self.client.api.exec_resize(self.exec_id, height=rows, width=columns)

    def close(self):
        self.socket.close()
        self.client.close()
