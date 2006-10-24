import py, errno
from pypy.module.rsocket.rsocket import *
from pypy.module.rsocket.rsocket import _c

def test_ipv4_addr():
    a = INETAddress("localhost", 4000)
    assert a.get_host() == "127.0.0.1"
    assert a.get_port() == 4000
    a = INETAddress("", 4001)
    assert a.get_host() == "0.0.0.0"
    assert a.get_port() == 4001
    a = INETAddress("<broadcast>", 47002)
    assert a.get_host() == "255.255.255.255"
    assert a.get_port() == 47002
    py.test.raises(GAIError, INETAddress, "no such host exists", 47003)
    res = repr(a)
    assert res == "<INETAddress 255.255.255.255:47002>"

def test_unix_addr():
    a = UNIXAddress("/tmp/socketname")
    assert a.get_path() == "/tmp/socketname"

def test_gethostname():
    s = gethostname()
    assert isinstance(s, str)

def test_gethostbyname():
    a = gethostbyname('localhost')
    assert isinstance(a, INETAddress)
    assert a.get_host() == "127.0.0.1"

def test_socketpair():
    s1, s2 = socketpair()
    s1.send('?')
    buf = s2.recv(100)
    assert buf == '?'
    count = s2.send('x'*99)
    assert 1 <= count <= 99
    buf = s1.recv(100)
    assert buf == 'x'*count
    s1.close()
    s2.close()

def test_simple_tcp():
    import thread
    sock = RSocket()
    try_ports = [1023] + range(20000, 30000, 437)
    for port in try_ports:
        print 'binding to port %d:' % (port,),
        try:
            sock.bind(INETAddress('127.0.0.1', port))
            print 'works'
            break
        except SocketError, e:   # should get a "Permission denied"
            print e
    else:
        raise e

    addr = INETAddress('127.0.0.1', port)
    assert addr.eq(sock.getsockname())
    sock.listen(1)
    s2 = RSocket(_c.AF_INET, _c.SOCK_STREAM)
    thread.start_new_thread(s2.connect, (addr,))
    s1, addr2 = sock.accept()
    assert addr.eq(s2.getpeername())
    assert addr2.eq(s2.getsockname())
    assert addr2.eq(s1.getpeername())

    s1.send('?')
    buf = s2.recv(100)
    assert buf == '?'
    thread.start_new_thread(s2.sendall, ('x'*500000,))
    buf = ''
    while len(buf) < 500000:
        data = s1.recv(500100)
        assert data
        buf += data
    assert buf == 'x'*500000
    s1.close()
    s2.close()

def test_simple_udp():
    s1 = RSocket(_c.AF_INET, _c.SOCK_DGRAM)
    try_ports = [1023] + range(20000, 30000, 437)
    for port in try_ports:
        print 'binding to port %d:' % (port,),
        try:
            s1.bind(INETAddress('127.0.0.1', port))
            print 'works'
            break
        except SocketError, e:   # should get a "Permission denied"
            print e
    else:
        raise e

    addr = INETAddress('127.0.0.1', port)
    assert addr.eq(s1.getsockname())
    s2 = RSocket(_c.AF_INET, _c.SOCK_DGRAM)
    s2.connect(addr)
    addr2 = s2.getsockname()

    s1.sendto('?', 0, addr2)
    buf = s2.recv(100)
    assert buf == '?'
    count = s2.send('x'*99)
    assert 1 <= count <= 99
    buf, addr3 = s1.recvfrom(100)
    assert buf == 'x'*count
    assert addr3.eq(addr2)
    s1.close()
    s2.close()

def test_nonblocking():
    sock = RSocket()
    sock.setblocking(False)
    try_ports = [1023] + range(20000, 30000, 437)
    for port in try_ports:
        print 'binding to port %d:' % (port,),
        try:
            sock.bind(INETAddress('127.0.0.1', port))
            print 'works'
            break
        except SocketError, e:   # should get a "Permission denied"
            print e
    else:
        raise e

    addr = INETAddress('127.0.0.1', port)
    assert addr.eq(sock.getsockname())
    sock.listen(1)
    err = py.test.raises(CSocketError, sock.accept)
    assert err.value.errno in (errno.EAGAIN, errno.EWOULDBLOCK)

    s2 = RSocket(_c.AF_INET, _c.SOCK_STREAM)
    s2.setblocking(False)
    err = py.test.raises(CSocketError, s2.connect, addr)
    assert err.value.errno == errno.EINPROGRESS

    s1, addr2 = sock.accept()
    s1.setblocking(False)
    assert addr.eq(s2.getpeername())
    assert addr2.eq(s2.getsockname())
    assert addr2.eq(s1.getpeername())

    err = s2.connect_ex(addr)   # should now work
    assert err in (0, errno.EISCONN)

    s1.send('?')
    buf = s2.recv(100)
    assert buf == '?'
    err = py.test.raises(CSocketError, s1.recv, 5000)
    assert err.value.errno == errno.EAGAIN
    count = s2.send('x'*500000)
    assert 1 <= count <= 500000
    buf = s1.recv(500100)
    assert buf == 'x'*count
    s1.close()
    s2.close()

