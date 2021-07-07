
import select
import urllib.parse
import socket
import http.client
import time
import os
import utils
import ssl


class Connection():
    def __init__(self, sock):
        self.sock = sock
        self.create_time = time.time()

    def close(self):
        self.sock.close()


class BaseResponse(object):
    def __init__(self, status=601, reason=b"", headers={}, body=b""):
        self.status = status
        self.reason = reason
        self.headers = {}
        for key in headers:
            if isinstance(key, tuple):
                key, value = key
            else:
                value = headers[key]
            key = key.title()
            self.headers[key] = value

        self.text = body

    def getheader(self, key, default_value=b""):
        key = key.title()
        if key in self.headers:
            return self.headers[key]
        else:
            return default_value


class TxtResponse(BaseResponse):
    def __init__(self, buffer):
        BaseResponse.__init__(self)
        if isinstance(buffer, memoryview):
            self.view = buffer
            self.read_buffer = buffer.tobytes()
        elif isinstance(buffer, str):
            self.read_buffer = utils.to_bytes(buffer)
            self.view = memoryview(self.read_buffer)
        elif isinstance(buffer, bytes):
            self.read_buffer = buffer
            self.view = memoryview(buffer)
        else:
            raise Exception("TxtResponse error")

        self.buffer_start = 0
        self.parse()

    def read_line(self):
        n1 = self.read_buffer.find(b"\r\n", self.buffer_start)
        if n1 == -1:
            raise Exception("read_line fail")

        line = self.read_buffer[self.buffer_start:n1]
        self.buffer_start = n1 + 2
        return line

    def read_headers(self):
        n1 = self.read_buffer.find(b"\r\n\r\n", self.buffer_start)
        if n1 == -1:
            raise Exception("read_headers fail")
        block = self.read_buffer[self.buffer_start:n1]
        self.buffer_start = n1 + 4
        return block

    def parse(self):
        requestline = self.read_line()
        words = requestline.split()
        if len(words) < 2:
            raise Exception("status line:%s" % requestline)

        self.version = words[0]
        self.status = int(words[1])
        self.info = b" ".join(words[2:])

        self.headers = {}
        header_block = self.read_headers()
        lines = header_block.split(b"\r\n")
        for line in lines:
            p = line.find(b":")
            key = line[0:p]
            value = line[p+2:]
            key = str(key.title())
            self.headers[key] = value

        self.body = self.view[self.buffer_start:]
        self.read_buffer = b""
        self.buffer_start = 0


