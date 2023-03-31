import _thread
import json
import os
import socket

ENABLE_MULTITHREAD = True  # default: True
BUFFER_SIZE = 4096  # default: 4096

HTTP_STATUS_CODES = {  # copy from werkzeug/http.py
    100: "Continue",
    101: "Switching Protocols",
    102: "Processing",
    200: "OK",
    201: "Created",
    202: "Accepted",
    203: "Non Authoritative Information",
    204: "No Content",
    205: "Reset Content",
    206: "Partial Content",
    207: "Multi Status",
    226: "IM Used",  # see RFC 3229
    300: "Multiple Choices",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    305: "Use Proxy",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",  # unused
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Request Entity Too Large",
    414: "Request URI Too Long",
    415: "Unsupported Media Type",
    416: "Requested Range Not Satisfiable",
    417: "Expectation Failed",
    418: "I'm a teapot",  # see RFC 2324
    421: "Misdirected Request",  # see RFC 7540
    422: "Unprocessable Entity",
    423: "Locked",
    424: "Failed Dependency",
    426: "Upgrade Required",
    428: "Precondition Required",  # see RFC 6585
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    449: "Retry With",  # proprietary MS extension
    451: "Unavailable For Legal Reasons",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "HTTP Version Not Supported",
    507: "Insufficient Storage",
    510: "Not Extended",
}


class Request:
    def __init__(self, http_request):
        # 参考 https://blog.csdn.net/u011146423/article/details/88191225
        # https://www.cnblogs.com/serpent/p/9445592.html
        self.method = None  # 请求方法，如 GET POST PUT DELETE
        self.path = None  # 请求路径，如 /index.html
        self.headers = dict()  # HTTP头部字典
        self.args = dict()  # 从URL解析的参数字典
        self.form = dict()  # 从请求内容解析的字典
        self.values = dict()  # = self.args + self.form 如果存在同key，args会覆盖form
        self.data = ""  # 请求body
        self.json = dict()  # 从请求body解析的json
        self.http_request = http_request
        self.process()

    def process(self):
        first_line = True
        while True:
            line = self.http_request.readline().strip().decode("utf8")
            print(line)
            if not line:  # or line in ('\r\n', '\n', '')
                break
            if first_line:  # 处理第一行（方法，路径，协议）
                first_line = False
                self.method, self.path, _ = line.split()
                # 处理args
                if self.path.find("?") >= 0:
                    self.path, args_string = self.path.split("?")
                    if args_string:
                        for kv in args_string.split("&"):
                            key, value = kv.split("=")
                            self.args[key] = value
            else:  # 处理http头部
                if line.find(":") == -1:
                    continue
                key, value = line.split(":", 1)
                value = value.lstrip(" ")
                self.headers[key] = value
        # 处理后续数据
        if "Content-Length" in self.headers:
            self.headers["Content-Length"] = int(self.headers["Content-Length"])
            self.data = self.http_request.read(self.headers["Content-Length"])
            print(self.data.decode("utf8"))
            print()
            if "Content-Type" not in self.headers or self.headers["Content-Type"] == "application/x-www-form-urlencoded":
                for kv in self.data.decode("utf8").split("&"):
                    if kv.find("=") == -1:
                        key = kv
                        value = ""
                    else:
                        key, value = kv.split("=")
                    self.form[key] = value
            elif self.headers["Content-Type"] == "application/json":
                self.json = json.loads(self.data.decode("utf8"))
        # 更新self.values
        self.values = self.args.copy()
        self.values.update(self.form)

    def print(self):
        print("method:", self.method)
        print("path:", self.path)
        print("headers:", self.headers)
        print("form:", self.form)
        print("args:", self.args)
        print("values:", self.values)
        print("json:", self.json)
        print("data:", self.data)


