from __future__ import print_function, absolute_import, unicode_literals
import os, sys
from attr import attrs, attrib
from zope.interface import implementer
from twisted.internet import defer
from ._interfaces import IWormhole
from .util import bytes_to_hexstr
from .timing import DebugTiming
from .journal import ImmediateJournal
from ._boss import Boss, WormholeError

# We can provide different APIs to different apps:
# * Deferreds
#   w.when_got_code().addCallback(print_code)
#   w.send(data)
#   w.receive().addCallback(got_data)
#   w.close().addCallback(closed)

# * delegate callbacks (better for journaled environments)
#   w = wormhole(delegate=app)
#   w.send(data)
#   app.wormhole_got_code(code)
#   app.wormhole_got_verifier(verifier)
#   app.wormhole_receive(data)
#   w.close()
#   app.wormhole_closed()
#
# * potential delegate options
#   wormhole(delegate=app, delegate_prefix="wormhole_",
#            delegate_args=(args, kwargs))

def _log(client_name, machine_name, old_state, input, new_state):
    print("%s.%s[%s].%s -> [%s]" % (client_name, machine_name,
                                    old_state, input, new_state))

@attrs
@implementer(IWormhole)
class _DelegatedWormhole(object):
    _delegate = attrib()

    def _set_boss(self, boss):
        self._boss = boss

    # from above

    def allocate_code(self, code_length=2):
        self._boss.allocate_code(code_length)
    def input_code(self, stdio):
        self._boss.input_code(stdio)
    def set_code(self, code):
        self._boss.set_code(code)

    def send(self, plaintext):
        self._boss.send(plaintext)
    def close(self):
        self._boss.close()

    def debug_set_trace(self, client_name, which="B N M S O K R RC NL C T",
                           logger=_log):
        self._boss.set_trace(client_name, which, logger)

    # from below
    def got_code(self, code):
        self._delegate.wormhole_got_code(code)
    def got_verifier(self, verifier):
        self._delegate.wormhole_got_verifier(verifier)
    def received(self, plaintext):
        self._delegate.wormhole_received(plaintext)
    def closed(self, result):
        self._delegate.wormhole_closed(result)

class WormholeClosed(Exception):
    pass

@implementer(IWormhole)
class _DeferredWormhole(object):
    def __init__(self):
        self._code = None
        self._code_observers = []
        self._verifier = None
        self._verifier_observers = []
        self._received_data = []
        self._received_observers = []
        self._closed_observers = []

    def _set_boss(self, boss):
        self._boss = boss

    # from above
    def when_code(self):
        if self._code:
            return defer.succeed(self._code)
        d = defer.Deferred()
        self._code_observers.append(d)
        return d

    def when_verifier(self):
        if self._verifier:
            return defer.succeed(self._verifier)
        d = defer.Deferred()
        self._verifier_observers.append(d)
        return d

    def when_received(self):
        if self._received_data:
            return defer.succeed(self._received_data.pop(0))
        d = defer.Deferred()
        self._received_observers.append(d)
        return d

    def allocate_code(self, code_length=2):
        self._boss.allocate_code(code_length)
    def input_code(self, stdio):
        self._boss.input_code(stdio)
    def set_code(self, code):
        self._boss.set_code(code)

    def send(self, plaintext):
        self._boss.send(plaintext)
    def close(self):
        self._boss.close()
        d = defer.Deferred()
        self._closed_observers.append(d)
        return d

    def debug_set_trace(self, client_name, which="B N M S O K R RC NL C T",
                           logger=_log):
        self._boss._set_trace(client_name, which, logger)

    # from below
    def got_code(self, code):
        self._code = code
        for d in self._code_observers:
            d.callback(code)
        self._code_observers[:] = []
    def got_verifier(self, verifier):
        self._verifier = verifier
        for d in self._verifier_observers:
            d.callback(verifier)
        self._verifier_observers[:] = []

    def received(self, plaintext):
        if self._received_observers:
            self._received_observers.pop(0).callback(plaintext)
            return
        self._received_data.append(plaintext)

    def closed(self, result):
        print("closed", result, type(result))
        if isinstance(result, WormholeError):
            e = result
        else:
            e = WormholeClosed(result)
        for d in self._verifier_observers:
            d.errback(e)
        for d in self._received_observers:
            d.errback(e)
        for d in self._closed_observers:
            d.callback(result)

def _wormhole(appid, relay_url, reactor, delegate=None,
              tor_manager=None, timing=None,
              journal=None,
              stderr=sys.stderr,
              ):
    timing = timing or DebugTiming()
    side = bytes_to_hexstr(os.urandom(5))
    journal = journal or ImmediateJournal()
    if delegate:
        w = _DelegatedWormhole(delegate)
    else:
        w = _DeferredWormhole()
    b = Boss(w, side, relay_url, appid, reactor, journal, timing)
    w._set_boss(b)
    # force allocate for now
    b.start()
    return w

def delegated_wormhole(appid, relay_url, reactor, delegate,
                       tor_manager=None, timing=None,
                       journal=None,
                       stderr=sys.stderr,
                       ):
    assert delegate
    return _wormhole(appid, relay_url, reactor, delegate,
                     tor_manager, timing, journal, stderr)

def deferred_wormhole(appid, relay_url, reactor,
                       tor_manager=None, timing=None,
                       journal=None,
                       stderr=sys.stderr,
                       ):
    return _wormhole(appid, relay_url, reactor, None,
                     tor_manager, timing, journal, stderr)