class Response(BaseResponse):
    def __init__(self, ssl_sock):
        BaseResponse.__init__(self)
        self.connection = ssl_sock
        ssl_sock.settimeout(1)
        self.read_buffer = b""
        self.buffer_start = 0
        self.chunked = False

    def read_line(self, timeout=60):
        start_time = time.time()
        sock = self.connection
        sock.setblocking(0)
        try:
            while True:
                n1 = self.read_buffer.find(b"\r\n", self.buffer_start)
                if n1 > -1:
                    line = self.read_buffer[self.buffer_start:n1]
                    self.buffer_start = n1 + 2
                    return line

                if time.time() - start_time > timeout:
                    raise socket.timeout()
                time.sleep(0.001)
                try:
                    data = sock.recv(8192)
                except socket.error as e:
                    # logging.exception("e:%r", e)
                    if e.errno in [2, 11, 10035]:
                        #time.sleep(0.1)
                        time_left = start_time + timeout - time.time()
                        r, w, e = select.select([sock], [], [], time_left)
                        continue
                    else:
                        raise e

                if isinstance(data, int):
                    continue
                if data and len(data):
                    self.read_buffer += data
        finally:
            sock.setblocking(1)

    def read_headers(self, timeout=60):
        start_time = time.time()
        sock = self.connection
        sock.setblocking(0)
        try:
            while True:
                n1 = self.read_buffer.find(b"\r\n\r\n", self.buffer_start)
                if n1 > -1:
                    block = self.read_buffer[self.buffer_start:n1]
                    self.buffer_start = n1 + 4
                    return block

                if time.time() - start_time > timeout:
                    raise socket.timeout()

                time.sleep(0.001)
                try:
                    data = sock.recv(8192)
                except socket.error as e:
                    # logging.exception("e:%r", e)
                    if e.errno in [2, 11, 10035]:
                        time.sleep(0.1)
                        continue
                    else:
                        raise e

                self.read_buffer += data
        except Exception as e:
            print(e)
        finally:
            sock.setblocking(1)

    def begin(self, timeout=60):
        start_time = time.time()
        line = self.read_line(500)

        requestline = line.rstrip(b'\r\n')
        words = requestline.split()
        if len(words) < 2:
            raise Exception("status line:%s" % requestline)

        self.version = words[0]
        self.status = int(words[1])
        self.reason = b" ".join(words[2:])

        self.headers = {}
        timeout -= time.time() - start_time
        timeout = max(timeout, 0.1)
        header_block = self.read_headers(timeout)
        lines = header_block.split(b"\r\n")
        for line in lines:
            p = line.find(b":")
            key = line[0:p]
            value = line[p+2:]
            key = key.title()
            self.headers[key] = value

        self.content_length = self.getheader(b"content-length", b"")
        if b"chunked" in self.getheader(b"Transfer-Encoding", b""):
            self.chunked = True
            self.chunk_list = []

        if b"gzip" in self.getheader(b"Transfer-Encoding", b""):
            print("not work")

    def _read_plain(self, read_len, timeout):
        if read_len == 0:
            return ""
        #elif read_len > 0:
        #    return self._read_size(read_len, timeout)

        if read_len is not None and len(self.read_buffer) - self.buffer_start > read_len:
            out_str = self.read_buffer[self.buffer_start:self.buffer_start + read_len]
            self.buffer_start += read_len
            if len(self.read_buffer) == self.buffer_start:
                self.read_buffer = b""
                self.buffer_start = 0
            return out_str

        self.connection.setblocking(0)
        start_time = time.time()
        out_len = len(self.read_buffer) - self.buffer_start
        out_list = [ self.read_buffer[self.buffer_start:] ]

        self.read_buffer = b""
        self.buffer_start = 0

        while time.time() - start_time < timeout:
            if not read_len and out_len > 0:
                break

            if read_len and out_len >= read_len:
                break

            if read_len:
                to_read = read_len - out_len
                to_read = min(to_read, 65535)
            else:
                to_read = 65535
            try:
                data = self.connection.recv(to_read)
            except socket.error as e:
                # logging.exception("e:%r", e)
                if e.errno in [2, 11, 10035]:
                    #time.sleep(0.1)
                    time_left = start_time + timeout - time.time()
                    r, w, e = select.select([self.connection], [], [], time_left)
                    continue
                else:
                    raise e

            if data:
                out_list.append(data)
                out_len += len(data)
        if read_len is not None and out_len < read_len:
            raise socket.timeout()

        return b"".join(out_list)

    def _read_size(self, read_len, timeout):
        if len(self.read_buffer) - self.buffer_start > read_len:
            buf = memoryview(self.read_buffer)
            out_str = buf[self.buffer_start:self.buffer_start + read_len]
            self.buffer_start += read_len
            if len(self.read_buffer) == self.buffer_start:
                self.read_buffer = b""
                self.buffer_start = 0
            return out_str

        self.connection.setblocking(0)
        start_time = time.time()
        out_len = len(self.read_buffer) - self.buffer_start
        out_bytes = bytearray(read_len)
        view = memoryview(out_bytes)
        view[0:out_len] = self.read_buffer[self.buffer_start:]

        self.read_buffer = b""
        self.buffer_start = 0

        while time.time() - start_time < timeout:
            if out_len >= read_len:
                break

            to_read = read_len - out_len
            to_read = min(to_read, 65535)

            try:
                nbytes = self.connection.recv_into(view[out_len:], to_read)
            except socket.error as e:
                # logging.exception("e:%r", e)
                if e.errno in [2, 11, 10035]:
                    # time.sleep(0.1)
                    time_left = start_time + timeout - time.time()
                    r, w, e = select.select([self.connection], [], [], time_left)
                    continue
                else:
                    raise e

            out_len += nbytes
        if out_len < read_len:
            raise socket.timeout()

        return out_bytes

    def _read_chunked(self, timeout):
        line = self.read_line(timeout)
        chunk_size = int(line, 16)
        dat = self._read_plain(chunk_size + 2, timeout)
        return dat[:-2]

    def read(self, read_len=None, timeout=60):
        #if not read_len and self.content_length is not None:
        #    read_len = int(self.content_length)

        if not self.chunked:
            data = self._read_plain(read_len, timeout)
        else:
            data = self._read_chunked(timeout)
        return data

    def readall(self, timeout=60):
        start_time = time.time()
        if self.chunked:
            out_list = []
            while True:
                time_left = timeout - (time.time() - start_time)
                if time_left < 0:
                    raise socket.timeout()

                dat = self._read_chunked(time_left)
                if not dat:
                    break

                out_list.append(dat)

            return b"".join(out_list)
        else:
            return self._read_plain(int(self.content_length), timeout=timeout)