class WebServer:
    def __init__(self, name):
        self.name = name
        self.route_map = dict()  # key为(path,method)，value为函数

    def add_route(self, endpoint, func, **options):
        """添加endpoint和func到route_map"""
        methods = options.pop("methods", None)
        if not methods:
            methods = ["GET"]
        for method in methods:
            self.route_map[(endpoint, method)] = func

    def route(self, endpoint, **options):
        """实现类似flask的route方法"""

        def wrapper(func):
            self.add_route(endpoint, func, **options)
            return func

        return wrapper

    @staticmethod
    def make_response(body, status_code, headers):
        headers_str = ""
        for header, value in headers.items():
            headers_str += "%s: %s\r\n" % (header, value)
        response = "HTTP/1.1 {status_code} {status_code_description}\r\nConnection: close\r\nContent-Length: {body_length}\r\n{headers_str}\r\n{body}".format(
            status_code=status_code,
            status_code_description=HTTP_STATUS_CODES[status_code],
            body_length=len(body.encode("utf8")),
            headers_str=headers_str,
            body=body
        ).encode("utf8")
        return response

    def handle_request(self, conn, address):
        try:
            file = conn.makefile('rb', 0)
            request = Request(file)
            # 执行route_map的函数
            if (request.path, request.method) in self.route_map:
                try:
                    response = self.route_map[(request.path, request.method)](request)  # 不知道怎么把request弄成像flask那样global的，所以使用参数代替
                    body = response
                    status_code = 200
                    headers = {}
                    if type(response) == tuple:
                        if len(response) == 3:
                            body, status_code, headers = response
                        elif len(response) == 2:
                            body, status_code = response
                    response = self.make_response(body, status_code, headers)
                except Exception as e:
                    print("Exception in handle_request:", repr(e))
                    response = b"HTTP/1.1 500 Internal Server Error\r\nConnection: close\r\nContent-Length: 3\r\n\r\n500"
                conn.sendall(response)
                del response
            else:
                # 尝试检查文件，如果文件不存在则返回404
                try:
                    file_size = os.stat(request.path)[6]
                    with open(request.path, "rb") as f:
                        conn.sendall(("HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: %s\r\n\r\n" % file_size).encode())
                        while True:  # 分段上传，避免吃爆内存
                            file_data = f.read(BUFFER_SIZE)
                            if file_data:
                                conn.sendall(file_data)
                                del file_data  # 垃圾回收有bug，这里必须手动delete，否则内存会炸
                            else:
                                del file_data
                                break
                except OSError:
                    conn.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 3\r\n\r\n404")
        except Exception as e:
            print("Unhandled exception in miniWebServer: ", e)
        finally:
            del request
            conn.close()

    def run(self, host="127.0.0.1", port=8080):
        """运行服务器"""
        print(self.route_map)
        address = socket.getaddrinfo(host, port)[0][-1]
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(address)  # ('0.0.0.0', 80)
        sock.listen(5)
        print("Running on http://%s:%d/" % (host, port))
        while True:
            try:
                conn, address = sock.accept()  # TODO: fix OSError: [Errno 113] ECONNABORTED
                print("New connection:", address)
            except OSError as e:
                print("Exception in sock.accept():", e)
                continue
            if ENABLE_MULTITHREAD:
                _thread.start_new_thread(self.handle_request, (conn, address))
            else:
                self.handle_request(conn, address)


def redirect(path, code=302):
    return "", code, {"Location": path}


def jsonify(data):
    return json.dumps(data), 200, [("Content-Type", "application/json")]


if __name__ == '__main__':
    app = WebServer(__name__)


    @app.route("/500")
    def test_500(request):
        a = 0 / 0
        return a


    @app.route("/200", methods=["GET", "POST", "PUT"])
    def test_200(request):
        request.print()
        return "hello"


    @app.route("/json", methods=["GET", "POST", "PUT"])
    def test_json(request):
        request.print()
        return jsonify({"msg": "hello"})


    app.run(host="0.0.0.0", port=8080)
