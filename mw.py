from __future__ import print_function
from noodles.middleware.middleware import BaseMiddleware
from gevent.lock import BoundedSemaphore as Semaphore
import json,datetime
class Logger(BaseMiddleware):
    def __init__(self,link):
        self._sem = Semaphore(1)
        self.link = link
        
    def run(self,producer,request):

        import gevent.monkey, gevent.socket
        #gevent.monkey.patch_all()
        import socket

        assert socket.socket is gevent.socket.socket, "gevent monkey patch has not occurred"
        
        self._sem.acquire()
        try:
            print(json.dumps([datetime.datetime.now().isoformat(),
                      request.remote_addr,
                      request.method,
                      request.path,
                      request.headers.get('Authorization')]))
        finally:
            self._sem.release()
            pass
        return self.link(producer,request)