class Client(object):
    def __init__(self, proxy=None, timeout=60, cert=""):
        self.timeout = timeout
        self.cert = cert
        self.connection = None
        self.host = None
        self.port = None
        self.tls = None

        if isinstance(proxy, str):
            proxy_sp = urllib.parse.urlsplit(proxy)

            self.proxy = {
                "type": proxy_sp.scheme,
                "host": proxy_sp.hostname,
                "port": proxy_sp.port,
                "user": proxy_sp.username,
                "pass": proxy_sp.password
            }
        elif isinstance(proxy, dict):
            self.proxy = proxy
        else:
            self.proxy = None

    def direct_connect(self, host, port):
        connect_timeout = 30

        if b':' in host:
            info = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (host, port, 0, 0))]
        elif utils.check_ip_valid4(host):
            info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))]
        else:
            try:
                info = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
                                          socket.SOCK_STREAM)
            except socket.gaierror:
                info = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))]

        for res in info:
            af, socktype, proto, canonname, sa = res
            s = None
            try:
                s = socket.socket(af, socktype, proto)
                # See http://groups.google.com/group/cherrypy-users/
                #        browse_frm/thread/bbfe5eb39c904fe0

                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024)
                s.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, True)
                s.settimeout(connect_timeout)
                s.connect((host, port))
                return s
            except socket.error:
                if s:
                    s.close()

        return None

    def connect(self, host, port, tls):
        if self.connection and host == self.host and port == self.port and self.tls == tls:
            return self.connection

        if not self.proxy:
            sock = self.direct_connect(host, port)
        else:
            connect_timeout = 5

            import socks

            sock = socks.socksocket(socket.AF_INET)
            sock.set_proxy(proxy_type=self.proxy["type"],
                           addr=self.proxy["host"],
                           port=self.proxy["port"], rdns=True,
                           username=self.proxy["user"],
                           password=self.proxy["pass"])

            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32*1024)
            sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, True)
            sock.settimeout(connect_timeout)

            sock.connect((host, port))

            # conn_time = time.time() - start_time
            # xlog.debug("proxy:%s tcp conn:%s time:%d", proxy["host"], host, conn_time * 1000)

        if tls:
            if os.path.isfile(self.cert):
                sock = ssl.wrap_socket(sock, ca_certs=self.cert)
            else:
                sock = ssl.wrap_socket(sock)

        self.connection = sock
        self.host = host
        self.port = port
        self.tls = tls

        return sock

    def request(self, method, url, headers={}, body=b"", read_payload=True):
        method = utils.to_bytes(method)
        url = utils.to_bytes(url)

        upl = urllib.parse.urlsplit(url)
        headers[b"Content-Length"] = str(len(body))
        headers[b"Host"] = upl.netloc
        port = upl.port
        if not port:
            if upl.scheme == b"http":
                port = 80
            elif upl.scheme == b"https":
                port = 443
            else:
                raise Exception("unknown method:%s" % upl.scheme)

        path = upl.path
        if not path:
            path = b"/"

        if upl.query:
            path += b"?" + upl.query

        sock = self.connect(upl.hostname, port, upl.scheme == b"https")
        if not sock:
            return None

        request_data = b'%s %s HTTP/1.1\r\n' % (method, path)

        for k, v in headers.items():
            if isinstance(v, int):
                request_data += b'%s: %d\r\n' % (utils.to_bytes(k), v)
            else:
                request_data += b'%s: %s\r\n' % (utils.to_bytes(k), utils.to_bytes(v))

        request_data += b'\r\n'

        body = utils.to_bytes(body)

        if len(request_data) + len(body) < 1300:
            body = request_data + body
        else:
            sock.send(request_data)

        payload_len = len(body)
        start = 0
        while start < payload_len:
            send_size = min(payload_len - start, 65535)
            sended = sock.send(body[start:start + send_size])
            start += sended

        sock.settimeout(self.timeout)
        response = Response(sock)

        response.begin(timeout=self.timeout)

        if response.status != 200:
            #logging.warn("status:%r", response.status)
            return response

        if not read_payload:
            return response

        if b'Transfer-Encoding' in response.headers:
            data_buffer = []
            while True:
                try:
                    data = response.read(8192, timeout=self.timeout)
                except http.client.IncompleteRead as e:
                    data = e.partial
                except Exception as e:
                    raise e

                if not data:
                    break
                else:
                    data_buffer.append(data)

            response.text = b"".join(data_buffer)
            return response
        else:
            content_length = int(response.getheader(b'Content-Length', 0))
            if content_length:
                response.text = response.read(content_length, timeout=self.timeout)

            return response


def request(method="GET", url=None, headers={}, body="", proxy=None, timeout=60, read_payload=True):
    if not url:
        raise Exception("no url")

    client = Client(proxy, timeout=timeout)
    return client.request(method, url, headers, body, read_payload)