def test_getaddrinfo_http():
    lst = getaddrinfo('localhost', 'http')
    assert isinstance(lst, list)
    found = False
    for family, socktype, protocol, canonname, addr in lst:
        if (family          == _c.AF_INET and
            socktype        == _c.SOCK_STREAM and
            addr.get_host() == '127.0.0.1' and
            addr.get_port() == 80):
            found = True
    assert found, lst

def test_getaddrinfo_snake():
    lst = getaddrinfo('snake.cs.uni-duesseldorf.de', None)
    assert isinstance(lst, list)
    found = False
    for family, socktype, protocol, canonname, addr in lst:
        if addr.get_host() == '134.99.112.214':
            found = True
    assert found, lst

def test_connect_ex():
    s = RSocket()
    err = s.connect_ex(s.getsockname())   # should not work
    assert err in (errno.ECONNREFUSED, errno.EADDRNOTAVAIL)


def test_getsetsockopt():
    # A socket sould start with reuse == 0
    s = RSocket(_c.AF_INET, _c.SOCK_STREAM)
    reuse = s.getsockopt_int(_c.SOL_SOCKET, _c.SO_REUSEADDR)
    assert reuse == 0
    s.setsockopt_int(_c.SOL_SOCKET, _c.SO_REUSEADDR, 1)
    reuse = s.getsockopt_int(_c.SOL_SOCKET, _c.SO_REUSEADDR)
    assert reuse != 0
    # Test string case
    s = RSocket(_c.AF_INET, _c.SOCK_STREAM)
    reusestr = s.getsockopt(_c.SOL_SOCKET, _c.SO_REUSEADDR, sizeof(_c.c_int))
    reuseptr = _c.cast(_c.c_char_p(reusestr), _c.POINTER(_c.c_int))
    assert reuseptr[0] == 0
    optval = _c.c_int(1)
    optvalp = _c.cast(_c.pointer(optval), _c.POINTER(_c.c_char))
    optstr = optvalp[:sizeof(_c.c_int)]
    s.setsockopt(_c.SOL_SOCKET, _c.SO_REUSEADDR, optstr)
    reusestr = s.getsockopt(_c.SOL_SOCKET, _c.SO_REUSEADDR, sizeof(_c.c_int))
    reuseptr = _c.cast(_c.c_char_p(reusestr), _c.POINTER(_c.c_int))
    assert reuseptr[0] != 0

def test_dup():
    s = RSocket(_c.AF_INET, _c.SOCK_STREAM)
    s.setsockopt_int(_c.SOL_SOCKET, _c.SO_REUSEADDR, 1)
    s.bind(INETAddress('localhost', 50007))
    s2 = s.dup()
    assert s.fileno() != s2.fileno()
    assert s.getsockname().eq(s2.getsockname())
    
class TestTCP:
    PORT = 50007
    HOST = 'localhost'

    def setup_method(self, method):
        self.serv = RSocket(_c.AF_INET, _c.SOCK_STREAM)
        self.serv.setsockopt_int(_c.SOL_SOCKET, _c.SO_REUSEADDR, 1)
        self.serv.bind(INETAddress(self.HOST, self.PORT))
        self.serv.listen(1)

    def teardown_method(self, method):
        self.serv.close()
        self.serv = None

    def test_timeout(self):
        def raise_timeout():
            self.serv.settimeout(1.0)
            self.serv.accept()
        py.test.raises(SocketTimeout, raise_timeout)

    def test_timeout_zero(self):
        def raise_error():
            self.serv.settimeout(0.0)
            foo = self.serv.accept()
        py.test.raises(SocketError, raise_error)

